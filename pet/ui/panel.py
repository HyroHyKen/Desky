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

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLineEdit, QToolTip, QWidget

from ..anim.easing import ease_in, ease_out_back
from ..brain.economy import DAILY_CAP
from ..brain.consumables import AISLES, by_need, get as consumable
from ..brain.needs import NEEDS
from ..feedback import bus
from ..geometry.cosmetics import NONE, SLOTS, by_slot, price as cosmetic_price
from ..genome.schema import ACCENT_COLORS, BODY_COLORS, hex_to_rgb
from .item import ITEM_KINDS
from .icons import MOOD_ICONS, center_square, draw_icon
from .motion import SpringBank, Stagger, Ticker, Tween

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

# Grande icône des pages vides. Elle occupe la place que le contenu aurait
# prise, et la mise en page lui réserve cette hauteur — sinon elle se superpose
# à ce qui l'entoure.
BIG_ICON = 62

# -- animation (lot L9) ------------------------------------------------------
#
# Durées dissymétriques, et c'est voulu : on regarde une interface s'ouvrir, on
# ne regarde pas une interface se fermer. Une sortie aussi longue que l'entrée
# donne l'impression que le logiciel traîne.
OPEN_SECONDS = 0.26
CLOSE_SECONDS = 0.15

# Échelle du panneau au tout début de son ouverture. Pas zéro : un panneau qui
# naît d'un point est un effet de diaporama. Il arrive nettement plus petit
# qu'il ne finira, et `ease_out_back` lui fait dépasser sa taille avant de se
# poser — c'est ce dépassement qui donne au panneau l'air d'avoir une masse.
OPEN_SCALE = 0.80

# **Pas de fondu.** L'opacité ne sert qu'à ne pas laisser un bord franc
# apparaître au premier pixel, et à escamoter le panneau à la fermeture : elle
# atteint 1 avant le tiers de l'ouverture, donc on ne la perçoit pas comme un
# fondu mais comme le début du bond. Une interface qui s'éclaircit n'a pas de
# matière ; c'est la taille et la cascade qui portent l'arrivée, pas l'alpha.
OPEN_ALPHA_RAMP = 0.45

# Cascade d'entrée des éléments. 35 ms de décalage : six boutons s'installent
# en 175 ms de plus que le premier, ce qui se perçoit comme une vague et non
# comme une attente. Au-delà de 60 ms, on attend le dernier bouton.
ENTER_DELAY = 0.035
ENTER_SECONDS = 0.30

# Plafond de la **durée totale** de la vague. Sans lui, la page de
# personnalisation et ses douze pastilles mettraient trois quarts de seconde à
# s'installer : à partir de là, on n'admire plus, on attend. Toutes les pages
# arrivent donc en un peu moins d'une demi-seconde, quelles qu'elles soient.
ENTER_SPREAD = 0.17

# Chaque élément arrive **d'en bas** et minuscule. L'échelle de départ est
# basse exprès : à 0,70 tous les éléments sont déjà lisibles à la première
# image et la cascade ne se lit plus comme une arrivée, seulement comme un
# agrandissement d'ensemble. À 0,25 chaque élément se pose vraiment à son tour.
ENTER_RISE = 13.0
ENTER_SCALE = 0.25

# Opacité propre à chaque élément, atteinte au premier tiers de son entrée —
# soit une centaine de millisecondes. Ce n'est pas un fondu : c'est ce qui
# évite qu'un bouton n'existe d'un coup à un quart de sa taille. Passé ce
# seuil, seule la taille travaille.
ENTER_ALPHA_RAMP = 0.32

# Réponse des boutons. L'appui **enfonce** — échelle inférieure à 1 — et le
# relâchement repasse par-dessus grâce au sous-amortissement du ressort. Le
# survol soulève à peine : il signale, il ne célèbre pas.
PRESS_SCALE = 0.88
HOVER_SCALE = 1.04
PRESS_SPRING = (34.0, 0.55)          # omega, zeta — vif, et il dépasse
HOVER_SPRING = (26.0, 0.85)          # plus calme, presque sans dépassement


def _icone_article(article) -> str:
    """Icône d'un consommable : celle du besoin qu'il sert.

    Pas d'icône par article, et c'est assumé : une gamelle et un en-cas servent
    la même chose, et deux pictogrammes proches à seize pixels se distinguent
    moins bien qu'un seul à deux tailles. La portion est dite par la **taille**
    du dessin (cf. `_echelle_article`), le prix et la quantité par les chiffres
    qui l'accompagnent.
    """
    return article.need


def _echelle_article(action: str) -> float:
    """Part du bouton qu'occupe l'icône : plus l'article rend, plus elle est
    grande. C'est ce qui sépare visuellement l'en-cas du repas."""
    cle = action.split(":", 1)[-1]
    article = consumable(cle)
    if article is None:
        return 0.56
    if article.instant:
        return 0.58
    # Autour du 0,56 de référence : le petit format en dessous, le grand
    # au-dessus, sans jamais s'en écarter assez pour dépareiller.
    return 0.44 + 0.20 * min(1.0, article.gain / 60.0)


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

# Le cyan du produit. Une seule définition : le filet sous les titres et le
# remplissage des jauges doivent être exactement la même couleur, faute de quoi
# l'interface a deux accents et n'en a donc aucun.
ACCENT = QColor(31, 168, 186)
BAR_FILL = ACCENT

BAR_LOW = QColor(196, 112, 58)
SWATCH_EDGE = QColor(24, 32, 40, 90)

# Sous ce niveau, une barre de besoin passe en ambre. Le même seuil que celui
# qui fait apparaître la bulle : il ne doit pas y avoir deux définitions de
# « ce besoin réclame de l'attention ».
BAR_LOW_LEVEL = 45.0

# Une page de rayon par emplacement, **dérivée** de la liste des emplacements :
# ajouter une famille d'articles ajoute sa page sans qu'on y touche.
# Rayons de la boutique : les cosmétiques par emplacement, puis les
# consommables par besoin. Dérivés des deux catalogues, donc ajouter un article
# le range sans qu'on touche à cette ligne.
SHOP_PAGES: tuple[str, ...] = (tuple("shop_" + s for s in SLOTS)
                               + tuple("shop_" + a for a in AISLES))

# `interactions` a disparu au lot L13 : des quatre soins il ne restait que la
# caresse, et une page pour un seul bouton est une page de trop — elle est
# remontée au menu racine.
PAGES = ("menu", "status", "games", "inventory", "custom", "shop") + SHOP_PAGES + (
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

# Rayons de consommables, par besoin servi.
AISLE_LABELS: dict[str, str] = {
    "hunger": "Nourriture",
    "hygiene": "Nettoyage",
    "energy": "Énergie",
}

PAGE_TITLES: dict[str, str] = {
    "games": "Jeux",
    "inventory": "Inventaire",
    "custom": "Apparence",
    "shop": "Boutique",
    "settings": "Réglages",
    "name": "Quel est mon nom ?",
}
PAGE_TITLES.update({"shop_" + s: SLOT_LABELS.get(s, s) for s in SLOTS})
PAGE_TITLES.update({"shop_" + a: AISLE_LABELS.get(a, a) for a in AISLES})

# Infobulle de chaque bouton. C'est ici que les pictogrammes obscurs se
# rattrapent : une grille de quatre carrés ne dit pas « interactions », et une
# étiquette de prix ne dit pas « boutique », tant qu'on ne les a pas survolés
# une première fois.
TOOLTIPS: dict[str, str] = {
    # Navigation
    "status": "Voir son état",
    "pet": "Le caresser",
    "inventory": "Inventaire",
    "custom": "Changer son apparence",
    "games": "Jouer avec lui",
    "shop": "Boutique",
    "settings": "Réglages",
    "quit": "Quitter",
    # Jeux
    "rally": "Ne pas laisser tomber le ballon",
    "cups": "Trouver sous quel gobelet il se cache",
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

# Consommables. Le libellé dit ce que c'est, l'infobulle ce que ça fait : à
# l'achat on veut comparer, à l'usage on veut se rappeler.
CONSUMABLE_LABELS: dict[str, str] = {
    "snack": "En-cas",
    "meal": "Repas",
    "kit": "Kit de bain",
    "battery": "Pile",
}
TOOLTIP_BUY = "%s — %d jetons"
TOOLTIP_USE = "%s — il en reste %d"

# Hauteur de la bande de titre, et sa police.
TITLE_H = 32
TITLE_SIZE = 18

# Taille de la référence d'usine, sous le nom (lot L18). Nettement plus petite
# que le nom : c'est une mention, pas un titre — le robot s'appelle Bip, il est
# de modèle C3-A7.
MODEL_SIZE = 11

# Filet d'accent sous le titre. Il fait deux choses qu'un titre seul ne fait
# pas : il ancre le texte à une largeur — donc la page a une tête, pas une
# ligne flottante — et il donne à la cascade quelque chose à **dessiner** en
# arrivant, puisqu'il se déploie depuis son centre.
TITLE_RULE_H = 3.0
TITLE_RULE_PAD = 12.0              # débord de chaque côté du texte
TITLE_RULE_GAP = 3.0               # entre la ligne de base et le filet

# Air entre le filet du titre et le premier élément de la page. Sans lui le
# titre est collé à ce qu'il annonce, et l'œil lit un bloc au lieu d'une
# en-tête suivie d'un contenu.
#
# Deux familles de pages s'en passent, et pour la même raison : elles ont déjà
# quelque chose entre le titre et les actions. La boutique et ses rayons
# portent la ligne du solde ; la page de statut n'a pas de titre du tout, son
# en-tête — pastille d'humeur et nom — en tient lieu et doit rester soudé aux
# jauges qu'il commente.
TITLE_LEAD = 15
TITLE_TIGHT_PAGES: frozenset[str] = frozenset({"status", "shop"}) | frozenset(SHOP_PAGES)

# Boutons du menu racine. La personnalisation se glisse **avant** la boutique :
# les deux touchent à l'apparence, et celle qui est gratuite doit se trouver la
# première.
# Sept entrées pour six colonnes depuis l'arrivée des jeux : le menu passe sur
# deux rangées. La largeur du panneau, elle, ne bouge pas — un panneau qui
# respire en changeant de page est fatigant, et c'est déjà pourquoi toutes les
# pages se conforment à six colonnes.
# `pet` — la caresse — est **dans le menu**, pas dans une sous-page : c'est le
# geste qu'on fait en passant, le seul qui ne coûte rien, et l'enterrer sous une
# navigation le rendrait plus cher que ce qu'il vaut.
MENU_ACTIONS = ("status", "pet", "games", "inventory", "custom", "shop",
                "settings", "quit")

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

# Jeux disponibles. Lancer une partie ferme le panneau, pour la même raison que
# poser un objet de soin : ce qui est intéressant n'est plus dans le menu, et le
# panneau bloque la locomotion dont le robot a besoin pour jouer.
GAME_ACTIONS = ("rally", "cups")


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
    # Référence d'usine, sous le nom. Vide partout ailleurs qu'au statut.
    model: str = ""
    big_icon: str = ""
    tokens: int = -1            # solde affiché, -1 pour ne rien montrer
    title: str = ""
    # Quantités à afficher en pastille sur un bouton, `action -> nombre`.
    # Utilisé par l'inventaire, où savoir **combien** il en reste est la seule
    # information qui compte.
    counts: dict = field(default_factory=dict)
    # Scores à afficher, `(jeu, record, dernier)`. `dernier` vaut -1 quand
    # aucune partie n'a été jouée dans cette session. Vide hors de la page des
    # jeux — c'est le seul endroit où un score a un sens.
    scores: list = field(default_factory=list)


class CarePanel(QWidget):
    """Panneau de soin. Sans état propre : il lit la session à chaque peinture."""

    care_requested = Signal(str)
    quit_requested = Signal()
    name_submitted = Signal(str)
    appearance_chosen = Signal(str, str)
    item_chosen = Signal(str, str)
    reset_requested = Signal()
    autostart_toggled = Signal()
    game_requested = Signal(str)
    purchase_requested = Signal(str)
    consumable_used = Signal(str)

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
        # Renseigné par la fenêtre, comme `item_pending` : le panneau ne connaît
        # ni l'énergie ni le coût d'une partie, il affiche ce qu'on lui dit.
        self.can_play = True
        # Score de la dernière partie, par jeu. Renseigné par la fenêtre à la
        # fin d'une partie, et affiché à côté du record — un score seul ne dit
        # pas si on a bien joué, un record seul ne dit pas ce qu'on vient de
        # faire.
        self.last_score: dict[str, int] = {}

        # -- animation (lot L9) ---------------------------------------------
        #
        # L'état d'animation vit **à côté** de la mise en page, jamais dedans :
        # `_layout()` reste une fonction pure de la session, recalculée à chaque
        # peinture, et c'est ce qui rend le panneau simple. Les ressorts sont
        # indexés par `Button.action`, l'identité que le test de clic utilise
        # déjà — un indice de rangée ne survivrait pas à un changement de page.
        self._ouverture = Tween(0.0)
        self._entree = Stagger(ENTER_DELAY, ENTER_SECONDS, ENTER_SPREAD)
        self._survol = SpringBank(*HOVER_SPRING)
        self._appui = SpringBank(*PRESS_SPRING)
        self._appui_action = ""
        self._fermeture = False
        self._opacite_fond = 1.0
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
        if not deja_visible:
            self._entree.start(self._entrance_keys(self._layout()))
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
            # La cascade aussi doit être soldée : laissée en vol, elle
            # rallumerait le tic d'un panneau déjà masqué.
            self._entree.finish()
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
        bouge = self._entree.step(dt) or bouge
        bouge = self._survol.step(dt) or bouge
        bouge = self._appui.step(dt) or bouge

        if self._fermeture and not self._ouverture.moving:
            self._fermeture = False
            self._entree.finish()
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

    def _entrance_keys(self, layout: Layout) -> list[str]:
        """Ordre de la cascade : de haut en bas, comme on lit la page.

        Les boutons viennent en dernier parce qu'ils sont ce vers quoi la main
        va : le regard descend le titre, l'état, puis trouve les actions déjà
        installées. L'ordre inverse ferait arriver les boutons sous un titre
        encore absent, et on ne saurait pas de quelle page ils dépendent.
        """
        cles: list[str] = []
        if layout.title:
            cles.append("titre")
        if layout.mood or layout.name:
            cles.append("entete")
        if layout.tokens >= 0:
            cles.append("bourse")
        cles += ["barre:%s" % nom for nom, _ in layout.bars]
        if layout.big_icon:
            cles.append("grande_icone")
        cles += ["bouton:%s" % b.action for b in layout.buttons]
        return cles

    def _entree_debut(self, painter: QPainter, cle: str, ancre) -> bool:
        """Ouvre la transformation d'entrée d'un élément.

        Rend `True` si un `restore()` est dû — le `_entree_fin` correspondant
        s'en charge. Deux appels appariés plutôt qu'un gestionnaire de
        contexte : le bouton en emboîte une seconde par-dessus, pour l'appui,
        et deux `with` imbriqués autour de six lignes coûtent plus à lire
        qu'ils ne rapportent.

        Le test porte sur `moving` et non sur la valeur : la courbe **dépasse**
        1 au milieu du mouvement, et comparer la valeur à 1 sauterait la
        transformation précisément pendant le dépassement. Une fois la cascade
        finie, toutes les valeurs valent exactement 1 et il n'y a plus rien à
        appliquer.
        """
        if not self._entree.moving:
            return False
        k = self._entree.value(cle)
        echelle = ENTER_SCALE + (1.0 - ENTER_SCALE) * k
        painter.save()
        # `setOpacity` **remplace** l'opacité courante au lieu de la
        # multiplier : celle du conteneur serait perdue si on se contentait de
        # poser la sienne. On compose donc les deux à la main.
        painter.setOpacity(self._opacite_fond
                           * max(0.0, min(1.0, k / ENTER_ALPHA_RAMP)))
        painter.translate(ancre.x(), ancre.y() + ENTER_RISE * (1.0 - k))
        painter.scale(echelle, echelle)
        painter.translate(-ancre.x(), -ancre.y())
        return True

    def _entree_fin(self, painter: QPainter, ouverte: bool) -> None:
        if ouverte:
            painter.restore()

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
        if change and self.isVisible():
            # Naviguer relance la cascade : la page suivante s'installe au
            # lieu de se substituer. C'est ce qui distingue une navigation
            # d'un simple changement de contenu — et c'est gratuit, la
            # mécanique d'entrée est déjà là.
            self._entree.start(self._entrance_keys(layout))
            self._ticker.wake()
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
        # Consommables d'abord : c'est ce qu'on vient chercher le plus souvent,
        # et un rayon de chapeaux placé devant la nourriture dirait mal ce que
        # la boutique sert désormais.
        rayons = tuple("shop_" + a for a in AISLES) + tuple("shop_" + s for s in SLOTS)
        layout.buttons = self._row(rayons[:MENU_COLUMNS], y)
        reste = rayons[MENU_COLUMNS:]
        if reste:
            layout.buttons += self._row(reste, y + BUTTON + GAP)
            y += BUTTON + GAP
        layout.buttons += self._row(("back",), y + BUTTON + GAP)
        layout.height = int(y + 2 * BUTTON + 2 * GAP + PAD)
        return layout

    def _shop_aisle_layout(self, need: str) -> Layout:
        """Un rayon de consommables : les articles, leur prix, ce qu'on en a.

        À la différence des cosmétiques, **on peut racheter** : un article déjà
        possédé n'est pas grisé, il affiche seulement combien on en a. C'est la
        distinction qui a justifié une seconde structure de stockage — posséder
        un chapeau est un état, posséder trois gamelles est une quantité.
        """
        solde = self.session.tokens
        articles = by_need(need)
        layout = Layout(height=0, tokens=solde,
                        title=PAGE_TITLES.get("shop_" + need, ""))

        y = self._top() + HEADER + BAR_GAP
        total = SHOP_COLUMNS * TILE + (SHOP_COLUMNS - 1) * TILE_GAP
        for index, article in enumerate(articles):
            colonne = index % SHOP_COLUMNS
            rangee = index // SHOP_COLUMNS
            x = (WIDTH - total) / 2.0 + colonne * (TILE + TILE_GAP)
            layout.buttons.append(Button(
                QRectF(x, y + rangee * (TILE + TILE_LABEL + TILE_GAP),
                       TILE, TILE),
                _icone_article(article), "buy:" + article.key,
                enabled=solde >= article.price,
                price=article.price,
            ))
            possede = self.session.count(article.key)
            if possede:
                layout.counts["buy:" + article.key] = possede

        lignes = (len(articles) + SHOP_COLUMNS - 1) // SHOP_COLUMNS
        bas = y + lignes * (TILE + TILE_LABEL + TILE_GAP)
        layout.buttons += self._row(("back",), bas)
        layout.height = int(bas + BUTTON + PAD)
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

        Le menu racine est le cas particulier qui justifie de ne pas se
        contenter de `PAGE_TITLES` : son titre est le **nom du robot**, qui n'y
        figure évidemment pas. Il calculait donc sa hauteur à part, et toute
        retouche de la bande de titre devait être faite à deux endroits — ce
        que cette méthode existe précisément pour éviter.
        """
        titre = PAGE_TITLES.get(self.page) or (
            self.session.name if self.page == "menu" else "")
        if not titre:
            return PAD
        return PAD + TITLE_H + (0 if self.page in TITLE_TIGHT_PAGES
                                else TITLE_LEAD)

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
            # Deux rangées depuis l'arrivée des jeux : sept entrées ne tiennent
            # pas sur six colonnes, et élargir le panneau le ferait changer de
            # taille d'une page à l'autre.
            premiere = MENU_ACTIONS[:MENU_COLUMNS]
            seconde = MENU_ACTIONS[MENU_COLUMNS:]
            hauteur = haut + BUTTON + PAD
            if seconde:
                hauteur += BUTTON + GAP
            # La caresse est au menu depuis le lot L13, et elle garde son
            # délai : il faut donc que le menu sache la griser. C'est le seul
            # bouton de navigation qui puisse être indisponible.
            def offert(action: str) -> bool:
                return action != "pet" or brain.can_care("pet")

            layout = Layout(height=hauteur, title=nom)
            layout.buttons = self._row(premiere, haut, enabled=offert)
            if seconde:
                layout.buttons += self._row(seconde, haut + BUTTON + GAP,
                                            enabled=offert)
            return layout

        if self.page == "status":
            hauteur = (PAD + HEADER + BAR_GAP
                       + len(NEEDS) * (BAR_HEIGHT + BAR_GAP)
                       + BUTTON + PAD)
            from ..genome.model import libelle_famille, model_name
            layout = Layout(height=hauteur, mood=brain.expression, name=nom,
                            model="%s · %s" % (libelle_famille(self.genome),
                                               model_name(self.genome)))
            layout.bars = [(n, getattr(brain.needs, n)) for n in NEEDS]
            layout.buttons = self._row(("back",),
                                       hauteur - PAD - BUTTON)
            return layout

        if self.page == "inventory":
            # Ce qu'on possède, et rien d'autre : un inventaire qui montrerait
            # aussi ce qu'on n'a pas serait une seconde boutique, et la boutique
            # existe déjà. Vide, la page le dit par une grande icône pâle plutôt
            # que par une rangée de cases grises.
            stock = sorted(self.session.consumables.items())

            if not stock:
                # Vide, la page le dit par une grande icône pâle plutôt que par
                # une rangée de cases grises — et le retour se place **sous**
                # elle, pas dessus.
                y = haut + BIG_ICON + GAP
                layout = Layout(height=int(y + BUTTON + PAD), title=titre)
                layout.big_icon = "inventory"
                layout.buttons = self._row(("back",), y)
                return layout

            layout = Layout(height=haut + 2 * BUTTON + GAP + PAD, title=titre)

            def dispo(action: str) -> bool:
                # Un objet est déjà posé sur le bureau : tout ce qui s'y pose
                # est indisponible, la pile reste utilisable.
                cle = action[len("use:"):]
                article = consumable(cle)
                return bool(article and (article.instant or not self.item_pending))

            actions = tuple("use:" + cle for cle, _ in stock)
            layout.buttons = self._row(actions, haut, enabled=dispo)
            for bouton in layout.buttons:
                article = consumable(bouton.action[len("use:"):])
                if article is not None:
                    bouton.icon = _icone_article(article)
            layout.counts = {"use:" + cle: n for cle, n in stock}
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
            rayon = self.page[len("shop_"):]
            if rayon in AISLES:
                return self._shop_aisle_layout(rayon)
            return self._shop_slot_layout(rayon)

        if self.page == "games":
            jouable = self.can_play
            # Une **ligne par jeu** : son bouton à gauche, ses scores à droite.
            # La page est construite pour que le troisième jeu n'oblige à rien
            # réécrire — seule `GAME_ACTIONS` le sait.
            hauteur = haut + len(GAME_ACTIONS) * (BUTTON + GAP) + BUTTON + PAD
            layout = Layout(height=hauteur, title=titre)
            for index, jeu in enumerate(GAME_ACTIONS):
                y = haut + index * (BUTTON + GAP)
                layout.buttons += self._row((jeu,), y,
                                            enabled=lambda a: jouable)
                layout.scores.append((jeu, self.session.best_score(jeu),
                                      self.last_score.get(jeu, -1)))
            layout.buttons += self._row(
                ("back",), haut + len(GAME_ACTIONS) * (BUTTON + GAP))
            return layout

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

        # Arrivée du panneau. L'échelle est **peinte**, la géométrie du widget
        # ne bouge pas : animer `setGeometry` ferait travailler le gestionnaire
        # de fenêtres trente fois par seconde pour un widget translucide
        # toujours au-dessus, et le résultat saccade.
        #
        # L'ancrage est le bas-centre : le panneau se pose au-dessus de la tête
        # du pet, et grandir depuis ce point-là donne l'impression qu'il en
        # sort. Grandir depuis le centre le ferait apparaître de nulle part.
        ouverture = self._ouverture.value
        self._opacite_fond = 1.0
        # `abs(... - 1)` et non `< 1` : `ease_out_back` **dépasse** 1 avant de
        # revenir, et c'est ce dépassement que le §10 réclame. Un test qui ne
        # regarderait que « pas encore ouvert » le supprimerait sans bruit.
        if abs(ouverture - 1.0) > 1e-3:
            # L'opacité n'est pas un fondu : elle atteint 1 avant le tiers de
            # l'ouverture. Elle ne sert qu'à éviter un bord franc au premier
            # pixel, et à escamoter le panneau quand il part.
            self._opacite_fond = max(0.0, min(1.0, ouverture / OPEN_ALPHA_RAMP))
            painter.setOpacity(self._opacite_fond)
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

        # Le contenu entre en cascade, de haut en bas. Chaque élément est peint
        # à travers sa propre transformation d'entrée : c'est ce qui remplace
        # le fondu, et c'est ce qui donne au panneau l'air d'être fait de
        # pièces plutôt que d'être une image qui s'éclaircit.
        if layout.title:
            fini = self._entree_debut(painter, "titre",
                                      QPointF(WIDTH / 2.0, PAD - 2 + TITLE_H / 2.0))
            self._paint_title(painter, layout.title,
                              self._entree.value("titre"))
            self._entree_fin(painter, fini)

        if layout.tokens >= 0:
            fini = self._entree_debut(painter, "bourse",
                                      QPointF(PAD, self._top() + HEADER / 2.0))
            self._paint_purse(painter, layout.tokens)
            self._entree_fin(painter, fini)

        if layout.mood or layout.name:
            fini = self._entree_debut(painter, "entete",
                                      QPointF(PAD, PAD + HEADER / 2.0))
            self._paint_header(painter, layout)
            self._entree_fin(painter, fini)

        for index, (need, value) in enumerate(layout.bars):
            y = PAD + HEADER + BAR_GAP + index * (BAR_HEIGHT + BAR_GAP)
            cle = "barre:%s" % need
            fini = self._entree_debut(painter, cle,
                                      QPointF(PAD, y + BAR_HEIGHT / 2.0))
            self._paint_bar(painter, need, value, y, self._entree.value(cle))
            self._entree_fin(painter, fini)

        if layout.big_icon:
            # Page vide : l'icône en gris pâle dit « il n'y a rien ici ».
            #
            # Posée sous le titre et non à une ordonnée fixe. Elle était calée
            # sur `PAD + 7`, ce qui datait d'une page **sans** titre : depuis
            # que l'inventaire en a un, elle lui passait au travers et le
            # bouton de retour lui passait au travers à son tour.
            boite = QRectF((WIDTH - BIG_ICON) / 2.0, self._top(),
                           BIG_ICON, BIG_ICON)
            fini = self._entree_debut(painter, "grande_icone", boite.center())
            draw_icon(painter, layout.big_icon, boite, INK_OFF)
            self._entree_fin(painter, fini)

        for jeu, record, dernier in layout.scores:
            self._paint_score(painter, layout, jeu, record, dernier)

        for index, button in enumerate(layout.buttons):
            centre = button.rect.center()
            entree = self._entree_debut(painter, "bouton:%s" % button.action,
                                        centre)
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
                painter.save()
                painter.translate(centre)
                painter.scale(echelle, echelle)
                painter.translate(-centre)
            self._paint_button(painter, button, index == self._hover)
            if button.action == self._hold_action and self._hold > 0.0:
                self._paint_hold(painter, button)
            if transforme:
                painter.restore()
            self._entree_fin(painter, entree)

        # Les pastilles de quantité **après** les boutons : peintes avant, les
        # boutons les recouvraient purement et simplement. Elles débordent du
        # coin, ce qui est précisément ce qu'on veut — une pastille contenue
        # dans le bouton se lit comme une partie du pictogramme.
        for action, nombre in layout.counts.items():
            self._paint_count(painter, layout, action, nombre)
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
            #
            # Même traitement que les titres de page : le nom du robot **est**
            # le titre de la page de statut, et le voir en demi-gras plus petit
            # à côté de « Interactions » en gras donnait à cette page l'air
            # d'appartenir à une autre application.
            font = QFont()
            font.setPixelSize(TITLE_SIZE)
            font.setWeight(QFont.Weight.Bold)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
            painter.setFont(font)
            painter.setPen(INK)

            gauche = PAD + HEADER + GAP
            largeur = WIDTH - 2 * PAD - HEADER - GAP
            if layout.model:
                # Deux lignes dans la même bande : le nom se cale en haut, la
                # référence dessous. Centrer le nom alors qu'une seconde ligne
                # le suit le ferait flotter au-dessus d'elle.
                painter.drawText(
                    QRectF(gauche, PAD, largeur, HEADER * 0.58),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                    layout.name)
                reference = QFont()
                reference.setPixelSize(MODEL_SIZE)
                reference.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
                painter.setFont(reference)
                painter.setPen(INK_SOFT)
                painter.drawText(
                    QRectF(gauche, PAD + HEADER * 0.56, largeur, HEADER * 0.44),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                    layout.model)
            else:
                painter.drawText(
                    QRectF(gauche, PAD, largeur, HEADER),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    layout.name)

    def _paint_bar(self, painter: QPainter, need: str, value: float,
                   y: int, entree: float = 1.0) -> None:
        icone = QRectF(PAD, y - 2, BAR_HEIGHT + 4, BAR_HEIGHT + 4)
        draw_icon(painter, need, icone, INK_SOFT)

        x = PAD + BAR_HEIGHT + 4 + GAP
        largeur = WIDTH - PAD - x
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BAR_BG)
        painter.drawRoundedRect(QRectF(x, y, largeur, BAR_HEIGHT),
                                BAR_HEIGHT / 2.0, BAR_HEIGHT / 2.0)

        # Le remplissage se déploie avec l'entrée de la barre, jamais avec un
        # changement de valeur : une jauge qui s'anime pendant qu'on la lit
        # réclame l'attention au lieu de l'informer. L'entrée est bornée à 1
        # ici — le dépassement de la courbe ferait déborder la jauge.
        part = max(0.0, min(1.0, value / 100.0)) * max(0.0, min(1.0, entree))
        if part > 0.001:
            # Plancher de largeur : une barre à 2 % doit rester visible comme
            # une barre, sinon elle se confond avec une barre vide.
            remplie = max(BAR_HEIGHT, largeur * part)
            painter.setBrush(BAR_LOW if value < BAR_LOW_LEVEL else BAR_FILL)
            painter.drawRoundedRect(QRectF(x, y, remplie, BAR_HEIGHT),
                                    BAR_HEIGHT / 2.0, BAR_HEIGHT / 2.0)

    def _paint_count(self, painter: QPainter, layout: Layout,
                     action: str, nombre: int) -> None:
        """Quantité possédée, en pastille sur le coin du bouton.

        En chiffres, comme le solde et les scores : « il t'en reste trois » ne
        se dit pas en pictogrammes, et trois petits points deviendraient
        illisibles à cinq. C'est la troisième et dernière entorse assumée à la
        règle du sans-texte.
        """
        bouton = next((b for b in layout.buttons if b.action == action), None)
        if bouton is None or nombre <= 0:
            return
        cote = 19.0
        pastille = QRectF(bouton.rect.right() - cote * 0.70,
                          bouton.rect.top() - cote * 0.26, cote, cote)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT if bouton.enabled else INK_OFF)
        painter.drawEllipse(pastille)

        font = QFont()
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(pastille, int(Qt.AlignmentFlag.AlignCenter), str(nombre))

    def _paint_score(self, painter: QPainter, layout: Layout, jeu: str,
                     record: int, dernier: int = -1) -> None:
        """Scores d'un jeu, à droite de son bouton.

        Le dernier en grand, le record en petit dessous. Ce sont les seuls
        chiffres de l'application avec le solde, et la même entorse assumée à
        la règle du sans-texte : un score se dit en chiffres, et le rendre en
        pastilles serait illisible dès dix échanges.

        Le dernier score passe à l'accent quand il **est** le record : c'est la
        seule façon, sans texte, de dire « vous venez de battre le vôtre ».
        """
        bouton = next((b for b in layout.buttons if b.action == jeu), None)
        if bouton is None:
            return
        gauche = bouton.rect.right() + GAP
        largeur = WIDTH - PAD - gauche
        aligne = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if dernier >= 0:
            font = QFont()
            font.setPixelSize(21)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(ACCENT if dernier >= record and record else INK)
            painter.drawText(
                QRectF(gauche, bouton.rect.top() - 2,
                       largeur, bouton.rect.height() * 0.58),
                aligne, str(dernier))

        # Le record est précédé d'une **étoile dessinée**, pas d'un caractère.
        # C'est la règle du §13 — l'interface est en pictogrammes — et c'est
        # aussi ce que vérifie `test_tout_le_texte_affiche_vient_de_la_table`,
        # qui a attrapé la première version de cette ligne.
        taille = 13 if dernier >= 0 else 16
        hauteur = bouton.rect.height() * (0.50 if dernier >= 0 else 1.0)
        haut = (bouton.rect.top() + bouton.rect.height() * 0.50 if dernier >= 0
                else bouton.rect.top())
        encre = INK_SOFT if dernier >= 0 else (INK if record else INK_OFF)

        etoile = QRectF(gauche, haut + (hauteur - taille) / 2.0, taille, taille)
        draw_icon(painter, "fun", etoile, encre)

        font = QFont()
        font.setPixelSize(taille)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(encre)
        painter.drawText(
            QRectF(gauche + taille + 4.0, haut,
                   largeur - taille - 4.0, hauteur),
            aligne, str(record))

    def _paint_title(self, painter: QPainter, titre: str,
                     entree: float = 1.0) -> None:
        """Titre de page, centré, souligné d'un filet d'accent.

        Le texte vient toujours de `PAGE_TITLES` ou du nom du robot, jamais
        d'une chaîne écrite ici : c'est ce qui garde l'interface traduisible.

        Le filet se déploie **depuis son centre** avec l'entrée du titre. Il
        n'est pas décoratif : sans lui le titre est une ligne de texte posée en
        haut d'une boîte, et rien ne dit que la page lui appartient. Sa largeur
        suit celle du texte, donc un titre court ne traîne pas une barre qui le
        dépasse — et une traduction plus longue reste couverte.
        """
        font = QFont()
        font.setPixelSize(TITLE_SIZE)
        font.setWeight(QFont.Weight.Bold)
        # L'interlettrage tient le titre à distance de son propre gras : sans
        # lui, un mot court en Bold à 18 px fait bloc.
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        painter.setFont(font)

        bande = QRectF(PAD, PAD - 2, WIDTH - 2 * PAD, TITLE_H - TITLE_RULE_H)
        painter.setPen(INK)
        painter.drawText(
            bande,
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            titre)

        largeur = painter.fontMetrics().horizontalAdvance(titre)
        plein = min(float(WIDTH - 2 * PAD), largeur + 2 * TITLE_RULE_PAD)
        courant = plein * max(0.0, min(1.0, entree))
        if courant < 1.0:
            return
        y = bande.bottom() + TITLE_RULE_GAP
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT)
        painter.drawRoundedRect(
            QRectF(WIDTH / 2.0 - courant / 2.0, y, courant, TITLE_RULE_H),
            TITLE_RULE_H / 2.0, TITLE_RULE_H / 2.0)

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

        if button.action.startswith("buy:"):
            draw_icon(painter, button.icon,
                      center_square(button.rect, _echelle_article(button.action)),
                      INK if button.enabled else INK_OFF)

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
        if button.action.startswith(("cos:", "buy:")):
            # Les deux sont des **vignettes de rayon** : un dessin, un prix
            # dessous. Le prix est la moitié de l'information d'une boutique, et
            # le reléguer à l'infobulle obligerait à survoler chaque article
            # pour comparer deux gamelles.
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
        # `center_square` a sa propre valeur par défaut, et c'est elle qui donne
        # à tous les boutons le même air. Lui passer 1.0 — ce que faisait la
        # première version de l'échelle des articles — remplit le bouton d'un
        # bord à l'autre : l'icône ne se lit plus comme un pictogramme posé dans
        # un carré, mais comme un aplat.
        if button.action.startswith(("use:", "buy:")):
            boite = center_square(button.rect, _echelle_article(button.action))
        else:
            boite = center_square(button.rect)
        draw_icon(painter, button.icon, boite, encre)

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
            nom = SLOT_LABELS.get(emplacement) or AISLE_LABELS.get(
                emplacement, emplacement)
            return TOOLTIP_CATEGORY % nom.lower()
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
        if action.startswith("buy:"):
            cle = action[len("buy:"):]
            return TOOLTIP_BUY % (CONSUMABLE_LABELS.get(cle, cle), button.price)
        if action.startswith("use:"):
            cle = action[len("use:"):]
            return TOOLTIP_USE % (CONSUMABLE_LABELS.get(cle, cle),
                                  self.session.count(cle))
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
        if action.startswith("buy:"):
            self.purchase_requested.emit(action[len("buy:"):])
            self.update()
            return
        if action.startswith("use:"):
            self.consumable_used.emit(action[len("use:"):])
            return
        if action in CARE_ACTIONS:
            self.care_requested.emit(action)
            self.update()
            return
        if action in GAME_ACTIONS:
            self.game_requested.emit(action)
            self.close_panel()
            return
        if action == "autostart":
            self.autostart_toggled.emit()
            bus.emit("reglage_bascule", reglage="autostart")
            self.update()
            return

    def keyPressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()
            return
        super().keyPressEvent(event)
