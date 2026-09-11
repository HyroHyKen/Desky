"""Étude de mouvement : le pet composé à sa position réelle, image par image.

Critère d'acceptation du lot L5b : « aucun mouvement linéaire visible », et
c'est un jugement qui se rend au ralenti. Les planches existantes centrent le
robot dans sa vignette, donc l'arc du saut y est invisible — la seule façon de
le voir est de coller le pet à sa position d'écran sur une frise unique.

Le sol est tracé, et la frise traverse volontairement une frontière de moniteur :
c'est là que le pas de sol se voit, ou ne se voit pas.

    .venv/Scripts/python.exe -m tools.loco_strip --gait hop --out saut.png
    .venv/Scripts/python.exe -m tools.loco_strip --gait glide --out glisse.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pet.anim.layers import AnimContext, Animator
from pet.anim.locomotion import Ground, Locomotion, Terrain
from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.scene import Scene

SIM_STEP = 1.0 / 120.0

# Terrain synthétique reproduisant le pas de sol réel de la machine de dev :
# deux écrans dont les zones de travail diffèrent de 130 px.
FLOOR_LEFT = 300.0
FLOOR_RIGHT = 170.0
BOUNDARY = 1100.0


def terrain_for(pet_w: int, pet_h: int) -> Terrain:
    """Deux ecrans **adjacents** : ils forment donc une seule bande."""
    return Terrain.from_grounds([
        Ground("gauche", 0.0, BOUNDARY, FLOOR_LEFT),
        Ground("droite", BOUNDARY, 2200.0, FLOOR_RIGHT),
    ], pet_w)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="étude de mouvement du pet")
    ap.add_argument("--gait", default="hop", choices=("hop", "glide"))
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--pet", type=int, default=150, help="taille du pet")
    ap.add_argument("--from-x", type=float, default=260.0)
    ap.add_argument("--to-x", type=float, default=1700.0)
    ap.add_argument("--every", type=int, default=7,
                    help="une image gardée sur N (pas de simulation 1/120 s)")
    ap.add_argument("--bg", type=str, default="#D7D7D3")
    ap.add_argument("--out", type=Path, default=Path("mouvement_loco.png"))
    args = ap.parse_args(argv)

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
    app = QGuiApplication.instance() or QGuiApplication([])

    pet = args.pet
    rc = RenderContext((pet, pet), samples=4)
    scene = Scene(rc)
    robot = build(generate(args.seed))
    scene.set_robot(robot)
    animator = Animator.for_robot(robot, seed=args.seed)

    terrain = terrain_for(pet, pet)
    loco = Locomotion(terrain, pet, pet, x=args.from_x, gait=args.gait,
                      seed=args.seed)
    loco.set_home(args.from_x)
    if not loco.go_to(args.to_x):
        print("cible refusée")
        return 1

    print(f"rendu sur {rc.info['renderer']} — démarche {args.gait}")

    # Simulation complète d'abord : on a besoin de l'étendue avant de peindre.
    frames: list[tuple[float, float, float, object]] = []
    t, i = 0.0, 0
    while loco.travelling and t < 30.0:
        channels = loco.update(SIM_STEP)
        animator.update(SIM_STEP, AnimContext(), extra=channels)
        if i % args.every == 0:
            scene.face_state = animator.face
            rc.begin()
            scene.draw(yaw=0.0, pitch=0.14, time_s=t)
            frames.append((t, loco.window_x, loco.window_y,
                           rc.read_rgba().copy()))
        t += SIM_STEP
        i += 1

    if not frames:
        print("aucune image")
        return 1

    xs = [f[1] for f in frames]
    ys = [f[2] for f in frames]
    marge = 20
    x0, y0 = min(xs) - marge, min(ys) - marge
    largeur = int(max(xs) - x0 + pet + marge)
    hauteur = int(max(ys) - y0 + pet + marge + 26)

    sheet = QImage(largeur, hauteur, QImage.Format.Format_RGBA8888_Premultiplied)
    sheet.fill(QColor(args.bg))
    painter = QPainter(sheet)

    # Sol : deux traits, et la frontière entre les deux moniteurs.
    painter.setPen(QPen(QColor("#A8A8A2"), 2))
    for ground in terrain.grounds:
        y = int(ground.floor_y - y0 + pet)
        painter.drawLine(int(max(0.0, ground.x_left - x0)), y,
                         int(ground.x_right - x0), y)
    painter.setPen(QPen(QColor("#C0605A"), 1, Qt.PenStyle.DashLine))
    painter.drawLine(int(BOUNDARY - x0), 0, int(BOUNDARY - x0), hauteur - 26)

    for index, (t, wx, wy, px) in enumerate(frames):
        tile = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                      QImage.Format.Format_RGBA8888_Premultiplied)
        # Les images anciennes sont estompées : la frise se lit alors dans le
        # sens du mouvement, comme une chronophotographie.
        painter.setOpacity(0.30 + 0.70 * (index / max(1, len(frames) - 1)))
        painter.drawImage(int(wx - x0), int(wy - y0), tile)

    painter.setOpacity(1.0)
    font = QFont()
    font.setPixelSize(13)
    painter.setFont(font)
    painter.setPen(QColor("#2A2A28"))
    painter.drawText(
        QRect(8, hauteur - 24, largeur - 16, 20),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        f"démarche {args.gait} — {t:.2f} s, {loco.hops} sauts, "
        f"{abs(args.to_x - args.from_x):.0f} px — trait rouge : frontière de "
        f"moniteur, sols à {FLOOR_LEFT:.0f} et {FLOOR_RIGHT:.0f}")
    painter.end()

    ok = sheet.save(str(args.out))
    print(f"frise {'ecrite' if ok else 'ECHEC'} : {args.out} "
          f"({largeur}x{hauteur}) — {len(frames)} images sur {t:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
