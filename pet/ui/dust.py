"""Fenêtre des particules : un calque à part, posé sur le bureau (lot L11).

Les particules vivaient d'abord dans la fenêtre du pet, peintes par-dessus son
image. Deux défauts que seul l'usage révèle :

**Elles suivaient ses rebonds.** Leurs coordonnées étaient celles du widget, et
ce widget se déplace à chaque image — chute, démarche, encaissement. Une
poussière soulevée au sol se remettait donc à bouger dès que le robot bougeait,
ce qui est exactement le contraire de ce que fait de la poussière. Elle est
retombée quelque part ; elle y reste.

**Elles étaient coupées en bas.** Les pieds du robot touchent le bord inférieur
de sa fenêtre à trois pixels près : il n'y a littéralement pas de place sous lui
pour une gerbe au sol.

D'où ce calque. Les particules sont en **pixels physiques d'écran**, comme le
pet et comme les objets de soin, et cette fenêtre-ci est plus large que celle du
robot — de quoi laisser la poussière s'étaler.

**Elle est traversante en permanence, et jamais autrement.** Le click-through
est posé une fois à la création et n'est jamais levé : aucune branche ne peut le
retirer par mégarde. C'est la contrainte §6 rendue structurellement impossible à
enfreindre, plutôt que seulement respectée.

**Elle ne se déplace pas tant qu'une particule vit.** Sinon la gerbe serait
rognée par un bord qui bouge sous elle. Elle se replace entre deux effets, ce
qui suffit : la plus longue vit deux secondes, et le robot ne va pas loin en
deux secondes — il dort.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from ..anim.particles import Particles
from ..app import win32
from . import sparks

# Taille du calque, en hauteurs de pet. Large : une poussière d'atterrissage
# s'étale sur près d'une largeur de robot de chaque côté, et un effet rogné se
# remarque bien plus qu'un effet discret.
MARGIN_X = 1.15
MARGIN_TOP = 0.55
MARGIN_BOTTOM = 0.22


class ParticleWindow(QWidget):
    """Calque transparent, traversant, qui ne porte que des particules."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.banc = Particles()
        self._origin = (0.0, 0.0)          # coin haut-gauche, en physique
        self._dpr = 1.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # Qt ne doit jamais recevoir un clic ici : ce calque n'a aucune
        # interaction, et `WA_TransparentForMouseEvents` le dit à Qt tandis que
        # `set_click_through` le dit à Windows. Les deux, parce qu'ils
        # répondent à deux questions différentes — qui reçoit l'événement, et
        # si la fenêtre est seulement visible au test de frappe du système.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # -- placement -----------------------------------------------------------

    def reframe(self, pet_rect: tuple[int, int, int, int], dpr: float) -> None:
        """Recentre le calque sur le pet. Sans effet si une particule vit.

        `pet_rect` est en pixels physiques, `dpr` le rapport physique/logique.
        Le calque déborde surtout **en bas et sur les côtés** : c'est là que va
        la poussière, et le haut n'a besoin que de la place d'un « Z ».
        """
        if not self.banc.empty:
            return

        left, top, pw, ph = pet_rect
        marge_x = ph * MARGIN_X
        x = left + pw / 2.0 - (pw / 2.0 + marge_x)
        y = top - ph * MARGIN_TOP
        largeur = pw + 2.0 * marge_x
        hauteur = ph * (MARGIN_TOP + 1.0 + MARGIN_BOTTOM)

        self._origin = (x, y)
        self._dpr = max(1e-6, dpr)
        self.setFixedSize(max(1, int(largeur / self._dpr)),
                          max(1, int(hauteur / self._dpr)))
        if not self.isVisible():
            self.show()
            # Posé après le premier affichage : avant, la fenêtre native
            # n'existe pas et le style étendu serait écrit dans le vide.
            win32.set_click_through(int(self.winId()), True)
        win32.set_window_pos(int(self.winId()), round(x), round(y))

    # -- cycle ---------------------------------------------------------------

    def step(self, dt: float, pet_h: float,
             floor: float | None = None) -> bool:
        """Avance le banc. Rend `True` s'il reste quelque chose à peindre."""
        vivant = self.banc.step(dt, pet_h, floor)
        if vivant:
            self.update()
        elif self.isVisible():
            # Un calque vide est masqué : une fenêtre transparente de plus dans
            # la pile du gestionnaire ne coûte pas cher, mais elle ne coûte
            # rien du tout quand elle n'est pas là.
            self.hide()
        return vivant

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self.banc.empty:
            return
        painter = QPainter(self)
        sparks.draw(painter, self.banc, self._origin, self._dpr)
        painter.end()
