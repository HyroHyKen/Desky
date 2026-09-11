"""Planche des cosmétiques, sur plusieurs morphologies.

Un chapeau se juge sur **des têtes différentes**, pas sur une seule : les
proportions de crâne varient du simple au double d'un génome à l'autre, et une
cote posée à l'oeil sur un robot trapu déborde sur un robot élancé.

    .venv/Scripts/python.exe -m tools.hat_sheet --out chapeaux.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.geometry.cosmetics import NONE, SLOTS, by_slot
from pet.render.context import RenderContext
from pet.render.scene import Scene

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BG = "#C6CBD0"
LABEL = "#22282D"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planche des cosmétiques")
    ap.add_argument("--seeds", type=int, nargs="+", default=[8, 3, 21])
    ap.add_argument("--size", type=int, default=220)
    ap.add_argument("--out", type=Path, default=Path("chapeaux.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    QGuiApplication.instance() or QGuiApplication([])

    tile = args.size
    rc = RenderContext((tile, tile), samples=4)
    scene = Scene(rc)
    print("rendu sur %s" % rc.info["renderer"])

    colonnes = [(NONE, 0, "")]
    for emplacement in SLOTS:
        colonnes += [(c.key, c.price, emplacement) for c in by_slot(emplacement)]
    marge, pied, entete = 8, 22, 22
    largeur = marge + len(colonnes) * (tile + marge)
    hauteur = entete + len(args.seeds) * (tile + pied) + marge

    sheet = QImage(largeur, hauteur, QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(QColor(BG))
    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(12)
    painter.setFont(font)
    centre = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    for ligne, seed in enumerate(args.seeds):
        genome = generate(seed)
        for colonne, (cle, _, emplacement) in enumerate(colonnes):
            scene.set_robot(build(genome,
                                  {emplacement: cle} if cle else None))
            rc.begin()
            scene.draw(yaw=0.0, pitch=0.14)
            px = rc.read_rgba()
            image = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                           QImage.Format.Format_RGBA8888_Premultiplied)
            painter.drawImage(marge + colonne * (tile + marge),
                              entete + ligne * (tile + pied), image)

    painter.setPen(QColor(LABEL))
    for colonne, (cle, prix, _) in enumerate(colonnes):
        etiquette = "aucun" if not cle else "%s — %d" % (cle, prix)
        painter.drawText(QRectF(marge + colonne * (tile + marge), 4, tile, 18),
                         centre, etiquette)
    painter.end()

    ok = sheet.save(str(args.out))
    print("planche %s : %s (%dx%d) — %d articles sur %d morphologies"
          % ("ecrite" if ok else "ECHEC", args.out, largeur, hauteur,
             len(colonnes) - 1, len(args.seeds)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
