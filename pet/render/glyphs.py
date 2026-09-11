"""Vocabulaire de sigles, côté Python.

**Les identifiants doivent correspondre à ceux de `shaders/glyphs.glsl`.** C'est
un contrat au même titre que l'ordre de `PARAMS` dans le génome : le shader
aiguille sur un entier, et décaler la table ici ferait afficher la goutte à la
place de la gamelle sans qu'aucune erreur ne soit levée. Un test du lot L6
compare les deux listes.

Ces sigles sont ceux dessinés **en SDF**, donc ceux que la bulle et les yeux
peuvent afficher. Les icônes des boutons du panneau sont d'une autre nature —
des chemins vectoriels tracés par QPainter — et vivent dans `ui/icons.py`. Deux
techniques pour un même langage visuel, à garder cohérentes à la main.
"""

from __future__ import annotations

# Ordre contractuel. `none` vaut 0 et ne dessine rien.
GLYPH_NAMES: tuple[str, ...] = (
    "none",
    "hunger",
    "fun",
    "energy",
    "hygiene",
    "robot",
    "question",
)

GLYPHS: dict[str, int] = {name: index for index, name in enumerate(GLYPH_NAMES)}

# Sigle affiché par la bulle pour chaque besoin. Les quatre besoins du §12 ont
# chacun le leur : une bulle qui ne saurait pas dire *quoi* ne servirait à rien.
GLYPH_FOR_NEED: dict[str, str] = {
    "hunger": "hunger",
    "fun": "fun",
    "energy": "energy",
    "hygiene": "hygiene",
}


def glyph_id(name: str) -> int:
    """Identifiant d'un sigle. Un nom inconnu ne dessine rien plutôt que lever.

    Le rendu ne doit jamais faire tomber l'application pour un pictogramme :
    une bulle vide est un défaut visible et réparable, un plantage non.
    """
    return GLYPHS.get(name, 0)
