"""Planche des Deskys qui flottent sur le site vitrine (lot L16).

    python -m tools.site_deskys [nombre] [dossier]

Les particules du site ne sont pas des illustrations : ce sont des robots
**réellement générés** par le moteur du produit, avec les mêmes génomes, les
mêmes cosmétiques et le même rendu toon. C'est ce qui rend la page honnête —
un visiteur qui installe Desky obtiendra un robot de cette famille-là, pas une
version idéalisée dessinée pour la vitrine.

**Les couleurs sont étalées, pas tirées.** Le génome pèse le blanc cassé à 60 %
(« pastels rares », §7), ce qui est juste en jeu — un robot est d'abord un objet
neutre posé sur un bureau — mais donne un champ de particules monotone. On étale
donc les teintes de corps et d'accent, qui sont exactement celles que la page de
personnalisation propose : on ne montre rien qu'on ne puisse avoir.

**Toutes les cases ont la même taille**, rognée sur l'union des silhouettes.
Cadrer chaque robot séparément le ferait sautiller au moment où la particule
change de variante.
"""

from __future__ import annotations

import pathlib
import random
import sys
import time
from dataclasses import replace

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from pet.anim.layers import AnimContext, Animator
from pet.genome.generator import generate
from pet.genome.schema import ACCENT_COLORS, BODY_COLORS
from pet.geometry.builder import build
from pet.geometry.cosmetics import COSMETICS
from pet.render.context import RenderContext
from pet.render.scene import Scene

# Nombre de variantes et disposition de la planche.
COUNT = 50
COLS = 10

# Taille de rendu d'une case avant rognage. Généreuse : c'est le rognage qui
# décide de la taille finale, et un robot élancé coiffé d'un chapeau de fête a
# besoin de place avant qu'on sache où il s'arrête.
CELL_W, CELL_H = 170, 210
PAD = 2

# Pas d'animation avant capture. Les ressorts du regard (§10.2) doivent avoir
# convergé, sinon la pose dépend du hasard de l'instant où l'on déclenche.
SETTLE = 150

# Part des robots qui portent quelque chose. Assez pour qu'on remarque qu'on
# peut les habiller, assez peu pour que la variété du génome reste le sujet.
HAT_SHARE = 0.34
MOUSTACHE_SHARE = 0.16

# Graine du tirage des accessoires et des regards. Figée : la planche doit être
# reproductible, sinon on ne peut pas dire si une régénération a changé quelque
# chose d'autre que le hasard.
SEED = 1789

DEFAULT_DIR = pathlib.Path("docs/assets")


def render(count: int = COUNT) -> tuple[QImage, int, int]:
    """Rend la planche. Retourne l'image et la taille d'une case."""
    chapeaux = [c.key for c in COSMETICS if c.slot == "hat"]
    moustaches = [c.key for c in COSMETICS if c.slot == "moustache"]

    rc = RenderContext((CELL_W, CELL_H), samples=4)
    scene = Scene(rc)
    rng = random.Random(SEED)

    frames = []
    for i in range(count):
        graine = 1000 + i * 7
        costume = {
            "palette.body": list(BODY_COLORS)[i % len(BODY_COLORS)],
            "palette.accent": list(ACCENT_COLORS)[(i // 2) % len(ACCENT_COLORS)],
        }
        if rng.random() < HAT_SHARE:
            costume["hat"] = rng.choice(chapeaux)
        if rng.random() < MOUSTACHE_SHARE:
            costume["moustache"] = rng.choice(moustaches)

        robot = build(generate(graine), costume)
        scene.set_robot(robot)

        anim = Animator.for_robot(robot, seed=graine)
        ctx = AnimContext(look_offset=(rng.uniform(-2.4, 2.4),
                                       rng.uniform(-1.1, 1.1)))
        for _ in range(SETTLE):
            anim.update(1 / 60.0, ctx)

        # Un sur huit a les yeux fermés : dans un champ de particules, cela
        # suffit à faire croire que l'ensemble cligne.
        clin = 1.0 if rng.random() < 0.12 else 0.0
        scene.face_state = replace(anim.face, blink=clin)
        rc.begin()
        scene.draw(yaw=0.0, pitch=0.16, scale=1.0, time_s=SETTLE / 60.0, lift=0.0)
        frames.append(rc.read_rgba().copy())

    x0, y0, x1, y1 = _union_bbox(frames)
    w, h = x1 - x0, y1 - y0
    lignes = (count + COLS - 1) // COLS

    sheet = QImage(w * COLS, h * lignes, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor(0, 0, 0, 0))
    painter = QPainter(sheet)
    for index, frame in enumerate(frames):
        crop = np.ascontiguousarray(frame[y0:y1, x0:x1])
        img = QImage(crop.data, w, h, w * 4,
                     QImage.Format.Format_RGBA8888_Premultiplied)
        painter.drawImage((index % COLS) * w, (index // COLS) * h, img)
    painter.end()
    return sheet, w, h


def _union_bbox(frames) -> tuple[int, int, int, int]:
    """Boîte qui contient **toutes** les silhouettes, élargie de `PAD`.

    La marge n'est pas cosmétique : sans elle, l'antialiasing du contour d'une
    case bave sur la voisine quand le canvas rééchantillonne la planche.
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
    count = int(argv[1]) if len(argv) > 1 else COUNT
    sortie = pathlib.Path(argv[2]) if len(argv) > 2 else DEFAULT_DIR
    sortie.mkdir(parents=True, exist_ok=True)

    debut = time.perf_counter()
    sheet, w, h = render(count)
    chemin = sortie / "deskys.webp"
    if not sheet.save(str(chemin), "WEBP", 86):
        print("échec de l'écriture de %s" % chemin)
        return 1

    print("%s : %d x %d, case %d x %d, %d variantes, %.0f Ko, %.1f s"
          % (chemin, sheet.width(), sheet.height(), w, h, count,
             chemin.stat().st_size / 1024, time.perf_counter() - debut))
    print("cols=%d  cell=%dx%d  count=%d   <- à reporter dans docs/particles.js"
          % (COLS, w, h, count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
