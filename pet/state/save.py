"""Persistance atomique et journalisation (CDC §14).

Emplacement : `%LOCALAPPDATA%\\Desky\\`, contenant `settings.json` (lot L1),
puis `pet.json` (génome, lot L2), `state.json` (besoins et tokens, lot L7) et
`debug.log`.

Deux exigences du CDC gouvernent ce module :

- **Écritures atomiques.** On écrit dans un fichier temporaire du même
  répertoire, on force l'écriture sur disque, puis `os.replace()`. C'est ce qui
  permet de survivre à un kill brutal du process : à tout instant, le fichier
  visible est soit l'ancienne version complète, soit la nouvelle, jamais un
  tronçon.
- **Pas de chiffrement, pas de signature.** Le CDC §14 le dit explicitement :
  l'application est gratuite, hors-ligne et sans classement, donc un utilisateur
  qui édite son JSON ne lèse personne. Un champ de version et une validation de
  bornes au chargement suffisent, et c'est tout ce qu'on fait ici.

Le journal ne contient que des **catégories** : jamais un titre de fenêtre,
jamais une URL, jamais une frappe (CDC §11).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .. import APP_NAME

log = logging.getLogger("desky.state")


def app_dir() -> Path:
    """`%LOCALAPPDATA%\\<AppName>\\`, créé si absent."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Écrit `data` en JSON de façon atomique.

    Le fichier temporaire est créé dans le répertoire cible, et non dans le
    répertoire temporaire du système : `os.replace()` n'est atomique que sur un
    même volume.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())          # sans ça, replace peut précéder l'écriture
        os.replace(tmp, path)
    except BaseException:
        # Ne jamais laisser de temporaire derrière soi, y compris sur KeyboardInterrupt.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, attempts: int = 4, delay: float = 0.04) -> dict[str, Any] | None:
    """Lit un JSON, ou None si absent, illisible ou corrompu.

    Réessaie brièvement en cas d'erreur d'accès. Mesuré au lot L1 : après un
    `os.replace()`, Windows peut refuser l'ouverture du fichier pendant quelques
    millisecondes — antivirus, indexeur, ou la fin du MoveFileEx lui-même. Sans
    ces tentatives, un démarrage tombant dans cette fenêtre repartirait sur les
    valeurs par défaut et l'utilisateur perdrait la position de son pet.

    Un JSON syntaxiquement invalide, lui, n'est **pas** réessayé : l'écriture
    étant atomique, on ne peut pas observer un fichier à moitié écrit, donc une
    erreur de syntaxe signifie une vraie corruption ou une édition manuelle
    ratée. Le pet repart alors sur ses défauts plutôt que de refuser de démarrer.
    """
    last: OSError | None = None
    for attempt in range(attempts):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            log.warning("%s corrompu, retour aux valeurs par défaut", path.name)
            return None
        except OSError as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(delay)
                continue
            log.warning("%s inaccessible après %d tentatives : %s",
                        path.name, attempts, type(exc).__name__)
            return None
        else:
            return data if isinstance(data, dict) else None
    return None


def sweep_temp_files() -> int:
    """Efface les temporaires d'écriture laissés par un arrêt brutal.

    Un process tué n'exécute aucun nettoyage : mesuré au lot L1, 8 kills en
    pleine écriture laissent 7 fichiers `.tmp` derrière eux. Sans ce balayage,
    le répertoire de données accumulerait un résidu à chaque crash — ce que
    l'exigence de désinstallation sans résidu du CDC §16 n'admet pas.

    Appelé au démarrage, où le mutex d'instance unique garantit qu'aucune autre
    instance n'est en train d'écrire.
    """
    removed = 0
    for f in app_dir().glob("*.tmp"):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        log.info("%d temporaire(s) d'un arrêt précédent effacé(s)", removed)
    return removed


class Store:
    """Document JSON versionné, avec validation de bornes au chargement.

    `validate` reçoit le dictionnaire chargé et retourne une version corrigée.
    Il doit **borner** plutôt que rejeter : une valeur hors plage vient soit
    d'une édition manuelle, soit d'une migration ratée, et dans les deux cas le
    pet doit démarrer.
    """

    def __init__(
        self,
        filename: str,
        schema_version: int,
        defaults: dict[str, Any],
        validate: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        migrate: Callable[[dict[str, Any], int], dict[str, Any]] | None = None,
    ) -> None:
        self.path = app_dir() / filename
        self.schema_version = schema_version
        self._defaults = defaults
        self._validate = validate
        self._migrate = migrate
        self.data: dict[str, Any] = dict(defaults)
        self._dirty = False

    def load(self) -> None:
        raw = read_json(self.path)
        if raw is None:
            self.data = dict(self._defaults)
            self._dirty = True                     # écrira au premier save
            log.info("aucun %s, valeurs par défaut", self.path.name)
            return

        found = int(raw.get("schema_version", 0))
        if found != self.schema_version and self._migrate is not None:
            log.info("migration de %s : schéma %d -> %d",
                     self.path.name, found, self.schema_version)
            raw = self._migrate(raw, found)

        merged = dict(self._defaults)
        merged.update(raw)
        merged["schema_version"] = self.schema_version
        self.data = self._validate(merged) if self._validate else merged

    def set(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if self.data.get(k) != v:
                self.data[k] = v
                self._dirty = True

    def save(self, force: bool = False) -> bool:
        """Écrit si nécessaire. Retourne True si une écriture a eu lieu."""
        if not (self._dirty or force):
            return False
        self.data["schema_version"] = self.schema_version
        write_json_atomic(self.path, self.data)
        self._dirty = False
        return True


# --- Journalisation ---------------------------------------------------------


def setup_logging(verbose: bool = False) -> Path:
    """Configure le journal dans `%LOCALAPPDATA%\\<AppName>\\debug.log`.

    Rotation à 256 Ko sur 2 fichiers : un journal de bureau qui grossit sans
    limite est un défaut en soi. Rien de sensible n'y transite (CDC §11) — les
    capteurs du lot L5 n'exposeront que des catégories.
    """
    path = app_dir() / "debug.log"
    root = logging.getLogger("desky")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=256 * 1024, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-14s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root.addHandler(handler)

    if verbose:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("[log] %(name)-14s %(message)s"))
        root.addHandler(console)

    return path


def purge_data() -> list[str]:
    """Supprime toutes les données locales (CDC §13, bouton de purge).

    Retourne la liste des fichiers effacés. Implémenté ici plutôt qu'au lot L7
    pour que l'exigence « la purge est effective » soit vérifiable dès que des
    fichiers existent.
    """
    removed = []
    d = app_dir()
    for f in d.glob("*.tmp"):
        try:
            f.unlink()
            removed.append(f.name)
        except OSError:
            pass
    for name in ("settings.json", "pet.json", "state.json", "debug.log", "debug.log.1"):
        f = d / name
        if f.exists():
            try:
                f.unlink()
                removed.append(name)
            except OSError as exc:
                log.warning("purge impossible pour %s : %s", name, type(exc).__name__)
    return removed


# --- Document de réglages (lot L1) ------------------------------------------

SETTINGS_SCHEMA = 1

# Bornes de la taille de rendu : proposition du CDC §17.1, décision ouverte.
SIZE_MIN, SIZE_MAX = 120, 400

SETTINGS_DEFAULTS: dict[str, Any] = {
    "schema_version": SETTINGS_SCHEMA,
    "size": 220,
    # Position mémorisée par identifiant de moniteur (CDC §6). Stockée en
    # fraction de la zone de travail et en écart au sol, et non en pixels
    # absolus : la position reste juste après un changement de résolution.
    #   { "<clé moniteur>": {"x_frac": 0.0-1.0, "floor_gap": px} }
    "positions": {},
    "last_monitor": "",
}


def _validate_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Borne les valeurs au chargement. Ne rejette jamais (CDC §14)."""
    try:
        data["size"] = max(SIZE_MIN, min(SIZE_MAX, int(data.get("size", 220))))
    except (TypeError, ValueError):
        data["size"] = 220

    positions = data.get("positions")
    clean: dict[str, dict[str, float]] = {}
    if isinstance(positions, dict):
        for key, pos in positions.items():
            if not isinstance(key, str) or not isinstance(pos, dict):
                continue
            try:
                clean[key] = {
                    "x_frac": max(0.0, min(1.0, float(pos.get("x_frac", 0.5)))),
                    "floor_gap": max(0, min(4000, int(pos.get("floor_gap", 0)))),
                }
            except (TypeError, ValueError):
                continue
    data["positions"] = clean

    if not isinstance(data.get("last_monitor"), str):
        data["last_monitor"] = ""
    return data


def settings_store() -> Store:
    return Store(
        "settings.json",
        schema_version=SETTINGS_SCHEMA,
        defaults=SETTINGS_DEFAULTS,
        validate=_validate_settings,
    )


def close_logging() -> None:
    """Ferme les handlers du journal et libère `debug.log`.

    Nécessaire pour que la purge puisse supprimer le fichier, et pour qu'un test
    puisse nettoyer son répertoire temporaire : sous Windows, un fichier encore
    ouvert n'est pas supprimable.
    """
    root = logging.getLogger("desky")
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)


# --- Document du génome (lot L2) --------------------------------------------
#
# Ce module connaît les documents qu'il persiste, donc il importe leur schéma.
# La dépendance ne va que dans ce sens : `genome` ignore `state`, il n'y a donc
# pas de cycle.


def genome_store() -> Store:
    """Document `pet.json` : le génome, en valeurs explicites (CDC §7).

    La graine y figure à titre de trace, mais ce ne sont **pas** elle qui décide
    de la morphologie au chargement : ce sont les valeurs. Régénérer depuis la
    graine ferait dériver le robot d'un utilisateur existant dès que l'ordre de
    tirage change.
    """
    from ..genome.migration import migrate
    from ..genome.schema import SCHEMA_VERSION, clamp_genome, defaults

    return Store(
        "pet.json",
        schema_version=SCHEMA_VERSION,
        defaults={"schema_version": SCHEMA_VERSION, "seed": 0, "attempts": 0, **defaults()},
        validate=clamp_genome,
        migrate=migrate,
    )


def load_or_create_genome() -> tuple[dict[str, Any], bool]:
    """Charge le génome, ou en tire un nouveau au premier lancement.

    Retourne `(génome, créé)`. `créé` vaut True au tout premier démarrage, ce que
    l'appelant peut utiliser pour une étape d'accueil — cf. la décision ouverte
    du CDC §17.5 sur le nom donné par l'utilisateur.
    """
    from ..genome.generator import generate, new_seed

    store = genome_store()
    existing = read_json(store.path)
    if existing is None:
        seed = new_seed()
        genome = generate(seed)
        store.data = dict(genome)
        store.save(force=True)
        log.info("génome créé (graine %d, %d tirage(s))", seed, genome.get("attempts", 1))
        return store.data, True

    store.load()
    log.info("génome chargé (graine %s)", store.data.get("seed"))
    return store.data, False


# --- Document d'état vivant (lot L6) ----------------------------------------

STATE_SCHEMA = 1

# Le §14 place dans `state.json` « besoins, tokens, inventaire ». Les deux
# derniers appartiennent au lot L7 : les champs sont déclarés vides pour que
# leur arrivée soit une migration additive, comme pour le génome.
STATE_DEFAULTS: dict[str, Any] = {
    "schema_version": STATE_SCHEMA,
    # Niveaux de satisfaction dans [0, 100]. Les valeurs de départ sont celles
    # de `brain.needs.Needs` ; elles sont recopiées ici plutôt qu'importées pour
    # que `state` ne dépende pas du `brain`.
    "needs": {"hunger": 70.0, "fun": 70.0, "energy": 80.0, "hygiene": 80.0},
    # Horloge murale du dernier enregistrement, pour la décroissance hors
    # ligne. Zéro signifie « jamais vu », donc aucune décroissance à appliquer.
    "last_seen": 0.0,
    # Délais de soin restants, en secondes. Persistés pour qu'un
    # redémarrage ne les remette pas à zéro — non par méfiance, le §14 étant
    # explicite là-dessus, mais parce qu'un délai qui s'évapore à la fermeture
    # est un bug, pas une politique.
    "cooldowns": {},
    # Nom donné au premier lancement, définitif (phase B du lot L6).
    "name": "",
    # Apparence choisie par l'utilisateur, **superposée** au génome sans le
    # muter : le génome reste le trait de naissance, ceci est un costume. Vide
    # signifie « celle de naissance ». Seules les couleurs sont modifiables
    # sans token pour le moment ; la boutique du lot L7 étendra ce même
    # dictionnaire, sans nouveau mécanisme.
    "appearance": {},
    "tokens": 0,
    # Meilleurs scores par jeu (lot L12). Un dictionnaire plutôt qu'un champ
    # par jeu : le second jeu ne doit pas demander de migration de schéma.
    "best_scores": {},
    # Quota quotidien du §14 : le jour en cours et ce qui y a déjà été gagné.
    # Persistés avec le solde, sinon fermer l'application rouvrirait le quota.
    "tokens_day": "",
    "tokens_today": 0,
    "inventory": [],
}


def _validate_state(data: dict[str, Any]) -> dict[str, Any]:
    """Borne les valeurs au chargement. Ne rejette jamais (CDC §14)."""
    needs = data.get("needs")
    clean: dict[str, float] = {}
    defaults = STATE_DEFAULTS["needs"]
    for key, fallback in defaults.items():
        value = needs.get(key, fallback) if isinstance(needs, dict) else fallback
        try:
            clean[key] = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            clean[key] = float(fallback)
    data["needs"] = clean

    try:
        seen = float(data.get("last_seen", 0.0))
    except (TypeError, ValueError):
        seen = 0.0
    # Une date future vient d'une horloge qui a reculé depuis. La ramener à
    # maintenant évite une durée d'absence négative en aval (§14).
    data["last_seen"] = max(0.0, min(seen, time.time()))

    cooldowns = data.get("cooldowns")
    kept: dict[str, float] = {}
    if isinstance(cooldowns, dict):
        for key, value in cooldowns.items():
            if not isinstance(key, str):
                continue
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                continue
            if seconds > 0.0:
                kept[key] = min(seconds, 86400.0)
    data["cooldowns"] = kept

    name = data.get("name")
    data["name"] = name.strip()[:24] if isinstance(name, str) else ""

    data["appearance"] = _validate_appearance(data.get("appearance"))

    try:
        data["tokens"] = max(0, int(data.get("tokens", 0)))
    except (TypeError, ValueError):
        data["tokens"] = 0

    jour = data.get("tokens_day")
    data["tokens_day"] = jour if isinstance(jour, str) else ""
    try:
        data["tokens_today"] = max(0, int(data.get("tokens_today", 0)))
    except (TypeError, ValueError):
        data["tokens_today"] = 0

    # L'inventaire ne garde que des articles **existants** : une clé inconnue
    # viendrait d'une édition manuelle ou d'une version plus récente, et
    # afficher un article qu'on ne sait pas dessiner serait pire que l'oublier.
    from ..geometry.cosmetics import BY_KEY
    inventory = data.get("inventory")
    data["inventory"] = (sorted({str(i) for i in inventory} & set(BY_KEY))
                         if isinstance(inventory, list) else [])
    return data


# Paramètres de génome que l'utilisateur peut choisir, et leurs valeurs
# autorisées. Déclaré ici plutôt que déduit : un `overrides` qui accepterait
# n'importe quelle clé du génome laisserait un fichier édité à la main changer
# les proportions du robot, ce qui n'est pas une personnalisation mais un autre
# robot.
from ..geometry.cosmetics import SLOTS as _COSMETIC_SLOTS

CUSTOMISABLE = ("palette.body", "palette.accent") + _COSMETIC_SLOTS


def _validate_appearance(raw: Any) -> dict[str, str]:
    """Ne garde que des choix connus. Ignore le reste sans se plaindre."""
    from ..genome.schema import ACCENT_COLORS, BODY_COLORS
    from ..geometry.cosmetics import NONE, SLOTS, by_slot

    autorise = {
        "palette.body": set(BODY_COLORS),
        "palette.accent": set(ACCENT_COLORS),
    }
    for emplacement in SLOTS:
        # « Rien » est un choix, pas une absence : il doit pouvoir être
        # enregistré pour qu'on puisse retirer ce qu'on porte.
        autorise[emplacement] = {c.key for c in by_slot(emplacement)} | {NONE}
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for cle in CUSTOMISABLE:
        valeur = raw.get(cle)
        if isinstance(valeur, str) and valeur in autorise[cle]:
            out[cle] = valeur
    return out


def state_store() -> Store:
    return Store(
        "state.json",
        schema_version=STATE_SCHEMA,
        defaults=STATE_DEFAULTS,
        validate=_validate_state,
    )
