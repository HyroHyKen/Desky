"""Visage : rendu SDF et expressions (CDC §9).

Le visage n'est pas de la géométrie. C'est la coque bombée produite par le lot
L2, dont le fragment shader dessine les yeux par SDF, en émissif non éclairé.
Ce module ne fait que deux choses : traduire le génome en forme de regard, et
porter les **expressions**, c'est-à-dire des jeux nommés de valeurs d'uniformes.

« Les transitions sont interpolées, jamais instantanées » (CDC §9). D'où
`FaceState`, qui sait s'interpoler vers une cible. Ce module fournit le mélange ;
c'est le lot L4 qui décidera *quand* et *à quelle vitesse* mélanger, et le lot L6
qui choisira l'expression depuis le comportement.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any

import moderngl
import numpy as np

# Le halo additif : la lueur d'une dalle émissive déborde légèrement.
GLOW = 0.42

# Traduction du génome vers l'espace UV de la dalle. Toutes trois sont des
# constantes de réglage, pas des gènes : le génome dit l'identité du regard, ces
# facteurs disent comment cette identité se lit dans la dalle.
SIZE_SCALE = 0.85       # eye.size -> demi-hauteur, en part de la demi-dalle
EYE_ASPECT = 0.55       # largeur/hauteur d'une pupille
SPACING_SPAN = 0.72     # eye.spacing -> écart au centre, en part de la demi-dalle


@dataclass(frozen=True)
class FaceState:
    """Les sept commandes du CDC §9, plus le regard.

    Toutes continues et toutes interpolables : c'est ce qui permet à une
    expression d'être une simple cible, et à une transition d'être un mélange.
    """

    blink: float = 0.0          # 0 → 1, écrasement vertical de la paupière
    gaze_x: float = 0.0         # décalage des pupilles
    gaze_y: float = 0.0
    lid_top: float = 0.0        # occlusion haute → colère
    lid_bottom: float = 0.0     # occlusion basse → somnolence
    squint: float = 0.0         # plissement → joie, méfiance
    pupil_scale: float = 1.0    # dilatation → surprise, affection
    glitch: float = 0.0         # bruit de balayage → réveil, saturation

    def lerp(self, other: FaceState, t: float) -> FaceState:
        """Mélange linéaire de deux états.

        Linéaire **ici** est correct : ce sont les courbes de `t` fournies par le
        lot L4 qui portent l'easing, et non ce mélange. Le CDC §10 interdit
        l'interpolation linéaire d'un mouvement visible dans le temps, pas le
        mélange de deux jeux de paramètres.
        """
        t = max(0.0, min(1.0, t))
        return FaceState(**{
            f.name: getattr(self, f.name) * (1.0 - t) + getattr(other, f.name) * t
            for f in fields(self)
        })

    def with_gaze(self, x: float, y: float) -> FaceState:
        return replace(self, gaze_x=x, gaze_y=y)


# Expressions : des jeux nommés, rien de plus (CDC §9). Le comportement du lot
# L6 les désignera par leur nom ; aucune n'est câblée dans le shader.
EXPRESSIONS: dict[str, FaceState] = {
    "neutre": FaceState(),
    "curieux": FaceState(pupil_scale=1.12, squint=0.05),
    "joyeux": FaceState(squint=0.55, pupil_scale=1.05, lid_bottom=0.18),
    "surpris": FaceState(pupil_scale=1.42, lid_top=-0.10),
    "affectueux": FaceState(pupil_scale=1.30, squint=0.30, lid_bottom=0.10),
    "mefiant": FaceState(squint=0.42, lid_top=0.26, pupil_scale=0.92),
    "fache": FaceState(lid_top=0.46, squint=0.20, pupil_scale=0.88),
    "somnolent": FaceState(lid_bottom=0.44, lid_top=0.20, pupil_scale=0.95),
    "endormi": FaceState(blink=0.90, lid_bottom=0.30),
    "reveil": FaceState(glitch=0.85, pupil_scale=1.20),
    "ennuye": FaceState(lid_top=0.30, lid_bottom=0.12, pupil_scale=0.94),
}


class FacePass:
    """Programme du visage et traduction du génome en forme de regard."""

    def __init__(self, ctx: moderngl.Context, program: moderngl.Program) -> None:
        self.ctx = ctx
        self.program = program
        self.program["uGlow"].value = GLOW
        self._aspect = 1.0

    def configure(self, genome: dict[str, Any], mesh_bounds, screen_color,
                  eye_color) -> None:
        """Fixe ce qui ne dépend que du génome. Appelé au changement de robot.

        L'aspect est mesuré sur les bornes réelles de la coque, pas déduit de
        ses paramètres angulaires : c'est lui qui rend l'espace du shader
        isotrope, et une approximation y déformerait les yeux.
        """
        lo, hi = mesh_bounds
        width = float(hi[0] - lo[0])
        height = float(hi[1] - lo[1])
        self._aspect = width / height if height > 1e-6 else 1.0

        self.program["uAspect"].value = self._aspect
        self.program["uScreenColor"].value = tuple(screen_color)
        self.program["uEyeColor"].value = tuple(eye_color)

        # Le génome donne l'identité du regard (CDC §7). Les valeurs sont
        # exprimées en unités de hauteur de coque, l'aspect étant déjà appliqué.
        # `eye.size` et `eye.spacing` sont donnés « en part de dalle » par le
        # CDC §7 : ce sont donc déjà des fractions, et les multiplier par 2,1
        # comme au premier essai donnait une demi-hauteur de 58 % de la dalle —
        # les deux pupilles se recouvraient en un seul pavé.
        spacing = float(genome["eye.spacing"])
        size = float(genome["eye.size"])
        self.program["uEyeSpacing"].value = spacing * self._aspect * SPACING_SPAN
        self.program["uEyeSize"].value = size * SIZE_SCALE
        self.program["uEyeAspect"].value = EYE_ASPECT
        self.program["uCornerRadius"].value = float(genome["eye.corner_radius"])
        # Dalle symétrique depuis le lot L3 : le centre du regard est le centre.
        self.program["uEyeCenterY"].value = 0.0

    def draw(self, vao: moderngl.VertexArray, mvp: np.ndarray,
             state: FaceState, scale: float, time_s: float,
             glyphs: tuple[int, int] = (0, 0), glyph_mix: float = 0.0) -> None:
        self.program["uMVP"].write(np.ascontiguousarray(mvp.T).tobytes())
        self.program["uScale"].value = scale
        self.program["uTime"].value = time_s

        self.program["uGlyphLeft"].value = int(glyphs[0])
        self.program["uGlyphRight"].value = int(glyphs[1])
        self.program["uGlyphMix"].value = float(max(0.0, min(1.0, glyph_mix)))

        self.program["uBlink"].value = state.blink
        self.program["uGaze"].value = (state.gaze_x, state.gaze_y)
        self.program["uLidTop"].value = state.lid_top
        self.program["uLidBottom"].value = state.lid_bottom
        self.program["uSquint"].value = state.squint
        self.program["uPupilScale"].value = state.pupil_scale
        self.program["uGlitch"].value = state.glitch

        vao.render(moderngl.TRIANGLES)
