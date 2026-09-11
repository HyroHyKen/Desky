"""Panneau de soin, ouvert au clic droit sur le pet (CDC §13, lot L6 phase B).

Une petite interface qui apparaît **au-dessus de la tête** du pet, faite de
carrés arrondis portant chacun une icône. Quatre pages depuis le menu racine :
statut, interactions, boutique, quitter.

**Aucun texte**, sauf le nom du robot — sa saisie au premier lancement et son
affichage ici. C'est la seule exception de toute l'application.

Deux partis pris d'implémentation méritent d'être expliqués.

**Tout est peint, rien n'est un widget.** Un seul `paintEvent` dessine le fond,
les boutons et les barres ; les clics sont testés contre la même liste de
rectangles qui a servi à peindre. Une hiérarchie de `QPushButton` stylés en
feuille de style aurait demandé autant de code pour un rendu moins maîtrisé, et
surtout la géométrie aurait existé en deux endroits — celui qui peint et celui
qui reçoit les clics. Ici elle n'existe qu'une fois, dans `_layout`.

**Le panneau ne prend pas le focus**, sauf pour la saisie du nom. Un panneau
qui vole le focus interrompt ce que l'utilisateur était en train de faire, et
c'est inacceptable pour un logiciel de bureau permanent. La page de nommage est
la seule qui en ait besoin, et elle l'active explicitement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLineEdit, QToolTip, QWidget

from ..anim.easing import ease_in, ease_out_back
from ..brain.economy import DAILY_CAP
from ..brain.needs import NEEDS
from ..feedback import bus
from ..geometry.cosmetics import NONE, SLOTS, by_slot, price as cosmetic_price
from ..genome.schema import ACCENT_COLORS, BODY_COLORS, hex_to_rgb
from .item import ITEM_KINDS
from .icons import MOOD_ICONS, center_square, draw_icon
from .motion import SpringBank, Ticker, Tween

# -- métriques, toutes en pixels logiques Qt ---------------------------------
#
# Le panneau est le **seul** endroit du projet qui raisonne en pixels logiques :
# c'est un widget Qt ordinaire, et Qt gère son échelle. Le pet, lui, est en
# pixels physiques de bout en bout (cf. app.window). La frontière entre les deux
# est le placement du panneau, et elle est franchie en un seul point.
PAD = 14
BUTTON = 46
GAP = 9
RADIUS = 13
BAR_HEIGHT = 15
BAR_GAP = 9
HEADER = 40
NAME_HEIGHT = 34

# Largeur : **cinq** boutons en ligne, depuis l'arrivée de la page de
# personnalisation. Toutes les pages s'y conforment, pour que le panneau ne
# change pas de largeur en changeant de page — un panneau qui respire à chaque
# navigation est fatigant.
MENU_COLUMNS = 6
WIDTH = MENU_COLUMNS * BUTTON + (MENU_COLUMNS - 1) * GAP + 2 * PAD

# Pastilles de couleur. Plus petites que les boutons : il y en a six sur une
# ligne, et une pastille de couleur n'a pas besoin d'être grande pour être
# reconnue — c'est même l'inverse, un grand aplat écrase le reste de la page.
SWATCH = 36
SWATCH_GAP = 8
SWATCH_RADIUS = 11

# Vignettes de la boutique : le bouton, plus une ligne de prix sous lui.
TILE = 52
TILE_LABEL = 15
TILE_GAP = 8
SHOP_COLUMNS = 4

# Appui long de la réinitialisation. Deux secondes, parce que le geste est
# irréversible et que l'interface n'a **pas de texte** pour demander
# confirmation : la durée tient lieu de « êtes-vous sûr ».
HOLD_SECONDS = 2.0
HOLD_TICK_MS = 30

# -- animation (lot L9) ------------------------------------------------------
#
# Durées dissymétriques, et c'est voulu : on regarde une interface s'ouvrir, on
# ne regarde pas une interface se fermer. Une sortie aussi longue que l'entrée
# donne l'impression que le logiciel traîne.
OPEN_SECONDS = 0.26
CLOSE_SECONDS = 0.15

# Échelle du panneau au tout début de son ouverture. Pas zéro : un panneau qui
# naît d'un point est un effet de diaporama. Il arrive presque à sa taille, et
# `ease_out_back` lui fait dépasser la sienne d'un cheveu avant de se poser —
# c'est ce dépassement, et lui seul, qui fait la différence de sensation.
OPEN_SCALE = 0.92

# Réponse des boutons. L'appui **enfonce** — échelle inférieure à 1 — et le
# relâchement repasse par-dessus grâce au sous-amortissement du ressort. Le
# survol soulève à peine : il signale, il ne célèbre pas.
PRESS_SCALE = 0.88
HOVER_SCALE = 1.04
PRESS_SPRING = (34.0, 0.55)          # omega, zeta — vif, et il dépasse
HOVER_SPRING = (26.0, 0.85)          # plus calme, presque sans dépassement


def _melange(a: QColor, b: QColor, t: float) -> QColor:
    """Interpole deux couleurs.

    `t` est borné, à la différence de l'échelle : un ressort sous-amorti passe
    au-dessus de 1, ce qu'on veut voir sur une taille — c'est le dépassement du
    §10 — mais pas sur une couleur, où cela ne donnerait qu'une teinte hors
    gamme, saturée au hasard du canal qui sature le premier.
    """
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


# Couleurs. Fixes et non génétiques, comme la bulle : c'est de l'interface, elle
# doit rester lisible quelle que soit la teinte du robot tiré.
BG = QColor(248, 250, 251, 246)
BG_EDGE = QColor(18, 26, 33, 40)
INK = QColor(20, 26, 33)
INK_SOFT = QColor(90, 101, 112)
BUTTON_BG = QColor(226, 231, 234)
BUTTON_HOVER = QColor(206, 216, 221)
BUTTON_OFF = QColor(236, 239, 241)
INK_OFF = QColor(176, 184, 191)
BAR_BG = QColor(224, 229, 232)
BAR_FILL = QColor(31, 168, 186)
BAR_LOW = QColor(196, 112, 58)
SWATCH_EDGE = QColor(24, 32, 40, 90)

# Sous ce niveau, une barre de besoin passe en ambre. Le même seuil que celui
# qui fait apparaître la bulle : il ne doit pas y avoir deux définitions de
# « ce besoin réclame de l'attention ».
BAR_LOW_LEVEL = 45.0

# Une page de rayon par emplacement, **dérivée** de la liste des emplacements :
# ajouter une famille d'articles ajoute sa page sans qu'on y touche.
SHOP_PAGES: tuple[str, ...] = tuple("shop_" + s for s in SLOTS)

PAGES = ("menu", "status", "interactions", "custom", "shop") + SHOP_PAGES + (
    "settings", "name")

# ---------------------------------------------------------------------------
# Libellés
# ---------------------------------------------------------------------------
#
# **Tout le texte de l'application est ici**, et nulle part ailleurs. La règle
# du lot L6 — « jamais de texte » — a été levée à la demande de l'utilisateur :
# des titres de page et des infobulles rendent les pictogrammes explicites, et
# c'est un gain d'usage réel.
#
# Elle laisse une conséquence dont il faut tenir compte : l'interface devient
# **traduisible**, donc localisable un jour. Les regrouper dans une table unique
# est ce qui rend cette traduction possible plus tard sans relire le code — et
# c'est gratuit aujourd'hui. Aucune chaîne affichée ne doit être écrite en
# ligne dans une méthode de peinture ; un test le vérifie.

# Titre de chaque page. **`status` n'en a pas** : sa pastille d'humeur, le nom
# du robot et les quatre barres se suffisent, et un titre y répéterait ce que
# la page montre déjà.
# Nom lisible de chaque emplacement, au pluriel : c'est un rayon.
SLOT_LABELS: dict[str, str] = {
    "hat": "Chapeaux",
    "moustache": "Moustaches",
}

PAGE_TITLES: dict[str, str] = {
    "interactions": "Interactions",
    "custom": "Apparence",
    "shop": "Boutique",
    "settings": "Réglages",
    "name": "Quel est mon nom ?",
}
PAGE_TITLES.update({"shop_" + s: SLOT_LABELS.get(s, s) for s in SLOTS})

# Infobulle de chaque bouton. C'est ici que les pictogrammes obscurs se
# rattrapent : une grille de quatre carrés ne dit pas « interactions », et une
# étiquette de prix ne dit pas « boutique », tant qu'on ne les a pas survolés
# une première fois.
TOOLTIPS: dict[str, str] = {
    # Navigation
    "status": "Voir son état",
    "interactions": "S'occuper de lui",
    "custom": "Changer son apparence",
    "shop": "Boutique",
    "settings": "Réglages",
    "quit": "Quitter",
    "back": "Retour",
    "check": "Valider",
    # Soins
    "feed": "Lui donner à manger",
    "play": "Jouer avec lui",
    "pet": "Le caresser",
    "clean": "Le nettoyer",
    # Réglages
    "autostart": "Lancer au démarrage de Windows",
    "reset": "Tout réinitialiser — maintenir appuyé",
}

# Infobulles des choix d'apparence, construites à la volée : une par couleur et
# une par chapeau serait une table à tenir à jour à chaque ajout.
TOOLTIP_SWATCH = "Couleur : %s"
TOOLTIP_HAT_BUY = "%s — %d jetons"
TOOLTIP_HAT_WEAR = "Porter : %s"
TOOLTIP_HAT_WORN = "Porté : %s"
TOOLTIP_NO_HAT = "Ne rien porter"

# Nom lisible des articles, pour les infobulles. Un article sans entrée ici
# affiche sa clé : lisible en dépannage, et le test de couverture le signale.
ITEM_LABELS: dict[str, str] = {
    "bow": "Nœud",
    "beanie": "Bonnet",
    "cap": "Casquette",
    "party": "Chapeau de fête",
    "tophat": "Haut-de-forme",
    "helmet": "Casque",
    "crown": "Couronne",
    "pencil": "Fine",
    "handlebar": "À guidon",
    "walrus": "De morse",
}
TOOLTIP_CATEGORY = "Voir les %s"

# Hauteur de la bande de titre, et sa police.
TITLE_H = 26
TITLE_SIZE = 15

# Boutons du menu racine. La personnalisation se glisse **avant** la boutique :
# les deux touchent à l'apparence, et celle qui est gratuite doit se trouver la
# première.
MENU_ACTIONS = ("status", "interactions", "custom", "shop", "settings",
                "quit")

# Actions qui exigent un appui maintenu. La seule pour l'instant, et la seule
# qui détruise quoi que ce soit.
HOLD_ACTIONS = frozenset({"reset"})

# Ce que l'utilisateur peut choisir, et dans quel ordre l'afficher. La couleur
# est pour l'instant la seule variable modifiable sans token ; la boutique du
# lot L7 ajoutera des lignes ici, pas un mécanisme.
SWATCH_ROWS = (
    ("palette.body", BODY_COLORS),
    ("palette.accent", ACCENT_COLORS),
)

# Soins de la page d'interactions, et l'icône de chacun.
CARE_ACTIONS = ("feed", "play", "pet", "clean")


@dataclass
class Button:
    """Un carré arrondi cliquable. Peint et testé depuis la même donnée.

    `swatch` porte une couleur au lieu d'une icône : c'est le même objet, donc
    le même test de clic et la même boucle de peinture, avec un rendu différent.
    Un second type de bouton aurait dupliqué les deux.
    """

    rect: QRectF
    icon: str
    action: str
    enabled: bool = True
    swatch: str = ""            # couleur hexadécimale, vide = icône
    selected: bool = False
    # Vignette de boutique : l'aperçu rendu en 3D, et le prix. Un prix négatif
    # veut dire « rien à payer » — article possédé, ou tête nue.
    preview: object = None
    price: int = -1


@dataclass
class Layout:
    """Géométrie complète d'une page."""

    height: int
    buttons: list[Button] = field(default_factory=list)
    bars: list[tuple[str, float]] = field(default_factory=list)
    mood: str = ""
    name: str = ""
    big_icon: str = ""
    tokens: int = -1            # solde affiché, -1 pour ne rien montrer
    title: str = ""


class CarePanel(QWidget):
    """Panneau de soin. Sans état propre : il lit la session à chaque peinture."""

    care_requested = Signal(str)
    quit_requested = Signal()
    name_submitted = Signal(str)
    appearance_chosen = Signal(str, str)
    item_chosen = Signal(str, str)
    reset_requested = Signal()
    autostart_toggled = Signal()

    def __init__(self, session, genome: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        # Le génome sert uniquement à savoir de quelle couleur le robot est
        # **né**, pour cocher la bonne pastille quand rien n'a été choisi. Le
        # panneau ne le modifie jamais : la personnalisation est un costume.
        self.genome = dict(genome or {})
        self.page = "menu"
        self._hover = -1

        # Fourni par la fenêtre : rendre un article demande le contexte GL, que
        # le panneau n'a pas et ne doit pas avoir.
        self.item_preview = None
        # Appui long en cours : l'action visée et sa progression.
        self._hold_action = ""
        self._hold = 0.0
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(HOLD_TICK_MS)
        self._hold_timer.timeout.connect(self._hold_tick)
        # Renseigné par la fenêtre : un seul objet de soin peut traîner sur le
        # bureau à la fois, donc les trois soins qui en produisent un se grisent
        # ensemble tant qu'il n'est ni rejoint ni évaporé.
        self.item_pending = False

        # -- animation (lot L9) ---------------------------------------------
        #
        # L'état d'animation vit **à côté** de la mise en page, jamais dedans :
        # `_layout()` reste une fonction pure de la session, recalculée à chaque
        # peinture, et c'est ce qui rend le panneau simple. Les ressorts sont
        # indexés par `Button.action`, l'identité que le test de clic utilise
        # déjà — un indice de rangée ne survivrait pas à un changement de page.
        self._ouverture = Tween(0.0)
        self._survol = SpringBank(*HOVER_SPRING)
        self._appui = SpringBank(*PRESS_SPRING)
        self._appui_action = ""
        self._fermeture = False
        self._ticker = Ticker(self.step, self.update, self)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Par défaut le panneau n'active pas sa fenêtre : il ne doit pas
        # interrompre ce que l'utilisateur tape. La page de nommage lève cette
        # règle pour elle seule, dans `open_page`.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setFixedWidth(WIDTH)

        self._edit = QLineEdit(self)
        self._edit.setMaxLength(20)
        self._edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._edit.setFrame(False)
        self._edit.hide()
        self._edit.returnPressed.connect(self._submit_name)
        font = QFont()
        font.setPixelSize(17)
        font.setWeight(QFont.Weight.DemiBold)
        self._edit.setFont(font)
        self._edit.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 2px solid #1FA8BA;"
            " border-radius: 9px; color: #141A21; padding: 3px; }")

    # -- ouverture et fermeture (lot L9) -----------------------------------

    def open_panel(self) -> None:
        """Montre le panneau, et le fait arriver.

        Repartir de la valeur atteinte plutôt que de zéro compte : rouvrir un
        panneau qui n'a pas fini de se fermer doit le rattraper en vol, pas le
        faire disparaître pour le refaire naître.
        """
        deja_visible = self.isVisible()
        self._fermeture = False
        if not deja_visible:
            self._ouverture.jump(0.0)
            self.show()
        self._ouverture.to(1.0, OPEN_SECONDS, ease_out_back)
        self._ticker.wake()
        if not deja_visible:
            bus.emit("panneau_ouvert")

    def close_panel(self, immediat: bool = False) -> None:
        """Referme. `immediat` saute l'animation.

        Le mode immédiat n'est pas un raccourci de confort. Il sert quand ce
        que le panneau peint est en train de disparaître sous lui : à la
        réinitialisation, la session qu'il lit à chaque image est effacée, et
        une fermeture animée continuerait de la lire pendant ce temps.
        """
        if not self.isVisible():
            return
        if immediat:
            self._fermeture = False
            self._ouverture.jump(0.0)
            self._ticker.stop()
            self.hide()
            bus.emit("panneau_ferme")
            return
        if self._fermeture:
            return
        self._fermeture = True
        self._ouverture.to(0.0, CLOSE_SECONDS, ease_in)
        self._ticker.wake()

    @property
    def closing(self) -> bool:
        """Une fermeture est en cours. Le panneau est encore visible."""
        return self._fermeture

    def step(self, dt: float) -> bool:
        """Avance l'animation de `dt`. Rend `True` tant que quelque chose bouge.

        Point d'entrée unique, appelé par le `Ticker` en production et
        directement par les tests avec un `dt` synthétique — sans timer, sans
        horloge réelle, donc sans durée fausse.
        """
        bouge = self._ouverture.step(dt)
        bouge = self._survol.step(dt) or bouge
        bouge = self._appui.step(dt) or bouge

        if self._fermeture and not self._ouverture.moving:
            self._fermeture = False
            self.hide()
            bus.emit("panneau_ferme")
            return False
        return bouge

    def _sync_targets(self, boutons: list[Button]) -> None:
        """Pose les cibles de survol et d'appui, et oublie les disparus.

        Appelée depuis les gestes de souris, jamais depuis `paintEvent` : une
        peinture qui modifie l'état d'animation se rappellerait elle-même.
        """
        cles = [b.action for b in boutons]
        survole = boutons[self._hover].action if 0 <= self._hover < len(boutons) else ""
        for bouton in boutons:
            # Un bouton grisé ne réagit pas au survol : il répondrait à un
            # geste qu'il refusera ensuite.
            self._survol.target(bouton.action,
                                1.0 if (bouton.enabled and bouton.action == survole) else 0.0)
            self._appui.target(bouton.action,
                               1.0 if bouton.action == self._appui_action else 0.0)
        self._survol.keep(cles)
        self._appui.keep(cles)
        self._ticker.wake()

    def _echelle_bouton(self, action: str) -> float:
        """Échelle peinte d'un bouton : l'appui enfonce, le survol soulève."""
        appui = self._appui.value(action)
        survol = self._survol.value(action)
        return (1.0
                + (PRESS_SCALE - 1.0) * appui
                + (HOVER_SCALE - 1.0) * survol * max(0.0, 1.0 - appui))

    # -- navigation --------------------------------------------------------

    def open_page(self, page: str) -> None:
        if page not in PAGES:
            return
        change = page != self.page
        self.page = page
        layout = self._layout()
        self.setFixedHeight(layout.height)
        self._hover = -1
        # Les ressorts de la page quittée n'ont plus d'objet : leurs boutons
        # n'existent plus. Sans cette purge, le tic ne s'arrêterait jamais.
        self._appui_action = ""
        self._sync_targets(layout.buttons)
        if change:
            bus.emit("page_changee", page=page)

        if page == "name":
            self._edit.setGeometry(PAD, self._top(), WIDTH - 2 * PAD,
                                   NAME_HEIGHT)
            self._edit.clear()
            self._edit.show()
            # Seule page à réclamer le focus, et elle le prend franchement :
            # sans activation, la saisie serait impossible.
            self.raise_()
            self.activateWindow()
            self._edit.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self._edit.hide()
        self.update()

    def _submit_name(self) -> None:
        texte = self._edit.text()
        if texte.strip():
            self.name_submitted.emit(texte)
            bus.emit("nom_donne", nom=texte.strip())

    # -- géométrie ---------------------------------------------------------

    def _row(self, actions, y: int, enabled=None) -> list[Button]:
        """Une rangée de boutons, centrée sur la largeur du panneau."""
        total = len(actions) * BUTTON + (len(actions) - 1) * GAP
        x = (WIDTH - total) / 2.0
        out = []
        for action in actions:
            ok = True if enabled is None else bool(enabled(action))
            out.append(Button(QRectF(x, y, BUTTON, BUTTON), action, action, ok))
            x += BUTTON + GAP
        return out

    def _swatch_row(self, param: str, palette: dict, choisi: str,
                    y: int) -> list[Button]:
        """Une ligne de pastilles, centrée. Une seule est marquée choisie."""
        noms = tuple(palette)
        total = len(noms) * SWATCH + (len(noms) - 1) * SWATCH_GAP
        x = (WIDTH - total) / 2.0
        out = []
        for nom in noms:
            out.append(Button(QRectF(x, y, SWATCH, SWATCH), "", f"{param}={nom}",
                              swatch=palette[nom], selected=(nom == choisi)))
            x += SWATCH + SWATCH_GAP
        return out

    def _shop_root_layout(self) -> Layout:
        """Racine du rayon : une catégorie par emplacement.

        Dérivée de `SLOTS`, donc ajouter une famille d'articles ajoute son
        bouton sans qu'on y touche. C'est tout l'objet de cette page : elle ne
        se justifierait pas pour une seule catégorie, mais elle rend la suivante
        gratuite.
        """
        haut = self._top()
        y = haut + HEADER + BAR_GAP
        layout = Layout(height=int(y + BUTTON + GAP + BUTTON + PAD),
                        tokens=self.session.tokens,
                        title=PAGE_TITLES.get("shop", ""))
        layout.buttons = self._row(tuple("shop_" + s for s in SLOTS), y)
        layout.buttons += self._row(("back",), y + BUTTON + GAP)
        return layout

    def _shop_slot_layout(self, slot: str) -> Layout:
        """Un rayon : le choix « rien », puis les articles, et le solde.

        Les vignettes montrent l'article **rendu en trois dimensions sur le
        robot de l'utilisateur**, et non une icône dessinée. C'est plus juste —
        il voit exactement ce qu'il achète, avec ses couleurs — et cela évite
        d'entretenir un dessin par article dans un vocabulaire qui en compte
        déjà plus de vingt.
        """
        possede = set(self.session.inventory)
        porte = self.session.appearance.get(slot, NONE)
        solde = self.session.tokens

        articles = [(NONE, 0)] + [(c.key, c.price) for c in by_slot(slot)]
        layout = Layout(height=0, tokens=solde,
                        title=PAGE_TITLES.get("shop_" + slot, ""))

        lignes = (len(articles) + SHOP_COLUMNS - 1) // SHOP_COLUMNS
        pas = TILE + TILE_LABEL + TILE_GAP
        y = self._top() + HEADER + BAR_GAP
        for index, (cle, prix) in enumerate(articles):
            colonne = index % SHOP_COLUMNS
            rangee = index // SHOP_COLUMNS
            total = SHOP_COLUMNS * TILE + (SHOP_COLUMNS - 1) * TILE_GAP
            x = (WIDTH - total) / 2.0 + colonne * (TILE + TILE_GAP)
            achete = cle == NONE or cle in possede
            layout.buttons.append(Button(
                QRectF(x, y + rangee * pas, TILE, TILE),
                "", "cos:%s:%s" % (slot, cle),
                enabled=achete or solde >= prix,
                selected=(cle == porte),
                preview=self._preview(slot, cle),
                price=-1 if achete else prix,
            ))
        bas = y + lignes * pas
        layout.buttons += self._row(("back",), bas)
        layout.height = int(bas + BUTTON + PAD)
        return layout

    def _preview(self, slot: str, key: str):
        """Aperçu d'un article, fourni par la fenêtre. None si indisponible.

        Le panneau ne sait pas rendre : il demande. Sans fournisseur — dans un
        test, sur une planche — les vignettes restent vides et la page tient
        quand même debout.
        """
        if self.item_preview is None:
            return None
        try:
            return self.item_preview(slot, key)
        except Exception:                              # pragma: no cover
            return None

    def _top(self) -> int:
        """Ordonnée où commence le contenu, titre compris.

        Un seul point de calcul : chaque page ajoute la bande de titre au même
        endroit, donc en ajouter un à une page ne demande pas de retoucher sa
        géométrie.
        """
        return PAD + (TITLE_H if PAGE_TITLES.get(self.page) else 0)

    def _layout(self) -> Layout:
        """**Seule** source de la géométrie : peinture et clics en dérivent."""
        brain = self.session.brain
        nom = self.session.name
        haut = self._top()
        titre = PAGE_TITLES.get(self.page, "")

        if self.page == "menu":
            # Le menu racine porte le **nom du robot** en guise de titre : c'est
            # sa page d'accueil, et aucun libellé générique ne dirait mieux où
            # l'on se trouve.
            layout = Layout(height=BUTTON + 2 * PAD, title=nom)
            if nom:
                layout.height += TITLE_H
            layout.buttons = self._row(MENU_ACTIONS,
                                       PAD + (TITLE_H if nom else 0))
            return layout

        if self.page == "status":
            hauteur = (PAD + HEADER + BAR_GAP
                       + len(NEEDS) * (BAR_HEIGHT + BAR_GAP)
                       + BUTTON + PAD)
            layout = Layout(height=hauteur, mood=brain.expression, name=nom)
            layout.bars = [(n, getattr(brain.needs, n)) for n in NEEDS]
            layout.buttons = self._row(("back",),
                                       hauteur - PAD - BUTTON)
            return layout

        if self.page == "interactions":
            hauteur = haut + BUTTON + GAP + BUTTON + PAD
            layout = Layout(height=hauteur, title=titre)

            def offert(action: str) -> bool:
                if self.item_pending and action in ITEM_KINDS:
                    return False
                return brain.can_care(action)

            layout.buttons = self._row(CARE_ACTIONS, haut, enabled=offert)
            layout.buttons += self._row(("back",), haut + BUTTON + GAP)
            return layout

        if self.page == "custom":
            costume = self.session.appearance
            pastilles = len(SWATCH_ROWS) * (SWATCH + SWATCH_GAP)
            layout = Layout(height=haut + pastilles + BUTTON + PAD,
                            title=titre)
            y = haut
            for param, palette in SWATCH_ROWS:
                # Rien de choisi veut dire « la couleur de naissance » : on la
                # lit dans le génome pour que la coche se pose au bon endroit.
                courant = costume.get(param) or str(self.genome.get(param, ""))
                layout.buttons += self._swatch_row(param, palette, courant, y)
                y += SWATCH + SWATCH_GAP
            layout.buttons += self._row(("back",), haut + pastilles)
            return layout

        if self.page == "shop":
            return self._shop_root_layout()

        if self.page in SHOP_PAGES:
            return self._shop_slot_layout(self.page[len("shop_"):])

        if self.page == "settings":
            hauteur = haut + BUTTON + GAP + BUTTON + PAD
            layout = Layout(height=hauteur, title=titre)
            layout.buttons = self._row(("autostart", "reset"), haut)
            layout.buttons += self._row(("back",), haut + BUTTON + GAP)
            return layout

        # Nommage. La validation a **son bouton** : dans une interface sans
        # texte, « appuyez sur Entrée » ne se devine pas, et la touche reste
        # disponible pour qui la connaît.
        hauteur = haut + NAME_HEIGHT + GAP + BUTTON + PAD
        layout = Layout(height=hauteur, title=titre)
        layout.buttons = self._row(("check",), haut + NAME_HEIGHT + GAP)
        return layout

    # -- peinture ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        layout = self._layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Arrivée du panneau (lot L9). L'échelle et l'opacité sont **peintes**,
        # la géométrie du widget ne bouge pas : animer `setGeometry` ferait
        # travailler le gestionnaire de fenêtres trente fois par seconde pour
        # un widget translucide toujours au-dessus, et le résultat saccade.
        #
        # L'ancrage est le bas-centre : le panneau se pose au-dessus de la tête
        # du pet, et grandir depuis ce point-là donne l'impression qu'il en
        # sort. Grandir depuis le centre le ferait apparaître de nulle part.
        ouverture = self._ouverture.value
        # `abs(... - 1)` et non `< 1` : `ease_out_back` **dépasse** 1 avant de
        # revenir, et c'est ce dépassement que le §10 réclame. Un test qui ne
        # regarderait que « pas encore ouvert » le supprimerait sans bruit.
        if abs(ouverture - 1.0) > 1e-3:
            painter.setOpacity(max(0.0, min(1.0, ouverture)))
            k = OPEN_SCALE + (1.0 - OPEN_SCALE) * ouverture
            painter.translate(self.width() / 2.0, float(self.height()))
            painter.scale(k, k)
            painter.translate(-self.width() / 2.0, -float(self.height()))

        fond = QPainterPath()
        fond.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1.0,
                                   self.height() - 1.0), 18.0, 18.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BG)
        painter.drawPath(fond)
        painter.setPen(BG_EDGE)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(fond)

        if layout.title:
            self._paint_title(painter, layout.title)
        if layout.tokens >= 0:
            self._paint_purse(painter, layout.tokens)
        if layout.mood or layout.name:
            self._paint_header(painter, layout)
        for index, (need, value) in enumerate(layout.bars):
            y = PAD + HEADER + BAR_GAP + index * (BAR_HEIGHT + BAR_GAP)
            self._paint_bar(painter, need, value, y)
        if layout.big_icon:
            # Boutique vide : l'icône en gris pâle dit « ici, plus tard ».
            # Le catalogue et les tokens sont le lot L7.
            draw_icon(painter, layout.big_icon,
                      QRectF((WIDTH - 62) / 2.0, PAD + 7, 62, 62), INK_OFF)

        for index, button in enumerate(layout.buttons):
            # Échelle autour du **centre du bouton** : depuis l'origine du
            # panneau, un bouton du bas se déplacerait de trente pixels pour se
            # contracter de quatre.
            #
            # La transformation enveloppe aussi l'anneau d'appui long : il
            # entoure le bouton, il doit s'enfoncer avec lui. Peint en dehors,
            # il flotterait autour d'un bouton rétréci — et c'est justement sur
            # un appui maintenu qu'on a tout le temps de le remarquer.
            echelle = self._echelle_bouton(button.action)
            transforme = abs(echelle - 1.0) > 1e-4
            if transforme:
                centre = button.rect.center()
                painter.save()
                painter.translate(centre)
                painter.scale(echelle, echelle)
                painter.translate(-centre)
            self._paint_button(painter, button, index == self._hover)
            if button.action == self._hold_action and self._hold > 0.0:
                self._paint_hold(painter, button)
            if transforme:
                painter.restore()
        painter.end()

    def _paint_header(self, painter: QPainter, layout: Layout) -> None:
        pastille = QRectF(PAD, PAD, HEADER, HEADER)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BUTTON_BG)
        painter.drawRoundedRect(pastille, RADIUS, RADIUS)
        draw_icon(painter, MOOD_ICONS.get(layout.mood, "mood_neutral"),
                  center_square(pastille, 0.66), INK)

        if layout.name:
            # L'une des deux seules occurrences de texte de l'application.
            font = QFont()
            font.setPixelSize(17)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(INK)
            painter.drawText(
                QRectF(PAD + HEADER + GAP, PAD,
                       WIDTH - 2 * PAD - HEADER - GAP, HEADER),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                layout.name)

    def _paint_bar(self, painter: QPainter, need: str, value: float,
                   y: int) -> None:
        icone = QRectF(PAD, y - 2, BAR_HEIGHT + 4, BAR_HEIGHT + 4)
        draw_icon(painter, need, icone, INK_SOFT)

        x = PAD + BAR_HEIGHT + 4 + GAP
        largeur = WIDTH - PAD - x
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BAR_BG)
        painter.drawRoundedRect(QRectF(x, y, largeur, BAR_HEIGHT),
                                BAR_HEIGHT / 2.0, BAR_HEIGHT / 2.0)

        part = max(0.0, min(1.0, value / 100.0))
        if part > 0.001:
            # Plancher de largeur : une barre à 2 % doit rester visible comme
            # une barre, sinon elle se confond avec une barre vide.
            remplie = max(BAR_HEIGHT, largeur * part)
            painter.setBrush(BAR_LOW if value < BAR_LOW_LEVEL else BAR_FILL)
            painter.drawRoundedRect(QRectF(x, y, remplie, BAR_HEIGHT),
                                    BAR_HEIGHT / 2.0, BAR_HEIGHT / 2.0)

    def _paint_title(self, painter: QPainter, titre: str) -> None:
        """Titre de page, centré dans sa bande.

        Le texte vient toujours de `PAGE_TITLES` ou du nom du robot, jamais
        d'une chaîne écrite ici : c'est ce qui garde l'interface traduisible.
        """
        font = QFont()
        font.setPixelSize(TITLE_SIZE)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(INK)
        painter.drawText(
            QRectF(PAD, PAD - 2, WIDTH - 2 * PAD, TITLE_H),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            titre)

    def _paint_purse(self, painter: QPainter, tokens: int) -> None:
        """Solde : un jeton et un nombre.

        **Le seul chiffre de l'application**, et la seule entorse à la règle du
        sans-texte après le nom. Elle est assumée : un prix se dit en chiffres,
        et les rendre en pastilles serait illisible dès dix jetons. Aucun mot
        n'apparaît pour autant — un chiffre est universel, un libellé non.
        """
        haut = self._top()
        piece = QRectF(PAD, haut + 4, 22, 22)
        draw_icon(painter, "token", piece, INK)
        font = QFont()
        font.setPixelSize(17)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(INK)
        painter.drawText(
            QRectF(PAD + 28, haut, 90, HEADER),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            str(tokens))

        # Ce qu'il reste à gagner aujourd'hui, en gris : le plafond du §14 doit
        # être visible, sinon un joueur assidu croit l'application cassée.
        reste = int(getattr(self.session, "tokens_remaining", DAILY_CAP))
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(INK_SOFT)
        painter.drawText(
            QRectF(WIDTH - PAD - 90, haut, 90, HEADER),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            "+%d" % reste)

    def _paint_tile(self, painter: QPainter, button: Button,
                    hover: bool) -> None:
        """Vignette de boutique : l'aperçu, son état, et son prix."""
        painter.setPen(Qt.PenStyle.NoPen)
        if not button.enabled:
            fond = BUTTON_OFF
        elif button.selected or hover:
            fond = BUTTON_HOVER
        else:
            fond = BUTTON_BG
        painter.setBrush(fond)
        painter.drawRoundedRect(button.rect, RADIUS, RADIUS)

        apercu = button.preview
        if apercu is not None and not apercu.isNull():
            cible = button.rect.adjusted(3, 3, -3, -3)
            painter.setOpacity(1.0 if button.enabled else 0.45)
            painter.drawPixmap(cible, apercu, QRectF(apercu.rect()))
            painter.setOpacity(1.0)

        if button.selected:
            # Porté : un liseré, plus franc qu'une coche qui masquerait
            # l'aperçu qu'on vient justement de vouloir montrer.
            painter.setPen(QPen(BAR_FILL, 3.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(button.rect.adjusted(1.5, 1.5, -1.5, -1.5),
                                    RADIUS, RADIUS)

        if button.price >= 0:
            font = QFont()
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(INK if button.enabled else INK_OFF)
            ligne = QRectF(button.rect.left(), button.rect.bottom() + 1,
                           button.rect.width(), TILE_LABEL)
            draw_icon(painter, "token",
                      QRectF(ligne.left() + 6, ligne.top() + 2, 11, 11),
                      INK if button.enabled else INK_OFF)
            painter.drawText(
                QRectF(ligne.left() + 19, ligne.top(), ligne.width() - 22,
                       TILE_LABEL),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                str(button.price))

    def _paint_hold(self, painter: QPainter, button: Button) -> None:
        """Anneau de progression de l'appui long."""
        painter.setPen(QPen(BAR_LOW, 3.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cadre = button.rect.adjusted(2.0, 2.0, -2.0, -2.0)
        painter.drawArc(cadre, 90 * 16, -int(360 * 16 * self._hold))

    def _paint_swatch(self, painter: QPainter, button: Button,
                      hover: bool) -> None:
        """Pastille de couleur, et la coche de celle qui est active.

        La coche est encrée en sombre ou en clair selon la luminance de la
        pastille : les palettes du génome vont du blanc cassé au magenta, et une
        coche d'une seule couleur disparaîtrait sur la moitié d'entre elles.
        """
        rouge, vert, bleu = hex_to_rgb(button.swatch)
        painter.setPen(QPen(SWATCH_EDGE, 2.0 if not hover else 3.0))
        painter.setBrush(QColor(int(rouge * 255), int(vert * 255),
                                int(bleu * 255)))
        painter.drawRoundedRect(button.rect, SWATCH_RADIUS, SWATCH_RADIUS)
        if button.selected:
            luminance = 0.299 * rouge + 0.587 * vert + 0.114 * bleu
            draw_icon(painter, "check", center_square(button.rect, 0.62),
                      INK if luminance > 0.55 else BG)

    def _paint_button(self, painter: QPainter, button: Button,
                      hover: bool) -> None:
        if button.swatch:
            self._paint_swatch(painter, button, hover)
            return
        if button.action.startswith("cos:"):
            self._paint_tile(painter, button, hover)
            return
        painter.setPen(Qt.PenStyle.NoPen)
        if not button.enabled:
            fond, encre = BUTTON_OFF, INK_OFF
        else:
            # Le survol se **mélange** au lieu de commuter : un aplat qui
            # change d'un coup sous le curseur est le seul mouvement de
            # l'interface qu'on remarque comme un défaut.
            fond = _melange(BUTTON_BG, BUTTON_HOVER,
                            self._survol.value(button.action))
            encre = INK
        painter.setBrush(fond)
        painter.drawRoundedRect(button.rect, RADIUS, RADIUS)
        draw_icon(painter, button.icon, center_square(button.rect), encre)

    # -- interaction -------------------------------------------------------

    def _at(self, pos) -> int:
        for index, button in enumerate(self._layout().buttons):
            if button.rect.contains(pos.x(), pos.y()):
                return index
        return -1

    def _tooltip(self, button: Button) -> str:
        """Texte d'infobulle d'un bouton. Vide si le bouton se suffit.

        Les pictogrammes obscurs se rattrapent ici : une grille de quatre carrés
        ne dit pas « interactions » tant qu'on ne l'a pas survolée une fois.
        Les choix d'apparence sont construits à la volée plutôt que tabulés —
        une entrée par couleur et par chapeau serait une table à tenir à jour à
        chaque ajout.
        """
        action = button.action
        if action.startswith("shop_"):
            emplacement = action[len("shop_"):]
            return TOOLTIP_CATEGORY % SLOT_LABELS.get(
                emplacement, emplacement).lower()
        if action.startswith("cos:"):
            cle = action.split(":", 2)[2]
            if not cle:
                return TOOLTIP_NO_HAT
            nom = ITEM_LABELS.get(cle, cle)
            if button.selected:
                return TOOLTIP_HAT_WORN % nom
            if button.price >= 0:
                return TOOLTIP_HAT_BUY % (nom, button.price)
            return TOOLTIP_HAT_WEAR % nom
        if "=" in action:
            return TOOLTIP_SWATCH % action.split("=", 1)[1].replace("-", " ")
        return TOOLTIPS.get(action, "")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        index = self._at(event.position())
        if index == self._hover:
            return
        self._hover = index
        boutons = self._layout().buttons
        self._sync_targets(boutons)
        self.update()

        if index < 0 or index >= len(boutons):
            QToolTip.hideText()
            return
        texte = self._tooltip(boutons[index])
        if not texte:
            QToolTip.hideText()
            return
        # Ancrée sous le bouton plutôt qu'au curseur : le panneau est petit, et
        # une bulle qui suit la souris masquerait le bouton d'à côté.
        rect = boutons[index].rect
        point = self.mapToGlobal(QPoint(int(rect.center().x()),
                                        int(rect.bottom()) + 4))
        QToolTip.showText(point, texte, self)

    def leaveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        QToolTip.hideText()
        if self._hover != -1:
            self._hover = -1
            # Le curseur peut sortir du panneau bouton enfoncé : relâcher la
            # cible d'appui ici évite un bouton resté écrasé pour toujours.
            self._appui_action = ""
            self._sync_targets(self._layout().buttons)
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        boutons = self._layout().buttons
        index = self._at(event.position())
        if index < 0:
            return
        button = boutons[index]
        if not button.enabled:
            # Un refus est un fait, au même titre qu'une acceptation : c'est
            # lui que le lot Sons voudra sonoriser d'un « non » sec.
            bus.emit("bouton_refuse", action=button.action)
            return
        self._appui_action = button.action
        self._sync_targets(boutons)
        self.update()
        if button.action in HOLD_ACTIONS:
            # Geste destructeur : il faut **maintenir**. L'interface n'ayant pas
            # de texte, aucune boîte de dialogue ne peut demander confirmation,
            # et la durée en tient lieu — on ne réinitialise pas son robot d'un
            # clic malheureux.
            self._hold_action = button.action
            self._hold = 0.0
            self._hold_timer.start()
            self.update()
            return
        self._activate(button.action)

    def _hold_tick(self) -> None:
        self._hold = min(1.0, self._hold + HOLD_TICK_MS / 1000.0 / HOLD_SECONDS)
        self.update()
        if self._hold >= 1.0:
            action, self._hold_action = self._hold_action, ""
            self._hold = 0.0
            self._hold_timer.stop()
            if action == "reset":
                self.reset_requested.emit()

    def _cancel_hold(self) -> None:
        if self._hold_action:
            self._hold_action = ""
            self._hold = 0.0
            self._hold_timer.stop()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self._cancel_hold()
        if self._appui_action:
            # Le relâchement rend la main au ressort, qui est sous-amorti :
            # le bouton repasse **au-dessus** de sa taille avant de se poser.
            # C'est là que se joue la sensation de rebond, pas à l'appui.
            self._appui_action = ""
            self._sync_targets(self._layout().buttons)
            self.update()

    def _activate(self, action: str) -> None:
        # Le fait brut, avant toute interprétation. Le panneau sait qu'un
        # bouton a été activé ; il ne sait pas encore si le soin sera accepté
        # ni si la bourse suffira — ces faits-là appartiennent à qui en décide.
        bus.emit("bouton_active", action=action)
        if action == "back":
            # Depuis une sous-page on remonte, depuis la racine on ferme : le
            # même geste veut dire « un cran en arrière » aux deux endroits.
            if self.page == "menu":
                self.close_panel()
            elif self.page in SHOP_PAGES:
                # D'un rayon on remonte aux catégories, pas au menu : sinon
                # essayer deux chapeaux demanderait de retraverser le panneau.
                self.open_page("shop")
            else:
                self.open_page("menu")
            return
        if action == "quit":
            self.quit_requested.emit()
            return
        if action in PAGES and action != "menu":
            self.open_page(action)
            return
        if "=" in action:
            param, valeur = action.split("=", 1)
            self.appearance_chosen.emit(param, valeur)
            bus.emit("apparence_changee", param=param, cle=valeur)
            self.update()
            return
        if action == "check":
            self._submit_name()
            return
        if action.startswith("cos:"):
            _, emplacement, cle = action.split(":", 2)
            self.item_chosen.emit(emplacement, cle)
            self.update()
            return
        if action == "autostart":
            self.autostart_toggled.emit()
            bus.emit("reglage_bascule", reglage="autostart")
            self.update()
            return
        if action in CARE_ACTIONS:
            self.care_requested.emit(action)
            self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()
            return
        super().keyPressEvent(event)
