"""Critères d'acceptation du poids et de l'impact, lot L10 (CDC §10, §3).

« Aucune interpolation linéaire sur un mouvement visible », et surtout
« anticipation avant les mouvements marqués et léger dépassement à l'arrivée ».
Un robot qui tombe et s'arrête net à la hauteur du sol n'enfreint pas la
première règle — il ne bouge tout simplement pas assez pour qu'elle s'applique.
C'est la seconde qu'il manque.

Deux familles, comme au lot L9 : ce qui doit bouger, et ce qui doit s'arrêter.
"""

from __future__ import annotations

import unittest

from pet.anim.impact import (
    FLIGHT_STRETCH_MAX, LAND_FULL_SPEED, LAND_MIN_SPEED, Impact,
)


def _joue(impact: Impact, secondes: float = 2.0, dt: float = 1.0 / 240.0):
    """Fait défiler l'encaissement. Rend la suite des déformations."""
    valeurs = []
    for _ in range(int(secondes / dt)):
        impact.step(dt)
        valeurs.append(impact.flex)
    return valeurs


class LandingTest(unittest.TestCase):
    def test_un_atterrissage_comprime_puis_depasse(self) -> None:
        """C'est tout le lot en une assertion.

        Comprimer sans rebondir donnerait un robot en pâte à modeler : il
        s'aplatit et reprend sa forme. Le dépassement au retour est ce qui le
        rend élastique, donc vivant.
        """
        impact = Impact()
        impact.land(LAND_FULL_SPEED)
        valeurs = _joue(impact)

        self.assertLess(min(valeurs), -0.02, "il ne s'écrase pas")
        creux = valeurs.index(min(valeurs))
        self.assertGreater(max(valeurs[creux:]), 0.005,
                           "il remonte sans dépasser : pas de rebond")

    def test_l_ecrasement_suit_la_vitesse_d_arrivee(self) -> None:
        """Un pet posé doucement et un pet lâché du haut de l'écran ne doivent
        pas encaisser pareil. C'est ce qui distingue un impact d'une animation
        d'impact jouée à l'identique."""
        creux = []
        for vitesse in (300.0, 700.0, LAND_FULL_SPEED):
            impact = Impact()
            impact.land(vitesse)
            creux.append(min(_joue(impact)))
        self.assertLess(creux[1], creux[0])
        self.assertLess(creux[2], creux[1])

    def test_un_micro_rebond_ne_declenche_rien(self) -> None:
        """En fin de chute le pet touche le sol plusieurs fois, de plus en plus
        doucement. Sans seuil, il frissonnerait en se posant."""
        impact = Impact()
        self.assertEqual(impact.land(LAND_MIN_SPEED - 1.0), 0.0)
        self.assertEqual(impact.flex, 0.0)

    def test_la_force_rendue_est_bornee(self) -> None:
        """Elle sera transmise telle quelle au son et à la poussière : une
        valeur hors de [0, 1] leur ferait produire n'importe quoi."""
        impact = Impact()
        self.assertAlmostEqual(impact.land(LAND_FULL_SPEED * 10.0), 1.0)


class FlightTest(unittest.TestCase):
    def test_la_vitesse_etire_le_corps(self) -> None:
        impact = Impact()
        impact.set_flight(1200.0)
        self.assertGreater(impact.flex, 0.0)
        self.assertLessEqual(impact.flex, FLIGHT_STRETCH_MAX + 1e-9)

    def test_l_etirement_est_plafonne(self) -> None:
        """Au-delà, le robot devient une nouille — ce qui appartient au dessin
        animé, pas à ce produit."""
        impact = Impact()
        impact.set_flight(100000.0)
        self.assertAlmostEqual(impact.flex, FLIGHT_STRETCH_MAX)

    def test_l_etirement_cesse_avec_le_mouvement(self) -> None:
        """Confié à un ressort, il traînerait après l'atterrissage — juste là
        où il faut de la compression."""
        impact = Impact()
        impact.set_flight(1200.0)
        impact.set_flight(0.0)
        self.assertEqual(impact.flex, 0.0)


class CadenceTest(unittest.TestCase):
    """Le §3 : ce qui bouge doit finir de bouger."""

    def test_le_pas_de_temps_ne_change_pas_le_mouvement(self) -> None:
        """La régression que ce lot corrige.

        L'ancien `_pulse *= 0.88` s'appliquait **par image** : à 10 fps le
        retour prenait trois fois moins de temps réel qu'à 30, si bien que le
        pet réagissait au clic d'autant plus mollement qu'il était occupé — et
        la cadence change précisément quand il est occupé (§3).
        """
        lent, rapide = Impact(), Impact()
        lent.poke()
        rapide.poke()
        for _ in range(10):
            lent.step(1.0 / 10.0)
        for _ in range(30):
            rapide.step(1.0 / 30.0)
        self.assertAlmostEqual(lent.flex, rapide.flex, places=3)

    def test_il_finit_par_se_poser(self) -> None:
        impact = Impact()
        impact.land(LAND_FULL_SPEED)
        _joue(impact, secondes=3.0)
        self.assertTrue(impact.settled, "l'encaissement ne se termine pas")

    def test_un_impact_au_repos_ne_demande_pas_d_images(self) -> None:
        self.assertTrue(Impact().settled)

    def test_un_etirement_en_cours_demande_des_images(self) -> None:
        impact = Impact()
        impact.set_flight(900.0)
        self.assertFalse(impact.settled)


class VolumeTest(unittest.TestCase):
    """`body.flex` conserve le volume : ce qui s'écrase s'élargit."""

    def _echelles(self, flex: float):
        from pet.genome.generator import generate
        from pet.geometry.builder import build
        from pet.anim.layers import apply_channels
        from pet.anim.rig_pose import RigPose, zero_channels

        robot = build(generate(3))
        pose = RigPose(robot.rig)
        canaux = zero_channels()
        canaux["body.flex"] = flex
        apply_channels(pose, canaux, robot.dims)
        echelle = robot.rig["body_flex"].scale
        return float(echelle[0]), float(echelle[1])

    def test_un_corps_ecrase_s_elargit(self) -> None:
        """Sans cette largeur, un corps comprimé rétrécit tout court — et le
        §10 n'y voit qu'un objet qui diminue, pas un objet qui encaisse."""
        largeur, hauteur = self._echelles(-0.12)
        self.assertLess(hauteur, 1.0)
        self.assertGreater(largeur, 1.0)
        self.assertAlmostEqual(largeur * largeur * hauteur, 1.0, places=6)

    def test_un_corps_etire_s_affine(self) -> None:
        largeur, hauteur = self._echelles(0.12)
        self.assertGreater(hauteur, 1.0)
        self.assertLess(largeur, 1.0)

    def test_une_deformation_absurde_ne_retourne_pas_le_robot(self) -> None:
        """`body.flex` cumule respiration, démarche et encaissement : rien
        n'empêche la somme de descendre sous -1, et une échelle négative
        retournerait le corps."""
        largeur, hauteur = self._echelles(-4.0)
        self.assertGreater(hauteur, 0.0)
        self.assertGreater(largeur, 0.0)


class GaitTest(unittest.TestCase):
    """Le signe de l'écrasement dans la démarche à sauts."""

    def _canaux(self, phase: str) -> dict:
        from .test_locomotion import PET, terrain_deux_ecrans
        from pet.anim.locomotion import Locomotion

        loco = Locomotion(terrain_deux_ecrans(), PET, PET, x=300.0,
                          gait="hop", seed=8)
        loco.set_home(300.0)
        loco.go_to(900.0)
        vus = {}
        for _ in range(600):
            canaux = loco.update(1.0 / 120.0)
            if loco._phase == phase and canaux.get("body.flex"):
                vus = canaux
                break
        return vus

    def test_l_accroupissement_ecrase_au_lieu_d_etirer(self) -> None:
        """Le défaut corrigé au lot L10 : `body.flex` positif **allonge** le
        corps, et c'était le signe écrit ici. Le robot s'étirait en
        s'accroupissant, ce qui est resté invisible tant que `flex` n'agissait
        que sur la hauteur — un étirement de 6 % ne se remarque pas.

        Les courbes écrites à la main de `layers` utilisaient déjà la bonne
        convention, ce qui achève de dater l'erreur.
        """
        canaux = self._canaux("crouch")
        self.assertTrue(canaux, "phase d'accroupissement jamais atteinte")
        self.assertLess(canaux["body.flex"], 0.0)

    def test_l_atterrissage_ecrase_aussi(self) -> None:
        canaux = self._canaux("land")
        self.assertTrue(canaux, "phase d'atterrissage jamais atteinte")
        self.assertLess(canaux["body.flex"], 0.0)


if __name__ == "__main__":
    unittest.main()
