"""Critères d'acceptation du choix de châssis, lot L21 (CDC §7, §13).

Cet écran a une particularité dans tout le produit : **il prend une décision
qu'on ne peut pas défaire**. Le châssis entre dans le génome, que la boutique ne
touche jamais ; il n'y a ni annulation, ni réglage, ni rachat. Les tests portent
donc d'abord sur ce qui protège l'utilisateur de lui-même — un clic ne choisit
pas, une fenêtre fermée ne décide pas à sa place — et ensuite seulement sur ce
que l'écran affiche.

Les gestes sont joués en appelant directement les gestionnaires avec un
événement minimal. C'est la logique de cet écran qu'on vérifie, pas la
distribution d'événements de Qt, et un `QMouseEvent` complet n'apporterait ici
qu'un constructeur déprécié de plus.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PySide6.QtCore import QPointF, Qt

from pet.genome.schema import CHASSIS, defaults
from pet.ui import chassis_choice
from pet.ui.chassis_choice import ChassisChooser

from .qt_app import ensure_app


class _Clic:
    """Le strict nécessaire : les gestionnaires ne lisent que la position."""

    def __init__(self, x: float, y: float) -> None:
        self._p = QPointF(x, y)

    def position(self) -> QPointF:
        return self._p


class _Touche:
    def __init__(self, touche) -> None:
        self._k = touche

    def key(self):
        return self._k


class _Fermeture:
    def accept(self) -> None:
        pass


class LoreTest(unittest.TestCase):
    def test_chaque_chassis_a_son_libelle_et_sa_description(self) -> None:
        """Lié au schéma : ajouter un châssis sans texte fait échouer la suite
        au lieu de livrer un carton muet."""
        for chassis in CHASSIS:
            self.assertIn(chassis, chassis_choice.LIBELLES)
            texte = chassis_choice.DESCRIPTIONS.get(chassis, "")
            self.assertGreater(len(texte), 80, "%s : description trop courte" % chassis)

    def test_le_lore_nomme_la_maison(self) -> None:
        joint = " ".join(chassis_choice.DESCRIPTIONS.values())
        self.assertIn("Desky Inc.", joint)


class ChoixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def _ecran(self):
        ecran = ChassisChooser()
        self.addCleanup(ecran.close)
        self.recus = []
        ecran.chosen.connect(lambda c: self.recus.append(("chosen", c)))
        ecran.dismissed.connect(lambda: self.recus.append(("dismissed", "")))
        return ecran

    def _centre(self, ecran, index: int) -> tuple[float, float]:
        rect = ecran._card_rect(index)
        return rect.center().x(), rect.center().y()

    def test_un_clic_ne_choisit_pas(self) -> None:
        """**La promesse de cet écran.** Le premier clic ouvre la confirmation
        et rien d'autre : un choix définitif pris par inadvertance sur une
        fenêtre qu'on découvre serait un piège."""
        ecran = self._ecran()
        ecran.mousePressEvent(_Clic(*self._centre(ecran, 0)))
        self.assertEqual(self.recus, [], "le clic a choisi tout seul")
        self.assertEqual(ecran._confirme, ecran.familles[0])

    def test_confirmer_choisit(self) -> None:
        ecran = self._ecran()
        ecran.mousePressEvent(_Clic(*self._centre(ecran, 1)))
        oui, _ = ecran._boutons_confirmation()
        ecran.mousePressEvent(_Clic(oui.center().x(), oui.center().y()))
        self.assertEqual(self.recus, [("chosen", ecran.familles[1])])

    def test_revenir_annule_sans_rien_choisir(self) -> None:
        ecran = self._ecran()
        ecran.mousePressEvent(_Clic(*self._centre(ecran, 0)))
        _, non = ecran._boutons_confirmation()
        ecran.mousePressEvent(_Clic(non.center().x(), non.center().y()))
        self.assertEqual(self.recus, [])
        self.assertEqual(ecran._confirme, "")

    def test_cliquer_a_cote_de_la_modale_annule(self) -> None:
        ecran = self._ecran()
        ecran.mousePressEvent(_Clic(*self._centre(ecran, 0)))
        ecran.mousePressEvent(_Clic(6.0, 6.0))
        self.assertEqual(self.recus, [])
        self.assertEqual(ecran._confirme, "")

    def test_echap_referme_la_modale_avant_de_quitter(self) -> None:
        """Deux échappements pour sortir : le premier annule la confirmation,
        le second seulement quitte l'écran."""
        ecran = self._ecran()
        ecran.mousePressEvent(_Clic(*self._centre(ecran, 0)))
        ecran.keyPressEvent(_Touche(Qt.Key.Key_Escape))
        self.assertEqual(self.recus, [])
        ecran.keyPressEvent(_Touche(Qt.Key.Key_Escape))
        self.assertEqual(self.recus, [("dismissed", "")])

    def test_fermer_sans_choisir_laisse_le_tirage_decider(self) -> None:
        """Rien ne doit se bloquer sur une fenêtre qu'on a fermée."""
        ecran = self._ecran()
        ecran.closeEvent(_Fermeture())
        self.assertEqual(self.recus, [("dismissed", "")])

    def test_l_ecran_ne_se_prononce_qu_une_fois(self) -> None:
        """Deux signaux pour un seul robot donneraient deux châssis, et le
        second écraserait le premier après que le carton est tombé."""
        ecran = self._ecran()
        ecran.mousePressEvent(_Clic(*self._centre(ecran, 0)))
        oui, _ = ecran._boutons_confirmation()
        ecran.mousePressEvent(_Clic(oui.center().x(), oui.center().y()))
        ecran.closeEvent(_Fermeture())
        ecran.keyPressEvent(_Touche(Qt.Key.Key_Escape))
        self.assertEqual(len(self.recus), 1, self.recus)

    def test_un_carton_par_chassis(self) -> None:
        ecran = self._ecran()
        self.assertEqual(ecran.familles, list(CHASSIS))
        rects = [ecran._card_rect(i) for i in range(len(CHASSIS))]
        for gauche, droite in zip(rects, rects[1:]):
            self.assertLess(gauche.right(), droite.left(), "cartons superposés")
        for rect in rects:
            self.assertGreaterEqual(rect.left(), 0.0)
            self.assertLessEqual(rect.right(), chassis_choice.WIDTH)

    def test_l_infobulle_ne_recouvre_pas_les_cartons(self) -> None:
        """Le défaut qu'on ne voit qu'en la regardant : texte et vignettes
        empilés au même endroit, illisibles."""
        ecran = self._ecran()
        boite = ecran._boite_infobulle()
        self.assertGreater(boite.top(), ecran._card_rect(0).bottom())
        self.assertLess(boite.bottom(), chassis_choice.HEIGHT)
        self.assertGreater(boite.height(), chassis_choice.VIGNETTE_H + 60,
                           "pas la place d'empiler le texte et le ruban")


class ApplicationTest(unittest.TestCase):
    """Ce que le choix fait au génome.

    **Le dossier de données est dérouté vers un temporaire**, et ce n'est pas
    une politesse : `apply_chassis` écrit le génome sur disque, comme il le doit.
    Sans ce déroutement, lancer la suite écrase le robot de la personne qui la
    lance — constaté une fois pendant l'écriture de ce lot, et il a fallu
    reconstituer le génome depuis la graine trouvée dans le journal.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self._dir.name

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old
        self._dir.cleanup()

    class _Fenetre:
        def __init__(self, genome: dict) -> None:
            self.genome = dict(genome)
            self.reconstruit = 0

        def _rebuild_robot(self) -> None:
            self.reconstruit += 1

    def _fenetre(self, chassis: str = "capsule"):
        from pet.app.parts.onboarding import OnboardingMixin

        genome = defaults()
        genome["chassis"] = chassis
        genome["ear.type"] = "antenna"

        class _Test(OnboardingMixin, ApplicationTest._Fenetre):
            pass

        return _Test(genome)

    def test_le_chassis_entre_dans_le_genome(self) -> None:
        """Et non dans `appearance` : c'est ce qui rend « définitif » vrai côté
        données, et pas seulement côté bouton."""
        fenetre = self._fenetre()
        self.assertTrue(fenetre.apply_chassis("monobloc"))
        self.assertEqual(fenetre.genome["chassis"], "monobloc")
        self.assertEqual(fenetre.reconstruit, 1)

    def test_le_monobloc_perd_ses_oreilles(self) -> None:
        """Même canonisation que le tirage : un monobloc n'en a pas."""
        fenetre = self._fenetre()
        fenetre.apply_chassis("monobloc")
        self.assertEqual(fenetre.genome["ear.type"], "none")

    def test_le_reste_du_genome_est_intact(self) -> None:
        """On choisit une silhouette, on ne commande pas un robot sur mesure."""
        fenetre = self._fenetre()
        avant = dict(fenetre.genome)
        fenetre.apply_chassis("monobloc")
        for cle, valeur in avant.items():
            if cle in ("chassis", "ear.type"):
                continue
            self.assertEqual(fenetre.genome[cle], valeur, cle)

    def test_choisir_le_chassis_deja_tire_ne_fait_rien(self) -> None:
        fenetre = self._fenetre("monobloc")
        self.assertFalse(fenetre.apply_chassis("monobloc"))
        self.assertEqual(fenetre.reconstruit, 0)

    def test_un_chassis_inconnu_est_refuse(self) -> None:
        fenetre = self._fenetre()
        self.assertFalse(fenetre.apply_chassis("trirème"))
        self.assertEqual(fenetre.genome["chassis"], "capsule")
        self.assertEqual(fenetre.reconstruit, 0)


if __name__ == "__main__":
    unittest.main()


class FicheTest(unittest.TestCase):
    """La fiche technique et le dessin industriel doivent dire la même chose."""

    def test_chaque_chassis_a_sa_fiche(self) -> None:
        for chassis in CHASSIS:
            lignes = chassis_choice.FICHES.get(chassis, ())
            self.assertGreaterEqual(len(lignes), 5, chassis)
            for cle, valeur in lignes:
                self.assertTrue(cle.strip(), chassis)
                self.assertTrue(str(valeur).strip(), "%s / %s" % (chassis, cle))

    def test_les_cotes_de_la_fiche_sont_celles_du_plan(self) -> None:
        """Un plan qui annonce 94 mm à côté d'une fiche qui en annonce 80 défait
        l'immersion en une seconde. Les deux viennent donc du même calcul, et
        c'est vérifié ici plutôt que laissé à la vigilance.
        """
        from pet.genome.generator import generate
        from pet.geometry import proportions
        from tools import make_chassis_art as art

        for chassis in CHASSIS:
            genome = generate(art.VEDETTES[chassis])
            genome["chassis"] = chassis
            if chassis == "monobloc":
                genome["ear.type"] = "none"
            dims = proportions.dimensions(genome)
            attendu = {
                "HAUTEUR": int(round(dims.total_height * art.MM_PAR_UNITE)),
                "LARGEUR": int(round(2.0 * max(dims.head_a, dims.body_a)
                                     * art.MM_PAR_UNITE)),
            }
            fiche = dict(chassis_choice.FICHES[chassis])
            for cle, valeur in attendu.items():
                self.assertEqual(fiche[cle], "%d mm" % valeur,
                                 "%s / %s" % (chassis, cle))

    def test_aucun_tiret_cadratin_dans_les_textes(self) -> None:
        """Demandé au lot L21 : le tiret cadratin coupe la lecture d'un écran
        qu'on découvre, et la ponctuation courante suffit."""
        textes = [chassis_choice.TITRE, chassis_choice.SOUS_TITRE,
                  chassis_choice.MENTION, chassis_choice.INVITE,
                  chassis_choice.CONFIRM_TITRE, chassis_choice.CONFIRM_CORPS,
                  chassis_choice.CONFIRM_OUI, chassis_choice.CONFIRM_NON]
        textes += list(chassis_choice.DESCRIPTIONS.values())
        textes += [c for lignes in chassis_choice.FICHES.values()
                   for paire in lignes for c in paire]
        for texte in textes:
            self.assertNotIn("—", texte, texte[:50])
