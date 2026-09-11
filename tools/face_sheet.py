"""Planche du visage : les expressions et les commandes du CDC §9.

Critère d'acceptation du lot L3 : « visage pilotable par uniformes ». Ce
jugement est visuel — chaque vignette n'est qu'un jeu de valeurs différent
envoyé au **même** shader, sans une seule branche côté CPU.

    .venv/Scripts/python.exe -m tools.face_sheet --out visages.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.face import EXPRESSIONS, FaceState
from pet.render.scene import Scene


def cases() -> list[tuple[str, FaceState, float]]:
    """(libellé, état, temps). Le temps ne sert qu'au balayage du glitch."""
    out: list[tuple[str, FaceState, float]] = []
    # Instant choisi pour que l'enveloppe du balayage soit à son maximum :
    # elle pulse, et l'échantillonner sur un de ses zéros masquait le glitch.
    for name, state in EXPRESSIONS.items():
        out.append((name, state, 0.42))

    # Clignement : la même expression à quatre instants de sa course, pour
    # vérifier qu'un œil fermé devient un trait et ne disparaît pas.
    for value in (0.0, 0.45, 0.80, 1.0):
        out.append((f"clignement {value:.2f}", FaceState(blink=value), 0.0))

    # Regard : les pupilles se déplacent dans la dalle, la dalle ne bouge pas.
    for label, gx, gy in (("regard gauche", -1.0, 0.0), ("regard droite", 1.0, 0.0),
                          ("regard haut", 0.0, 1.0), ("regard bas", 0.0, -1.0)):
        out.append((label, FaceState(pupil_scale=1.05).with_gaze(gx, gy), 0.0))

    # Transition : une expression est une cible, une transition un mélange.
    neutre, joyeux = EXPRESSIONS["neutre"], EXPRESSIONS["joyeux"]
    for t in (0.25, 0.5, 0.75):
        out.append((f"neutre→joyeux {t:.2f}", neutre.lerp(joyeux, t), 0.0))

    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="planche des expressions du visage")
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--cell", type=int, default=210)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=0.06)
    ap.add_argument("--bg", type=str, default="#D7D7D3")
    ap.add_argument("--out", type=Path, default=Path("visages.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    app = QGuiApplication.instance() or QGuiApplication([])

    rc = RenderContext((args.cell, args.cell), samples=4)
    scene = Scene(rc)
    scene.set_robot(build(generate(args.seed)))
    print(f"rendu sur {rc.info['renderer']}")

    items = cases()
    label_h = 26
    rows = (len(items) + args.cols - 1) // args.cols
    sheet = QImage(args.cols * args.cell, rows * (args.cell + label_h),
                   QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(QColor(args.bg))

    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(14)
    painter.setFont(font)

    for i, (label, state, t) in enumerate(items):
        scene.face_state = state
        rc.begin()
        scene.draw(yaw=args.yaw, pitch=args.pitch, time_s=t)
        px = rc.read_rgba().copy()

        cx = (i % args.cols) * args.cell
        cy = (i // args.cols) * (args.cell + label_h)
        tile = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                      QImage.Format.Format_RGBA8888_Premultiplied)
        painter.drawImage(cx, cy, tile)
        painter.setPen(QColor("#2A2A28"))
        painter.drawText(QRect(cx, cy + args.cell - 4, args.cell, label_h),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                         label)

    painter.end()
    ok = sheet.save(str(args.out))
    print(f"planche {'ecrite' if ok else 'ECHEC'} : {args.out} "
          f"({sheet.width()}x{sheet.height()}) — {len(items)} vignettes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
