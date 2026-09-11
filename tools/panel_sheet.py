"""Planche des pages du panneau de soin.

Le §13 demande une interface « au-dessus de sa tête », en carrés arrondis et
sans texte. Une interface sans libellés ne se relit pas : elle se **regarde**,
et cette planche met les cinq pages côte à côte pour ça.

    .venv/Scripts/python.exe -m tools.panel_sheet --out panneau.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FOND = "#C9CDD1"


class _FauxSession:
    """Session minimale : le panneau ne lit que `brain`, `name` et `appearance`."""

    def __init__(self, brain, name: str) -> None:
        self.brain = brain
        self.name = name
        self.appearance = {}
        self.inventory = []
        self.tokens = 0
        self.tokens_remaining = 25


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planche du panneau de soin")
    ap.add_argument("--name", default="Boulon")
    ap.add_argument("--out", type=Path, default=Path("panneau.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from pet.brain.brain import Brain
    from pet.brain.needs import Needs
    from pet.genome.generator import generate
    from pet.ui.panel import PAGES, WIDTH, CarePanel

    # Un état volontairement contrasté : deux besoins hauts, deux bas, pour que
    # les barres montrent à la fois leurs deux couleurs. Et un délai en cours,
    # pour qu'un bouton grisé soit visible sur la page d'interactions.
    brain = Brain(Needs(hunger=28.0, fun=88.0, energy=61.0, hygiene=9.0))
    brain.care("feed")
    # Un vrai génome : la page de personnalisation coche la couleur de
    # naissance quand rien n'a encore été choisi.
    genome = generate(8)
    session = _FauxSession(brain, args.name)
    session.tokens = 30
    session.inventory = ["bow", "cap"]
    session.appearance = {"hat": "cap"}
    panel = CarePanel(session, genome)

    # Aperçus de la boutique, rendus comme l'application les rend : la page
    # n'aurait aucun intérêt à juger avec des vignettes vides.
    from PySide6.QtGui import QPixmap

    from pet.geometry.builder import build
    from pet.render.context import RenderContext
    from pet.render.scene import Scene

    rc = RenderContext((128, 128), samples=4)
    scene = Scene(rc)
    cache = {}

    def apercu(emplacement, cle):
        if cle not in cache:
            scene.set_robot(build(genome,
                                  {emplacement: cle} if cle else None))
            rc.begin()
            scene.draw(yaw=0.0, pitch=0.14)
            px = rc.read_rgba()
            image = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                           QImage.Format.Format_RGBA8888_Premultiplied).copy()
            cache[cle] = QPixmap.fromImage(image)
        return cache[cle]

    panel.item_preview = apercu

    rendus = []
    for page in PAGES:
        panel.open_page(page)
        panel.resize(WIDTH, panel.height())
        if page == "name":
            panel._edit.setText(args.name)
        QApplication.processEvents()
        rendus.append((page, panel.grab().toImage()))

    marge, entete = 18, 24
    largeur = marge + len(PAGES) * (WIDTH + marge)
    hauteur = entete + max(i.height() for _, i in rendus) + 34

    sheet = QImage(largeur, hauteur, QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(QColor(FOND))
    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(12)
    painter.setFont(font)
    centre = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    for index, (page, image) in enumerate(rendus):
        x = marge + index * (WIDTH + marge)
        painter.drawImage(x, entete, image)
        painter.setPen(QColor("#33383C"))
        painter.drawText(QRectF(x, entete + image.height() + 8, WIDTH, 20),
                         centre, page)
    painter.end()

    ok = sheet.save(str(args.out))
    print("planche %s : %s (%dx%d) — %d pages, largeur de panneau %d px"
          % ("ecrite" if ok else "ECHEC", args.out, largeur, hauteur,
             len(PAGES), WIDTH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
