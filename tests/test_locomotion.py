"""Critères d'acceptation de la locomotion, lot L5b.

Le lot **étend le CDC** : le §6 ne prévoit que le déplacement à la souris, la
locomotion autonome n'y est qu'implicite dans trois des neuf actions du §12. Les
critères viennent donc de la définition du lot, plus l'exigence du §10 qui
s'applique à tout mouvement visible : aucune interpolation linéaire.

Aucun GPU, aucune fenêtre : le terrain est injectable, donc les scénarios
s'écrivent à la main — y compris ceux qu'on ne peut pas reproduire sur la
machine de dev, comme deux écrans non contigus.
"""

from __future__ import annotations

import unittest

import numpy as np

from pet.anim.locomotion import (
    ARRIVE_EPS,
    FLOOR_BLEND_PX,
    GAITS,
    MAX_LEAN,
    RETARGET_EPS,
    STUCK_SECONDS,
    USER_COOLDOWN,
    WANDER_RANGE,
    Ground,
    Locomotion,
    Terrain,
)
from pet.app import win32

PET = 150
STEP = 1.0 / 120.0


def terrain_deux_ecrans(step: float = 130.0) -> Terrain:
    """Deux écrans **adjacents** de hauteurs de sol différentes."""
    return Terrain.from_grounds([
        Ground("gauche", 0.0, 1100.0, 300.0),
        Ground("droite", 1100.0, 2200.0, 300.0 - step),
    ], PET)


def terrain_disjoint() -> Terrain:
    """Deux écrans séparés par un vide : infranchissable à pied."""
    return Terrain.from_grounds([
        Ground("gauche", 0.0, 1000.0, 300.0),
        Ground("droite", 1600.0, 2600.0, 300.0),
    ], PET)


def voyage(loco: Locomotion, limite: float = 30.0) -> list[tuple[float, float]]:
    """Simule jusqu'à l'arrêt. Retourne les couples (x, y de fenêtre)."""
    trace: list[tuple[float, float]] = []
    t = 0.0
    while loco.travelling and t < limite:
        loco.update(STEP)
        trace.append((loco.x, loco.window_y))
        t += STEP
    return trace


class TerrainTest(unittest.TestCase):
    def test_ecrans_adjacents_forment_une_bande_continue(self) -> None:
        """Régression du défaut trouvé sur la première frise.

        En rentrant les bornes moniteur par moniteur, il subsistait entre deux
        écrans un trou de la largeur du pet où son centre ne pouvait pas se
        trouver. Le saut le franchissait par chance ; le glissement s'y coinçait.
        """
        terrain = terrain_deux_ecrans()
        self.assertEqual(len(terrain.segments), 1,
                         "deux écrans qui se touchent font une seule bande")
        # Aucun x de la bande ne doit être déplacé par le clamp.
        for x in np.linspace(terrain.span[0], terrain.span[1], 200):
            self.assertAlmostEqual(terrain.clamp_x(float(x)), float(x), places=6)

    def test_ecrans_disjoints_ne_sont_pas_franchissables(self) -> None:
        terrain = terrain_disjoint()
        self.assertEqual(len(terrain.segments), 2)
        # Un point dans le vide est ramené au bord de la bande la plus proche.
        milieu = terrain.clamp_x(1300.0)
        self.assertNotAlmostEqual(milieu, 1300.0, places=1)
        self.assertIn(round(milieu), (925, 1675))

    def test_bornes_en_centre(self) -> None:
        terrain = terrain_deux_ecrans()
        gauche, droite = terrain.span
        self.assertAlmostEqual(gauche, PET / 2.0)
        self.assertAlmostEqual(droite, 2200.0 - PET / 2.0)

    def test_le_sol_est_adouci_a_la_frontiere(self) -> None:
        terrain = terrain_deux_ecrans(step=130.0)
        avant = terrain.floor_at(1100.0 - FLOOR_BLEND_PX - 10.0)
        apres = terrain.floor_at(1100.0 + FLOOR_BLEND_PX + 10.0)
        milieu = terrain.floor_at(1100.0)
        self.assertAlmostEqual(avant, 300.0)
        self.assertAlmostEqual(apres, 170.0)
        self.assertAlmostEqual(milieu, 235.0, delta=1.0)

    def test_le_sol_ne_saute_jamais(self) -> None:
        """Aucun pas visible : la pente est bornée sur toute la bande."""
        terrain = terrain_deux_ecrans(step=200.0)
        xs = np.arange(terrain.span[0], terrain.span[1], 2.0)
        sols = np.array([terrain.floor_at(float(x)) for x in xs])
        pas_max = float(np.abs(np.diff(sols)).max())
        self.assertLess(pas_max, 6.0, f"pas de sol de {pas_max:.1f} px")

    def test_ecran_trop_petit_est_ecarte(self) -> None:
        class FauxMoniteur:
            def __init__(self, work, key):
                self.work, self.key = work, key
        terrain = Terrain.from_monitors(
            [FauxMoniteur((0, 0, 80, 80), "minuscule")], PET, PET)
        self.assertTrue(terrain.empty)

    def test_les_moniteurs_reels(self) -> None:
        """La machine de dev : trois écrans, dont deux à coordonnées négatives."""
        terrain = Terrain.from_monitors(win32.list_monitors(), 220, 220)
        self.assertFalse(terrain.empty)
        gauche, droite = terrain.span
        self.assertLess(gauche, droite)
        # Tous les sols sont dans les zones de travail réelles.
        for ground in terrain.grounds:
            self.assertLess(ground.x_left, ground.x_right)


class TravelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.terrain = terrain_deux_ecrans()

    def _loco(self, gait: str = "hop", x: float = 300.0) -> Locomotion:
        loco = Locomotion(self.terrain, PET, PET, x=x, gait=gait, seed=8)
        loco.set_home(x)
        return loco

    def test_les_deux_demarches_arrivent(self) -> None:
        for gait in GAITS:
            loco = self._loco(gait)
            self.assertTrue(loco.go_to(1900.0), gait)
            voyage(loco)
            self.assertFalse(loco.travelling, gait)
            self.assertAlmostEqual(loco.x, 1900.0,
                                   delta=ARRIVE_EPS * PET + 1.0, msg=gait)
            self.assertEqual(loco.abandons, 0, gait)

    def test_ne_sort_jamais_de_la_bande(self) -> None:
        gauche, droite = self.terrain.span
        for gait in GAITS:
            for cible in (-5000.0, 5000.0):
                loco = self._loco(gait, x=1100.0)
                loco.go_to(cible)
                for x, _ in voyage(loco):
                    self.assertGreaterEqual(x, gauche - 0.5, gait)
                    self.assertLessEqual(x, droite + 0.5, gait)

    def test_aucun_saut_de_hauteur_au_franchissement(self) -> None:
        """Le pas de sol entre écrans ne doit jamais se voir."""
        loco = self._loco("glide", x=600.0)
        loco.go_to(1600.0)
        ys = [y for _, y in voyage(loco)]
        # En glissement, l'arc est nul : le y ne suit que le sol.
        pas_max = max(abs(b - a) for a, b in zip(ys, ys[1:]))
        self.assertLess(pas_max, 6.0, f"saut de {pas_max:.1f} px")

    def test_le_saut_decolle_puis_repose(self) -> None:
        loco = self._loco("hop", x=300.0)
        loco.go_to(1000.0)
        arcs = []
        while loco.travelling:
            loco.update(STEP)
            arcs.append(loco.arc)
        self.assertGreater(max(arcs), 0.15 * PET, "l'arc doit être visible")
        self.assertAlmostEqual(loco.arc, 0.0, places=6, msg="il finit au sol")
        self.assertGreater(loco.hops, 3)

    def test_aucun_mouvement_lineaire(self) -> None:
        """Exigence du CDC §10, appliquée au déplacement.

        La dispersion est mesurée sur **toute** la trajectoire, pauses
        comprises. Un premier essai ne gardait que les images où le pet avance,
        et concluait que le saut était linéaire : à l'intérieur d'un saut la
        vitesse horizontale *est* constante — c'est la définition d'un
        projectile — et le filtre jetait justement les accroupissements et les
        pauses, c'est-à-dire tout ce qui fait le rythme. La non-linéarité du
        saut est portée par son arc, vérifiée séparément ci-dessous.
        """
        for gait in GAITS:
            loco = self._loco(gait, x=300.0)
            loco.go_to(1800.0)
            xs = [x for x, _ in voyage(loco)]
            vitesses = np.abs(np.diff(np.array(xs))) / STEP
            self.assertGreater(vitesses.size, 60, gait)
            variation = float(vitesses.std() / vitesses.mean())
            self.assertGreater(variation, 0.15,
                               f"{gait} : vitesse trop constante ({variation:.3f})")

    def test_l_arc_du_saut_est_parabolique_et_non_triangulaire(self) -> None:
        """C'est l'arc qui porte la non-linéarité du saut.

        Distinguer une parabole d'une rampe se fait sur le rapport de la moyenne
        au maximum : deux tiers pour une parabole, une moitié pour un triangle.
        """
        loco = self._loco("hop", x=300.0)
        loco.go_to(1200.0)

        vol: list[float] = []
        vols: list[list[float]] = []
        while loco.travelling:
            loco.update(STEP)
            if loco.arc > 0.0:
                vol.append(loco.arc)
            elif vol:
                vols.append(vol)
                vol = []

        self.assertGreater(len(vols), 2, "il faut plusieurs vols à mesurer")
        for arcs in vols:
            a = np.array(arcs)
            rapport = float(a.mean() / a.max())
            self.assertGreater(rapport, 0.58,
                               f"arc trop triangulaire (rapport {rapport:.3f})")
            self.assertLess(rapport, 0.76,
                            f"arc anormal (rapport {rapport:.3f})")

    def test_l_inclinaison_suit_le_sens_du_mouvement(self) -> None:
        for gait in GAITS:
            droite = self._loco(gait, x=300.0)
            droite.go_to(1500.0)
            rolls_droite = []
            while droite.travelling:
                rolls_droite.append(droite.update(STEP)["body.roll"])

            gauche = self._loco(gait, x=1500.0)
            gauche.go_to(300.0)
            rolls_gauche = []
            while gauche.travelling:
                rolls_gauche.append(gauche.update(STEP)["body.roll"])

            self.assertLess(min(rolls_droite), -0.01, gait)
            self.assertGreater(max(rolls_gauche), 0.01, gait)
            for serie in (rolls_droite, rolls_gauche):
                self.assertLessEqual(max(abs(r) for r in serie),
                                     MAX_LEAN + 1e-6, gait)

    def test_l_arrivee_est_franche(self) -> None:
        """Pas de dérive résiduelle : il s'arrête vraiment."""
        loco = self._loco("hop", x=300.0)
        loco.go_to(1200.0)
        voyage(loco)
        for _ in range(600):
            loco.update(STEP)
        self.assertAlmostEqual(loco.x, 1200.0, delta=ARRIVE_EPS * PET + 1.0)
        self.assertEqual(loco.velocity, 0.0)
        self.assertEqual(loco.arc, 0.0)

    def test_un_trajet_sans_progres_est_abandonne(self) -> None:
        """Une cible dans une bande inatteignable ne doit pas figer le pet."""
        loco = Locomotion(terrain_disjoint(), PET, PET, x=500.0,
                          gait="glide", seed=1)
        loco.set_home(500.0)
        loco.go_to(2400.0)              # autre bande, non contiguë
        voyage(loco, limite=STUCK_SECONDS * 3)
        self.assertFalse(loco.travelling)
        self.assertEqual(loco.abandons, 1)

    def test_demarche_inconnue_refusee(self) -> None:
        with self.assertRaises(ValueError):
            Locomotion(self.terrain, PET, PET, gait="galop")


class TargetingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.terrain = terrain_deux_ecrans()
        self.loco = Locomotion(self.terrain, PET, PET, x=800.0, seed=8)
        self.loco.set_home(800.0)

    def test_hysteresis_sur_la_cible(self) -> None:
        """Deux cibles voisines ne justifient pas de repartir (pas de va-et-vient)."""
        self.assertTrue(self.loco.go_to(1400.0))
        proche = 1400.0 + RETARGET_EPS * PET * 0.5
        self.assertFalse(self.loco.go_to(proche))
        loin = 1400.0 + RETARGET_EPS * PET * 2.0
        self.assertTrue(self.loco.go_to(loin))

    def test_une_cible_sur_place_est_refusee(self) -> None:
        self.assertFalse(self.loco.go_to(self.loco.x + 1.0))

    def test_le_glisser_reprend_la_main(self) -> None:
        self.loco.go_to(1800.0)
        for _ in range(60):
            self.loco.update(STEP)
        self.loco.yield_to_user(400.0)
        self.assertFalse(self.loco.travelling)
        self.assertAlmostEqual(self.loco.x, 400.0)

    def test_pas_de_bras_de_fer_apres_un_glisser(self) -> None:
        """Il ne repart pas tout de suite : sinon c'est un bras de fer."""
        self.loco.yield_to_user(400.0)
        self.assertFalse(self.loco.go_to(1800.0))
        self.assertAlmostEqual(self.loco.cooldown, USER_COOLDOWN, places=6)

        for _ in range(int(USER_COOLDOWN / STEP) + 10):
            self.loco.update(STEP)
        self.assertEqual(self.loco.cooldown, 0.0)
        self.assertTrue(self.loco.go_to(1800.0))

    def test_le_glisser_definit_le_domicile(self) -> None:
        """Décision de conception du lot L5b."""
        self.loco.set_home(1700.0)
        self.assertAlmostEqual(self.loco.home_x, 1700.0)
        self.assertAlmostEqual(self.loco.x, 1700.0)
        self.assertFalse(self.loco.travelling)

    def test_la_flanerie_reste_pres_du_domicile(self) -> None:
        rayon = WANDER_RANGE * PET
        self.loco.set_home(1100.0)
        for _ in range(80):
            self.loco.stop()
            if not self.loco.wander():
                continue
            self.assertLessEqual(abs(self.loco.target_x - 1100.0), rayon + 1.0)

    def test_la_flanerie_reste_dans_la_bande(self) -> None:
        """Même avec un domicile au bord, la cible reste praticable."""
        gauche, droite = self.terrain.span
        for domicile in (gauche, droite):
            loco = Locomotion(self.terrain, PET, PET, x=domicile, seed=3)
            loco.set_home(domicile)
            for _ in range(60):
                loco.stop()
                if loco.wander():
                    self.assertGreaterEqual(loco.target_x, gauche - 0.5)
                    self.assertLessEqual(loco.target_x, droite + 0.5)

    def test_le_retour_au_domicile(self) -> None:
        self.loco.set_home(500.0)
        self.loco.go_to(1900.0)
        voyage(self.loco)
        self.assertTrue(self.loco.go_home())
        voyage(self.loco)
        self.assertAlmostEqual(self.loco.x, 500.0, delta=ARRIVE_EPS * PET + 1.0)

    def test_la_flanerie_est_reproductible(self) -> None:
        """Le hasard vient de la graine du génome, comme le rythme de l'idle."""
        def cibles(seed: int) -> list[float]:
            loco = Locomotion(self.terrain, PET, PET, x=800.0, seed=seed)
            loco.set_home(800.0)
            out = []
            for _ in range(10):
                loco.stop()
                if loco.wander():
                    out.append(loco.target_x)
            return out

        self.assertEqual(cibles(42), cibles(42))
        self.assertNotEqual(cibles(42), cibles(43))


class WindowGeometryTest(unittest.TestCase):
    """Conversion centre -> coin de fenêtre, ce dont SetWindowPos a besoin."""

    def setUp(self) -> None:
        self.loco = Locomotion(terrain_deux_ecrans(), PET, PET, x=600.0, seed=1)

    def test_le_coin_est_le_centre_moins_la_moitie(self) -> None:
        self.assertAlmostEqual(self.loco.window_x, 600.0 - PET / 2.0)

    def test_le_y_suit_le_sol_moins_l_arc(self) -> None:
        self.assertAlmostEqual(self.loco.window_y, self.loco.floor_y)
        self.loco.arc = 30.0
        self.assertAlmostEqual(self.loco.window_y, self.loco.floor_y - 30.0)

    def test_le_pet_reste_dans_l_ecran_en_pixels_de_fenetre(self) -> None:
        """Vérifié sur le coin, pas sur le centre : c'est ce qui est écrit."""
        terrain = terrain_deux_ecrans()
        loco = Locomotion(terrain, PET, PET, x=terrain.span[0], seed=1)
        self.assertGreaterEqual(loco.window_x, 0.0 - 0.5)
        loco = Locomotion(terrain, PET, PET, x=terrain.span[1], seed=1)
        self.assertLessEqual(loco.window_x + PET, 2200.0 + 0.5)


if __name__ == "__main__":
    unittest.main()
