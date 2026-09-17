"""Dessins industriels des châssis, portés sur le site vitrine (lot L22).

    python -m tools.site_chassis [dossier]

Ne dessine rien : il **convertit** les planches que le produit embarque déjà —
celles du choix au premier lancement, produites par `tools.make_chassis_art` —
au format que la page attend. C'est le point entier de ce module : la vitrine et
l'application montrent exactement la même image, extraite du même robot, et une
évolution de la géométrie les met à jour toutes les deux d'un seul geste.

L'alternative aurait été une illustration faite pour la page. Elle finirait par
promettre un robot que le moteur ne produit plus — c'est déjà la raison pour
laquelle les particules sont de vrais rendus et non des dessins.

Le WebP sans perte pèse ici moins que le PNG d'origine : un dessin au trait sur
fond uni compresse bien, et la page n'a aucune raison d'hériter d'un fichier
plus lourd que nécessaire.
"""

from __future__ import annotations

import pathlib
import sys

from PySide6.QtGui import QGuiApplication, QImage

from pet.genome.schema import CHASSIS

SOURCE = pathlib.Path("pet") / "assets" / "chassis"
DEFAULT_DIR = pathlib.Path("docs") / "assets"

# Sans perte. Le trait fait un pixel de large sur un fond plat : à qualité 90,
# la compression avec perte bave autour de chaque ligne et le dessin prend un
# halo — très visible sur les cotes, qui sont du texte fin.
QUALITE = 100


def convert(sortie: pathlib.Path = DEFAULT_DIR) -> list[pathlib.Path]:
    """Convertit les dessins des deux châssis. Retourne les fichiers écrits."""
    sortie.mkdir(parents=True, exist_ok=True)
    ecrits = []
    for famille in CHASSIS:
        source = SOURCE / ("blueprint_%s.png" % famille)
        if not source.is_file():
            raise SystemExit(
                "%s manquant : lancez d'abord `python -m tools.make_chassis_art`"
                % source)
        image = QImage(str(source))
        if image.isNull():
            raise SystemExit("%s illisible" % source)
        cible = sortie / ("blueprint_%s.webp" % famille)
        if not image.save(str(cible), "WEBP", QUALITE):
            raise SystemExit("échec de l'écriture de %s" % cible)
        ecrits.append(cible)
    return ecrits


def main(argv: list[str]) -> int:
    # `QGuiApplication` et non `QApplication` : ce module ne fait que lire et
    # réécrire des images, il n'ouvre aucune fenêtre.
    app = QGuiApplication.instance() or QGuiApplication([])
    sortie = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_DIR
    for chemin in convert(sortie):
        image = QImage(str(chemin))
        print("%s : %d x %d, %.0f Ko"
              % (chemin, image.width(), image.height(),
                 chemin.stat().st_size / 1024))
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
