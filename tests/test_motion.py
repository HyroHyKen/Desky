"""Critères d'acceptation de l'animation d'interface, lot L9 (CDC §10, §3).

Deux exigences se rencontrent ici et tirent dans des sens opposés.

Le §10 veut du mouvement partout : « aucune interpolation linéaire sur un
mouvement visible », avec anticipation et dépassement. Le §3 veut moins de 4 %
d'un cœur au repos. Un panneau animé qui laisse son tic tourner pour toujours
respecte le premier et ruine le second.

D'où deux familles de tests : ceux qui vérifient que ça bouge **comme il faut**,
et ceux qui vérifient que ça **s'arrête**.
"""

from __future__ import annotations

import unittest

from pet.anim.easing import EASINGS, Spring, ease_in, ease_out_back
from pet.ui.motion import SpringBank, Tween

from .qt_app import ensure_app


class EasingPartageTest(unittest.TestCase):
    """L'easing a quitté le rig pour être utilisable par l'interface."""

    def test_easing_ne_depend_ni_de_la_geometrie_ni_de_qt(self) -> None:
        """C'est toute la raison de l'extraction du lot L9.

        Tant que les courbes vivaient dans `rig_pose`, animer un bouton tirait
        `geometry.rig` dans la couche d'interface. Le §10 vaut pour tout ce qui
        bouge à l'écran, pas seulement pour le robot.

        Le contrôle porte sur les **imports**, pas sur le texte du fichier :
        l'entête du module explique justement de quoi il s'est affranchi, et
        une recherche de chaîne prendrait cette explication pour la faute.
        """
        import ast
        from pathlib import Path

        import pet.anim.easing as easing

        arbre = ast.parse(Path(easing.__file__).read_text(encoding="utf-8"))
        importes: list[str] = []
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes += [a.name for a in noeud.names]
            elif isinstance(noeud, ast.ImportFrom):
                importes.append("." * noeud.level + (noeud.module or ""))

        for interdit in ("geometry", "PySide6", "render"):
            fautifs = [m for m in importes if interdit in m]
            self.assertEqual(fautifs, [],
                             "easing importe %s : %s" % (interdit, fautifs))

    def test_rig_pose_les_reexporte(self) -> None:
        """Tout ce qui les importait depuis là doit continuer de marcher."""
        from pet.anim import rig_pose

        self.assertIs(rig_pose.Spring, Spring)
        self.assertIs(rig_pose.ease_out_back, ease_out_back)

    def test_aucune_courbe_n_est_lineaire(self) -> None:
        """L'exigence du §10, vérifiée sur l'ensemble du registre."""
        for nom, courbe in EASINGS.items():
            ecart = max(abs(courbe(t / 20.0) - t / 20.0) for t in range(21))
            self.assertGreater(ecart, 0.02, "%s est quasi linéaire" % nom)


class SpringSettledTest(unittest.TestCase):
    """`settled` gouverne l'arrêt du tic : il doit être exact."""

    def test_un_ressort_au_repos_est_pose(self) -> None:
        s = Spring(1.0)
        self.assertTrue(s.settled(1.0))

    def test_passer_sur_la_cible_a_pleine_vitesse_n_est_pas_pose(self) -> None:
        """C'est le piège que `settled` existe pour éviter.

        Un ressort sous-amorti traverse sa cible **au milieu** d'un
        dépassement, position exacte et vitesse maximale. Ne tester que la
        position couperait l'animation précisément à l'instant que le §10
        réclame.
        """
        s = Spring(0.0, omega=20.0, zeta=0.4)
        traversee = False
        for _ in range(200):
            avant = float(s.value)
            s.step(1.0, 1.0 / 120.0)
            if avant < 1.0 <= float(s.value):
                traversee = True
                self.assertFalse(s.settled(1.0),
                                 "posé alors qu'il traverse sa cible en vitesse")
                break
        self.assertTrue(traversee, "le ressort n'a jamais dépassé sa cible")

    def test_il_finit_par_se_poser(self) -> None:
        s = Spring(0.0, omega=20.0, zeta=0.4)
        for _ in range(600):
            s.step(1.0, 1.0 / 120.0)
        self.assertTrue(s.settled(1.0))


class TweenTest(unittest.TestCase):
    def test_il_atteint_sa_cible_et_s_arrete(self) -> None:
        t = Tween(0.0)
        t.to(1.0, 0.2, ease_out_back)
        pas = 0
        while t.step(1.0 / 60.0):
            pas += 1
            self.assertLess(pas, 100, "le tween ne s'arrête pas")
        self.assertAlmostEqual(t.value, 1.0, places=6)
        self.assertFalse(t.moving)

    def test_l_arrivee_depasse_la_cible(self) -> None:
        """Le dépassement du §10, sur la valeur réellement peinte.

        Ce n'est pas une propriété de `ease_out_back` qu'on teste — elle est
        évidente — mais le fait que le `Tween` la laisse passer. Borner la
        valeur à [0, 1] quelque part sur le chemin supprimerait l'effet sans
        rien casser d'autre, et personne ne s'en apercevrait avant de regarder
        une vidéo au ralenti.
        """
        t = Tween(0.0)
        t.to(1.0, 0.3, ease_out_back)
        maximum = 0.0
        while t.step(1.0 / 120.0):
            maximum = max(maximum, t.value)
        self.assertGreater(maximum, 1.02, "l'arrivée ne dépasse pas")

    def test_une_nouvelle_cible_repart_de_la_valeur_atteinte(self) -> None:
        """Refermer un panneau à moitié ouvert doit partir d'où il en est."""
        t = Tween(0.0)
        t.to(1.0, 0.4, ease_out_back)
        for _ in range(6):
            t.step(1.0 / 60.0)
        milieu = t.value
        self.assertGreater(milieu, 0.0)
        self.assertLess(milieu, 1.0)

        t.to(0.0, 0.2, ease_in)
        t.step(1e-6)
        self.assertAlmostEqual(t.value, milieu, places=3)

    def test_jump_ne_bouge_pas(self) -> None:
        t = Tween(0.0)
        t.jump(1.0)
        self.assertEqual(t.value, 1.0)
        self.assertFalse(t.moving)
        self.assertFalse(t.step(1.0 / 60.0))


class StaggerTest(unittest.TestCase):
    """La cascade qui remplace le fondu."""

    def test_les_elements_partent_dans_l_ordre(self) -> None:
        from pet.ui.motion import Stagger

        cascade = Stagger(delai=0.04, duree=0.2, etalement=1.0)
        cascade.start(["a", "b", "c"])
        cascade.step(0.02)
        self.assertGreater(cascade.value("a"), 0.0)
        self.assertEqual(cascade.value("b"), 0.0, "b est parti avec a")
        self.assertEqual(cascade.value("c"), 0.0)

    def test_le_premier_arrive_avant_le_dernier(self) -> None:
        from pet.ui.motion import Stagger

        cascade = Stagger(delai=0.04, duree=0.2, etalement=1.0)
        cascade.start(["a", "b", "c"])
        while cascade.value("a") < 1.0:
            cascade.step(1.0 / 240.0)
        self.assertLess(cascade.value("c"), 1.0)

    def test_l_etalement_plafonne_la_duree_totale(self) -> None:
        """Sans plafond, douze pastilles mettent près d'une seconde à
        s'installer — et à partir de là on n'admire plus, on attend."""
        from pet.ui.motion import Stagger

        def duree(nombre: int) -> float:
            cascade = Stagger(delai=0.035, duree=0.30, etalement=0.17)
            cascade.start(["e%d" % i for i in range(nombre)])
            t = 0.0
            while cascade.step(1.0 / 240.0):
                t += 1.0 / 240.0
            return t

        self.assertLess(duree(4), 0.48)
        self.assertLess(duree(12), 0.48)
        self.assertLess(duree(30), 0.48)

    def test_une_cle_inconnue_est_deja_en_place(self) -> None:
        """Un bouton qui se dégrise au milieu d'une page établie ne doit pas
        entrer en cascade : ce serait un sursaut sans cause visible."""
        from pet.ui.motion import Stagger

        cascade = Stagger()
        cascade.start(["a"])
        self.assertEqual(cascade.value("jamais_annonce"), 1.0)

    def test_l_arrivee_depasse(self) -> None:
        from pet.ui.motion import Stagger

        cascade = Stagger(delai=0.0, duree=0.3)
        cascade.start(["a"])
        maximum = 0.0
        while cascade.step(1.0 / 240.0):
            maximum = max(maximum, cascade.value("a"))
        self.assertGreater(maximum, 1.02, "la cascade n'a pas de rebond")

    def test_finish_solde_tout(self) -> None:
        from pet.ui.motion import Stagger

        cascade = Stagger()
        cascade.start(["a", "b"])
        cascade.finish()
        self.assertFalse(cascade.moving)
        self.assertEqual(cascade.value("b"), 1.0)


class SpringBankTest(unittest.TestCase):
    def test_une_identite_inconnue_rend_le_repos(self) -> None:
        banc = SpringBank()
        self.assertEqual(banc.value("jamais_vu"), 0.0)

    def test_il_poursuit_la_cible_puis_s_arrete(self) -> None:
        banc = SpringBank(omega=30.0, zeta=0.8)
        banc.target("soin", 1.0)
        pas = 0
        while banc.step(1.0 / 60.0):
            pas += 1
            self.assertLess(pas, 400, "le banc ne s'arrête jamais")
        self.assertAlmostEqual(banc.value("soin"), 1.0, places=3)
        self.assertFalse(banc.moving)

    def test_keep_oublie_les_identites_disparues(self) -> None:
        """Sans purge, changer de page vingt fois laisse vingt jeux de
        ressorts qu'on continuerait d'avancer — et le tic ne s'arrêterait
        plus jamais."""
        banc = SpringBank()
        banc.target("status", 1.0)
        banc.target("shop", 1.0)
        banc.step(1.0 / 60.0)

        banc.keep(["status"])
        self.assertEqual(banc.value("shop"), 0.0)
        self.assertNotEqual(banc.value("status"), 0.0)

    def test_une_cible_qui_change_en_vol_conserve_la_vitesse(self) -> None:
        """Le curseur qui entre, sort, ré-entre avant la fin du mouvement.

        Un tween serait relancé depuis une valeur intermédiaire, vitesse
        remise à zéro : le bouton marquerait un arrêt net à chaque
        changement d'avis. Un ressort transporte sa vitesse, et c'est
        exactement ce qu'on vérifie ici — poser une cible ne touche ni la
        position ni la vitesse, seule l'accélération change.
        """
        banc = SpringBank(omega=26.0, zeta=0.85)
        banc.target("bouton", 1.0)
        for _ in range(4):
            banc.step(1.0 / 60.0)

        position = banc.value("bouton")
        vitesse = banc._ressorts["bouton"].velocity
        self.assertGreater(vitesse, 0.5, "le ressort devrait être lancé")

        banc.target("bouton", 0.0)
        self.assertEqual(banc.value("bouton"), position)
        self.assertEqual(banc._ressorts["bouton"].velocity, vitesse)


class TickerTest(unittest.TestCase):
    """Le tic doit s'éteindre seul. C'est le §3 dans cette couche."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def test_il_s_arrete_quand_plus_rien_ne_bouge(self) -> None:
        from pet.ui.motion import Ticker

        restant = [3]

        def step(dt: float) -> bool:
            restant[0] -= 1
            return restant[0] > 0

        peintures = []
        ticker = Ticker(step, lambda: peintures.append(1))
        ticker.wake()
        self.assertTrue(ticker.running)
        for _ in range(3):
            ticker._on_tick()
        self.assertFalse(ticker.running, "le tic tourne encore dans le vide")
        self.assertEqual(len(peintures), 3)

    def test_reveiller_un_tic_deja_actif_ne_le_redemarre_pas(self) -> None:
        from pet.ui.motion import Ticker

        ticker = Ticker(lambda dt: True, lambda: None)
        ticker.wake()
        ticker.wake()
        self.assertTrue(ticker.running)
        ticker.stop()
        self.assertFalse(ticker.running)


if __name__ == "__main__":
    unittest.main()
