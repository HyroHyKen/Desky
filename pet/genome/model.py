"""Nom de modèle : le code gravé sous le robot (lot L18).

Chaque robot porte, en plus du nom que l'utilisateur lui donne, une référence
d'usine — `C3-A7`, `M1-G4` — lisible comme un matricule de droïde. Le nom dit
qui il est, le modèle dit ce qu'il est.

**Le modèle ne dépend que de ce qu'on ne peut pas changer.** Ni la couleur, ni
le chapeau, ni la moustache n'y entrent : tout cela s'achète et se retire, et un
robot qui changerait de référence en enfilant un bonnet n'aurait pas de
référence du tout. Seuls les traits de naissance comptent — ceux que le §7 range
dans le génome et que la boutique ne touche jamais.

Format, en quatre caractères plus un tiret :

    C  3  -  A  7
    │  │     │  │
    │  │     │  └─ signature, 0 à 9 : deux robots de même famille, même forme et
    │  │     │     même trait ne portent pas le même code
    │  │     └─ trait distinctif du châssis (voir `_lettre_trait`)
    │  └─ forme, 1 cubique à 4 sphérique
    └─ famille : C capsule, M monobloc

**La signature n'utilise pas `hash()`.** Python randomise le hachage des
chaînes à chaque processus : le robot aurait changé de référence à chaque
lancement. `crc32` est déterministe, partout et pour toujours.
"""

from __future__ import annotations

import zlib
from typing import Any

# Familles de châssis. La lettre est ce qui se lit en premier ; elle doit donc
# porter l'information la plus structurante, et le châssis est la seule chose
# qui change vraiment la silhouette.
FAMILLES: dict[str, str] = {"capsule": "C", "monobloc": "M"}
FAMILLE_DEFAUT = "C"

# Libellés lisibles, pour la page de statut. Le code est un matricule, pas un
# nom de produit : on montre les deux.
LIBELLES: dict[str, str] = {"capsule": "Capsule", "monobloc": "Monobloc"}

# Bornes de `head.exponent_n1`, recopiées du schéma. Un exposant bas donne un
# cube arrondi, un exposant haut une sphère.
FORME_MIN, FORME_MAX = 0.35, 1.00
FORMES = 4

# Trait distinctif, une lettre. **L'alphabet dépend du châssis**, et c'est
# voulu : une capsule se distingue par ses oreilles, un monobloc n'en a pas et
# se distingue par la taille de son écran. Garder un alphabet commun aurait
# donné la même lettre `X` à tous les monoblocs, soit un code sans pouvoir
# distinctif sur quatre robots sur dix.
LETTRES_OREILLES: dict[str, str] = {
    "antenna": "A", "disc": "D", "fin": "I", "none": "X",
}
LETTRES_ECRAN: dict[str, str] = {
    "compact": "N", "standard": "S", "large": "G",
}
LETTRE_DEFAUT = "X"

# Paramètres qui entrent dans la signature : tout ce qui façonne le robot, et
# rien de ce qui se change. Déclaré en dur plutôt que déduit de `PARAMS` moins
# une liste d'exclusions — ajouter un paramètre au schéma ne doit pas renommer
# silencieusement tous les robots existants. Le jour où l'on veut qu'il compte,
# on l'inscrit ici, et on sait ce qu'on fait.
SIGNATURE_PARAMS: tuple[str, ...] = (
    "head.radius", "head.squash_y", "head.exponent_n1", "head.exponent_n2",
    "body.height", "body.width", "body.taper",
    "neck.length",
    "ear.type", "ear.spread", "ear.size",
    "face.plate_ratio", "eye.spacing", "eye.size", "eye.corner_radius",
    "outline.width",
    "chassis", "screen.height",
)

# Arrondi appliqué aux nombres avant signature. Trois décimales : assez fin pour
# que deux robots distincts le restent, assez grossier pour qu'une réécriture du
# fichier par une autre version de Python ne change pas la référence.
SIGNATURE_DECIMALES = 3


def famille(genome: dict[str, Any]) -> str:
    """Lettre de famille."""
    return FAMILLES.get(str(genome.get("chassis", "capsule")), FAMILLE_DEFAUT)


def libelle_famille(genome: dict[str, Any]) -> str:
    """Nom lisible du châssis, pour l'affichage."""
    return LIBELLES.get(str(genome.get("chassis", "capsule")),
                        LIBELLES["capsule"])


def chiffre_forme(genome: dict[str, Any]) -> int:
    """1 pour un cube arrondi, 4 pour une sphère."""
    try:
        n1 = float(genome.get("head.exponent_n1", FORME_MIN))
    except (TypeError, ValueError):
        n1 = FORME_MIN
    part = (n1 - FORME_MIN) / (FORME_MAX - FORME_MIN)
    part = max(0.0, min(0.999, part))
    return 1 + int(part * FORMES)


def _lettre_trait(genome: dict[str, Any]) -> str:
    """Lettre du trait distinctif, selon le châssis."""
    if str(genome.get("chassis", "capsule")) == "monobloc":
        return LETTRES_ECRAN.get(str(genome.get("screen.height", "standard")),
                                 LETTRES_ECRAN["standard"])
    return LETTRES_OREILLES.get(str(genome.get("ear.type", "none")),
                                LETTRE_DEFAUT)


def _empreinte(genome: dict[str, Any]) -> str:
    """Chaîne canonique des traits de naissance, dans un ordre figé."""
    morceaux = []
    for cle in SIGNATURE_PARAMS:
        valeur = genome.get(cle)
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            morceaux.append("%s=%.*f" % (cle, SIGNATURE_DECIMALES, float(valeur)))
        else:
            morceaux.append("%s=%s" % (cle, valeur))
    return "|".join(morceaux)


def chiffre_signature(genome: dict[str, Any]) -> int:
    """Chiffre 0-9 qui sépare deux robots par ailleurs identiques."""
    brut = zlib.crc32(_empreinte(genome).encode("utf-8"))
    return brut % 10


def model_name(genome: dict[str, Any]) -> str:
    """Référence complète, du type `C3-A7`."""
    return "%s%d-%s%d" % (famille(genome), chiffre_forme(genome),
                          _lettre_trait(genome), chiffre_signature(genome))
