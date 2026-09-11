"""Passe de contour par inverted hull (CDC §8).

Chaque partie est rendue une seconde fois, sommets déplacés le long de leur
normale, en couleur plate sombre, avec les faces avant écartées et le test de
profondeur actif. Seule la frange dépassant de la silhouette subsiste.

Cette méthode est **imposée** par le CDC sur une alternative post-process de
détection de bords : elle ne requiert ni depth buffer ni normal buffer
supplémentaires, et surtout elle se comporte correctement contre un fond
transparent, là où une détection de contours produirait des artefacts sur tout
le pourtour de la silhouette.

Deux points propres à ce projet :

- **Épaisseur en pixels, pas en unités monde.** Le cadrage du robot varie avec
  sa morphologie ; une extrusion en unités monde donnerait un trait plus fin sur
  un robot élancé. L'épaisseur est donc convertie depuis une consigne en pixels,
  ce qui rend le trait génétique du §17.3 réellement comparable d'un robot à
  l'autre.
- **Les coques ouvertes sont exclues.** Extruder la coque faciale ferait
  apparaître un liseré sur tout le pourtour du rectangle de l'écran, puisque son
  bord franc n'a pas de face arrière pour le masquer.
"""

from __future__ import annotations

import moderngl

# Épaisseur de référence, en pixels, pour un trait génétique à 1.0.
BASE_WIDTH_PX = 2.4

OUTLINE_COLOR = (0.055, 0.060, 0.075)


class OutlinePass:
    """Programme et réglages du contour. Les VBO appartiennent à la scène."""

    def __init__(self, ctx: moderngl.Context, program: moderngl.Program) -> None:
        self.ctx = ctx
        self.program = program
        self.program["uOutlineColor"].value = OUTLINE_COLOR

    def world_width(self, half_extent: float, height_px: int,
                    genetic_width: float) -> float:
        """Convertit une épaisseur en pixels vers des unités monde.

        La caméra étant orthographique, la demi-hauteur de vue `half_extent`
        couvre exactement la moitié de la hauteur de rendu : un pixel vaut donc
        `2 · half_extent / height_px` en unités monde, indépendamment de la
        profondeur. C'est cette propriété qui donne un contour d'épaisseur
        constante sans compensation.
        """
        if height_px <= 0:
            return 0.0
        world_per_px = 2.0 * half_extent / float(height_px)
        return BASE_WIDTH_PX * genetic_width * world_per_px

    def begin(self, cull: int) -> None:
        """Active le culling attendu par l'inverted hull.

        `cull` est déterminé par l'enroulement effectif des maillages, mesuré et
        non déduit : le sens d'enroulement dépend de l'inversion de l'axe Y dans
        la projection, et se tromper donne un aplat sombre au lieu d'un trait.
        """
        self.ctx.enable(moderngl.CULL_FACE)
        self.ctx.cull_face = cull

    def end(self) -> None:
        self.ctx.disable(moderngl.CULL_FACE)
