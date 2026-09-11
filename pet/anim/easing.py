"""Ressorts amortis et courbes d'easing (CDC §10).

L'exigence de qualité du §10 gouverne ce module : **aucune interpolation
linéaire sur un mouvement visible**. Tout passe par de l'easing ou des ressorts,
avec anticipation avant les mouvements marqués et léger dépassement à l'arrivée.

Ces briques vivaient dans `rig_pose`, où elles étaient nées, et où elles étaient
restées prisonnières : ce module importe `..geometry.rig`, si bien qu'animer un
bouton du panneau de soin aurait tiré toute la géométrie du robot dans la couche
d'interface. Le vocabulaire du §10 vaut pour **tout ce qui bouge à l'écran**, pas
seulement pour le rig — un panneau qui s'ouvre d'un coup viole le §10 aussi
sûrement qu'un robot qui glisse en linéaire.

D'où ce module, qui ne dépend que de `math` et de `numpy`. `rig_pose` le
réexporte : tout ce qui importait `Spring` depuis là continue de marcher.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

__all__ = [
    "Spring",
    "ease_in_out", "ease_out", "ease_in",
    "ease_out_back", "ease_in_back", "ease_out_elastic",
    "EASINGS",
]


# ---------------------------------------------------------------------------
# Ressort amorti
# ---------------------------------------------------------------------------


class Spring:
    """Ressort amorti du second ordre, résolu analytiquement.

    `omega` est la pulsation propre en rad/s — plus elle est grande, plus le
    mouvement est vif. `zeta` est le taux d'amortissement : en dessous de 1 le
    ressort dépasse et revient, à 1 il arrive sans dépasser, au-dessus il traîne.

    Le §10 demande « raideur et amortissement paramétrés, pas d'interpolation
    linéaire » : ce sont exactement ces deux nombres.

    **Solution analytique exacte**, et non intégration pas à pas. C'est une
    nécessité et non un raffinement : la cadence de ce projet passe de 30 à
    10 fps selon le régime (CDC §3), donc `dt` triple d'un instant à l'autre. Un
    intégrateur d'Euler explicite se met à osciller puis diverge sur de tels
    pas ; la solution analytique donne le même mouvement quel que soit le
    découpage temporel.

    Fonctionne sur un scalaire ou sur un vecteur numpy, indifféremment.
    """

    __slots__ = ("value", "velocity", "omega", "zeta")

    def __init__(self, value, omega: float = 12.0, zeta: float = 1.0) -> None:
        self.value = np.asarray(value, dtype="f8") if np.ndim(value) else float(value)
        self.velocity = np.zeros_like(self.value) if np.ndim(value) else 0.0
        self.omega = float(omega)
        self.zeta = float(zeta)

    def reset(self, value) -> None:
        self.value = np.asarray(value, dtype="f8") if np.ndim(value) else float(value)
        self.velocity = np.zeros_like(self.value) if np.ndim(value) else 0.0

    def step(self, target, dt: float):
        """Avance de `dt` vers `target`. Exact, donc stable à tout `dt`."""
        if dt <= 0.0:
            return self.value

        w, z = self.omega, self.zeta
        x = self.value - target            # écart à la cible
        v = self.velocity

        if z < 1.0 - 1e-6:                 # sous-amorti : dépasse puis revient
            wd = w * math.sqrt(1.0 - z * z)
            e = math.exp(-z * w * dt)
            c1 = x
            c2 = (v + z * w * x) / wd
            cs, sn = math.cos(wd * dt), math.sin(wd * dt)
            pos = e * (c1 * cs + c2 * sn)
            vel = e * (-z * w * (c1 * cs + c2 * sn) + wd * (-c1 * sn + c2 * cs))
        elif z <= 1.0 + 1e-6:              # critique : arrive sans dépasser
            e = math.exp(-w * dt)
            c1 = x
            c2 = v + w * x
            pos = (c1 + c2 * dt) * e
            vel = (c2 - w * (c1 + c2 * dt)) * e
        else:                              # sur-amorti : traîne
            r = w * math.sqrt(z * z - 1.0)
            r1, r2 = -z * w + r, -z * w - r
            e1, e2 = math.exp(r1 * dt), math.exp(r2 * dt)
            c2 = (v - r1 * x) / (r2 - r1)
            c1 = x - c2
            pos = c1 * e1 + c2 * e2
            vel = c1 * r1 * e1 + c2 * r2 * e2

        self.value = target + pos
        self.velocity = vel
        return self.value

    def settled(self, target, epsilon: float = 1e-3) -> bool:
        """Le ressort est-il arrivé, et arrêté ?

        Les deux conditions comptent. Un ressort sous-amorti passe exactement
        sur sa cible au milieu d'une oscillation, à pleine vitesse : ne tester
        que la position couperait l'animation en plein dépassement, c'est-à-dire
        au moment précis que le §10 réclame.

        C'est ce prédicat qui permet d'arrêter le tic d'animation quand plus
        rien ne bouge, et donc de tenir le budget CPU du §3.
        """
        ecart = float(np.max(np.abs(np.asarray(self.value) - np.asarray(target))))
        vitesse = float(np.max(np.abs(np.asarray(self.velocity))))
        return ecart < epsilon and vitesse < epsilon


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------
#
# Chaque courbe prend et rend un paramètre dans [0, 1]. Aucune n'est linéaire :
# c'est l'exigence du §10, et un test le vérifie sur l'ensemble du registre.


def ease_in_out(t: float) -> float:
    """Départ et arrivée doux. Le défaut pour un mouvement quelconque."""
    return t * t * (3.0 - 2.0 * t)


def ease_out(t: float) -> float:
    """Départ vif, arrivée douce. Pour une réaction."""
    return 1.0 - (1.0 - t) ** 3


def ease_in(t: float) -> float:
    """Départ lent, arrivée vive. Pour une chute, un affaissement."""
    return t * t * t


def ease_out_back(t: float, overshoot: float = 1.9) -> float:
    """Léger dépassement à l'arrivée, puis retour. Exigé par le §10."""
    u = t - 1.0
    return 1.0 + u * u * ((overshoot + 1.0) * u + overshoot)


def ease_in_back(t: float, anticipation: float = 1.5) -> float:
    """Petit recul avant de partir. C'est l'anticipation du §10."""
    return t * t * ((anticipation + 1.0) * t - anticipation)


def ease_out_elastic(t: float) -> float:
    """Rebond amorti à l'arrivée. Pour un mouvement joyeux."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return 1.0 + (2.0 ** (-9.0 * t)) * math.sin((t * 6.5 - 0.75) * math.pi)


EASINGS: dict[str, Callable[[float], float]] = {
    "in_out": ease_in_out,
    "out": ease_out,
    "in": ease_in,
    "out_back": ease_out_back,
    "in_back": ease_in_back,
    "out_elastic": ease_out_elastic,
}
