"""Illustrations des châssis, pour le choix du premier lancement (lot L20).

    python -m tools.make_chassis_art

Deux familles d'images, toutes rendues par le moteur du produit :

- **un dessin industriel par châssis**, pour le carton qu'on choisit ;
- **quelques vignettes d'exemples par châssis**, pour l'infobulle qui les fait
  défiler.

**Le blueprint n'est pas dessiné à la main, il est extrait du rendu.** Le robot
est rendu normalement, puis on lui prend ses arêtes : le bord de sa silhouette
dans le canal alpha, et les ruptures de luminance à l'intérieur — le contour
toon, la dalle faciale, la césure entre les volumes. On obtient donc un tracé
qui est **exactement** celui du robot que l'utilisateur recevra, et qui suivra
toute évolution de la géométrie sans qu'on ait à redessiner quoi que ce soit.

C'est aussi la seule méthode honnête ici : une illustration dessinée à côté
finirait par promettre un robot que le moteur ne produit plus.

Les vignettes, elles, sont des rendus ordinaires. Elles montrent la variété
réelle du châssis — proportions, exposants, couleurs — parce que c'est
précisément la question que se pose quelqu'un devant les deux cartons.
"""

from __future__ import annotations

import pathlib
import sys
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter,
                           QPen)

from pet.genome.generator import generate
from pet.genome.model import model_name
from pet.geometry import proportions
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.scene import Scene

SORTIE = pathlib.Path("pet") / "assets" / "chassis"

# --- Le dessin industriel ---------------------------------------------------

PLANCHE_W, PLANCHE_H = 560, 700
RENDU = 660                     # côté du rendu dont on extrait les arêtes

# Graine vedette de chaque châssis. Figée : c'est l'image qui représente la
# famille, elle ne doit pas changer d'une régénération à l'autre.
VEDETTES = {"capsule": 101, "monobloc": 11}

# Palette du blueprint. Bleu profond légèrement vert, pour rester dans la
# famille du cyan du produit plutôt que dans le bleu roi des plans d'architecte.
FOND = QColor("#0d2b36")
FOND_BAS = QColor("#123a48")
GRILLE = QColor(150, 226, 240, 26)
GRILLE_FORTE = QColor(150, 226, 240, 52)
TRAIT = QColor("#bdeef7")
COTE = QColor(150, 226, 240, 170)
CARTOUCHE = QColor(190, 238, 247, 210)

# Seuils d'extraction. `ALPHA` isole la silhouette, `LUMA` les ruptures
# internes. Réglés au rendu, et le second est le délicat : à 0,16 le dégradé
# lisse du toon produisait des volutes à l'intérieur des volumes, qui se
# lisaient comme des traces de gomme et non comme des traits de construction.
# À 0,42 seules les ruptures franches survivent — contour, dalle, jointures.
ALPHA_SEUIL = 0.35
LUMA_SEUIL = 0.42

# Millimètres par unité de monde. Purement décoratif, mais **déduit des vraies
# dimensions** : coter les deux planches à la même valeur parce qu'elles sont
# cadrées pareil aurait été un mensonge gratuit, et le premier à s'en apercevoir
# aurait eu raison de douter du reste.
MM_PAR_UNITE = 42.0

# --- Les vignettes ----------------------------------------------------------

VIGNETTE = 240
EXEMPLES = 6

# Graines des exemples, par châssis. Choisies pour couvrir la variété plutôt que
# tirées au hasard : c'est une vitrine, elle doit montrer les extrêmes.
GRAINES_EXEMPLES = {
    "capsule": (3, 47, 101, 512, 1234, 4242),
    "monobloc": (11, 23, 88, 233, 777, 2024),
}


def _genome(seed: int, chassis: str) -> dict:
    g = generate(seed)
    g["chassis"] = chassis
    if chassis == "monobloc":
        g["ear.type"] = "none"
    return g


def _rendu(scene: Scene, rc: RenderContext, genome: dict, pitch: float):
    scene.set_robot(build(genome))
    rc.begin()
    scene.draw(yaw=0.0, pitch=pitch, scale=1.0, time_s=0.0, lift=0.0)
    return rc.read_rgba().copy()


def _aretes(frame: np.ndarray) -> np.ndarray:
    """Carte d'arêtes dans [0, 1], depuis un rendu RGBA.

    Deux sources, additionnées : le bord de l'alpha — la silhouette — et le
    gradient de luminance à l'intérieur, qui attrape le contour toon, la dalle
    faciale et les jointures. Le gradient est masqué par l'alpha, sans quoi le
    bord de l'image produirait une seconde silhouette décalée d'un pixel.
    """
    rgb = frame[:, :, :3].astype(np.float32) / 255.0
    alpha = frame[:, :, 3].astype(np.float32) / 255.0
    luma = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114

    def gradient(canal: np.ndarray) -> np.ndarray:
        gy, gx = np.gradient(canal)
        return np.hypot(gx, gy)

    bord = gradient(alpha)
    interieur = gradient(luma * alpha) * (alpha > 0.5)

    carte = np.clip(bord / max(1e-6, ALPHA_SEUIL), 0.0, 1.0)
    carte = np.maximum(carte, np.clip(interieur / max(1e-6, LUMA_SEUIL), 0.0, 1.0))
    return carte


def _fond(painter: QPainter) -> None:
    from PySide6.QtGui import QLinearGradient

    degrade = QLinearGradient(0, 0, 0, PLANCHE_H)
    degrade.setColorAt(0.0, FOND)
    degrade.setColorAt(1.0, FOND_BAS)
    painter.fillRect(0, 0, PLANCHE_W, PLANCHE_H, degrade)

    for pas, couleur, epaisseur in ((20, GRILLE, 1.0), (100, GRILLE_FORTE, 1.0)):
        painter.setPen(QPen(couleur, epaisseur))
        for x in range(0, PLANCHE_W + 1, pas):
            painter.drawLine(x, 0, x, PLANCHE_H)
        for y in range(0, PLANCHE_H + 1, pas):
            painter.drawLine(0, y, PLANCHE_W, y)


def _cotes(painter: QPainter, boite: QRectF, hauteur_mm: int,
           largeur_mm: int) -> None:
    """Lignes de cote, à gauche et en bas. C'est ce qui fait « plan »."""
    painter.setPen(QPen(COTE, 1.2))
    police = QFont()
    police.setPixelSize(13)
    police.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
    painter.setFont(police)

    x = boite.left() - 26
    painter.drawLine(QPointF(x, boite.top()), QPointF(x, boite.bottom()))
    for y in (boite.top(), boite.bottom()):
        painter.drawLine(QPointF(x - 5, y), QPointF(x + 5, y))
    painter.save()
    painter.translate(x - 8, boite.center().y())
    painter.rotate(-90)
    painter.drawText(QRectF(-60, -16, 120, 16),
                     int(Qt.AlignmentFlag.AlignCenter), "%d mm" % hauteur_mm)
    painter.restore()

    y = boite.bottom() + 26
    painter.drawLine(QPointF(boite.left(), y), QPointF(boite.right(), y))
    for x2 in (boite.left(), boite.right()):
        painter.drawLine(QPointF(x2, y - 5), QPointF(x2, y + 5))
    painter.drawText(QRectF(boite.left(), y + 4, boite.width(), 18),
                     int(Qt.AlignmentFlag.AlignCenter), "%d mm" % largeur_mm)


def _cartouche(painter: QPainter, chassis: str, reference: str) -> None:
    haut = PLANCHE_H - 84
    painter.setPen(QPen(QColor(150, 226, 240, 90), 1.2))
    painter.drawLine(24, haut, PLANCHE_W - 24, haut)
    painter.drawLine(24, haut + 34, PLANCHE_W - 24, haut + 34)

    titre = QFont()
    titre.setPixelSize(22)
    titre.setWeight(QFont.Weight.Bold)
    titre.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.4)
    painter.setFont(titre)
    painter.setPen(CARTOUCHE)
    painter.drawText(QRectF(24, haut + 2, PLANCHE_W - 48, 32),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                     "CHÂSSIS %s" % chassis.upper())

    petit = QFont()
    petit.setPixelSize(12)
    petit.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
    painter.setFont(petit)
    painter.setPen(QColor(150, 226, 240, 190))
    painter.drawText(QRectF(24, haut + 38, PLANCHE_W - 48, 20),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                     "DESKY INC.  ·  SÉRIE %s  ·  ÉCH. 1:1" % reference)


def planche(scene: Scene, rc: RenderContext, chassis: str) -> QImage:
    genome = _genome(VEDETTES[chassis], chassis)
    frame = _rendu(scene, rc, genome, pitch=0.0)
    carte = _aretes(frame)

    # Les arêtes deviennent une image en niveaux d'alpha, teintée du trait.
    hauteur, largeur = carte.shape
    rgba = np.zeros((hauteur, largeur, 4), dtype=np.uint8)
    rgba[:, :, 0] = TRAIT.red()
    rgba[:, :, 1] = TRAIT.green()
    rgba[:, :, 2] = TRAIT.blue()
    rgba[:, :, 3] = (np.clip(carte, 0.0, 1.0) * 255).astype(np.uint8)
    trait = QImage(rgba.data, largeur, hauteur, largeur * 4,
                   QImage.Format.Format_RGBA8888).copy()

    planche = QImage(PLANCHE_W, PLANCHE_H, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(planche)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    _fond(painter)

    # Le tracé est cadré sur ce qu'il contient réellement, et non sur la boîte
    # de rendu : les deux châssis n'occupent pas la même part de leur carré.
    masque = carte > 0.06
    lignes = np.flatnonzero(masque.any(axis=1))
    colonnes = np.flatnonzero(masque.any(axis=0))
    source = QRectF(float(colonnes[0]), float(lignes[0]),
                    float(colonnes[-1] - colonnes[0] + 1),
                    float(lignes[-1] - lignes[0] + 1))

    dispo_h = PLANCHE_H - 250
    echelle = dispo_h / source.height()
    dest_w = source.width() * echelle
    boite = QRectF((PLANCHE_W - dest_w) / 2.0, 92.0, dest_w, dispo_h)
    painter.drawImage(boite, trait, source)

    dims = proportions.dimensions(genome)
    _cotes(painter, boite,
           hauteur_mm=int(round(dims.total_height * MM_PAR_UNITE)),
           largeur_mm=int(round(2.0 * max(dims.head_a, dims.body_a)
                                * MM_PAR_UNITE)))
    _cartouche(painter, chassis, model_name(genome))
    painter.end()
    return planche


def vignettes(scene: Scene, rc: RenderContext, chassis: str) -> list[QImage]:
    images = []
    for seed in GRAINES_EXEMPLES[chassis][:EXEMPLES]:
        frame = _rendu(scene, rc, _genome(seed, chassis), pitch=0.16)
        h, w = frame.shape[0], frame.shape[1]
        img = QImage(frame.data, w, h, w * 4,
                     QImage.Format.Format_RGBA8888_Premultiplied).copy()
        images.append(img.scaledToWidth(VIGNETTE,
                                        Qt.TransformationMode.SmoothTransformation))
    return images


def main(argv: list[str]) -> int:
    QGuiApplication.instance() or QGuiApplication([])
    SORTIE.mkdir(parents=True, exist_ok=True)
    debut = time.perf_counter()

    rc_plan = RenderContext((RENDU, RENDU), samples=8)
    scene_plan = Scene(rc_plan)
    rc_vig = RenderContext((VIGNETTE * 2, int(VIGNETTE * 2.4)), samples=4)
    scene_vig = Scene(rc_vig)

    ecrits = 0
    for chassis in ("capsule", "monobloc"):
        chemin = SORTIE / ("blueprint_%s.png" % chassis)
        planche(scene_plan, rc_plan, chassis).save(str(chemin), "PNG")
        print("%s : %.0f Ko" % (chemin, chemin.stat().st_size / 1024))
        ecrits += 1

        for index, image in enumerate(vignettes(scene_vig, rc_vig, chassis), 1):
            c = SORTIE / ("exemple_%s_%d.png" % (chassis, index))
            image.save(str(c), "PNG")
            ecrits += 1

    print("%d images en %.1f s" % (ecrits, time.perf_counter() - debut))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
