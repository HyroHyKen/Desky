"""Bulle de besoin (lot L6 phase B).

Le pet exprime un besoin par un sigle dans une petite bulle au-dessus de sa
tête ; cliquer dessus affiche deux sigles à la place de ses yeux. C'est par ses
yeux qu'il parle, et il n'écrit jamais rien.

**Rendue en GL et non par QPainter**, bien qu'elle soit un élément d'interface.
Deux raisons, et la première est structurelle : la fenêtre décide de sa surface
cliquable en relisant l'alpha du dernier tampon rendu (lot L1), donc une bulle
peinte par-dessus ne serait pas cliquable. La seconde est la cohérence : les
sigles sont déjà des SDF pour les yeux, et les partager garantit que les deux
surfaces se ressemblent.

La bulle vit dans le bandeau que le cadrage réserve au-dessus du robot (cf.
`scene.BUBBLE_HEADROOM`) : la fenêtre ne change pas de taille pour autant.
"""

from __future__ import annotations

import moderngl
import numpy as np

# Rayon de la bulle, en part de la hauteur de rendu. Choisi pour tenir dans le
# bandeau réservé avec un peu de jeu : une bulle qui touche le bord haut de la
# fenêtre serait rognée, la fenêtre n'ayant pas de marge.
RADIUS_RATIO = 0.115

# Décalage horizontal, en rayons de bulle. Légèrement à droite de l'axe : une
# bulle parfaitement centrée sur la tête lit comme un chapeau.
OFFSET_X = 0.95

# Couleurs. Fixes et non génétiques : c'est de l'interface, et elle doit rester
# lisible quelle que soit la teinte du robot tiré.
FILL = (0.97, 0.975, 0.98)
INK = (0.10, 0.13, 0.17)


class BubblePass:
    """Quad aligné sur l'écran, placé en pixels de rendu."""

    def __init__(self, ctx: moderngl.Context, program: moderngl.Program) -> None:
        self.ctx = ctx
        self.program = program
        corners = np.array([
            [-1.0, -1.0], [1.0, -1.0], [-1.0, 1.0],
            [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0],
        ], dtype="f4")
        self.vbo = ctx.buffer(corners.tobytes())
        self.vao = ctx.vertex_array(program, [(self.vbo, "2f", "in_corner")])
        program["uFill"].value = FILL
        program["uInk"].value = INK

    def draw(self, viewport: tuple[int, int], anchor: tuple[float, float],
             glyph: int, opacity: float, scale: float = 1.0,
             pulse: float = 0.0) -> None:
        """Dessine la bulle. `anchor` est en pixels de rendu, origine en haut.

        Ne dessine rien pour un sigle nul ou une opacité nulle : c'est le cas
        courant — la bulle n'apparaît que lorsqu'un besoin est bas — et il ne
        doit rien coûter.
        """
        if glyph <= 0 or opacity <= 0.001:
            return

        w, h = viewport
        radius = RADIUS_RATIO * h
        cx = anchor[0] + OFFSET_X * radius
        # Recentré vers le bas de la bulle : `anchor` désigne le milieu du
        # bandeau, et la queue doit descendre vers la tête.
        cy = anchor[1]

        self.program["uViewportPx"].value = (float(w), float(h))
        self.program["uCenterPx"].value = (float(cx), float(cy))
        self.program["uRadiusPx"].value = float(radius)
        self.program["uGlyph"].value = int(glyph)
        self.program["uOpacity"].value = float(max(0.0, min(1.0, opacity)))
        self.program["uScale"].value = float(max(0.0, scale))
        self.program["uPulse"].value = float(max(0.0, min(1.0, pulse)))

        # Sans test de profondeur : la bulle est au-dessus de tout, et le
        # bandeau est vide par construction.
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.vao.render(moderngl.TRIANGLES)

    def hit(self, viewport: tuple[int, int], anchor: tuple[float, float],
            point: tuple[float, float]) -> bool:
        """Le point est-il dans la bulle ? En pixels de rendu.

        Un test de boîte et non la SDF exacte : la fenêtre a déjà son test
        d'alpha au pixel pour décider de la traversée des clics, et ce test-ci
        ne sert qu'à distinguer « clic sur la bulle » de « clic sur le robot ».
        Une boîte un peu généreuse est ici une qualité — une bulle de trente
        pixels doit se cliquer sans viser.
        """
        _, h = viewport
        radius = RADIUS_RATIO * h
        cx = anchor[0] + OFFSET_X * radius
        cy = anchor[1]
        return (abs(point[0] - cx) <= radius
                and abs(point[1] - cy) <= radius * 1.05)

    def release(self) -> None:
        self.vao.release()
        self.vbo.release()
        self.program.release()
