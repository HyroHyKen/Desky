"""Fenêtre du ballon : elle le montre, et elle sent le curseur (lot L12).

Même patron que `ui/dust` et que `ui/item` : une fenêtre à part, translucide,
toujours au-dessus, en **pixels physiques d'écran**. Le ballon traverse
l'écran ; il ne pouvait pas vivre dans la fenêtre du pet.

**Traversante en permanence.** Le joueur frappe le ballon en l'**effleurant du
curseur**, sans cliquer : il n'y a donc aucune raison que cette fenêtre
intercepte quoi que ce soit, et toutes les raisons de s'assurer qu'elle ne le
fera jamais. Un jeu qui vole les clics de l'application du dessous serait pire
que pas de jeu du tout.

**Elle lit la position du curseur elle-même**, plutôt que d'attendre un
événement souris — qu'elle ne recevra jamais, étant traversante. C'est
`GetCursorPos`, le même appel que le hit-testing du pet fait déjà jusqu'à
60 fois par seconde ; en ajouter un par image pendant une partie ne change rien
au budget du §3, et la partie est de toute façon en régime interactif.

Le ballon est **dessiné**, pas rendu en 3D : un ovale, un nœud, un reflet. Le
moteur toon sait faire des robots, et lui demander une baudruche coûterait une
géométrie, une passe et un shader pour un objet qui tient en quinze lignes de
`QPainter`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ..app import win32
from ..games.balloon import Balloon

# Marge autour du ballon, en rayons : le reflet et le nœud débordent, et une
# fenêtre au ras du disque les rognerait.
MARGIN = 0.55

# Couleurs. Le ballon n'est **pas** génétique : c'est un accessoire de jeu, pas
# une partie du robot, et il doit rester lisible sur n'importe quel bureau.
SKIN = QColor(232, 86, 104)
SKIN_DARK = QColor(176, 48, 70)
SHEEN = QColor(255, 236, 240, 205)
STRING = QColor(120, 60, 72, 170)

# Teinte du tour : le ballon **dit à qui c'est**. Sans ce signal, l'alternance
# stricte serait une règle invisible, et rater son tour ressemblerait à un bug.
MINE = QColor(31, 168, 186)          # à vous — le cyan du produit


class BalloonWindow(QWidget):
    """Le ballon, sa fenêtre, et la détection du curseur."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.balloon: Balloon | None = None
        self.player_turn = False
        self._origin = (0.0, 0.0)
        self._dpr = 1.0
        self._armed = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # -- suivi ---------------------------------------------------------------

    def follow(self, balloon: Balloon, player_turn: bool) -> None:
        """Replace la fenêtre sur le ballon et redessine.

        Appelée à chaque image : le ballon bouge vite, et une fenêtre qui
        traînerait d'une image le ferait apparaître décalé de vingt pixels.
        """
        self.balloon = balloon
        self.player_turn = player_turn
        r = balloon.radius * (1.0 + MARGIN)
        x, y = balloon.x - r, balloon.y - r
        cote = max(1, int(2.0 * r / max(1e-6, self._dpr)))

        self._origin = (x, y)
        if self.size().width() != cote:
            self.setFixedSize(cote, cote)
        if not self.isVisible():
            self.show()
            win32.set_click_through(int(self.winId()), True)
            self._armed = True
        win32.set_window_pos(int(self.winId()), round(x), round(y))
        self.update()

    def set_dpr(self, dpr: float) -> None:
        self._dpr = max(1e-6, float(dpr))

    def hide_balloon(self) -> None:
        self.balloon = None
        if self.isVisible():
            self.hide()

    @staticmethod
    def cursor_touches(balloon: Balloon) -> bool:
        """Le curseur est-il dans le ballon, maintenant ?

        Lu directement plutôt que reçu : la fenêtre étant traversante, aucun
        événement souris ne lui parviendra jamais. C'est le même appel que le
        hit-testing du pet, et il coûte quelques microsecondes.
        """
        cx, cy = win32.get_cursor_pos()
        return balloon.contains(float(cx), float(cy))

    # -- peinture ------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        ballon = self.balloon
        if ballon is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        ox, oy = self._origin
        k = 1.0 / self._dpr
        cx = (ballon.x - ox) * k
        cy = (ballon.y - oy) * k
        r = ballon.radius * k

        # Écrasement à la frappe, et étirement dans la chute : le même
        # vocabulaire qu'au lot L10. Une baudruche est l'objet le plus mou du
        # produit ; la voir rigide serait le seul endroit où le §10 manquerait.
        squash = ballon.squash
        vitesse = min(1.0, abs(ballon.vy) / max(1.0, 3.0 * ballon.pet_h))
        rx = r * (1.0 + 0.30 * squash - 0.10 * vitesse)
        ry = r * (1.0 - 0.26 * squash + 0.14 * vitesse)

        # Ficelle : elle pend et suit le mouvement, parce qu'un ballon sans
        # ficelle est une balle.
        penche = math.atan2(ballon.vx, max(1.0, abs(ballon.vy) + 60.0))
        painter.setPen(QPen(STRING, max(1.0, r * 0.07)))
        painter.drawLine(QPointF(cx, cy + ry * 0.92),
                         QPointF(cx - math.sin(penche) * r * 0.55,
                                 cy + ry * 1.5))

        boite = QRectF(cx - rx, cy - ry, 2.0 * rx, 2.0 * ry)
        degrade = QRadialGradient(cx - rx * 0.32, cy - ry * 0.38, r * 1.55)
        degrade.setColorAt(0.0, SKIN)
        degrade.setColorAt(1.0, SKIN_DARK)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(degrade)
        painter.drawEllipse(boite)

        # Anneau du tour, à l'extérieur du ballon pour ne pas le salir.
        if self.player_turn:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(MINE, max(1.5, r * 0.11)))
            painter.drawEllipse(boite.adjusted(-r * 0.20, -r * 0.20,
                                               r * 0.20, r * 0.20))

        # Reflet, et le petit nœud sous le ballon.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SHEEN)
        painter.drawEllipse(QRectF(cx - rx * 0.46, cy - ry * 0.58,
                                   rx * 0.42, ry * 0.30))
        painter.setBrush(SKIN_DARK)
        painter.drawEllipse(QPointF(cx, cy + ry * 0.94), r * 0.10, r * 0.09)
        painter.end()
