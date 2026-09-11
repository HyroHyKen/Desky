"""Localisation des fichiers embarqués (lot L8).

Le projet lit deux dossiers de données à l'exécution : les shaders GLSL et les
sprites d'objets. Tant qu'on lance depuis les sources, `Path(__file__).parent`
suffit ; une fois gelé par PyInstaller, il désigne un chemin **à l'intérieur de
l'archive**, qui n'existe pas toujours sur le disque.

Ce module est la seule réponse à cette question, et il vaut mieux qu'elle soit
explicite : un `__file__` qui marche par chance dans un mode de gel et pas dans
l'autre est un défaut qu'on ne découvre qu'au premier testeur, quand le robot
refuse de s'afficher sans dire pourquoi.

`sys._MEIPASS` est la racine que PyInstaller pose au démarrage, en `onedir`
comme en `onefile`. Hors gel, l'attribut n'existe pas et on retombe sur le
dossier du paquet.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Racine du paquet `pet`, depuis les sources.
PACKAGE_ROOT = Path(__file__).resolve().parent


def is_frozen() -> bool:
    """L'application tourne-t-elle depuis un binaire PyInstaller ?"""
    return bool(getattr(sys, "frozen", False))


def root() -> Path:
    """Racine sous laquelle chercher les données embarquées."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        # Les données sont ajoutées sous `pet/...` dans le paquet gelé, ce qui
        # garde exactement la même arborescence que dans les sources.
        return Path(base) / "pet"
    return PACKAGE_ROOT


def resource_dir(*parts: str) -> Path:
    """Dossier de données, gelé ou non.

    Retourne le chemin même s'il n'existe pas : c'est à l'appelant de décider
    quoi faire d'un dossier manquant, et il le sait mieux que ce module — les
    sprites d'objets peuvent manquer sans conséquence, les shaders non.
    """
    return root().joinpath(*parts)
