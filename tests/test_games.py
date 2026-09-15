"""Critères d'acceptation du jeu de ballon, lot L12 (CDC §12, §14).

Une partie entière se joue en mémoire, au pas de temps synthétique : c'est tout
l'intérêt d'avoir gardé `pet/games` sans Qt. On peut donc vérifier des choses
qu'on ne saurait pas tester à l'écran — que le robot vise juste, que la
difficulté monte vraiment, qu'une partie parfaite ne plante pas.
"""

from __future__ import annotations

import unittest

from pet.games import OVER, PLAYER, PLAYING, ROBOT, Balloon, Rally
from pet.games import robot as ia
from pet.games.rally import SERVE_HEIGHT, SERVE_IMPULSE, SERVE_SECONDS

PET_H = 220.0
LEFT, RIGHT, FLOOR = 0.0, 1920.0, 860.0
DT = 1.0 / 60.0


def _ballon(rally: int = 0) -> Balloon:
    b = Balloon(RIGHT / 2, FLOOR - 1.6 * PET_H, PET_H, LEFT, RIGHT, FLOOR)
    b.rally = rally
    return b


def _partie(first: str = PLAYER) -> Rally:
    r = Rally(_ballon(), first=first)
    for _ in range(int(SERVE_SECONDS / DT) + 2):
        r.step(DT)
    return r


class BalloonTest(unittest.TestCase):
    def test_il_tombe_lentement_au_depart(self) -> None:
        """Un ballon de baudruche n'est pas une balle : c'est ce qui rend le jeu
        jouable à la souris."""
        b = _ballon()
        _, duree = b.predict_landing()
        self.assertGreater(duree, 2.0, "il tombe comme une pierre")

    def test_il_s_alourdit_avec_les_echanges(self) -> None:
        """Toute la courbe de difficulté tient dans ce test."""
        vols = []
        for echanges in (0, 8, 16, 24):
            b = _ballon(echanges)
            vols.append(b.predict_landing()[1])
        for avant, apres in zip(vols, vols[1:]):
            self.assertLess(apres, avant, "le ballon ne s'alourdit pas")
        self.assertLess(vols[-1], vols[0] * 0.55,
                        "l'écart entre le premier et le dernier échange est trop faible")

    def test_le_poids_plafonne(self) -> None:
        """Une difficulté qui croît sans fin transforme un jeu d'adresse en
        compte à rebours."""
        self.assertAlmostEqual(_ballon(24).predict_landing()[1],
                               _ballon(200).predict_landing()[1], places=3)

    def test_il_rebondit_sur_les_bords(self) -> None:
        b = _ballon()
        b.x = RIGHT - b.radius - 2.0
        b.vx = 900.0
        for _ in range(20):
            b.step(DT)
        self.assertLessEqual(b.x + b.radius, RIGHT + 1e-6)
        self.assertLess(b.vx, 0.0, "il traverse le bord au lieu d'y rebondir")

    def test_deux_frappes_ne_s_enchainent_pas(self) -> None:
        """Sans délai, un curseur immobile dans le ballon le frapperait à
        chaque image — soixante échanges par seconde."""
        b = _ballon()
        self.assertTrue(b.hit(b.x, 1.0))
        self.assertFalse(b.hit(b.x, 1.0))

    def test_la_prediction_est_la_physique(self) -> None:
        """Elle rejoue `step()`, elle ne l'approxime pas. Une formule fermée
        serait fausse d'une demi-largeur d'écran avec ce frottement.
        """
        b = _ballon()
        b.hit(b.x - 20.0, 1.0)
        prevu, delai = b.predict_landing()

        joue = 0.0
        while not b.grounded and joue < 20.0:
            b.step(DT)
            joue += DT
        self.assertAlmostEqual(b.x, prevu, delta=1.0)
        self.assertAlmostEqual(joue, delai, delta=2 * DT)


class ServeTest(unittest.TestCase):
    """Le service doit se lire comme une baudruche lancée, pas lâchée."""

    def _service(self, pet_h: float = PET_H, plafond: float = 0.0):
        b = Balloon(RIGHT / 2, FLOOR - SERVE_HEIGHT * pet_h, pet_h,
                    LEFT, RIGHT, FLOOR, top=plafond)
        b.vy = -SERVE_IMPULSE * pet_h
        sommet, t, t_sommet = b.y, 0.0, 0.0
        while t < 15.0:
            b.step(DT)
            t += DT
            if b.y < sommet:
                sommet, t_sommet = b.y, t
            if b.grounded:
                break
        return (FLOOR - sommet) / pet_h, t_sommet, sommet

    def test_il_monte_franchement(self) -> None:
        """Il ne s'élevait que de deux dixièmes de hauteur avant de redescendre,
        ce qui se lit comme une balle lâchée et non comme un ballon lancé."""
        apogee, _, _ = self._service()
        self.assertGreater(apogee - SERVE_HEIGHT, 1.0,
                           "il ne monte presque pas au service")

    def test_il_monte_longtemps(self) -> None:
        """L'ascension **lente** est ce qui dit « c'est léger », davantage que
        n'importe quel réglage de gravité."""
        _, t_sommet, _ = self._service()
        self.assertGreater(t_sommet, 0.8, "l'ascension est trop brève")

    def test_il_ne_sort_jamais_par_le_haut(self) -> None:
        """À la taille maximale du §17.1, le service monterait à 1 320 px —
        au-dessus de la zone de travail de la plupart des écrans. Un ballon
        qu'on perd de vue pendant deux secondes n'est pas un jeu."""
        for pet_h in (120.0, 220.0, 400.0):
            _, _, sommet = self._service(pet_h, plafond=0.0)
            self.assertGreaterEqual(sommet, 0.0,
                                    "le ballon sort de l'écran à %.0f px" % pet_h)

    def test_le_plafond_ne_renvoie_pas_comme_un_mur(self) -> None:
        """De la baudruche ne rebondit pas comme une balle de squash."""
        b = Balloon(RIGHT / 2, 400.0, PET_H, LEFT, RIGHT, FLOOR, top=0.0)
        b.y = b.radius + 4.0
        b.vy = -1200.0
        b.step(DT)
        self.assertLess(b.vy, 400.0, "il repart du plafond comme d'un trampoline")


class TurnTest(unittest.TestCase):
    """L'alternance stricte, qui est ce qui donne un sens au score."""

    def test_personne_ne_frappe_pendant_le_service(self) -> None:
        """Le curseur qui se trouvait déjà là ne doit pas ouvrir la partie."""
        r = Rally(_ballon())
        self.assertFalse(r.hit(PLAYER, r.balloon.x))
        self.assertEqual(r.score, 0)

    def test_chacun_son_tour(self) -> None:
        r = _partie()
        self.assertTrue(r.player_turn)
        self.assertFalse(r.hit(ROBOT, r.balloon.x), "le robot joue hors tour")
        self.assertTrue(r.hit(PLAYER, r.balloon.x - 30.0))
        self.assertTrue(r.robot_turn)
        self.assertFalse(r.hit(PLAYER, r.balloon.x), "le joueur rejoue")

    def test_le_ballon_repart_vers_l_autre(self) -> None:
        """Sans cela, un échange sur deux serait injouable."""
        r = _partie()
        r.hit(PLAYER, r.balloon.x + 40.0)      # frappé par la droite
        self.assertLess(r.balloon.vx, 0.0, "il repart du côté du frappeur")

    def test_le_ballon_au_sol_finit_la_partie(self) -> None:
        r = _partie()
        r.hit(PLAYER, r.balloon.x - 30.0)
        for _ in range(int(20.0 / DT)):
            r.step(DT)
            if r.over:
                break
        self.assertEqual(r.state, OVER)
        self.assertEqual(r.score, 1)

    def test_le_record_est_retenu(self) -> None:
        r = Rally(_ballon(), best=7)
        r.state = PLAYING
        for _ in range(9):
            r.hit(r.turn, r.balloon.x - 30.0)
            r.balloon._cooldown = 0.0
        self.assertTrue(r.record)
        r.abandon()
        self.assertEqual(r.best, 9)

    def test_abandonner_n_efface_pas_le_score(self) -> None:
        """Effacer douze échanges parce qu'une vidéo est passée en plein écran
        serait une punition, et le §12 les interdit."""
        r = _partie()
        r.hit(PLAYER, r.balloon.x - 30.0)
        r.abandon()
        self.assertEqual(r.state, OVER)
        self.assertEqual(r.score, 1)


class RobotTest(unittest.TestCase):
    def test_il_ne_bouge_pas_pendant_le_tour_du_joueur(self) -> None:
        """Aller se placer sous un ballon qui ne lui revient pas donnerait
        l'impression qu'il triche, ou qu'il attend une erreur."""
        r = _partie()
        self.assertTrue(r.player_turn)
        self.assertIsNone(ia.aim(r, PET_H))

    def test_il_vise_l_atterrissage_et_non_le_ballon(self) -> None:
        """Poursuivre la position courante d'un ballon qui dérive fait toujours
        suivre une trajectoire plus longue que la sienne : on arrive après."""
        r = _partie()
        r.hit(PLAYER, r.balloon.x - 30.0)
        for _ in range(20):
            r.step(DT)

        cible = ia.aim(r, PET_H)
        self.assertIsNotNone(cible)
        arrivee, _ = r.balloon.predict_landing()
        self.assertLess(abs(cible - arrivee), 0.6 * PET_H,
                        "il ne vise pas le point d'arrivée")

    def test_il_ne_frappe_pas_hors_de_portee(self) -> None:
        r = _partie()
        r.hit(PLAYER, r.balloon.x - 30.0)
        loin = r.balloon.x + 6.0 * PET_H
        self.assertFalse(ia.should_hit(r, loin, FLOOR - PET_H, PET_H))

    def test_une_partie_jouee_par_le_robot_seul_avance(self) -> None:
        """Le robot placé et alimenté doit produire des échanges : c'est le
        test qui échouerait si sa portée, sa visée ou l'alternance se
        contredisaient."""
        r = _partie(first=ROBOT)
        pet_x = r.balloon.x
        vitesse = PET_H / 0.63              # la marche du produit, en px/s
        for _ in range(int(25.0 / DT)):
            if r.over:
                break
            r.step(DT)
            cible = ia.aim(r, PET_H)
            if cible is not None:
                pas = vitesse * DT
                pet_x += max(-pas, min(pas, cible - pet_x))
                ia.play(r, pet_x, FLOOR - PET_H, PET_H)
            elif r.player_turn:
                # « Joueur » automatique : il frappe dès que le ballon est bas.
                if r.balloon.vy > 0 and FLOOR - r.balloon.y < 1.6 * PET_H:
                    r.hit(PLAYER, r.balloon.x - 0.3 * PET_H)
        self.assertGreater(r.score, 5,
                           "le robot n'arrive pas à entretenir un échange")


class ReachTest(unittest.TestCase):
    """La portée verticale du robot, corrigée après essai.

    Elle était confondue avec la portée horizontale : 0,95 hauteur de pet
    au-dessus du crâne, soit un ballon frappé à **deux fois sa propre hauteur**
    sans lever le bras ni sauter. Un robot qui touche ce qu'il ne peut
    visiblement pas atteindre annule l'enjeu du placement.
    """

    def _partie_robot(self, hauteur: float) -> Rally:
        r = Rally(_ballon(), first=ROBOT)
        r.state = PLAYING
        r.balloon.y = (FLOOR - PET_H) - hauteur * PET_H
        r.balloon.x = 900.0
        r.balloon._cooldown = 0.0
        return r

    def test_il_n_atteint_pas_un_ballon_au_dessus_de_sa_tete(self) -> None:
        for hauteur in (0.4, 0.7, 1.0, 2.0):
            r = self._partie_robot(hauteur)
            self.assertFalse(
                ia.should_hit(r, 900.0, FLOOR - PET_H, PET_H),
                "il frappe un ballon à %.1f hauteur au-dessus du crâne" % hauteur)

    def test_il_atteint_ce_qui_est_a_hauteur_de_tete(self) -> None:
        for hauteur in (0.0, 0.2):
            r = self._partie_robot(hauteur)
            self.assertTrue(ia.should_hit(r, 900.0, FLOOR - PET_H, PET_H),
                            "il rate un ballon sur sa tête")

    def test_un_ballon_au_niveau_du_corps_est_encore_a_lui(self) -> None:
        """Il joue aussi du torse."""
        r = self._partie_robot(-0.6)
        self.assertTrue(ia.should_hit(r, 900.0, FLOOR - PET_H, PET_H))

    def test_la_portee_horizontale_reste_bornee(self) -> None:
        r = self._partie_robot(0.0)
        self.assertFalse(ia.should_hit(r, 900.0 + 2.0 * PET_H,
                                       FLOOR - PET_H, PET_H))


class ScoreTest(unittest.TestCase):
    """Persistance des records — §14, et sobriété des écritures."""

    def setUp(self) -> None:
        import os
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self._dir.name

    def tearDown(self) -> None:
        import os
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old
        self._dir.cleanup()

    def _session(self):
        from pet.brain.session import Session

        s = Session()
        s.load()
        return s

    def test_un_record_est_conserve(self) -> None:
        s = self._session()
        self.assertEqual(s.best_score("rally"), 0)
        self.assertTrue(s.record_score("rally", 12))
        self.assertEqual(s.best_score("rally"), 12)

    def test_un_score_inferieur_n_ecrit_rien(self) -> None:
        """Une partie ratée n'a aucune raison de provoquer une écriture."""
        s = self._session()
        s.record_score("rally", 12)
        self.assertFalse(s.record_score("rally", 5))
        self.assertEqual(s.best_score("rally"), 12)

    def test_les_jeux_ne_se_marchent_pas_dessus(self) -> None:
        """Un dictionnaire plutôt qu'un champ par jeu : le second jeu ne doit
        pas demander de migration de schéma."""
        s = self._session()
        s.record_score("rally", 12)
        s.record_score("autre", 3)
        self.assertEqual(s.best_score("rally"), 12)
        self.assertEqual(s.best_score("autre"), 3)

    def test_il_survit_au_redemarrage(self) -> None:
        s = self._session()
        s.record_score("rally", 31)
        s.flush(force=True)
        self.assertEqual(self._session().best_score("rally"), 31)


if __name__ == "__main__":
    unittest.main()
