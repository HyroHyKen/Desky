"""Critères d'acceptation du multi-écran et du plein écran, lot L1 (CDC §6).

La géométrie de position et le choix de moniteur sont testés en pur, sans GPU ni
fenêtre. La détection de plein écran, elle, est testée contre une **vraie**
fenêtre plein écran : c'est le seul moyen de vérifier que le shell n'est pas pris
pour une application, ce qui masquerait le pet en permanence.
"""

from __future__ import annotations

import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from pet.app import win32
from pet.app.clock import Regime, RenderClock
from pet.anim.impact import Impact
from pet.app.window import (PetWindow, choose_monitor, floor_y,
                            frac_to_position, position_to_frac)

from .qt_app import ensure_app


class FakeMonitor:
    def __init__(self, key: str, primary: bool = False) -> None:
        self.key = key
        self.primary = primary


class PositionGeometryTest(unittest.TestCase):
    # Écran principal réel de la machine de dev : 1920x1200, barre des tâches
    # de 40 px, donc une zone de travail de 1160 de haut.
    WORK = (0, 0, 1920, 1160)
    PET = (220, 220)

    def test_aller_retour_exact(self) -> None:
        for x, y in [(0, 940), (1394, 940), (1700, 500), (860, 0)]:
            frac, gap = position_to_frac(x, y, self.PET, self.WORK)
            rx, ry = frac_to_position(frac, gap, self.PET, self.WORK)
            self.assertAlmostEqual(rx, x, delta=1.0, msg=f"x pour ({x},{y})")
            self.assertAlmostEqual(ry, y, delta=1.0, msg=f"y pour ({x},{y})")

    def test_pose_au_sol_donne_un_ecart_nul(self) -> None:
        y = floor_y(self.WORK, self.PET[1])
        self.assertEqual(y, 940.0)
        _, gap = position_to_frac(1000, y, self.PET, self.WORK)
        self.assertEqual(gap, 0)

    def test_survit_a_un_changement_de_resolution(self) -> None:
        """Le pet reste sur l'écran après un passage en 1280x720.

        C'est la raison d'être du stockage en fraction plutôt qu'en pixels : une
        position absolue de 1700 px serait hors écran après la bascule.
        """
        frac, gap = position_to_frac(1700, 940, self.PET, self.WORK)
        petite = (0, 0, 1280, 680)
        x, y = frac_to_position(frac, gap, self.PET, petite)
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(x + self.PET[0], 1280)
        self.assertEqual(y, floor_y(petite, self.PET[1]))

    def test_ecran_a_coordonnees_negatives(self) -> None:
        """Le montage de la machine de dev a un écran en X et Y négatifs."""
        work = (-1920, -19, 1920, 1040)
        frac, gap = position_to_frac(-500, 801, self.PET, work)
        x, y = frac_to_position(frac, gap, self.PET, work)
        self.assertAlmostEqual(x, -500, delta=1.0)
        self.assertAlmostEqual(y, 801, delta=1.0)

    def test_fraction_hors_bornes_est_ramenee(self) -> None:
        x, _ = frac_to_position(9.0, 0, self.PET, self.WORK)
        self.assertEqual(x, 1920 - 220)
        x, _ = frac_to_position(-3.0, 0, self.PET, self.WORK)
        self.assertEqual(x, 0)

    def test_pet_plus_large_que_l_ecran(self) -> None:
        """Cas dégénéré : ne doit pas diviser par zéro."""
        frac, gap = position_to_frac(0, 0, (2000, 2000), self.WORK)
        self.assertGreaterEqual(frac, 0.0)
        x, y = frac_to_position(frac, gap, (2000, 2000), self.WORK)
        self.assertEqual(x, 0.0)


class MonitorChoiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.a = FakeMonitor("MON-A", primary=True)
        self.b = FakeMonitor("MON-B")

    def test_moniteur_memorise_present(self) -> None:
        mon, fell_back = choose_monitor([self.a, self.b], "MON-B")
        self.assertIs(mon, self.b)
        self.assertFalse(fell_back)

    def test_repli_quand_le_moniteur_a_disparu(self) -> None:
        """CDC §6 : repositionnement si l'écran disparaît."""
        mon, fell_back = choose_monitor([self.a], "MON-B")
        self.assertIs(mon, self.a)
        self.assertTrue(fell_back, "le repli doit être signalé pour être journalisé")

    def test_premier_lancement_sans_cle(self) -> None:
        mon, fell_back = choose_monitor([self.a, self.b], "")
        self.assertIs(mon, self.a)
        self.assertFalse(fell_back, "un premier lancement n'est pas un repli")

    def test_sans_ecran_principal_declare(self) -> None:
        c, d = FakeMonitor("C"), FakeMonitor("D")
        mon, _ = choose_monitor([c, d], "inconnu")
        self.assertIs(mon, c)

    def test_aucun_moniteur_est_une_erreur(self) -> None:
        with self.assertRaises(ValueError):
            choose_monitor([], "MON-A")


class MonitorEnumerationTest(unittest.TestCase):
    """Vérifie l'énumération réelle des moniteurs de la machine."""

    def test_au_moins_un_moniteur_et_un_seul_principal(self) -> None:
        monitors = win32.list_monitors()
        self.assertGreaterEqual(len(monitors), 1)
        self.assertEqual(sum(1 for m in monitors if m.primary), 1)
        self.assertTrue(monitors[0].primary, "l'écran principal doit venir en premier")

    def test_les_cles_sont_uniques_et_non_vides(self) -> None:
        keys = [m.key for m in win32.list_monitors()]
        self.assertTrue(all(keys), "une clé vide casserait la mémorisation")
        self.assertEqual(len(keys), len(set(keys)), "clés dupliquées entre moniteurs")

    def test_la_zone_de_travail_tient_dans_l_ecran(self) -> None:
        for m in win32.list_monitors():
            rl, rt, rw, rh = m.rect
            wl, wt, ww, wh = m.work
            self.assertGreaterEqual(wl, rl)
            self.assertGreaterEqual(wt, rt)
            self.assertLessEqual(wl + ww, rl + rw)
            self.assertLessEqual(wt + wh, rt + rh)

    def test_le_moniteur_sous_le_curseur_contient_le_curseur(self) -> None:
        cx, cy = win32.get_cursor_pos()
        m = win32.monitor_from_point(cx, cy)
        ml, mt, mw, mh = m.rect
        self.assertTrue(ml <= cx < ml + mw and mt <= cy < mt + mh)


class FullscreenDetectionTest(unittest.TestCase):
    """CDC §6 : masquer le pet sous une application en plein écran exclusif."""

    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_app()

    @staticmethod
    def _spin(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def test_le_bureau_nu_n_est_pas_du_plein_ecran(self) -> None:
        """Le test le plus important : un faux positif ici masquerait le pet
        en permanence, ce qui ressemblerait à une application qui ne démarre pas.

        Le shell (`Progman`, `WorkerW`, la barre des tâches) couvre en effet tout
        l'écran en permanence, et doit donc être écarté explicitement.
        """
        for cls_name in ("Progman", "WorkerW", "Shell_TrayWnd"):
            self.assertIn(cls_name, win32._SHELL_CLASSES,
                          f"{cls_name} doit être écarté de la détection")

    def test_detecte_une_vraie_fenetre_plein_ecran(self) -> None:
        w = QWidget()
        w.setWindowTitle("plein ecran de test")
        w.showFullScreen()
        self._spin(600)                     # laisse le compositeur s'installer

        try:
            hwnd = int(w.winId())
            detected = win32.foreground_fullscreen_monitor(own_hwnd=0)
            if detected is None:
                self.skipTest("la fenêtre de test n'a pas obtenu le premier plan "
                              "(session verrouillée ou focus volé par un tiers)")
            # Le moniteur attendu est celui qui porte effectivement la
            # fenêtre, pas l'écran principal : Qt ouvre le plein écran sur
            # l'écran courant, qui peut être n'importe lequel des trois.
            attendu = win32.monitor_from_window(hwnd)
            self.assertEqual(detected.key, attendu.key)
            # Le pet lui-même ne doit jamais se détecter comme plein écran.
            self.assertIsNone(win32.foreground_fullscreen_monitor(own_hwnd=hwnd))
        finally:
            w.close()
            self._spin(300)

    def test_plus_de_plein_ecran_apres_fermeture(self) -> None:
        w = QWidget()
        w.showFullScreen()
        self._spin(500)
        w.close()
        self._spin(600)
        self.assertIsNone(win32.foreground_fullscreen_monitor(own_hwnd=0),
                          "le pet doit réapparaître dès la fermeture du plein écran")

    def test_l_horloge_se_suspend_et_reprend(self) -> None:
        """Chaîne complète : détection -> horloge -> 0 fps -> reprise."""
        clock = RenderClock()
        ticks = []
        clock.tick.connect(lambda: ticks.append(1))
        clock.start()

        clock.set_suspended(True)
        ticks.clear()
        self._spin(700)
        self.assertEqual(len(ticks), 0, "aucun rendu ne doit avoir lieu à l'état masqué")
        self.assertEqual(clock.regime, Regime.SUSPENDED)

        clock.set_suspended(False)
        ticks.clear()
        self._spin(700)
        self.assertGreater(len(ticks), 0, "le rendu doit reprendre")
        clock.stop()


class CuriousGazeTest(unittest.TestCase):
    """Les coups d'oeil inventés par le pet.

    C'est la seule cible du regard qui ne vienne de rien d'observable, et c'est
    ce qui la rend vivante : un regard purement réactif suit, un regard qui part
    de lui-même suggère une intention.
    """

    WORK = (0, 0, 1920, 1160)

    def _gaze(self, seed: int = 3):
        from pet.anim.curiosity import CuriousGaze
        return CuriousGaze(seed=seed)

    def _run(self, gaze, seconds: float, curious: bool, dt: float = 0.05):
        vus = []
        for _ in range(int(seconds / dt)):
            vus.append(gaze.update(dt, curious, self.WORK, 900.0, 220.0))
        return vus

    def test_un_pet_qui_n_est_pas_curieux_ne_regarde_nulle_part(self) -> None:
        vus = self._run(self._gaze(), 120.0, curious=False)
        self.assertTrue(all(p is None for p in vus))

    def test_la_curiosite_ponctue_sans_distraire(self) -> None:
        """Trop fréquent, le pet aurait l'air distrait plutôt que curieux."""
        vus = self._run(self._gaze(), 120.0, curious=True)
        coups = sum(1 for a, b in zip(vus, vus[1:]) if a is None and b is not None)
        part = sum(1 for p in vus if p is not None) / len(vus)
        self.assertGreaterEqual(coups, 4, "il ne regarde jamais ailleurs")
        self.assertLessEqual(coups, 20, "il est distrait, pas curieux")
        self.assertLess(part, 0.35, "il passe son temps à regarder ailleurs")

    def test_un_coup_d_oeil_tient_sa_cible(self) -> None:
        """Un point qui saute à chaque image ne se lirait pas comme un regard."""
        gaze = self._gaze()
        vus = [p for p in self._run(gaze, 120.0, curious=True) if p is not None]
        self.assertTrue(vus)
        suite = []
        courant = None
        for point in vus:
            if point != courant:
                courant = point
                suite.append(1)
            else:
                suite[-1] += 1
        # Chaque cible doit tenir au moins une seconde, soit vingt images.
        self.assertGreaterEqual(min(suite), 20)

    def test_il_regarde_assez_loin_pour_que_ca_se_voie(self) -> None:
        from pet.anim.curiosity import GLANCE_MIN_DISTANCE

        vus = [p for p in self._run(self._gaze(), 200.0, curious=True)
               if p is not None]
        self.assertTrue(vus)
        for x, _ in vus:
            self.assertGreaterEqual(abs(x - 900.0),
                                    GLANCE_MIN_DISTANCE * 220.0 - 1.0)

    def test_il_ne_regarde_pas_le_sol(self) -> None:
        """Un regard levé suggère qu'il a vu quelque chose ; baissé, rien."""
        _, wt, _, wh = self.WORK
        vus = [p for p in self._run(self._gaze(), 200.0, curious=True)
               if p is not None]
        for _, y in vus:
            self.assertLess(y, wt + wh * 0.6)

    def test_le_point_reste_dans_l_ecran(self) -> None:
        wl, wt, ww, wh = self.WORK
        vus = [p for p in self._run(self._gaze(), 200.0, curious=True)
               if p is not None]
        for x, y in vus:
            self.assertGreaterEqual(x, wl)
            self.assertLessEqual(x, wl + ww)
            self.assertGreaterEqual(y, wt)
            self.assertLessEqual(y, wt + wh)

    def test_la_graine_rend_le_temperament_reproductible(self) -> None:
        """Comme le rythme des clignements : il appartient à l'identité."""
        a = self._run(self._gaze(7), 90.0, curious=True)
        b = self._run(self._gaze(7), 90.0, curious=True)
        self.assertEqual(a, b)
        c = self._run(self._gaze(8), 90.0, curious=True)
        self.assertNotEqual(a, c)

    def test_un_ecran_etroit_ne_boucle_pas(self) -> None:
        """Garde-fou : aucune place lointaine ne doit pas faire tourner en rond."""
        from pet.anim.curiosity import CuriousGaze

        gaze = CuriousGaze(seed=1)
        vus = [gaze.update(0.05, True, (0, 0, 200, 200), 100.0, 220.0)
               for _ in range(2000)]
        self.assertTrue(any(p is not None for p in vus))


class LookTargetTest(unittest.TestCase):
    """La liste de priorités du regard, et ce qu'elle a le droit de lire."""

    def test_la_cible_est_resolue_en_un_seul_endroit(self) -> None:
        """Deux résolutions finiraient par diverger, comme toute géométrie."""
        import inspect

        source = inspect.getsource(PetWindow._anim_context)
        self.assertIn("_look_point", source)
        self.assertNotIn("sensors.cursor.position", source,
                         "le contexte d'animation retourne lire le curseur")

        boucle = inspect.getsource(PetWindow._on_render)
        self.assertIn("_look_target(", boucle)

    def test_toutes_les_sources_sont_couvertes(self) -> None:
        import inspect

        source = inspect.getsource(PetWindow._look_target)
        for source_nom in ("item", "glance", "media", "caret", "window",
                           "cursor"):
            self.assertIn('"%s"' % source_nom, source,
                          "la source %s n'est jamais attribuée" % source_nom)

    def test_la_fenetre_active_ne_livre_qu_une_geometrie(self) -> None:
        """Le §11 interdit de stocker un titre ; un rectangle n'en est pas un."""
        centre = win32.foreground_window_center(0)
        if centre is not None:
            x, y = centre
            self.assertIsInstance(x, int)
            self.assertIsInstance(y, int)

    def test_notre_propre_fenetre_n_est_pas_une_cible(self) -> None:
        """Sinon le pet se regarderait lui-même dès qu'il a le premier plan."""
        propre = win32.get_foreground_window()
        if propre:
            self.assertIsNone(win32.foreground_window_center(propre))

    def test_le_caret_ne_leve_jamais(self) -> None:
        """Il rend None **souvent** : beaucoup d'applis ne le publient pas."""
        for _ in range(3):
            valeur = win32.caret_position()
            if valeur is not None:
                self.assertEqual(len(valeur), 2)


class EdgeTravelTest(unittest.TestCase):
    """« Fouine près du bord de **l'écran** » — au singulier.

    Régression signalée par des utilisateurs : le pet faisait cinq ou six sauts
    d'un côté puis autant pour revenir. La cause était que `sniff_around` visait
    le bord du **terrain**, c'est-à-dire la bande praticable fusionnée de tous
    les moniteurs. Mesuré sur un montage à trois écrans : 3 532 px de trajet
    médian pour cette action, contre 379 pour la flânerie.
    """

    ECRAN = (0, 0, 1920, 1160)
    BANDE = (-1920, 3840)

    def _stub(self, pet_x: float):
        from pet.anim.locomotion import Ground, Terrain
        from pet.app.window import PetWindow
        from pet.brain.utility import SelfState

        class _FauxLoco:
            def __init__(self, terrain):
                self.terrain = terrain
                self.cibles = []

            def go_to(self, x):
                self.cibles.append(x)
                return True

            def stop(self):
                pass

            def wander(self):
                return True

            def go_home(self):
                return True

        class _FauxMoniteur:
            work = EdgeTravelTest.ECRAN

        terrain = Terrain.from_grounds([
            Ground("gauche", -1920.0, 0.0, 1000.0),
            Ground("centre", 0.0, 1920.0, 1000.0),
            Ground("droite", 1920.0, 3840.0, 1000.0),
        ], 220)

        w = PetWindow.__new__(PetWindow)
        w.animator = None
        w.locomotion = _FauxLoco(terrain)
        w._me = SelfState(x=pet_x)
        w.current_monitor = lambda: _FauxMoniteur()
        w.sensors = None
        return w

    def _target(self, pet_x: float) -> float:
        from pet.brain.utility import Plan

        w = self._stub(pet_x)
        w._apply_plan(Plan("sniff_around", travel="edge"), 220)
        self.assertEqual(len(w.locomotion.cibles), 1)
        return w.locomotion.cibles[0]

    def test_la_cible_reste_sur_l_ecran_courant(self) -> None:
        wl, _, ww, _ = self.ECRAN
        for pet_x in (100.0, 600.0, 960.0, 1400.0, 1850.0):
            cible = self._target(pet_x)
            self.assertGreaterEqual(cible, wl - 1.0,
                                    "il sort de l'écran par la gauche")
            self.assertLessEqual(cible, wl + ww + 1.0,
                                 "il sort de l'écran par la droite")

    def test_le_trajet_ne_depasse_pas_une_largeur_d_ecran(self) -> None:
        """C'est la propriété qui manquait, et tout le symptôme en découlait."""
        _, _, ww, _ = self.ECRAN
        for pet_x in (100.0, 960.0, 1850.0):
            self.assertLessEqual(abs(self._target(pet_x) - pet_x), ww,
                                 "le fouinage traverse plus d'un écran")

    def test_il_fouine_du_cote_oppose(self) -> None:
        """Sinon il fouinerait le bord sur lequel il est déjà posé."""
        wl, _, ww, _ = self.ECRAN
        milieu = wl + ww / 2.0
        self.assertGreater(self._target(wl + 100.0), milieu)
        self.assertLess(self._target(wl + ww - 100.0), milieu)

    def test_la_cible_reste_praticable(self) -> None:
        """Un écran peut déborder de la bande à ses extrémités."""
        from pet.anim.locomotion import Ground, Terrain

        gauche, droite = Terrain.from_grounds([
            Ground("centre", 0.0, 1920.0, 1000.0)], 220).span
        for pet_x in (100.0, 1800.0):
            w = self._stub(pet_x)
            w.locomotion.terrain = Terrain.from_grounds([
                Ground("centre", 0.0, 1920.0, 1000.0)], 220)
            from pet.brain.utility import Plan
            w._apply_plan(Plan("sniff_around", travel="edge"), 220)
            cible = w.locomotion.cibles[0]
            self.assertGreaterEqual(cible, gauche)
            self.assertLessEqual(cible, droite)


if __name__ == "__main__":
    unittest.main()


class FrameDemandTest(unittest.TestCase):
    """La cadence doit suivre ce que le pet **fait**, pas la souris.

    Régression restée invisible deux lots : l'horloge adaptative du §3 n'était
    sollicitée que par le curseur entrant dans la boîte du pet. Juste au lot L1,
    où le pet ne bougeait que si on le tirait ; faux depuis les lots L5b et L6,
    où il se déplace seul. Mesuré avant correctif : 1 200 px de trajet et une
    traversée d'écran, intégralement à 9 fps.

    Le prédicat est testé sur une instance non initialisée, dont on ne renseigne
    que les champs qu'il lit : c'est ce qui permet de le vérifier sans GPU, sans
    hwnd et sans robot.
    """

    def _stub(self, **kwargs):
        w = PetWindow.__new__(PetWindow)
        w._dragging = False
        w._falling = False
        w.panel = None
        w._x, w._y = 100.0, 200.0
        w._frame_pos = (100, 200)
        w.locomotion = None
        w.animator = None
        w._bubble_opacity = 0.0
        w._eye_mix = 0.0
        w._intro_phase = ""
        w.item = None
        # Un encaissement en cours déforme le corps sans déplacer la fenêtre :
        # le prédicat le lit, donc le montage doit le fournir (lot L10).
        w._impact = Impact()
        w.dust = None
        w.rally = None
        for cle, valeur in kwargs.items():
            setattr(w, cle, valeur)
        return w

    def test_un_pet_immobile_ne_demande_rien(self) -> None:
        self.assertFalse(self._stub()._wants_frames())

    def test_un_deplacement_demande_des_images(self) -> None:
        """Le critère est le mouvement effectif, quelle qu'en soit la cause."""
        w = self._stub()
        w._x = 140.0
        self.assertTrue(w._wants_frames())

    def test_un_deplacement_sous_le_pixel_ne_compte_pas(self) -> None:
        w = self._stub()
        w._x = 100.3
        self.assertFalse(w._wants_frames())

    def test_la_chute_et_le_glisser_demandent_des_images(self) -> None:
        self.assertTrue(self._stub(_falling=True)._wants_frames())
        self.assertTrue(self._stub(_dragging=True)._wants_frames())

    def test_un_fondu_de_bulle_demande_des_images(self) -> None:
        self.assertTrue(self._stub(_bubble_opacity=0.5)._wants_frames())
        self.assertTrue(self._stub(_eye_mix=0.5)._wants_frames())

    def test_une_bulle_posee_se_contente_du_repos(self) -> None:
        """Sa respiration d'appel est assez lente pour 10 fps."""
        self.assertFalse(self._stub(_bubble_opacity=1.0)._wants_frames())

    def test_un_objet_en_mouvement_demande_des_images(self) -> None:
        """Il tombe, on le traîne, il se fait manger : tout ça se voit."""
        class _FauxObjet:
            def __init__(self, state):
                self.state = state

        for etat in ("falling", "held", "consumed", "expiring"):
            self.assertTrue(self._stub(item=_FauxObjet(etat))._wants_frames(),
                            "un objet en état " + etat + " ne réclame rien")
        self.assertFalse(self._stub(item=_FauxObjet("idle"))._wants_frames(),
                         "un objet posé se contente du repos")

    def test_la_scene_d_arrivee_demande_des_images(self) -> None:
        """Elle est scriptée : rien ne bouge la fenêtre, tout bouge le robot."""
        from pet.app.window import INTRO_SCRIPTED

        for phase in INTRO_SCRIPTED:
            self.assertTrue(self._stub(_intro_phase=phase)._wants_frames(),
                            f"la phase {phase} ne réclame pas d'images")
        # « asking » n'est qu'une attente : la bulle posée se contente du repos.
        self.assertFalse(self._stub(_intro_phase="asking")._wants_frames())

    def test_la_boucle_de_rendu_sollicite_l_horloge(self) -> None:
        """Le prédicat ne sert à rien s'il n'est pas branché."""
        import inspect

        source = inspect.getsource(PetWindow._on_render)
        self.assertIn("_wants_frames()", source)
        self.assertIn("clock.poke()", source)
