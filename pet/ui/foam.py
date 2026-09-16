"""La mousse du bain, peinte par-dessus le robot (lot L15).

**Pourquoi au pinceau et non dans la passe GL.** Le hit-testing lit l'alpha de
la frame rendue (`_on_hit_test`) : de la mousse écrite dans le FBO agrandirait
la zone cliquable du robot au fil du savonnage, et on finirait par l'attraper en
visant à côté. Peinte après coup par `QPainter`, elle se voit sans rien changer
à ce qu'on peut saisir — c'est la même raison qui a sorti les particules du lot
L11 du rendu du robot.

**Les coordonnées sont normalisées**, et c'est ce qui fait tenir la mousse en
place : le robot respire, cligne, et sa fenêtre peut changer de DPI en
traversant deux écrans. Un flocon posé en pixels aurait glissé à chaque
respiration.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter

# Blanc légèrement bleuté : de la mousse pure blanche disparaît sur les robots
# clairs, et le bleu est la couleur que tout le monde associe au savon.
FOAM = QColor(238, 246, 255)
FOAM_EDGE = QColor(176, 203, 232)
SHINE = QColor(255, 255, 255)

# Opacité de l'amas. En dessous, la mousse a l'air d'un halo ; au-dessus, elle
# cache le robot qu'on est précisément en train de regarder.
ALPHA = 0.86
EDGE_ALPHA = 0.34

# Reflet, en part du rayon du flocon : décalé en haut à gauche, comme si la
# lumière venait de là — la même convention que l'ombre de contact du §8.
SHINE_R = 0.30
SHINE_OFFSET = (-0.26, -0.28)


def paint(painter: QPainter, foam, width: float, height: float) -> None:
    """Peint les flocons sur un painter déjà ouvert sur la fenêtre du pet.

    `width` et `height` sont la taille **logique** de la fenêtre. Le rayon est
    exprimé en largeurs de robot, comme dans le modèle, donc il se convertit
    avec `width` sur les deux axes : c'est ce qui garde les flocons ronds.
    """
    if not foam:
        return

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(0, 0, 0, 0))

    for flocon in foam:
        rayon = flocon.r * width * flocon.scale
        if rayon <= 0.4:
            continue
        opacite = max(0.0, min(1.0, flocon.fade))
        centre = QPointF(flocon.u * width, flocon.v * height)

        bord = QColor(FOAM_EDGE)
        bord.setAlphaF(EDGE_ALPHA * opacite)
        painter.setBrush(bord)
        painter.drawEllipse(centre, rayon, rayon)

        corps = QColor(FOAM)
        corps.setAlphaF(ALPHA * opacite)
        painter.setBrush(corps)
        painter.drawEllipse(centre, rayon * 0.86, rayon * 0.86)

        reflet = QColor(SHINE)
        reflet.setAlphaF(0.75 * opacite)
        painter.setBrush(reflet)
        painter.drawEllipse(
            QPointF(centre.x() + SHINE_OFFSET[0] * rayon,
                    centre.y() + SHINE_OFFSET[1] * rayon),
            rayon * SHINE_R, rayon * SHINE_R)

    painter.restore()
