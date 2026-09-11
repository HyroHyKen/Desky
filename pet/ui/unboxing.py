"""Le carton du premier lancement (lot L6 phase B).

« Au milieu de son écran tombera d'en haut un carton ; dès qu'il clique dessus,
le carton s'ouvre et se dissipe tandis que le robot en sort. »

Trois états, et un clic pour passer du premier au troisième : `falling`, puis
`waiting` — le carton a rebondi et attend —, puis `opening`. La fenêtre se
supprime toute seule à la fin.

**Dessiné par QPainter, en polygones, et non modélisé dans le pipeline toon.**
C'est un écart par rapport à ce que le cadrage du lot annonçait, et il mérite sa
justification. L'argument qui plaidait pour le pipeline toon était d'éviter une
chaîne d'assets pour un seul écran — or du tracé vectoriel n'est pas un asset :
il n'y a ni fichier, ni import, ni conversion. En face, la modélisation
demandait un maillage de caisse, quatre rabats articulés dans un rig, une
seconde animation, et un second contexte ModernGL autonome. Le cadrage avait
identifié ce poste comme le plus incertain en charge de toute la phase ; il
l'était. Et le langage visuel s'y retrouve quand même : le rendu toon est fait
d'aplats et d'un contour sombre, ce qu'un polygone tracé par Qt donne
directement.

La fenêtre est **petite et se déplace**, plutôt que de couvrir l'écran : un
voile plein écran, même transparent, intercepterait les clics du bureau. Elle
descend comme le pet lui-même descend quand on le lâche (lot L1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

# Taille de la fenêtre du carton, en pixels logiques. Assez large pour les
# rabats grands ouverts, qui débordent nettement de la caisse.
WIDTH = 260
HEIGHT = 260

# Caisse, dans la fenêtre.
BOX_W = 150
BOX_H = 112
BOX_TOP = 118

# Chute : mêmes valeurs de sensation que la chute du pet au lot L1, exprimées
# ici en pixels logiques par seconde.
GRAVITY = 1900.0
RESTITUTION = 0.30
REST_SPEED = 90.0

# Ouverture, puis dissipation. L'ouverture est vive, la dissipation lente : le
# geste doit avoir une réponse immédiate, et la disparition doit laisser le
# temps de voir le robot arriver.
OPEN_SECONDS = 0.34
FADE_SECONDS = 0.62
OPEN_ANGLE = 122.0

# Écrasement à l'impact, en part de la hauteur de caisse.
SQUASH = 0.16
SQUASH_DECAY = 5.5

CARDBOARD = QColor(198, 154, 100)
CARDBOARD_DARK = QColor(170, 128, 79)
CARDBOARD_LIGHT = QColor(214, 175, 124)
INTERIOR = QColor(96, 70, 44)
TAPE = QColor(226, 210, 182)
INK = QColor(38, 30, 22)
STROKE = 3.0


@dataclass
class _Flap:
    """Un rabat : son côté (-1 gauche, +1 droite) et sa longueur."""

    side: int
    length: float


FLAPS = (_Flap(-1, BOX_W * 0.5), _Flap(1, BOX_W * 0.5))


class Unboxing(QWidget):
    """Le carton. Émet `opened` au clic, puis `finished` quand il a disparu."""

    opened = Signal()
    finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(WIDTH, HEIGHT)

        self.state = "falling"
        self._y = 0.0
        self._target_y = 0.0
        self._vy = 0.0
        self._squash = 0.0
        self._open = 0.0
        self._fade = 0.0
        self._x = 0.0

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # -- cycle de vie ------------------------------------------------------

    def start(self, center_x: int, target_y: int, screen_top: int = 0) -> None:
        """Lâche le carton **depuis le haut de l'écran**, vers `target_y`.

        `target_y` est le haut de la fenêtre à l'arrivée, `screen_top` le bord
        haut de l'écran, tous deux en pixels logiques.

        Le départ est calé sur le bord de l'écran et non à une hauteur fixe
        au-dessus de la cible : le carton doit **entrer dans le champ**, ce qui
        veut dire venir de hors-champ. Lâché deux cent quarante pixels plus
        haut, il apparaissait déjà à moitié descendu.
        """
        self._x = float(center_x) - WIDTH / 2.0
        self._target_y = float(target_y)
        self._y = min(self._target_y - HEIGHT * 0.6,
                      float(screen_top) - HEIGHT)
        self._vy = 0.0
        self.state = "falling"
        self.move(int(self._x), int(self._y))
        self.show()
        self._timer.start()

    def _tick(self) -> None:
        dt = self._timer.interval() / 1000.0

        if self.state == "falling":
            self._vy += GRAVITY * dt
            self._y += self._vy * dt
            if self._y >= self._target_y:
                self._y = self._target_y
                if abs(self._vy) < REST_SPEED:
                    self._vy = 0.0
                    self.state = "waiting"
                else:
                    # Le rebond emporte l'écrasement avec lui : c'est
                    # l'écrasement qui donne le poids, pas la hauteur du rebond.
                    self._squash = min(1.0, abs(self._vy) / 900.0)
                    self._vy = -self._vy * RESTITUTION
            self.move(int(self._x), int(self._y))

        elif self.state == "opening":
            self._open = min(1.0, self._open + dt / OPEN_SECONDS)
            # La dissipation démarre une fois les rabats bien écartés, sinon on
            # ne voit pas le carton s'ouvrir, seulement s'effacer.
            if self._open > 0.45:
                self._fade = min(1.0, self._fade + dt / FADE_SECONDS)
            if self._fade >= 1.0:
                self._timer.stop()
                self.hide()
                self.finished.emit()
                return

        self._squash = max(0.0, self._squash - SQUASH_DECAY * dt * self._squash
                           - 0.01)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self.state != "waiting":
            return
        if not self._box_rect().contains(event.position()):
            return
        self.state = "opening"
        self.opened.emit()

    # -- dessin ------------------------------------------------------------

    def _box_rect(self) -> QRectF:
        """Caisse à l'écran, écrasement compris.

        L'écrasement conserve le bord bas : une caisse qui s'aplatit se tasse
        sur le sol, elle ne rétrécit pas autour de son centre.
        """
        h = BOX_H * (1.0 - SQUASH * self._squash)
        w = BOX_W * (1.0 + 0.5 * SQUASH * self._squash)
        bas = BOX_TOP + BOX_H
        return QRectF((WIDTH - w) / 2.0, bas - h, w, h)

    def _flap_polygon(self, flap: _Flap, rect: QRectF) -> QPolygonF:
        """Rabat articulé sur le bord haut de la caisse.

        Fermé, il est horizontal et rejoint son voisin au milieu ; ouvert, il
        pointe vers l'extérieur. La perspective est feinte par un simple
        raccourcissement vertical — un vrai rabat en trois dimensions
        demanderait le pipeline que ce module a justement écarté.
        """
        angle = math.radians(OPEN_ANGLE * self._open)
        charniere = QPointF(rect.center().x() + flap.side * rect.width() / 2.0,
                            rect.top())
        # Fermé, le rabat pointe **vers l'intérieur** — d'où le signe négatif —
        # et rejoint son voisin au milieu du couvercle. Au-delà de quatre-vingt-
        # dix degrés le cosinus change de signe et il repart vers l'extérieur,
        # ce qui donne le basculement complet sans cas particulier.
        dx = -flap.side * flap.length * math.cos(angle) * (rect.width() / BOX_W)
        dy = -flap.length * math.sin(angle)
        bout = QPointF(charniere.x() + dx, charniere.y() + dy)

        # Épaisseur du rabat, perpendiculaire à sa longueur.
        epaisseur = 13.0
        nx = -dy
        ny = dx
        norme = max(1e-3, math.hypot(nx, ny))
        nx, ny = nx / norme * epaisseur * 0.5, ny / norme * epaisseur * 0.5

        return QPolygonF([
            QPointF(charniere.x() + nx, charniere.y() + ny),
            QPointF(bout.x() + nx, bout.y() + ny),
            QPointF(bout.x() - nx, bout.y() - ny),
            QPointF(charniere.x() - nx, charniere.y() - ny),
        ])

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(1.0 - self._fade)

        rect = self._box_rect()
        pen = QPen(INK, STROKE)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # Ombre de contact d'abord, comme le pet en a une (§8) : sans elle la
        # caisse flotte, et peinte après elle se retrouve **par-dessus**.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(40, 34, 26, 46))
        painter.drawEllipse(QRectF(rect.center().x() - rect.width() * 0.46,
                                   rect.bottom() - 6, rect.width() * 0.92, 13))

        # Intérieur, visible dès que les rabats s'écartent.
        if self._open > 0.02:
            creux = QRectF(rect.left() + 8, rect.top() - 6,
                           rect.width() - 16, 26)
            painter.setPen(pen)
            painter.setBrush(INTERIOR)
            painter.drawRoundedRect(creux, 5, 5)

        # Rabats derrière la caisse tant qu'ils sont peu ouverts, devant
        # ensuite : c'est ce qui donne l'impression qu'ils basculent vers nous.
        for flap in FLAPS:
            painter.setPen(pen)
            painter.setBrush(CARDBOARD_DARK if self._open > 0.5
                             else CARDBOARD_LIGHT)
            painter.drawPolygon(self._flap_polygon(flap, rect))

        # Caisse.
        corps = QPainterPath()
        corps.addRoundedRect(rect, 7, 7)
        painter.setPen(pen)
        painter.setBrush(CARDBOARD)
        painter.drawPath(corps)

        # Bande de fermeture verticale, et le sillon horizontal du couvercle.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(TAPE)
        bande = QRectF(rect.center().x() - 11, rect.top() + 3, 22,
                       rect.height() * 0.42)
        painter.drawRect(bande)
        painter.setPen(QPen(CARDBOARD_DARK, 2.0))
        painter.drawLine(QPointF(rect.left() + 5, rect.top() + rect.height() * 0.42),
                         QPointF(rect.right() - 5, rect.top() + rect.height() * 0.42))

        painter.end()
