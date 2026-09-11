"""Particules : poussière d'impact, étincelles de soin, sommeil (lot L11).

**Elles ne sont jamais gratuites.** Une particule qui n'est motivée par rien est
du bruit à l'écran, et sur un logiciel de bureau permanent le bruit se paie en
désinstallations. Chaque famille ici répond à un fait : le robot a atterri, un
soin a été accepté, un achat a été refusé, il dort. Le bus du lot L9 les fournit
tels quels, avec leur intensité.

**Elles ne connaissent ni Qt ni le rendu.** Ce module est de la donnée et de
l'intégration numérique ; la peinture est dans `ui/sparks`. C'est le même
partage qu'entre `anim/easing` et `ui/motion`, et pour la même raison : ce qui
calcule doit se tester sans écran.

**Aucune allocation par image.** Les tableaux sont alloués une fois et réutilisés
en place. Une liste d'objets qu'on crée et détruit trente fois par seconde fait
travailler le ramasse-miettes en continu sous une application censée tenir sous
4 % d'un cœur (§3) — et le coût ne se voit pas en profilant une seconde, il se
voit en regardant la consommation d'une journée.

Le budget est **fixe** : au-delà de `CAPACITY` particules vivantes, les nouvelles
sont refusées. Un plafond dur vaut mieux qu'un tableau qui grandit : le pire cas
est connu d'avance, et un défaut de réglage produit un effet pauvre plutôt
qu'une fuite de mémoire.
"""

from __future__ import annotations

import math
import random

import numpy as np

# Budget global. Une poussière d'atterrissage en consomme une douzaine, une
# gerbe d'étincelles une vingtaine : cent laisse de la marge pour deux effets
# simultanés sans jamais dépasser.
CAPACITY = 100

# Familles. Le nom est celui du **phénomène**, pas de l'événement qui le
# déclenche : la même poussière sert à un atterrissage et, plus tard, à un pas
# lourd, sans qu'il faille la renommer.
DUST = 0
SPARK = 1
SLEEP = 2
REFUS = 3

# Gravité appliquée aux particules, en fraction de hauteur de pet par seconde
# carrée. Exprimée relativement, comme tout le reste du produit : la taille de
# rendu est réglable de 120 à 400 px (§17.1) et la poussière doit retomber de la
# même façon aux deux extrêmes.
GRAVITY = {DUST: 1.5, SPARK: 1.1, SLEEP: -0.10, REFUS: 2.2}

# Frottement, par seconde. La poussière s'arrête vite — c'est de la matière
# soulevée, pas un projectile ; les étincelles gardent leur élan plus longtemps.
DRAG = {DUST: 3.4, SPARK: 1.2, SLEEP: 0.9, REFUS: 2.6}


class Particles:
    """Un banc de particules à budget fixe, en tableaux parallèles.

    Les tableaux parallèles plutôt qu'une liste d'objets : l'intégration se fait
    alors en quatre opérations numpy sur tout le banc, sans boucle Python. À
    cent particules la différence n'est pas décisive, mais la structure l'est —
    elle rend le coût indépendant du nombre de familles.
    """

    __slots__ = ("x", "y", "vx", "vy", "life", "life0", "size", "kind",
                 "alive", "_rng", "_n")

    def __init__(self, seed: int = 0) -> None:
        z = np.zeros(CAPACITY, dtype="f4")
        self.x, self.y = z.copy(), z.copy()
        self.vx, self.vy = z.copy(), z.copy()
        self.life, self.life0 = z.copy(), z.copy()
        self.size = z.copy()
        self.kind = np.zeros(CAPACITY, dtype="i2")
        self.alive = np.zeros(CAPACITY, dtype=bool)
        self._rng = random.Random(seed)
        self._n = 0

    # -- émission ------------------------------------------------------------

    def _free_slots(self, combien: int) -> np.ndarray:
        """Indices libres, au plus `combien`. Jamais de réallocation."""
        libres = np.flatnonzero(~self.alive)
        return libres[:combien]

    def burst(self, kind: int, x: float, y: float, count: int,
              speed: float, spread: float, life: float,
              size: float, up: float = 0.0, x_spread: float = 2.0,
              y_spread: float = 1.5) -> int:
        """Émet jusqu'à `count` particules. Rend le nombre réellement émis.

        Les positions et vitesses sont en **pixels de la fenêtre du pet** : le
        seul repère que la peinture connaisse. `spread` est le demi-angle, en
        radians, autour de l'horizontale ou de la verticale selon `up`.

        `x_spread` étale les points de **naissance**, ce qui n'est pas la même
        chose que `spread` qui ouvre les directions. Une gerbe née d'un point
        unique ressemble à une fontaine, ce qui convient à un jet mais pas à un
        halo : les étincelles de soin doivent naître **autour** du robot, sinon
        elles se superposent à son visage et se lisent comme un défaut d'image.
        """
        slots = self._free_slots(count)
        if slots.size == 0:
            return 0
        for i in slots:
            angle = self._rng.uniform(-spread, spread)
            v = speed * self._rng.uniform(0.55, 1.0)
            if up:
                # Gerbe vers le haut : l'angle s'écarte de la verticale.
                self.vx[i] = math.sin(angle) * v
                self.vy[i] = -math.cos(angle) * v * up
            else:
                # Poussière : elle part sur les côtés, à peine soulevée. Le
                # signe alterne pour que les deux côtés soient servis même sur
                # un petit nombre de particules.
                cote = 1.0 if self._rng.random() < 0.5 else -1.0
                self.vx[i] = cote * math.cos(angle) * v
                self.vy[i] = -abs(math.sin(angle)) * v * 0.7
            self.x[i] = x + self._rng.uniform(-x_spread, x_spread)
            self.y[i] = y + self._rng.uniform(-y_spread, y_spread)
            duree = life * self._rng.uniform(0.7, 1.15)
            self.life[i] = duree
            self.life0[i] = duree
            self.size[i] = size * self._rng.uniform(0.65, 1.25)
            self.kind[i] = kind
            self.alive[i] = True
        self._n = int(self.alive.sum())
        return int(slots.size)

    # -- intégration ---------------------------------------------------------

    def step(self, dt: float, pet_h: float, floor: float | None = None) -> bool:
        """Avance le banc. Rend `True` s'il reste quelque chose de vivant.

        `pet_h` convertit les constantes relatives en pixels : la gravité d'une
        poussière doit produire la même image sur un pet de 120 px et sur un de
        400.

        `floor` est l'ordonnée du sol, en pixels d'écran. Sans lui, la poussière
        **traverse le sol** : elle est soulevée au niveau des pieds, la gravité
        la tire vers le bas, et elle finit sa vie sous la ligne où le robot se
        tient. Ce n'est pas subtil — la gerbe a l'air de tomber dans un trou.
        Les familles qui montent (étincelles, sommeil) n'en ont pas besoin, mais
        le plancher ne leur coûte rien puisqu'elles ne l'atteignent jamais.
        """
        if not self._n:
            return False

        vivantes = self.alive
        self.life[vivantes] -= dt

        mortes = vivantes & (self.life <= 0.0)
        if mortes.any():
            self.alive[mortes] = False
            vivantes = self.alive

        if not vivantes.any():
            self._n = 0
            return False

        for famille, g in GRAVITY.items():
            masque = vivantes & (self.kind == famille)
            if not masque.any():
                continue
            self.vy[masque] += g * pet_h * dt
            frein = max(0.0, 1.0 - DRAG[famille] * dt)
            self.vx[masque] *= frein
            self.vy[masque] *= frein

        self.x[vivantes] += self.vx[vivantes] * dt
        self.y[vivantes] += self.vy[vivantes] * dt

        if floor is not None:
            # Au sol, la particule **glisse et s'arrête** au lieu de rebondir :
            # de la poussière ne rebondit pas, et un rebond ferait remarquer
            # chaque grain individuellement — exactement ce qu'une poussière ne
            # doit pas faire.
            posees = vivantes & (self.y > floor)
            if posees.any():
                self.y[posees] = floor
                self.vy[posees] = 0.0
                self.vx[posees] *= max(0.0, 1.0 - 6.0 * dt)

        self._n = int(vivantes.sum())
        return True

    def clear(self) -> None:
        self.alive[:] = False
        self._n = 0

    # -- lecture -------------------------------------------------------------

    @property
    def count(self) -> int:
        return self._n

    @property
    def empty(self) -> bool:
        return self._n == 0

    def visible(self):
        """Indices vivants, et l'avancement de vie de chacun dans [0, 1].

        L'avancement sert à la peinture : une particule s'efface et rétrécit en
        finissant sa vie, et c'est ce qui la fait disparaître sans qu'elle
        s'éteigne d'un coup.
        """
        idx = np.flatnonzero(self.alive)
        if idx.size == 0:
            return idx, np.empty(0, dtype="f4")
        age = 1.0 - self.life[idx] / np.maximum(1e-6, self.life0[idx])
        return idx, np.clip(age, 0.0, 1.0)
