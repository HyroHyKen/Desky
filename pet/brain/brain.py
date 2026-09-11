"""Le tick de comportement du CDC §12, et rien de plus.

Assemble l'économie de besoins, la liste d'actions et l'élection, et leur
ajoute la seule chose qu'aucune des trois ne porte : le **temps**. Trois
mécanismes de durée cohabitent, et ils répondent à trois défauts différents :

- l'**hystérésis** de `utility` empêche deux scores voisins d'alterner à chaque
  tick de 250 ms ;
- le **plancher** `min_seconds` empêche une action de ne durer que trois ticks
  quand un besoin franchit un seuil, ce que l'hystérésis ne couvre pas ;
- le **plafond** `max_seconds`, suivi d'un repos forcé, empêche une action à
  score élevé et stable de monopoliser le pet — un `bored_slump` à `fun` nul
  battrait sinon toutes les ambiances indéfiniment.

Aucun import de `anim`, `render` ou Qt : ce module se teste sans GPU, et un test
du lot L6 le vérifie en sous-processus.
"""

from __future__ import annotations

from .actions import default_actions
from .needs import CARE_COOLDOWN, CARE_GAINS, Needs
from .utility import RECENCY_FULL, Action, Candidate, Plan, SelfState, elect

# Période imposée par le §12. Le `brain` ne la lit pas lui-même — il reçoit un
# `dt` — mais c'est elle qui cadence l'appelant, et les durées d'action sont
# choisies en multiples lisibles de cette valeur.
TICK = 0.25

# Rapport entre le repos forcé et le plafond de l'action qui l'a déclenché.
REST_RATIO = 1.6


class Brain:
    """Décide, et n'exécute rien.

    Le résultat de `update` est un `Plan` : des noms de courbe, d'expression et
    d'intention de déplacement. C'est l'appelant qui les résout, ce qui garde la
    cloison du §5 et rend une journée entière rejouable sans fenêtre.
    """

    def __init__(self, needs: Needs | None = None,
                 actions: list[Action] | None = None) -> None:
        self.needs = needs if needs is not None else Needs()
        self.actions = actions if actions is not None else default_actions()
        self._by_name = {a.name: a for a in self.actions}

        self.current = ""
        self.plan = Plan("idle_wander", travel="wander")
        self.elapsed = 0.0
        self.changes = 0
        self.candidates: list[Candidate] = []

        # Les actions démarrent « anciennes » : au premier tick, le bonus de
        # nouveauté est plein pour toutes, donc l'élection se joue sur les
        # scores et non sur un ordre d'initialisation.
        self.since = {a.name: RECENCY_FULL for a in self.actions}
        self._rest: dict[str, float] = {}
        self._cooldowns: dict[str, float] = {}
        self._poke = 1e9
        self._cheer = 1e9
        self._prev_state = ""

    # --- événements d'interface ------------------------------------------

    def poke(self) -> None:
        """Le pet a été cliqué. L'appelant signale un clic, pas un âge."""
        self._poke = 0.0

    def cheer(self) -> None:
        self._cheer = 0.0

    def cooldown(self, kind: str) -> float:
        """Secondes restantes avant de pouvoir resservir ce soin."""
        return max(0.0, self._cooldowns.get(kind, 0.0))

    def can_care(self, kind: str) -> bool:
        return kind in CARE_GAINS and self.cooldown(kind) <= 0.0

    def care(self, kind: str) -> dict[str, float]:
        """Applique un soin s'il est disponible. Retourne les deltas réels.

        Un soin refusé retourne un dictionnaire vide plutôt que de lever : le
        §12 interdit les notifications punitives, et un bouton grisé dit déjà
        tout ce qu'il y a à dire.

        C'est le chemin direct, celui de la caresse. Les soins qui passent par
        un objet posé sur le bureau se font en deux temps, ci-dessous.
        """
        if not self.start_care(kind):
            return {}
        return self.deliver_care(kind)

    def start_care(self, kind: str) -> bool:
        """Réserve un soin : pose le délai **sans** appliquer le gain.

        Sépare l'intention de son effet, ce qu'exige le soin par objet : le
        délai doit courir dès qu'on fait apparaître l'objet — sinon rien
        n'empêche d'en semer dix —, alors que le besoin ne monte qu'au moment
        où le robot le rejoint.
        """
        if not self.can_care(kind):
            return False
        self._cooldowns[kind] = CARE_COOLDOWN[kind]
        return True

    def deliver_care(self, kind: str) -> dict[str, float]:
        """Applique le gain d'un soin déjà réservé."""
        applied = self.needs.care(kind)
        if applied:
            self.cheer()
        return applied

    def refund_care(self, kind: str) -> None:
        """Annule le délai d'un soin qui n'a pas abouti.

        Un objet que le robot n'a jamais rejoint s'évapore, et faire payer
        l'utilisateur pour ça serait une punition — que le §12 interdit.
        """
        self._cooldowns.pop(kind, None)

    # --- humeur ----------------------------------------------------------

    @property
    def expression(self) -> str:
        """Visage à afficher : celui de l'action, sinon celui de l'humeur."""
        return self.plan.expression or self.needs.mood()

    # --- tick ------------------------------------------------------------

    def update(self, dt: float, ctx, me: SelfState) -> Plan:
        dt = max(0.0, float(dt))
        self.needs.tick(getattr(ctx, "state", ""), dt)
        self._advance(dt)

        # Retour de l'utilisateur après une absence : décision §17.4, il dort
        # pendant `away` et fête son retour.
        state = getattr(ctx, "state", "")
        if self._prev_state == "away" and state != "away":
            self.cheer()
        self._prev_state = state

        me.poke_seconds = self._poke
        me.cheer_seconds = self._cheer

        held = self._by_name.get(self.current)
        if held is not None and self.current not in self._rest:
            if self.elapsed < held.min_seconds and not self._reflex_waiting(ctx, me):
                if held.is_available(self.needs, ctx, me):
                    self.since[self.current] = 0.0
                    return self.plan

        chosen, self.candidates = elect(
            self.actions, self.needs, ctx, me, self.current, self.since,
            blocked=frozenset(self._rest),
        )
        if chosen is None:
            return self.plan

        if chosen.name != self.current:
            self.current = chosen.name
            self.plan = chosen.plan()
            self.elapsed = 0.0
            self.changes += 1
        self.since[self.current] = 0.0
        return self.plan

    def _reflex_waiting(self, ctx, me: SelfState) -> bool:
        """Un réflexe autre que l'action en cours attend-il son tour ?

        C'est la seule dérogation au plancher de durée. Elle est nécessaire :
        un clic ou un soin reçu pendant une sieste, dont le plancher fait six
        secondes, ne serait sinon célébré qu'une éternité plus tard.
        """
        for action in self.actions:
            if not action.reflex or action.name == self.current:
                continue
            if action.name in self._rest:
                continue
            if action.is_available(self.needs, ctx, me):
                return True
        return False

    def _advance(self, dt: float) -> None:
        self._poke += dt
        self._cheer += dt
        self.elapsed += dt
        for name in self.since:
            self.since[name] += dt

        for table in (self._cooldowns, self._rest):
            for key in list(table):
                table[key] -= dt
                if table[key] <= 0.0:
                    del table[key]

        held = self._by_name.get(self.current)
        if held is not None and held.max_seconds > 0.0:
            if self.elapsed >= held.max_seconds:
                self._rest[held.name] = held.max_seconds * REST_RATIO
