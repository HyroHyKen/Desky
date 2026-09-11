"""Peinture des particules, et recettes qui les déclenchent (lot L11).

Deux choses ici, et elles vont ensemble : ce qu'un fait produit comme gerbe, et
à quoi cette gerbe ressemble. Ce sont deux moitiés de la même décision
esthétique, et les séparer obligerait à relire deux fichiers pour régler un
effet.

**Peintes par `QPainter`, pas rendues dans la scène GL.** Le hit-testing du pet
lit l'alpha de l'image rendue (`window._opaque_bbox` et `_on_hit_test`) : toute
matière dessinée dans le FBO deviendrait **cliquable** — des étincelles qui
avalent les clics destinés à la fenêtre du dessous. Peintes hors du rendu, elles
ne touchent jamais cet alpha. C'est aussi la voie la moins chère : aucune passe
GL, aucun tampon à recycler.

**Et peintes dans leur propre fenêtre**, pas dans celle du robot — voir
`ui/dust` pour les deux raisons. Conséquence ici : toutes les positions sont en
**pixels physiques d'écran**, comme celles du pet et des objets de soin, et
jamais en coordonnées de widget. Une particule appartient à l'endroit où elle
est retombée, pas à la fenêtre qui passait par là.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ..anim.particles import DUST, REFUS, SLEEP, SPARK, Particles

# Cyan du produit. **Doit valoir `panel.ACCENT`** : une étincelle de soin et la
# jauge qu'elle vient de remplir sont le même geste, et deux cyans voisins mais
# distincts se remarquent immédiatement. Recopié plutôt qu'importé pour ne pas
# faire dépendre les particules du panneau de soin ; un test vérifie l'égalité.
ACCENT = QColor(31, 168, 186)

# Poussière : la teinte de l'ombre de contact, pas un gris neutre. C'est de la
# matière du sol soulevée, elle appartient au sol.
DUST_COLOR = QColor(96, 104, 112)

# Sommeil : bleu doux, nettement moins contrasté que l'accent. Un « Z » qui
# saute aux yeux réveillerait l'utilisateur, pas le robot.
SLEEP_COLOR = QColor(120, 141, 166)

REFUS_COLOR = QColor(196, 112, 58)     # l'ambre des jauges basses


# ---------------------------------------------------------------------------
# Recettes
# ---------------------------------------------------------------------------
#
# Toutes prennent le **rectangle du pet en pixels physiques** — `(gauche, haut,
# largeur, hauteur)`, exactement ce que rend `window._pet_rect` — et expriment
# leurs distances en fractions de sa hauteur : la taille de rendu va de 120 à
# 400 px (§17.1), et un effet réglé en pixels serait ridicule à un bout et
# envahissant à l'autre.
#
# Le rectangle plutôt que la seule taille : une gerbe naît **quelque part sur
# l'écran**, et ce quelque part ne doit plus rien devoir à la fenêtre qui
# l'émet.


def landing_dust(banc: Particles, force: float, rect) -> int:
    """Poussière d'atterrissage, dosée par la force du choc.

    `force` vient du bus, telle que l'encaissement du lot L10 l'a calculée : la
    même valeur nourrit la déformation du corps et cette gerbe, donc les deux
    disent la même chose de la violence du choc. C'est ce qui fait qu'ils se
    lisent comme un seul événement et non comme deux effets superposés.
    """
    force = max(0.0, min(1.0, force))
    if force < 0.12:
        return 0                        # un pas posé ne soulève rien
    left, top, w, h = rect
    combien = int(4 + 12 * force)
    return banc.burst(
        DUST, left + w * 0.5, top + h - h * 0.02, combien,
        speed=h * (0.55 + 0.95 * force), spread=0.62,
        life=0.42 + 0.22 * force, size=h * 0.060,
        x_spread=w * 0.06, y_spread=h * 0.01)


def care_sparks(banc: Particles, rect) -> int:
    """Halo de soin : il naît **autour** du robot, et il monte.

    Le point de naissance est bas et large, jamais au centre. Émises du milieu
    de la fenêtre, les étincelles apparaissent par-dessus le visage — elles sont
    peintes après lui — et se lisent alors comme un défaut d'affichage plutôt
    que comme une réaction. Nées au niveau du corps et étalées sur toute la
    largeur, elles remontent le long de la silhouette, ce qui est exactement ce
    qu'on voulait montrer.
    """
    left, top, w, h = rect
    return banc.burst(
        SPARK, left + w * 0.5, top + h * 0.82, 16,
        speed=h * 0.80, spread=0.55, life=0.70, size=h * 0.040, up=1.0,
        x_spread=w * 0.36, y_spread=h * 0.04)


def refusal_puff(banc: Particles, rect) -> int:
    """Petit refus : trois particules ambre, courtes. Un « non », pas un drame.

    Le §12 interdit de culpabiliser l'utilisateur : un achat hors budget
    mérite un signal, pas une réprimande. Trois particules et un tiers de
    seconde sont exactement le poids d'un haussement d'épaules.
    """
    left, top, w, h = rect
    return banc.burst(
        REFUS, left + w * 0.5, top + h * 0.72, 4,
        speed=h * 0.38, spread=0.30, life=0.36, size=h * 0.038, up=0.8,
        x_spread=w * 0.16, y_spread=h * 0.02)


def sleep_z(banc: Particles, rect) -> int:
    """Un « Z » qui s'élève. Émis au compte-gouttes par la fenêtre."""
    left, top, w, h = rect
    return banc.burst(
        SLEEP, left + w * 0.62, top + h * 0.34, 1,
        speed=h * 0.13, spread=0.25, life=2.1, size=h * 0.075, up=1.0)


# ---------------------------------------------------------------------------
# Peinture
# ---------------------------------------------------------------------------


def _z_path(painter: QPainter, x: float, y: float, s: float) -> None:
    """Trace un « Z » de taille `s`, centré sur (x, y)."""
    demi = s * 0.5
    painter.drawPolyline([
        QPointF(x - demi, y - demi),
        QPointF(x + demi, y - demi),
        QPointF(x - demi, y + demi),
        QPointF(x + demi, y + demi),
    ])


def draw(painter: QPainter, banc: Particles, origin=(0.0, 0.0),
         dpr: float = 1.0) -> None:
    """Peint le banc dans le calque dont le coin haut-gauche est `origin`.

    Les particules sont en pixels physiques d'écran ; `QPainter`, lui, travaille
    en logique. La conversion se fait ici, en un seul point, exactement comme
    `window.place_panel` le fait pour le panneau. Confondre les deux donne des
    gerbes deux fois trop grandes et décalées d'un écran sur un poste à 200 %.
    """
    idx, age = banc.visible()
    if idx.size == 0:
        return

    ox, oy = origin
    echelle = 1.0 / max(1e-6, dpr)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    xs = (banc.x[idx] - ox) * echelle
    ys = (banc.y[idx] - oy) * echelle
    tailles, familles = banc.size[idx] * echelle, banc.kind[idx]

    for k in range(idx.size):
        a = float(age[k])
        x, y, s = float(xs[k]), float(ys[k]), float(tailles[k])
        famille = int(familles[k])

        if famille == DUST:
            # Elle **grossit** en s'effaçant : c'est ce qui la fait se
            # dissiper au lieu de s'éteindre. Une particule qui rétrécit en
            # disparaissant a l'air aspirée.
            couleur = QColor(DUST_COLOR)
            couleur.setAlphaF(max(0.0, 0.60 * (1.0 - a) ** 1.4))
            rayon = s * (0.55 + 0.95 * a)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(couleur)
            painter.drawEllipse(QPointF(x, y), rayon, rayon * 0.82)

        elif famille in (SPARK, REFUS):
            # Deux familles pour un même dessin : le losange est le bon signe
            # dans les deux cas, seule la couleur change. Les distinguer par la
            # famille et non par un attribut détourné garde `burst` honnête —
            # une taille négative aurait marché jusqu'au jour où quelqu'un
            # aurait trié le banc par taille.
            couleur = QColor(ACCENT if famille == SPARK else REFUS_COLOR)
            couleur.setAlphaF(max(0.0, 1.0 - a * a))
            rayon = s * (1.0 - 0.55 * a)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(couleur)
            # Losange plutôt que disque : une étincelle a des pointes, et à
            # cette taille c'est la seule chose qui la distingue d'une
            # poussière claire.
            painter.drawPolygon([
                QPointF(x, y - rayon), QPointF(x + rayon * 0.5, y),
                QPointF(x, y + rayon), QPointF(x - rayon * 0.5, y),
            ])

        else:                                           # SLEEP
            couleur = QColor(SLEEP_COLOR)
            # Il apparaît, tient, puis s'efface : un « Z » qui naît déjà opaque
            # se remarque comme un clignotement.
            opacite = min(1.0, a * 5.0) * max(0.0, 1.0 - max(0.0, a - 0.55) / 0.45)
            couleur.setAlphaF(0.75 * opacite)
            stylo = QPen(couleur)
            stylo.setWidthF(max(1.2, s * 0.16))
            stylo.setCapStyle(Qt.PenCapStyle.RoundCap)
            stylo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(stylo)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            _z_path(painter, x, y, s * (0.8 + 0.5 * a))

    painter.restore()
