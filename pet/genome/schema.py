"""Définition, bornes et version du génome (CDC §7).

Le génome est un vecteur de paramètres **nommés et bornés**, stocké en JSON avec
ses valeurs explicites et un numéro de version de schéma. Il n'est pas stocké
sous forme de graine seule : c'est la condition pour qu'une évolution du schéma
ne régénère pas différemment le robot d'un utilisateur existant.

Les clés sont plates et pointées (`head.radius`), comme dans le tableau du
CDC §7. Une structure plate simplifie trois choses d'un coup : la validation de
bornes, la migration, et l'édition manuelle du fichier — que le CDC §14 assume
explicitement.

**L'ordre de déclaration de `PARAMS` fait partie du contrat.** C'est lui qui fixe
l'ordre de consommation du générateur pseudo-aléatoire, donc une même graine ne
redonne le même robot que si cet ordre ne change pas. Un nouveau paramètre
s'ajoute **à la fin**, jamais au milieu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 3


@dataclass(frozen=True)
class Num:
    """Paramètre continu, tiré uniformément dans [lo, hi]."""

    key: str
    lo: float
    hi: float
    note: str = ""

    @property
    def default(self) -> float:
        """Valeur de repli : le milieu de la plage.

        Sert à la migration, quand un génome écrit par une version antérieure ne
        contient pas encore ce paramètre.
        """
        return (self.lo + self.hi) / 2.0

    def clamp(self, value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return self.default
        if v != v:                      # NaN
            return self.default
        return max(self.lo, min(self.hi, v))


@dataclass(frozen=True)
class Choice:
    """Paramètre discret, tiré selon des poids."""

    key: str
    options: tuple[str, ...]
    weights: tuple[float, ...]
    note: str = ""

    @property
    def default(self) -> str:
        """Repli : l'option la plus probable, donc la plus neutre."""
        return self.options[max(range(len(self.weights)), key=self.weights.__getitem__)]

    def clamp(self, value: Any) -> str:
        return value if value in self.options else self.default


# --- Palettes (CDC §7 : blanc cassé dominant, accents cyan dominants) --------

BODY_COLORS: dict[str, str] = {
    "blanc-casse": "#F2F0EB",
    "ivoire": "#EFE7D6",
    "gris-perle": "#E3E4E6",
    "menthe-pale": "#E2EFE7",
    "rose-pale": "#F2E6E6",
    "bleu-pale": "#E4EBF2",
}

ACCENT_COLORS: dict[str, str] = {
    "cyan": "#35D7E8",
    "turquoise": "#2FB8C6",
    "ambre": "#F0A63C",
    "magenta": "#E24FA0",
}

EAR_TYPES: tuple[str, ...] = ("none", "antenna", "disc", "fin")

# Châssis : la silhouette d'ensemble (lot L17).
#
# `capsule` est l'historique — une tête posée sur un corps, éventuellement
# séparés par un cou. `monobloc` est une coque d'un seul tenant, sans jointure
# visible : le visage, les oreilles et les chapeaux se posent sur sa partie
# haute, mais la silhouette ne se brise nulle part.
#
# Un monobloc **ne porte pas d'antenne** : une tige plantée dans un bloc qui n'a
# pas de tête distincte ne se lit pas comme une oreille, elle se lit comme une
# erreur de montage. La règle est tenue par `generator.viability_issues`.
CHASSIS: tuple[str, ...] = ("capsule", "monobloc")

# Tailles d'écran d'un monobloc (lot L17). Trois variantes franches plutôt
# qu'une valeur continue : le grand écran est le trait de caractère du châssis,
# et une hauteur tirée au hasard dans un intervalle donne surtout des
# intermédiaires mous. Inerte sur une capsule, qui porte une dalle et non un
# écran.
SCREEN_HEIGHTS: tuple[str, ...] = ("compact", "standard", "large")


# --- Le génome ---------------------------------------------------------------

PARAMS: tuple[Num | Choice, ...] = (
    # Tête
    Num("head.radius", 0.85, 1.35, "taille de tête, multiplicateur"),
    Num("head.squash_y", 0.80, 1.20, "aplatissement vertical"),
    Num("head.exponent_n1", 0.35, 1.00, "sphère à 1.0, cube arrondi à 0.35"),
    Num("head.exponent_n2", 0.35, 1.00, "idem, sur l'autre axe"),
    # Corps
    Num("body.height", 0.70, 1.60, "élancement"),
    Num("body.width", 0.75, 1.25, "corpulence"),
    Num("body.taper", 0.70, 1.15, "rapport épaules/base"),
    # Cou
    Num("neck.length", 0.00, 0.35, "0 = tête posée sur le corps"),
    # Oreilles
    Choice("ear.type", EAR_TYPES, (18.0, 30.0, 28.0, 24.0),
           "trait génétique, cf. décision §17.2"),
    Num("ear.spread", 0.60, 1.40, "écartement"),
    Num("ear.size", 0.60, 1.40, "taille"),
    # Visage
    Num("face.plate_ratio", 0.55, 0.85, "proportion de la dalle sur la tête"),
    Num("eye.spacing", 0.42, 0.72, "écart des pupilles, en part de dalle"),
    # Plancher relevé au lot L3, après rendu : sous 0,21 la pupille lit comme
    # un grain de poussière sur la dalle. Le CDC §7 laisse cette plage vide,
    # c'est donc un choix de ce projet, et le §7 invite à l'ajuster au tuning.
    Num("eye.size", 0.21, 0.31, "taille des pupilles, en part de dalle"),
    Num("eye.corner_radius", 0.15, 0.50, "arrondi du rectangle des pupilles"),
    # Palette
    Choice("palette.body", tuple(BODY_COLORS), (60.0, 14.0, 12.0, 5.0, 5.0, 4.0),
           "blanc cassé dominant, pastels rares"),
    Choice("palette.accent", tuple(ACCENT_COLORS), (70.0, 12.0, 9.0, 9.0),
           "cyan dominant, ambre et magenta rares"),
    # Trait
    Num("outline.width", 0.80, 1.60, "épaisseur du contour, cf. décision §17.3"),
    # Châssis (lot L17).
    #
    # **En dernier, et c'est impératif.** `generator.draw` consomme le PRNG dans
    # l'ordre de ce tuple : insérer un paramètre ailleurs qu'à la fin décalerait
    # tous les tirages suivants, et chaque graine donnerait un autre robot. La
    # place de cette ligne est donc un contrat, pas un rangement.
    Choice("chassis", CHASSIS, (62.0, 38.0),
           "capsule dominante, monobloc plus rare"),
    Choice("screen.height", SCREEN_HEIGHTS, (28.0, 44.0, 28.0),
           "hauteur d'écran d'un monobloc ; sans effet sur une capsule"),
)

PARAMS_BY_KEY: dict[str, Num | Choice] = {p.key: p for p in PARAMS}


def defaults() -> dict[str, Any]:
    """Génome médian. Ne sert pas de robot par défaut, seulement de repli."""
    return {p.key: p.default for p in PARAMS}


def clamp_genome(raw: dict[str, Any]) -> dict[str, Any]:
    """Borne chaque paramètre connu et complète les manquants.

    Borner plutôt que rejeter, comme pour les réglages (CDC §14) : une valeur
    hors plage vient d'une édition manuelle ou d'une migration ratée, et dans les
    deux cas le pet doit démarrer.

    Les clés inconnues sont **conservées**. Un utilisateur qui a lancé une
    version plus récente puis revient en arrière ne doit pas perdre les
    paramètres que l'ancienne version ne sait pas encore lire.
    """
    out = dict(raw)
    for p in PARAMS:
        out[p.key] = p.clamp(raw.get(p.key, p.default))
    return out


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """`#RRGGBB` -> triplet dans [0, 1]. Repli sur le blanc cassé si invalide."""
    s = value.strip().lstrip("#")
    if len(s) != 6:
        s = BODY_COLORS["blanc-casse"].lstrip("#")
    try:
        r, g, b = (int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return hex_to_rgb(BODY_COLORS["blanc-casse"])
    return r, g, b


def body_rgb(genome: dict[str, Any]) -> tuple[float, float, float]:
    return hex_to_rgb(BODY_COLORS.get(genome["palette.body"], "#F2F0EB"))


def accent_rgb(genome: dict[str, Any]) -> tuple[float, float, float]:
    return hex_to_rgb(ACCENT_COLORS.get(genome["palette.accent"], "#35D7E8"))
