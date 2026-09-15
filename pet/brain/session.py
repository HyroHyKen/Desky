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
        gagne = self.economy.award(amount)
        if gagne:
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
