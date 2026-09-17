"""Critères d'acceptation des illustrations de châssis, lot L20 (CDC §7, §13).

Ces images ont un défaut de nature : **elles ne sont pas vérifiées par le code
qui les utilise**. Un carton dont l'illustration manque reste cliquable, le
choix fonctionne, rien ne lève — l'utilisateur voit juste un rectangle vide au
moment exact où on lui demande de choisir pour toujours.

Le vrai risque n'est donc pas qu'une image soit laide, c'est qu'un châssis
ajouté plus tard n'en ait aucune et que personne ne s'en aperçoive avant un
utilisateur. C'est ce que le premier test attrape.
"""

from __future__ import annotations

import unittest

from PySide6.QtGui import QImage

from pet.genome.schema import CHASSIS
from pet.ui import chassis_art


class LivraisonTest(unittest.TestCase):
    def test_chaque_chassis_du_schema_a_son_dessin(self) -> None:
        """Le test qui compte : il lie les images au **schéma**, donc ajouter
        un châssis sans son illustration fait échouer la suite au lieu de
        livrer un carton vide."""
        for chassis in CHASSIS:
            self.assertIsNotNone(chassis_art.blueprint(chassis), chassis)

    def test_chaque_chassis_a_des_exemples(self) -> None:
        for chassis in CHASSIS:
            exemples = chassis_art.examples(chassis)
            self.assertGreaterEqual(len(exemples), 3,
                                    "%s : %d vignette(s)" % (chassis, len(exemples)))

    def test_les_images_sont_lisibles(self) -> None:
        """Un PNG tronqué se charge en `QImage` nulle, et se dessine sans rien
        dire. Le seul moyen de le savoir est de l'ouvrir."""
        for chassis in CHASSIS:
            plan = QImage(str(chassis_art.blueprint(chassis)))
            self.assertFalse(plan.isNull(), "blueprint %s illisible" % chassis)
            self.assertGreater(plan.width(), 200, chassis)
            self.assertGreater(plan.height(), plan.width(),
                               "%s : le dessin doit être en portrait" % chassis)
            for chemin in chassis_art.examples(chassis):
                vignette = QImage(str(chemin))
                self.assertFalse(vignette.isNull(), str(chemin))
                self.assertTrue(vignette.hasAlphaChannel(),
                                "%s : fond non transparent" % chemin.name)

    def test_les_exemples_d_un_chassis_ne_debordent_pas_sur_l_autre(self) -> None:
        """La découverte se fait par préfixe : `exemple_capsule_` ne doit pas
        attraper un fichier de monobloc, et réciproquement."""
        capsules = {c.name for c in chassis_art.examples("capsule")}
        monoblocs = {c.name for c in chassis_art.examples("monobloc")}
        self.assertTrue(capsules)
        self.assertTrue(monoblocs)
        self.assertFalse(capsules & monoblocs)

    def test_un_chassis_inconnu_ne_leve_pas(self) -> None:
        """L'appelant décide quoi faire d'une image manquante ; ce module ne
        décide rien et ne casse rien."""
        self.assertIsNone(chassis_art.blueprint("trirème"))
        self.assertEqual(chassis_art.examples("trirème"), [])

    def test_un_dossier_absent_ne_leve_pas(self) -> None:
        from pathlib import Path

        absent = Path(__file__).parent / "_dossier_qui_n_existe_pas"
        self.assertIsNone(chassis_art.blueprint("capsule", directory=absent))
        self.assertEqual(chassis_art.examples("capsule", directory=absent), [])


if __name__ == "__main__":
    unittest.main()
