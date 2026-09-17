"""Favicon et vignette de partage du site (lot L16).

    python -m tools.site_icons

**Le favicon est l'icône de l'application, à l'octet près.** `docs/favicon.ico`
est une copie de `packaging/desky.ico` plutôt qu'un rendu refait ici : deux
rendus séparés finiraient par diverger au premier réglage du moteur, et on
aurait deux robots légèrement différents selon qu'on regarde l'onglet ou la
barre des tâches. `tests/test_site.py` compare les deux fichiers.

Les déclinaisons PNG viennent en revanche du même appel que l'icône Windows —
`make_icon.render_sizes`, même graine, même cadrage, même tangage —, parce que
les navigateurs modernes et iOS veulent du PNG et que Windows n'en a pas besoin.

**La vignette de partage est en 1200 × 630**, le format qu'attendent les
aperçus. Jusqu'ici `og:image` pointait sur le logo, qui est trois fois et demie
plus large que haut : les aperçus le rognaient ou le noyaient dans du blanc.
"""

from __future__ import annotations

import pathlib
import shutil
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QRadialGradient)

from tools.make_icon import MASCOT_SEED, render_sizes

DOCS = pathlib.Path("docs")
ICONE_APP = pathlib.Path("packaging") / "desky.ico"

# Tailles PNG. 32 pour l'onglet, 180 pour l'écran d'accueil iOS, 512 pour les
# manifestes et les gros aperçus.
PNG_SIZES = (32, 180, 512)

# Vignette de partage.
CARD_W, CARD_H = 1200, 630

# Les teintes du site, recopiées de `docs/style.css`. Une vignette qui ne
# ressemblerait pas à la page qu'elle annonce ferait douter du lien.
FOND_HAUT = QColor("#fcfefe")
FOND_BAS = QColor("#f2f7f8")
HALO_FROID = QColor(220, 241, 245)
HALO_CHAUD = QColor(253, 238, 221)


def ecrire_favicons() -> list[pathlib.Path]:
    ecrits = []

    cible = DOCS / "favicon.ico"
    shutil.copyfile(ICONE_APP, cible)
    ecrits.append(cible)

    for image, taille in zip(render_sizes(MASCOT_SEED, PNG_SIZES), PNG_SIZES):
        chemin = DOCS / "assets" / ("icon-%d.png" % taille)
        image.convertToFormat(QImage.Format.Format_RGBA8888).save(str(chemin), "PNG")
        ecrits.append(chemin)
    return ecrits


def _fond(painter: QPainter) -> None:
    lineaire = QLinearGradient(0, 0, 0, CARD_H)
    lineaire.setColorAt(0.0, FOND_HAUT)
    lineaire.setColorAt(1.0, FOND_BAS)
    painter.fillRect(0, 0, CARD_W, CARD_H, lineaire)

    for centre, couleur, rayon in (((0.5, 0.08), HALO_FROID, 0.75),
                                   ((0.86, 0.86), HALO_CHAUD, 0.6)):
        halo = QRadialGradient(CARD_W * centre[0], CARD_H * centre[1],
                               CARD_W * rayon)
        debut = QColor(couleur)
        fin = QColor(couleur)
        fin.setAlpha(0)
        halo.setColorAt(0.0, debut)
        halo.setColorAt(1.0, fin)
        painter.fillRect(0, 0, CARD_W, CARD_H, halo)


def ecrire_vignette() -> pathlib.Path:
    carte = QImage(CARD_W, CARD_H, QImage.Format.Format_ARGB32_Premultiplied)
    carte.fill(QColor(255, 255, 255))

    painter = QPainter(carte)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    _fond(painter)

    # Une rangée de variantes en fond, pâles : c'est le champ de la page, et il
    # dit d'un coup d'œil que chaque robot est différent.
    planche = QImage(str(DOCS / "assets" / "deskys.webp"))
    if not planche.isNull():
        cote_w = planche.width() // 10
        cote_h = planche.height() // 5
        painter.setOpacity(0.30)
        for index, (col, row) in enumerate(((1, 0), (4, 2), (7, 1), (9, 3),
                                            (2, 4), (6, 0))):
            h = 150 + (index % 3) * 34
            w = h * cote_w / cote_h
            x = 40 + index * 196
            y = CARD_H - h - 24 - (index % 2) * 30
            painter.drawImage(QRectF(x, y, w, h), planche,
                              QRectF(col * cote_w, row * cote_h, cote_w, cote_h))
        painter.setOpacity(1.0)

    logo = QImage(str(DOCS / "assets" / "logo.png"))
    if not logo.isNull():
        large = 720.0
        haut = large * logo.height() / logo.width()
        painter.drawImage(QRectF((CARD_W - large) / 2, 120, large, haut),
                          logo, QRectF(logo.rect()))

    chemin = DOCS / "assets" / "social.png"
    painter.end()
    carte.save(str(chemin), "PNG")
    return chemin


def main(argv: list[str]) -> int:
    QGuiApplication.instance() or QGuiApplication([])

    if not ICONE_APP.is_file():
        print("icône de l'application absente : %s" % ICONE_APP)
        return 1
    (DOCS / "assets").mkdir(parents=True, exist_ok=True)

    for chemin in ecrire_favicons():
        print("%s : %.0f Ko" % (chemin, chemin.stat().st_size / 1024))
    vignette = ecrire_vignette()
    print("%s : %d x %d, %.0f Ko"
          % (vignette, CARD_W, CARD_H, vignette.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
