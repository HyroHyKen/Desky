"""Critères d'acceptation de la géométrie, lot L2 (CDC §7, §10).

Trois propriétés sont vérifiées ici et non à l'œil :

- les **normales analytiques** sont exactes, comparées à des tangentes calculées
  par différences finies ;
- le maillage est **fermé et sans triangle dégénéré**, ce qui conditionne la
  passe de contour par inverted hull du lot L3 ;
- l'assemblage est **déterministe** et tient le budget de 200 ms.

Le caractère « 20 robots visuellement distincts » du critère d'acceptation est,
lui, un jugement visuel : il se rend sur la planche produite par
`tools/contact_sheet.py`, pas ici.
"""

from __future__ import annotations

import unittest
from collections import Counter

import numpy as np

from pet.genome.generator import generate
from pet.genome.schema import defaults
from pet.geometry import proportions
from pet.geometry.builder import build
from pet.geometry.rig import ROOT, Node, Rig, rotation_x, rotation_y, rotation_z
from pet.geometry.superellipsoid import (
    Mesh,
    _spow,
    superellipsoid,
    superellipsoid_patch,
)


def _surface_point(a, b, c, n1, n2, u, v, taper=1.0):
    """Position paramétrique en scalaires, pour différences finies."""
    rad = _spow(np.array(np.cos(v)), n1)
    x = float(a * rad * _spow(np.array(np.cos(u)), n2))
    z = float(c * rad * _spow(np.array(np.sin(u)), n2))
    y = float(b * _spow(np.array(np.sin(v)), n1))
    if taper != 1.0:
        s = 1.0 + (taper - 1.0) * ((y + b) / (2.0 * b))
        x, z = x * s, z * s
    return np.array([x, y, z])


def _numeric_normal(a, b, c, n1, n2, u, v, taper=1.0, h=1e-6):
    du = (_surface_point(a, b, c, n1, n2, u + h, v, taper)
          - _surface_point(a, b, c, n1, n2, u - h, v, taper)) / (2 * h)
    dv = (_surface_point(a, b, c, n1, n2, u, v + h, taper)
          - _surface_point(a, b, c, n1, n2, u, v - h, taper)) / (2 * h)
    n = np.cross(du, dv)
    ln = float(np.linalg.norm(n))
    return n / ln if ln > 1e-12 else None


def _edge_counts(mesh: Mesh) -> Counter:
    counts: Counter = Counter()
    for tri in mesh.indices.reshape(-1, 3):
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            counts[(min(a, b), max(a, b))] += 1
    return counts


def _triangle_areas(mesh: Mesh) -> np.ndarray:
    tri = mesh.indices.reshape(-1, 3)
    p = mesh.positions
    e1 = p[tri[:, 1]] - p[tri[:, 0]]
    e2 = p[tri[:, 2]] - p[tri[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)


class SuperellipsoidTest(unittest.TestCase):
    CASES = [
        ("sphère", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        ("ellipsoïde", 0.6, 1.1, 0.8, 1.0, 1.0, 1.0),
        ("cube arrondi", 0.6, 0.6, 0.6, 0.40, 0.40, 1.0),
        ("exposants mixtes", 0.7, 0.5, 0.7, 0.35, 1.00, 1.0),
        ("effilé 0.70", 0.5, 0.8, 0.45, 1.0, 1.0, 0.70),
        ("effilé 1.15", 0.5, 0.8, 0.45, 0.8, 0.9, 1.15),
    ]

    def test_normales_exactes(self) -> None:
        """Les normales analytiques doivent coïncider avec les tangentes.

        Y compris sur les cas effilés : c'est ce qui valide la correction par
        transposée inverse du jacobien de l'effilement.
        """
        rng = np.random.default_rng(7)
        for label, a, b, c, n1, n2, taper in self.CASES:
            worst = 0.0
            for _ in range(300):
                u = rng.uniform(-np.pi, np.pi)
                v = rng.uniform(-np.pi / 2 * 0.92, np.pi / 2 * 0.92)
                if min(abs(np.cos(u)), abs(np.sin(u))) < 0.05:
                    continue                    # arêtes du cube arrondi
                nn = _numeric_normal(a, b, c, n1, n2, u, v, taper)
                if nn is None:
                    continue
                nrad = _spow(np.array(np.cos(v)), 2.0 - n1)
                na = np.array([
                    float((1.0 / a) * nrad * _spow(np.array(np.cos(u)), 2.0 - n2)),
                    float((1.0 / b) * _spow(np.array(np.sin(v)), 2.0 - n1)),
                    float((1.0 / c) * nrad * _spow(np.array(np.sin(u)), 2.0 - n2)),
                ])
                if taper != 1.0:
                    x, y, z = _surface_point(a, b, c, n1, n2, u, v)
                    s = 1.0 + (taper - 1.0) * ((y + b) / (2.0 * b))
                    sp = (taper - 1.0) / (2.0 * b)
                    na = np.array([na[0] / s,
                                   na[1] - sp * (x * na[0] + z * na[2]) / s,
                                   na[2] / s])
                na = na / np.linalg.norm(na)
                if float(np.dot(na, nn)) < 0:
                    nn = -nn
                ang = np.degrees(np.arccos(np.clip(float(np.dot(na, nn)), -1, 1)))
                worst = max(worst, ang)
            self.assertLess(worst, 1.0, f"{label} : écart max {worst:.4f}°")

    def test_normales_unitaires_et_finies(self) -> None:
        for label, a, b, c, n1, n2, taper in self.CASES:
            m = superellipsoid(a, b, c, n1, n2, taper=taper)
            self.assertTrue(np.isfinite(m.vertices).all(), label)
            lengths = np.linalg.norm(m.normals, axis=1)
            np.testing.assert_allclose(lengths, 1.0, atol=1e-5,
                                       err_msg=f"normales non unitaires : {label}")

    def test_maillage_ferme(self) -> None:
        """Chaque arête est partagée par exactement deux triangles.

        C'est la condition qui garantit qu'aucune fente n'apparaîtra dans le
        contour extrudé du lot L3 : une arête de bord y produirait un trou.
        """
        for label, a, b, c, n1, n2, taper in self.CASES:
            m = superellipsoid(a, b, c, n1, n2, taper=taper)
            counts = _edge_counts(m)
            mauvaises = {e: n for e, n in counts.items() if n != 2}
            self.assertEqual(mauvaises, {}, f"{label} : {len(mauvaises)} arêtes non partagées")

    def test_caracteristique_d_euler(self) -> None:
        """V − E + F = 2 : la surface est bien une sphère topologique."""
        m = superellipsoid(0.6, 0.7, 0.55, 0.5, 0.8)
        v = m.vertex_count
        e = len(_edge_counts(m))
        f = m.triangle_count
        self.assertEqual(v - e + f, 2, f"V={v} E={e} F={f}")

    def test_aucun_triangle_degenere(self) -> None:
        for label, a, b, c, n1, n2, taper in self.CASES:
            areas = _triangle_areas(superellipsoid(a, b, c, n1, n2, taper=taper))
            self.assertEqual(int((areas < 1e-9).sum()), 0, label)

    def test_bornes_conformes_aux_demi_dimensions(self) -> None:
        a, b, c = 0.7, 0.5, 0.3
        lo, hi = superellipsoid(a, b, c, 1.0, 1.0).bounds()
        np.testing.assert_allclose(hi, [a, b, c], atol=1e-5)
        np.testing.assert_allclose(lo, [-a, -b, -c], atol=1e-5)

    def test_exposant_bas_donne_une_forme_plus_cubique(self) -> None:
        """CDC §7 : sphère à 1.0, cube arrondi à 0.35.

        Mesuré sur la diagonale, où un cube s'éloigne du centre bien plus qu'une
        sphère de mêmes demi-dimensions.
        """
        rayons = []
        for n in (1.0, 0.60, 0.35):
            m = superellipsoid(1.0, 1.0, 1.0, n, n)
            rayons.append(float(np.linalg.norm(m.positions, axis=1).max()))
        self.assertLess(rayons[0], rayons[1])
        self.assertLess(rayons[1], rayons[2])
        self.assertAlmostEqual(rayons[0], 1.0, delta=0.02, msg="n=1 doit être la sphère")

    def test_effilement_exact_sommet_par_sommet(self) -> None:
        """Le facteur d'effilement vaut exactement 1 + (taper−1)·(y+b)/2b.

        Testé par appariement de sommets plutôt que par bandes de latitude :
        l'effilement ne touche pas y, donc les deux maillages ont exactement les
        mêmes sommets aux mêmes indices, et le rapport des abscisses doit valoir
        le facteur prédit — sans seuil ni tolérance de bande à choisir.
        """
        b = 0.8
        for taper in (0.6, 0.85, 1.15):
            droit = superellipsoid(0.5, b, 0.45, 0.9, 1.0)
            effile = superellipsoid(0.5, b, 0.45, 0.9, 1.0, taper=taper)

            y = droit.positions[:, 1]
            np.testing.assert_allclose(effile.positions[:, 1], y, atol=1e-6,
                                       err_msg="l'effilement ne doit pas déplacer y")

            attendu = 1.0 + (taper - 1.0) * ((y + b) / (2.0 * b))
            for axe in (0, 2):
                sel = np.abs(droit.positions[:, axe]) > 1e-4
                obtenu = effile.positions[sel, axe] / droit.positions[sel, axe]
                np.testing.assert_allclose(
                    obtenu, attendu[sel], rtol=2e-4,
                    err_msg=f"taper={taper}, axe={axe}")

            # Ancrage : facteur exactement 1 à la base, exactement taper au sommet.
            base = int(np.argmin(y))
            sommet = int(np.argmax(y))
            self.assertAlmostEqual(float(attendu[base]), 1.0, places=5)
            self.assertAlmostEqual(float(attendu[sommet]), taper, places=5)

    def test_arguments_invalides_refuses(self) -> None:
        for kwargs in ({"a": 0.0}, {"b": -1.0}, {"n1": 0.0}, {"n2": 2.5},
                       {"sectors": 2}, {"rings": 1}):
            base = {"a": 1.0, "b": 1.0, "c": 1.0, "n1": 1.0, "n2": 1.0}
            base.update(kwargs)
            with self.assertRaises(ValueError, msg=str(kwargs)):
                superellipsoid(**base)


class PatchTest(unittest.TestCase):
    def _patch(self, **kw):
        args = dict(a=0.6, b=0.55, c=0.58, n1=0.7, n2=0.6,
                    u_center=np.pi / 2, u_half=0.6, v_center=-0.16, v_half=0.45)
        args.update(kw)
        return superellipsoid_patch(**args)

    def test_coque_ouverte(self) -> None:
        """Une coque a un bord : certaines arêtes n'appartiennent qu'à un triangle."""
        counts = _edge_counts(self._patch())
        self.assertGreater(sum(1 for n in counts.values() if n == 1), 0)
        self.assertEqual(sum(1 for n in counts.values() if n > 2), 0)

    def test_normales_tournees_vers_l_exterieur(self) -> None:
        m = self._patch()
        dots = np.einsum("ij,ij->i", m.positions, m.normals)
        self.assertTrue((dots > 0).all(), "une normale rentre dans le volume")

    def test_centree_sur_l_avant(self) -> None:
        """La coque doit être centrée en x et regarder vers +z."""
        m = self._patch()
        lo, hi = m.bounds()
        self.assertAlmostEqual(float(lo[0]), -float(hi[0]), delta=1e-5)
        self.assertGreater(float(m.positions[:, 2].min()), 0.0)

    def test_l_etendue_suit_le_parametre(self) -> None:
        petite = self._patch(u_half=0.35, v_half=0.28)
        grande = self._patch(u_half=0.80, v_half=0.60)
        self.assertLess(petite.bounds()[1][0], grande.bounds()[1][0])

    def test_pas_de_triangle_degenere(self) -> None:
        self.assertEqual(int((_triangle_areas(self._patch()) < 1e-12).sum()), 0)

    def test_arguments_invalides_refuses(self) -> None:
        for kw in ({"u_half": 0.0}, {"v_half": -0.2}, {"a": 0.0}, {"sectors": 1}):
            with self.assertRaises(ValueError, msg=str(kw)):
                self._patch(**kw)


class RigTest(unittest.TestCase):
    def test_composition_hierarchique(self) -> None:
        rig = Rig()
        rig.add(Node("a", parent=ROOT, translation=np.array([1.0, 0.0, 0.0], dtype="f4")))
        rig.add(Node("b", parent="a", translation=np.array([0.0, 2.0, 0.0], dtype="f4")))
        world = rig.world_matrices()
        np.testing.assert_allclose(world["b"][:3, 3], [1.0, 2.0, 0.0], atol=1e-6)

    def test_rotation_du_parent_deplace_l_enfant(self) -> None:
        rig = Rig()
        rig.add(Node("a", parent=ROOT,
                     rotation=np.array([0.0, np.pi / 2, 0.0], dtype="f4")))
        rig.add(Node("b", parent="a", translation=np.array([1.0, 0.0, 0.0], dtype="f4")))
        world = rig.world_matrices()
        # Une rotation d'un quart de tour autour de Y envoie +X sur −Z.
        np.testing.assert_allclose(world["b"][:3, 3], [0.0, 0.0, -1.0], atol=1e-6)

    def test_matrices_de_rotation_orthonormales(self) -> None:
        for fn in (rotation_x, rotation_y, rotation_z):
            m = fn(0.7)[:3, :3]
            np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-6, err_msg=fn.__name__)
            self.assertAlmostEqual(float(np.linalg.det(m)), 1.0, places=5, msg=fn.__name__)

    def test_parent_inconnu_refuse(self) -> None:
        rig = Rig()
        with self.assertRaises(ValueError):
            rig.add(Node("orphelin", parent="fantome"))

    def test_doublon_refuse(self) -> None:
        rig = Rig()
        rig.add(Node("a", parent=ROOT))
        with self.assertRaises(ValueError):
            rig.add(Node("a", parent=ROOT))

    def test_profondeur(self) -> None:
        rig = Rig()
        rig.add(Node("a", parent=ROOT))
        rig.add(Node("b", parent="a"))
        self.assertEqual((rig.depth(ROOT), rig.depth("a"), rig.depth("b")), (0, 1, 2))


class BuilderTest(unittest.TestCase):
    def test_le_robot_se_tient_au_sol(self) -> None:
        """y_min doit être exactement 0 : le pet repose sur le sol, pas dedans."""
        for seed in range(1, 120):
            robot = build(generate(seed))
            lo, _ = robot.bounds()
            self.assertAlmostEqual(float(lo[1]), 0.0, places=4, msg=f"graine {seed}")

    def test_topologie_du_rig_constante(self) -> None:
        """CDC §10, et condition pour que le lot L4 n'ait qu'un chemin d'animation."""
        base = {ROOT, "body", "neck", "head", "face"}
        for seed in range(1, 80):
            robot = build(generate(seed))
            noeuds = set(robot.rig.order)
            self.assertTrue(base.issubset(noeuds), f"graine {seed} : {noeuds}")
            if robot.genome["ear.type"] != "none":
                self.assertIn("ear_l", noeuds)
                self.assertIn("ear_r", noeuds)

    def test_parties_selon_le_type_d_oreille(self) -> None:
        attendu = {"none": 0, "disc": 2, "fin": 2, "antenna": 4}
        vus = set()
        for seed in range(1, 200):
            genome = generate(seed)
            kind = genome["ear.type"]
            if kind in vus:
                continue
            vus.add(kind)
            robot = build(genome)
            oreilles = [p for p in robot.parts if p.name.startswith("ear_")]
            self.assertEqual(len(oreilles), attendu[kind], kind)
            if len(vus) == 4:
                break
        self.assertEqual(vus, {"none", "disc", "fin", "antenna"},
                         "les quatre types doivent apparaître en 200 graines")

    def test_cou_absent_si_longueur_nulle(self) -> None:
        genome = dict(defaults())
        genome["neck.length"] = 0.0
        robot = build(genome)
        self.assertNotIn("neck", [p.name for p in robot.parts])
        self.assertIn("neck", robot.rig, "le nœud doit rester, seule la partie disparaît")

    def test_assemblage_deterministe_au_bit(self) -> None:
        """Même génome, même géométrie — comparée octet par octet."""
        for seed in (3, 77, 4242):
            a, b = build(generate(seed)), build(generate(seed))
            self.assertEqual(len(a.parts), len(b.parts))
            for pa, pb in zip(a.parts, b.parts):
                self.assertEqual(pa.name, pb.name)
                self.assertEqual(pa.mesh.vertices.tobytes(), pb.mesh.vertices.tobytes(),
                                 f"graine {seed}, partie {pa.name}")
                self.assertEqual(pa.mesh.indices.tobytes(), pb.mesh.indices.tobytes())

    def test_budget_de_construction(self) -> None:
        """CDC : la régénération complète doit rester sous 200 ms."""
        pire = max(build(generate(seed)).build_ms for seed in range(1, 60))
        self.assertLess(pire, 200.0, f"pire construction : {pire:.1f} ms")

    def test_geometrie_finie(self) -> None:
        for seed in range(1, 60):
            robot = build(generate(seed))
            for part in robot.parts:
                self.assertTrue(np.isfinite(part.mesh.vertices).all(),
                                f"graine {seed}, partie {part.name}")

    def test_les_surcharges_ne_mutent_pas_le_genome(self) -> None:
        """La boutique du lot L7 habille le robot sans toucher son identité."""
        genome = generate(11)
        avant = dict(genome)
        robot = build(genome, overrides={"ear.type": "antenna",
                                         "palette.body": "menthe-pale"})
        self.assertEqual(genome, avant, "le génome d'origine a été modifié")
        self.assertEqual(robot.genome["ear.type"], "antenna")
        self.assertIn("ear_l", robot.rig)

    def test_dimensions_partagees_avec_la_viabilite(self) -> None:
        """Générateur et assembleur doivent lire les mêmes dimensions.

        S'ils divergeaient, une règle de cohérence pourrait rejeter des génomes
        viables ou en accepter d'inviables.
        """
        genome = generate(21)
        robot = build(genome)
        self.assertEqual(robot.dims, proportions.dimensions(genome))

    def test_le_trait_est_un_caractere_du_robot(self) -> None:
        """Décision §17.3 : l'épaisseur du contour est génétique."""
        largeurs = {build(generate(s)).outline_width for s in range(1, 40)}
        self.assertGreater(len(largeurs), 10, "le trait ne varie pas d'un robot à l'autre")


if __name__ == "__main__":
    unittest.main()
