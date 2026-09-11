"""Banc-titre : une animation décomposée en images, pour la revue au ralenti.

Critère d'acceptation du lot L4 : « aucune interpolation linéaire visible », et
cela se juge au ralenti, image par image. Les propriétés mécanisables — vitesse
non constante, bornes, étagement des ressorts — sont dans `tests/test_anim.py` ;
ce qui reste à l'œil se regarde ici.

    .venv/Scripts/python.exe -m tools.anim_strip --out mouvement.png
    .venv/Scripts/python.exe -m tools.anim_strip --what look --out suivi.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pet.anim.layers import ACTIONS, AnimContext, Animator
from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.scene import Scene

# Pas de simulation. Fin volontairement : on veut voir le mouvement, pas la
# cadence de rendu, et un pas fin rend les courbes lisibles au ralenti.
SIM_STEP = 1.0 / 120.0


def simulate(animator: Animator, scene: Scene, rc: RenderContext,
             duration: float, samples: int, ctx: AnimContext,
             action: str | None) -> list:
    """Joue `duration` secondes et retourne `samples` images réparties dessus."""
    if action is not None:
        animator.play(action)

    frames = []
    at = [duration * i / max(1, samples - 1) for i in range(samples)]
    t = 0.0
    next_sample = 0

    while next_sample < samples:
        while next_sample < samples and t >= at[next_sample] - SIM_STEP * 0.5:
            scene.face_state = animator.face
            rc.begin()
            scene.draw(yaw=0.0, pitch=0.14, time_s=t)
            frames.append((at[next_sample], rc.read_rgba().copy()))
            next_sample += 1
        animator.update(SIM_STEP, ctx)
        t += SIM_STEP
    return frames


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="banc-titre d'animation")
    ap.add_argument("--what", default="actions",
                    choices=("actions", "idle", "look", "breath"),
                    help="actions : une ligne par action ; look : balayage du curseur")
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--cell", type=int, default=150)
    ap.add_argument("--samples", type=int, default=9)
    ap.add_argument("--bg", type=str, default="#D7D7D3")
    ap.add_argument("--out", type=Path, default=Path("mouvement.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    app = QGuiApplication.instance() or QGuiApplication([])

    rc = RenderContext((args.cell, args.cell), samples=4)
    scene = Scene(rc)
    robot = build(generate(args.seed))
    scene.set_robot(robot)
    print(f"rendu sur {rc.info['renderer']}")

    # Chaque ligne : (libellé, durée, contexte, action)
    rows: list[tuple[str, float, AnimContext, str | None]] = []
    if args.what == "actions":
        for name, curve in ACTIONS.items():
            rows.append((name, curve.duration * 1.05, AnimContext(), name))
    elif args.what == "idle":
        for start in (0.0, 8.0, 16.0):
            rows.append((f"idle {start:.0f}-{start + 6:.0f} s", 6.0,
                         AnimContext(), None))
    elif args.what == "breath":
        rows.append(("respiration, un cycle", 3.7, AnimContext(), None))
    else:
        for label, offset in (("curseur a droite", (2.6, 0.0)),
                              ("curseur a gauche", (-2.6, 0.0)),
                              ("curseur en haut", (0.0, 1.8)),
                              ("curseur tres a droite", (7.0, 0.0)),
                              ("retour au repos", None)):
            rows.append((label, 1.6, AnimContext(look_offset=offset), None))

    label_w, label_h = 190, 22
    sheet = QImage(label_w + args.samples * args.cell,
                   len(rows) * (args.cell + label_h),
                   QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(QColor(args.bg))
    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(14)
    painter.setFont(font)

    for r, (label, duration, ctx, action) in enumerate(rows):
        # `for_robot` repart de la pose de repos : sans cela, chaque ligne
        # hériterait de la posture finale de la précédente.
        animator = Animator.for_robot(robot, seed=args.seed)
        if args.what == "look":
            # Part du repos, puis vise : on veut voir l'approche, pas l'arrivée.
            for _ in range(60):
                animator.update(SIM_STEP, AnimContext())
        elif args.what == "idle":
            avance = float(label.split()[1].split("-")[0])
            for _ in range(int(avance / SIM_STEP)):
                animator.update(SIM_STEP, AnimContext())

        frames = simulate(animator, scene, rc, duration, args.samples, ctx, action)
        y = r * (args.cell + label_h)

        painter.setPen(QColor("#2A2A28"))
        painter.drawText(QRect(6, y + args.cell // 2 - 10, label_w - 12, 22),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         label)
        for i, (t, px) in enumerate(frames):
            x = label_w + i * args.cell
            tile = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                          QImage.Format.Format_RGBA8888_Premultiplied)
            painter.drawImage(x, y, tile)
            painter.setPen(QColor("#6A6A66"))
            painter.drawText(QRect(x, y + args.cell - 4, args.cell, label_h),
                             int(Qt.AlignmentFlag.AlignHCenter
                                 | Qt.AlignmentFlag.AlignVCenter),
                             f"{t:.2f} s")
        print(f"  {label:26s} {duration:5.2f} s -> {len(frames)} images")

    painter.end()
    ok = sheet.save(str(args.out))
    print(f"\nbanc-titre {'ecrit' if ok else 'ECHEC'} : {args.out} "
          f"({sheet.width()}x{sheet.height()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
