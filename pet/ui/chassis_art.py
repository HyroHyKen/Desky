"""Où trouver les illustrations de châssis (lot L20).

Deux familles d'images, produites par `tools/make_chassis_art.py` : le dessin
industriel qui illustre le carton de choix, et les vignettes d'exemples que
l'infobulle fait défiler.

**Découvertes par nom de fichier, pas déclarées dans une table.** C'est le même
parti pris que les sprites d'objets du lot L7 : déposer un
`exemple_capsule_7.png` dans le dossier suffit à l'obtenir dans l'infobulle,
sans toucher au code ni à un manifeste qui finirait par mentir. Le blueprint,
lui, est unique par châssis, donc son nom est déterminé.

Toutes les fonctions rendent des chemins **existants** ou rien. Une illustration
manquante n'est pas une erreur fatale — le carton reste choisissable, il est
simplement moins joli — et c'est à l'appelant de décider quoi afficher à la
place.
"""

from __future__ import annotations

from pathlib import Path

from ..resources import resource_dir

ASSET_DIR = resource_dir("assets", "chassis")

BLUEPRINT = "blueprint_%s.png"
EXEMPLE = "exemple_%s_"


def blueprint(chassis: str, directory: Path | None = None) -> Path | None:
    """Dessin industriel d'un châssis, ou `None` s'il manque."""
    base = directory if directory is not None else ASSET_DIR
    chemin = base / (BLUEPRINT % chassis)
    return chemin if chemin.is_file() else None


def examples(chassis: str, directory: Path | None = None) -> list[Path]:
    """Vignettes d'exemples, triées pour que le défilement soit reproductible.

    Le tri est **numérique** et non lexicographique : à dix vignettes, un tri de
    chaînes place `exemple_x_10` avant `exemple_x_2`. L'ordre du défilement n'a
    certes pas de sens propre, mais un ordre qui saute d'un cran dès qu'on passe
    la dizaine est le genre de bizarrerie qu'on met une heure à comprendre.
    """
    base = directory if directory is not None else ASSET_DIR
    if not base.is_dir():
        return []
    prefixe = EXEMPLE % chassis

    def rang(chemin: Path) -> tuple[int, str]:
        queue = chemin.stem[len(prefixe):]
        return (int(queue) if queue.isdigit() else 1 << 30, chemin.name)

    return sorted(base.glob(prefixe + "*.png"), key=rang)
