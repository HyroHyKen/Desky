"""Planche de jugement de la bulle, des sigles et du bandeau réservé.

Trois choses ne se tranchent qu'à l'oeil, et cet outil les met côte à côte :

- **les sigles sont-ils lisibles** à la taille où ils seront vus, une bulle de
  vingt-cinq pixels de côté ;
- **les yeux comme afficheur** : deux pictogrammes à la place des pupilles
  doivent rester reconnaissables sur une dalle bombée ;
- **le bandeau réservé** : combien de hauteur la bulle peut prendre avant que le
  robot paraisse rapetissé.

    .venv/Scripts/python.exe -m tools.bubble_sheet --out bulle.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.glyphs import GLYPH_FOR_NEED, GLYPH_NAMES, glyph_id
from pet.render.scene import BUBBLE_HEADROOM, Scene

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Paires affichées dans les yeux. La première est celle du baptême, au premier
# lancement : « qui suis-je ».
EYE_PAIRS = (
    ("robot", "question"),
    ("hunger", "question"),
    ("fun", "fun"),
    ("energy", "hygiene"),
)

HEADROOMS = (0.0, 0.13, BUBBLE_HEADROOM, 0.40)

BG = "#D9D8D2"
LABEL = "#33322E"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planche de la bulle et des sigles")
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--size", type=int, default=220)
    ap.add_argument("--out", type=Path, default=Path("bulle.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    QGuiApplication.instance() or QGuiApplication([])

    tile = args.size
    rc = RenderContext((tile, tile), samples=4)
    scene = Scene(rc)
    scene.set_robot(build(generate(args.seed)))
    print("rendu sur %s" % rc.info["renderer"])

    besoins = tuple(GLYPH_FOR_NEED)
    colonnes = max(len(besoins), len(EYE_PAIRS), len(HEADROOMS))
    marge, entete, pied = 10, 22, 20
    largeur = marge + colonnes * (tile + marge)
    hauteur = 3 * (entete + tile + pied) + marge

    sheet = QImage(largeur, hauteur, QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(QColor(BG))
    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(12)
    painter.setFont(font)
    centre = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    gauche = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def rendre(x: int, y: int, legende: str) -> None:
        rc.begin()
        scene.draw(yaw=0.0, pitch=0.14)
        px = rc.read_rgba()
        image = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                       QImage.Format.Format_RGBA8888_Premultiplied)
        painter.drawImage(x, y, image)
        painter.setPen(QColor(LABEL))
        painter.drawText(QRect(x, y + tile, tile, pied), centre, legende)

    def titre(y: int, texte: str) -> None:
        painter.setPen(QColor(LABEL))
        painter.drawText(QRect(marge, y, largeur - marge, entete), gauche, texte)

    def reset() -> None:
        scene.bubble_glyph = 0
        scene.bubble_opacity = 0.0
        scene.eye_glyph_mix = 0.0
        scene.headroom = BUBBLE_HEADROOM

    # -- rangée 1 : les quatre besoins dans la bulle ------------------------
    y = marge
    titre(y, "bulle : un sigle par besoin (bandeau %.0f %%)"
          % (100 * BUBBLE_HEADROOM))
    y += entete
    for index, besoin in enumerate(besoins):
        reset()
        scene.bubble_glyph = glyph_id(GLYPH_FOR_NEED[besoin])
        scene.bubble_opacity = 1.0
        scene.bubble_pulse = 1.0
        rendre(marge + index * (tile + marge), y, besoin)

    # -- rangée 2 : les yeux comme afficheur --------------------------------
    y += tile + pied
    titre(y, "yeux : deux sigles à la place des pupilles")
    y += entete
    for index, (a, b) in enumerate(EYE_PAIRS):
        reset()
        scene.eye_glyphs = (glyph_id(a), glyph_id(b))
        scene.eye_glyph_mix = 1.0
        rendre(marge + index * (tile + marge), y, "%s + %s" % (a, b))

    # -- rangée 3 : le bandeau réservé --------------------------------------
    y += tile + pied
    titre(y, "bandeau réservé : le bord bas ne bouge pas, le robot rapetisse")
    y += entete
    for index, hr in enumerate(HEADROOMS):
        reset()
        scene.headroom = hr
        scene.bubble_glyph = glyph_id("hunger")
        scene.bubble_opacity = 1.0 if hr > 0.01 else 0.0
        marque = " (retenu)" if abs(hr - BUBBLE_HEADROOM) < 1e-6 else ""
        rendre(marge + index * (tile + marge), y, "%.0f %%%s" % (100 * hr, marque))

    painter.end()
    ok = sheet.save(str(args.out))
    print("planche %s : %s (%dx%d) — sigles %s"
          % ("ecrite" if ok else "ECHEC", args.out, largeur, hauteur,
             ", ".join(GLYPH_NAMES[1:])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
