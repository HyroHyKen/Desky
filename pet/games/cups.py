"""Le jeu des trois gobelets (lot L14).

Pur, comme le ballon : aucune ligne ici ne sait ce qu'est une fenêtre. Une
partie entière se déroule au pas de temps synthétique, ce qui permet de la
tester — y compris de vérifier que le robot finit bien sous le gobelet que le
mélange dit, ce qui est la seule chose que ce jeu doit garantir absolument.

**Deux repères, et il faut les tenir séparés.** Une *position* est un des trois
emplacements fixes sur le bureau ; un *gobelet* est un objet qui se déplace
entre eux. Le joueur clique une position, le robot est caché sous un gobelet, et
c'est la correspondance entre les deux qui change à chaque permutation. Les
confondre donne un jeu qui marche presque — et qui désigne le mauvais gobelet
une fois sur trois.

**La difficulté monte sur deux axes**, comme demandé : à chaque manche réussie,
une permutation de plus et des permutations plus rapides. Les deux sont
plafonnés : au-delà, le mélange cesse d'être un jeu d'attention pour devenir un
tirage au sort, et perdre à pile ou face n'apprend rien.

**Rien n'est aléatoire au moment du dévoilement.** Le tirage a lieu à la
préparation de la manche, la séquence est figée, et le déroulement ne fait que
la jouer. C'est ce qui rend la partie rejouable à l'identique en test, et ce qui
garantit qu'aucun arrondi de temps ne peut déplacer le robot en cours de route.
"""

from __future__ import annotations

import random

SLOTS = 3
MIDDLE = 1

# États d'une manche.
REVEAL = "reveal"              # gobelets levés, le robot est visible
COVERING = "covering"          # ils descendent
SHUFFLING = "shuffling"
CHOOSING = "choosing"          # au joueur
RESULT = "result"              # le gobelet choisi se soulève
OVER = "over"

# Durées fixes, en secondes.
REVEAL_SECONDS = 1.4           # le temps de bien voir où il est
COVER_SECONDS = 0.45
RESULT_SECONDS = 1.6

# Courbe de difficulté. Une permutation de plus par manche, et chacune plus
# rapide — mais les deux plafonnent : au-delà, le mélange devient un tirage au
# sort, et perdre à pile ou face n'apprend rien.
SWAPS_BASE = 3
SWAPS_PER_ROUND = 1
SWAPS_MAX = 9

SWAP_SECONDS = 0.55
SWAP_DECAY = 0.88
SWAP_SECONDS_MIN = 0.17

# Pause entre deux permutations. Nulle serait illisible — on ne verrait qu'un
# grouillement ; trop longue rendrait le mélange mou. Elle suit la vitesse.
SWAP_GAP_RATIO = 0.22


def swaps_for_round(round_index: int) -> int:
    return min(SWAPS_MAX, SWAPS_BASE + SWAPS_PER_ROUND * max(0, round_index))


def seconds_for_round(round_index: int) -> float:
    return max(SWAP_SECONDS_MIN,
               SWAP_SECONDS * (SWAP_DECAY ** max(0, round_index)))


class Cups:
    """Une partie : des manches, un score, et la place du robot.

    `on_round`, `on_wrong` et `on_end` sont des crochets pour la fenêtre — les
    règles n'ont pas à savoir qu'il existe des particules ni des animations.
    """

    __slots__ = ("cup_at", "robot_cup", "state", "score", "best", "round",
                 "_rng", "_t", "_plan", "_step_index", "_swap_seconds",
                 "picked", "on_round", "on_wrong", "on_end")

    def __init__(self, best: int = 0, seed: int | None = None) -> None:
        # Position **de chaque gobelet**. `cup_at[i]` est l'emplacement où se
        # trouve le gobelet `i` : c'est la moitié qui bouge.
        self.cup_at = list(range(SLOTS))
        # Gobelet sous lequel se trouve le robot. Il ne change **jamais** —
        # seule sa position change. C'est la séparation qui rend le jeu juste :
        # le robot n'est pas téléporté d'un gobelet à l'autre, il est transporté.
        self.robot_cup = MIDDLE
        self.state = REVEAL
        self.score = 0
        self.best = int(best)
        self.round = 0
        self.picked = -1
        self._rng = random.Random(seed)
        self._t = 0.0
        self._plan: list[tuple[int, int]] = []
        self._step_index = 0
        self._swap_seconds = SWAP_SECONDS
        self.on_round = None
        self.on_wrong = None
        self.on_end = None

    # -- lecture -------------------------------------------------------------

    @property
    def over(self) -> bool:
        return self.state == OVER

    @property
    def robot_slot(self) -> int:
        """Emplacement où se trouve réellement le robot."""
        return self.cup_at[self.robot_cup]

    @property
    def can_pick(self) -> bool:
        return self.state == CHOOSING

    @property
    def record(self) -> bool:
        return self.score > self.best

    @property
    def swap(self) -> tuple[int, int] | None:
        """Permutation en cours, en **emplacements**, ou `None`."""
        if self.state != SHUFFLING or self._step_index >= len(self._plan):
            return None
        return self._plan[self._step_index]

    @property
    def swap_progress(self) -> float:
        """Avancement de la permutation en cours, dans [0, 1]."""
        if self.state != SHUFFLING:
            return 0.0
        return min(1.0, self._t / max(1e-6, self._swap_seconds))

    def slot_of_cup(self, cup: int) -> int:
        return self.cup_at[cup]

    def cup_in_slot(self, slot: int) -> int:
        for cup, place in enumerate(self.cup_at):
            if place == slot:
                return cup
        return -1

    # -- déroulement ---------------------------------------------------------

    def _prepare(self) -> None:
        """Tire la séquence de la manche. **Une fois**, à l'avance.

        Tirer au fil du déroulement rendrait la partie irreproductible en test
        et, pire, laisserait le hasard intervenir après que le joueur a commencé
        à suivre le gobelet des yeux.
        """
        combien = swaps_for_round(self.round)
        self._swap_seconds = seconds_for_round(self.round)
        plan: list[tuple[int, int]] = []
        precedent: tuple[int, int] | None = None
        for _ in range(combien):
            while True:
                a, b = self._rng.sample(range(SLOTS), 2)
                paire = (min(a, b), max(a, b))
                # Jamais deux fois la même d'affilée : la refaire annule la
                # précédente, et le joueur voit un aller-retour qui n'apprend
                # rien tout en coûtant une permutation.
                if paire != precedent:
                    break
            plan.append(paire)
            precedent = paire
        self._plan = plan
        self._step_index = 0

    def step(self, dt: float) -> None:
        if self.state == OVER:
            return
        self._t += dt

        if self.state == REVEAL:
            if self._t >= REVEAL_SECONDS:
                self._t = 0.0
                self.state = COVERING
            return

        if self.state == COVERING:
            if self._t >= COVER_SECONDS:
                self._t = 0.0
                self._prepare()
                self.state = SHUFFLING
            return

        if self.state == SHUFFLING:
            duree = self._swap_seconds * (1.0 + SWAP_GAP_RATIO)
            if self._t < duree:
                return
            a, b = self._plan[self._step_index]
            # L'échange a lieu **à la fin** du mouvement, pas au début : c'est
            # ce qui fait que `robot_slot` dit toujours la vérité de ce qu'on
            # voit à l'écran.
            self._exchange(a, b)
            self._t = 0.0
            self._step_index += 1
            if self._step_index >= len(self._plan):
                self.state = CHOOSING
            return

        if self.state == RESULT:
            if self._t >= RESULT_SECONDS:
                self._t = 0.0
                if self.picked == self.robot_slot:
                    self._next_round()
                else:
                    self._finish()

    def _exchange(self, a: int, b: int) -> None:
        for cup, place in enumerate(self.cup_at):
            if place == a:
                self.cup_at[cup] = b
            elif place == b:
                self.cup_at[cup] = a

    def pick(self, slot: int) -> bool:
        """Le joueur désigne un emplacement. Rend `True` si le choix est pris."""
        if self.state != CHOOSING or not 0 <= slot < SLOTS:
            return False
        self.picked = slot
        self.state = RESULT
        self._t = 0.0
        if slot == self.robot_slot:
            self.score += 1
            if self.on_round is not None:
                self.on_round(self.score)
        elif self.on_wrong is not None:
            self.on_wrong(self.robot_slot)
        return True

    def _next_round(self) -> None:
        self.round += 1
        self.picked = -1
        # Le robot repart du milieu à chaque manche : voir où il est **avant**
        # le mélange fait partie du jeu, et le laisser là où la manche
        # précédente l'a mené donnerait un départ différent à chaque fois sans
        # rien apporter.
        self.cup_at = list(range(SLOTS))
        self.robot_cup = MIDDLE
        self.state = REVEAL
        self._t = 0.0

    def _finish(self) -> None:
        self.state = OVER
        if self.score > self.best:
            self.best = self.score
        if self.on_end is not None:
            self.on_end(self.score)

    def abandon(self) -> None:
        """Fin demandée de l'extérieur. Le score acquis compte (§12)."""
        if self.state != OVER:
            self._finish()
