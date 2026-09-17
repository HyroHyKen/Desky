"""Primitive paramétrique : le superellipsoïde (CDC §7).

Une seule formule couvre la sphère, le cube arrondi et la capsule, ce qui
maximise la variété morphologique pour un coût minimal. Le CDC la donne avec
l'axe polaire sur z ; ici il est sur **y**, pour coïncider avec le repère du rig
(Y vers le haut). C'est un simple renommage d'axes, pas une modification de la
formule.

    x = a · sgn(cos v)|cos v|^n1 · sgn(cos u)|cos u|^n2
    z = c · sgn(cos v)|cos v|^n1 · sgn(sin u)|sin u|^n2
    y = b · sgn(sin v)|sin v|^n1

    u ∈ [-π, π[ , v ∈ [-π/2, π/2]

**Normales analytiques**, jamais moyennées sur les faces (CDC §7) : la normale
d'un superquadrique s'obtient en remplaçant les exposants n par 2−n, ce qui est
exact et ne coûte qu'une puissance de plus par sommet.

Deux propriétés du maillage produit, qui comptent pour la passe de contour du
lot L3 :

- **Pas de couture.** Les indices bouclent modulo `sectors` au lieu de dupliquer
  la colonne u = ±π. Il n'existe donc aucune paire de sommets coïncidents dont
  les normales pourraient diverger et ouvrir une fente dans le trait.
- **Pas de triangle dégénéré.** Les pôles sont deux sommets uniques coiffés de
  triangles, et non une rangée entière de sommets confondus.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Grille par défaut : le CDC §7 indique que 32 × 24 suffit.
DEFAULT_SECTORS = 32
DEFAULT_RINGS = 24


@dataclass(frozen=True)
class Mesh:
    """Maillage prêt pour le VBO : positions et normales entrelacées."""

    vertices: np.ndarray        # (N, 6) float32 : px py pz nx ny nz
    indices: np.ndarray         # (M,) int32, multiple de 3

    # Coordonnées 2D de la surface, dans [-1, 1]², et seulement pour les coques.
    # C'est l'espace dans lequel le fragment shader du visage dessine les yeux
    # par SDF (CDC §9) : la coque faciale est bombée en 3D, mais le dessin qui
    # s'y applique est plan.
    uv: np.ndarray | None = None            # (N, 2) float32

    # Un volume fermé peut être extrudé pour la passe de contour ; une coque
    # ouverte non — son bord franc produirait un liseré sur tout le pourtour du
    # rectangle. La passe de contour du lot L3 s'en sert pour trier.
    closed: bool = True

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.indices.size // 3)

    @property
    def positions(self) -> np.ndarray:
        return self.vertices[:, :3]

    @property
    def normals(self) -> np.ndarray:
        return self.vertices[:, 3:6]

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.positions.min(axis=0), self.positions.max(axis=0)


def _spow(base: np.ndarray, exponent: float) -> np.ndarray:
    """sgn(base)·|base|^exponent, sans NaN en zéro."""
    return np.sign(base) * np.power(np.abs(base), exponent)


def _grid(sectors: int, rings: int) -> tuple[np.ndarray, np.ndarray]:
    """Longitudes (sans doublon de couture) et latitudes intérieures."""
    u = np.linspace(-np.pi, np.pi, sectors, endpoint=False)
    v = np.linspace(-np.pi / 2.0, np.pi / 2.0, rings + 1)[1:-1]   # pôles exclus
    return u, v


def _indices(sectors: int, interior_rings: int, first_ring: int,
             south: int, north: int) -> np.ndarray:
    """Triangles : calotte sud, bandes intermédiaires, calotte nord.

    Enroulement choisi pour que les faces regardent vers l'extérieur avec la
    projection à Y inversé retenue au lot L0 (cf. `render.toon._ortho`).
    """
    tris: list[tuple[int, int, int]] = []

    def ring_vertex(ring: int, sector: int) -> int:
        return first_ring + ring * sectors + (sector % sectors)

    for s in range(sectors):
        tris.append((south, ring_vertex(0, s + 1), ring_vertex(0, s)))

    for r in range(interior_rings - 1):
        for s in range(sectors):
            a = ring_vertex(r, s)
            b = ring_vertex(r, s + 1)
            c = ring_vertex(r + 1, s)
            d = ring_vertex(r + 1, s + 1)
            tris.append((a, b, c))
            tris.append((b, d, c))

    last = interior_rings - 1
    for s in range(sectors):
        tris.append((north, ring_vertex(last, s), ring_vertex(last, s + 1)))

    return np.array(tris, dtype="i4").reshape(-1)


def superellipsoid(
    a: float, b: float, c: float,
    n1: float = 1.0, n2: float = 1.0,
    sectors: int = DEFAULT_SECTORS, rings: int = DEFAULT_RINGS,
    taper: float = 1.0,
) -> Mesh:
    """Superellipsoïde de demi-dimensions (a, b, c) et d'exposants (n1, n2).

    `n1 = n2 = 1` donne l'ellipsoïde exact ; vers 0.35, un cube arrondi.

    `taper` applique un effilement linéaire sur la hauteur — le rapport
    épaules/base du CDC §7 — que la formule du superellipsoïde ne sait pas
    exprimer seule. Les normales sont alors corrigées par la transposée inverse
    du jacobien de la déformation, calculée exactement : les recalculer par
    moyennage de faces trahirait la précision analytique du reste.
    """
    if min(a, b, c) <= 0.0:
        raise ValueError("les demi-dimensions doivent être strictement positives")
    if not (0.0 < n1 <= 2.0 and 0.0 < n2 <= 2.0):
        raise ValueError("les exposants doivent être dans ]0, 2]")
    if sectors < 3 or rings < 2:
        raise ValueError("grille trop grossière")

    u, v = _grid(sectors, rings)
    uu, vv = np.meshgrid(u, v, indexing="xy")       # (rings-1, sectors)

    cv, sv = np.cos(vv), np.sin(vv)
    cu, su = np.cos(uu), np.sin(uu)

    # Positions
    rad = _spow(cv, n1)
    px = a * rad * _spow(cu, n2)
    pz = c * rad * _spow(su, n2)
    py = b * _spow(sv, n1)

    # Normales analytiques : mêmes termes, exposants 2 − n.
    nrad = _spow(cv, 2.0 - n1)
    nx = (1.0 / a) * nrad * _spow(cu, 2.0 - n2)
    nz = (1.0 / c) * nrad * _spow(su, 2.0 - n2)
    ny = (1.0 / b) * _spow(sv, 2.0 - n1)

    pos = np.stack([px, py, pz], axis=-1).reshape(-1, 3)
    nrm = np.stack([nx, ny, nz], axis=-1).reshape(-1, 3)

    # Pôles : ajoutés à part, en sommets uniques.
    poles_pos = np.array([[0.0, -b, 0.0], [0.0, b, 0.0]])
    poles_nrm = np.array([[0.0, -1.0, 0.0], [0.0, 1.0, 0.0]])
    pos = np.vstack([poles_pos, pos])
    nrm = np.vstack([poles_nrm, nrm])

    if taper != 1.0:
        pos, nrm = _apply_taper(pos, nrm, b, taper)

    # Une normale nulle ne peut survenir qu'en cas de sous-débordement ; on la
    # remplace plutôt que de propager un NaN dans le shader.
    lengths = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, lengths, out=np.tile([0.0, 1.0, 0.0], (len(nrm), 1)),
                    where=lengths > 1e-12)

    vertices = np.hstack([pos, nrm]).astype("f4")
    indices = _indices(sectors, len(v), first_ring=2, south=0, north=1)
    return Mesh(vertices=np.ascontiguousarray(vertices), indices=indices, closed=True)


def _apply_taper(
    pos: np.ndarray, nrm: np.ndarray, b: float, taper: float
) -> tuple[np.ndarray, np.ndarray]:
    """Effilement linéaire sur la hauteur, normales corrigées exactement.

    La déformation est x' = s(y)·x, z' = s(y)·z, y' = y, avec s linéaire de 1 à
    la base à `taper` au sommet. Son jacobien vaut

        J = [[s,  s'·x, 0],
             [0,  1,    0],
             [0,  s'·z, s]]

    et une normale se transforme en J⁻ᵀn. Résoudre Jᵀm = n donne directement
    m = (n₀/s, n₁ − s'(x·n₀ + z·n₂)/s, n₂/s), sans inverser de matrice.
    """
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    t = (y + b) / (2.0 * b)                         # 0 à la base, 1 au sommet
    s = 1.0 + (taper - 1.0) * t
    s_prime = (taper - 1.0) / (2.0 * b)

    n0, n1c, n2 = nrm[:, 0], nrm[:, 1], nrm[:, 2]
    m0 = n0 / s
    m2 = n2 / s
    m1 = n1c - s_prime * (x * n0 + z * n2) / s

    new_pos = np.stack([x * s, y, z * s], axis=-1)
    new_nrm = np.stack([m0, m1, m2], axis=-1)
    return new_pos, new_nrm


def superellipsoid_patch(
    a: float, b: float, c: float,
    n1: float, n2: float,
    u_center: float, u_half: float,
    v_center: float, v_half: float,
    sectors: int = 24, rings: int = 18,
    taper: float = 1.0,
) -> Mesh:
    """Portion ouverte de superellipsoïde : une coque, pas un volume fermé.

    Sert la dalle faciale (CDC §9, « un quad légèrement bombé »). Une plaque
    plane ne convient pas : posée à une profondeur fixe devant un crâne qui
    bombe, son centre est enterré dans la tête et seuls ses bords émergent, ce
    qui dessine un nœud papillon au lieu d'un visage. En reprenant les exposants
    de la tête et un rayon très légèrement supérieur, la coque épouse le crâne
    comme une visière.

    Aucune boucle et aucun pôle : la grille est ouverte, donc les sommets de bord
    ne sont pas partagés. C'est voulu — c'est une surface à bord franc.

    Repère : la face avant est en u = π/2, puisque z est maximal là où
    sgn(sin u)|sin u|^n2 vaut 1.

    `taper` reprend exactement celui de `superellipsoid`, et il n'est pas
    décoratif : la dalle faciale d'un monobloc est découpée dans la surface de
    sa coque, et si la coque est effilée alors que la dalle ne l'est pas, la
    dalle s'enfonce dedans dès que l'effilement élargit le haut. Mesuré au lot
    L17 : sur un `taper` de 1,08, la coque atteignait z = 0,515 et la dalle
    0,512 — le visage disparaissait entièrement.
    """
    if min(a, b, c) <= 0.0:
        raise ValueError("les demi-dimensions doivent être strictement positives")
    if u_half <= 0.0 or v_half <= 0.0:
        raise ValueError("l'étendue de la coque doit être strictement positive")
    if sectors < 2 or rings < 2:
        raise ValueError("grille trop grossière")

    u = np.linspace(u_center - u_half, u_center + u_half, sectors + 1)
    v = np.linspace(v_center - v_half, v_center + v_half, rings + 1)
    uu, vv = np.meshgrid(u, v, indexing="xy")

    cv, sv = np.cos(vv), np.sin(vv)
    cu, su = np.cos(uu), np.sin(uu)

    rad = _spow(cv, n1)
    px = a * rad * _spow(cu, n2)
    pz = c * rad * _spow(su, n2)
    py = b * _spow(sv, n1)

    nrad = _spow(cv, 2.0 - n1)
    nx = (1.0 / a) * nrad * _spow(cu, 2.0 - n2)
    nz = (1.0 / c) * nrad * _spow(su, 2.0 - n2)
    ny = (1.0 / b) * _spow(sv, 2.0 - n1)

    pos = np.stack([px, py, pz], axis=-1).reshape(-1, 3)
    nrm = np.stack([nx, ny, nz], axis=-1).reshape(-1, 3)

    if taper != 1.0:
        pos, nrm = _apply_taper(pos, nrm, b, taper)

    lengths = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, lengths, out=np.tile([0.0, 0.0, 1.0], (len(nrm), 1)),
                    where=lengths > 1e-12)

    cols = sectors + 1
    tris: list[tuple[int, int, int]] = []
    for r in range(rings):
        for s in range(sectors):
            i0 = r * cols + s
            i1 = i0 + 1
            i2 = i0 + cols
            i3 = i2 + 1
            tris.append((i0, i1, i2))
            tris.append((i1, i3, i2))

    # UV dans [-1, 1]², orientées comme le voit le spectateur : s croît vers la
    # droite de l'écran et t vers le haut. Le sens de s est inversé par rapport
    # à u parce que x = a·|cos u|^n2 décroît quand u croît au-delà de π/2.
    ss = -(uu - u_center) / u_half
    tt = (vv - v_center) / v_half
    uv = np.stack([ss, tt], axis=-1).reshape(-1, 2).astype("f4")

    vertices = np.hstack([pos, nrm]).astype("f4")
    return Mesh(vertices=np.ascontiguousarray(vertices),
                indices=np.array(tris, dtype="i4").reshape(-1),
                uv=np.ascontiguousarray(uv), closed=False)
