"""Critères d'acceptation de l'écran de lancement, lot L19 (CDC §3, §6).

Un écran de lancement a deux façons de mal tourner, et aucune des deux ne se
voit en le regardant une fois sur sa propre machine :

- **il clignote** sur un poste rapide, parce qu'il part dès que l'application
  est prête — c'est-à-dire tout de suite ;
- **il reste** sur un poste où le chargement échoue, posé au milieu de l'écran
  par-dessus le message d'erreur, sans rien pour le faire partir.

Les deux tiennent à la machine à phases, qui est donc séparée du widget et se
joue ici à `dt` synthétique, sans écran.
"""

from __future__ import annotations

import unittest

from pet.ui.splash import (ENTRANT, ENTREE, FINI, SECURITE, SORTANT, SORTIE,
                           TENUE, TENUE_MIN, Fondu)

DT = 1.0 / 120.0


def _jouer(fondu: Fondu, secondes: float) -> None:
    for _ in range(int(secondes / DT)):
        fondu.step(DT)


def _jusqu_a_la_fin(fondu: Fondu, limite: float = 30.0) -> float:
    t = 0.0
    while not fondu.fini and t < limite:
        fondu.step(DT)
        t += DT
    return t


class DerouleTest(unittest.TestCase):
    def test_il_commence_invisible(self) -> None:
        """Un logo qui apparaît à pleine opacité n'est pas un fondu."""
        self.assertEqual(Fondu().opacite, 0.0)

    def test_l_ordre_des_phases(self) -> None:
        fondu = Fondu()
        self.assertEqual(fondu.phase, ENTRANT)
        _jouer(fondu, ENTREE + DT)
        self.assertEqual(fondu.phase, TENUE)
        fondu.pret()
        _jouer(fondu, TENUE_MIN + DT)
        self.assertEqual(fondu.phase, SORTANT)
        _jouer(fondu, SORTIE + DT)
        self.assertEqual(fondu.phase, FINI)

    def test_il_est_pleinement_visible_pendant_la_tenue(self) -> None:
        fondu = Fondu()
        _jouer(fondu, ENTREE + DT)
        self.assertEqual(fondu.opacite, 1.0)

    def test_l_opacite_reste_bornee(self) -> None:
        """Une opacité hors de [0, 1] est refusée par Qt sans prévenir."""
        fondu = Fondu()
        fondu.pret()
        for _ in range(int(20.0 / DT)):
            fondu.step(DT)
            self.assertGreaterEqual(fondu.opacite, 0.0)
            self.assertLessEqual(fondu.opacite, 1.0)

    def test_il_finit_a_zero(self) -> None:
        fondu = Fondu()
        fondu.pret()
        _jusqu_a_la_fin(fondu)
        self.assertEqual(fondu.opacite, 0.0)


class PlancherTest(unittest.TestCase):
    """Le cas de la machine rapide, celui qu'on ne voit jamais chez soi."""

    def test_pret_immediatement_ne_fait_pas_clignoter(self) -> None:
        """`finish()` appelé à la première image ne doit pas escamoter le logo.

        C'est le scénario du poste rapide : la fenêtre se construit en moins de
        temps que le fondu d'entrée, et sans plancher le logo apparaîtrait et
        disparaîtrait dans le même souffle.
        """
        fondu = Fondu()
        fondu.pret()
        duree = _jusqu_a_la_fin(fondu)
        self.assertGreaterEqual(duree, ENTREE + TENUE_MIN + SORTIE - 3 * DT)

    def test_la_tenue_dure_au_moins_son_plancher(self) -> None:
        fondu = Fondu()
        _jouer(fondu, ENTREE + DT)
        fondu.pret()
        _jouer(fondu, TENUE_MIN * 0.5)
        self.assertEqual(fondu.phase, TENUE, "la tenue a été écourtée")

    def test_sans_pret_il_tient_le_temps_du_chargement(self) -> None:
        """Le pendant du test précédent : tant que rien n'est prêt, il reste —
        c'est tout son intérêt, couvrir un chargement lent."""
        fondu = Fondu()
        _jouer(fondu, 3.0)
        self.assertEqual(fondu.phase, TENUE)
        self.assertEqual(fondu.opacite, 1.0)


class SecuriteTest(unittest.TestCase):
    """Le cas du chargement qui n'aboutit pas."""

    def test_il_s_efface_meme_si_personne_ne_le_libere(self) -> None:
        """Entre l'affichage et `finish()`, le bootstrap peut échouer et ouvrir
        une boîte de dialogue. Sans plafond, le logo resterait posé dessus."""
        fondu = Fondu()
        duree = _jusqu_a_la_fin(fondu, limite=SECURITE + 5.0)
        self.assertTrue(fondu.fini, "l'écran ne part jamais")
        self.assertLessEqual(duree, SECURITE + SORTIE + 0.2)

    def test_le_plafond_laisse_un_fondu_et_ne_coupe_pas_net(self) -> None:
        fondu = Fondu()
        _jouer(fondu, SECURITE + DT)
        self.assertEqual(fondu.phase, SORTANT)
        self.assertGreater(fondu.opacite, 0.0)


class BudgetTest(unittest.TestCase):
    """Ce que l'écran coûte au démarrage, que le §3 plafonne à trois secondes."""

    def test_seul_le_fondu_d_entree_s_ajoute_au_demarrage(self) -> None:
        """La tenue et la sortie se jouent pendant et après le chargement ; le
        fondu d'entrée, lui, est du temps ajouté. Il doit rester petit."""
        self.assertLessEqual(ENTREE, 0.35)

    def test_l_ecran_entier_reste_bref(self) -> None:
        fondu = Fondu()
        fondu.pret()
        self.assertLess(_jusqu_a_la_fin(fondu), 1.5)


class EnchainementTest(unittest.TestCase):
    """Ce qui attend la fin de l'écran de lancement.

    L'accueil du lot L21 s'ouvre sur `finished`. Deux façons de se tromper :
    l'émettre trop tôt, et les deux écrans se superposent ; ne jamais l'émettre,
    et l'accueil ne s'ouvre pas du tout. Les deux sont couverts ici, sur la
    machine à phases plutôt que sur le widget, qui demanderait un écran.
    """

    def test_le_fondu_ne_se_dit_fini_qu_a_la_fin(self) -> None:
        fondu = Fondu()
        fondu.pret()
        for _ in range(int((ENTREE + TENUE_MIN + SORTIE) / DT) - 4):
            fondu.step(DT)
            self.assertFalse(fondu.fini, "annoncé fini alors qu'il est visible")
        _jusqu_a_la_fin(fondu)
        self.assertTrue(fondu.fini)

    def test_un_ecran_sans_image_est_fini_d_emblee(self) -> None:
        """Sans logo à afficher, le signal ne partira jamais : l'appelant doit
        pouvoir le savoir avant de s'y abonner, sinon l'accueil reste fermé."""
        fondu = Fondu()
        fondu.phase = FINI
        self.assertTrue(fondu.fini)
        self.assertEqual(fondu.opacite, 0.0)

if __name__ == "__main__":
    unittest.main()
