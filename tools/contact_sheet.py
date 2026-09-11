"""Planche de contact : N graines rendues côte à côte.

Critère d'acceptation du lot L2 : « 20 graines tirées produisent 20 robots
visuellement distincts et tous viables ». Ce jugement est visuel et ne peut pas
être un test unitaire — d'où cet outil, qui produit la planche à regarder. Les
propriétés vérifiables mécaniquement (déterminisme, viabilité, budget de temps)
sont, elles, dans `tests/`.

    .venv/Scripts/python.exe -m tools.contact_sheet --seeds 20 --out planche.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.scene import Scene


def render_one(rc: RenderContext, scene: Scene, seed: int,
               yaw: float, pitch: float) -> tuple[np.ndarray, dict]:
    genome = generate(seed)
    robot = build(genome)
    scene.set_robot(robot)
    rc.begin()
    scene.draw(yaw=yaw, pitch=pitch)
    return rc.read_rgba().copy(), {
        "seed": seed,
        "ear": genome["ear.type"],
        "body": genome["palette.body"],
        "accent": genome["palette.accent"],
        "ratio": robot.dims.head_width / robot.dims.body_width,
        "attempts": genome["attempts"],
        "build_ms": robot.build_ms,
        "tris": robot.triangle_count,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planche de contact du génome")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--cell", type=int, default=200, help="côté d'une vignette")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--yaw", type=float, default=0.42)
    ap.add_argument("--pitch", type=float, default=0.12)
    ap.add_argument("--out", type=Path, default=Path("planche_genomes.png"))
    args = ap.parse_args(argv)

    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    app = QGuiApplication.instance() or QGuiApplication([])

    rc = RenderContext((args.cell, args.cell), samples=4)
    scene = Scene(rc)
    print(f"rendu sur {rc.info['renderer']}")

    rows = (args.seeds + args.cols - 1) // args.cols
    sheet = QImage(args.cols * args.cell, rows * args.cell,
                   QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(0x00000000)

    painter = QPainter(sheet)
    infos = []
    for i in range(args.seeds):
        seed = args.first_seed + i
        pixels, info = render_one(rc, scene, seed, args.yaw, args.pitch)
        infos.append(info)
        tile = QImage(pixels.data, pixels.shape[1], pixels.shape[0],
                      pixels.shape[1] * 4,
                      QImage.Format.Format_RGBA8888_Premultiplied)
        painter.drawImage((i % args.cols) * args.cell,
                          (i // args.cols) * args.cell, tile)
    painter.end()

    ok = sheet.save(str(args.out))
    print(f"planche {'ecrite' if ok else 'ECHEC'} : {args.out} "
          f"({sheet.width()}x{sheet.height()})")

    print()
    print(f"{'seed':>5} {'oreilles':9} {'corps':12} {'accent':10} "
          f"{'tete/corps':>10} {'tirages':>8} {'tris':>6} {'ms':>6}")
    for info in infos:
        print(f"{info['seed']:5d} {info['ear']:9} {info['body']:12} {info['accent']:10} "
              f"{info['ratio']:10.2f} {info['attempts']:8d} {info['tris']:6d} "
              f"{info['build_ms']:6.2f}")

    ears = {}
    for info in infos:
        ears[info["ear"]] = ears.get(info["ear"], 0) + 1
    print()
    print("repartition des oreilles :", dict(sorted(ears.items())))
    print(f"tirages par genome : moyenne {sum(i['attempts'] for i in infos)/len(infos):.2f}")
    print(f"construction : max {max(i['build_ms'] for i in infos):.2f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
