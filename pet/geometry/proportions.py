"""Silhouette de référence et dimensions dérivées du génome.

Les paramètres du génome sont des **multiplicateurs**, pas des tailles absolues :
le CDC §7 les donne autour de 1.0 (`head.radius` 0.85–1.35, `body.width`
0.75–1.25). Ce module porte la silhouette de référence qu'ils multiplient, et
c'est donc lui qui donne un sens géométrique aux nombres du génome.

Source unique de vérité, partagée par deux appelants qui doivent absolument
s'accorder : la validation de viabilité du générateur (`genome.generator`) et
l'assemblage des maillages (`geometry.builder`). Si les deux calculaient les
dimensions séparément, une règle de cohérence pourrait rejeter des génomes
parfaitement viables — ou en accepter d'inviables.

Repère : **Y vers le haut**, **Z vers l'avant** (le visage regarde +Z), origine
au sol entre les pieds. Unités arbitraires, mises à l'échelle au rendu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- Silhouette de référence, tous multiplicateurs à 1.0 --------------------
#
# Proportions de nourrisson (CDC §1) : une tête large par rapport au corps. Ces
# valeurs sont le point de réglage principal du lot L9 ; les changer déplace tout
# le nuage morphologique d'un coup.

HEAD_RADIUS = 0.52          # demi-largeur de tête de référence
BODY_WIDTH = 0.70           # largeur de corps de référence
BODY_HEIGHT = 0.85          # hauteur de corps de référence
BODY_DEPTH_RATIO = 0.86     # profondeur du corps, en part de sa largeur
HEAD_DEPTH_RATIO = 0.96     # profondeur de tête, en part de sa demi-largeur
# Rayon du cou. Assez large pour relier visuellement tête et corps : un cou
# mince lit comme une perle flottante entre deux volumes, défaut constaté sur
# la planche de contact du lot L2.
NECK_RADIUS_RATIO = 0.52    # en part de la demi-largeur de tête
NECK_MAX_BODY_RATIO = 0.80  # mais jamais plus large que ça du demi-corps

# Enfoncement des parties les unes dans les autres aux jointures. Le CDC §7
# assume des jointures visibles, mais un interstice n'est pas une jointure :
# des volumes rigides qui s'effleurent laissent voir le fond au travers.
JOINT_SINK_RATIO = 0.16     # en part de la demi-hauteur de tête
NECK_OVERLAP_RATIO = 0.60   # en part du rayon du cou
EAR_SIZE = 0.26             # demi-taille d'oreille de référence

# Écartement des oreilles : le génome (0.6–1.4) est remappé sur cette plage,
# exprimée en part de la demi-largeur de tête. En dessous de 1.0 l'oreille
# mord sur la tête, au-dessus elle s'en écarte.
EAR_SPREAD_MIN = 0.82
EAR_SPREAD_MAX = 1.16

# Profondeur à laquelle la dalle faciale est posée, en part de la demi-profondeur
# de tête. Inférieure à 1.0 : la dalle est légèrement encastrée.
PLATE_DEPTH_RATIO = 0.78

# Oreilles montées sur les côtés, susceptibles de croiser la dalle.
SIDE_EAR_TYPES = frozenset({"disc", "fin"})


@dataclass(frozen=True)
class Dimensions:
    """Demi-dimensions absolues déduites d'un génome."""

    head_a: float           # demi-largeur de tête
    head_b: float           # demi-hauteur de tête
    head_c: float           # demi-profondeur de tête
    body_a: float
    body_b: float
    body_c: float
    neck_r: float
    neck_h: float
    ear_r: float            # demi-taille d'oreille
    ear_x: float            # position d'attache en X, valeur absolue
    plate_half_w: float     # demi-largeur de la dalle faciale
    plate_z: float          # profondeur d'implantation de la dalle
    chassis: str = "capsule"

    @property
    def monobloc(self) -> bool:
        return self.chassis == "monobloc"

    @property
    def shell_b(self) -> float:
        """Demi-hauteur de la coque d'un monobloc, du sol au sommet.

        Le cou étant nul sur ce châssis, elle vaut exactement la somme des deux
        demi-hauteurs : la coque occupe la place du corps **et** de la tête.
        """
        return self.body_b + self.head_b

    @property
    def carrier_top(self) -> float:
        """Sommet, au repos, du maillage porté par `body_flex`.

        Sert à reporter la montée de poitrine sur le cou quand le corps
        respire ou encaisse (cf. `anim.layers.apply_channels`). La capsule y
        porte son corps, le monobloc sa coque entière — et sans cette
        distinction, le visage d'un monobloc glisserait sur son bloc à chaque
        atterrissage.
        """
        return 2.0 * (self.shell_b if self.monobloc else self.body_b)

    @property
    def head_width(self) -> float:
        return 2.0 * self.head_a

    @property
    def body_width(self) -> float:
        return 2.0 * self.body_a

    @property
    def head_center_y(self) -> float:
        """Hauteur du centre de la tête, corps et cou empilés."""
        return 2.0 * self.body_b + self.neck_h + self.head_b

    @property
    def total_height(self) -> float:
        return self.head_center_y + self.head_b


def _remap(value: float, lo: float, hi: float, out_lo: float, out_hi: float) -> float:
    t = 0.0 if hi == lo else (value - lo) / (hi - lo)
    return out_lo + max(0.0, min(1.0, t)) * (out_hi - out_lo)


def dimensions(genome: dict[str, Any]) -> Dimensions:
    """Traduit un génome en demi-dimensions absolues."""
    head_a = HEAD_RADIUS * float(genome["head.radius"])
    body_a = 0.5 * BODY_WIDTH * float(genome["body.width"])
    body_b = 0.5 * BODY_HEIGHT * float(genome["body.height"])
    ear_r = EAR_SIZE * float(genome["ear.size"])
    head_c = head_a * HEAD_DEPTH_RATIO
    chassis = str(genome.get("chassis", "capsule"))

    # Un monobloc est une colonne : **même largeur en haut qu'en bas**, et pas
    # de cou. C'est ce qui permet à la dalle faciale, aux oreilles et aux
    # chapeaux — tous cotés en demi-dimensions de tête — de tomber juste sur la
    # coque sans qu'aucun d'eux n'ait à savoir qu'il y a deux châssis.
    neck_h = float(genome["neck.length"])
    if chassis == "monobloc":
        body_a = head_a
        neck_h = 0.0

    return Dimensions(
        head_a=head_a,
        head_b=head_a * float(genome["head.squash_y"]),
        head_c=head_c,
        body_a=body_a,
        body_b=body_b,
        body_c=body_a * BODY_DEPTH_RATIO,
        neck_r=min(head_a * NECK_RADIUS_RATIO, body_a * NECK_MAX_BODY_RATIO),
        neck_h=neck_h,
        ear_r=ear_r,
        ear_x=head_a * _remap(float(genome["ear.spread"]), 0.60, 1.40,
                              EAR_SPREAD_MIN, EAR_SPREAD_MAX),
        plate_half_w=head_a * float(genome["face.plate_ratio"]),
        plate_z=head_c * PLATE_DEPTH_RATIO,
        chassis=chassis,
    )
