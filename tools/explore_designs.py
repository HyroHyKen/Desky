"""Planche d'exploration esthétique — recherche de silhouette.

**Outil d'exploration, pas du code de production.** `pet/geometry/builder.py`
reste inchangé : il porte l'assemblage validé du lot L2 et ses 106 tests. Ici on
compose librement des parties pour comparer des directions de design, et c'est
seulement celle qui sera retenue qui redescendra dans le builder.

Deux ajouts par rapport au lot L2, indispensables pour juger :

- **Des pupilles géométriques.** La planche du lot L2 montrait des dalles
  aveugles, ce qui rend le design illisible. Ce sont des capsules placées sur la
  surface de l'écran, et un simple substitut : le CDC §9 impose que le visage
  définitif soit dessiné par SDF dans un fragment shader, au lot L3.
- **Un jonc de cadre**, quatre bandeaux formant un rectangle autour de l'écran.
  C'est ce qui fait lire une face comme un écran encadré plutôt que comme une
  tache sombre.

Contrainte d'identité du CDC §1 : le vocabulaire visuel des références est repris
(écran cadré, corps trapu, bras en pastille, languette de crâne, socle rond), les
proportions et les silhouettes sont propres au projet.

    .venv/Scripts/python.exe -m tools.explore_designs --out exploration.png
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pet.genome.schema import ACCENT_COLORS, BODY_COLORS, accent_rgb, body_rgb, defaults
from pet.geometry import proportions
from pet.geometry.builder import Part, Robot
from pet.geometry.proportions import Dimensions
from pet.geometry.rig import ROOT, Node, Rig
from pet.geometry.superellipsoid import _spow, superellipsoid, superellipsoid_patch
from pet.render.context import RenderContext
from pet.render.scene import Scene

HALF_PI = np.pi / 2.0

SCREEN_COLOR = (0.075, 0.085, 0.105)
DARK_TRIM = (0.20, 0.21, 0.24)


def surface_point(a, b, c, n1, n2, u, v, inflate=1.0):
    """Point de la surface d'un superellipsoïde, pour y poser une pièce."""
    rad = _spow(np.array(np.cos(v)), n1)
    return np.array([
        float(a * inflate * rad * _spow(np.array(np.cos(u)), n2)),
        float(b * inflate * _spow(np.array(np.sin(v)), n1)),
        float(c * inflate * rad * _spow(np.array(np.sin(u)), n2)),
    ])


def half_width_at(a: float, n1: float, y_frac: float, taper: float = 1.0) -> float:
    """Demi-largeur du superellipsoïde à la hauteur `y_frac` (−1 en bas, +1 en haut).

    Trois planches de suite, les bras et les roues sont restés invisibles parce
    qu'ils étaient placés à une fraction de la demi-largeur mesurée **au centre**
    du corps, alors qu'ils sont posés plus haut ou plus bas — là où le volume est
    plus étroit. Ils se retrouvaient donc à l'intérieur.

    De y = b·sgn(sin v)|sin v|^n1 on tire |sin v| = |y_frac|^(1/n1), donc la
    demi-largeur vaut a·(1 − |y_frac|^(2/n1))^(n1/2). L'effilement s'y applique
    ensuite, puisqu'il multiplie x en fonction de la hauteur.
    """
    t = min(1.0, abs(float(y_frac)))
    w = a * (max(0.0, 1.0 - t ** (2.0 / n1))) ** (n1 / 2.0)
    if taper != 1.0:
        w *= 1.0 + (taper - 1.0) * ((float(y_frac) + 1.0) / 2.0)
    return w



def boost(color: tuple[float, float, float], factor: float = 1.9):
    """Éclaircit une couleur pour qu'elle lise comme émissive.

    Substitut d'exploration : la passe toon éclaire les pupilles comme le reste,
    alors que le CDC §9 les veut émissives et non éclairées. Au lot L3 elles ne
    seront plus de la géométrie du tout.
    """
    return tuple(min(1.0, c * factor) for c in color)


# --- Pièces d'exploration ---------------------------------------------------

@dataclass
class FaceHost:
    """Volume qui porte le visage : la tête, ou le corps pour un monobloc.

    Généralisé parce qu'une direction de design intéressante — le monobloc, un
    seul volume portant l'écran — n'a pas de tête du tout, et que le cadre, l'
    écran et les pupilles doivent alors se poser sur le corps sans dupliquer
    leur code.
    """

    node: str
    a: float
    b: float
    c: float
    n1: float
    n2: float
    v_center: float




def screen_patch(h: FaceHost, u_span: float, v_span: float,
                 inflate: float = 1.02) -> Part:
    return Part("screen", h.node, superellipsoid_patch(
        a=h.a * inflate, b=h.b * inflate, c=h.c * inflate, n1=h.n1, n2=h.n2,
        u_center=HALF_PI, u_half=u_span, v_center=h.v_center, v_half=v_span,
        sectors=26, rings=18,
    ), SCREEN_COLOR)


def bezel_parts(h: FaceHost, u_span: float, v_span: float,
                thickness: float, color, inflate: float = 1.05) -> list[Part]:
    """Jonc de cadre : quatre bandeaux en couronne autour de l'écran.

    Construit en quatre coques plutôt qu'en un anneau : une couronne complète
    demanderait une primitive à trou, alors que quatre portions de la même
    surface donnent exactement le même dessin.
    """
    vc = h.v_center
    ou, ov = u_span + thickness, v_span + thickness
    common = dict(a=h.a * inflate, b=h.b * inflate, c=h.c * inflate, n1=h.n1, n2=h.n2)
    strips = [
        ("haut", dict(u_center=HALF_PI, u_half=ou, v_center=vc + (ov + v_span) / 2,
                      v_half=(ov - v_span) / 2, sectors=24, rings=3)),
        ("bas", dict(u_center=HALF_PI, u_half=ou, v_center=vc - (ov + v_span) / 2,
                     v_half=(ov - v_span) / 2, sectors=24, rings=3)),
        ("gauche", dict(u_center=HALF_PI - (ou + u_span) / 2, u_half=(ou - u_span) / 2,
                        v_center=vc, v_half=ov, sectors=3, rings=18)),
        ("droite", dict(u_center=HALF_PI + (ou + u_span) / 2, u_half=(ou - u_span) / 2,
                        v_center=vc, v_half=ov, sectors=3, rings=18)),
    ]
    return [Part(f"bezel_{name}", h.node, superellipsoid_patch(**common, **kw), color)
            for name, kw in strips]


def eye_parts(h: FaceHost, accent, spacing: float, size: float,
              shape: str = "capsule", v_offset: float = 0.07) -> list[Part]:
    """Deux pupilles posées sur la surface de l'écran."""
    parts = []
    for side, sign in (("l", -1.0), ("r", 1.0)):
        u = HALF_PI + sign * spacing
        p = surface_point(h.a, h.b, h.c, h.n1, h.n2,
                          u, h.v_center + v_offset, inflate=1.05)
        if shape == "capsule":                  # capsule verticale
            a, b, c = size * 0.62, size, size * 0.34
            n1, n2 = 0.75, 0.60
        elif shape == "ronde":
            a, b, c = size * 0.85, size * 0.85, size * 0.34
            n1, n2 = 1.0, 1.0
        elif shape == "barre":                  # trait horizontal
            a, b, c = size * 1.25, size * 0.42, size * 0.30
            n1, n2 = 0.55, 0.45
        else:                                   # carrée
            a, b, c = size * 0.78, size * 0.78, size * 0.34
            n1, n2 = 0.42, 0.38
        parts.append(Part(f"eye_{side}", h.node,
                          superellipsoid(a, b, c, n1, n2, sectors=18, rings=12),
                          boost(accent), offset=tuple(p)))
    return parts


def top_tab(d: Dimensions, color) -> Part:
    """Languette plate sur le crâne, inclinée vers l'arrière."""
    return Part("top_tab", "head_top", superellipsoid(
        a=d.head_a * 0.52, b=d.head_b * 0.10, c=d.head_c * 0.44,
        n1=0.30, n2=0.28, sectors=22, rings=8,
    ), color)


def brow(h: FaceHost, color, u_span: float) -> Part:
    """Petite lèvre de visière au-dessus de l'écran."""
    return Part("brow", h.node, superellipsoid_patch(
        a=h.a * 1.11, b=h.b * 1.11, c=h.c * 1.11, n1=h.n1, n2=h.n2,
        u_center=HALF_PI, u_half=u_span * 0.94, v_center=h.v_center + 0.54,
        v_half=0.10, sectors=22, rings=3,
    ), color)


def helmet(d: Dimensions, g: dict, color) -> Part:
    """Calotte colorée sur le dessus de la tête."""
    return Part("helmet", "head", superellipsoid_patch(
        a=d.head_a * 1.03, b=d.head_b * 1.03, c=d.head_c * 1.03,
        n1=g["head.exponent_n1"], n2=g["head.exponent_n2"],
        u_center=HALF_PI, u_half=np.pi, v_center=0.74, v_half=0.40,
        sectors=36, rings=12,
    ), color)


def arm_parts(d: Dimensions, color, length: float = 1.0) -> list[Part]:
    """Deux bras en pastille, saillants sur la face avant du corps.

    Premiere planche : les bras etaient invisibles, places a 0,62 fois la
    demi-largeur du corps, c'est-a-dire **a l'interieur** du volume. Ils sont
    desormais portes par la face avant, ou ils depassent franchement.
    """
    parts = []
    for side, sign in (("l", -1.0), ("r", 1.0)):
        # Taille calee sur la hauteur du corps, pour ne pas dominer un
        # monobloc large ni disparaitre sur une capsule etroite.
        r = d.body_b * 0.21 * length
        parts.append(Part(f"arm_{side}", f"arm_{side}", superellipsoid(
            a=r, b=r * 2.6, c=r * 0.92,
            n1=0.80, n2=0.90, sectors=16, rings=12,
        ), color, offset=(0.0, -r * 2.1, 0.0)))
    return parts


def arm_nodes(d: Dimensions, n1: float, n2: float, taper: float,
              angle: float = 0.30, y: float = 0.10) -> list[Node]:
    """Bras montés sur les **flancs**, à l'extérieur réel de la silhouette.

    Les flancs sont la seule position qui ne collisionne avec aucune autre
    pièce, quelle que soit la morphologie — ni l'écran d'un monobloc, ni le
    panneau de poitrine d'un cube. Le X d'attache est calculé à la hauteur
    d'implantation, pas au centre du corps : cf. `half_width_at`.
    """
    x = half_width_at(d.body_a, n1, y, taper)
    return [
        Node(f"arm_{side}", parent="body",
             translation=np.array([sign * (x + d.body_b * 0.10), d.body_b * y,
                                   d.body_c * 0.24], dtype="f4"),
             rotation=np.array([0.0, 0.0, sign * -angle], dtype="f4"))
        for side, sign in (("l", -1.0), ("r", 1.0))
    ]


def puck(d: Dimensions, color) -> Part:
    """Socle rond, à la place des pieds."""
    return Part("puck", ROOT, superellipsoid(
        a=d.body_a * 1.34, b=d.body_b * 0.17, c=d.body_a * 1.34,
        n1=0.52, n2=1.0, sectors=30, rings=12,
    ), color, offset=(0.0, d.body_b * 0.17, 0.0))


def wheels(d: Dimensions, color, n1: float = 0.78, taper: float = 1.0) -> list[Part]:
    """Deux roues aux flancs bas, à l'extérieur réel de la silhouette."""
    parts = []
    y_frac = -0.55
    x = half_width_at(d.body_a, n1, y_frac, taper)
    for side, sign in (("l", -1.0), ("r", 1.0)):
        # Deuxieme planche : a 0,86 fois la demi-hauteur, une seule roue etait
        # visible et lisait comme un cylindre posé devant le corps.
        rr = d.body_b * 0.40
        parts.append(Part(f"wheel_{side}", "body", superellipsoid(
            a=d.body_a * 0.13, b=rr, c=rr,
            n1=0.94, n2=1.0, sectors=20, rings=14,
        ), DARK_TRIM,
            offset=(sign * (x + d.body_a * 0.10), d.body_b * y_frac, 0.0)))
    return parts


def feet(d: Dimensions, color) -> list[Part]:
    parts = []
    for side, sign in (("l", -1.0), ("r", 1.0)):
        parts.append(Part(f"foot_{side}", "body", superellipsoid(
            a=d.body_a * 0.40, b=d.body_b * 0.14, c=d.body_c * 0.66,
            n1=0.45, n2=0.55, sectors=18, rings=10,
        ), color, offset=(sign * d.body_a * 0.48, -d.body_b * 0.94, d.body_c * 0.10)))
    return parts


def chest_panel(d: Dimensions, g: dict, color, u_half: float = 0.34,
                v_half: float = 0.26) -> Part:
    """Petit panneau sur la poitrine.

    Etendue reduite depuis la premiere planche : a 0,52 x 0,42, le panneau
    d'accent recouvrait toute la face avant et le corps disparaissait sous la
    couleur.
    """
    return Part("chest", "body", superellipsoid_patch(
        a=d.body_a * 1.02, b=d.body_b * 1.02, c=d.body_c * 1.02,
        n1=g["_body_n1"], n2=g["_body_n2"],
        u_center=HALF_PI, u_half=u_half, v_center=-0.02, v_half=v_half,
        sectors=18, rings=12,
    ), color)


def collar(d: Dimensions, color) -> Part:
    return Part("collar", "neck", superellipsoid(
        a=d.neck_r * 1.32, b=d.neck_r * 0.20, c=d.neck_r * 1.32,
        n1=0.55, n2=1.0, sectors=22, rings=10,
    ), color, offset=(0.0, -d.neck_h * 0.5, 0.0))


def shoulders(d: Dimensions, color) -> list[Part]:
    parts = []
    for side, sign in (("l", -1.0), ("r", 1.0)):
        parts.append(Part(f"shoulder_{side}", "body", superellipsoid(
            a=d.body_a * 0.46, b=d.body_b * 0.26, c=d.body_c * 0.44,
            n1=0.60, n2=0.80, sectors=18, rings=12,
        ), color, offset=(sign * d.body_a * 0.72, d.body_b * 0.86, 0.0)))
    return parts


def antennas(d: Dimensions, accent, color, count: int = 2) -> tuple[list[Node], list[Part]]:
    nodes, parts = [], []
    r = d.head_a * 0.30
    sides = [("c", 0.0)] if count == 1 else [("l", -1.0), ("r", 1.0)]
    for side, sign in sides:
        node = f"ant_{side}"
        nodes.append(Node(node, parent="head",
                          translation=np.array(
                              [sign * d.head_a * 0.40, d.head_b * 1.90, 0.0], dtype="f4"),
                          rotation=np.array([0.0, 0.0, sign * -0.12], dtype="f4")))
        parts.append(Part(f"ant_{side}_stalk", node, superellipsoid(
            a=r * 0.10, b=r * 0.85, c=r * 0.10, n1=0.72, n2=0.95, sectors=12, rings=8,
        ), color, offset=(0.0, r * 0.85, 0.0)))
        parts.append(Part(f"ant_{side}_tip", node, superellipsoid(
            a=r * 0.25, b=r * 0.25, c=r * 0.25, sectors=14, rings=10,
        ), boost(accent, 1.5), offset=(0.0, r * 1.86, 0.0)))
    return nodes, parts


# --- Variantes ---------------------------------------------------------------


@dataclass
class Variant:
    key: str
    label: str
    genome: dict[str, Any] = field(default_factory=dict)
    features: tuple[str, ...] = ()
    eye_shape: str = "capsule"
    eye_spacing: float = 0.34
    eye_size: float = 0.115
    screen_u: float = 0.72
    screen_v: float = 0.44
    bezel_thickness: float = 0.13
    # Exposants du corps. Codes en dur sur la premiere planche, ils rendaient
    # tous les corps identiques : « Cube franc » avait un corps en oeuf.
    body_n1: float = 0.78
    body_n2: float = 0.86
    faceless_head: bool = False   # visage porte par le corps, pas de tete


def base_genome(**over: Any) -> dict[str, Any]:
    g = dict(defaults())
    g["_plate_v"] = -0.10
    g.update(over)
    return g


VARIANTS: list[Variant] = [
    # --- direction « écran cadré », inspirée des références ------------------
    Variant("cadre_large", "Écran cadré, tête large",
            base_genome(**{"head.radius": 1.32, "head.squash_y": 0.72,
                           "head.exponent_n1": 0.42, "head.exponent_n2": 0.40,
                           "body.height": 0.90, "body.width": 1.05,
                           "body.taper": 1.05, "neck.length": 0.16}),
            ("bezel", "arms", "toptab"), screen_u=0.86, screen_v=0.40,
            eye_spacing=0.36, eye_size=0.10),
    Variant("cadre_socle", "Écran cadré + socle rond",
            base_genome(**{"head.radius": 1.28, "head.squash_y": 0.74,
                           "head.exponent_n1": 0.44, "head.exponent_n2": 0.42,
                           "body.height": 0.78, "body.width": 1.02,
                           "body.taper": 1.00, "neck.length": 0.14}),
            ("bezel", "arms", "puck"), screen_u=0.84, screen_v=0.40,
            eye_spacing=0.35, eye_size=0.10, body_n1=0.58, body_n2=0.70),
    Variant("cadre_visiere", "Écran cadré + lèvre de visière",
            base_genome(**{"head.radius": 1.24, "head.squash_y": 0.80,
                           "head.exponent_n1": 0.46, "head.exponent_n2": 0.44,
                           "body.height": 1.00, "body.width": 0.98,
                           "neck.length": 0.18}),
            ("bezel", "brow", "arms"), screen_u=0.78, screen_v=0.42),
    Variant("cadre_fin", "Écran cadré, jonc fin",
            base_genome(**{"head.radius": 1.20, "head.squash_y": 0.82,
                           "head.exponent_n1": 0.55, "head.exponent_n2": 0.50,
                           "body.height": 1.05, "body.width": 0.95,
                           "neck.length": 0.20}),
            ("bezel", "arms"), bezel_thickness=0.07, screen_u=0.76, screen_v=0.44),
    Variant("cadre_epaules", "Écran cadré + épaules",
            base_genome(**{"head.radius": 1.26, "head.squash_y": 0.78,
                           "head.exponent_n1": 0.44, "head.exponent_n2": 0.42,
                           "body.height": 0.86, "body.width": 1.12,
                           "body.taper": 1.10, "neck.length": 0.12}),
            ("bezel", "shoulders", "arms"), screen_u=0.82, screen_v=0.40,
            body_n1=0.62, body_n2=0.74),

    # --- direction cubique ---------------------------------------------------
    Variant("cube_franc", "Cube franc",
            base_genome(**{"head.radius": 1.10, "head.squash_y": 0.95,
                           "head.exponent_n1": 0.36, "head.exponent_n2": 0.36,
                           "body.height": 1.05, "body.width": 1.10,
                           "body.taper": 0.98, "neck.length": 0.14}),
            ("bezel", "feet"), eye_shape="carree", screen_u=0.70, screen_v=0.52,
            body_n1=0.36, body_n2=0.38),
    Variant("cube_bras", "Cube + bras",
            base_genome(**{"head.radius": 1.05, "head.squash_y": 1.00,
                           "head.exponent_n1": 0.38, "head.exponent_n2": 0.38,
                           "body.height": 0.95, "body.width": 1.15,
                           "neck.length": 0.10}),
            ("bezel", "arms", "chest"), eye_shape="carree",
            screen_u=0.66, screen_v=0.50, body_n1=0.38, body_n2=0.40),
    Variant("cube_chenilles", "Cube sur roues",
            base_genome(**{"head.radius": 1.06, "head.squash_y": 0.90,
                           "head.exponent_n1": 0.38, "head.exponent_n2": 0.40,
                           "body.height": 0.82, "body.width": 1.18,
                           "neck.length": 0.10}),
            ("bezel", "wheels"), eye_shape="carree", screen_u=0.68, screen_v=0.48,
            body_n1=0.40, body_n2=0.44),

    # --- antennes ------------------------------------------------------------
    Variant("antenne_unique", "Antenne unique",
            base_genome(**{"head.radius": 1.05, "head.squash_y": 0.95,
                           "head.exponent_n1": 0.60, "head.exponent_n2": 0.55,
                           "body.height": 1.25, "body.width": 0.88,
                           "body.taper": 0.82, "neck.length": 0.22}),
            ("bezel", "antenna1", "arms")),
    Variant("antenne_paire", "Paire d'antennes",
            base_genome(**{"head.radius": 1.10, "head.squash_y": 0.88,
                           "head.exponent_n1": 0.52, "head.exponent_n2": 0.50,
                           "body.height": 1.10, "body.width": 0.92,
                           "neck.length": 0.18}),
            ("bezel", "antenna2", "arms")),
    Variant("antenne_socle", "Antennes + socle",
            base_genome(**{"head.radius": 1.14, "head.squash_y": 0.84,
                           "head.exponent_n1": 0.48, "head.exponent_n2": 0.46,
                           "body.height": 0.80, "body.width": 1.00,
                           "neck.length": 0.16}),
            ("bezel", "antenna2", "puck")),

    # --- casque / bicolore ---------------------------------------------------
    Variant("casque", "Casque coloré",
            base_genome(**{"head.radius": 1.18, "head.squash_y": 0.86,
                           "head.exponent_n1": 0.50, "head.exponent_n2": 0.48,
                           "body.height": 1.00, "body.width": 1.00,
                           "neck.length": 0.16}),
            ("bezel", "helmet", "arms")),
    Variant("casque_socle", "Casque + socle rond",
            base_genome(**{"head.radius": 1.22, "head.squash_y": 0.80,
                           "head.exponent_n1": 0.46, "head.exponent_n2": 0.44,
                           "body.height": 0.76, "body.width": 1.04,
                           "neck.length": 0.14}),
            ("bezel", "helmet", "puck", "arms")),
    Variant("bicolore", "Plastron d'accent",
            base_genome(**{"head.radius": 1.16, "head.squash_y": 0.88,
                           "head.exponent_n1": 0.52, "head.exponent_n2": 0.50,
                           "body.height": 1.08, "body.width": 0.98,
                           "neck.length": 0.18}),
            ("bezel", "chest_accent", "arms")),

    # --- silhouettes qui s'écartent franchement de la référence -------------
    Variant("monobloc", "Monobloc, un seul volume",
            base_genome(**{"body.height": 1.30, "body.width": 1.30,
                           "body.taper": 1.02, "neck.length": 0.0}),
            ("bezel",), faceless_head=True, body_n1=0.72, body_n2=0.78,
            screen_u=0.58, screen_v=0.34, eye_spacing=0.26, eye_size=0.072),
    Variant("monobloc_bras", "Monobloc + bras",
            base_genome(**{"body.height": 1.26, "body.width": 1.34,
                           "body.taper": 0.96, "neck.length": 0.0}),
            ("bezel", "arms"), faceless_head=True, body_n1=0.66, body_n2=0.76,
            screen_u=0.56, screen_v=0.32, eye_spacing=0.25, eye_size=0.070),
    Variant("monobloc_cube", "Monobloc cubique",
            base_genome(**{"body.height": 1.20, "body.width": 1.28,
                           "body.taper": 1.00, "neck.length": 0.0}),
            ("bezel", "feet"), faceless_head=True, body_n1=0.38, body_n2=0.40,
            eye_shape="carree", screen_u=0.30, screen_v=0.22,
            eye_spacing=0.13, eye_size=0.040),
    Variant("capsule", "Capsule élancée",
            base_genome(**{"head.radius": 0.92, "head.squash_y": 1.00,
                           "head.exponent_n1": 0.80, "head.exponent_n2": 0.75,
                           "body.height": 1.55, "body.width": 0.80,
                           "body.taper": 0.88, "neck.length": 0.10}),
            ("bezel", "arms"), screen_u=0.62, screen_v=0.46, eye_size=0.10),
    Variant("champignon", "Champignon",
            base_genome(**{"head.radius": 1.34, "head.squash_y": 0.66,
                           "head.exponent_n1": 0.70, "head.exponent_n2": 0.62,
                           "body.height": 0.90, "body.width": 0.82,
                           "body.taper": 0.76, "neck.length": 0.12}),
            ("bezel",), screen_u=0.80, screen_v=0.34, eye_size=0.095),
    Variant("tour", "Tour compacte",
            base_genome(**{"head.radius": 0.96, "head.squash_y": 1.10,
                           "head.exponent_n1": 0.40, "head.exponent_n2": 0.42,
                           "body.height": 1.35, "body.width": 0.86,
                           "body.taper": 1.08, "neck.length": 0.0}),
            ("bezel", "feet"), eye_shape="carree", screen_u=0.52, screen_v=0.44,
            body_n1=0.40, body_n2=0.42, eye_spacing=0.24, eye_size=0.10),
    Variant("galet", "Galet posé",
            base_genome(**{"head.radius": 1.24, "head.squash_y": 0.90,
                           "head.exponent_n1": 0.68, "head.exponent_n2": 0.64,
                           "body.height": 0.62, "body.width": 1.22,
                           "body.taper": 0.92, "neck.length": 0.0}),
            ("bezel", "arms"), screen_u=0.66, screen_v=0.44),

    # --- variations de regard sur une même silhouette -----------------------
    Variant("regard_capsule", "Regard : capsules",
            base_genome(**{"head.radius": 1.22, "head.squash_y": 0.80,
                           "head.exponent_n1": 0.46, "head.exponent_n2": 0.44,
                           "body.height": 0.92, "body.width": 1.02,
                           "neck.length": 0.16}),
            ("bezel", "arms"), eye_shape="capsule", screen_u=0.80, screen_v=0.40),
    Variant("regard_rond", "Regard : ronds",
            base_genome(**{"head.radius": 1.22, "head.squash_y": 0.80,
                           "head.exponent_n1": 0.46, "head.exponent_n2": 0.44,
                           "body.height": 0.92, "body.width": 1.02,
                           "neck.length": 0.16}),
            ("bezel", "arms"), eye_shape="ronde", screen_u=0.80, screen_v=0.40),
    Variant("regard_barre", "Regard : traits",
            base_genome(**{"head.radius": 1.22, "head.squash_y": 0.80,
                           "head.exponent_n1": 0.46, "head.exponent_n2": 0.44,
                           "body.height": 0.92, "body.width": 1.02,
                           "neck.length": 0.16}),
            ("bezel", "arms"), eye_shape="barre", screen_u=0.80, screen_v=0.40),
    Variant("regard_serre", "Regard : rapproché",
            base_genome(**{"head.radius": 1.22, "head.squash_y": 0.80,
                           "head.exponent_n1": 0.46, "head.exponent_n2": 0.44,
                           "body.height": 0.92, "body.width": 1.02,
                           "neck.length": 0.16}),
            ("bezel", "arms"), eye_spacing=0.22, eye_size=0.125,
            screen_u=0.80, screen_v=0.40),
    Variant("sans_cadre", "Sans jonc, écran nu",
            base_genome(**{"head.radius": 1.22, "head.squash_y": 0.80,
                           "head.exponent_n1": 0.46, "head.exponent_n2": 0.44,
                           "body.height": 0.92, "body.width": 1.02,
                           "neck.length": 0.16}),
            ("arms",), screen_u=0.80, screen_v=0.42),
]


def build_variant(v: Variant, body_key: str = "blanc-casse",
                  accent_key: str = "cyan") -> Robot:
    t0 = time.perf_counter()
    g = dict(v.genome)
    g["palette.body"] = body_key
    g["palette.accent"] = accent_key
    g["_body_n1"], g["_body_n2"] = v.body_n1, v.body_n2
    d = proportions.dimensions(g)
    body = body_rgb(g)
    accent = accent_rgb(g)

    rig = Rig()
    rig.add(Node("body", parent=ROOT,
                 translation=np.array([0.0, d.body_b, 0.0], dtype="f4")))
    rig.add(Node("neck", parent="body",
                 translation=np.array([0.0, d.body_b + d.neck_h / 2.0, 0.0], dtype="f4")))
    sink = d.head_b * proportions.JOINT_SINK_RATIO
    rig.add(Node("head", parent="neck",
                 translation=np.array([0.0, d.neck_h / 2.0 - sink + d.head_b, 0.0],
                                      dtype="f4")))
    rig.add(Node("head_top", parent="head",
                 translation=np.array([0.0, d.head_b * 1.02, -d.head_c * 0.30],
                                      dtype="f4"),
                 rotation=np.array([-0.30, 0.0, 0.0], dtype="f4")))

    parts: list[Part] = [
        Part("body", "body", superellipsoid(
            a=d.body_a, b=d.body_b, c=d.body_c, n1=v.body_n1, n2=v.body_n2,
            taper=g["body.taper"]), body),
    ]
    if d.neck_h > 0.0 and not v.faceless_head:
        overlap = d.neck_r * proportions.NECK_OVERLAP_RATIO
        parts.append(Part("neck", "neck", superellipsoid(
            a=d.neck_r, b=d.neck_h / 2.0 + overlap, c=d.neck_r,
            n1=0.70, n2=0.90, sectors=20, rings=12), body))
    if v.faceless_head:
        # Monobloc : aucun volume de tête, l'écran est porté par le corps.
        host = FaceHost("body", d.body_a, d.body_b, d.body_c,
                        v.body_n1, v.body_n2, v_center=0.16)
        eye_ref = d.body_width
    else:
        parts.append(Part("head", "head", superellipsoid(
            a=d.head_a, b=d.head_b, c=d.head_c,
            n1=g["head.exponent_n1"], n2=g["head.exponent_n2"]), body))
        host = FaceHost("head", d.head_a, d.head_b, d.head_c,
                        g["head.exponent_n1"], g["head.exponent_n2"],
                        v_center=g["_plate_v"])
        eye_ref = d.head_width

    parts.append(screen_patch(host, v.screen_u, v.screen_v))
    if "bezel" in v.features:
        parts.extend(bezel_parts(host, v.screen_u, v.screen_v,
                                 v.bezel_thickness, body))
    # eye_size est une fraction de la largeur de l'hôte, pas une taille absolue :
    # les pupilles restent ainsi proportionnées quelle que soit la morphologie.
    parts.extend(eye_parts(host, accent, v.eye_spacing,
                           v.eye_size * eye_ref, v.eye_shape))

    if "toptab" in v.features:
        parts.append(top_tab(d, body))
    if "brow" in v.features:
        parts.append(brow(host, body, v.screen_u))
    if "helmet" in v.features:
        parts.append(helmet(d, g, accent))
    if "arms" in v.features:
        # Sur un monobloc, le corps porte aussi l'écran : les bras descendent
        # pour ne pas empiéter dessus.
        for node in arm_nodes(d, v.body_n1, v.body_n2, g["body.taper"],
                              y=-0.34 if v.faceless_head else 0.10):
            rig.add(node)
        parts.extend(arm_parts(d, body))
    if "puck" in v.features:
        parts.append(puck(d, body))
    if "wheels" in v.features:
        parts.extend(wheels(d, body, v.body_n1, g["body.taper"]))
    if "feet" in v.features:
        parts.extend(feet(d, body))
    if "chest" in v.features:
        parts.append(chest_panel(d, g, DARK_TRIM))
    if "chest_accent" in v.features:
        parts.append(chest_panel(d, g, accent))
    if "collar" in v.features and d.neck_h > 0:
        parts.append(collar(d, accent))
    if "shoulders" in v.features:
        parts.extend(shoulders(d, body))
    for feat, count in (("antenna1", 1), ("antenna2", 2)):
        if feat in v.features:
            nodes, ant = antennas(d, accent, body, count)
            for node in nodes:
                rig.add(node)
            parts.extend(ant)

    return Robot(genome=g, dims=d, rig=rig, parts=tuple(parts),
                 outline_width=g["outline.width"], accent=accent,
                 build_ms=(time.perf_counter() - t0) * 1000.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planche d'exploration esthétique")
    ap.add_argument("--cell", type=int, default=300)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--yaw", type=float, default=0.34)
    ap.add_argument("--pitch", type=float, default=0.10)
    ap.add_argument("--bg", type=str, default="#D7D7D3",
                    help="fond de planche : les robots sont clairs, il faut du contraste")
    ap.add_argument("--out", type=Path, default=Path("exploration_designs.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    app = QGuiApplication.instance() or QGuiApplication([])

    rc = RenderContext((args.cell, args.cell), samples=4)
    scene = Scene(rc)
    print(f"rendu sur {rc.info['renderer']} — {len(VARIANTS)} variantes")

    label_h = 30
    rows = (len(VARIANTS) + args.cols - 1) // args.cols
    sheet = QImage(args.cols * args.cell, rows * (args.cell + label_h),
                   QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(QColor(args.bg))

    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(15)
    painter.setFont(font)

    for i, variant in enumerate(VARIANTS):
        robot = build_variant(variant)
        scene.set_robot(robot)
        rc.begin()
        scene.draw(yaw=args.yaw, pitch=args.pitch)
        px = rc.read_rgba().copy()

        cx = (i % args.cols) * args.cell
        cy = (i // args.cols) * (args.cell + label_h)
        tile = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                      QImage.Format.Format_RGBA8888_Premultiplied)
        painter.drawImage(cx, cy, tile)

        painter.setPen(QColor("#2A2A28"))
        painter.drawText(QRect(cx, cy + args.cell - 4, args.cell, label_h),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                         variant.label)
        print(f"  {variant.key:18s} {len(robot.parts):3d} parties  "
              f"{robot.triangle_count:6d} tris  {robot.build_ms:5.1f} ms")
    painter.end()

    ok = sheet.save(str(args.out))
    print(f"\nplanche {'ecrite' if ok else 'ECHEC'} : {args.out} "
          f"({sheet.width()}x{sheet.height()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
