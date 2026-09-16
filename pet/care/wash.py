"""Le bain : on frotte à l'éponge, puis on rince au spray (lot L15).

Le nettoyage passait par un objet qu'on posait et que le robot venait chercher :
la jauge montait toute seule, et le geste de l'utilisateur s'arrêtait au clic.
Ce module le remplace par un **rituel en deux temps**, dans l'esprit de
Nintendogs — on frotte jusqu'à ce que tout soit couvert, puis on rince.

**Pourquoi une grille plutôt qu'un compteur.** Un simple « frotter pendant huit
secondes » se satisfait d'un tremblement sur place ; il ne demande pas de
regarder le robot. La grille impose de le **parcourir**, donc de le voir. C'est
la même différence qu'entre remplir une barre et nettoyer quelque chose.

**La grille est masquée par la silhouette.** Les cases qui tombent hors du robot
— les coins de sa boîte, le vide entre ses jambes — ne comptent pas. Sans ce
masque, un bain ne se terminerait qu'en frottant du vide, et le §12 interdit de
faire perdre l'utilisateur sur une règle qu'il ne peut pas voir.

**Les distances sont en largeurs de robot, corrigées de l'aspect.** La zone de
frottement doit être **ronde à l'écran** ; en coordonnées normalisées, où `v`
couvre une hauteur et `u` une largeur, un cercle deviendrait un ovale sur un
robot élancé. `aspect` remet les deux axes à la même échelle.

Rien ici ne connaît Qt, ni le GPU, ni la fenêtre : `scrub` et `aim` reçoivent
des coordonnées normalisées, et c'est la couture de `pet/app/parts/wash.py` qui
les leur fournit.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# Les trois temps. `DONE` est terminal : une fois dedans, plus rien ne bouge.
SPONGE = "sponge"
SPRAY = "spray"
DONE = "done"

# Découpe de la silhouette. Plus haute que large, comme le robot.
#
# **Réglée au rendu, pas au jugé.** En 6 × 8, seules 14 cases sur 48 tombaient
# sur un robot de morphologie courante : la boîte de rendu est nettement plus
# large que la silhouette, et le bain se terminait en trois coups d'éponge sans
# qu'on ait eu à regarder où l'on passait. En 8 × 10 il en reste une trentaine,
# ce qui demande d'en faire le tour.
GRID_COLS = 8
GRID_ROWS = 10

# Rayon de l'éponge, en largeurs de robot. Calé sur l'objet qu'on tient : le
# sprite fait environ 0,39 largeur de robot, donc un rayon de 0,17 correspond à
# peu près à sa moitié. Exiger une précision supérieure à la taille de l'éponge
# serait une punition déguisée ; beaucoup plus large, on nettoie sans viser.
SCRUB_RADIUS = 0.17

# Mousse. Deux flocons par case, petits : la mousse doit se lire comme de la
# mousse, c'est-à-dire un amas de bulles, et non comme un nuage posé sur le
# robot. Les gros ronds de la première version cachaient le visage, qui est
# précisément ce qu'on regarde.
FOAM_PER_CELL = 3
FOAM_MAX = 200
FOAM_RADIUS = (0.026, 0.050)

# Dispersion d'un flocon autour du centre de sa case, en parts de la case. Bornée
# court : un flocon jeté à une demi-case déborde de la silhouette sur les cases
# de bord, et de la mousse flottant à côté du robot se voit tout de suite.
FOAM_JITTER = 0.32

# Durées d'apparition et de disparition d'un flocon, en secondes.
FOAM_GROW = 0.16
FOAM_FADE = 0.55

# Rinçage. Quatre jets, comme demandé, avec un délai entre deux : sans lui, un
# passage rapide devant le robot en déclencherait quatre dans la même seconde et
# le rinçage se jouerait sans qu'on l'ait vu.
SPRAY_COUNT = 4
SPRAY_INTERVAL = 0.62

# Portée du spray, en largeurs de robot, entre son centre et celui du robot.
# « Quand on n'est pas loin » : assez large pour ne pas avoir à viser, assez
# courte pour qu'on ait le sentiment de l'avoir approché.
SPRAY_RANGE = 0.95

# Délai d'armement à l'entrée dans la portée. Il évite le jet parti au moment
# précis où l'on saisit l'objet, avant même d'avoir bougé.
SPRAY_ARM = 0.16


@dataclass
class Foam:
    """Un flocon de mousse, en coordonnées normalisées du robot.

    Il n'a ni vitesse ni chute : la mousse **colle**. C'est ce qui la distingue
    des particules du lot L11, qui vivent en coordonnées écran et tombent.
    """

    u: float
    v: float
    r: float
    age: float = 0.0
    fade: float = 1.0

    @property
    def scale(self) -> float:
        """Apparition élastique, dans l'esprit du §10 : rien n'apparaît à sa
        taille finale."""
        if self.age >= FOAM_GROW:
            return 1.0
        part = self.age / FOAM_GROW
        return 1.0 - (1.0 - part) * (1.0 - part)


class Wash:
    """Le rituel du bain, du premier coup d'éponge au dernier jet.

    `aspect` est la hauteur du robot divisée par sa largeur. `mask` dit quelles
    cases tombent sur lui ; `None` les accepte toutes, ce qui est la bonne
    réponse quand la silhouette n'est pas encore connue — un bain impossible
    vaudrait bien pire qu'un bain trop facile.
    """

    def __init__(self, aspect: float = 1.3,
                 mask: tuple[bool, ...] | None = None,
                 seed: int = 0) -> None:
        self.aspect = max(0.2, float(aspect))
        self.state = SPONGE
        self.sprays = 0
        self.foam: list[Foam] = []

        self._rng = random.Random(seed)
        self._covered: set[int] = set()
        self._rinsing = False
        self._range_seconds = 0.0
        self._since_spray = 0.0

        if mask is None:
            self._valid = frozenset(range(GRID_COLS * GRID_ROWS))
        else:
            self._valid = frozenset(i for i, ok in enumerate(mask) if ok)
        if not self._valid:
            # Une silhouette vide — frame pas encore rendue, robot hors écran —
            # ne doit pas donner un bain qu'on ne peut pas finir.
            self._valid = frozenset(range(GRID_COLS * GRID_ROWS))

    # -- lecture -------------------------------------------------------------

    @property
    def progress(self) -> float:
        """Part de la silhouette déjà frottée, dans [0, 1]."""
        return len(self._covered) / float(len(self._valid))

    @property
    def scrubbed(self) -> bool:
        return len(self._covered) >= len(self._valid)

    @property
    def done(self) -> bool:
        return self.state == DONE

    @property
    def rinsing(self) -> bool:
        """La mousse est en train de partir : on ne frotte plus, on regarde."""
        return self._rinsing

    def cell_center(self, index: int) -> tuple[float, float]:
        """Centre d'une case, en coordonnées normalisées."""
        col, row = index % GRID_COLS, index // GRID_COLS
        return ((col + 0.5) / GRID_COLS, (row + 0.5) / GRID_ROWS)

    # -- éponge --------------------------------------------------------------

    def scrub(self, u: float, v: float) -> int:
        """Passe l'éponge en (u, v). Rend le nombre de cases nouvellement faites.

        Sans effet dès que la mousse s'en va : continuer à frotter pendant que
        le rinçage part remettrait de la mousse sur un robot déjà propre.
        """
        if self.state != SPONGE or self._rinsing:
            return 0

        faites = 0
        for index in self._valid:
            if index in self._covered:
                continue
            cu, cv = self.cell_center(index)
            if self._distance(u, v, cu, cv) > SCRUB_RADIUS:
                continue
            self._covered.add(index)
            faites += 1
            self._mousser(index)

        if faites and self.scrubbed:
            # Tout est couvert : la mousse part d'elle-même, et c'est cette
            # disparition qui fait passer au spray. Enchaîner sur-le-champ
            # priverait l'utilisateur du seul moment où il voit son travail.
            self._rinsing = True
        return faites

    def _mousser(self, index: int) -> None:
        cu, cv = self.cell_center(index)
        for _ in range(FOAM_PER_CELL):
            if len(self.foam) >= FOAM_MAX:
                return
            self.foam.append(Foam(
                u=cu + self._rng.uniform(-FOAM_JITTER, FOAM_JITTER) / GRID_COLS,
                v=cv + self._rng.uniform(-FOAM_JITTER, FOAM_JITTER) / GRID_ROWS,
                r=self._rng.uniform(*FOAM_RADIUS),
            ))

    def _distance(self, u: float, v: float, cu: float, cv: float) -> float:
        """Distance en largeurs de robot, corrigée de l'aspect (cf. l'entête)."""
        return math.hypot(u - cu, (v - cv) * self.aspect)

    # -- spray ---------------------------------------------------------------

    def aim(self, u: float, v: float, dt: float) -> bool:
        """Approche le spray en (u, v). Rend `True` quand un jet part.

        Le robot est visé depuis **son centre** et non depuis la case la plus
        proche : on rince un robot, on ne rince pas une case.
        """
        if self.state != SPRAY:
            return False

        if self._distance(u, v, 0.5, 0.5) > SPRAY_RANGE:
            self._range_seconds = 0.0
            return False

        self._range_seconds += dt
        self._since_spray += dt
        if self._range_seconds < SPRAY_ARM:
            return False
        if self._since_spray < SPRAY_INTERVAL:
            return False

        self._since_spray = 0.0
        self.sprays += 1
        if self.sprays >= SPRAY_COUNT:
            self.state = DONE
        return True

    # -- temps ---------------------------------------------------------------

    def step(self, dt: float) -> None:
        """Avance la mousse, et fait passer de l'éponge au spray."""
        if self.state == DONE and not self.foam:
            return

        partie = self._rinsing or self.state != SPONGE
        for flocon in self.foam:
            flocon.age += dt
            if partie:
                flocon.fade = max(0.0, flocon.fade - dt / FOAM_FADE)
        if partie:
            self.foam = [f for f in self.foam if f.fade > 0.0]

        if self.state == SPONGE and self._rinsing and not self.foam:
            self.state = SPRAY
            self._rinsing = False
            self._since_spray = SPRAY_INTERVAL      # le premier jet ne se fait
            self._range_seconds = 0.0               # pas attendre deux fois

    def abandon(self) -> None:
        """Le bain s'arrête là où il en est. Ce qui a été fait reste acquis."""
        self.state = DONE
        self._rinsing = True

    # -- valeur du soin ------------------------------------------------------

    def credit(self) -> float:
        """Part du soin méritée, dans [0, 1].

        Un bain interrompu à mi-chemin **vaut la moitié** plutôt que rien : le
        §12 interdit de punir, et perdre son kit pour avoir été dérangé serait
        exactement cela. L'éponge pèse les deux tiers — c'est le geste long — et
        le rinçage le tiers restant.
        """
        if self.state == DONE and self.sprays >= SPRAY_COUNT:
            return 1.0
        return min(1.0, 0.66 * self.progress
                   + 0.34 * (self.sprays / float(SPRAY_COUNT)))
