"""Logo embarqué dans l'application, dérivé de celui du site (lot L19).

    python -m tools.make_splash

**Une seule source de vérité.** `docs/assets/logo.png` est le fichier fourni ;
celui de l'application en est une réduction produite ici. Garder deux originaux
finirait par donner deux logos différents selon qu'on regarde le site ou l'écran
de lancement, et personne ne s'en apercevrait avant longtemps.

La réduction n'est pas cosmétique : l'original fait 1181 px de large pour un
écran qui l'affiche autour de 460 px logiques. Embarquer l'original reviendrait
à faire décoder au démarrage deux fois plus de pixels que nécessaire, dans la
seconde où l'on cherche précisément à paraître rapide.
"""

from __future__ import annotations

import pathlib
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage

SOURCE = pathlib.Path("docs") / "assets" / "logo.png"
CIBLE = pathlib.Path("pet") / "assets" / "brand" / "logo.png"

# Largeur embarquée. L'écran de lancement l'affiche à `splash.LOGO_W` pixels
# logiques ; on garde le double pour rester net sur un écran à 200 %.
LARGEUR = 960


def main(argv: list[str]) -> int:
    QGuiApplication.instance() or QGuiApplication([])

    if not SOURCE.is_file():
        print("source absente : %s" % SOURCE)
        return 1

    source = QImage(str(SOURCE))
    if source.isNull():
        print("source illisible : %s" % SOURCE)
        return 1

    reduit = source.scaledToWidth(LARGEUR, Qt.TransformationMode.SmoothTransformation)
    CIBLE.parent.mkdir(parents=True, exist_ok=True)
    if not reduit.save(str(CIBLE), "PNG"):
        print("échec de l'écriture : %s" % CIBLE)
        return 1

    print("%s : %d x %d, %.0f Ko  (source %d x %d, %.0f Ko)"
          % (CIBLE, reduit.width(), reduit.height(),
             CIBLE.stat().st_size / 1024,
             source.width(), source.height(), SOURCE.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
