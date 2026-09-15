"""Critères d'acceptation du jeu des trois gobelets, lot L14 (CDC §12, §14).

Un jeu de bonneteau n'a qu'une obligation absolue : **le robot doit être là où
le mélange dit qu'il est**. Tout le reste est du réglage ; celle-là, si elle
casse, rend le jeu malhonnête sans que personne puisse le prouver — on croit
seulement avoir mal suivi.

D'où le poids donné ici à la séparation gobelet / emplacement, qui est la seule
chose que ce jeu puisse se tromper en silence.
"""

from __future__ import annotations

import unittest

from pet.games.cups import (CHOOSING, COVERING, MIDDLE, OVER, RESULT, REVEAL,
                            SHUFFLING, SLOTS, Cups, seconds_for_round,
                            swaps_for_round)

DT = 1.0 / 120.0


def _jusqu_au_choix(game: Cups, limite: float = 60.0) -> float:
    t = 0.0
    while game.state != CHOOSING and t < limite:
        game.step(DT)
        t += DT
    return t


def _jusqu_a(game: Cups, etat: str, limite: float = 60.0) -> None:
    t = 0.0
    while game.state != etat and t < limite:
        game.step(DT)
        t += DT


class HonestyTest(unittest.TestCase):
    """Le robot est là où le mélange dit qu'il est. C'est tout le jeu."""

    def test_le_robot_ne_change_jamais_de_gobelet(self) -> None:
        """Il est **transporté**, pas téléporté.

        La distinction n'est pas théorique : un jeu qui déplacerait le robot
        d'un gobelet à l'autre serait indétectable à l'œil et parfaitement
        injouable. C'est précisément pour cela que le gobelet et l'emplacement
        sont deux choses séparées dans le modèle.
        """
        game = Cups(seed=3)
        _jusqu_au_choix(game)
        self.assertEqual(game.robot_cup, MIDDLE)

    def test_la_position_du_robot_suit_les_permutations(self) -> None:
        """Rejouée à la main, permutation par permutation."""
        game = Cups(seed=5)
        _jusqu_a(game, SHUFFLING)

        attendu = game.robot_slot
        vus = 0
        precedent = game.swap
        while game.state == SHUFFLING:
            game.step(DT)
            courant = game.swap
            if courant != precedent and precedent is not None:
                a, b = precedent
                if attendu == a:
                    attendu = b
                elif attendu == b:
                    attendu = a
                vus += 1
                self.assertEqual(game.robot_slot, attendu,
                                 "le robot a décroché à la permutation %d" % vus)
            precedent = courant
        self.assertGreater(vus, 0, "aucune permutation observée")

    def test_un_seul_gobelet_par_emplacement(self) -> None:
        """Deux gobelets au même endroit voudrait dire qu'un emplacement est
        vide : le joueur cliquerait dans le vide sans comprendre."""
        game = Cups(seed=9)
        for _ in range(int(20.0 / DT)):
            game.step(DT)
            self.assertEqual(sorted(game.cup_at), list(range(SLOTS)))
            if game.state == CHOOSING:
                break

    def test_le_gobelet_d_un_emplacement_est_reciproque(self) -> None:
        game = Cups(seed=11)
        _jusqu_au_choix(game)
        for slot in range(SLOTS):
            cup = game.cup_in_slot(slot)
            self.assertEqual(game.slot_of_cup(cup), slot)


class DifficultyTest(unittest.TestCase):
    def test_chaque_manche_ajoute_une_permutation(self) -> None:
        self.assertLess(swaps_for_round(0), swaps_for_round(3))

    def test_chaque_manche_accelere(self) -> None:
        self.assertGreater(seconds_for_round(0), seconds_for_round(3))

    def test_les_deux_axes_plafonnent(self) -> None:
        """Au-delà, le mélange cesse d'être un jeu d'attention pour devenir un
        tirage au sort, et perdre à pile ou face n'apprend rien."""
        self.assertEqual(swaps_for_round(50), swaps_for_round(200))
        self.assertAlmostEqual(seconds_for_round(50), seconds_for_round(200))

    def test_une_manche_reste_regardable(self) -> None:
        """Ni expédiée, ni interminable : c'est la durée pendant laquelle le
        joueur doit tenir sa concentration."""
        for manche in (0, 4, 12, 30):
            duree = swaps_for_round(manche) * seconds_for_round(manche) * 1.22
            self.assertGreater(duree, 1.2, "manche %d expédiée" % manche)
            self.assertLess(duree, 4.0, "manche %d interminable" % manche)

    def test_jamais_deux_fois_la_meme_permutation_d_affilee(self) -> None:
        """La refaire annule la précédente : le joueur voit un aller-retour qui
        n'apprend rien tout en coûtant une permutation."""
        for graine in range(12):
            game = Cups(seed=graine)
            _jusqu_a(game, SHUFFLING)
            plan = game._plan
            for avant, apres in zip(plan, plan[1:]):
                self.assertNotEqual(avant, apres, "graine %d" % graine)


class RoundTest(unittest.TestCase):
    def test_on_ne_choisit_pas_avant_la_fin_du_melange(self) -> None:
        game = Cups(seed=2)
        self.assertFalse(game.pick(0), "choix accepté pendant la révélation")
        _jusqu_a(game, SHUFFLING)
        self.assertFalse(game.pick(0), "choix accepté pendant le mélange")

    def test_un_bon_choix_ouvre_une_nouvelle_manche(self) -> None:
        game = Cups(seed=4)
        _jusqu_au_choix(game)
        self.assertTrue(game.pick(game.robot_slot))
        self.assertEqual(game.score, 1)
        self.assertEqual(game.state, RESULT)

        _jusqu_a(game, REVEAL)
        self.assertEqual(game.round, 1)
        self.assertEqual(game.robot_cup, MIDDLE,
                         "le robot ne repart pas du milieu")
        self.assertFalse(game.over)

    def test_un_mauvais_choix_finit_la_partie(self) -> None:
        game = Cups(seed=6)
        _jusqu_au_choix(game)
        game.pick((game.robot_slot + 1) % SLOTS)
        self.assertEqual(game.score, 0)
        _jusqu_a(game, OVER)
        self.assertTrue(game.over)

    def test_le_resultat_se_regarde_avant_de_conclure(self) -> None:
        """On doit **voir** où il était, sinon perdre ne dit rien et on
        soupçonne le jeu de tricher."""
        game = Cups(seed=8)
        _jusqu_au_choix(game)
        game.pick((game.robot_slot + 1) % SLOTS)
        self.assertEqual(game.state, RESULT)
        game.step(DT)
        self.assertFalse(game.over, "la partie se conclut sans montrer")

    def test_le_record_est_retenu(self) -> None:
        game = Cups(best=2, seed=10)
        for _ in range(3):
            _jusqu_au_choix(game)
            game.pick(game.robot_slot)
            _jusqu_a(game, REVEAL)
        self.assertEqual(game.score, 3)
        self.assertTrue(game.record)
        game.abandon()
        self.assertEqual(game.best, 3)

    def test_abandonner_n_efface_pas_le_score(self) -> None:
        game = Cups(seed=12)
        _jusqu_au_choix(game)
        game.pick(game.robot_slot)
        game.abandon()
        self.assertEqual(game.score, 1)
        self.assertTrue(game.over)

    def test_une_partie_finie_ne_bouge_plus(self) -> None:
        game = Cups(seed=14)
        game.abandon()
        avant = list(game.cup_at)
        for _ in range(200):
            game.step(DT)
        self.assertEqual(game.cup_at, avant)


class SequenceTest(unittest.TestCase):
    def test_la_sequence_est_tiree_une_fois_pour_toutes(self) -> None:
        """Tirer au fil du déroulement laisserait le hasard intervenir après que
        le joueur a commencé à suivre le gobelet des yeux."""
        game = Cups(seed=15)
        _jusqu_a(game, SHUFFLING)
        plan = list(game._plan)
        for _ in range(40):
            game.step(DT)
        self.assertEqual(game._plan, plan)

    def test_la_meme_graine_rejoue_la_meme_partie(self) -> None:
        """C'est ce qui rend un défaut de mélange reproductible."""
        a, b = Cups(seed=21), Cups(seed=21)
        _jusqu_au_choix(a)
        _jusqu_au_choix(b)
        self.assertEqual(a.cup_at, b.cup_at)
        self.assertEqual(a.robot_slot, b.robot_slot)

    def test_l_ordre_des_etats_est_celui_attendu(self) -> None:
        game = Cups(seed=17)
        vus = [game.state]
        for _ in range(int(30.0 / DT)):
            game.step(DT)
            if game.state != vus[-1]:
                vus.append(game.state)
            if game.state == CHOOSING:
                break
        self.assertEqual(vus, [REVEAL, COVERING, SHUFFLING, CHOOSING])


if __name__ == "__main__":
    unittest.main()
