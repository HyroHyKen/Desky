"""Passe toon (CDC §8).

Équivalent fonctionnel de `MeshToonMaterial` : diffus lambertien quantifié par
une rampe de dégradé, spéculaire dur seuillé, rim light. Caméra
**orthographique**, ce qui donne une silhouette stable, évite la distorsion de
perspective sur un objet proche et rend l'épaisseur du contour constante sans
compensation.

Passe pure depuis le lot L3 : elle ne possède ni géométrie ni cadrage, seulement
son programme et sa rampe. Les tampons et l'ordre des passes appartiennent à
`render/scene.py` — la passe qui les détenait devenait maîtresse des autres.
"""

from __future__ import annotations

import moderngl
import numpy as np

# Rampe de dégradé : cinq paliers. Le CDC §8 prescrit 4 à 6 pixels.
RAMP = (0.40, 0.60, 0.78, 0.91, 1.00)

SPEC_COLOR = (0.35, 0.35, 0.33)
LIGHT_DIR = (-0.40, 0.78, 0.55)
SHININESS = 24.0
RIM_START, RIM_END = 0.55, 0.95

# Part de l'accent du génome reprise par le rim light. Le liseré coloré du bord
# est ce qui rattache la silhouette à la teinte du robot sans repeindre le corps.
RIM_FROM_ACCENT = 0.42


class ToonPass:
    """Programme et rampe. La géométrie vient de l'appelant."""

    def __init__(self, ctx: moderngl.Context, program: moderngl.Program) -> None:
        self.ctx = ctx
        self.program = program
        self.gradient = self._make_gradient(ctx)

        program["uSpecColor"].value = SPEC_COLOR
        program["uLightDir"].value = LIGHT_DIR
        program["uShininess"].value = SHININESS
        program["uRimStart"].value = RIM_START
        program["uRimEnd"].value = RIM_END
        program["uGradientMap"].value = 0

    @staticmethod
    def _make_gradient(ctx: moderngl.Context) -> moderngl.Texture:
        """Rampe en filtrage NEAREST + CLAMP_TO_EDGE (CDC §8).

        C'est le filtrage nearest, et non la rampe elle-même, qui produit les
        paliers nets caractéristiques du toon.
        """
        steps = np.array(RAMP, dtype="f4")
        pixels = (np.repeat(steps[:, None], 3, axis=1) * 255).astype("u1")
        tex = ctx.texture((len(RAMP), 1), 3, pixels.tobytes())
        tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        tex.repeat_x = False
        tex.repeat_y = False
        return tex

    def configure(self, accent: tuple[float, float, float]) -> None:
        """Fixe ce qui ne dépend que du robot. Appelé au changement de génome."""
        self.program["uRimColor"].value = tuple(c * RIM_FROM_ACCENT for c in accent)

    def begin(self, scale: float) -> None:
        self.gradient.use(0)
        self.program["uScale"].value = scale

    def draw(self, vao: moderngl.VertexArray, mvp: np.ndarray,
             model: np.ndarray, color: tuple[float, float, float]) -> None:
        normal_mat = np.linalg.inv(model[:3, :3]).T.astype("f4")
        self.program["uMVP"].write(np.ascontiguousarray(mvp.T).tobytes())
        self.program["uNormalMat"].write(np.ascontiguousarray(normal_mat.T).tobytes())
        self.program["uBaseColor"].value = color
        vao.render(moderngl.TRIANGLES)

    def release(self) -> None:
        self.gradient.release()
