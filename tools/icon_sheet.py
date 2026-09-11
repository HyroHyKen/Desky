"""Planche des icônes du panneau, aux tailles où elles seront vues.

L'interface du lot L6 n'a **aucun texte** : chaque icône doit donc être
compréhensible seule, et à vingt pixels de côté. Cette planche les montre à
trois tailles, en aplat et au trait, sur les deux fonds du panneau.

    .venv/Scripts/python.exe -m tools.icon_sheet --out icones.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pet.ui.icons import ICON_NAMES, draw_icon, draw_stroke_icon

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TAILLES = (20, 32, 56)
FOND = "#F4F6F7"
BOUTON = "#E2E7EA"
ENCRE = "#141A21"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planche des icônes du panneau")
    ap.add_argument("--out", type=Path, default=Path("icones.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter)
    QGuiApplication.instance() or QGuiApplication([])

    # Largeur suffisante pour les trois tailles côte à côte : la première
    # version se chevauchait, et une planche illisible ne juge rien.
    colonne = sum(TAILLES) + 4 * len(TAILLES) + 26
    ligne = 84
    largeur = 20 + len(ICON_NAMES) * colonne
    hauteur = 20 + 2 * ligne + 30

    image = QImage(largeur, hauteur, QImage.Format.Format_RGBA8888_Premultiplied)
    image.fill(QColor(FOND))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    font = QFont()
    font.setPixelSize(10)
    painter.setFont(font)
    centre = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    for index, name in enumerate(ICON_NAMES):
        x = 20 + index * colonne

        # Rangée 1 : aplat, sur une pastille de bouton, aux trois tailles.
        y = 20
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BOUTON))
        painter.drawRoundedRect(
            QRectF(x - 6, y - 6, sum(TAILLES) + 4 * len(TAILLES) + 4, 68),
            14, 14)
        cx = x
        for taille in TAILLES:
            draw_icon(painter, name, QRectF(cx, y + (56 - taille) / 2,
                                           taille, taille), QColor(ENCRE))
            cx += taille + 4

        # Rangée 2 : au trait, sans pastille.
        y = 20 + ligne
        cx = x
        for taille in TAILLES:
            draw_stroke_icon(painter, name,
                             QRectF(cx, y + (56 - taille) / 2, taille, taille),
                             QColor(ENCRE))
            cx += taille + 4

        painter.setPen(QColor("#5A6570"))
        painter.drawText(QRectF(x - 8, 20 + 2 * ligne, colonne, 24), centre, name)

    painter.end()
    ok = image.save(str(args.out))
    print("planche %s : %s (%dx%d) — %d icônes, tailles %s"
          % ("ecrite" if ok else "ECHEC", args.out, largeur, hauteur,
             len(ICON_NAMES), TAILLES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
