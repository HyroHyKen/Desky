"""Ombre de contact (CDC §8).

« Une ellipse floutée en alpha, rendue sous le robot, dont l'opacité et le rayon
suivent sa hauteur. Élément peu coûteux et déterminant pour l'ancrage visuel. »

La hauteur en question est celle du robot au-dessus du sol : au lot L1, le pet
peut être attrapé et lâché, et il retombe. Une ombre qui ne réagit pas à cette
hauteur trahit immédiatement le truquage — c'est elle qui dit au spectateur que
l'objet est en l'air.

Module hors de la liste du CDC §5, qui range l'ombre dans la section rendu sans
lui donner de fichier. Elle a sa géométrie, son shader et ses réglages propres :
la diluer dans la passe toon aurait mélangé deux choses sans rapport.
"""

from __future__ import annotations

import moderngl
import numpy as np

# Rayon de l'ombre au contact, en part de la demi-largeur du robot.
BASE_RADIUS = 1.02

# Aplatissement vertical de l'ellipse. Le quad étant aligné sur l'écran (cf.
# shadow.vert.glsl), cette valeur est ce qui la fait lire comme posée au sol et
# non comme un disque planté à la verticale.
SQUASH = 0.30

SHADOW_COLOR = (0.055, 0.065, 0.085)
OPACITY = 0.40
FALLOFF = 2.1

# Hauteur, en part de la hauteur du robot, à laquelle l'ombre a fini de se
# diluer. Au-delà, elle ne bouge plus : un pet tenu très haut garde une trace
# faible plutôt que de disparaître, ce qui serait plus déroutant qu'utile.
LIFT_RANGE = 0.9


class ShadowPass:
    """Quad au sol, avec sa propre géométrie — indépendante du robot."""

    def __init__(self, ctx: moderngl.Context, program: moderngl.Program) -> None:
        self.ctx = ctx
        self.program = program
        corners = np.array([
            [-1.0, -1.0], [1.0, -1.0], [-1.0, 1.0],
            [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0],
        ], dtype="f4")
        self.vbo = ctx.buffer(corners.tobytes())
        self.vao = ctx.vertex_array(program, [(self.vbo, "2f", "in_corner")])

        program["uShadowColor"].value = SHADOW_COLOR
        program["uSquash"].value = SQUASH
        program["uFalloff"].value = FALLOFF

    def draw(self, mvp: np.ndarray, center: tuple[float, float, float],
             half_width: float, robot_height: float, lift: float = 0.0) -> None:
        """Dessine l'ombre. `lift` est la hauteur du robot au-dessus du sol.

        `mvp` doit être **sans la rotation** du robot : le quad est aligné sur
        l'écran, et le faire tourner avec le pet le ferait basculer sur la
        tranche.

        Le rendu se fait **sans écriture de profondeur** : l'ombre est au sol,
        donc exactement au niveau des pieds du robot, et disputer le test de
        profondeur avec eux produirait du z-fighting. Elle est simplement
        dessinée en premier.
        """
        t = 0.0
        if robot_height > 1e-6:
            t = min(1.0, max(0.0, lift / (robot_height * LIFT_RANGE)))

        # Plus le robot monte, plus l'ombre s'élargit et s'efface.
        self.program["uMVP"].write(np.ascontiguousarray(mvp.T).tobytes())
        self.program["uCenter"].value = center
        self.program["uRadius"].value = half_width * BASE_RADIUS * (1.0 + 0.55 * t)
        self.program["uOpacity"].value = OPACITY * (1.0 - 0.72 * t)

        self.ctx.depth_mask = False
        try:
            self.vao.render(moderngl.TRIANGLES)
        finally:
            self.ctx.depth_mask = True

    def release(self) -> None:
        self.vao.release()
        self.vbo.release()
