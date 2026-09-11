"""Cosmétiques de la boutique : chapeaux, moustaches, et la suite (CDC §13).

**De la géométrie, pas des images.** Un cosmétique est fait de superellipsoïdes
greffés sur le nœud `head` du rig, donc il traverse la passe toon, le contour et
l'ombre comme le reste du robot, et il suit la tête sans une ligne de code —
aucun nœud de rig n'est ajouté. Un sprite aurait demandé une chaîne d'assets et
une orientation à recalculer à chaque image, pour un résultat qui aurait juré.

**Tout est en parts des demi-dimensions de la tête.** C'est la seule façon de
tenir : les crânes varient du simple au double d'un génome à l'autre, et une
cote posée à l'oeil sur un robot trapu déborde sur un robot élancé.

Ce module remplace `hats.py`, qui portait le même mécanisme sous un nom devenu
faux dès l'arrivée des moustaches. La généralisation tient en une notion :
l'**emplacement**. Chaque cosmétique en occupe un, chaque emplacement se porte
indépendamment des autres, et ajouter une famille — lunettes, écharpe — revient
à ajouter une entrée à `SLOTS` et des articles à `COSMETICS`. Rien d'autre dans
le projet n'a besoin de le savoir : le panneau construit ses pages depuis
`SLOTS`, et `state.json` accepte les clés qui s'y trouvent.

Les pièces sont **alignées sur les axes**, sans rotation : `Part` ne porte qu'un
décalage, et lui ajouter une rotation aurait touché l'assembleur et le rig pour
des formes qu'on obtient très bien en empilant des ellipsoïdes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Emplacements, dans l'ordre d'affichage de la boutique. **Ce tuple est la
# source unique** : les pages du rayon, les clés acceptées dans `state.json` et
# la validation du costume en dérivent toutes.
SLOTS: tuple[str, ...] = ("hat", "moustache")

# Ancrages possibles d'une pièce.
#
# `crown` — au-dessus du crâne, `y` compté depuis son sommet.
# `face`  — sur la face avant, `y` compté depuis le centre de la tête.
#
# Deux ancrages suffisent parce qu'ils correspondent aux deux endroits où l'on
# pose quelque chose sur une tête ; un troisième viendra avec les lunettes, et
# il se déclarera ici.
ANCHORS = ("crown", "face")

# Profondeur de la face avant, en parts de `head_c`.
#
# **Mesurée, pas devinée.** À la hauteur d'une moustache — un demi-rayon sous le
# centre — la surface d'un crâne rond a déjà reculé à environ `0,89·head_c`,
# alors qu'un crâne cubique y est encore à `1,0`. Posée à 0,82, la pièce passait
# donc *derrière* la peau sur les morphologies rondes et s'y confondait.
#
# À 0,95, elle ressort franchement sur les crânes ronds et reste encastrée sur
# les cubiques : son dos, à `0,95 − c`, demeure sous la surface dans les deux
# cas, donc elle ne flotte jamais.
FACE_Z = 0.95

# Palette des cosmétiques. Hors génome : ce sont des objets achetés, pas des
# traits de naissance, et ils doivent se reconnaître d'un robot à l'autre.
FELT = (0.16, 0.17, 0.21)
FELT_LIGHT = (0.29, 0.31, 0.37)
RED = (0.78, 0.29, 0.26)
GOLD = (0.88, 0.70, 0.26)
CREAM = (0.94, 0.91, 0.84)
GREEN = (0.32, 0.60, 0.42)
BLUE = (0.36, 0.52, 0.76)
HAIR = (0.21, 0.16, 0.13)
HAIR_LIGHT = (0.34, 0.25, 0.19)


@dataclass(frozen=True)
class Piece:
    """Un morceau, en parts des demi-dimensions de la tête.

    `a`, `b`, `c` multiplient `head_a`, `head_b`, `head_c`. `x`, `y`, `z` sont
    des décalages dans les mêmes unités, dont l'origine dépend de `anchor`.
    """

    a: float
    b: float
    c: float
    y: float
    color: tuple[float, float, float]
    n1: float = 1.0
    n2: float = 1.0
    taper: float = 1.0
    x: float = 0.0
    z: float = 0.0
    anchor: str = "crown"


@dataclass(frozen=True)
class Cosmetic:
    """Un article de la boutique."""

    key: str
    slot: str
    price: int
    pieces: tuple[Piece, ...] = field(default_factory=tuple)


def _crown(**kwargs) -> Piece:
    return Piece(anchor="crown", **kwargs)


def _face(**kwargs) -> Piece:
    return Piece(anchor="face", **kwargs)


# Le catalogue. Les prix couvrent la fourchette convenue, 5 à 50, et suivent la
# complexité perçue plutôt qu'un barème : le ruban est une babiole, la couronne
# est le trophée. À 25 jetons par jour, la couronne se mérite en deux jours.
COSMETICS: tuple[Cosmetic, ...] = (
    # --- chapeaux ---------------------------------------------------------
    Cosmetic("bow", "hat", 5, (
        _crown(a=0.30, b=0.22, c=0.22, y=0.02, color=RED, n1=0.7, n2=0.7),
        _crown(a=0.16, b=0.14, c=0.16, y=0.06, color=RED, n1=0.8, n2=0.8),
    )),
    Cosmetic("beanie", "hat", 10, (
        _crown(a=0.96, b=0.52, c=0.96, y=0.16, color=GREEN, n1=0.85),
        _crown(a=1.02, b=0.14, c=1.02, y=0.02, color=CREAM, n1=0.6),
    )),
    Cosmetic("cap", "hat", 15, (
        _crown(a=0.94, b=0.46, c=0.94, y=0.14, color=BLUE, n1=0.9),
        _crown(a=0.62, b=0.07, c=0.90, y=0.02, color=BLUE, n1=0.5, n2=0.6,
               z=0.72),
        _crown(a=0.20, b=0.12, c=0.20, y=0.34, color=CREAM, n1=0.8, n2=0.8),
    )),
    Cosmetic("party", "hat", 20, (
        _crown(a=0.72, b=0.92, c=0.72, y=0.74, color=RED, taper=0.06),
        _crown(a=0.22, b=0.20, c=0.22, y=1.64, color=CREAM, n1=0.9, n2=0.9),
    )),
    Cosmetic("tophat", "hat", 35, (
        _crown(a=1.32, b=0.08, c=1.32, y=0.04, color=FELT, n1=0.45, n2=0.9),
        _crown(a=0.82, b=0.78, c=0.82, y=0.76, color=FELT, n1=0.40, n2=0.9),
        _crown(a=0.86, b=0.12, c=0.86, y=0.28, color=RED, n1=0.40, n2=0.9),
    )),
    Cosmetic("helmet", "hat", 40, (
        _crown(a=1.00, b=0.62, c=1.00, y=0.10, color=FELT_LIGHT, n1=0.75),
        _crown(a=0.12, b=0.34, c=0.94, y=0.52, color=GOLD, n1=0.6, n2=0.6),
    )),
    Cosmetic("crown", "hat", 50, (
        _crown(a=0.98, b=0.26, c=0.98, y=0.20, color=GOLD, n1=0.45),
        _crown(a=0.16, b=0.30, c=0.16, y=0.60, color=GOLD, n1=0.9, n2=0.9,
               taper=0.25),
        _crown(a=0.16, b=0.24, c=0.16, y=0.52, color=GOLD, n1=0.9, n2=0.9,
               taper=0.25, z=0.66),
        _crown(a=0.16, b=0.24, c=0.16, y=0.52, color=GOLD, n1=0.9, n2=0.9,
               taper=0.25, z=-0.66),
        _crown(a=0.14, b=0.14, c=0.14, y=0.92, color=RED, n1=0.9, n2=0.9),
    )),

    # --- moustaches -------------------------------------------------------
    #
    # Posées sous la dalle du visage, jamais dessus : la dalle est la seule
    # surface expressive du robot, et la couvrir même en partie lui coûterait
    # plus que la moustache ne lui apporte.
    Cosmetic("pencil", "moustache", 10, (
        _face(a=0.52, b=0.045, c=0.14, y=-0.46, color=HAIR, n1=0.5, n2=0.5),
    )),
    # Les pointes sont **sous** la barre, pas au-dessus. Placées plus haut, elles
    # se lisaient comme deux antennes partant vers le ciel plutôt que comme les
    # extrémités épaissies d'une moustache.
    Cosmetic("handlebar", "moustache", 20, (
        _face(a=0.48, b=0.075, c=0.15, y=-0.44, color=HAIR, n1=0.55, n2=0.6),
        _face(a=0.15, b=0.105, c=0.14, y=-0.50, color=HAIR, n1=0.85, n2=0.85,
              x=-0.47),
        _face(a=0.15, b=0.105, c=0.14, y=-0.50, color=HAIR, n1=0.85, n2=0.85,
              x=0.47),
    )),
    Cosmetic("walrus", "moustache", 25, (
        _face(a=0.62, b=0.16, c=0.18, y=-0.48, color=HAIR_LIGHT, n1=0.75,
              n2=0.7),
        _face(a=0.30, b=0.20, c=0.16, y=-0.56, color=HAIR_LIGHT, n1=0.85,
              n2=0.85, x=-0.30),
        _face(a=0.30, b=0.20, c=0.16, y=-0.56, color=HAIR_LIGHT, n1=0.85,
              n2=0.85, x=0.30),
    )),
)

BY_KEY = {item.key: item for item in COSMETICS}

# Valeur d'`appearance[slot]` quand rien n'est porté. Une chaîne vide plutôt
# qu'une clé absente : le panneau doit pouvoir montrer « aucun » comme un choix,
# à côté des articles possédés.
NONE = ""


def by_slot(slot: str) -> tuple[Cosmetic, ...]:
    """Articles d'un emplacement, dans l'ordre du catalogue."""
    return tuple(c for c in COSMETICS if c.slot == slot)


def slot_of(key: str) -> str:
    """Emplacement d'un article, ou chaîne vide s'il est inconnu."""
    item = BY_KEY.get(key)
    return item.slot if item is not None else ""


def price(key: str) -> int:
    item = BY_KEY.get(key)
    return item.price if item is not None else 0


def parts_for(key: str, dims, node: str = "head"):
    """Parties de rig d'un cosmétique, prêtes à être ajoutées au robot.

    Importé paresseusement pour que ce module reste lisible sans dépendre de
    l'assembleur, qui lui-même l'importe : les deux se référencent, et c'est
    l'import tardif qui évite le cycle.
    """
    from .builder import Part
    from .superellipsoid import superellipsoid

    item = BY_KEY.get(key)
    if item is None:
        return []

    # Le nœud `head` est à la jointure du cou ; le maillage de tête est remonté
    # de sa demi-hauteur. Le centre de la tête est donc à `head_b`, et son
    # sommet à deux fois cette valeur.
    centre = dims.head_b
    sommet = 2.0 * dims.head_b

    parts = []
    for index, piece in enumerate(item.pieces):
        mesh = superellipsoid(
            a=max(1e-3, piece.a * dims.head_a),
            b=max(1e-3, piece.b * dims.head_b),
            c=max(1e-3, piece.c * dims.head_c),
            n1=piece.n1, n2=piece.n2, taper=piece.taper,
        )
        if piece.anchor == "face":
            origine_y = centre
            origine_z = FACE_Z * dims.head_c
        else:
            origine_y = sommet
            origine_z = 0.0
        parts.append(Part(
            "%s_%s_%d" % (item.slot, item.key, index), node, mesh, piece.color,
            offset=(piece.x * dims.head_a,
                    origine_y + piece.y * dims.head_b,
                    origine_z + piece.z * dims.head_c),
        ))
    return parts
