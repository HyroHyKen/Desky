"""Le choix du châssis, au tout premier lancement (lot L21).

Deux cartons, un par châssis, illustrés du dessin industriel du lot L20. On en
survole un pour lire ce qu'il est, on le clique, on confirme — et c'est réglé
pour la vie du robot.

**Pourquoi une confirmation.** Le châssis rejoint le génome, qui est l'identité
du robot et que la boutique ne touche jamais : contrairement à la couleur ou au
chapeau, il ne se change plus. Un choix irréversible pris au premier clic d'une
fenêtre qu'on découvre serait un piège ; la modale est le seul endroit de
l'application où l'on demande confirmation, et c'est parce que c'est le seul
geste qu'on ne peut pas défaire.

**Le refus est prévu.** Fermer la fenêtre ou appuyer sur Échap ne bloque
personne : le robot garde alors le châssis que le tirage lui avait donné. C'est
un vrai tirage, pas un repli arbitraire, donc l'utilisateur ne perd rien — il a
seulement laissé le hasard décider, ce qui est exactement ce qui se passait
avant ce lot.

Peint à la main comme le panneau de soin et le carton : ce produit n'utilise pas
de widgets Qt standards, et une boîte de dialogue système au milieu de son
premier lancement jurerait autant qu'une police différente.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPixmap)
from PySide6.QtWidgets import QWidget

from ..genome.schema import CHASSIS
from . import chassis_art
from .motion import SpringBank, Stagger, Ticker

log = logging.getLogger("desky.ui")

# --- Fenêtre ---------------------------------------------------------------

WIDTH, HEIGHT = 880, 856
PAD = 26
RADIUS = 22

CARD_W, CARD_H = 324, 404
CARD_GAP = 44
CARD_TOP = 96

# --- Palette, celle du panneau de soin --------------------------------------

BG = QColor(248, 250, 251, 250)
BG_EDGE = QColor(18, 26, 33, 46)
INK = QColor(20, 26, 33)
INK_SOFT = QColor(90, 101, 112)
ACCENT = QColor(31, 168, 186)
CARD_BG = QColor(255, 255, 255)
CARD_EDGE = QColor(207, 217, 222)
VOILE = QColor(12, 20, 26, 170)

TITLE_SIZE = 21
LEAD_SIZE = 13
CARD_TITLE_SIZE = 17
BODY_SIZE = 12

# --- Le lore ----------------------------------------------------------------
#
# Il n'invente rien : chaque phrase s'appuie sur une vraie propriété du châssis.
# Un lore qui promettrait autre chose que ce que le moteur produit serait la
# première chose que l'utilisateur constaterait comme fausse.

LIBELLES = {"capsule": "Capsule", "monobloc": "Monobloc"}

DESCRIPTIONS = {
    "capsule": (
        "Le châssis d'origine, assemblé sans interruption depuis la première "
        "série. Tête articulée sur un corps distinct : il hoche, il penche, il "
        "se retourne pour suivre le curseur. Antennes, disques ou ailerons, "
        "toutes les oreilles du catalogue sortent de cette ligne. Chez Desky "
        "Inc. on l'appelle « celui qui a une nuque »."
    ),
    "monobloc": (
        "Coque d'un seul tenant, née d'un atelier qui voulait supprimer la "
        "jointure du cou, la pièce qui revenait le plus souvent au service "
        "après-vente. Ni oreilles ni articulation : un grand écran, et le bloc "
        "entier s'oriente. La note interne disait « moins de pièces, moins "
        "d'ennuis ». Elle est restée sur l'affiche de l'atelier."
    ),
}

# Fiche technique, une ligne par caractéristique. Tout y est inventé **sauf les
# cotes**, qui sont celles du dessin industriel du lot L20 : un plan qui annonce
# 94 mm à côté d'une fiche qui en annonce 80 est le genre de détail qui défait
# une immersion en une seconde. Un test compare les deux.
FICHES = {
    "capsule": (
        ("MISE EN SERVICE", "2017"),
        ("HAUTEUR", "87 mm"),
        ("LARGEUR", "50 mm"),
        ("MASSE À VIDE", "340 g"),
        ("ARTICULATIONS", "3 (cou, tête, buste)"),
        ("CALCULATEUR", "DK-4 « Colibri »"),
    ),
    "monobloc": (
        ("MISE EN SERVICE", "2023"),
        ("HAUTEUR", "89 mm"),
        ("LARGEUR", "47 mm"),
        ("MASSE À VIDE", "410 g"),
        ("ARTICULATIONS", "aucune"),
        ("CALCULATEUR", "DK-7 « Bourdon »"),
    ),
}

FICHE_TITRE = "FICHE TECHNIQUE"

TITRE = "Choisissez son châssis"
SOUS_TITRE = "DESKY INC.  ·  ATELIER D'ASSEMBLAGE"
MENTION = "Proportions, couleurs et visage : tout le reste est tiré au sort."
INVITE = "Survolez un châssis pour lire sa fiche."

CONFIRM_TITRE = "C'est définitif"
CONFIRM_CORPS = ("Votre robot naîtra sur un châssis %s. Ce choix fait partie de "
                 "son identité : il ne se change ni dans la boutique, ni plus "
                 "tard. Tout le reste pourra évoluer.")
CONFIRM_OUI = "C'est celui-là"
CONFIRM_NON = "Revenir"

# --- Défilement des exemples ------------------------------------------------

# Amplitudes du mouvement. Réglées à l'œil, et volontairement franches : un
# rebond qu'on devine n'est pas un rebond, c'est une imprécision.
ENTREE_ECHELLE = 0.84       # échelle de départ d'une carte qui arrive
ENTREE_MONTEE = 34.0        # pixels parcourus pendant l'entrée
SURVOL_ECHELLE = 0.045      # agrandissement au survol
SURVOL_MONTEE = 10.0        # levée au survol
APPUI_ECHELLE = 0.07        # écrasement d'un bouton enfoncé

VIGNETTE_H = 96
VIGNETTE_GAP = 12
DEFILEMENT = 26.0               # pixels par seconde


class ChassisChooser(QWidget):
    """Les deux cartons, l'infobulle et la confirmation.

    `chosen` porte le châssis retenu ; `dismissed` le fait que l'utilisateur
    soit parti sans choisir. Exactement un des deux part, toujours.
    """

    chosen = Signal(str)
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setFixedSize(WIDTH, HEIGHT)

        self.familles = [c for c in CHASSIS]
        self._plans: dict[str, QPixmap] = {}
        self._exemples: dict[str, list[QPixmap]] = {}
        self._charger()

        self._survol = ""           # châssis survolé, "" si aucun
        self._confirme = ""         # châssis en attente de confirmation
        self._fini = False
        self._defile = 0.0

        # Trois bancs, trois raideurs. Le survol est le plus vif et le plus
        # sous-amorti : c'est lui qu'on voit répondre au geste. Le voile ne
        # dépasse pas — un fond qui rebondit se lit comme un défaut d'affichage.
        self._entree = Stagger(delai=0.10, duree=0.46)
        self._ressorts = SpringBank(omega=17.0, zeta=0.55)
        self._voile = SpringBank(omega=15.0, zeta=1.0)
        self._modale = SpringBank(omega=15.0, zeta=0.58)
        self._appui = SpringBank(omega=30.0, zeta=0.62)
        self._ticker = Ticker(self.step, self.update, self)

    # -- ressources ----------------------------------------------------------

    def _charger(self) -> None:
        for famille in self.familles:
            chemin = chassis_art.blueprint(famille)
            if chemin is not None:
                plan = QPixmap(str(chemin))
                if not plan.isNull():
                    self._plans[famille] = plan.scaledToWidth(
                        CARD_W - 2 * 14, Qt.TransformationMode.SmoothTransformation)
            vignettes = []
            for exemple in chassis_art.examples(famille):
                image = QPixmap(str(exemple))
                if not image.isNull():
                    vignettes.append(image.scaledToHeight(
                        VIGNETTE_H, Qt.TransformationMode.SmoothTransformation))
            self._exemples[famille] = vignettes

    # -- cycle de vie --------------------------------------------------------

    def start(self) -> None:
        self._entree.start(["titre"] + self.familles + ["mention"])
        self.show()
        self._ticker.wake()

    def step(self, dt: float) -> bool:
        # L'appui est **relâché à chaque image** : le bouton s'écrase au clic et
        # remonte ensuite tout seul, sans qu'on ait à guetter le relâchement de
        # la souris. C'est ce que fait déjà le panneau de soin.
        for cle in ("oui", "non"):
            self._appui.target(cle, 0.0)
        bouge = self._entree.step(dt)
        bouge = self._ressorts.step(dt) or bouge
        bouge = self._voile.step(dt) or bouge
        bouge = self._modale.step(dt) or bouge
        bouge = self._appui.step(dt) or bouge
        # Le défilement des exemples ne s'arrête jamais tant qu'un carton est
        # survolé : il est donc **exclu** du prédicat d'immobilité, sinon le
        # ticker tournerait pour lui seul alors qu'il n'y a rien à voir ailleurs.
        if self._survol and not self._confirme:
            self._defile += DEFILEMENT * dt
            return True
        return bouge

    def _terminer(self, famille: str) -> None:
        if self._fini:
            return
        self._fini = True
        self._ticker.stop()
        self.hide()
        if famille:
            log.info("châssis choisi : %s", famille)
            self.chosen.emit(famille)
        else:
            log.info("châssis non choisi : le tirage décide")
            self.dismissed.emit()
        self.deleteLater()

    # -- géométrie -----------------------------------------------------------

    def _card_rect(self, index: int) -> QRectF:
        total = len(self.familles) * CARD_W + (len(self.familles) - 1) * CARD_GAP
        x = (WIDTH - total) / 2.0 + index * (CARD_W + CARD_GAP)
        return QRectF(x, CARD_TOP, CARD_W, CARD_H)

    def _famille_a(self, x: float, y: float) -> str:
        for index, famille in enumerate(self.familles):
            if self._card_rect(index).contains(x, y):
                return famille
        return ""

    def _boutons_confirmation(self) -> tuple[QRectF, QRectF]:
        largeur, hauteur, ecart = 168.0, 46.0, 16.0
        boite = self._boite_confirmation()
        y = boite.bottom() - PAD - hauteur
        cx = boite.center().x()
        return (QRectF(cx - largeur - ecart / 2.0, y, largeur, hauteur),
                QRectF(cx + ecart / 2.0, y, largeur, hauteur))

    def _boite_confirmation(self) -> QRectF:
        largeur, hauteur = 470.0, 232.0
        return QRectF((WIDTH - largeur) / 2.0, (HEIGHT - hauteur) / 2.0,
                      largeur, hauteur)

    # -- souris --------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:      # noqa: N802 (API Qt)
        if self._confirme:
            return
        survol = self._famille_a(event.position().x(), event.position().y())
        if survol != self._survol:
            self._survol = survol
            self._defile = 0.0
            for famille in self.familles:
                self._ressorts.target(famille, 1.0 if famille == survol else 0.0)
            self._ticker.wake()

    def mousePressEvent(self, event) -> None:     # noqa: N802 (API Qt)
        x, y = event.position().x(), event.position().y()
        if self._confirme:
            oui, non = self._boutons_confirmation()
            if oui.contains(x, y):
                self._appui.target("oui", 1.0)
                self._terminer(self._confirme)
            elif non.contains(x, y) or not self._boite_confirmation().contains(x, y):
                self._appui.target("non", 1.0 if non.contains(x, y) else 0.0)
                self._confirme = ""
                self._voile.target("voile", 0.0)
                self._modale.target("modale", 0.0)
                self._ticker.wake()
            return

        famille = self._famille_a(x, y)
        if famille:
            self._confirme = famille
            self._survol = ""
            self._voile.target("voile", 1.0)
            self._modale.target("modale", 1.0)
            for autre in self.familles:
                self._ressorts.target(autre, 0.0)
            self._ticker.wake()

    def keyPressEvent(self, event) -> None:       # noqa: N802 (API Qt)
        if event.key() == Qt.Key.Key_Escape:
            if self._confirme:
                self._confirme = ""
                self._voile.target("voile", 0.0)
                self._modale.target("modale", 0.0)
                self._ticker.wake()
            else:
                self._terminer("")

    def closeEvent(self, event) -> None:          # noqa: N802 (API Qt)
        if not self._fini:
            self._terminer("")
        event.accept()

    # -- peinture ------------------------------------------------------------

    def paintEvent(self, event) -> None:          # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        fond = QRectF(0.5, 0.5, WIDTH - 1.0, HEIGHT - 1.0)
        painter.setPen(BG_EDGE)
        painter.setBrush(BG)
        painter.drawRoundedRect(fond, RADIUS, RADIUS)

        self._peindre_titre(painter)
        for index, famille in enumerate(self.familles):
            self._peindre_carton(painter, index, famille)
        self._peindre_infobulle(painter)
        self._peindre_mention(painter)
        if self._confirme or self._voile.value("voile") > 0.01:
            self._peindre_confirmation(painter)
        painter.end()

    def _police(self, taille: int, gras: bool = False,
                espacement: float = 0.0) -> QFont:
        police = QFont()
        police.setPixelSize(taille)
        if gras:
            police.setWeight(QFont.Weight.Bold)
        if espacement:
            police.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, espacement)
        return police

    def _peindre_titre(self, painter: QPainter) -> None:
        part = self._entree.value("titre")
        painter.setOpacity(part)
        painter.setFont(self._police(LEAD_SIZE, espacement=2.2))
        painter.setPen(ACCENT)
        painter.drawText(QRectF(0, PAD, WIDTH, 20),
                         int(Qt.AlignmentFlag.AlignCenter), SOUS_TITRE)
        painter.setFont(self._police(TITLE_SIZE, gras=True, espacement=0.4))
        painter.setPen(INK)
        painter.drawText(QRectF(0, PAD + 24, WIDTH, 30),
                         int(Qt.AlignmentFlag.AlignCenter), TITRE)
        painter.setOpacity(1.0)

    def _peindre_carton(self, painter: QPainter, index: int,
                        famille: str) -> None:
        """Entrée et survol passent tous deux par l'**échelle**.

        Une carte qui ne fait que glisser arrive sans poids : c'est le
        dépassement d'échelle qui lui en donne, exactement comme au lot L9. La
        courbe de `Stagger` rend des valeurs au-dessus de 1 au milieu du
        mouvement, et c'est ce dépassement qu'on cherche ici — l'opacité, elle,
        est bornée, parce qu'une opacité qui dépasse ne se voit pas et masque le
        rebond au lieu de l'accompagner.
        """
        part = self._entree.value(famille)
        if part <= 0.001:
            return
        leve = self._ressorts.value(famille)
        rect = self._card_rect(index)

        echelle = (ENTREE_ECHELLE + (1.0 - ENTREE_ECHELLE) * part
                   + SURVOL_ECHELLE * leve)
        monte = ENTREE_MONTEE * (1.0 - part) - SURVOL_MONTEE * leve

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, part)))
        centre = rect.center()
        painter.translate(centre.x(), centre.y() + monte)
        painter.scale(echelle, echelle)
        painter.translate(-centre.x(), -centre.y())

        # L'ombre portée grandit avec la levée : c'est elle qui dit que la carte
        # a décollé, plus encore que son déplacement.
        if leve > 0.01:
            ombre = QColor(20, 60, 72, int(38 * min(1.0, leve)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ombre)
            painter.drawRoundedRect(rect.translated(0.0, 10.0 * leve + 6.0),
                                    RADIUS + 2, RADIUS + 2)

        painter.setPen(ACCENT if leve > 0.45 else CARD_EDGE)
        painter.setBrush(CARD_BG)
        painter.drawRoundedRect(rect, RADIUS, RADIUS)

        plan = self._plans.get(famille)
        if plan is not None:
            zone = QRectF(rect.left() + 14, rect.top() + 14,
                          rect.width() - 28, rect.height() - 72)
            chemin = QPainterPath()
            chemin.addRoundedRect(zone, 14, 14)
            painter.save()
            painter.setClipPath(chemin)
            # Cadré par le haut : le cartouche du plan est en bas, et c'est la
            # silhouette qui doit rester visible quand la place manque.
            painter.drawPixmap(int(zone.left()), int(zone.top()), plan)
            painter.restore()

        painter.setFont(self._police(CARD_TITLE_SIZE, gras=True, espacement=1.6))
        painter.setPen(INK)
        painter.drawText(QRectF(rect.left(), rect.bottom() - 52,
                                rect.width(), 34),
                         int(Qt.AlignmentFlag.AlignCenter),
                         LIBELLES.get(famille, famille).upper())
        painter.restore()

    def _boite_infobulle(self) -> QRectF:
        haut = CARD_TOP + CARD_H + 18
        return QRectF(PAD, haut, WIDTH - 2 * PAD, HEIGHT - haut - 56)

    def _peindre_infobulle(self, painter: QPainter) -> None:
        """La boîte est **toujours là**, pleine ou vide.

        La faire apparaître au survol décalerait la mention du bas à chaque
        passage de souris ; une interface qui saute pendant qu'on hésite donne
        l'impression qu'on a cliqué par erreur.
        """
        boite = self._boite_infobulle()
        painter.setOpacity(max(0.0, min(1.0, self._entree.value("mention"))))
        painter.setPen(CARD_EDGE)
        painter.setBrush(QColor(255, 255, 255, 238))
        painter.drawRoundedRect(boite, 16, 16)

        famille = self._survol
        if not famille or self._confirme:
            painter.setFont(self._police(BODY_SIZE))
            painter.setPen(QColor(152, 162, 172))
            painter.drawText(boite, int(Qt.AlignmentFlag.AlignCenter), INVITE)
            painter.setOpacity(1.0)
            return

        # Le contenu entre en décalé par rapport à la boîte : c'est ce qui fait
        # qu'on lit un panneau qui se remplit, et non un panneau qui change.
        arrivee = max(0.0, min(1.0, self._ressorts.value(famille)))
        painter.setOpacity(arrivee)
        haut = boite.top() + 16
        colonne = (boite.width() - 3 * 20) * 0.58

        texte = QRectF(boite.left() + 20, haut, colonne, 132)
        painter.setFont(self._police(BODY_SIZE))
        painter.setPen(INK_SOFT)
        painter.drawText(texte,
                         int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop),
                         DESCRIPTIONS.get(famille, ""))

        self._peindre_fiche(painter, famille,
                            QRectF(texte.right() + 20, haut,
                                   boite.right() - texte.right() - 40, 132))
        painter.setOpacity(1.0)
        self._peindre_defilement(painter, famille, boite)

    def _peindre_fiche(self, painter: QPainter, famille: str,
                       zone: QRectF) -> None:
        """La fiche technique, en colonne d'étiquettes et de valeurs.

        Alignée en deux colonnes plutôt qu'en phrases : c'est ce qui la fait
        lire comme une notice d'usine et non comme un paragraphe de plus.
        """
        lignes = FICHES.get(famille, ())
        if not lignes:
            return

        painter.setFont(self._police(BODY_SIZE - 2, gras=True, espacement=1.4))
        painter.setPen(ACCENT)
        painter.drawText(QRectF(zone.left(), zone.top(), zone.width(), 16),
                         int(Qt.AlignmentFlag.AlignLeft), FICHE_TITRE)

        y = zone.top() + 22.0
        pas = 19.0
        largeur_cle = zone.width() * 0.52
        for cle, valeur in lignes:
            painter.setFont(self._police(BODY_SIZE - 2, espacement=0.6))
            painter.setPen(QColor(150, 160, 170))
            painter.drawText(QRectF(zone.left(), y, largeur_cle, pas),
                             int(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter), cle)
            painter.setFont(self._police(BODY_SIZE - 1, gras=True))
            painter.setPen(INK)
            painter.drawText(QRectF(zone.left() + largeur_cle, y,
                                    zone.width() - largeur_cle, pas),
                             int(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter), valeur)
            y += pas

    def _peindre_defilement(self, painter: QPainter, famille: str,
                            boite: QRectF) -> None:
        vignettes = self._exemples.get(famille) or []
        if not vignettes:
            return
        bande = QRectF(boite.left() + 12, boite.bottom() - VIGNETTE_H - 14,
                       boite.width() - 24, VIGNETTE_H + 6)
        chemin = QPainterPath()
        chemin.addRoundedRect(bande, 10, 10)
        painter.save()
        painter.setClipPath(chemin)

        largeurs = [v.width() + VIGNETTE_GAP for v in vignettes]
        boucle = sum(largeurs)
        # Deux passes : la seconde recolle la file derrière la première, ce qui
        # fait un ruban sans fin. Sans elle on verrait le vide revenir.
        depart = bande.left() - (self._defile % boucle)
        x = depart
        for _ in range(2):
            for vignette, largeur in zip(vignettes, largeurs):
                if x + largeur > bande.left() and x < bande.right():
                    painter.drawPixmap(int(x), int(bande.top()), vignette)
                x += largeur
        painter.restore()

    def _peindre_mention(self, painter: QPainter) -> None:
        part = self._entree.value("mention")
        painter.setOpacity(part)
        painter.setFont(self._police(BODY_SIZE))
        painter.setPen(INK_SOFT)
        painter.drawText(QRectF(0, HEIGHT - 46, WIDTH, 24),
                         int(Qt.AlignmentFlag.AlignCenter), MENTION)
        painter.setOpacity(1.0)

    def _peindre_confirmation(self, painter: QPainter) -> None:
        part = max(0.0, min(1.0, self._voile.value("voile")))
        voile = QColor(VOILE)
        voile.setAlpha(int(VOILE.alpha() * part))
        chemin = QPainterPath()
        chemin.addRoundedRect(QRectF(0, 0, WIDTH, HEIGHT), RADIUS, RADIUS)
        painter.setClipPath(chemin)
        painter.fillRect(QRectF(0, 0, WIDTH, HEIGHT), voile)
        painter.setClipping(False)

        pop = self._modale.value("modale")
        if pop <= 0.02:
            return

        boite = self._boite_confirmation()
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, pop)))
        # Le ressort de la modale est sous-amorti : `pop` passe au-dessus de 1
        # puis revient, et c'est ce dépassement qui la fait « claquer » à
        # l'arrivée au lieu de se déplier mollement.
        centre = boite.center()
        echelle = 0.88 + 0.12 * pop
        painter.translate(centre.x(), centre.y())
        painter.scale(echelle, echelle)
        painter.translate(-centre.x(), -centre.y())

        painter.setPen(CARD_EDGE)
        painter.setBrush(CARD_BG)
        painter.drawRoundedRect(boite, 18, 18)

        painter.setFont(self._police(CARD_TITLE_SIZE, gras=True))
        painter.setPen(INK)
        painter.drawText(QRectF(boite.left() + PAD, boite.top() + 18,
                                boite.width() - 2 * PAD, 26),
                         int(Qt.AlignmentFlag.AlignCenter), CONFIRM_TITRE)

        corps = CONFIRM_CORPS % LIBELLES.get(self._confirme or "capsule",
                                             "Capsule")
        painter.setFont(self._police(BODY_SIZE))
        painter.setPen(INK_SOFT)
        painter.drawText(QRectF(boite.left() + PAD, boite.top() + 52,
                                boite.width() - 2 * PAD, 76),
                         int(Qt.TextFlag.TextWordWrap
                             | Qt.AlignmentFlag.AlignHCenter), corps)

        oui, non = self._boutons_confirmation()
        for rect, libelle, plein, cle in ((non, CONFIRM_NON, False, "non"),
                                          (oui, CONFIRM_OUI, True, "oui")):
            enfonce = self._appui.value(cle)
            painter.save()
            milieu = rect.center()
            facteur = 1.0 - APPUI_ECHELLE * max(0.0, min(1.0, enfonce))
            painter.translate(milieu.x(), milieu.y())
            painter.scale(facteur, facteur)
            painter.translate(-milieu.x(), -milieu.y())
            painter.setPen(Qt.PenStyle.NoPen if plein else CARD_EDGE)
            painter.setBrush(ACCENT if plein else QColor(0, 0, 0, 0))
            painter.drawRoundedRect(rect, rect.height() / 2.0,
                                    rect.height() / 2.0)
            painter.setFont(self._police(BODY_SIZE + 2, gras=plein))
            painter.setPen(QColor(255, 255, 255) if plein else INK)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), libelle)
            painter.restore()
        painter.restore()
