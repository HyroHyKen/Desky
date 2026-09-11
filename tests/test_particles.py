"""Critères d'acceptation des particules, lot L11 (CDC §3, §6, §12).

Trois exigences, et la première est la seule qui puisse casser le produit.

**La zone cliquable ne doit pas grandir.** Le hit-testing du pet lit l'alpha de
l'image rendue : toute matière dessinée dans le FBO devient cliquable, et des
étincelles qui avalent les clics destinés à la fenêtre du dessous sont une
régression du §6 que personne ne rattacherait aux particules.

**Le banc doit se vider.** Le §3 plafonne à 4 % d'un cœur : un effet qui ne
meurt pas maintient la cadence à 30 fps indéfiniment.

**Rien n'est gratuit.** Le §12 interdit les comportements imposés ; une
particule sans cause est du bruit, et sur un logiciel de bureau permanent le
bruit se paie en désinstallations.
"""

from __future__ import annotations

import unittest

import numpy as np

from pet.anim.particles import CAPACITY, DUST, REFUS, SLEEP, SPARK, Particles

from .qt_app import ensure_app


def _joue(banc: Particles, secondes: float, pet_h: float = 220.0,
          dt: float = 1.0 / 120.0) -> int:
    pas = 0
    for _ in range(int(secondes / dt)):
        if not banc.step(dt, pet_h):
            break
        pas += 1
    return pas


class BankTest(unittest.TestCase):
    def test_un_banc_neuf_est_vide(self) -> None:
        self.assertTrue(Particles().empty)
        self.assertFalse(Particles().step(1.0 / 60.0, 220.0))

    def test_une_gerbe_finit_par_mourir(self) -> None:
        banc = Particles(seed=1)
        banc.burst(DUST, 100.0, 200.0, 12, speed=200.0, spread=0.6,
                   life=0.4, size=6.0)
        self.assertGreater(banc.count, 0)
        _joue(banc, 3.0)
        self.assertTrue(banc.empty, "la gerbe ne meurt jamais")

    def test_le_budget_est_dur(self) -> None:
        """Un plafond dur vaut mieux qu'un tableau qui grandit : le pire cas est
        connu d'avance, et un défaut de réglage produit un effet pauvre plutôt
        qu'une fuite de mémoire."""
        banc = Particles(seed=2)
        emis = 0
        for _ in range(20):
            emis += banc.burst(SPARK, 0.0, 0.0, 30, speed=100.0, spread=1.0,
                               life=9.0, size=4.0, up=1.0)
        self.assertEqual(emis, CAPACITY)
        self.assertEqual(banc.count, CAPACITY)
        self.assertEqual(banc.burst(SPARK, 0.0, 0.0, 5, speed=1.0, spread=1.0,
                                    life=1.0, size=1.0), 0)

    def test_aucune_allocation_par_image(self) -> None:
        """Les tableaux sont alloués une fois et réutilisés en place.

        Une liste d'objets créée et détruite trente fois par seconde fait
        travailler le ramasse-miettes en continu sous une application censée
        tenir sous 4 % d'un cœur. Le coût ne se voit pas en profilant une
        seconde ; il se voit sur la consommation d'une journée.
        """
        banc = Particles(seed=3)
        banc.burst(DUST, 50.0, 50.0, 40, speed=150.0, spread=0.8,
                   life=5.0, size=5.0)
        identites = [id(t) for t in (banc.x, banc.y, banc.vx, banc.vy,
                                     banc.life, banc.size, banc.kind, banc.alive)]
        _joue(banc, 1.0)
        self.assertEqual(
            [id(t) for t in (banc.x, banc.y, banc.vx, banc.vy,
                             banc.life, banc.size, banc.kind, banc.alive)],
            identites, "un tableau a été réalloué pendant l'intégration")

    def test_la_taille_du_pet_met_la_gravite_a_l_echelle(self) -> None:
        """La taille de rendu va de 120 à 400 px (§17.1) : une poussière réglée
        en pixels serait ridicule à un bout et envahissante à l'autre."""
        chutes = []
        for pet_h in (120.0, 400.0):
            banc = Particles(seed=4)
            banc.burst(DUST, 0.0, 0.0, 1, speed=0.0, spread=0.0,
                       life=5.0, size=1.0, x_spread=0.0, y_spread=0.0)
            for _ in range(30):
                banc.step(1.0 / 120.0, pet_h)
            chutes.append(float(banc.y[banc.alive][0]))
        self.assertAlmostEqual(chutes[1] / chutes[0], 400.0 / 120.0, places=3)

    def test_l_avancement_de_vie_reste_borne(self) -> None:
        banc = Particles(seed=5)
        banc.burst(SLEEP, 0.0, 0.0, 4, speed=10.0, spread=0.2,
                   life=0.5, size=8.0, up=1.0)
        for _ in range(40):
            banc.step(1.0 / 120.0, 220.0)
            _, age = banc.visible()
            if age.size:
                self.assertTrue(bool(np.all((age >= 0.0) & (age <= 1.0))))


class RecipeTest(unittest.TestCase):
    """Chaque gerbe répond à un fait, et son intensité suit celle du fait."""

    def test_un_atterrissage_leger_ne_souleve_rien(self) -> None:
        from pet.ui import sparks

        banc = Particles(seed=6)
        self.assertEqual(sparks.landing_dust(banc, 0.05, 220.0, 220.0), 0)
        self.assertTrue(banc.empty)

    def test_la_poussiere_suit_la_force_du_choc(self) -> None:
        """La même force nourrit la déformation du corps et cette gerbe : c'est
        ce qui les fait lire comme un seul événement."""
        from pet.ui import sparks

        comptes = []
        for force in (0.25, 1.0):
            banc = Particles(seed=7)
            comptes.append(sparks.landing_dust(banc, force, 220.0, 220.0))
        self.assertLess(comptes[0], comptes[1])

    def test_les_etincelles_de_soin_ne_naissent_pas_sur_le_visage(self) -> None:
        """Peintes après le robot, des étincelles nées au centre apparaissent
        **par-dessus** son visage et se lisent comme un défaut d'image. Elles
        doivent naître bas et large, puis remonter le long de la silhouette.
        """
        from pet.ui import sparks

        banc = Particles(seed=8)
        h = 220.0
        sparks.care_sparks(banc, h, h)
        idx, _ = banc.visible()
        ys = banc.y[idx]
        # Le visage occupe le tiers supérieur : aucune naissance là.
        self.assertGreater(float(ys.min()), h * 0.45,
                           "une étincelle naît sur le visage")
        xs = banc.x[idx]
        self.assertGreater(float(xs.max() - xs.min()), h * 0.3,
                           "la gerbe naît d'un point : c'est une fontaine")

    def test_un_refus_est_bref_et_discret(self) -> None:
        """Le §12 interdit de culpabiliser : un achat hors budget mérite un
        signal, pas une réprimande."""
        from pet.ui import sparks

        banc = Particles(seed=9)
        sparks.refusal_puff(banc, 220.0, 220.0)
        self.assertLessEqual(banc.count, 5)
        self.assertTrue(bool(np.all(banc.kind[banc.alive] == REFUS)))
        _joue(banc, 1.0)
        self.assertTrue(banc.empty, "le refus s'attarde")


class PaletteTest(unittest.TestCase):
    """Une étincelle de soin et la jauge qu'elle vient de remplir sont le même
    geste : deux cyans voisins mais distincts se remarquent immédiatement."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def test_l_accent_des_etincelles_est_celui_du_panneau(self) -> None:
        from pet.ui.panel import ACCENT as ACCENT_PANNEAU
        from pet.ui.sparks import ACCENT as ACCENT_ETINCELLES

        self.assertEqual(ACCENT_ETINCELLES.rgb(), ACCENT_PANNEAU.rgb())

    def test_le_refus_reprend_l_ambre_des_jauges_basses(self) -> None:
        from pet.ui.panel import BAR_LOW
        from pet.ui.sparks import REFUS_COLOR

        self.assertEqual(REFUS_COLOR.rgb(), BAR_LOW.rgb())


if __name__ == "__main__":
    unittest.main()
