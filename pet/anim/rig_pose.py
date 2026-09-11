"""Poses et courbes d'animation du rig (CDC §5, §10).

L'exigence de qualité du §10 gouverne tout ce module : **aucune interpolation
linéaire sur un mouvement visible**. Tout passe par de l'easing ou des ressorts,
avec anticipation avant les mouvements marqués et léger dépassement à l'arrivée.
Ces outils-là vivent dans `easing`, et sont réexportés ici.

Deux briques propres au rig :

- `Channels` — un mouvement est décrit par des canaux nommés (`head.yaw`,
  `body.flex`…) plutôt que par des matrices. Les couches produisent des canaux,
  et un seul point de code les traduit en poses du rig. C'est ce qui permet de
  superposer trois couches sans qu'aucune connaisse la géométrie.
- `PoseCurve` — courbes de pose nommées pour les actions discrètes, avec un
  easing **par segment**.

`RigPose` sépare la **pose de base**, qui encode la forme issue du génome, des
**deltas** que l'animation écrit. Sans cette séparation, animer une translation
détruirait la morphologie du robot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from ..geometry.rig import Node, Rig

# Ressorts et easing vivent dans `easing`, qui ne dépend de rien : la couche
# d'interface doit pouvoir les utiliser sans tirer la géométrie du robot avec
# elle. Ils sont réexportés ici parce que c'est de ce module que le rig, les
# couches et la locomotion les ont toujours importés.
from .easing import (                                              # noqa: F401
    EASINGS,
    Spring,
    ease_in,
    ease_in_back,
    ease_in_out,
    ease_out,
    ease_out_back,
    ease_out_elastic,
)


# ---------------------------------------------------------------------------
# Canaux et courbes de pose
# ---------------------------------------------------------------------------

# Canaux animables. Décrire un mouvement par des noms plutôt que par des
# matrices laisse les couches ignorer la géométrie : un seul point de code, dans
# `layers.apply_channels`, sait comment un canal devient une pose.
CHANNELS: tuple[str, ...] = (
    "body.yaw", "body.pitch", "body.roll",
    "body.flex",            # respiration : échelle Y du corps, 0 = repos
    "body.lift",            # saut, affaissement
    "head.yaw", "head.pitch", "head.roll",
    "head.lift",
    "ear.droop",            # oreilles tombantes : fatigue, tristesse
    "face.blink", "face.squint", "face.lid_top", "face.lid_bottom",
    "face.pupil", "face.glitch",
    "face.gaze_x", "face.gaze_y",
)

Channels = dict[str, float]


def zero_channels() -> Channels:
    return {name: 0.0 for name in CHANNELS}


def add_channels(into: Channels, other: Channels, weight: float = 1.0) -> Channels:
    """Superpose `other` sur `into`. Les couches s'ajoutent, elles ne s'écrasent pas."""
    for key, value in other.items():
        into[key] = into.get(key, 0.0) + value * weight
    return into


@dataclass(frozen=True)
class Key:
    """Clé d'une courbe de pose : un instant, des canaux, un easing d'arrivée.

    L'easing porté par la clé est celui du segment **qui y mène**. C'est le sens
    utile : on choisit comment on arrive quelque part.
    """

    t: float
    values: Channels = field(default_factory=dict)
    ease: str = "in_out"


@dataclass(frozen=True)
class PoseCurve:
    """Courbe de pose nommée, pour les animations discrètes du §10.3."""

    name: str
    keys: tuple[Key, ...]
    loop: bool = False

    def __post_init__(self) -> None:
        if len(self.keys) < 2:
            raise ValueError(f"{self.name} : une courbe a besoin d'au moins deux clés")
        times = [k.t for k in self.keys]
        if times != sorted(times):
            raise ValueError(f"{self.name} : clés non ordonnées dans le temps")
        if times[0] != 0.0:
            raise ValueError(f"{self.name} : la première clé doit être à t=0")
        for key in self.keys:
            if key.ease not in EASINGS:
                raise ValueError(f"{self.name} : easing inconnu {key.ease!r}")
            for channel in key.values:
                if channel not in CHANNELS:
                    raise ValueError(f"{self.name} : canal inconnu {channel!r}")

    @property
    def duration(self) -> float:
        return self.keys[-1].t

    def sample(self, t: float) -> Channels:
        """Canaux à l'instant `t`, easing du segment appliqué."""
        if self.loop and self.duration > 0.0:
            t = t % self.duration
        if t <= 0.0:
            return dict(self.keys[0].values)
        if t >= self.duration:
            return dict(self.keys[-1].values)

        index = 0
        for i in range(1, len(self.keys)):
            if t <= self.keys[i].t:
                index = i
                break
        a, b = self.keys[index - 1], self.keys[index]
        span = b.t - a.t
        u = 0.0 if span <= 0.0 else (t - a.t) / span
        eased = EASINGS[b.ease](u)

        out: Channels = {}
        for channel in set(a.values) | set(b.values):
            va = a.values.get(channel, 0.0)
            vb = b.values.get(channel, 0.0)
            out[channel] = va + (vb - va) * eased
        return out


# ---------------------------------------------------------------------------
# Pose du rig
# ---------------------------------------------------------------------------


@dataclass
class NodeDelta:
    """Écart à la pose de base d'un nœud. Additif, sauf l'échelle."""

    translation: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype="f4"))
    rotation: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype="f4"))
    scale: np.ndarray = field(default_factory=lambda: np.ones(3, dtype="f4"))

    def reset(self) -> None:
        self.translation[:] = 0.0
        self.rotation[:] = 0.0
        self.scale[:] = 1.0


class RigPose:
    """Sépare la forme du génome des deltas que l'animation écrit.

    Sans cette séparation, animer la translation d'un nœud détruirait la
    morphologie : les translations du rig **sont** la morphologie, puisque c'est
    là que le lot L2 a encodé les proportions du robot.
    """

    def __init__(self, rig: Rig, base: dict | None = None) -> None:
        self.rig = rig
        # La base est fournie de préférence par `Robot.base_pose`, relevée à la
        # construction. À défaut on relève l'état courant, ce qui n'est correct
        # que si le rig est au repos — créer une pose sur un rig déjà animé y
        # cuirait l'animation en cours.
        self._base: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = (
            {name: (t.copy(), r.copy(), s.copy()) for name, (t, r, s) in base.items()}
            if base else
            {name: (node.translation.copy(), node.rotation.copy(), node.scale.copy())
             for name, node in rig.nodes.items()}
        )
        self.deltas: dict[str, NodeDelta] = {name: NodeDelta() for name in rig.nodes}

    def reset(self) -> None:
        for delta in self.deltas.values():
            delta.reset()

    def offset(self, node: str, *, translation: Iterable[float] | None = None,
               rotation: Iterable[float] | None = None,
               scale: Iterable[float] | None = None) -> None:
        """Ajoute un écart. Les appels successifs s'accumulent."""
        delta = self.deltas.get(node)
        if delta is None:
            return                      # nœud absent : morphologie sans oreilles
        if translation is not None:
            delta.translation += np.asarray(translation, dtype="f4")
        if rotation is not None:
            delta.rotation += np.asarray(rotation, dtype="f4")
        if scale is not None:
            delta.scale *= np.asarray(scale, dtype="f4")

    def apply(self) -> None:
        """Écrit base + delta dans les nœuds du rig."""
        for name, node in self.rig.nodes.items():
            base_t, base_r, base_s = self._base[name]
            delta = self.deltas[name]
            node.translation = base_t + delta.translation
            node.rotation = base_r + delta.rotation
            node.scale = base_s * delta.scale

    def base_translation(self, node: str) -> np.ndarray:
        return self._base[node][0]

    def restore(self) -> None:
        """Remet la pose de base, deltas ignorés. Utile aux tests et au rendu figé."""
        self.reset()
        self.apply()


def add_node_if_missing(rig: Rig, node: Node) -> None:
    """Ajoute un nœud seulement s'il manque. Pratique face aux morphologies."""
    if node.name not in rig:
        rig.add(node)
