"""Le `brain` et son fichier d'état, réunis.

Ajoute au `Brain` les trois choses qui relèvent d'une session et non d'une
décision : le chargement, la **décroissance hors ligne**, et l'enregistrement
périodique que le §14 fixe à soixante secondes plus la fermeture propre.

Le §5 interdit au `brain` de connaître `render` et `anim`. Dépendre de `state`
est en revanche normal et voulu : c'est le seul endroit du `brain` qui touche un
fichier, ce qui laisse tout le reste — besoins, actions, élection — testable sans
disque.
"""

from __future__ import annotations

import logging
import time

from ..state import save
from . import achievements, consumables
from .brain import Brain
from .economy import Economy
from .needs import Needs, offline_elapsed
from .utility import Plan, SelfState

log = logging.getLogger("desky.brain")

# Période d'enregistrement imposée par le §14.
SAVE_SECONDS = 60.0

# État attribué au temps passé hors ligne. L'application fermée, l'utilisateur
# n'était pas devant son pet : `away` est la seule lecture honnête, et c'est
# aussi celle qui laisse `energy` remonter — un pet retrouvé reposé.
OFFLINE_STATE = "away"


class Session:
    """Cycle de vie du comportement : charger, décider, enregistrer."""

    def __init__(self, store: save.Store | None = None,
                 clock=time.time) -> None:
        self.store = store if store is not None else save.state_store()
        self.clock = clock
        self.brain = Brain()
        self.economy = Economy()
        self._since_save = 0.0
        self.offline_seconds = 0.0

    # --- chargement -------------------------------------------------------

    def load(self) -> None:
        self.store.load()
        data = self.store.data
        self.brain = Brain(Needs.from_dict(data.get("needs", {})))
        self.economy = Economy.from_dict(data)

        # Date de naissance (lot L22). Absente des sauvegardes d'avant les
        # trophées : on la rattrape une fois, sur le plus vieux repère
        # disponible, plutôt que de faire naître aujourd'hui un robot qu'on a
        # depuis trois mois.
        if self.born_at <= 0.0:
            naissance = save.estimate_birth(self.clock())
            self.store.set(born_at=round(naissance, 3))
            log.info("date de naissance estimee : %.0f", naissance)
        self._rattraper_les_compteurs()
        self.mark_day()

        cooldowns = data.get("cooldowns") or {}
        elapsed = offline_elapsed(self.clock(), float(data.get("last_seen", 0.0)))
        self.offline_seconds = elapsed

        if elapsed > 0.0:
            before = self.brain.needs.as_dict()
            self.brain.needs.tick(OFFLINE_STATE, elapsed)
            log.info("absence facturee %.1f h, besoins %s -> %s",
                     elapsed / 3600.0, before, self.brain.needs.as_dict())

        # Les délais de soin s'écoulent aussi pendant l'absence, et sur la durée
        # **réelle** : le plafond de huit heures protège les besoins de
        # l'utilisateur, pas les délais qui, eux, ne peuvent que se réduire.
        real = max(0.0, self.clock() - float(data.get("last_seen", 0.0)))
        for kind, seconds in cooldowns.items():
            try:
                left = float(seconds) - real
            except (TypeError, ValueError):
                continue
            if left > 0.0:
                self.brain._cooldowns[kind] = left

    # --- trophées (lot L22) -----------------------------------------------

    @property
    def born_at(self) -> float:
        return float(self.store.data.get("born_at", 0.0) or 0.0)

    @property
    def stats(self) -> dict[str, float]:
        brut = self.store.data.get("stats") or {}
        return {str(k): float(v) for k, v in brut.items()
                if isinstance(v, (int, float))}

    def bump(self, mesure: str, combien: float = 1.0) -> float:
        """Ajoute au compteur. Retourne sa nouvelle valeur.

        N'enregistre pas : les compteurs suivent les gestes de l'utilisateur, et
        écrire sur disque à chaque poussée du doigt serait une écriture toutes
        les deux secondes. L'enregistrement périodique du §14 les emporte, et
        `unlock` force la main dès qu'un trophée tombe — c'est-à-dire au seul
        moment où perdre le compteur se verrait.
        """
        compteurs = dict(self.stats)
        valeur = max(0.0, compteurs.get(mesure, 0.0) + float(combien))
        compteurs[mesure] = valeur
        self.store.set(stats=compteurs)
        return valeur

    def _rattraper_les_compteurs(self) -> None:
        """Ce que la sauvegarde **prouve** déjà, pour les robots d'avant (L22).

        Les trophées arrivent après des semaines d'usage : sans ce rattrapage,
        un utilisateur qui a baptisé son robot, joué, gagné et acheté verrait
        une page entièrement grise, y compris sur des choses qu'il a
        manifestement faites. Le §12 interdit de punir ; effacer un passé qu'on
        peut lire dans le fichier en serait une forme discrète.

        **Chaque ligne est une déduction, pas une estimation.** Un nom ne
        s'obtient qu'en baptisant, un record ne s'inscrit qu'en jouant, un
        accessoire ne s'ajoute à l'inventaire qu'en l'achetant. Ce qui ne se
        démontre pas — combien de repas, combien de bains — reste à zéro, et
        c'est la bonne réponse : mieux vaut un compteur en retard qu'un compteur
        inventé.

        Ne s'exécute que tant qu'aucun compteur n'existe, donc une seule fois
        dans la vie d'une sauvegarde.
        """
        if self.stats:
            return
        if self.name:
            self.record_stat(achievements.BAPTEME, 1.0)
        scores = self.store.data.get("best_scores") or {}
        if scores:
            # Un record inscrit veut dire au moins une partie finie, et au
            # moins un record battu.
            self.record_stat(achievements.PARTIES, float(len(scores)))
            self.record_stat(achievements.RECORDS, float(len(scores)))
        possedes = len(self.inventory)
        if possedes:
            self.record_stat(achievements.ACHATS, float(possedes))
        # Le solde est un **plancher** de ce qui a été gagné : ce qui a déjà été
        # dépensé n'est écrit nulle part.
        if self.economy.tokens > 0:
            self.record_stat(achievements.JETONS, float(self.economy.tokens))

    def set_stat(self, mesure: str, valeur: float) -> float:
        """Pose la valeur d'un compteur. Pour ce qui se remet à zéro."""
        compteurs = dict(self.stats)
        compteurs[mesure] = max(0.0, float(valeur))
        self.store.set(stats=compteurs)
        return compteurs[mesure]

    def record_stat(self, mesure: str, valeur: float) -> float:
        """Garde le **maximum** atteint. Pour ce qui se bat, pas ce qui s'ajoute."""
        compteurs = dict(self.stats)
        valeur = max(compteurs.get(mesure, 0.0), float(valeur))
        compteurs[mesure] = valeur
        self.store.set(stats=compteurs)
        return valeur

    def mark_day(self, when: float | None = None) -> bool:
        """Compte une journée de présence. Rend `True` si elle est nouvelle.

        Le repère est la date **locale** et non un multiple de 86 400 secondes :
        une journée commence à minuit chez l'utilisateur, pas à minuit UTC.
        """
        from datetime import date

        quand = self.clock() if when is None else float(when)
        try:
            jour = float(date.fromtimestamp(quand).toordinal())
        except (OverflowError, OSError, ValueError):
            return False
        if self.stats.get("jour_dernier", 0.0) == jour:
            return False
        self.record_stat("jour_dernier", jour)
        self.bump(achievements.JOURS_VUS, 1)
        return True

    @property
    def achievements(self) -> dict[str, float]:
        """Trophées obtenus, `clé -> date`."""
        brut = self.store.data.get("achievements") or {}
        return {str(k): float(v) for k, v in brut.items()
                if k in achievements.BY_KEY}

    @property
    def claimed(self) -> list[str]:
        return list(self.store.data.get("claimed") or [])

    def mesures(self, when: float | None = None) -> dict[str, float]:
        """Les compteurs, plus les mesures qu'on lit ailleurs.

        L'âge, les records et le nombre d'accessoires ne sont pas accumulés :
        ils existent déjà sous une autre forme, et en tenir une copie donnerait
        deux vérités dont l'une finirait périmée.
        """
        quand = self.clock() if when is None else float(when)
        out = dict(self.stats)
        naissance = self.born_at
        out[achievements.AGE] = (max(0.0, quand - naissance) / 86400.0
                                 if naissance > 0.0 else 0.0)
        out[achievements.RALLY] = float(self.best_score("rally"))
        out[achievements.CUPS] = float(self.best_score("cups"))
        out[achievements.ACCESSOIRES] = float(len(self.inventory))
        return out

    def check_achievements(self, when: float | None = None) -> list[str]:
        """Débloque ce qui doit l'être. Retourne les clés **nouvelles**.

        Ne verse rien : la récompense s'encaisse depuis la page des trophées,
        d'un geste de l'utilisateur. Débloquer et réclamer sont séparés parce
        que des jetons qui tombent tout seuls pendant qu'on travaille ne se
        remarquent pas, et un trophée qu'on n'a pas vu passer n'en est pas un.
        """
        quand = self.clock() if when is None else float(when)
        deja = self.achievements
        neufs = [cle for cle in achievements.obtenus(self.mesures(quand))
                 if cle not in deja]
        if not neufs:
            return []
        deja.update({cle: round(quand, 3) for cle in neufs})
        self.store.set(achievements=deja)
        # Forcé : un trophée obtenu qu'un plantage effacerait serait la seule
        # perte vraiment irréparable de ce fichier, puisqu'un premier bain ne se
        # refait pas.
        self.flush(force=True)
        return neufs

    def claimable(self) -> list[str]:
        """Trophées obtenus dont la récompense attend, dans l'ordre du catalogue."""
        encaisses = set(self.claimed)
        obtenus = self.achievements
        return [cle for cle in achievements.ORDRE
                if cle in obtenus and cle not in encaisses]

    def claim(self, cle: str) -> int:
        """Encaisse la récompense d'un trophée. Retourne les jetons versés.

        Hors plafond quotidien, et une seule fois : le second appel rend zéro
        plutôt que de lever, parce qu'un double-clic sur un bouton n'est pas une
        faute à signaler.
        """
        if cle not in self.achievements or cle in self.claimed:
            return 0
        gain = self.economy.grant(achievements.recompense(cle))
        self.store.set(claimed=sorted(set(self.claimed) | {cle}))
        self.flush(force=True)
        return gain

    # --- économie ---------------------------------------------------------

    @property
    def tokens(self) -> int:
        return self.economy.tokens

    @property
    def tokens_remaining(self) -> int:
        """Ce qui peut encore être gagné aujourd'hui (§14)."""
        return self.economy.remaining

    @property
    def inventory(self) -> list[str]:
        return list(self.store.data.get("inventory") or [])

    def award_tokens(self, amount: int = 1) -> int:
        """Verse un gain de soin. Retourne ce qui a **réellement** été versé.

        Écrit tout de suite : un token gagné qu'un plantage annulerait serait
        plus irritant que pas de token du tout.
        """
        avant = self.economy.remaining
        gagne = self.economy.award(amount)
        if gagne:
            self.bump(achievements.JETONS, gagne)
            # Le plafond vient d'être atteint. Le repérer à la **transition**
            # plutôt qu'à l'état suffit à ne le compter qu'une fois par jour :
            # `today` repart de zéro à chaque bascule de journée, donc le
            # passage de « il reste quelque chose » à « il ne reste rien » n'a
            # lieu qu'une fois.
            if avant > 0 and self.economy.remaining == 0:
                self.bump(achievements.JOURS_PLEINS, 1)
            self.flush(force=True)
        return gagne

    def owns(self, key: str) -> bool:
        return key in self.inventory

    def buy(self, key: str) -> bool:
        """Achète un article. Définitif : on ne revend rien.

        L'achat et le port sont deux gestes séparés — acheter met dans
        l'inventaire, porter écrit dans `appearance` — pour qu'on puisse
        posséder plusieurs chapeaux et en changer sans repayer.
        """
        from ..geometry.cosmetics import BY_KEY

        article = BY_KEY.get(key)
        if article is None or self.owns(key):
            return False
        if not self.economy.spend(article.price):
            return False
        self.store.set(inventory=sorted(set(self.inventory) | {key}))
        self.flush(force=True)
        return True

    @property
    def appearance(self) -> dict[str, str]:
        """Costume choisi, à passer tel quel en `overrides` à `build`."""
        return dict(self.store.data.get("appearance") or {})

    def wear(self, slot: str, key: str) -> bool:
        """Porte un article possédé sur cet emplacement, ou rien.

        L'emplacement est passé explicitement plutôt que déduit de l'article :
        retirer ce qu'on porte se fait avec une clé vide, qui n'appartient à
        aucun emplacement, et il faut bien savoir lequel on libère.
        """
        from ..geometry.cosmetics import NONE, SLOTS, slot_of

        if slot not in SLOTS:
            return False
        if key == NONE:
            return self.set_appearance(slot, NONE)
        if not self.owns(key) or slot_of(key) != slot:
            return False
        return self.set_appearance(slot, key)

    def worn(self, slot: str) -> str:
        """Article porté sur cet emplacement, ou chaîne vide."""
        return str(self.appearance.get(slot, ""))

    def set_appearance(self, param: str, value: str) -> bool:
        """Change un élément d'apparence. Retourne True si quelque chose a bougé.

        Écrit tout de suite : un choix visuel qu'un plantage annulerait serait
        pire que pas de choix du tout.
        """
        if param not in save.CUSTOMISABLE:
            return False
        courant = self.appearance
        if courant.get(param) == value:
            return False
        courant[param] = value
        nettoye = save._validate_appearance(courant)
        if nettoye.get(param) != value:
            return False
        self.store.set(appearance=nettoye)
        self.flush(force=True)
        return True

    @property
    def name(self) -> str:
        return str(self.store.data.get("name", ""))

    def set_name(self, name: str) -> bool:
        """Baptise le pet. Refuse si un nom existe déjà : il est définitif."""
        clean = " ".join(str(name).split())[:24]
        if not clean or self.name:
            return False
        self.store.set(name=clean)
        self.flush(force=True)
        return True

    # --- tick -------------------------------------------------------------

    def update(self, dt: float, ctx, me: SelfState) -> Plan:
        plan = self.brain.update(dt, ctx, me)
        self._since_save += max(0.0, float(dt))
        if self._since_save >= SAVE_SECONDS:
            self.flush()
        return plan

    def care(self, kind: str) -> dict[str, float]:
        applied = self.brain.care(kind)
        if applied:
            self.flush(force=True)
        return applied

    def start_care(self, kind: str) -> bool:
        """Réserve un soin. Enregistré aussitôt : le délai doit survivre à un
        plantage, sinon fermer l'application remettrait tous les compteurs à
        zéro."""
        if not self.brain.start_care(kind):
            return False
        self.flush(force=True)
        return True

    def deliver_care(self, kind: str) -> dict[str, float]:
        applied = self.brain.deliver_care(kind)
        if applied:
            self.flush(force=True)
        return applied

    def refund_care(self, kind: str) -> None:
        self.brain.refund_care(kind)
        self.flush(force=True)

    # --- enregistrement ---------------------------------------------------

    # -- consommables (lot L13) ---------------------------------------------

    @property
    def consumables(self) -> dict[str, int]:
        """Quantités possédées, clé par clé. Les zéros n'y figurent pas.

        Les articles retirés du catalogue sont convertis ici comme ils le sont
        au chargement (`consumables.RETIRED`), et les clés inconnues écartées :
        l'inventaire ne doit contenir que des choses qu'on sait dessiner et
        utiliser. Le faire des deux côtés n'est pas une redite — la sauvegarde
        normalise le fichier une fois, cette propriété protège la session d'un
        `store.set` direct.
        """
        brut = self.store.data.get("consumables") or {}
        out: dict[str, int] = {}
        for cle, nombre in brut.items():
            try:
                quantite = int(nombre)
            except (TypeError, ValueError):
                continue
            if quantite <= 0:
                continue
            cle = consumables.RETIRED.get(str(cle), str(cle))
            if cle not in consumables.BY_KEY:
                continue
            out[cle] = out.get(cle, 0) + quantite
        return out

    def count(self, key: str) -> int:
        return self.consumables.get(key, 0)

    def buy_consumable(self, key: str, quantity: int = 1) -> bool:
        """Achète `quantity` exemplaires. Rend `False` si le solde ne suffit pas.

        Tout ou rien : acheter trois gamelles avec de quoi en payer deux ne doit
        pas en livrer deux et prendre l'argent des trois.
        """
        article = consumables.get(key)
        if article is None or quantity < 1:
            return False
        if not self.economy.spend(article.price * quantity):
            return False
        stock = dict(self.consumables)
        stock[key] = stock.get(key, 0) + quantity
        self.store.set(consumables=stock)
        return True

    def use_consumable(self, key: str) -> bool:
        """Retire un exemplaire du stock. Rend `False` s'il n'y en a plus.

        Ne l'applique pas : c'est la fenêtre qui décide **comment** — posé sur
        le bureau et rejoint, ou appliqué sur-le-champ. Le stock, lui, se décide
        ici et nulle part ailleurs.
        """
        stock = dict(self.consumables)
        if stock.get(key, 0) < 1:
            return False
        stock[key] -= 1
        if stock[key] <= 0:
            del stock[key]
        self.store.set(consumables=stock)
        return True

    def apply_consumable(self, key: str, factor: float = 1.0) -> dict[str, float]:
        """Applique l'effet d'un consommable **déjà retiré du stock**.

        Séparé de `use_consumable` parce que les deux moments ne coïncident
        pas : un article posé sur le bureau quitte le stock tout de suite — sans
        quoi on en sèmerait dix — mais n'agit qu'une fois le robot arrivé. La
        pile, elle, fait les deux dans la même seconde.

        `factor` sert aux articles à rituel (lot L15) : un bain interrompu à
        mi-chemin rend la moitié du soin. C'est un **facteur** et non un gain
        libre, pour que le catalogue reste la seule source de ce que vaut un
        article — un appelant ne doit pas pouvoir décider qu'un kit rend 300.
        """
        article = consumables.get(key)
        if article is None:
            return {}
        part = max(0.0, min(1.0, float(factor)))
        applied = self.brain.needs.apply({article.need: article.gain * part})
        if applied:
            self.flush(force=True)
        return applied

    def refund_consumable(self, key: str) -> None:
        """Rend un exemplaire. Pour l'objet posé puis jamais rejoint.

        Le §12 interdit de punir : un objet qui s'évapore parce que le robot
        n'y est pas allé ne doit pas coûter l'article.
        """
        if consumables.get(key) is None:
            return
        stock = dict(self.consumables)
        stock[key] = stock.get(key, 0) + 1
        self.store.set(consumables=stock)

    # -- scores de jeu (lot L12) --------------------------------------------

    def best_score(self, jeu: str) -> int:
        """Meilleur score enregistré pour ce jeu. Zéro si jamais joué."""
        scores = self.store.data.get("best_scores") or {}
        try:
            return max(0, int(scores.get(jeu, 0)))
        except (TypeError, ValueError):
            return 0

    def record_score(self, jeu: str, score: int) -> bool:
        """Enregistre un score. Rend `True` s'il s'agit d'un nouveau record.

        Écrit **seulement** quand le record tombe : une partie ratée n'a aucune
        raison de provoquer une écriture disque, et le §14 demande que la
        persistance reste sobre.
        """
        score = max(0, int(score))
        if score <= self.best_score(jeu):
            return False
        scores = dict(self.store.data.get("best_scores") or {})
        scores[jeu] = score
        self.store.set(best_scores=scores)
        return True

    def flush(self, force: bool = False) -> bool:
        self._since_save = 0.0
        self.store.set(
            needs=self.brain.needs.as_dict(),
            last_seen=round(self.clock(), 3),
            cooldowns={k: round(v, 1) for k, v in self.brain._cooldowns.items()},
            **self.economy.as_dict(),
        )
        return self.store.save(force=force)
