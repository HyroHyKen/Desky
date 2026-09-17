"""Planche du robot qui suit la souris sur le site (lot L16).

    python -m tools.site_hero [graine] [dossier]

Le robot du site n'est pas une illustration : c'est le robot du produit, rendu
hors écran, dans les poses que prend son regard quand on bouge la souris. La
page rejoue la planche au canvas et lui applique la démarche du lot L5b — mêmes
durées, mêmes amplitudes, même écrasement. Ce n'est donc pas une imitation du
robot, c'est le robot.

**Une pose par direction du regard.** Les trois ressorts étagés du §10.2 — les
pupilles vives, la tête qui suit, le corps qui traîne — sont laissés converger
pour chaque case, puis capturés. Interpoler entre deux cases à l'exécution
serait plus léger, mais les ressorts ne sont pas linéaires : on obtiendrait des
poses que le robot ne prend jamais.

**L'animateur est recréé à chaque pose et avancé du même nombre de pas.**
Respiration et balancement sont alors en phase identique sur toute la planche.
Sans cela le robot sursauterait en passant d'une case à la voisine.

**Deux étages de clignement** — ouvert et fermé — pour chaque pose. Un
clignement à deux images suffit à l'œil dès lors qu'il est bref, et doubler la
planche coûte moins cher que de rendre une troisième position de paupière qu'on
ne voit qu'un vingtième de seconde.
"""

from __future__ import annotations

import pathlib
import sys
import time
from dataclasses import replace

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from pet.anim.layers import AnimContext, Animator
from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.scene import Scene

# Graine du robot vedette. Figée : c'est le visage du produit sur sa page, il ne
# doit pas changer d'une régénération à l'autre.
SEED = 8

# Grille du regard. Neuf colonnes parce que la souris se déplace surtout
# horizontalement sur une page ; trois rangées suffisent en hauteur.
COLS = 9
ROWS = 3

# Amplitude du regard, en hauteurs de robot. Au-delà, l'intérêt décroît de
# lui-même (`LOOK_INTEREST_RANGE`) et les poses extrêmes se ressemblent.
DX = 2.4
DY = 1.2

CELL_W, CELL_H = 220, 280
PAD = 2
SETTLE = 180

DEFAULT_DIR = pathlib.Path("docs/assets")


def _offsets():
    for row in range(ROWS):
        dy = -DY + 2 * DY * (row / (ROWS - 1)) if ROWS > 1 else 0.0
        for col in range(COLS):
            dx = -DX + 2 * DX * (col / (COLS - 1)) if COLS > 1 else 0.0
            yield row, col, dx, dy


def render(seed: int = SEED) -> tuple[QImage, int, int]:
    rc = RenderContext((CELL_W, CELL_H), samples=4)
    scene = Scene(rc)
    robot = build(generate(seed), {})
    scene.set_robot(robot)

    frames: dict[tuple[int, int, int], np.ndarray] = {}
    for row, col, dx, dy in _offsets():
        anim = Animator.for_robot(robot, seed=seed)
        ctx = AnimContext(look_offset=(dx, dy))
        for _ in range(SETTLE):
            anim.update(1 / 60.0, ctx)
        for etage, niveau in ((0, 0.0), (1, 1.0)):
            scene.face_state = replace(anim.face, blink=niveau)
            rc.begin()
            scene.draw(yaw=0.0, pitch=0.16, scale=1.0, time_s=SETTLE / 60.0,
                       lift=0.0)
            frames[(etage, row, col)] = rc.read_rgba().copy()

    x0, y0, x1, y1 = _union_bbox(frames.values())
    w, h = x1 - x0, y1 - y0

    sheet = QImage(w * COLS, h * ROWS * 2, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor(0, 0, 0, 0))
    painter = QPainter(sheet)
    for (etage, row, col), frame in frames.items():
        crop = np.ascontiguousarray(frame[y0:y1, x0:x1])
        img = QImage(crop.data, w, h, w * 4,
                     QImage.Format.Format_RGBA8888_Premultiplied)
        painter.drawImage(col * w, (etage * ROWS + row) * h, img)
    painter.end()
    return sheet, w, h


def _union_bbox(frames) -> tuple[int, int, int, int]:
    """Boîte qui contient toutes les poses, élargie de `PAD`.

    Commune à toute la planche : cadrer chaque pose séparément déplacerait le
    robot d'un pixel ou deux à chaque changement de case, ce qui se lit comme un
    tremblement.
    """
    x0, y0, x1, y1 = CELL_W, CELL_H, 0, 0
    for frame in frames:
        mask = frame[:, :, 3] > 6
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        if rows.size:
            y0, y1 = min(y0, int(rows[0])), max(y1, int(rows[-1]))
            x0, x1 = min(x0, int(cols[0])), max(x1, int(cols[-1]))
    return (max(0, x0 - PAD), max(0, y0 - PAD),
            min(CELL_W, x1 + 1 + PAD), min(CELL_H, y1 + 1 + PAD))


def main(argv: list[str]) -> int:
    seed = int(argv[1]) if len(argv) > 1 else SEED
    sortie = pathlib.Path(argv[2]) if len(argv) > 2 else DEFAULT_DIR
    sortie.mkdir(parents=True, exist_ok=True)

    debut = time.perf_counter()
    sheet, w, h = render(seed)
    chemin = sortie / "hero.webp"
    if not sheet.save(str(chemin), "WEBP", 90):
        print("échec de l'écriture de %s" % chemin)
        return 1

    print("%s : %d x %d, %.0f Ko, %.1f s"
          % (chemin, sheet.width(), sheet.height(),
             chemin.stat().st_size / 1024, time.perf_counter() - debut))
    print("COLS=%d  ROWS=%d  CELL=%dx%d  DX=%.1f  DY=%.1f"
          "   <- à reporter dans docs/hero.js" % (COLS, ROWS, w, h, DX, DY))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
