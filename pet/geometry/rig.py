"""Hiérarchie de transformations (CDC §10).

`root → body → neck → head → {face, ears}`. Transformations locales composées
par une traversée simple. **Pas de skinning, pas de squelette pondéré** : le
robot est un assemblage de parties rigides, ce qui suffit et ne coûte presque
rien — et c'est précisément ce choix qui rend l'animation du lot L4 possible sans
re-meshing.

Convention : matrices 4×4 numpy en ligne, appliquées à gauche (`M @ v`), comme la
projection du lot L0. La transposition vers l'ordre colonne d'OpenGL a lieu au
moment de l'écriture de l'uniforme, pas ici.

Les nœuds portent une pose locale mutable (translation, rotation, échelle). Au
lot L2 elle est fixée par l'assemblage ; au lot L4, les couches d'animation
écriront dedans, et rien d'autre ne changera.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

ROOT = "root"


def identity() -> np.ndarray:
    return np.identity(4, dtype="f4")


def translation(x: float, y: float, z: float) -> np.ndarray:
    m = identity()
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def scaling(sx: float, sy: float, sz: float) -> np.ndarray:
    m = identity()
    m[0, 0], m[1, 1], m[2, 2] = sx, sy, sz
    return m


def rotation_x(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    m = identity()
    m[1, 1], m[1, 2] = c, -s
    m[2, 1], m[2, 2] = s, c
    return m


def rotation_y(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    m = identity()
    m[0, 0], m[0, 2] = c, s
    m[2, 0], m[2, 2] = -s, c
    return m


def rotation_z(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    m = identity()
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return m


@dataclass
class Node:
    """Nœud du rig. Sa pose locale est la seule chose que l'animation touche."""

    name: str
    parent: str | None = ROOT
    translation: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype="f4"))
    rotation: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype="f4"))
    scale: np.ndarray = field(default_factory=lambda: np.ones(3, dtype="f4"))

    def local_matrix(self) -> np.ndarray:
        m = translation(*self.translation)
        rx, ry, rz = self.rotation
        if rz:
            m = m @ rotation_z(float(rz))
        if ry:
            m = m @ rotation_y(float(ry))
        if rx:
            m = m @ rotation_x(float(rx))
        if not np.allclose(self.scale, 1.0):
            m = m @ scaling(*self.scale)
        return m


class Rig:
    """Arbre de nœuds, résolu par traversée en ordre topologique."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {ROOT: Node(ROOT, parent=None)}
        self._order: list[str] = [ROOT]

    def add(self, node: Node) -> Node:
        if node.name in self.nodes:
            raise ValueError(f"nœud déjà présent : {node.name}")
        if node.parent not in self.nodes:
            raise ValueError(f"parent inconnu pour {node.name} : {node.parent}")
        self.nodes[node.name] = node
        # Les parents étant toujours ajoutés avant leurs enfants, l'ordre
        # d'insertion est déjà topologique : aucun tri n'est nécessaire.
        self._order.append(node.name)
        return node

    def __contains__(self, name: str) -> bool:
        return name in self.nodes

    def __getitem__(self, name: str) -> Node:
        return self.nodes[name]

    @property
    def order(self) -> tuple[str, ...]:
        return tuple(self._order)

    def world_matrices(self) -> dict[str, np.ndarray]:
        """Matrice monde de chaque nœud.

        Une seule passe, chaque nœud composant la matrice déjà résolue de son
        parent. Coût négligeable : le rig compte moins d'une dizaine de nœuds.
        """
        out: dict[str, np.ndarray] = {}
        for name in self._order:
            node = self.nodes[name]
            local = node.local_matrix()
            out[name] = local if node.parent is None else out[node.parent] @ local
        return out

    def depth(self, name: str) -> int:
        d = 0
        node = self.nodes[name]
        while node.parent is not None:
            node = self.nodes[node.parent]
            d += 1
        return d
