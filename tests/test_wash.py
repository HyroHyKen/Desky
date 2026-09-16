"""Critères d'acceptation du bain, lot L15 (CDC §12, §13).

Le bain a une obligation que le reste du soin n'a pas : **il doit pouvoir se
terminer**. Un objet de soin qu'on n'atteint pas s'évapore et rend l'article ;
un rituel qui n'aboutit pas, lui, immobilise le robot. C'est ce qui explique le
poids donné ici à la fin de la séquence — la couverture atteignable, l'abandon,
le crédit partiel — plutôt qu'au réglage des durées.

Tout se joue à `dt` synthétique, sans écran : c'est l'intérêt d'avoir gardé le
modèle hors de Qt.
"""

from __future__ import annotations

import math
import unittest

from pet.care.wash import (DONE, GRID_COLS, GRID_ROWS, SCRUB_RADIUS, SPONGE,
                           SPRAY, SPRAY_ARM, SPRAY_COUNT, SPRAY_INTERVAL, Wash)

DT = 1.0 / 60.0


def _frotter_partout(bain: Wash) -> None:
    """Passe l'éponge sur le centre de chaque case."""
    for index in range(GRID_COLS * GRID_ROWS):
        u, v = bain.cell_center(index)
        bain.scrub(u, v)


def _laisser_partir_la_mousse(bain: Wash, limite: float = 5.0) -> float:
    t = 0.0
    while bain.state == SPONGE and t < limite:
        bain.step(DT)
        t += DT
    return t


def _rincer(bain: Wash, jets: int = SPRAY_COUNT) -> int:
    """Approche le spray du centre jusqu'à obtenir `jets` jets."""
    partis = 0
    t = 0.0
    while partis < jets and t < 30.0:
        if bain.aim(0.5, 0.5, DT):
            partis += 1
        bain.step(DT)
        t += DT
    return partis


class SpongeTest(unittest.TestCase):
    def test_un_seul_endroit_ne_suffit_pas(self) -> None:
        bain = Wash()
        bain.scrub(0.5, 0.5)
        self.assertLess(bain.progress, 1.0)
        self.assertEqual(bain.state, SPONGE)

    def test_frotter_partout_couvre_tout(self) -> None:
        bain = Wash()
        _frotter_partout(bain)
        self.assertTrue(bain.scrubbed)
        self.assertAlmostEqual(bain.progress, 1.0)

    def test_la_mousse_nait_sous_l_eponge(self) -> None:
        """Elle marque **où on est passé**, sinon elle ne sert à rien."""
        bain = Wash()
        bain.scrub(0.2, 0.2)
        self.assertTrue(bain.foam)
        for flocon in bain.foam:
            self.assertLess(abs(flocon.u - 0.2), 0.45)
            self.assertLess(abs(flocon.v - 0.2), 0.45)

    def test_la_mousse_part_puis_le_spray_arrive(self) -> None:
        """L'ordre compte : voir son travail avant de le rincer."""
        bain = Wash()
        _frotter_partout(bain)
        self.assertTrue(bain.rinsing)
        self.assertEqual(bain.state, SPONGE, "le spray arrive avant le rinçage")
        _laisser_partir_la_mousse(bain)
        self.assertEqual(bain.state, SPRAY)
        self.assertFalse(bain.foam)

    def test_on_ne_remousse_pas_pendant_le_rincage(self) -> None:
        bain = Wash()
        _frotter_partout(bain)
        bain.step(DT)
        avant = len(bain.foam)
        self.assertEqual(bain.scrub(0.5, 0.5), 0)
        self.assertLessEqual(len(bain.foam), avant)

    def test_les_cases_hors_silhouette_ne_bloquent_pas(self) -> None:
        """Sinon le bain ne se finit qu'en frottant du vide, ce qui ne se
        devine pas — et le §12 interdit de perdre sur une règle invisible."""
        masque = tuple(i % 2 == 0 for i in range(GRID_COLS * GRID_ROWS))
        bain = Wash(mask=masque)
        _frotter_partout(bain)
        self.assertTrue(bain.scrubbed)

    def test_une_silhouette_vide_donne_un_bain_faisable(self) -> None:
        """Pas d'image rendue : on préfère un bain trop facile à un bain
        impossible."""
        bain = Wash(mask=tuple([False] * (GRID_COLS * GRID_ROWS)))
        _frotter_partout(bain)
        self.assertTrue(bain.scrubbed)

    def test_la_zone_de_frottement_est_ronde_a_l_ecran(self) -> None:
        """En coordonnées normalisées, un disque deviendrait un ovale : sur un
        robot élancé, un coup d'éponge couvrirait bien plus haut que large.

        On vérifie la règle plutôt qu'une forme observée : est couverte
        exactement la case dont le centre est à moins d'un rayon **en pixels**.
        Compter les cases n'aurait rien dit — la grille n'est pas carrée, donc
        il n'existe même pas de case à la même distance dans les deux axes.
        """
        bain = Wash(aspect=2.0)
        bain.scrub(0.5, 0.5)
        for index in range(GRID_COLS * GRID_ROWS):
            u, v = bain.cell_center(index)
            pixels = math.hypot(u - 0.5, (v - 0.5) * bain.aspect)
            self.assertEqual(index in bain._covered, pixels <= SCRUB_RADIUS,
                             "case %d à %.3f largeur de robot" % (index, pixels))


class SprayTest(unittest.TestCase):
    def _au_spray(self) -> Wash:
        bain = Wash()
        _frotter_partout(bain)
        _laisser_partir_la_mousse(bain)
        return bain

    def test_quatre_jets_suffisent(self) -> None:
        bain = self._au_spray()
        self.assertEqual(_rincer(bain), SPRAY_COUNT)
        self.assertEqual(bain.state, DONE)

    def test_loin_du_robot_rien_ne_part(self) -> None:
        bain = self._au_spray()
        for _ in range(240):
            self.assertFalse(bain.aim(3.0, 0.5, DT))
            bain.step(DT)
        self.assertEqual(bain.sprays, 0)

    def test_les_jets_sont_espaces(self) -> None:
        """Sans délai, traverser l'écran une fois rincerait tout le robot."""
        bain = self._au_spray()
        instants = []
        t = 0.0
        while bain.sprays < SPRAY_COUNT and t < 30.0:
            if bain.aim(0.5, 0.5, DT):
                instants.append(t)
            bain.step(DT)
            t += DT
        for avant, apres in zip(instants, instants[1:]):
            self.assertGreaterEqual(apres - avant, SPRAY_INTERVAL - DT)

    def test_le_premier_jet_attend_l_armement(self) -> None:
        """Il ne part pas dans l'image où l'on saisit l'objet."""
        bain = self._au_spray()
        self.assertFalse(bain.aim(0.5, 0.5, DT))
        self.assertLess(SPRAY_ARM, SPRAY_INTERVAL)

    def test_sortir_de_portee_desarme(self) -> None:
        bain = self._au_spray()
        bain.aim(0.5, 0.5, DT)
        bain.aim(5.0, 5.0, DT)          # on s'éloigne
        self.assertFalse(bain.aim(0.5, 0.5, DT),
                         "un jet part sans nouvel armement")

    def test_on_ne_frotte_plus_une_fois_au_spray(self) -> None:
        bain = self._au_spray()
        self.assertEqual(bain.scrub(0.5, 0.5), 0)
        self.assertFalse(bain.foam)

    def test_une_partie_finie_ne_bouge_plus(self) -> None:
        bain = self._au_spray()
        _rincer(bain)
        jets = bain.sprays
        for _ in range(120):
            bain.aim(0.5, 0.5, DT)
            bain.step(DT)
        self.assertEqual(bain.sprays, jets)


class CreditTest(unittest.TestCase):
    """Ce que vaut un bain interrompu. Le §12 interdit de ne rien rendre."""

    def test_un_bain_complet_vaut_tout(self) -> None:
        bain = Wash()
        _frotter_partout(bain)
        _laisser_partir_la_mousse(bain)
        _rincer(bain)
        self.assertEqual(bain.credit(), 1.0)

    def test_un_bain_jamais_commence_ne_vaut_rien(self) -> None:
        bain = Wash()
        bain.abandon()
        self.assertEqual(bain.credit(), 0.0)

    def test_un_bain_a_moitie_fait_vaut_quelque_chose(self) -> None:
        bain = Wash()
        for index in range(0, GRID_COLS * GRID_ROWS, 2):
            u, v = bain.cell_center(index)
            bain.scrub(u, v)
        bain.abandon()
        credit = bain.credit()
        self.assertGreater(credit, 0.2)
        self.assertLess(credit, 1.0)

    def test_l_abandon_termine_et_fait_partir_la_mousse(self) -> None:
        bain = Wash()
        bain.scrub(0.5, 0.5)
        bain.abandon()
        self.assertTrue(bain.done)
        for _ in range(120):
            bain.step(DT)
        self.assertFalse(bain.foam, "de la mousse survit à la fin du bain")

    def test_le_rincage_seul_ne_vaut_pas_le_bain_entier(self) -> None:
        """L'éponge est le geste long : elle doit peser le plus."""
        bain = Wash()
        _frotter_partout(bain)
        _laisser_partir_la_mousse(bain)
        bain.aim(0.5, 0.5, SPRAY_ARM + SPRAY_INTERVAL)
        partiel = Wash()
        partiel.scrub(*partiel.cell_center(0))
        self.assertGreater(bain.credit(), partiel.credit())


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# La couture : le modèle branché sur des outils réels
# ---------------------------------------------------------------------------
#
# C'est la moitié qui casse. Le modèle se vérifie à `dt` synthétique et ne peut
# guère mentir ; la couture, elle, convertit des pixels physiques en
# coordonnées normalisées, échange une éponge contre un spray et décide quand
# payer — trois endroits où une erreur ne se voit qu'à l'usage.


class _FauxHorloge:
    def __init__(self) -> None:
        self.reveils = 0

    def poke(self) -> None:
        self.reveils += 1


class _FauxLoco:
    def __init__(self) -> None:
        self.arrets = 0

    def stop(self) -> None:
        self.arrets += 1


class _FauxMoniteur:
    work = (0, 0, 1920, 1080)


class _FauxSession:
    def __init__(self) -> None:
        self.appliques: list[tuple[str, float]] = []
        self.rendus: list[str] = []

    def apply_consumable(self, key: str, factor: float = 1.0) -> dict:
        self.appliques.append((key, factor))
        return {"hygiene": 100.0 * factor}

    def refund_consumable(self, key: str) -> None:
        self.rendus.append(key)


class _FauxImpact:
    def __init__(self) -> None:
        self.sursauts = 0

    def poke(self) -> None:
        self.sursauts += 1


class _FauxPoussiere:
    def __init__(self) -> None:
        from pet.anim.particles import Particles
        self.banc = Particles()


class _FauxKit:
    """Ce que `_consume_item` passe au bain : un objet posé, à sa place."""

    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        self.consumable = "kit"


def _faire_fenetre(*bases):
    """Une fenêtre réduite à ce que le bain lit d'elle.

    Partagée par les deux classes de couture plutôt que recopiée : le montage
    est déjà le plus gros de ce fichier, et deux copies divergeraient au premier
    attribut ajouté. `bases` permet d'y mêler un autre mixin — `ItemsMixin` pour
    vérifier l'aiguillage du kit.
    """
    import random

    from pet.app.parts.wash import WashMixin

    pw, ph = WashSeamTest.PW, WashSeamTest.PH
    depart = WashSeamTest.PET

    class _Fenetre(*bases, WashMixin):
        def __init__(self) -> None:
            self._x, self._y = depart
            self.wash = None
            self.wash_tool = None
            self.wash_article = ""
            self._wash_idle = 0.0
            self._wash_outro = 0.0
            self._alpha = None
            self.diag = False
            self.item = None
            self.clock = _FauxHorloge()
            self.locomotion = _FauxLoco()
            self.session = _FauxSession()
            self._impact = _FauxImpact()
            self._poussiere = _FauxPoussiere()
            self.fetes: list[str] = []

            class _Picker:
                _rng = random.Random(7)

            self._picker = _Picker()

        def _pet_rect(self):
            return (self._x, self._y, pw, ph)

        def width(self):
            return pw

        def current_monitor(self):
            return _FauxMoniteur()

        def _ensure_dust(self):
            return self._poussiere

        def _celebrate_care(self, cle, applied):
            self.fetes.append(cle)

    return _Fenetre()


class WashSeamTest(unittest.TestCase):
    """Le bain entier, joué à la main sur une vraie éponge."""

    PW, PH = 200, 260
    PET = (500.0, 400.0)

    @classmethod
    def setUpClass(cls) -> None:
        from .qt_app import ensure_app
        ensure_app()

    def _fenetre(self):
        w = _faire_fenetre()
        self.addCleanup(w._close_tool)
        return w

    def _tenir(self, w, u: float, v: float) -> None:
        """Place l'outil pour que son **centre** tombe en (u, v) sur le robot."""
        outil = w.wash_tool
        outil.held = True
        outil.state = "held"
        moitie = outil.side / 2.0
        outil.x = w._x + u * self.PW - moitie
        outil.y = w._y + v * self.PH - moitie

    def _frotter_tout(self, w) -> None:
        for index in range(GRID_COLS * GRID_ROWS):
            u, v = w.wash.cell_center(index)
            self._tenir(w, u, v)
            w._step_wash(DT)

    def test_le_kit_sort_l_eponge_et_gele_le_robot(self) -> None:
        w = self._fenetre()
        w._start_wash(_FauxKit(600.0, 700.0))
        self.assertTrue(w.washing)
        self.assertIsNotNone(w.wash_tool)
        self.assertEqual(w.wash_tool.sprite.name, "clean_sponge.png",
                         "le bain ne commence pas par l'éponge")
        self.assertEqual(w.locomotion.arrets, 1,
                         "le robot n'est pas arrêté à l'arrivée")

    def test_l_outil_sort_la_ou_le_kit_etait(self) -> None:
        """Sinon l'éponge apparaît ailleurs que l'objet qu'on vient de rejoindre."""
        w = self._fenetre()
        w._start_wash(_FauxKit(613.0, 702.0))
        self.assertEqual((w.wash_tool.x, w.wash_tool.y), (613.0, 702.0))

    def test_frotter_couvre_puis_l_outil_devient_le_spray(self) -> None:
        w = self._fenetre()
        w._start_wash(_FauxKit(600.0, 700.0))
        self._frotter_tout(w)
        self.assertTrue(w.wash.scrubbed, "le passage complet ne couvre pas tout")

        avant = w.wash_tool
        for _ in range(120):
            w._step_wash(DT)
            if w.wash.state == SPRAY:
                break
        self.assertEqual(w.wash.state, SPRAY)
        self.assertIsNot(w.wash_tool, avant, "l'éponge n'a pas été échangée")
        self.assertEqual(w.wash_tool.sprite.name, "clean_spray.png")
        self.assertEqual((w.wash_tool.x, w.wash_tool.y), (avant.x, avant.y),
                         "le spray n'apparaît pas où l'éponge était")

    def test_le_bain_complet_paie_le_soin_et_range_les_outils(self) -> None:
        w = self._fenetre()
        w._start_wash(_FauxKit(600.0, 700.0))
        self._frotter_tout(w)
        for _ in range(120):
            w._step_wash(DT)
            if w.wash.state == SPRAY:
                break

        for _ in range(int(20.0 / DT)):
            self._tenir(w, 0.5, 0.5)
            w._step_wash(DT)
            if not w.washing:
                break

        self.assertFalse(w.washing, "le bain ne se termine pas")
        self.assertIsNone(w.wash_tool, "un outil traîne encore sur le bureau")
        self.assertEqual(w.session.appliques, [("kit", 1.0)])
        self.assertEqual(w.fetes, ["kit"])
        self.assertGreater(w._impact.sursauts, 0, "aucun sursaut sous le jet")

    def test_un_kit_laisse_en_plan_rend_la_main_et_l_article(self) -> None:
        """Un rituel qui immobiliserait le robot pour toujours serait un bug
        déguisé en règle."""
        from pet.app.parts.wash import WASH_IDLE

        w = self._fenetre()
        w._start_wash(_FauxKit(600.0, 700.0))
        for _ in range(int((WASH_IDLE + 3.0) / DT)):
            w._step_wash(DT)
            if not w.washing:
                break
        self.assertFalse(w.washing)
        self.assertEqual(w.session.rendus, ["kit"],
                         "le kit n'est pas rendu alors que rien n'a été fait")
        self.assertEqual(w.session.appliques, [])

    def test_un_bain_interrompu_paie_ce_qui_a_ete_fait(self) -> None:
        w = self._fenetre()
        w._start_wash(_FauxKit(600.0, 700.0))
        for index in range(0, GRID_COLS * GRID_ROWS, 2):
            u, v = w.wash.cell_center(index)
            self._tenir(w, u, v)
            w._step_wash(DT)
        w._cancel_wash()

        self.assertFalse(w.washing)
        self.assertEqual(len(w.session.appliques), 1)
        cle, facteur = w.session.appliques[0]
        self.assertEqual(cle, "kit")
        self.assertGreater(facteur, 0.0)
        self.assertLess(facteur, 1.0)

    def test_l_outil_hors_du_robot_ne_frotte_rien(self) -> None:
        """La conversion pixels -> normalisées est le seul endroit où une
        erreur d'un facteur deux passerait inaperçue."""
        w = self._fenetre()
        w._start_wash(_FauxKit(600.0, 700.0))
        self._tenir(w, 4.0, 4.0)
        w._step_wash(DT)
        self.assertEqual(w.wash.progress, 0.0)

    def test_un_passage_au_pied_couvre_le_pied(self) -> None:
        """La conversion pixels -> normalisées, vérifiée **là où elle ment**.

        Un facteur d'échelle pris sur la mauvaise dimension — la largeur au lieu
        de la hauteur — décale d'autant plus qu'on s'éloigne du haut : en haut du
        robot l'erreur est invisible, en bas elle sort du corps. Frotter au
        centre ne l'aurait donc pas vue, et un passage complet non plus, les
        cases voisines se rattrapant les unes les autres.
        """
        w = self._fenetre()
        w._start_wash(_FauxKit(600.0, 700.0))
        self._tenir(w, 0.5, 0.94)
        w._step_wash(DT)

        self.assertGreater(w.wash.progress, 0.0,
                           "un passage sur le robot ne couvre rien")
        bas = [i for i in w.wash._covered
               if w.wash.cell_center(i)[1] > 0.75]
        self.assertTrue(bas, "le passage au pied n'a pas couvert le pied")
        haut = [i for i in w.wash._covered
                if w.wash.cell_center(i)[1] < 0.3]
        self.assertFalse(haut, "un passage au pied a couvert la tête")


class KitRoutingTest(unittest.TestCase):
    """Le kit **n'agit pas au contact** : il ouvre le rituel.

    C'est le seul endroit du lot où une erreur rendrait le bain invisible sans
    rien casser : l'hygiène remonterait à l'arrivée du robot, comme avant, et le
    kit ne sortirait jamais son éponge. Le symptôme serait « rien ne se passe »,
    le plus difficile à diagnostiquer.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from .qt_app import ensure_app
        ensure_app()

    def _fenetre(self):
        from pet.app.parts.items import ItemsMixin

        w = _faire_fenetre(ItemsMixin)
        self.addCleanup(w._close_tool)
        return w

    def _objet(self, cle: str):
        from pet.ui.item import ItemWindow
        item = ItemWindow("clean", None, 60, consumable=cle)
        self.addCleanup(item.close)
        item.place(600.0, 700.0)
        return item

    def test_le_kit_ouvre_le_bain_au_lieu_de_soigner(self) -> None:
        w = self._fenetre()
        w._consume_item(self._objet("kit"))
        self.assertTrue(w.washing, "le kit n'a pas ouvert le bain")
        self.assertEqual(w.session.appliques, [],
                         "l'hygiène est montée sans qu'on ait lavé quoi que ce soit")

    def test_un_repas_agit_toujours_au_contact(self) -> None:
        """Le détour ne doit pas contaminer les articles ordinaires."""
        w = self._fenetre()
        w._consume_item(self._objet("meal"))
        self.assertFalse(w.washing)
        self.assertEqual(w.session.appliques, [("meal", 1.0)])
