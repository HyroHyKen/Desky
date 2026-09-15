"""Fenêtre des trois gobelets : elle les dessine, et elle reçoit le clic (L14).

C'est la **seule fenêtre de jeu cliquable**, et c'est délibéré. Le ballon se
frappe en l'effleurant parce qu'on le rattrape ; un gobelet se choisit, une
fois, et survoler déclencherait dès qu'on traverse l'écran. Un choix unique
demande un geste franc.

Le click-through est donc levé **pendant la phase de choix, et seulement là** :
hors de cette phase elle redevient traversante, comme les autres fenêtres de
jeu. Un calque qui intercepterait les clics pendant qu'on regarde un mélange
volerait des clics à ce qui se trouve dessous sans rien offrir en échange.

**Le robot n'est pas dessiné ici.** Sa fenêtre est masquée pendant le mélange et
replacée sous le gobelet dévoilé — voir `app/parts/games`. C'était la seule
façon fiable : compter sur l'ordre d'empilement entre deux fenêtres toutes deux
« toujours au-dessus » aurait donné un robot réapparaissant par-dessus son
gobelet une fois sur dix, sur un défaut impossible à reproduire.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient)
from PySide6.QtWidgets import QWidget

from ..anim.easing import ease_in, ease_in_out, ease_out_back
from ..app import win32
from ..games import cups as jeu

# Géométrie, en hauteurs de pet. Les gobelets sont **plus grands que le robot**,
# comme demandé : il faut qu'on croie qu'il tient dessous.
CUP_W = 1.05
CUP_H = 1.30
GAP = 0.34

# Hauteur de lever d'un gobelet au dévoilement, et de l'arc que décrit celui qui
# passe par-dessus pendant une permutation.
LIFT = 1.05
ARC = 0.42

# Durée du lever. Assez lente pour qu'on la voie se faire, assez brève pour ne
# pas retarder la révélation.
LIFT_SECONDS = 0.34

# Ce que la fenêtre doit réserver au-dessus des gobelets : le plus grand des
# deux mouvements verticaux, **plus le dépassement** de leurs courbes, plus de
# quoi loger le halo de survol. Un dépassement rogné est pire qu'un mouvement
# sans dépassement : on voit l'objet disparaître dans le bord.
MARGIN_TOP = max(LIFT, ARC) * 1.12 + 0.22

# Marge de la fenêtre autour de la bande de gobelets.
#
# En haut, elle doit couvrir le **lever** — 0,75 ne suffisait pas et les
# gobelets levés étaient tranchés net à trois dixièmes de hauteur de pet, ce qui
# se voyait précisément au moment où le joueur regarde le plus. Elle est donc
# dérivée de `LIFT` plutôt que posée à la main : les deux nombres doivent bouger
# ensemble, et un seul les tient.
MARGIN_X = 0.25
MARGIN_BOTTOM = 0.12

CUP = QColor(214, 122, 64)
CUP_DARK = QColor(158, 78, 38)
CUP_LIP = QColor(236, 156, 96)
SHADOW = QColor(18, 24, 30, 70)

# Halo de survol. Le cyan du produit, comme tout ce qui signale qu'une
# interaction est possible.
GLOW = QColor(31, 168, 186)


class CupsWindow(QWidget):
    """Les trois gobelets, leur mouvement, et le choix du joueur."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.game: jeu.Cups | None = None
        self.on_pick = None
        self._origin = (0.0, 0.0)
        self._dpr = 1.0
        self._pet_h = 200.0
        self._hover = -1
        self._clickable = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

    # -- géométrie -----------------------------------------------------------

    def band_width(self) -> float:
        """Largeur de la bande de gobelets, en pixels physiques."""
        return (jeu.SLOTS * CUP_W + (jeu.SLOTS - 1) * GAP) * self._pet_h

    def place(self, game: jeu.Cups, pet_rect, dpr: float, work) -> None:
        """Positionne la fenêtre, centrée sur le pet et bornée par l'écran."""
        self.game = game
        left, top, pw, ph = pet_rect
        self._pet_h = float(ph)
        self._dpr = max(1e-6, dpr)

        largeur = self.band_width() + 2.0 * MARGIN_X * ph
        hauteur = (MARGIN_TOP + CUP_H + MARGIN_BOTTOM) * ph
        wl, _, ww, _ = work
        x = left + pw / 2.0 - largeur / 2.0
        x = max(float(wl), min(float(wl + ww) - largeur, x))
        # Le bas des gobelets repose sur le sol du pet.
        y = top + ph - hauteur + MARGIN_BOTTOM * ph

        self._origin = (x, y)
        self.setFixedSize(max(1, int(largeur / self._dpr)),
                          max(1, int(hauteur / self._dpr)))
        if not self.isVisible():
            self.show()
        win32.set_window_pos(int(self.winId()), round(x), round(y))

    def slot_center_x(self, slot: int) -> float:
        """Abscisse **écran** du centre d'un emplacement."""
        ox, _ = self._origin
        pas = (CUP_W + GAP) * self._pet_h
        gauche = ox + MARGIN_X * self._pet_h + CUP_W * self._pet_h / 2.0
        return gauche + slot * pas

    def _cup_xy(self, cup: int) -> tuple[float, float]:
        """Position **locale logique** du centre bas d'un gobelet."""
        game = self.game
        ox, oy = self._origin
        k = 1.0 / self._dpr
        base_y = oy + (MARGIN_TOP + CUP_H) * self._pet_h

        slot = game.cup_at[cup]
        x = self.slot_center_x(slot)
        y = base_y
        echange = game.swap

        if echange is not None:
            a, b = echange
            t = game.swap_progress
            if slot in (a, b):
                autre = b if slot == a else a
                depart, arrivee = self.slot_center_x(slot), self.slot_center_x(autre)
                # `ease_out_back` plutôt qu'une sigmoïde : le gobelet dépasse
                # très légèrement sa place puis s'y pose, ce que le §10 demande
                # de tout mouvement marqué. Sans ce dépassement, il s'arrête
                # net et le mélange a l'air d'être joué au métronome.
                x = depart + (arrivee - depart) * ease_out_back(t, 1.1)
                # L'un passe au-dessus, l'autre au-dessous : c'est ce
                # croisement qui rend le mélange lisible, et sans lui les deux
                # gobelets se traversent.
                #
                # L'arc est pondéré par `ease_in_out` en plus du sinus : un
                # sinus seul décolle et atterrit à vitesse maximale, ce qui se
                # voit comme un à-coup aux deux bouts du mouvement.
                sens = -1.0 if slot == a else 1.0
                cloche = math.sin(math.pi * min(1.0, t)) * ease_in_out(
                    min(1.0, t * 2.2))
                y = base_y + sens * ARC * self._pet_h * cloche

        if game.state in (jeu.REVEAL, jeu.COVERING, jeu.RESULT):
            y -= self._lift(cup) * LIFT * self._pet_h

        return (x - ox) * k, (y - oy) * k

    def _lift(self, cup: int) -> float:
        """Part de lever d'un gobelet, dans [0, 1]."""
        game = self.game
        if game.state == jeu.REVEAL:
            # Il monte, dépasse, se pose. C'est le premier mouvement que voit
            # le joueur, et c'est lui qui dit si le jeu est soigné.
            monte = min(1.0, game._t / LIFT_SECONDS)
            return ease_out_back(monte, 1.5) if monte < 1.0 else 1.0
        if game.state == jeu.COVERING:
            # Il tombe : lent d'abord, puis vite. `ease_in` est exactement la
            # courbe d'un objet qu'on lâche.
            return 1.0 - ease_in(min(1.0, game._t / jeu.COVER_SECONDS))
        if game.state == jeu.RESULT:
            # Le gobelet choisi se lève, et celui du robot aussi quand ce n'est
            # pas le même : on doit **voir** où il était, sinon perdre ne dit
            # rien et on soupçonne le jeu de tricher.
            slot = game.cup_at[cup]
            if slot in (game.picked, game.robot_slot):
                monte = min(1.0, game._t / LIFT_SECONDS)
                return ease_out_back(monte, 1.5) if monte < 1.0 else 1.0
        return 0.0

    # -- interaction ---------------------------------------------------------

    def set_clickable(self, actif: bool) -> None:
        """N'intercepte la souris que pendant la phase de choix."""
        if actif == self._clickable:
            return
        self._clickable = actif
        if self.isVisible():
            win32.set_click_through(int(self.winId()), not actif)
        if not actif and self._hover != -1:
            self._hover = -1
            self.update()

    def _slot_at(self, x: float, y: float) -> int:
        """Emplacement sous un point local logique, ou -1."""
        demi = CUP_W * self._pet_h / 2.0 / self._dpr
        ox, _ = self._origin
        for slot in range(jeu.SLOTS):
            centre = (self.slot_center_x(slot) - ox) / self._dpr
            if abs(x - centre) <= demi:
                return slot
        return -1

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if not self._clickable:
            return
        slot = self._slot_at(event.position().x(), event.position().y())
        if slot != self._hover:
            self._hover = slot
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self._hover != -1:
            self._hover = -1
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if not self._clickable:
            return
        slot = self._slot_at(event.position().x(), event.position().y())
        if slot >= 0 and self.on_pick is not None:
            self.on_pick(slot)

    def raise_above_pet(self, pet_hwnd: int) -> None:
        """Place les gobelets **devant** le robot.

        Appelé à chaque image où les deux sont visibles : réaffichage du pet,
        clic sur une autre fenêtre, n'importe quoi peut avoir rebattu l'ordre
        entre-temps, et un gobelet derrière son robot ruine l'illusion sans
        prévenir.
        """
        if self.isVisible() and pet_hwnd:
            win32.raise_above(int(self.winId()), pet_hwnd)

    def close_game(self) -> None:
        self.game = None
        self.set_clickable(False)
        if self.isVisible():
            self.hide()

    # -- peinture ------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        game = self.game
        if game is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        k = 1.0 / self._dpr
        largeur = CUP_W * self._pet_h * k
        hauteur = CUP_H * self._pet_h * k

        # Les gobelets qui passent **derrière** d'abord : l'ordre de peinture
        # est ce qui donne le croisement, et il change au cours d'une
        # permutation.
        ordre = sorted(range(jeu.SLOTS), key=lambda c: self._cup_xy(c)[1])
        for cup in ordre:
            x, y = self._cup_xy(cup)
            slot = game.cup_at[cup]
            if game.can_pick and slot == self._hover:
                self._paint_glow(painter, x, y, largeur, hauteur)
            self._paint_cup(painter, x, y, largeur, hauteur,
                            self._lift(cup))
        painter.end()

    def _paint_glow(self, painter: QPainter, x: float, y: float,
                    w: float, h: float) -> None:
        """Halo derrière le gobelet survolé.

        **Derrière**, pas dessus : un halo peint par-dessus laverait la couleur
        du gobelet et donnerait l'impression qu'il est désactivé, soit
        exactement le contraire du message. Il dit « celui-là est cliquable ».
        """
        centre = QPointF(x, y - h * 0.5)
        rayon = max(w, h) * 0.82
        degrade = QRadialGradient(centre, rayon)
        chaud = QColor(GLOW)
        chaud.setAlpha(150)
        degrade.setColorAt(0.0, chaud)
        milieu = QColor(GLOW)
        milieu.setAlpha(70)
        degrade.setColorAt(0.55, milieu)
        degrade.setColorAt(1.0, QColor(GLOW.red(), GLOW.green(), GLOW.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(degrade)
        painter.drawEllipse(centre, rayon, rayon)

    def _paint_cup(self, painter: QPainter, x: float, y: float,
                   w: float, h: float, lift: float = 0.0) -> None:
        """Un gobelet renversé, vu **légèrement de dessus**.

        Cette vue décide de tout le dessin, et la première version se
        contredisait : le haut montrait une ellipse pleine — donc on voyait le
        fond du gobelet d'au-dessus — pendant que le bas montrait une bouche
        ouverte avec son intérieur sombre, ce qui ne se voit que d'en dessous.
        L'œil attrape ce genre d'incohérence sans savoir la nommer ; il en
        ressort seulement que l'objet est mal dessiné.

        Vu de dessus, le bas d'un gobelet posé ne montre **pas** son intérieur :
        on n'en voit que le bord avant, qui bombe vers le bas. L'intérieur
        n'apparaît qu'une fois le gobelet **soulevé**, et d'autant plus qu'il
        l'est — d'où `lift`.
        """
        haut = w * 0.62                      # le sommet est plus étroit
        # Aplatissement des ellipses : c'est ce seul nombre qui dit de combien
        # on surplombe. Le même en haut et en bas, sans quoi les deux bouts
        # racontent deux points de vue différents.
        ovale = h * 0.075

        ombre = QRectF(x - w * 0.46, y - ovale * 0.5, w * 0.92, ovale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SHADOW)
        painter.drawEllipse(ombre)

        # Corps : les flancs, puis le bord bas **bombé vers le bas** — c'est la
        # moitié avant de l'ellipse de l'ouverture, la seule qu'on voie.
        corps = QPainterPath()
        corps.moveTo(x - haut / 2.0, y - h)
        corps.lineTo(x + haut / 2.0, y - h)
        corps.lineTo(x + w / 2.0, y)
        corps.arcTo(QRectF(x - w / 2.0, y - ovale / 2.0, w, ovale), 0.0, -180.0)
        corps.closeSubpath()

        degrade = QLinearGradient(x - w / 2.0, 0.0, x + w / 2.0, 0.0)
        degrade.setColorAt(0.0, CUP_DARK)
        degrade.setColorAt(0.34, CUP)
        degrade.setColorAt(1.0, CUP_DARK)
        painter.setBrush(degrade)
        painter.drawPath(corps)

        if lift > 0.01:
            # Soulevé, on découvre l'intérieur par la moitié **arrière** de
            # l'ouverture : celle qui bombe vers le haut.
            creux = QPainterPath()
            creux.moveTo(x - w / 2.0, y)
            creux.arcTo(QRectF(x - w / 2.0, y - ovale / 2.0, w, ovale),
                        180.0, -180.0)
            creux.closeSubpath()
            sombre = QColor(CUP_DARK)
            sombre.setAlpha(int(255 * min(1.0, lift * 1.6)))
            painter.setBrush(sombre)
            painter.drawPath(creux)

        # Liseré clair sur le bord avant : il donne l'épaisseur de la paroi, et
        # c'est ce qui empêche le gobelet de se lire comme un trapèze plein.
        painter.setPen(QPen(CUP_LIP, max(1.0, h * 0.016)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(x - w / 2.0, y - ovale / 2.0, w, ovale),
                        0, -180 * 16)

        # Fond du gobelet, vu de dessus : l'ellipse complète, dans le même
        # aplatissement que l'ouverture.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CUP_LIP)
        painter.drawEllipse(QRectF(x - haut / 2.0, y - h - ovale * 0.42,
                                   haut, ovale * 0.84))
