"""Objets de soin posés sur le bureau.

Remplace le bouton qui soigne « par magie » : nourrir, jouer et nettoyer font
**apparaître un objet** au sol, et le soin ne s'applique qu'une fois le robot et
l'objet réunis.

**Une seule règle couvre les trois façons de les réunir.** Le robot va le
chercher tout seul, l'utilisateur porte le robot jusqu'à l'objet, ou il traîne
l'objet jusqu'au robot : dans les trois cas c'est le même test de proximité qui
déclenche, donc il n'y a aucun cas particulier à écrire.

Caresser reste un bouton direct. C'est le seul soin sans objet à apporter, et en
inventer un aurait été forcé.

Ce module ne décide rien : il porte un sprite, sa position et son état. C'est la
fenêtre du pet qui le fait vivre, exactement comme elle fait vivre la bulle —
elle a déjà la boucle de rendu, le sol et le test de survol.
"""

from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .. import resources

# Soins qui passent par un objet, et le préfixe de fichier qui les fournit.
# `pet` n'y figure pas : une caresse ne s'apporte pas.
# Familles de sprites posables sur le bureau. `play` a disparu au lot L13 :
# jouer est devenu un jeu, pas un objet qu'on pose.
ITEM_KINDS: dict[str, str] = {
    "feed": "food",
    "clean": "clean",
}

ASSET_DIR = resources.resource_dir("assets", "items")

# Taille de l'objet, en part de la hauteur du pet. Assez gros pour se voir et
# s'attraper à la souris, assez petit pour que le robot reste le sujet.
SIZE_RATIO = 0.34

# Distance de réunion, en largeurs de pet, entre les deux centres. Généreuse :
# rater son objet de trois pixels après l'avoir traîné à travers l'écran serait
# une punition, et le §12 les interdit.
REACH = 0.72

# Durée de vie avant évaporation, et durée des deux fondus.
TTL_SECONDS = 180.0
EXPIRE_FADE = 1.2
CONSUME_SECONDS = 0.45

# Chute, en pixels physiques. Mêmes sensations que celle du pet au lot L1.
GRAVITY = 2600.0
RESTITUTION = 0.24
REST_VELOCITY = 40.0



def available_sprites(kind: str, directory: Path | None = None) -> list[Path]:
    """Fichiers disponibles pour un soin, triés pour être reproductibles.

    Découverts **par préfixe** plutôt que déclarés dans une table : ajouter une
    variété de nourriture au dossier suffit alors à l'obtenir en jeu, sans
    toucher au code ni à un manifeste qui finirait par mentir.
    """
    prefix = ITEM_KINDS.get(kind)
    if prefix is None:
        return []
    base = directory if directory is not None else ASSET_DIR
    if not base.is_dir():
        return []
    return sorted(base.glob(prefix + "_*.png"))


class SpritePicker:
    """Choisit un sprite, en évitant de resservir le dernier.

    « Histoire qu'il ne mange pas tout le temps la même chose » : le hasard pur
    répète, et deux repas identiques d'affilée se remarquent bien plus qu'une
    série variée ne se savoure.
    """

    def __init__(self, seed: int = 0, directory: Path | None = None) -> None:
        self._rng = random.Random(seed)
        self._last: dict[str, Path] = {}
        self._dir = directory

    def pick(self, kind: str) -> Path | None:
        choix = available_sprites(kind, self._dir)
        if not choix:
            return None
        precedent = self._last.get(kind)
        if len(choix) > 1 and precedent in choix:
            choix = [c for c in choix if c != precedent]
        retenu = self._rng.choice(choix)
        self._last[kind] = retenu
        return retenu


class ItemWindow(QWidget):
    """Un objet posé sur le bureau : un sprite, une position, un état.

    Positionné en **pixels physiques** comme le pet, et pour la même raison : la
    proximité se mesure entre deux centres, et mélanger les deux espaces de
    coordonnées la fausserait sur un montage à DPI mixtes.
    """

    def __init__(self, kind: str, sprite: Path | None, side: int,
                 parent: QWidget | None = None,
                 consumable: str = "") -> None:
        super().__init__(parent)
        self.kind = kind
        # Article dont il provient. L'objet posé doit savoir **ce qu'il rend**
        # une fois rejoint, et ce qu'il faut rembourser s'il s'évapore : deux
        # gamelles de prix différents posent le même sprite.
        self.consumable = consumable
        self.state = "falling"
        self._t = 0.0
        self._fade = 1.0
        self._scale = 1.0

        self.x = 0.0
        self.y = 0.0
        self._vy = 0.0
        self.held = False
        self._grab = (0.0, 0.0)
        self._eaten = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(side, side)

        self.pixmap = QPixmap(str(sprite)) if sprite is not None else QPixmap()
        if not self.pixmap.isNull():
            self.pixmap = self.pixmap.scaled(
                side, side, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        self._alpha = (self.pixmap.toImage() if not self.pixmap.isNull()
                       else None)

    # -- état --------------------------------------------------------------

    @property
    def gone(self) -> bool:
        return self.state == "gone"

    @property
    def eaten(self) -> bool:
        """A-t-il déjà été consommé ? Vrai dès le premier contact."""
        return self._eaten

    @property
    def side(self) -> int:
        return self.width()

    def center(self, dpr: float) -> tuple[float, float]:
        """Centre de l'objet, en pixels **physiques**."""
        moitie = self.width() * dpr / 2.0
        return self.x + moitie, self.y + moitie

    def place(self, x: float, y: float) -> None:
        self.x, self.y = float(x), float(y)
        self._apply()

    def _apply(self) -> None:
        from ..app import win32
        if self.isVisible():
            win32.set_window_pos(int(self.winId()), round(self.x), round(self.y))

    # -- vie ---------------------------------------------------------------

    @property
    def _done(self) -> bool:
        """Consommé ou disparu : plus aucune manipulation ne doit l'atteindre.

        **Invariant introduit après un bug d'usage.** Traîner l'objet jusqu'au
        robot déclenche la consommation alors qu'on le tient **encore** : le
        bouton de la souris n'est relâché qu'après. `release` écrasait alors
        l'état « consommé » par « en chute », l'objet retombait au sol, et comme
        il était déjà marqué mangé il n'était plus jamais absorbable. Il restait
        posé là pour toujours.

        Le symptôme ne se voyait qu'avec le panneau ouvert, parce que le pet
        immobile fait de « traîner l'objet jusqu'à lui » la façon naturelle de
        faire — sans panneau, c'est le robot qui vient chercher, et il n'est
        alors tenu par personne.
        """
        return self._eaten or self.state in ("consumed", "gone")

    def grab_at(self, dx: float, dy: float) -> None:
        """L'utilisateur l'attrape. `dx`, `dy` : prise dans l'objet."""
        if self._done:
            return
        self.held = True
        self.state = "held"
        self._grab = (dx, dy)

    def drag_to(self, cx: float, cy: float) -> None:
        if self._done:
            return
        self.x = cx - self._grab[0]
        self.y = cy - self._grab[1]
        self._apply()

    def release(self) -> None:
        if self._done:
            # La main s'ouvre sur un objet déjà mangé : il ne retombe pas, il
            # finit de disparaître.
            self.held = False
            return
        self.held = False
        self.state = "falling"
        self._vy = 0.0

    def consume(self) -> bool:
        """Le robot l'a atteint : il disparaît en se rétractant.

        **Rend True une seule fois**, et c'est ce qui garantit qu'un soin n'est
        appliqué qu'une fois. L'invariant vit ici plutôt que chez l'appelant
        parce qu'il porte sur l'objet : la première version laissait
        l'animation de disparition passer en `gone` dans la même image, la
        fenêtre retombait alors dans son test de proximité, et le besoin montait
        **deux fois** sans que rien ne le signale.
        """
        if self._eaten:
            return False
        self._eaten = True
        # La main le lâche d'office : il a été mangé, il n'est plus tenu. Sans
        # cette ligne, le relâchement qui suit le ramenait en chute.
        self.held = False
        self.state = "consumed"
        self._t = 0.0
        return True

    def step(self, dt: float, floor_y: float) -> bool:
        """Avance l'objet. Retourne True s'il faut redessiner.

        `floor_y` est l'ordonnée **physique** du haut de l'objet posé au sol.
        """
        if self.state == "gone":
            return False
        self._t += dt

        if self.state == "consumed":
            part = min(1.0, self._t / CONSUME_SECONDS)
            self._scale = 1.0 - 0.55 * part
            self._fade = 1.0 - part
            if part >= 1.0:
                self._finish()
            self.update()
            return True

        if self.state == "held":
            self._fade = 1.0
            return False

        if self.state == "falling":
            self._vy += GRAVITY * dt
            self.y += self._vy * dt
            if self.y >= floor_y:
                self.y = floor_y
                if abs(self._vy) < REST_VELOCITY:
                    self._vy = 0.0
                    self.state = "idle"
                    self._t = 0.0
                else:
                    self._vy = -self._vy * RESTITUTION
            self._apply()
            return True

        # Posé : il attend, et finit par s'évaporer.
        if self._t >= TTL_SECONDS:
            self.state = "expiring"
            self._t = 0.0
            return True
        return False

    def expire_step(self, dt: float) -> bool:
        if self.state != "expiring":
            return False
        self._fade = max(0.0, self._fade - dt / EXPIRE_FADE)
        if self._fade <= 0.0:
            self._finish()
        self.update()
        return True

    def _finish(self) -> None:
        self.state = "gone"
        self.hide()

    # -- survol ------------------------------------------------------------

    def opaque_at(self, lx: float, ly: float) -> bool:
        """Le point, en coordonnées **logiques** de la fenêtre, est-il dessus ?

        Testé sur l'alpha du sprite et non sur le rectangle : un objet carré
        dont les coins mangent les clics du bureau serait une gêne permanente
        pour trois minutes de présence.
        """
        if self._alpha is None:
            return False
        if not (0 <= lx < self._alpha.width() and 0 <= ly < self._alpha.height()):
            return False
        return self._alpha.pixelColor(int(lx), int(ly)).alpha() > 38

    # -- souris ------------------------------------------------------------
    #
    # Le glisser est autonome, comme celui du pet et pour la même raison : il
    # lit le curseur en **pixels physiques** via Win32 plutôt que la position
    # logique de l'évènement Qt, ce qui reste juste quand on traîne l'objet d'un
    # écran à l'autre avec des facteurs d'échelle différents.

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self.state in ("gone", "consumed"):
            return
        from ..app import win32
        cx, cy = win32.get_cursor_pos()
        self.grab_at(cx - self.x, cy - self.y)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if not self.held:
            return
        from ..app import win32
        cx, cy = win32.get_cursor_pos()
        self.drag_to(cx, cy)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self.held:
            self.release()

    # -- peinture ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self.pixmap.isNull() or self.state == "gone":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(max(0.0, min(1.0, self._fade)))

        cote = self.width() * self._scale
        # Le rétrécissement garde le **bas** en place : un objet qu'on avale se
        # tasse sur le sol, il ne s'évapore pas en lévitant.
        x = (self.width() - cote) / 2.0
        y = self.height() - cote
        painter.drawPixmap(QRectF(x, y, cote, cote), self.pixmap,
                           QRectF(self.pixmap.rect()))
        painter.end()
