"""Annonce d'un trophée, en bas à droite de l'écran (lot L22).

Une bannière qui entre par la droite, se laisse lire, et repart. Elle ne
demande rien et ne se ferme pas : un trophée est une bonne nouvelle, et une
bonne nouvelle qu'il faut congédier d'un clic devient une corvée.

**Elle ne prend jamais le focus, et ne se met pas sur le trajet.** Le coin bas
droit est le seul endroit d'un bureau Windows où rien d'important ne vit — la
zone de notification est juste en dessous, et l'utilisateur y est habitué.

**Une file, pas une pile.** Trois trophées peuvent tomber dans la même seconde,
par exemple au premier lancement d'une version qui rattrape l'existant. Les
empiler à l'écran couvrirait le quart du bureau ; ils défilent donc l'un après
l'autre, et la file est bornée — au-delà, la page des trophées dit le reste
bien mieux qu'une file d'attente de deux minutes.

**La mécanique du passage est séparée du widget**, comme le fondu de l'écran de
lancement : elle n'a ni fenêtre ni horloge, donc un test la joue en `dt`
synthétique et vérifie qu'une bannière finit toujours par partir.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ..anim.easing import ease_in, ease_out_back
from .icons import draw_icon

# Les trois temps, en secondes. La tenue est longue — on ne regarde pas son
# bureau en permanence, et une annonce de 1,5 s se rate.
ENTREE = 0.44
TENUE = 3.4
SORTIE = 0.30

# Tenue quand d'autres attendent derrière. Mesuré sur un vrai lancement : sept
# trophées rattrapés d'un coup font vingt-neuf secondes de bannières à pleine
# durée, ce qui n'est plus une bonne nouvelle mais une interruption. Raccourcies,
# les mêmes sept tiennent en dix-sept secondes et se lisent comme une salve.
TENUE_FILE = 1.5

ENTRANT, TENUE_PHASE, SORTANT, FINI = "entrant", "tenue", "sortant", "fini"

# Géométrie, en pixels logiques.
WIDTH = 286
HEIGHT = 64
MARGE = 18                      # écart aux bords de la zone de travail
RADIUS = 16
PASTILLE = 34                   # disque de la coche

# File d'attente. Au-delà, on laisse tomber : la page des trophées dit la suite
# bien mieux qu'une file qui continue de défiler une minute plus tard.
FILE_MAX = 6

# Couleurs, reprises du panneau. Elles y sont redéfinies plutôt qu'importées :
# `panel` tire cinquante symboles et une bannière n'a pas à dépendre de lui.
BG = QColor(248, 250, 251, 250)
BG_EDGE = QColor(18, 26, 33, 42)
INK = QColor(20, 26, 33)
INK_SOFT = QColor(90, 101, 112)
ACCENT = QColor(31, 168, 186)

# Les deux seules chaînes de ce module.
SURTITRE = "Trophée débloqué"


class Passage:
    """Entrée, tenue, sortie. Sans Qt ni horloge.

    `decalage` vaut 1 quand la bannière est hors de l'écran, 0 quand elle est en
    place. Il **dépasse** légèrement à l'arrivée : c'est la courbe qui donne à
    la bannière l'air d'avoir une masse, comme au panneau.
    """

    __slots__ = ("phase", "t", "tenue")

    def __init__(self, tenue: float = TENUE) -> None:
        self.phase = ENTRANT
        self.t = 0.0
        self.tenue = max(0.0, float(tenue))

    @property
    def fini(self) -> bool:
        return self.phase == FINI

    def step(self, dt: float) -> None:
        if self.phase == FINI:
            return
        self.t += max(0.0, float(dt))
        if self.phase == ENTRANT and self.t >= ENTREE:
            self.phase, self.t = TENUE_PHASE, 0.0
        elif self.phase == TENUE_PHASE and self.t >= self.tenue:
            self.phase, self.t = SORTANT, 0.0
        elif self.phase == SORTANT and self.t >= SORTIE:
            self.phase, self.t = FINI, 0.0

    @property
    def decalage(self) -> float:
        if self.phase == ENTRANT:
            return 1.0 - ease_out_back(min(1.0, self.t / ENTREE))
        if self.phase == SORTANT:
            return ease_in(min(1.0, self.t / SORTIE))
        return 0.0 if self.phase == TENUE_PHASE else 1.0

    @property
    def opacite(self) -> float:
        """L'opacité ne travaille qu'à la sortie.

        À l'entrée, c'est le glissement qui porte l'arrivée : un fondu par-dessus
        rendrait la bannière fantomatique pendant tout son trajet. À la sortie
        en revanche elle disparaît sur place autant qu'elle s'en va, sans quoi
        on la voit raser le bord de l'écran.
        """
        if self.phase == SORTANT:
            return 1.0 - ease_in(min(1.0, self.t / SORTIE))
        return 0.0 if self.phase == FINI else 1.0


class Toast(QWidget):
    """La bannière, et sa file."""

    HZ = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.passage = Passage()
        self.titre = ""
        self._file: list[str] = []
        self._ancre = (0.0, 0.0)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # Transparente aux clics : elle se pose sur le bureau de quelqu'un qui
        # travaille, et intercepter un clic parce qu'on a gagné un trophée
        # serait le contraire d'une récompense.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(WIDTH, HEIGHT)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(1000 // self.HZ)
        self._timer.timeout.connect(self._tick)

    # -- placement ----------------------------------------------------------

    def set_corner(self, work: tuple[int, int, int, int], dpr: float = 1.0) -> None:
        """Pose le coin bas droit depuis une zone de travail en pixels physiques."""
        left, top, w, h = work
        dpr = max(1.0, float(dpr))
        self._ancre = ((left + w) / dpr - WIDTH - MARGE,
                       (top + h) / dpr - HEIGHT - MARGE)
        self._replacer()

    def _replacer(self) -> None:
        x, y = self._ancre
        # Le glissement se fait en **déplaçant la fenêtre** et non en peignant
        # un décalage : une fenêtre translucide toujours au-dessus qui peint du
        # vide sur les trois quarts de sa surface coûte plus cher à composer
        # qu'une petite fenêtre qu'on déplace.
        self.move(int(x + self.passage.decalage * (WIDTH + MARGE * 2)), int(y))

    # -- file ---------------------------------------------------------------

    def annoncer(self, titre: str) -> None:
        """Ajoute un trophée à la file, et démarre si rien n'est en cours."""
        titre = str(titre).strip()
        if not titre or len(self._file) >= FILE_MAX:
            return
        self._file.append(titre)
        if not self.titre:
            self._suivante()

    def _suivante(self) -> None:
        if not self._file:
            self.titre = ""
            self._timer.stop()
            self.hide()
            return
        self.titre = self._file.pop(0)
        self.passage = Passage(TENUE_FILE if self._file else TENUE)
        self._replacer()
        self.setWindowOpacity(1.0)
        self.show()
        self._timer.start()

    def step(self, dt: float) -> bool:
        """Avance d'un pas. Rend `True` tant qu'une bannière est en vol.

        Séparé du minuteur pour que les tests jouent le passage entier sans
        horloge réelle, comme partout ailleurs dans l'interface.
        """
        if not self.titre:
            return False
        self.passage.step(dt)
        self.setWindowOpacity(self.passage.opacite)
        self._replacer()
        if self.passage.fini:
            self._suivante()
            return bool(self.titre)
        return True

    def _tick(self) -> None:
        if not self.step(1.0 / self.HZ):
            return
        self.update()

    # -- rendu --------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if not self.titre:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        fond = QPainterPath()
        fond.addRoundedRect(QRectF(0.5, 0.5, WIDTH - 1.0, HEIGHT - 1.0),
                            RADIUS, RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BG)
        painter.drawPath(fond)
        painter.setPen(BG_EDGE)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(fond)

        # La coche est **blanche sur un disque cyan**, et non cyan sur le fond :
        # c'est le seul aplat de couleur de la bannière, et il faut qu'il porte
        # le message à trois mètres.
        disque = QRectF(14.0, (HEIGHT - PASTILLE) / 2.0, PASTILLE, PASTILLE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT)
        painter.drawEllipse(disque)
        draw_icon(painter, "check", disque.adjusted(8.0, 8.0, -8.0, -8.0),
                  QColor(255, 255, 255))

        gauche = disque.right() + 12.0
        largeur = WIDTH - gauche - 14.0

        font = QFont()
        font.setPixelSize(10)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        painter.setFont(font)
        painter.setPen(INK_SOFT)
        painter.drawText(QRectF(gauche, 13.0, largeur, 13.0),
                         int(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter),
                         SURTITRE)

        font.setPixelSize(15)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(INK)
        metrique = painter.fontMetrics()
        painter.drawText(QRectF(gauche, 28.0, largeur, 20.0),
                         int(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter),
                         metrique.elidedText(self.titre,
                                             Qt.TextElideMode.ElideRight,
                                             int(largeur)))
        painter.end()
