"""Génère les sprites d'objets par défaut, en PNG.

Ces onze images sont des **bouche-trous**, pas l'art final : elles existent pour
que le mécanisme d'objets soit jouable tout de suite, et pour servir de gabarit
à celles qui les remplaceront. Le code ne les connaît pas individuellement — il
découvre le dossier par préfixe — donc écraser un fichier suffit à changer un
objet, et en ajouter un suffit à enrichir la variété.

**Le contrat de composition, à respecter par tout remplaçant :**

- 256 × 256, RGBA, fond transparent ;
- le **bas du dessin est la ligne de contact avec le sol**. Une marge vide en
  dessous ferait flotter l'objet, puisque c'est le bord bas de l'image qui est
  posé sur le sol de la zone de travail ;
- centré horizontalement, quelques pixels de marge transparente sur les côtés
  pour que le contour ne soit pas rogné à la mise à l'échelle ;
- aplats et contour sombre, comme le rendu toon : l'objet doit avoir l'air
  d'appartenir au même monde que le robot.

    .venv/Scripts/python.exe -m tools.make_items
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SIDE = 256
GROUND = 247.0          # ligne de contact, laissée au trait de contour
STROKE = 9.0

PALETTE = {
    "ink": "#2A211A",
    "metal": "#BAC3CB",
    "metal_dark": "#8D98A2",
    "brass": "#D8A957",
    "copper": "#C4794A",
    "green": "#5FAE7C",
    "blue": "#6E9BD1",
    "red": "#D1655C",
    "cream": "#EFE3CE",
    "glass": "#DCE8EF",
    "dark": "#4A5560",
}


def _painter(image):
    from PySide6.QtGui import QPainter
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return p


def _draw(painter, path, fill: str) -> None:
    """Aplat plus contour, les deux d'un coup. C'est tout le style toon."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPen
    pen = QPen(QColor(PALETTE["ink"]), STROKE)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QColor(fill))
    painter.drawPath(path)


def _poly(points):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.moveTo(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    path.closeSubpath()
    return path


def _rounded(x, y, w, h, r):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _ellipse(x, y, w, h):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.addEllipse(QRectF(x, y, w, h))
    return path


def _hexagon(cx, cy, r):
    import math
    return _poly([(cx + r * math.cos(math.radians(60 * i - 30)),
                   cy + r * math.sin(math.radians(60 * i - 30)))
                  for i in range(6)])


# --- les onze objets --------------------------------------------------------


def food_bolt(p) -> None:
    """Boulon vu de trois quarts : tête hexagonale et filetage."""
    _draw(p, _rounded(104.0, 96.0, 48.0, GROUND - 96.0, 10.0), PALETTE["metal"])
    for y in (140.0, 176.0, 212.0):
        _draw(p, _rounded(100.0, y, 56.0, 14.0, 7.0), PALETTE["metal_dark"])
    _draw(p, _hexagon(128.0, 78.0, 64.0), PALETTE["metal"])


def food_gear(p) -> None:
    """Pignon : une couronne et huit dents."""
    import math
    for i in range(8):
        a = math.radians(45 * i)
        cx = 128.0 + 74.0 * math.cos(a)
        cy = 150.0 + 74.0 * math.sin(a)
        _draw(p, _rounded(cx - 22.0, cy - 22.0, 44.0, 44.0, 8.0),
              PALETTE["metal_dark"])
    _draw(p, _ellipse(48.0, 70.0, 160.0, 160.0), PALETTE["metal"])
    _draw(p, _ellipse(104.0, 126.0, 48.0, 48.0), PALETTE["dark"])


def food_oilcan(p) -> None:
    """Burette : un corps trapu et un bec long."""
    _draw(p, _poly([(150.0, 120.0), (232.0, 62.0), (240.0, 78.0),
                    (160.0, 140.0)]), PALETTE["metal_dark"])
    _draw(p, _poly([(52.0, GROUND), (204.0, GROUND), (196.0, 118.0),
                    (60.0, 118.0)]), PALETTE["brass"])
    _draw(p, _rounded(96.0, 62.0, 64.0, 60.0, 12.0), PALETTE["metal"])


def food_sparkplug(p) -> None:
    """Bougie : céramique claire, écrou hexagonal, électrode."""
    _draw(p, _rounded(112.0, GROUND - 52.0, 32.0, 52.0, 6.0),
          PALETTE["metal_dark"])
    _draw(p, _hexagon(128.0, GROUND - 78.0, 50.0), PALETTE["metal"])
    _draw(p, _rounded(96.0, 52.0, 64.0, 128.0, 16.0), PALETTE["cream"])
    _draw(p, _rounded(108.0, 24.0, 40.0, 44.0, 14.0), PALETTE["metal"])


def food_fuse(p) -> None:
    """Fusible : tube de verre, embouts métalliques, filament."""
    _draw(p, _rounded(24.0, GROUND - 92.0, 208.0, 92.0, 44.0), PALETTE["glass"])
    _draw(p, _rounded(24.0, GROUND - 92.0, 46.0, 92.0, 18.0), PALETTE["metal"])
    _draw(p, _rounded(186.0, GROUND - 92.0, 46.0, 92.0, 18.0), PALETTE["metal"])
    _draw(p, _rounded(76.0, GROUND - 56.0, 104.0, 14.0, 7.0), PALETTE["copper"])


def food_chip(p) -> None:
    """Puce : un carré sombre et ses pattes."""
    for i in range(4):
        x = 62.0 + i * 36.0
        _draw(p, _rounded(x, GROUND - 38.0, 22.0, 38.0, 6.0), PALETTE["metal"])
        _draw(p, _rounded(x, 74.0, 22.0, 34.0, 6.0), PALETTE["metal"])
    _draw(p, _rounded(48.0, 96.0, 160.0, 116.0, 16.0), PALETTE["dark"])
    _draw(p, _ellipse(68.0, 116.0, 26.0, 26.0), PALETTE["metal_dark"])


def toy_ball(p) -> None:
    """Balle : une sphère et sa bande."""
    _draw(p, _ellipse(32.0, GROUND - 190.0, 190.0, 190.0), PALETTE["red"])
    from PySide6.QtGui import QPainterPath
    bande = QPainterPath()
    bande.moveTo(40.0, GROUND - 118.0)
    bande.quadTo(128.0, GROUND - 70.0, 214.0, GROUND - 118.0)
    bande.quadTo(128.0, GROUND - 150.0, 40.0, GROUND - 118.0)
    bande.closeSubpath()
    _draw(p, bande, PALETTE["cream"])


def toy_cube(p) -> None:
    """Cube en perspective cavalière : face, dessus, côté."""
    _draw(p, _poly([(40.0, GROUND), (168.0, GROUND), (168.0, 118.0),
                    (40.0, 118.0)]), PALETTE["blue"])
    _draw(p, _poly([(40.0, 118.0), (168.0, 118.0), (216.0, 74.0),
                    (88.0, 74.0)]), PALETTE["glass"])
    _draw(p, _poly([(168.0, GROUND), (216.0, GROUND - 44.0), (216.0, 74.0),
                    (168.0, 118.0)]), PALETTE["dark"])


def toy_spring(p) -> None:
    """Ressort : quatre spires empilées."""
    for i in range(4):
        y = GROUND - 46.0 - i * 44.0
        _draw(p, _ellipse(46.0, y, 164.0, 60.0), PALETTE["metal"])


def clean_sponge(p) -> None:
    """Éponge : un pavé arrondi, ses alvéoles, et sa face abrasive."""
    _draw(p, _rounded(30.0, GROUND - 120.0, 196.0, 120.0, 22.0),
          PALETTE["green"])
    _draw(p, _rounded(30.0, GROUND - 120.0, 196.0, 44.0, 20.0),
          PALETTE["brass"])
    for cx, cy in ((78.0, GROUND - 48.0), (128.0, GROUND - 62.0),
                   (176.0, GROUND - 44.0)):
        _draw(p, _ellipse(cx - 13.0, cy - 13.0, 26.0, 26.0), PALETTE["dark"])


def clean_spray(p) -> None:
    """Vaporisateur : flacon, gâchette, buse."""
    _draw(p, _rounded(62.0, 122.0, 132.0, GROUND - 122.0, 18.0),
          PALETTE["glass"])
    _draw(p, _rounded(78.0, 168.0, 100.0, 52.0, 8.0), PALETTE["blue"])
    _draw(p, _rounded(106.0, 74.0, 44.0, 56.0, 8.0), PALETTE["metal"])
    _draw(p, _poly([(106.0, 74.0), (150.0, 74.0), (150.0, 44.0),
                    (46.0, 44.0), (46.0, 66.0), (106.0, 66.0)]),
          PALETTE["metal_dark"])


ITEMS = {
    "food_bolt": food_bolt,
    "food_gear": food_gear,
    "food_oilcan": food_oilcan,
    "food_sparkplug": food_sparkplug,
    "food_fuse": food_fuse,
    "food_chip": food_chip,
    "toy_ball": toy_ball,
    "toy_cube": toy_cube,
    "toy_spring": toy_spring,
    "clean_sponge": clean_sponge,
    "clean_spray": clean_spray,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="sprites d'objets par défaut")
    ap.add_argument("--out", type=Path,
                    default=Path("pet") / "assets" / "items")
    ap.add_argument("--sheet", type=Path, default=None,
                    help="PNG de contrôle réunissant les onze objets")
    args = ap.parse_args(argv)

    from PySide6.QtGui import QColor, QGuiApplication, QImage
    QGuiApplication.instance() or QGuiApplication([])

    args.out.mkdir(parents=True, exist_ok=True)
    images = []
    for nom, dessin in ITEMS.items():
        image = QImage(SIDE, SIDE, QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = _painter(image)
        dessin(painter)
        painter.end()
        chemin = args.out / (nom + ".png")
        image.save(str(chemin))
        images.append((nom, image))
    print("%d sprites écrits dans %s" % (len(images), args.out))

    if args.sheet is not None:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QFont, QPainter
        tuile = 150
        largeur = 14 + len(images) * (tuile + 14)
        sheet = QImage(largeur, tuile + 46,
                       QImage.Format.Format_RGBA8888_Premultiplied)
        sheet.fill(QColor("#9AA7B2"))
        painter = QPainter(sheet)
        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        for index, (nom, image) in enumerate(images):
            x = 14 + index * (tuile + 14)
            painter.drawImage(x, 10, image.scaled(
                tuile, tuile, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            painter.setPen(QColor("#14202A"))
            painter.drawText(QRectF(x, tuile + 16, tuile, 20),
                             int(Qt.AlignmentFlag.AlignHCenter), nom)
        # Ligne de sol : elle doit affleurer le bas de chaque dessin.
        painter.setPen(QColor("#D1655C"))
        painter.drawLine(0, 10 + tuile, largeur, 10 + tuile)
        painter.end()
        sheet.save(str(args.sheet))
        print("planche de contrôle :", args.sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
