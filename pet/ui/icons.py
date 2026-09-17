"""Icônes du panneau, en chemins vectoriels.

Deuxième moitié du vocabulaire visuel du lot L6. Les sigles de la bulle et des
yeux sont des SDF dans un shader (`render/glyphs.glsl`) ; ceux-ci sont des
`QPainterPath` tracés par Qt. Deux techniques pour un même langage, et il faut
les garder cohérents **à la main** : les quatre icônes de besoin reprennent
délibérément les formes du shader — gamelle, étoile, pile, goutte — pour qu'une
bulle et une barre de besoin parlent de la même chose.

Chaque icône est dessinée dans un carré de 100 unités, coin haut-gauche à
l'origine, et `draw_icon` la met à l'échelle du rectangle demandé. Travailler
dans un carré fixe évite d'avoir à réfléchir aux proportions à chaque appel, et
garantit que toutes les icônes ont le même poids optique.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPainterPathStroker, QPen

# Repère de tracé. Toutes les coordonnées ci-dessous y sont exprimées.
BOX = 100.0

# Épaisseur des traits, dans le même repère. Les icônes mélangent volontairement
# aplats et traits : un pictogramme tout en aplat devient une tache aux petites
# tailles, un pictogramme tout en trait devient un gribouillis.
STROKE = 9.0


def _rounded(path: QPainterPath, x: float, y: float, w: float, h: float,
             r: float) -> None:
    path.addRoundedRect(QRectF(x, y, w, h), r, r)


def _stroked_arc(rect: QRectF, start: float, sweep: float,
                 width: float) -> QPainterPath:
    """Arc **épaissi en surface**, et non un arc à remplir.

    Un `arcTo` ajouté à un chemin rempli donne un camembert, pas un anneau : le
    bouton d'arrêt ressemblait à un cadenas et l'anse du sac à un couvercle.
    `QPainterPathStroker` convertit le trait en contour fermé, ce qui redonne un
    vrai anneau tout en gardant un tracé rempli d'un seul tenant.
    """
    arc = QPainterPath()
    arc.arcMoveTo(rect, start)
    arc.arcTo(rect, start, sweep)
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    return stroker.createStroke(arc)


def _bowl(path: QPainterPath) -> None:
    """Gamelle pleine — la faim. Même construction que `gHunger` du shader.

    Un récipient vide n'a pas de silhouette propre : la première version, un
    demi-disque sous une barre, se lisait comme une colline. Le tas qui dépasse
    dit « de la nourriture », et la cuve plus étroite que le bord dit
    « un récipient ».
    """
    # Tas, d'abord : il passe derrière le bord.
    tas = QPainterPath()
    tas.moveTo(24.0, 44.0)
    tas.arcTo(QRectF(24.0, 22.0, 52.0, 44.0), 180.0, -180.0)
    tas.closeSubpath()
    path.addPath(tas)

    # Cuve, resserrée vers le fond.
    cuve = QPainterPath()
    cuve.moveTo(13.0, 50.0)
    cuve.lineTo(87.0, 50.0)
    cuve.lineTo(74.0, 82.0)
    cuve.quadTo(50.0, 90.0, 26.0, 82.0)
    cuve.closeSubpath()
    path.addPath(cuve)

    # Bord, par-dessus les deux.
    _rounded(path, 8.0, 41.0, 84.0, 13.0, 6.5)


def _star(path: QPainterPath) -> None:
    """Étoile à quatre branches — l'amusement.

    Deux losanges croisés, comme `gFun`. Une balle avait été essayée d'abord :
    elle se lisait comme un panneau d'interdiction.
    """
    for a, b in ((14.0, 46.0), (46.0, 14.0)):
        losange = QPainterPath()
        losange.moveTo(50.0, 50.0 - b)
        losange.lineTo(50.0 + a, 50.0)
        losange.lineTo(50.0, 50.0 + b)
        losange.lineTo(50.0 - a, 50.0)
        losange.closeSubpath()
        path.addPath(losange)


def _battery(path: QPainterPath) -> None:
    """Pile — l'énergie."""
    _rounded(path, 30.0, 20.0, 40.0, 68.0, 9.0)
    _rounded(path, 42.0, 11.0, 16.0, 10.0, 4.0)
    trou = QPainterPath()
    _rounded(trou, 40.0, 58.0, 20.0, 18.0, 5.0)
    path.addPath(trou.toReversed())


def _drop(path: QPainterPath) -> None:
    """Goutte — l'hygiène. Disque et triangle soudés, comme `gHygiene`.

    Reconstruite depuis deux primitives au lieu d'un mélange de `cubicTo` et
    d'`arcTo` : la version précédente enchaînait une courbe et un arc dont les
    tangentes ne se raccordaient pas, ce qui laissait un pli sur le flanc.
    """
    bas = QPainterPath()
    bas.addEllipse(QRectF(20.0, 40.0, 60.0, 54.0))
    path.addPath(bas)

    pointe = QPainterPath()
    pointe.moveTo(50.0, 6.0)
    pointe.quadTo(78.0, 44.0, 78.0, 62.0)
    pointe.lineTo(22.0, 62.0)
    pointe.quadTo(22.0, 44.0, 50.0, 6.0)
    pointe.closeSubpath()
    path.addPath(pointe)


def _gauge(path: QPainterPath) -> None:
    """Jauge — la page de statut. Trois barres de longueurs différentes."""
    for index, longueur in enumerate((64.0, 44.0, 76.0)):
        _rounded(path, 14.0, 24.0 + index * 24.0, longueur, 13.0, 6.5)


def _grid(path: QPainterPath) -> None:
    """Grille de quatre — le menu d'interactions.

    Une main avait été essayée d'abord : à vingt pixels elle se lisait comme un
    bouchon, et surtout elle servait **aussi** de bouton « caresser », donc deux
    boutons du même parcours portaient le même dessin. Une grille dit « plusieurs
    choses à choisir » sans ambiguïté possible.
    """
    for cx in (26.0, 58.0):
        for cy in (26.0, 58.0):
            _rounded(path, cx - 10.0, cy - 10.0, 20.0, 20.0, 6.0)


def _heart(path: QPainterPath) -> None:
    """Coeur — caresser.

    Une caresse n'a pas de pictogramme littéral qui tienne à cette taille ; le
    coeur dit l'intention, ce qui est ce qu'un bouton doit dire.
    """
    path.moveTo(50.0, 84.0)
    path.cubicTo(14.0, 58.0, 12.0, 38.0, 26.0, 26.0)
    path.cubicTo(38.0, 16.0, 48.0, 24.0, 50.0, 34.0)
    path.cubicTo(52.0, 24.0, 62.0, 16.0, 74.0, 26.0)
    path.cubicTo(88.0, 38.0, 86.0, 58.0, 50.0, 84.0)
    path.closeSubpath()


def _tag(path: QPainterPath) -> None:
    """Étiquette de prix — la boutique.

    Un sac à provisions avait été essayé : corps arrondi et anse en arc, il se
    lisait comme un **cadenas**. L'étiquette n'a pas de sosie dans ce jeu
    d'icônes, et son oeillet la rend identifiable même à vingt pixels.
    """
    corps = QPainterPath()
    corps.moveTo(52.0, 10.0)
    corps.lineTo(90.0, 48.0)
    corps.lineTo(48.0, 90.0)
    corps.lineTo(10.0, 52.0)
    corps.lineTo(10.0, 18.0)
    corps.quadTo(10.0, 10.0, 18.0, 10.0)
    corps.closeSubpath()
    oeillet = QPainterPath()
    oeillet.addEllipse(QRectF(22.0, 22.0, 20.0, 20.0))
    corps.addPath(oeillet.toReversed())
    path.addPath(corps)


def _power(path: QPainterPath) -> None:
    """Bouton d'arrêt — quitter.

    L'ouverture de l'anneau est **étroite**, et c'est ce qui distingue ce
    pictogramme d'une flèche de rechargement : la première version laissait
    soixante-quatre degrés de jour et se lisait « recharger », ce qui, pour un
    bouton qui ferme l'application, est le pire des contresens.
    """
    path.addPath(_stroked_arc(QRectF(21.0, 28.0, 58.0, 58.0), 107.0, -334.0,
                              12.0))
    _rounded(path, 44.0, 12.0, 12.0, 36.0, 6.0)


def _back(path: QPainterPath) -> None:
    """Flèche de retour."""
    path.moveTo(58.0, 20.0)
    path.lineTo(28.0, 50.0)
    path.lineTo(58.0, 80.0)
    path.lineTo(58.0, 62.0)
    path.lineTo(44.0, 50.0)
    path.lineTo(58.0, 38.0)
    path.closeSubpath()
    _rounded(path, 52.0, 41.0, 28.0, 18.0, 8.0)


def _palette(path: QPainterPath) -> None:
    """Trois godets de couleur — la personnalisation.

    Trois disques en triangle plutôt qu'une palette de peintre : à vingt pixels,
    la forme en haricot avec son trou de pouce devient une tache, alors que trois
    ronds de tailles différentes se lisent immédiatement comme « des couleurs ».
    Aucune autre icône du jeu n'est faite de disques, donc pas de confusion.
    """
    path.addEllipse(QRectF(12.0, 44.0, 34.0, 34.0))
    path.addEllipse(QRectF(52.0, 50.0, 28.0, 28.0))
    path.addEllipse(QRectF(32.0, 14.0, 30.0, 30.0))


def _balloon(path: QPainterPath) -> None:
    """Ballon de baudruche — les jeux.

    Un ovale, un nœud, une ficelle. Le nœud est ce qui le distingue d'un
    disque : sans lui, à seize pixels, l'icône des jeux serait celle du jeton.
    """
    path.addEllipse(QRectF(24.0, 10.0, 52.0, 62.0))
    noeud = QPainterPath()
    noeud.moveTo(44.0, 70.0)
    noeud.lineTo(56.0, 70.0)
    noeud.lineTo(50.0, 80.0)
    noeud.closeSubpath()
    path.addPath(noeud)
    ficelle = QPainterPath()
    ficelle.moveTo(50.0, 79.0)
    ficelle.cubicTo(58.0, 84.0, 42.0, 88.0, 50.0, 94.0)
    stroker = QPainterPathStroker()
    stroker.setWidth(STROKE * 0.62)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    path.addPath(stroker.createStroke(ficelle))


def _crate(path: QPainterPath) -> None:
    """Caisse — l'inventaire.

    Un coffre vu de face, avec sa sangle. Distinct du sac de la boutique : l'un
    est ce qu'on possède, l'autre ce qu'on peut acheter, et les confondre à
    seize pixels rendrait la navigation illisible.
    """
    _rounded(path, 14.0, 30.0, 72.0, 52.0, 8.0)
    creux = QPainterPath()
    _rounded(creux, 22.0, 38.0, 56.0, 36.0, 5.0)
    path.addPath(creux)
    sangle = QPainterPath()
    _rounded(sangle, 42.0, 22.0, 16.0, 40.0, 4.0)
    path.addPath(sangle)


def _cup(path: QPainterPath) -> None:
    """Gobelet renversé — le jeu des trois gobelets.

    Un trapèze et sa lèvre. La lèvre est ce qui le distingue d'un seau ou d'un
    abat-jour : sans elle, à seize pixels, on ne voit pas qu'il est creux.
    """
    corps = QPainterPath()
    corps.moveTo(34.0, 18.0)
    corps.lineTo(66.0, 18.0)
    corps.lineTo(78.0, 76.0)
    corps.lineTo(22.0, 76.0)
    corps.closeSubpath()
    path.addPath(corps)
    path.addEllipse(QRectF(20.0, 68.0, 60.0, 18.0))
    creux = QPainterPath()
    creux.addEllipse(QRectF(30.0, 72.0, 40.0, 10.0))
    path.addPath(creux)


def _token(path: QPainterPath) -> None:
    """Jeton — la monnaie. Un disque et son anneau intérieur."""
    piece = QPainterPath()
    piece.addEllipse(QRectF(10.0, 10.0, 80.0, 80.0))
    creux = QPainterPath()
    creux.addEllipse(QRectF(30.0, 30.0, 40.0, 40.0))
    piece.addPath(creux.toReversed())
    path.addPath(piece)
    path.addEllipse(QRectF(42.0, 42.0, 16.0, 16.0))


def _autostart(path: QPainterPath) -> None:
    """Lancement au démarrage : une fenêtre, et une flèche qui y entre."""
    cadre = QPainterPath()
    cadre.addRoundedRect(QRectF(30.0, 16.0, 58.0, 68.0), 10.0, 10.0)
    creux = QPainterPath()
    creux.addRoundedRect(QRectF(42.0, 28.0, 34.0, 44.0), 5.0, 5.0)
    cadre.addPath(creux.toReversed())
    path.addPath(cadre)
    fleche = QPainterPath()
    fleche.moveTo(8.0, 42.0)
    fleche.lineTo(40.0, 42.0)
    fleche.lineTo(40.0, 30.0)
    fleche.lineTo(62.0, 50.0)
    fleche.lineTo(40.0, 70.0)
    fleche.lineTo(40.0, 58.0)
    fleche.lineTo(8.0, 58.0)
    fleche.closeSubpath()
    path.addPath(fleche)


def _gear(path: QPainterPath) -> None:
    """Engrenage — la page de réglages.

    Distinct du pignon de la nourriture : huit dents fines et un moyeu large,
    là où `food_gear` est trapu. La confusion serait fâcheuse, mais les deux ne
    se croisent jamais — l'un est un sprite au sol, l'autre un bouton.
    """
    import math

    for i in range(8):
        a = math.radians(22.5 + 45.0 * i)
        cx = 50.0 + 36.0 * math.cos(a)
        cy = 50.0 + 36.0 * math.sin(a)
        _rounded(path, cx - 9.0, cy - 9.0, 18.0, 18.0, 4.0)
    couronne = QPainterPath()
    couronne.addEllipse(QRectF(16.0, 16.0, 68.0, 68.0))
    creux = QPainterPath()
    creux.addEllipse(QRectF(38.0, 38.0, 24.0, 24.0))
    couronne.addPath(creux.toReversed())
    path.addPath(couronne)


def _reset(path: QPainterPath) -> None:
    """Corbeille — la purge des données. Geste irréversible, icône sans appel."""
    cuve = QPainterPath()
    cuve.moveTo(24.0, 34.0)
    cuve.lineTo(76.0, 34.0)
    cuve.lineTo(69.0, 90.0)
    cuve.lineTo(31.0, 90.0)
    cuve.closeSubpath()
    for x in (41.0, 55.0):
        barre = QPainterPath()
        barre.addRoundedRect(QRectF(x, 46.0, 8.0, 32.0), 4.0, 4.0)
        cuve.addPath(barre.toReversed())
    path.addPath(cuve)
    _rounded(path, 16.0, 22.0, 68.0, 12.0, 6.0)
    _rounded(path, 40.0, 10.0, 20.0, 10.0, 4.0)


def _cat_hat(path: QPainterPath) -> None:
    """Haut-de-forme — la catégorie des chapeaux."""
    _rounded(path, 10.0, 68.0, 80.0, 14.0, 7.0)
    _rounded(path, 28.0, 18.0, 44.0, 54.0, 6.0)
    bandeau = QPainterPath()
    _rounded(bandeau, 26.0, 54.0, 48.0, 13.0, 4.0)
    path.addPath(bandeau.toReversed())


def _cat_moustache(path: QPainterPath) -> None:
    """Moustache à guidon — la catégorie des moustaches."""
    corps = QPainterPath()
    corps.moveTo(50.0, 36.0)
    corps.quadTo(76.0, 34.0, 88.0, 50.0)
    corps.quadTo(78.0, 72.0, 58.0, 58.0)
    corps.quadTo(50.0, 52.0, 42.0, 58.0)
    corps.quadTo(22.0, 72.0, 12.0, 50.0)
    corps.quadTo(24.0, 34.0, 50.0, 36.0)
    corps.closeSubpath()
    path.addPath(corps)


def _check(path: QPainterPath) -> None:
    """Coche — valider. Le pendant du retour, sur la page de nommage."""
    trait = QPainterPath()
    trait.moveTo(20.0, 52.0)
    trait.lineTo(41.0, 72.0)
    trait.lineTo(82.0, 28.0)
    stroker = QPainterPathStroker()
    stroker.setWidth(15.0)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    path.addPath(stroker.createStroke(trait))


def _clock(path: QPainterPath) -> None:
    """Horloge — le temps passé ensemble.

    Aiguilles à dix heures dix, comme sur toutes les vitrines d'horloger : à
    midi pile elles se confondent, et l'icône n'a plus qu'un trait.
    """
    cadran = QPainterPath()
    cadran.addEllipse(QRectF(10.0, 10.0, 80.0, 80.0))
    creux = QPainterPath()
    creux.addEllipse(QRectF(20.0, 20.0, 60.0, 60.0))
    cadran.addPath(creux.toReversed())
    path.addPath(cadran)

    aiguilles = QPainterPath()
    aiguilles.moveTo(50.0, 50.0)
    aiguilles.lineTo(50.0, 28.0)
    aiguilles.moveTo(50.0, 50.0)
    aiguilles.lineTo(70.0, 58.0)
    stroker = QPainterPathStroker()
    stroker.setWidth(9.0)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    path.addPath(stroker.createStroke(aiguilles))


def _cake(path: QPainterPath) -> None:
    """Gâteau — l'anniversaire. Une bougie, parce qu'il n'y en a qu'un."""
    # Le glaçage déborde de part et d'autre, et une rainure l'en sépare : sans
    # elle, les deux rectangles fusionnent en un bloc qui se lit « valise ».
    gateau = QPainterPath()
    _rounded(gateau, 18.0, 52.0, 64.0, 36.0, 8.0)
    _rounded(gateau, 11.0, 44.0, 78.0, 16.0, 8.0)
    rainure = QPainterPath()
    rainure.addRect(QRectF(21.0, 59.0, 58.0, 4.0))
    gateau.addPath(rainure.toReversed())
    path.addPath(gateau)

    _rounded(path, 46.0, 24.0, 8.0, 20.0, 4.0)
    # La flamme est **détachée** de la mèche. Collée, elle prolongeait la bougie
    # et l'ensemble se lisait comme une antenne.
    flamme = QPainterPath()
    flamme.moveTo(50.0, 2.0)
    flamme.quadTo(63.0, 12.0, 50.0, 20.0)
    flamme.quadTo(37.0, 12.0, 50.0, 2.0)
    path.addPath(flamme)


def _trophy(path: QPainterPath) -> None:
    """Coupe — les trophées, et le bouton qui mène à leur page."""
    coupe = QPainterPath()
    coupe.moveTo(28.0, 14.0)
    coupe.lineTo(72.0, 14.0)
    coupe.lineTo(69.0, 40.0)
    coupe.quadTo(66.0, 62.0, 50.0, 62.0)
    coupe.quadTo(34.0, 62.0, 31.0, 40.0)
    coupe.closeSubpath()
    path.addPath(coupe)
    # Les anses sont des anneaux ouverts posés de part et d'autre : dessinées
    # pleines, elles alourdissent la coupe au point qu'on y voit un vase.
    for gauche in (True, False):
        rect = (QRectF(8.0, 18.0, 30.0, 30.0) if gauche
                else QRectF(62.0, 18.0, 30.0, 30.0))
        path.addPath(_stroked_arc(rect, 90.0 if gauche else 90.0,
                                  180.0 if gauche else -180.0, 8.0))
    _rounded(path, 44.0, 60.0, 12.0, 16.0, 3.0)
    _rounded(path, 28.0, 76.0, 44.0, 12.0, 5.0)


def _screen(path: QPainterPath) -> None:
    """Écran — ce qu'on regarde ensemble. Un cadre, un pied, un triangle."""
    cadre = QPainterPath()
    cadre.addRoundedRect(QRectF(10.0, 16.0, 80.0, 56.0), 9.0, 9.0)
    creux = QPainterPath()
    creux.addRoundedRect(QRectF(20.0, 26.0, 60.0, 36.0), 4.0, 4.0)
    cadre.addPath(creux.toReversed())
    path.addPath(cadre)
    lecture = QPainterPath()
    lecture.moveTo(43.0, 33.0)
    lecture.lineTo(65.0, 44.0)
    lecture.lineTo(43.0, 55.0)
    lecture.closeSubpath()
    path.addPath(lecture)
    _rounded(path, 34.0, 78.0, 32.0, 10.0, 5.0)
    _rounded(path, 45.0, 70.0, 10.0, 10.0, 2.0)


def _face(path: QPainterPath, courbure: float) -> None:
    """Visage d'humeur. `courbure` positive sourit, négative boude.

    Un seul tracé paramétré plutôt que trois icônes distinctes : les humeurs
    forment un continuum, et trois dessins séparés se seraient désaccordés.
    """
    contour = QPainterPath()
    contour.addEllipse(QRectF(10.0, 10.0, 80.0, 80.0))
    creux = QPainterPath()
    creux.addEllipse(QRectF(19.0, 19.0, 62.0, 62.0))
    contour.addPath(creux.toReversed())
    path.addPath(contour)

    path.addEllipse(QRectF(33.0, 36.0, 9.0, 14.0))
    path.addEllipse(QRectF(58.0, 36.0, 9.0, 14.0))

    # Bouche tracée **au trait puis épaissie**, et non refermée sur elle-même.
    # La version précédente fermait un fuseau entre deux courbes : à courbure
    # nulle il bombait quand même vers le haut, si bien que le visage « neutre »
    # souriait légèrement. Un trait d'épaisseur constante n'a pas ce défaut, et
    # sa courbure change franchement de signe.
    trait = QPainterPath()
    depart = 64.0 - 0.22 * courbure * 20.0
    trait.moveTo(33.0, depart)
    trait.quadTo(50.0, 64.0 + courbure * 26.0, 67.0, depart)
    stroker = QPainterPathStroker()
    stroker.setWidth(8.5)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    path.addPath(stroker.createStroke(trait))


# Table des tracés. Le nom est la clé, et il est stable : le panneau y référence
# ses boutons, et un nom inconnu dessine un carré plutôt que de lever.
BUILDERS = {
    "hunger": _bowl,
    "fun": _star,
    "energy": _battery,
    "hygiene": _drop,
    "status": _gauge,
    "interactions": _grid,
    "shop": _tag,
    "quit": _power,
    "back": _back,
    "check": _check,
    "custom": _palette,
    "token": _token,
    "games": _balloon,
    "inventory": _crate,
    # Rayons de consommables : l'icône du besoin servi. Un rayon et le besoin
    # qu'il sert disent la même chose, et un second pictogramme pour la même
    # idée n'apprendrait rien à personne.
    "shop_hunger": _bowl,
    "shop_hygiene": _drop,
    "shop_energy": _battery,
    "rally": _balloon,
    "cups": _cup,
    "shop_hat": _cat_hat,
    "shop_moustache": _cat_moustache,
    "settings": _gear,
    "trophies": _trophy,
    "trophy": _trophy,
    "clock": _clock,
    "cake": _cake,
    "screen": _screen,
    "autostart": _autostart,
    "reset": _reset,
    "feed": _bowl,
    "play": _star,
    "pet": _heart,
    "clean": _drop,
    "mood_happy": lambda p: _face(p, 1.0),
    "mood_neutral": lambda p: _face(p, 0.0),
    "mood_sad": lambda p: _face(p, -1.0),
}

ICON_NAMES = tuple(sorted(BUILDERS))

# Humeurs du `brain` vers les trois visages. Le `brain` publie un nom
# d'expression du §9 ; le panneau n'a pas besoin de la même finesse qu'une dalle
# de visage, trois degrés suffisent à une pastille de vingt pixels.
MOOD_ICONS = {
    "joyeux": "mood_happy",
    "affectueux": "mood_happy",
    "curieux": "mood_neutral",
    "neutre": "mood_neutral",
    "surpris": "mood_neutral",
    "somnolent": "mood_sad",
    "endormi": "mood_sad",
    "ennuye": "mood_sad",
    "mefiant": "mood_sad",
    "fache": "mood_sad",
    "reveil": "mood_neutral",
}


def icon_path(name: str) -> QPainterPath:
    """Tracé d'une icône dans le carré de 100. Cache volontairement absent.

    Un `QPainterPath` se construit en quelques microsecondes et le panneau ne
    se repeint qu'à l'ouverture ou au survol : un cache serait de la complexité
    pour un gain nul.
    """
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    builder = BUILDERS.get(name)
    if builder is None:
        _rounded(path, 20.0, 20.0, 60.0, 60.0, 10.0)
        return path
    builder(path)
    return path


def draw_icon(painter: QPainter, name: str, rect: QRectF, color) -> None:
    """Dessine l'icône `name` dans `rect`, en aplat de couleur `color`."""
    path = icon_path(name)
    painter.save()
    painter.translate(rect.left(), rect.top())
    painter.scale(rect.width() / BOX, rect.height() / BOX)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)
    painter.restore()


def draw_stroke_icon(painter: QPainter, name: str, rect: QRectF, color,
                     width: float = STROKE) -> None:
    """Variante au trait, pour les icônes qui doivent rester légères."""
    path = icon_path(name)
    painter.save()
    painter.translate(rect.left(), rect.top())
    painter.scale(rect.width() / BOX, rect.height() / BOX)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


def center_square(rect: QRectF, part: float = 0.56) -> QRectF:
    """Carré centré occupant `part` du plus petit côté de `rect`.

    Sert à poser une icône dans un bouton : c'est ce rapport qui donne à tous
    les boutons le même air, quelle que soit la forme de l'icône.
    """
    side = min(rect.width(), rect.height()) * part
    return QRectF(rect.center().x() - side / 2.0,
                  rect.center().y() - side / 2.0, side, side)
