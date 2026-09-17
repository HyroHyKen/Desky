"""Assemblage du robot depuis un génome (CDC §7).

Le robot est un **assemblage de parties rigides distinctes** liées par une
hiérarchie de transformations, et non un maillage unifié. Les jointures visibles
sont assumées : c'est le vocabulaire du hard-surface robotique, et c'est aussi ce
qui rend l'animation possible.

Piste écartée par le CDC pour la v1 : SDF avec union lisse et marching cubes.
Plus organique, mais empêche l'animation par parties, alourdit le maillage et
coûte un re-meshing à chaque changement de pose.

Repère local de la tête : origine à la jointure du cou, sommet du crâne à
`2 · head_b`. Placer le nœud de tête à la jointure et non au centre est
délibéré — c'est le pivot correct pour le look-at du lot L4, où faire tourner la
tête autour de son centre donnerait un mouvement de bille et non de nuque.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..genome.schema import accent_rgb, body_rgb
from . import cosmetics, proportions
from .proportions import Dimensions
from .rig import ROOT, Node, Rig
from .superellipsoid import Mesh, superellipsoid, superellipsoid_patch

# Dalle faciale : sombre, non éclairée au lot L3 où le shader SDF y dessinera les
# pupilles. La couleur est fixe et non génétique — c'est l'ardoise, pas la peau.
PLATE_COLOR = (0.09, 0.10, 0.12)

# Exposants du corps et du cou. Le CDC §7 ne fait varier que ceux de la tête :
# le corps garde une identité stable, et c'est la tête qui porte la variété.
BODY_N1, BODY_N2 = 0.78, 0.86
NECK_N1, NECK_N2 = 0.70, 0.90

# Coque faciale **symétrique** en latitude. Un décalage vers le bas paraissait
# une bonne idée — regard enfantin — mais aux exposants bas du génome, |sin v|^n1
# croît très vite près de l'équateur : la coque s'étendait alors bien plus vers
# le bas que vers le haut, et son centre visuel n'était plus son centre
# paramétrique. Symétrique, l'espace UV du visage est enfin centré.
PLATE_V_CENTER = 0.0

# Étendue angulaire de la coque, en part de π/2, pilotée par face.plate_ratio.
# Le rapport très dissymétrique entre les deux donne un écran **en paysage** :
# mesuré au lot L3, la dalle sortait en portrait (aspect 0,74) avec des étendues
# comparables, parce que l'exposant vertical étire l'axe y. L'étendue
# horizontale a été ramenée de 0,82 à 0,72 : au haut de la plage de
# face.plate_ratio, la dalle atteignait le bord du crâne au lieu d'y être
# encadrée par le plastique.
PLATE_U_SPAN = 0.72
PLATE_V_SPAN = 0.19

# La coque est générée sur un rayon très légèrement supérieur à celui du crâne,
# pour se poser dessus sans z-fighting.
PLATE_INFLATE = 1.02

# Cadrage de l'écran sur un monobloc (lot L17).
#
# `RISE` est la hauteur du **centre** de l'écran, en part de la demi-hauteur de
# coque au-dessus de son centre. Un bloc qui regarde depuis son milieu n'a pas
# un visage, il a un hublot.
#
# `SCREEN_HALF_H` est la demi-hauteur de l'écran, dans la même unité — et elle
# est **constante, ce qui est tout l'objet du réglage**. Le grand écran est ce
# qui fait le charme de ce châssis ; l'indexer sur `face.plate_ratio` comme le
# fait la capsule le réduisait à une fente sur les génomes au ratio bas. Le
# ratio continue de gouverner la largeur, donc les écrans restent différents
# d'un robot à l'autre — ils ne sont simplement plus rabougris.
#
# Exprimée en hauteur de monde et non en angle : l'angle qui atteint une
# hauteur donnée dépend de l'exposant du génome, donc une constante d'angle
# donnerait un écran d'une taille différente sur chaque robot.
MONOBLOC_FACE_RISE = 0.44
MONOBLOC_PLATE_U = 1.10

# Les trois hauteurs d'écran, en parts de la demi-hauteur de coque. Choisies au
# rendu comparatif : en dessous de 0,22 l'écran redevient une fente et les yeux
# des points, au-delà de 0,38 il avale le bloc. Les yeux étant dimensionnés en
# fraction de la dalle, ils grandissent avec l'écran — c'est ce qui fait que les
# trois variantes se distinguent d'un coup d'œil et pas seulement à la mesure.
MONOBLOC_SCREEN_HALF_H = {"compact": 0.22, "standard": 0.30, "large": 0.38}


@dataclass(frozen=True)
class Part:
    """Une partie rigide, attachée à un nœud du rig."""

    name: str
    node: str
    mesh: Mesh
    color: tuple[float, float, float]
    # Décalage dans le repère du nœud. Séparé de la translation du nœud parce
    # que le nœud est un pivot d'animation, alors que ce décalage est une donnée
    # de forme et ne bouge jamais.
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def offset_matrix(self) -> np.ndarray:
        m = np.identity(4, dtype="f4")
        m[0, 3], m[1, 3], m[2, 3] = self.offset
        return m


@dataclass(frozen=True)
class Robot:
    """Robot assemblé, prêt à téléverser en VBO."""

    genome: dict[str, Any]
    dims: Dimensions
    rig: Rig
    parts: tuple[Part, ...]
    outline_width: float
    accent: tuple[float, float, float]
    build_ms: float
    # Pose de repos du rig, relevée à la construction. Le lot L4 s'en sert comme
    # référence : capturer la pose *courante* du rig exposerait à y cuire une
    # animation en cours, ce qui figerait le pet dans sa dernière posture.
    base_pose: dict = field(default_factory=dict)

    @property
    def vertex_count(self) -> int:
        return sum(p.mesh.vertex_count for p in self.parts)

    @property
    def triangle_count(self) -> int:
        return sum(p.mesh.triangle_count for p in self.parts)

    def part_matrices(self) -> list[tuple[Part, np.ndarray]]:
        """Matrice monde de chaque partie, décalage de forme inclus."""
        world = self.rig.world_matrices()
        return [(p, world[p.node] @ p.offset_matrix()) for p in self.parts]

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Boîte englobante du robot assemblé, dans le repère monde."""
        lo = np.full(3, np.inf)
        hi = np.full(3, -np.inf)
        for part, matrix in self.part_matrices():
            pos = part.mesh.positions
            homo = np.hstack([pos, np.ones((len(pos), 1), dtype="f4")])
            world_pos = (matrix @ homo.T).T[:, :3]
            lo = np.minimum(lo, world_pos.min(axis=0))
            hi = np.maximum(hi, world_pos.max(axis=0))
        return lo, hi


def _build_rig(d: Dimensions) -> Rig:
    """`root → body → {body_flex, neck → head → {face, ear_l, ear_r}}` (CDC §10).

    `body_flex` s'ajoute au schéma du §10 : il ne porte aucune articulation, il
    isole l'échelle de respiration pour qu'elle ne se propage pas au reste.
    """
    rig = Rig()
    rig.add(Node("body", parent=ROOT, translation=np.array([0.0, d.body_b, 0.0], dtype="f4")))

    # Nœud dédié au maillage du corps, distinct de `body`. Sa raison d'être est
    # la respiration du lot L4 : l'échelle d'un nœud se propage à ses enfants,
    # donc la poser sur `body` étirerait aussi le cou et la tête. Portée par un
    # enfant que rien d'autre n'utilise, elle ne déforme que le corps.
    rig.add(Node("body_flex", parent="body"))

    # Le cou existe comme nœud même quand sa longueur est nulle : le rig garde
    # ainsi la même topologie pour tous les génomes, ce qui évite au lot L4
    # d'avoir deux chemins d'animation selon la morphologie.
    rig.add(Node("neck", parent="body",
                 translation=np.array([0.0, d.body_b + d.neck_h / 2.0, 0.0], dtype="f4")))
    # La tête est enfoncée dans ce qui la porte. Sans cet enfoncement, deux
    # volumes rigides ne font que s'effleurer et on voit le fond entre eux.
    sink = d.head_b * proportions.JOINT_SINK_RATIO
    rig.add(Node("head", parent="neck",
                 translation=np.array([0.0, d.neck_h / 2.0 - sink, 0.0], dtype="f4")))

    # Nœud de visage placé au centre de la tête : la coque faciale est déjà
    # exprimée dans le repère du crâne, et ce nœud sera le pivot du visage SDF
    # du lot L3 puis de ses expressions au lot L4.
    #
    # **Sur un monobloc, la dalle est accrochée à `body_flex`**, comme la coque
    # dont elle est un morceau de surface, et non à la tête.
    #
    # La différence ne se voit qu'à l'écrasement, et elle est totale. `body.flex`
    # pose une échelle `(w, s, w)` sur `body_flex` : la coque s'aplatit et
    # s'élargit, à volume conservé. Une dalle accrochée à la tête ne reçoit que
    # des translations — elle garde sa taille pendant que la coque grossit de
    # 6 % en profondeur, et la coque l'avale. Mesuré : à `flex = -0,12` l'écran
    # a entièrement disparu dans le bloc, et il ressortait par le bas aux
    # valeurs plus fortes.
    #
    # Accrochée au même nœud que la coque, avec l'origine de la coque pour
    # translation, elle subit exactement la même transformation : la relation
    # entre les deux surfaces est alors vraie par construction, à toute échelle,
    # au lieu d'être rattrapée déformation par déformation. C'est aussi ce que
    # le châssis raconte — la dalle ne bouge pas de son bloc, le lot L17 avait
    # déjà annulé pour elle le lacet et le tangage de tête.
    #
    # `shell_b - body_b` est le centre de la coque dans le repère de
    # `body_flex`, c'est-à-dire l'offset du maillage de coque, au signe près :
    # les deux se lisent ensemble (cf. `_shell_part`).
    if d.monobloc:
        rig.add(Node("face", parent="body_flex",
                     translation=np.array([0.0, d.shell_b - d.body_b, 0.0],
                                          dtype="f4")))
    else:
        rig.add(Node("face", parent="head",
                     translation=np.array([0.0, d.head_b, 0.0], dtype="f4")))
    return rig


def _body_part(genome: dict[str, Any], d: Dimensions,
               color: tuple[float, float, float]) -> Part:
    mesh = superellipsoid(
        a=d.body_a, b=d.body_b, c=d.body_c,
        n1=BODY_N1, n2=BODY_N2,
        taper=float(genome["body.taper"]),
    )
    return Part("body", "body_flex", mesh, color)


def _shell_part(genome: dict[str, Any], d: Dimensions,
                color: tuple[float, float, float]) -> Part:
    """Coque d'un monobloc : **un seul volume**, du sol au sommet.

    Elle remplace à elle seule le corps, le cou et la tête. Portée par
    `body_flex` comme le corps d'une capsule, et pour la même raison : c'est ce
    nœud qui reçoit la respiration et l'encaissement du lot L10. Une coque
    montée sur `head` serait tournée par le regard mais ne s'écraserait jamais
    en atterrissant.

    Les exposants sont ceux de la tête : un génome au crâne cubique donne un
    bloc cubique, un crâne rond donne une gélule. Le châssis change la
    silhouette, il n'efface pas le génome.
    """
    mesh = superellipsoid(
        a=d.head_a, b=d.shell_b, c=d.head_c,
        n1=float(genome["head.exponent_n1"]),
        n2=float(genome["head.exponent_n2"]),
        taper=float(genome["body.taper"]),
    )
    # Le maillage est centré sur lui-même ; `body_flex` est à hauteur de
    # `body_b`. On remonte donc la coque de la différence pour que son pied
    # touche le sol.
    return Part("shell", "body_flex", mesh, color,
                offset=(0.0, d.shell_b - d.body_b, 0.0))


def _neck_part(d: Dimensions, color: tuple[float, float, float]) -> Part | None:
    if d.neck_h <= 0.0:
        return None                     # tête posée sur le corps (CDC §7)
    # Le cou est allongé au-delà de sa longueur nominale pour pénétrer le corps
    # en bas et la tête en haut : c'est ce recouvrement qui le fait lire comme
    # une jointure et non comme une perle posée entre deux volumes.
    overlap = d.neck_r * proportions.NECK_OVERLAP_RATIO
    mesh = superellipsoid(
        a=d.neck_r, b=d.neck_h / 2.0 + overlap, c=d.neck_r,
        n1=NECK_N1, n2=NECK_N2, sectors=20, rings=12,
    )
    return Part("neck", "neck", mesh, color)


def _head_part(genome: dict[str, Any], d: Dimensions,
               color: tuple[float, float, float]) -> Part:
    mesh = superellipsoid(
        a=d.head_a, b=d.head_b, c=d.head_c,
        n1=float(genome["head.exponent_n1"]),
        n2=float(genome["head.exponent_n2"]),
    )
    # Le maillage est centré, le nœud est à la jointure du cou : on remonte donc
    # la tête de sa demi-hauteur.
    return Part("head", "head", mesh, color, offset=(0.0, d.head_b, 0.0))


def _v_pour_hauteur(part: float, n1: float) -> float:
    """Angle `v` qui atteint la hauteur `part` de la demi-hauteur, signé.

    Inverse `y = b·sgn(sin v)·|sin v|^n1`. Le plafond à 0,995 évite le pôle,
    où la surface se referme et où un bord d'écran n'aurait plus de largeur.
    """
    cible = min(0.995, abs(part))
    angle = float(np.arcsin(min(1.0, cible ** (1.0 / n1))))
    return angle if part >= 0.0 else -angle


def _face_part(genome: dict[str, Any], d: Dimensions) -> Part:
    """Coque faciale : portion de la surface du crâne, légèrement gonflée.

    Le CDC §9 demande « un quad légèrement bombé ». Une plaque plane posée à une
    profondeur fixe ne convient pas : le crâne bombant vers l'avant, le centre de
    la plaque s'enterre dans la tête et seuls ses bords émergent, ce qui dessine
    un nœud papillon — défaut constaté sur la planche de contact du lot L2. En
    reprenant les exposants du crâne, la coque l'épouse exactement.

    Le maillage est exprimé dans le repère centré de la tête ; le nœud `face`
    étant lui-même au centre de la tête, aucun décalage n'est nécessaire.
    """
    ratio = float(genome["face.plate_ratio"])
    half_pi = np.pi / 2.0
    n1 = float(genome["head.exponent_n1"])

    # Sur quel volume la dalle est-elle découpée. C'est **toute** la différence
    # entre les deux châssis : une dalle taillée dans une petite tête et posée
    # sur un grand bloc voit ses bords s'enfoncer, et il ne reste qu'une fente
    # sombre — voire rien du tout sur les coques les plus rondes.
    b = d.shell_b if d.monobloc else d.head_b

    if d.monobloc:
        # Les deux bords de l'écran sont visés en **hauteur**, puis convertis en
        # angles. L'écran a donc exactement la même taille sur tous les robots,
        # quel que soit l'exposant de leur coque.
        demi = MONOBLOC_SCREEN_HALF_H.get(
            str(genome.get("screen.height", "standard")),
            MONOBLOC_SCREEN_HALF_H["standard"])
        haut = _v_pour_hauteur(MONOBLOC_FACE_RISE + demi, n1)
        bas = _v_pour_hauteur(MONOBLOC_FACE_RISE - demi, n1)
        # Centré sur la **hauteur** visée et non sur l'angle médian. Les deux ne
        # coïncident pas — `y = b·sin(v)^n1` est convexe — et prendre l'angle
        # médian faisait remonter les yeux dans le haut de l'écran, d'autant
        # plus que la coque est cubique : jusqu'à un cinquième de la hauteur
        # d'écran sur les exposants les plus bas.
        v_center = _v_pour_hauteur(MONOBLOC_FACE_RISE, n1)
        v_half = 0.5 * (haut - bas)
    else:
        v_center = PLATE_V_CENTER
        v_half = half_pi * ratio * PLATE_V_SPAN

    mesh = superellipsoid_patch(
        a=d.head_a * PLATE_INFLATE,
        b=b * PLATE_INFLATE,
        c=d.head_c * PLATE_INFLATE,
        n1=n1,
        n2=float(genome["head.exponent_n2"]),
        u_center=half_pi,                       # face avant : z maximal
        u_half=half_pi * ratio * PLATE_U_SPAN
        * (MONOBLOC_PLATE_U if d.monobloc else 1.0),
        v_center=v_center,
        v_half=v_half,
        sectors=26, rings=18,
        # La coque d'un monobloc est effilée ; sans le même effilement ici, la
        # dalle s'enfonce dedans dès que le haut s'élargit.
        taper=float(genome["body.taper"]) if d.monobloc else 1.0,
    )
    return Part("face", "face", mesh, PLATE_COLOR)


def _ear_parts(genome: dict[str, Any], d: Dimensions,
               color: tuple[float, float, float],
               accent: tuple[float, float, float]) -> tuple[list[Node], list[Part]]:
    """Oreilles selon `ear.type`. Retourne les nœuds à ajouter et les parties.

    `ear.type` est traité comme un **trait génétique** et non comme un
    cosmétique déblocable : le CDC le liste dans le tableau du génome (§7), et le
    génome est l'identité du robot. La boutique du §13 vendra des habillages
    qui surchargent l'apparence à l'assemblage, sans muter le génome — d'où le
    paramètre `overrides` de `build`.
    """
    # Un monobloc n'a pas d'oreilles. Montées sur un bloc sans tête, elles se
    # lisent comme des poignées et non comme un trait de visage. La règle est
    # canonisée à la génération (`generator.normalize`) ; elle est **aussi**
    # tenue ici, qui est la dernière ligne avant le rendu — un génome édité à la
    # main ne doit pas pouvoir en faire apparaître.
    if d.monobloc:
        return [], []

    kind = genome["ear.type"]
    if kind == "none":
        return [], []

    nodes: list[Node] = []
    parts: list[Part] = []
    r = d.ear_r

    for side, sign in (("l", -1.0), ("r", 1.0)):
        node_name = f"ear_{side}"

        if kind == "antenna":
            # Tige fine partant du sommet du crâne, terminée par une bille
            # d'accent. Écartement resserré : une antenne part du dessus, pas
            # des côtés.
            nodes.append(Node(
                node_name, parent="head",
                translation=np.array(
                    [sign * d.ear_x * 0.42, d.head_b * 1.86, 0.0], dtype="f4"),
                rotation=np.array([0.0, 0.0, sign * -0.14], dtype="f4"),
            ))
            stalk = superellipsoid(a=r * 0.11, b=r * 0.78, c=r * 0.11,
                                   n1=0.72, n2=0.95, sectors=14, rings=8)
            parts.append(Part(f"ear_{side}_stalk", node_name, stalk, color,
                              offset=(0.0, r * 0.78, 0.0)))
            tip = superellipsoid(a=r * 0.26, b=r * 0.26, c=r * 0.26,
                                 n1=1.0, n2=1.0, sectors=16, rings=12)
            parts.append(Part(f"ear_{side}_tip", node_name, tip, accent,
                              offset=(0.0, r * 1.72, 0.0)))

        elif kind == "disc":
            # Disque mince plaqué sur le côté de la tête.
            nodes.append(Node(
                node_name, parent="head",
                translation=np.array([sign * d.ear_x, d.head_b, 0.0], dtype="f4"),
                rotation=np.array([0.0, 0.0, sign * 0.10], dtype="f4"),
            ))
            disc = superellipsoid(a=r * 0.26, b=r, c=r * 0.94,
                                  n1=0.85, n2=0.80, sectors=22, rings=14)
            parts.append(Part(f"ear_{side}_disc", node_name, disc, color))

        elif kind == "fin":
            # Aileron allongé, incliné vers l'arrière et vers l'extérieur.
            nodes.append(Node(
                node_name, parent="head",
                translation=np.array(
                    [sign * d.ear_x * 0.94, d.head_b * 1.18, -r * 0.30], dtype="f4"),
                rotation=np.array([0.34, 0.0, sign * 0.30], dtype="f4"),
            ))
            fin = superellipsoid(a=r * 0.20, b=r * 1.22, c=r * 0.58,
                                 n1=0.66, n2=0.72, sectors=20, rings=14)
            parts.append(Part(f"ear_{side}_fin", node_name, fin, color))

        else:                                       # pragma: no cover
            raise ValueError(f"type d'oreille inconnu : {kind!r}")

    return nodes, parts


def build(genome: dict[str, Any], overrides: dict[str, Any] | None = None) -> Robot:
    """Assemble le robot décrit par `genome`.

    `overrides` permet à la boutique du lot L7 de substituer une apparence
    (palette, type d'oreilles) **sans muter le génome** : le génome reste le
    trait de naissance, l'inventaire est un costume.

    La géométrie n'est régénérée qu'ici, donc uniquement au changement de génome
    et jamais par image (CDC §7).
    """
    t0 = time.perf_counter()

    effective = dict(genome)
    if overrides:
        effective.update(overrides)

    d = proportions.dimensions(effective)
    body_color = body_rgb(effective)
    accent = accent_rgb(effective)

    rig = _build_rig(d)

    # Le rig est le **même** pour les deux châssis — c'est déjà le parti pris du
    # cou de longueur nulle, étendu d'un cran. Seules les pièces changent : un
    # monobloc en pose une là où la capsule en pose trois.
    if d.monobloc:
        parts: list[Part] = [_shell_part(effective, d, body_color)]
    else:
        parts = [_body_part(effective, d, body_color)]
        neck = _neck_part(d, body_color)
        if neck is not None:
            parts.append(neck)
        parts.append(_head_part(effective, d, body_color))

    parts.append(_face_part(effective, d))

    ear_nodes, ear_parts = _ear_parts(effective, d, body_color, accent)
    for node in ear_nodes:
        rig.add(node)
    parts.extend(ear_parts)

    # Cosmétiques portés, un par emplacement. Ils arrivent par `overrides` et
    # non par le génome : ce sont des objets achetés, pas des traits de
    # naissance, et le §14 range l'inventaire à part précisément pour ça. Aucun
    # nœud de rig n'est ajouté — ils se greffent sur `head` et suivent donc la
    # tête sans une ligne de plus.
    #
    # La boucle porte sur `SLOTS` : ajouter une famille d'articles ne demande
    # rien ici.
    for emplacement in cosmetics.SLOTS:
        porte = str(effective.get(emplacement, "") or "")
        if porte:
            parts.extend(cosmetics.parts_for(porte, d))

    base_pose = {
        name: (node.translation.copy(), node.rotation.copy(), node.scale.copy())
        for name, node in rig.nodes.items()
    }

    return Robot(
        genome=effective,
        dims=d,
        rig=rig,
        parts=tuple(parts),
        outline_width=float(effective["outline.width"]),
        accent=accent,
        build_ms=(time.perf_counter() - t0) * 1000.0,
        base_pose=base_pose,
    )
