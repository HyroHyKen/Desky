"""Regard curieux : le pet invente lui-même où regarder (CDC §10, lot L6).

Sorti de `window` au lot L10. C'est une pièce d'animation et non de fenêtrage :
elle ne connaît qu'une zone de travail et une position, et elle en tire un point
à fixer. Sa place est ici, avec le reste de ce qui fait bouger le robot.
"""

from __future__ import annotations

import random

# Coups d'oeil de curiosité : intervalle entre deux, et durée de chacun.
# L'intervalle est large parce que c'est une **ponctuation** : trop fréquent, le
# pet aurait l'air distrait plutôt que curieux.
GLANCE_GAP = (7.0, 15.0)
GLANCE_HOLD = (1.2, 2.6)

# Distance minimale du point visé, en largeurs de pet. Un coup d'oeil vers un
# point tout proche ne tourne pas la tête, donc ne se voit pas : autant ne pas
# le jouer.
GLANCE_MIN_DISTANCE = 2.2


class CuriousGaze:
    """Coups d'oeil du pet vers un point de son choix.

    « Comme s'il tentait d'amener l'utilisateur sur autre chose. » C'est la
    seule cible du regard qui ne vienne de rien d'observable : elle est
    **inventée** par le pet, et c'est précisément ce qui la rend vivante. Un
    regard qui ne fait que suivre des choses existantes reste réactif ; un
    regard qui part de lui-même vers un coin de l'écran suggère une intention.

    Le hasard vient d'une graine, comme le rythme des clignements du lot L4 : le
    tempérament d'attention appartient à l'identité du robot, et reste
    reproductible en test.
    """

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)
        self.point: tuple[float, float] | None = None
        self._left = self._rng.uniform(*GLANCE_GAP)

    def update(self, dt: float, curious: bool, work, pet_x: float,
               pet_w: float) -> tuple[float, float] | None:
        """Avance l'horloge des coups d'oeil et rend le point visé, ou None."""
        self._left -= max(0.0, dt)
        if self._left > 0.0:
            return self.point

        if self.point is not None:
            # Fin du coup d'oeil : retour au régime normal.
            self.point = None
            self._left = self._rng.uniform(*GLANCE_GAP)
            return None

        if not curious:
            # Pas curieux : on repousse sans consommer le tour, sinon le
            # premier instant de curiosité déclencherait un coup d'oeil immédiat.
            self._left = self._rng.uniform(*GLANCE_GAP) * 0.5
            return None

        wl, wt, ww, wh = work
        mini = GLANCE_MIN_DISTANCE * max(1.0, pet_w)
        for _ in range(8):
            x = self._rng.uniform(wl, wl + ww)
            if abs(x - pet_x) >= mini:
                break
        else:
            x = wl if pet_x > wl + ww / 2.0 else wl + ww
        # Dans la moitié haute : regarder le sol ne raconte rien, alors qu'un
        # regard levé suggère qu'il a vu quelque chose.
        y = self._rng.uniform(wt + wh * 0.12, wt + wh * 0.55)
        self.point = (x, y)
        self._left = self._rng.uniform(*GLANCE_HOLD)
        return self.point
