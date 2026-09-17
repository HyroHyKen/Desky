"""Écran de lancement : le logo en fondu, au centre (lot L19).

Il paraît à chaque ouverture, le temps que le robot soit prêt. Trois temps —
entrée, tenue, sortie — et une règle qui les gouverne tous : **la tenue dure au
moins `TENUE_MIN`, et au moins jusqu'à ce que l'application soit prête**. Sur
une machine rapide c'est le plancher qui commande, sur une machine lente c'est
le chargement ; dans les deux cas on ne voit jamais le logo clignoter.

**Le minuteur de sécurité n'est pas une précaution de principe.** Entre
l'apparition de l'écran et l'appel à `finish()`, le bootstrap construit un
contexte OpenGL et un robot — deux choses qui peuvent échouer et ouvrir une
boîte de dialogue d'erreur. Sans plafond, le logo resterait posé au milieu de
l'écran par-dessus le message, sans rien pour le faire partir.

**La machine à phases est séparée du widget**, et c'est ce qui la rend
vérifiable : elle n'a ni fenêtre, ni horloge, ni Qt, donc un test la joue à `dt`
synthétique et vérifie le plancher de tenue sans ouvrir d'écran.

**Pourquoi le fondu d'entrée est pompé à la main.** Il se joue *avant* la
boucle d'évènements, puisque la fenêtre du robot n'existe pas encore. Un
`QTimer` n'y tournerait pas. C'est aussi la seule partie de l'écran qui ajoute
vraiment au temps de démarrage — la tenue, elle, recouvre un chargement qui
avait lieu de toute façon.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ..anim.easing import ease_in_out
from ..resources import resource_dir

# Les trois temps, en secondes.
ENTREE = 0.26
TENUE_MIN = 0.42
SORTIE = 0.34

# Plafond absolu. Au-delà, l'écran s'efface même si personne ne l'a libéré.
SECURITE = 6.0

# Largeur d'affichage du logo, en pixels logiques.
LOGO_W = 460

ASSET = "logo.png"

ENTRANT, TENUE, SORTANT, FINI = "entrant", "tenue", "sortant", "fini"


class Fondu:
    """Le déroulé de l'écran, sans Qt ni horloge.

    `pret()` annonce que l'application a fini de se charger. Il ne raccourcit
    jamais la tenue en dessous de son plancher : appelé tout de suite sur une
    machine rapide, il laisse quand même le logo se voir.
    """

    __slots__ = ("phase", "t", "total", "_pret")

    def __init__(self) -> None:
        self.phase = ENTRANT
        self.t = 0.0
        self.total = 0.0
        self._pret = False

    @property
    def fini(self) -> bool:
        return self.phase == FINI

    def pret(self) -> None:
        self._pret = True

    def step(self, dt: float) -> None:
        if self.phase == FINI:
            return
        self.t += dt
        self.total += dt

        # Le plafond l'emporte sur tout le reste : un chargement qui n'aboutit
        # pas ne doit pas laisser le logo planté sur le bureau.
        if self.total >= SECURITE and self.phase != SORTANT:
            self.phase, self.t = SORTANT, 0.0
            return

        if self.phase == ENTRANT and self.t >= ENTREE:
            self.phase, self.t = TENUE, 0.0
        elif self.phase == TENUE and self._pret and self.t >= TENUE_MIN:
            self.phase, self.t = SORTANT, 0.0
        elif self.phase == SORTANT and self.t >= SORTIE:
            self.phase, self.t = FINI, 0.0

    @property
    def opacite(self) -> float:
        """Opacité courante, dans [0, 1]."""
        if self.phase == ENTRANT:
            return ease_in_out(min(1.0, self.t / ENTREE))
        if self.phase == TENUE:
            return 1.0
        if self.phase == SORTANT:
            return 1.0 - ease_in_out(min(1.0, self.t / SORTIE))
        return 0.0


class Splash(QWidget):
    """Le logo, centré sur l'écran où se trouve le curseur.

    Mêmes règles de fenêtre que le reste du produit : sans bordure, translucide,
    au premier plan et **sans jamais prendre le focus** — l'utilisateur vient
    peut-être de lancer autre chose, et voler son clavier une seconde serait
    impardonnable pour une image.
    """

    # Émis quand le logo a **fini de s'effacer**, et pas quand on l'autorise à
    # partir. La différence compte : l'accueil du lot L21 s'ouvre là-dessus, et
    # une fenêtre de choix qui apparaît par-dessus un logo encore visible donne
    # deux écrans superposés au moment précis où l'on découvre le produit.
    finished = Signal()

    HZ = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fondu = Fondu()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        chemin = resource_dir("assets", "brand") / ASSET
        self.pixmap = QPixmap(str(chemin)) if chemin.is_file() else QPixmap()
        if not self.pixmap.isNull():
            self.pixmap = self.pixmap.scaledToWidth(
                LOGO_W, Qt.TransformationMode.SmoothTransformation)
            self.setFixedSize(self.pixmap.size())
        else:
            self.setFixedSize(LOGO_W, 1)

        self.setWindowOpacity(0.0)
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // self.HZ)
        self._timer.timeout.connect(self._tick)

    # -- vie -----------------------------------------------------------------

    @property
    def fini(self) -> bool:
        """L'écran est-il déjà parti ? Vrai aussi s'il n'a jamais pu paraître.

        Un appelant qui attend `finished` doit d'abord poser cette question :
        sans logo à afficher, le signal ne partira jamais et ce qui l'attendait
        ne s'ouvrirait pas.
        """
        return self.fondu.fini

    def begin(self, centre: tuple[float, float], dpr: float = 1.0) -> None:
        """Affiche l'écran, centré sur un point donné en pixels **physiques**."""
        if self.pixmap.isNull():
            self.fondu.phase = FINI
            return
        self.move(int(centre[0] / dpr - self.width() / 2),
                  int(centre[1] / dpr - self.height() / 2))
        self.show()
        self._timer.start()

    def pump_entrance(self, app) -> None:
        """Joue le fondu d'entrée avant que la boucle d'évènements existe.

        C'est le seul endroit du produit qui tourne en attente active, et c'est
        assumé : il dure le temps du fondu, une fois par lancement, et il n'a
        aucune autre façon d'exister — le `QTimer` qui anime la suite ne tourne
        que sous `app.exec()`, qui n'est pas encore lancé à cet instant.
        """
        import time

        if self.fondu.fini:
            return
        dernier = time.perf_counter()
        while self.fondu.phase == ENTRANT:
            maintenant = time.perf_counter()
            self.fondu.step(maintenant - dernier)
            dernier = maintenant
            self.setWindowOpacity(self.fondu.opacite)
            app.processEvents()

    def finish(self) -> None:
        """L'application est prête : l'écran peut s'effacer, à son rythme."""
        self.fondu.pret()

    # -- rendu ---------------------------------------------------------------

    def _tick(self) -> None:
        self.fondu.step(1.0 / self.HZ)
        self.setWindowOpacity(self.fondu.opacite)
        if self.fondu.fini:
            self._timer.stop()
            self.close()
            self.finished.emit()
            self.deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self.pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, self.pixmap)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        """Un clic l'abrège. Il ne saute pas : il part en fondu, sinon la
        disparition se lit comme un défaut d'affichage."""
        self.fondu.pret()
        if self.fondu.phase == TENUE:
            self.fondu.phase, self.fondu.t = SORTANT, 0.0
