"""Icône de l'application : un robot qui vous regarde droit dans les yeux.

Rendue par le moteur du produit lui-même, pas dessinée à côté. L'icône est donc
exacte par construction — mêmes proportions, même toon, même contour — et elle
suivra toute évolution du rendu sans qu'on ait à la refaire.

**Un `.ico` est un lot de tailles, pas une image redimensionnée.** Windows pioche
la définition qui lui convient selon le contexte — 16 px dans la barre des
tâches, 32 dans l'explorateur, 256 dans les grandes vignettes — et laisser le
système réduire un seul grand rendu donne une bouillie à 16 px. Chaque taille
est donc **rendue à sa résolution**, ce qui coûte quelques millisecondes et
sauve la lisibilité aux petites tailles.

Le fichier est écrit à la main. Qt sait produire un `.ico`, mais seulement à
partir d'une image unique : le format ICO tel qu'il est assemblé ici — un
en-tête, un répertoire, puis des PNG concaténés — tient en trente lignes et
donne le contrôle sur le jeu de tailles.

    .venv/Scripts/python.exe -m tools.make_icon
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from pet.genome.generator import generate
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.scene import Scene

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Tailles embarquées. 256 est la plus grande que Windows lit dans un ICO, et
# elle est stockée en PNG ; les autres couvrent les usages courants.
SIZES = (16, 24, 32, 48, 64, 128, 256)

# Cadrage de l'icône. Le bandeau de bulle n'a pas lieu d'être ici — il n'y a pas
# de bulle — et le supprimer rend le robot **plus grand dans le carré**, ce qui
# compte beaucoup à seize pixels.
HEADROOM = 0.0

# Il regarde droit devant : aucun lacet, et juste assez de tangage pour qu'on
# voie le dessus de la tête et que la silhouette ne soit pas plate.
YAW = 0.0
PITCH = 0.10

# Graine du robot de l'icône. Choisie pour sa silhouette, et **figée** : c'est
# le visage du produit, il ne doit pas changer d'une version à l'autre.
MASCOT_SEED = 8


def render_sizes(seed: int, sizes=SIZES, samples: int = 8) -> list:
    """Rend le robot à chaque taille demandée. Retourne des QImage."""
    from PySide6.QtGui import QImage

    images = []
    robot = build(generate(seed))
    for side in sizes:
        rc = RenderContext((side * 2, side * 2), samples=samples)
        scene = Scene(rc)
        scene.headroom = HEADROOM
        scene.set_robot(robot)
        rc.begin()
        scene.draw(yaw=YAW, pitch=PITCH)
        px = rc.read_rgba()
        grand = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                       QImage.Format.Format_RGBA8888_Premultiplied).copy()
        # Rendu au double puis réduit : l'anti-aliasing du contour est bien
        # meilleur ainsi qu'en rendant directement à seize pixels, où le trait
        # tombe sous le pixel.
        from PySide6.QtCore import Qt
        images.append(grand.scaled(side, side,
                                   Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation))
        scene.release()
        rc.release()
    return images


def png_bytes(image) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray

    data = QByteArray()
    tampon = QBuffer(data)
    tampon.open(QBuffer.OpenModeFlag.WriteOnly)
    # Converti hors prémultiplié : le PNG stocke des couleurs droites, et
    # laisser du prémultiplié y assombrit tous les bords translucides.
    from PySide6.QtGui import QImage
    image.convertToFormat(QImage.Format.Format_RGBA8888).save(tampon, "PNG")
    tampon.close()
    return bytes(data)


def write_ico(path: Path, images) -> None:
    """Assemble un `.ico` : en-tête, répertoire, puis les PNG.

    Le champ de taille vaut 0 pour 256, comme le format l'exige — un octet ne
    peut pas porter 256.
    """
    entrees = [png_bytes(image) for image in images]
    tete = struct.pack("<HHH", 0, 1, len(entrees))
    decalage = len(tete) + 16 * len(entrees)

    repertoire = b""
    for image, donnees in zip(images, entrees):
        cote = image.width() % 256
        repertoire += struct.pack("<BBBBHHII", cote, cote, 0, 0, 1, 32,
                                  len(donnees), decalage)
        decalage += len(donnees)

    path.write_bytes(tete + repertoire + b"".join(entrees))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="icône de l'application")
    ap.add_argument("--seed", type=int, default=MASCOT_SEED)
    ap.add_argument("--out", type=Path,
                    default=Path("packaging") / "desky.ico")
    ap.add_argument("--preview", type=Path, default=None,
                    help="PNG de contrôle montrant toutes les tailles")
    args = ap.parse_args(argv)

    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])

    images = render_sizes(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_ico(args.out, images)
    print("icône écrite : %s (%d tailles, %d octets)"
          % (args.out, len(images), args.out.stat().st_size))

    if args.preview is not None:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter

        marge = 16
        largeur = marge + sum(max(s, 64) + marge for s in SIZES)
        planche = QImage(largeur, 256 + 48,
                         QImage.Format.Format_RGBA8888_Premultiplied)
        planche.fill(QColor("#B9C0C6"))
        peintre = QPainter(planche)
        police = QFont()
        police.setPixelSize(11)
        peintre.setFont(police)
        x = marge
        for image in images:
            case = max(image.width(), 64)
            peintre.drawImage(x + (case - image.width()) // 2,
                              16 + (256 - image.height()) // 2, image)
            peintre.setPen(QColor("#1B2228"))
            peintre.drawText(QRectF(x, 280, case, 18),
                             int(Qt.AlignmentFlag.AlignHCenter),
                             "%d px" % image.width())
            x += case + marge
        peintre.end()
        planche.save(str(args.preview))
        print("planche de contrôle :", args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
