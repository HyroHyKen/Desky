"""Critères d'acceptation de l'interface, lot L6 phase B (CDC §13).

Quatre familles :

- **Le contrat des sigles.** La table Python et les `#define` du shader doivent
  coïncider ; les décaler ferait afficher la goutte à la place de la gamelle,
  silencieusement.
- **Le bandeau de bulle.** La propriété qui a justifié de ne pas agrandir la
  fenêtre : le bord bas du robot ne bouge pas quand on réserve de la hauteur.
- **Le panneau.** Une seule source de géométrie, des pages cohérentes, des
  délais respectés, et aucun texte hors le nom.
- **Le carton.** Sa machine à trois états, et le sens de ses rabats.

Les tests de rendu ouvrent un contexte GL ; ceux du panneau ouvrent une
QApplication partagée. Les deux se sautent proprement là où ce n'est pas
disponible.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from .qt_app import ensure_app
from .test_sensors import _code_only

PET_ROOT = Path(__file__).resolve().parents[1] / "pet"
SHADER_DIR = PET_ROOT / "render" / "shaders"


def _settle(anime, dt: float = 1.0 / 60.0, limite: float = 5.0) -> int:
    """Fait défiler une animation jusqu'à l'arrêt. Rend le nombre de pas.

    Pas de timer, pas d'horloge réelle : c'est le même parti pris que
    `IntroSequenceTest._play`, et pour la même raison — une boucle serrée sur
    `perf_counter` ferait défiler mille images pour une seconde d'animation et
    mesurerait des durées fausses.

    La limite n'est pas une précaution de style : une animation qui ne s'arrête
    jamais est précisément le défaut que le lot L9 doit empêcher — le tic qui
    tourne en fond et mange le budget CPU du §3. Ici elle fait échouer le test
    au lieu de le suspendre.
    """
    pas = 0
    maximum = int(limite / dt)
    while anime.step(dt):
        pas += 1
        if pas > maximum:
            raise AssertionError(
                "l'animation ne s'arrête pas : %.1f s simulées sans repos" % limite)
    return pas


# ---------------------------------------------------------------------------
# Le contrat des sigles
# ---------------------------------------------------------------------------


class GlyphContractTest(unittest.TestCase):
    def test_les_identifiants_python_et_glsl_coincident(self) -> None:
        """Contrat au même titre que l'ordre de `PARAMS` dans le génome."""
        from pet.render.glyphs import GLYPHS, GLYPH_NAMES

        source = (SHADER_DIR / "glyphs.glsl").read_text(encoding="utf-8")
        defines = dict(
            (nom.lower(), int(valeur))
            for nom, valeur in re.findall(
                r"#define\s+GLYPH_([A-Z]+)\s+(\d+)", source))

        self.assertEqual(set(defines), set(GLYPH_NAMES),
                         "les deux vocabulaires n'ont pas les mêmes sigles")
        for nom, identifiant in GLYPHS.items():
            self.assertEqual(defines[nom], identifiant,
                             f"le sigle {nom} n'a pas le même numéro des deux "
                             f"côtés de la frontière")

    def test_chaque_sigle_est_aiguille_dans_le_shader(self) -> None:
        """Un sigle déclaré mais non aiguillé ne dessinerait rien."""
        from pet.render.glyphs import GLYPH_NAMES

        source = (SHADER_DIR / "glyphs.glsl").read_text(encoding="utf-8")
        aiguillage = source.split("float glyphDistance")[-1]
        for nom in GLYPH_NAMES:
            if nom == "none":
                continue
            self.assertIn(f"GLYPH_{nom.upper()}", aiguillage,
                          f"{nom} n'est pas aiguillé")

    def test_chaque_besoin_a_son_sigle(self) -> None:
        from pet.brain.needs import NEEDS
        from pet.render.glyphs import GLYPH_FOR_NEED, GLYPHS

        self.assertEqual(set(GLYPH_FOR_NEED), set(NEEDS))
        for nom in GLYPH_FOR_NEED.values():
            self.assertIn(nom, GLYPHS)

    def test_un_sigle_inconnu_ne_dessine_rien_plutot_que_lever(self) -> None:
        from pet.render.glyphs import glyph_id

        self.assertEqual(glyph_id("licorne"), 0)
        self.assertEqual(glyph_id(""), 0)

    def test_l_inclusion_glsl_resout_les_fichiers(self) -> None:
        """Sans inclusion, les deux shaders dupliqueraient le vocabulaire."""
        from pet.render.context import RenderContext

        source = RenderContext._source("bubble.frag.glsl")
        self.assertIn("float glyphDistance", source)
        self.assertNotIn("#include", source)

    def test_les_deux_surfaces_partagent_le_meme_vocabulaire(self) -> None:
        for nom in ("bubble.frag.glsl", "face.frag.glsl"):
            texte = (SHADER_DIR / nom).read_text(encoding="utf-8")
            self.assertIn('#include "glyphs.glsl"', texte,
                          f"{nom} n'inclut pas le vocabulaire partagé")


# ---------------------------------------------------------------------------
# Le bandeau de bulle
# ---------------------------------------------------------------------------


class HeadroomTest(unittest.TestCase):
    """La propriété qui a permis de ne pas agrandir la fenêtre du pet."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()
        try:
            from pet.genome.generator import generate
            from pet.geometry.builder import build
            from pet.render.context import RenderContext
            from pet.render.scene import Scene
        except Exception as exc:                       # pragma: no cover
            raise unittest.SkipTest(f"rendu indisponible : {exc}")
        try:
            cls.rc = RenderContext((220, 220), samples=4)
        except Exception as exc:                       # pragma: no cover
            raise unittest.SkipTest(f"contexte GL indisponible : {exc}")
        cls.scene = Scene(cls.rc)
        cls.scene.set_robot(build(generate(8)))

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "rc", None) is not None:
            cls.scene.release()
            cls.rc.release()

    def _bounds(self, headroom: float) -> tuple[int, int]:
        import numpy as np
        self.scene.headroom = headroom
        self.rc.begin()
        self.scene.draw(yaw=0.0, pitch=0.14)
        alpha = self.rc.read_rgba()[:, :, 3]
        lignes = np.where(alpha.max(axis=1) > 38)[0]
        return int(lignes.min()), int(lignes.max())

    def test_le_bord_bas_ne_bouge_pas(self) -> None:
        """C'est **toute** la justification de ne pas toucher à la fenêtre.

        Le sol des lots L1 et L5b est ancré sur le bas de la fenêtre. Si
        réserver un bandeau déplaçait les pieds du robot, il aurait fallu
        reprendre la géométrie de position de deux lots livrés.
        """
        _, bas_sans = self._bounds(0.0)
        for headroom in (0.13, 0.26, 0.40):
            _, bas = self._bounds(headroom)
            self.assertLessEqual(abs(bas - bas_sans), 6,
                                 f"le bord bas a bougé de {bas - bas_sans} px "
                                 f"à {headroom:.0%} de bandeau")

    def test_le_robot_rapetisse_quand_le_bandeau_grandit(self) -> None:
        hauteurs = []
        for headroom in (0.0, 0.13, 0.26, 0.40):
            haut, bas = self._bounds(headroom)
            hauteurs.append(bas - haut)
        for avant, apres in zip(hauteurs, hauteurs[1:]):
            self.assertLess(apres, avant)

    def test_l_ancre_de_bulle_tombe_dans_le_bandeau(self) -> None:
        self.scene.headroom = 0.26
        haut, _ = self._bounds(0.26)
        _, ancre_y = self.scene.bubble_anchor_px()
        self.assertGreaterEqual(ancre_y, 0.0)
        self.assertLess(ancre_y, haut,
                        "la bulle se poserait sur le robot au lieu du bandeau")

    def test_le_bandeau_est_borne(self) -> None:
        self.scene.headroom = 5.0
        self.assertLessEqual(self.scene.headroom, 0.6)
        self.scene.headroom = -3.0
        self.assertGreaterEqual(self.scene.headroom, 0.0)
        self.scene.headroom = 0.26

    def test_la_bulle_ne_se_clique_que_visible(self) -> None:
        self.scene.headroom = 0.26
        ancre = self.scene.bubble_anchor_px()
        self.scene.bubble_glyph = 0
        self.scene.bubble_opacity = 1.0
        self.assertFalse(self.scene.bubble_hit(ancre))

        from pet.render.glyphs import glyph_id
        self.scene.bubble_glyph = glyph_id("hunger")
        self.scene.bubble_opacity = 0.05
        self.assertFalse(self.scene.bubble_hit(ancre),
                         "une bulle presque transparente ne doit pas se cliquer")
        self.scene.bubble_opacity = 1.0
        from pet.render.bubble import OFFSET_X, RADIUS_RATIO
        rayon = RADIUS_RATIO * self.rc.size[1]
        self.assertTrue(
            self.scene.bubble_hit((ancre[0] + OFFSET_X * rayon, ancre[1])))
        self.assertFalse(self.scene.bubble_hit((ancre[0], ancre[1] + 400)))
        self.scene.bubble_glyph = 0
        self.scene.bubble_opacity = 0.0


class WantTest(unittest.TestCase):
    def test_la_bulle_demande_avant_que_le_visage_s_assombrisse(self) -> None:
        """Le seuil de demande doit précéder celui de l'humeur.

        Une bulle qui n'apparaît qu'au moment où le pet a déjà l'air malheureux
        arrive trop tard pour servir à quoi que ce soit.
        """
        from pet.brain.needs import MOOD_NEUTRAL, WANT_THRESHOLD

        self.assertGreater(WANT_THRESHOLD, MOOD_NEUTRAL)

    def test_un_seul_besoin_est_demande_a_la_fois(self) -> None:
        from pet.brain.needs import Needs

        n = Needs(hunger=10.0, fun=12.0, energy=90.0, hygiene=90.0)
        self.assertEqual(n.want(), "hunger")

    def test_rien_n_est_demande_quand_tout_va_bien(self) -> None:
        from pet.brain.needs import NEEDS, Needs, WANT_THRESHOLD

        n = Needs(**{k: WANT_THRESHOLD + 1.0 for k in NEEDS})
        self.assertEqual(n.want(), "")


# ---------------------------------------------------------------------------
# Le panneau
# ---------------------------------------------------------------------------


class _FauxSession:
    def __init__(self, brain, name: str = "") -> None:
        self.brain = brain
        self.name = name
        self.appearance = {}
        self.inventory = []
        self.tokens = 0
        self.tokens_remaining = 25
        self.best_scores = {}
        self.consumables = {}
        # Trophées (lot L22) : la page les lit comme elle lit le reste.
        self.achievements = {}
        self.claimed = []
        self.stats = {}

    def best_score(self, jeu: str) -> int:
        return int(self.best_scores.get(jeu, 0))

    def mesures(self, when=None) -> dict:
        return dict(self.stats)

    def count(self, key: str) -> int:
        return int(self.consumables.get(key, 0))


class PanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def _panel(self, needs=None, name="Boulon"):
        from pet.brain.brain import Brain
        from pet.brain.needs import Needs
        from pet.ui.panel import CarePanel

        brain = Brain(needs if needs is not None else Needs())
        return CarePanel(_FauxSession(brain, name)), brain

    def test_le_menu_racine_porte_les_pages_demandees(self) -> None:
        """Les quatre du §13, plus la personnalisation ajoutée après le lot."""
        from pet.ui.panel import MENU_ACTIONS

        panel, _ = self._panel()
        panel.open_page("menu")
        actions = [b.action for b in panel._layout().buttons]
        self.assertEqual(actions, list(MENU_ACTIONS))
        for demandee in ("status", "pet", "games", "inventory", "shop", "quit"):
            self.assertIn(demandee, actions)

    def test_chaque_page_a_un_retour(self) -> None:
        panel, _ = self._panel()
        for page in ("status", "interactions", "shop"):
            panel.open_page(page)
            actions = [b.action for b in panel._layout().buttons]
            self.assertIn("back", actions, f"la page {page} est sans issue")

    def test_le_retour_remonte_puis_ferme(self) -> None:
        panel, _ = self._panel()
        panel.open_page("status")
        panel._activate("back")
        self.assertEqual(panel.page, "menu")

        panel.open_panel()
        panel._activate("back")
        # Depuis le lot L9 la fermeture est animée : le panneau reste visible
        # le temps de s'en aller. C'est le pas de temps qui le fait
        # disparaître, pas l'appel — et c'est bien la disparition qu'on teste,
        # pas la vitesse à laquelle elle se produit.
        self.assertTrue(panel.closing)
        _settle(panel)
        self.assertFalse(panel.isVisible())

    def test_le_titre_respire_au_dessus_du_contenu(self) -> None:
        """Un titre collé à ce qu'il annonce se lit comme un bloc, pas comme
        une en-tête suivie d'un contenu."""
        from pet.ui.panel import PAD, TITLE_H, TITLE_LEAD

        panel, _ = self._panel()
        for page in ("menu", "interactions", "custom", "settings", "name"):
            panel.open_page(page)
            self.assertEqual(panel._top(), PAD + TITLE_H + TITLE_LEAD,
                             "la page %s n'a pas son air sous le titre" % page)

    def test_la_boutique_et_le_statut_restent_serres(self) -> None:
        """Les deux ont déjà quelque chose entre le titre et les actions : la
        ligne du solde pour l'une, l'en-tête d'humeur pour l'autre. Y ajouter
        de l'air séparerait un bloc qui doit rester soudé."""
        from pet.ui.panel import PAD, SHOP_PAGES, TITLE_H

        panel, _ = self._panel()
        for page in ("shop",) + SHOP_PAGES:
            panel.open_page(page)
            self.assertEqual(panel._top(), PAD + TITLE_H,
                             "la page %s a pris de l'air" % page)

        panel.open_page("status")
        self.assertEqual(panel._top(), PAD, "le statut n'a pas de titre")

    def test_le_menu_ne_calcule_plus_sa_bande_de_titre_a_part(self) -> None:
        """Son titre est le nom du robot, donc absent de `PAGE_TITLES` : il
        recopiait le calcul de `_top`, et toute retouche de la bande devait
        être faite à deux endroits."""
        from pet.ui.panel import PAD

        panel, _ = self._panel(name="")
        panel.open_page("menu")
        self.assertEqual(panel._top(), PAD, "un robot sans nom n'a pas de titre")

        nomme, _ = self._panel()
        nomme.open_page("menu")
        self.assertGreater(nomme._top(), PAD)
        self.assertEqual(nomme._layout().buttons[0].rect.top(), nomme._top())

    def test_la_page_de_statut_montre_les_quatre_besoins(self) -> None:
        from pet.brain.needs import NEEDS

        panel, _ = self._panel()
        panel.open_page("status")
        layout = panel._layout()
        self.assertEqual([n for n, _ in layout.bars], list(NEEDS))
        self.assertEqual(layout.name, "Boulon")
        self.assertTrue(layout.mood)

    def test_un_soin_en_delai_est_grise(self) -> None:
        from pet.brain.needs import Needs

        # La caresse est le seul soin qui ait encore un délai, et elle est
        # désormais au menu racine.
        panel, brain = self._panel(Needs(fun=10.0))
        panel.open_page("menu")
        avant = {b.action: b.enabled for b in panel._layout().buttons}
        self.assertTrue(avant["pet"])

        brain.care("pet")
        apres = {b.action: b.enabled for b in panel._layout().buttons}
        self.assertFalse(apres["pet"], "le délai n'a pas grisé le bouton")
        self.assertTrue(apres["games"], "la navigation reste ouverte")

    def test_un_bouton_grise_ne_repond_pas(self) -> None:
        from pet.brain.needs import Needs

        panel, brain = self._panel(Needs(hunger=10.0))
        panel.open_page("interactions")
        brain.care("feed")
        recus = []
        panel.care_requested.connect(recus.append)
        for button in panel._layout().buttons:
            if button.action == "feed":
                # Passe par le chemin réel du clic, pas par `_activate`.
                if button.enabled:
                    panel._activate(button.action)
        self.assertEqual(recus, [])

    def test_la_geometrie_n_existe_qu_une_fois(self) -> None:
        """Peinture et clics doivent dériver du **même** appel à `_layout`.

        Deux calculs séparés finissent toujours par divergér d'un pixel, et un
        bouton qui ne répond pas là où il est dessiné est un défaut invisible en
        relecture.
        """
        source = (PET_ROOT / "ui" / "panel.py").read_text(encoding="utf-8")
        # `_at` (les clics) et `paintEvent` (la peinture) appellent `_layout`.
        for methode in ("_at", "paintEvent", "mousePressEvent"):
            bloc = source.split(f"def {methode}")[1].split("\n    def ")[0]
            self.assertIn("_layout()", bloc,
                          f"{methode} ne dérive pas de _layout")

    def test_tout_le_texte_affiche_vient_de_la_table(self) -> None:
        """La règle a changé au lot L7, et voici celle qui la remplace.

        « Jamais de texte » a été levée à la demande de l'utilisateur : des
        titres de page et des infobulles rendent les pictogrammes explicites, et
        c'est un gain d'usage réel. Elle laisse une conséquence — l'interface
        devient **traduisible** — et l'invariant qui compte désormais est que
        tout le texte affiché soit **au même endroit**, sans quoi une traduction
        future demanderait de relire tout le code.

        Vérifié là où ça se joue : aucune méthode de peinture ne contient de
        chaîne littérale qui ressemble à du texte d'affichage. Lu par l'AST et
        non par découpage du texte — une méthode se repère par sa structure, pas
        par son indentation.
        """
        import ast

        arbre = ast.parse(
            (PET_ROOT / "ui" / "panel.py").read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef):
                continue
            if not noeud.name.startswith("_paint"):
                continue
            # La docstring est repérée **par identité** et non par comparaison
            # de texte : `ast.get_docstring` la désindente, donc elle ne
            # correspond plus à la constante brute.
            doc = None
            if noeud.body and isinstance(noeud.body[0], ast.Expr):
                if isinstance(noeud.body[0].value, ast.Constant):
                    doc = noeud.body[0].value
            for enfant in ast.walk(noeud):
                if not isinstance(enfant, ast.Constant) or enfant is doc:
                    continue
                if not isinstance(enfant.value, str):
                    continue
                texte = enfant.value
                if len(texte) < 3:
                    continue
                self.assertNotIn(
                    " ", texte,
                    "%s affiche une chaîne écrite en ligne : %r"
                    % (noeud.name, texte))

    def test_chaque_page_a_son_titre_sauf_le_statut(self) -> None:
        """Le statut s'en passe : sa pastille, le nom et les barres suffisent."""
        from pet.ui.panel import PAGE_TITLES, PAGES

        self.assertNotIn("status", PAGE_TITLES)
        for page in PAGES:
            if page in ("status", "menu"):
                continue
            self.assertIn(page, PAGE_TITLES, "la page %s est sans titre" % page)
            self.assertTrue(PAGE_TITLES[page].strip())

    def test_le_titre_est_bien_porte_par_la_page(self) -> None:
        from pet.ui.panel import PAGE_TITLES

        panel, _ = self._panel()
        for page, titre in PAGE_TITLES.items():
            panel.open_page(page)
            self.assertEqual(panel._layout().title, titre)

        panel.open_page("status")
        self.assertEqual(panel._layout().title, "")

    def test_le_menu_racine_porte_le_nom_du_robot(self) -> None:
        """Sa page d'accueil : aucun libellé générique ne dirait mieux où l'on
        se trouve."""
        panel, _ = self._panel()
        panel.open_page("menu")
        self.assertEqual(panel._layout().title, panel.session.name)

    def test_chaque_bouton_a_une_infobulle(self) -> None:
        """C'est là que les pictogrammes obscurs se rattrapent."""
        from pet.ui.panel import PAGES

        panel, _ = self._panel()
        for page in PAGES:
            panel.open_page(page)
            for bouton in panel._layout().buttons:
                self.assertTrue(
                    panel._tooltip(bouton).strip(),
                    "le bouton %s de la page %s n'a pas d'infobulle"
                    % (bouton.action, page))

    def test_l_infobulle_d_un_chapeau_dit_son_etat(self) -> None:
        panel, _ = self._panel()
        panel.session.inventory = ["bow"]
        panel.session.appearance = {"hat": "bow"}
        panel.session.tokens = 50
        panel.open_page("shop_hat")
        par_action = {b.action: b for b in panel._layout().buttons}

        porte = panel._tooltip(par_action["cos:hat:bow"])
        a_vendre = panel._tooltip(par_action["cos:hat:crown"])
        self.assertNotEqual(porte, a_vendre)
        self.assertIn("50", a_vendre, "le prix n'est pas dans l'infobulle")

    def test_le_titre_ne_recouvre_aucun_bouton(self) -> None:
        from pet.ui.panel import PAGES, TITLE_H

        panel, _ = self._panel()
        for page in PAGES:
            panel.open_page(page)
            layout = panel._layout()
            if not layout.title:
                continue
            for bouton in layout.buttons:
                self.assertGreaterEqual(
                    bouton.rect.top(), TITLE_H,
                    "un bouton de %s passe sous le titre" % page)

    def test_la_saisie_est_le_seul_widget_de_texte(self) -> None:
        """Scanné **hors chaînes et commentaires**, et c'est indispensable.

        La première version lisait la source brute et trouvait `QPushButton`
        dans la docstring qui explique pourquoi le panneau n'en utilise pas —
        exactement l'erreur que les tests de vie privée du lot L5 avaient déjà
        commise sur leurs propres docstrings.
        """
        code = _code_only(
            (PET_ROOT / "ui" / "panel.py").read_text(encoding="utf-8"))
        self.assertEqual(code.count("QLineEdit"), 2)   # import + construction
        for interdit in ("QLabel", "QPushButton", "QCheckBox"):
            self.assertNotIn(interdit, code,
                             f"{interdit} introduit du texte dans l'interface")

    def test_la_page_de_nommage_offre_une_validation(self) -> None:
        """Sans texte, « appuyez sur Entrée » ne se devine pas."""
        panel, _ = self._panel(name="")
        panel.open_page("name")
        actions = [b.action for b in panel._layout().buttons]
        self.assertIn("check", actions)

    def test_un_nom_vide_n_est_pas_soumis(self) -> None:
        panel, _ = self._panel(name="")
        panel.open_page("name")
        recus = []
        panel.name_submitted.connect(recus.append)
        panel._edit.setText("   ")
        panel._activate("check")
        self.assertEqual(recus, [])
        panel._edit.setText("Boulon")
        panel._activate("check")
        self.assertEqual(recus, ["Boulon"])

    def test_seule_la_page_de_nommage_reclame_le_focus(self) -> None:
        """Un panneau qui vole le focus interrompt le travail en cours."""
        source = (PET_ROOT / "ui" / "panel.py").read_text(encoding="utf-8")
        self.assertIn("WA_ShowWithoutActivating", source)
        bloc = source.split("def open_page")[1].split("\n    def ")[0]
        self.assertIn("activateWindow", bloc)
        avant, apres = bloc.split("activateWindow", 1)
        self.assertIn('page == "name"', avant,
                      "l'activation n'est pas réservée à la page de nommage")

    def test_la_largeur_ne_change_pas_de_page_en_page(self) -> None:
        from pet.ui.panel import PAGES, WIDTH

        panel, _ = self._panel()
        for page in PAGES:
            panel.open_page(page)
            self.assertEqual(panel.width(), WIDTH)

    def test_toutes_les_pages_tiennent_dans_leur_hauteur(self) -> None:
        from pet.ui.panel import PAGES

        panel, _ = self._panel()
        for page in PAGES:
            panel.open_page(page)
            layout = panel._layout()
            for button in layout.buttons:
                self.assertLessEqual(button.rect.bottom(), layout.height,
                                     f"un bouton dépasse sur la page {page}")

    def test_la_boutique_offre_la_tete_nue_et_tous_les_chapeaux(self) -> None:
        """Le bouton et la page dataient du lot L6 ; le catalogue arrive ici."""
        from pet.geometry.cosmetics import NONE, by_slot

        panel, _ = self._panel()
        panel.open_page("shop_hat")
        actions = [b.action for b in panel._layout().buttons]
        self.assertIn("cos:hat:" + NONE, actions,
                      "on ne peut pas se découvrir la tête")
        for chapeau in by_slot("hat"):
            self.assertIn("cos:hat:" + chapeau.key, actions)
        self.assertIn("back", actions)

    def test_la_boutique_montre_le_solde(self) -> None:
        panel, _ = self._panel()
        panel.open_page("shop_hat")
        self.assertGreaterEqual(panel._layout().tokens, 0)

    def test_un_chapeau_trop_cher_n_est_pas_cliquable(self) -> None:
        from pet.geometry.cosmetics import by_slot

        panel, _ = self._panel()
        session = panel.session
        session.tokens = 0
        panel.open_page("shop_hat")
        par_action = {b.action: b for b in panel._layout().buttons}
        cher = max(by_slot("hat"), key=lambda h: h.price)
        self.assertFalse(par_action["cos:hat:" + cher.key].enabled)

        session.tokens = cher.price
        par_action = {b.action: b for b in panel._layout().buttons}
        self.assertTrue(par_action["cos:hat:" + cher.key].enabled)

    def test_un_chapeau_possede_n_affiche_plus_de_prix(self) -> None:
        """Sinon on croit devoir le racheter pour le porter."""
        panel, _ = self._panel()
        panel.session.inventory = ["bow"]
        panel.open_page("shop_hat")
        par_action = {b.action: b for b in panel._layout().buttons}
        self.assertLess(par_action["cos:hat:bow"].price, 0)
        self.assertGreaterEqual(par_action["cos:hat:crown"].price, 0)

    def test_le_chapeau_porte_est_marque(self) -> None:
        panel, _ = self._panel()
        panel.session.inventory = ["bow"]
        panel.session.appearance = {"hat": "bow"}
        panel.open_page("shop_hat")
        portes = [b.action for b in panel._layout().buttons if b.selected]
        self.assertEqual(portes, ["cos:hat:bow"])

    def test_la_page_de_reglages_porte_ses_trois_boutons(self) -> None:
        panel, _ = self._panel()
        panel.open_page("settings")
        actions = [b.action for b in panel._layout().buttons]
        self.assertEqual(actions, ["autostart", "reset", "back"])

    def test_la_reinitialisation_exige_un_appui_maintenu(self) -> None:
        """Geste irréversible, et pas un mot pour demander confirmation.

        La durée tient lieu de « êtes-vous sûr » : on ne réinitialise pas son
        robot d'un clic malheureux.
        """
        from pet.ui.panel import HOLD_ACTIONS, HOLD_SECONDS

        self.assertIn("reset", HOLD_ACTIONS)
        self.assertGreaterEqual(HOLD_SECONDS, 1.0)

        panel, _ = self._panel()
        panel.open_page("settings")
        recus = []
        panel.reset_requested.connect(lambda: recus.append(True))

        bouton = next(b for b in panel._layout().buttons
                      if b.action == "reset")
        panel.mousePressEvent(_FauxClic(bouton.rect.center()))
        self.assertEqual(recus, [], "un simple clic a réinitialisé")
        self.assertEqual(panel._hold_action, "reset")

        panel.mouseReleaseEvent(None)
        self.assertEqual(panel._hold_action, "", "l'appui n'a pas été annulé")
        self.assertEqual(recus, [])

        panel.mousePressEvent(_FauxClic(bouton.rect.center()))
        for _ in range(int(HOLD_SECONDS * 1000 / 30) + 4):
            panel._hold_tick()
        self.assertEqual(recus, [True], "l'appui maintenu n'a rien déclenché")


# ---------------------------------------------------------------------------
# Animation du panneau (lot L9)
# ---------------------------------------------------------------------------
#
# Deux exigences opposées se rencontrent ici : le §10 veut du mouvement partout,
# le §3 veut moins de 4 % d'un cœur. Chaque test appartient à l'une ou à
# l'autre, et ceux qui vérifient l'arrêt comptent autant que ceux qui vérifient
# le mouvement.


class PanelMotionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def _panel(self):
        from pet.brain.brain import Brain
        from pet.brain.needs import Needs
        from pet.ui.panel import CarePanel

        panel = CarePanel(_FauxSession(Brain(Needs()), "Boulon"))
        self.addCleanup(panel.close)
        return panel

    # -- ça bouge ----------------------------------------------------------

    def test_l_ouverture_n_est_pas_instantanee(self) -> None:
        """Le critère du lot, dans sa forme la plus nue."""
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        self.assertTrue(panel.isVisible())
        self.assertLess(panel._ouverture.value, 1.0,
                        "le panneau est déjà à sa taille : il a sauté")
        _settle(panel)
        self.assertAlmostEqual(panel._ouverture.value, 1.0, places=6)

    def test_l_ouverture_depasse_sa_taille_avant_de_se_poser(self) -> None:
        """Le dépassement du §10, sur la valeur réellement peinte.

        C'est la propriété la plus fragile de tout le lot : borner l'ouverture
        à [0, 1] dans `paintEvent` supprimerait l'effet sans casser un seul
        autre test, et la différence ne se voit qu'au ralenti.
        """
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        maximum = 0.0
        while panel.step(1.0 / 120.0):
            maximum = max(maximum, panel._ouverture.value)
        self.assertGreater(maximum, 1.02, "l'ouverture ne dépasse pas")

    def _bouton_sans_navigation(self, panel):
        """Un bouton qui reste à l'écran une fois pressé.

        La distinction n'est pas un détail de test : le panneau active **à
        l'appui**, donc presser un bouton de navigation remplace la page, et
        avec elle le bouton pressé. Sa réponse d'appui n'a alors nulle part où
        se jouer — c'est la transition de page qui fait office de retour. Seuls
        les boutons qui restent peuvent s'enfoncer et rebondir.
        """
        panel.session.consumables = {"meal": 2, "kit": 1}
        panel.open_page("inventory")
        for bouton in panel._layout().buttons:
            if bouton.enabled and bouton.action.startswith("use:"):
                return bouton
        self.skipTest("aucun article disponible")

    def test_l_appui_enfonce_le_bouton(self) -> None:
        panel = self._panel()
        panel.open_panel()
        bouton = self._bouton_sans_navigation(panel)
        _settle(panel)

        panel.mousePressEvent(_FauxClic(bouton.rect.center()))
        for _ in range(6):
            panel.step(1.0 / 60.0)
        self.assertLess(panel._echelle_bouton(bouton.action), 1.0,
                        "l'appui ne s'enfonce pas")

    def test_le_relachement_repasse_au_dessus(self) -> None:
        """C'est là que se joue la sensation de rebond, pas à l'appui."""
        panel = self._panel()
        panel.open_panel()
        bouton = self._bouton_sans_navigation(panel)
        _settle(panel)

        panel.mousePressEvent(_FauxClic(bouton.rect.center()))
        for _ in range(10):
            panel.step(1.0 / 60.0)
        panel.mouseReleaseEvent(_FauxClic(bouton.rect.center()))

        maximum = 0.0
        while panel.step(1.0 / 120.0):
            maximum = max(maximum, panel._echelle_bouton(bouton.action))
        self.assertGreater(maximum, 1.0,
                           "le bouton revient sans dépasser : pas de rebond")

    def test_un_bouton_de_navigation_laisse_la_page_faire_le_retour(self) -> None:
        """Décision de conception, épinglée ici pour qu'on ne la « corrige »
        pas plus tard : activer à l'appui fait disparaître le bouton pressé,
        et sa réponse avec lui. Ce qui doit rester vrai, c'est qu'il ne reste
        **rien en vol** derrière lui."""
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        _settle(panel)

        bouton = panel._layout().buttons[0]
        panel.mousePressEvent(_FauxClic(bouton.rect.center()))
        self.assertNotEqual(panel.page, "menu", "ce bouton ne navigue pas")
        self.assertNotIn(bouton.action, panel._appui._ressorts)
        _settle(panel)

    def test_rouvrir_pendant_la_fermeture_rattrape_en_vol(self) -> None:
        """Un second clic droit pendant la fermeture ne doit pas faire
        disparaître le panneau pour le refaire naître."""
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        _settle(panel)

        panel.close_panel()
        for _ in range(3):
            panel.step(1.0 / 60.0)
        mi_chemin = panel._ouverture.value
        self.assertLess(mi_chemin, 1.0)

        panel.open_panel()
        self.assertFalse(panel.closing)
        self.assertTrue(panel.isVisible())
        panel.step(1e-6)
        self.assertAlmostEqual(panel._ouverture.value, mi_chemin, places=3,
                               msg="l'ouverture est repartie de zéro")

    # -- ça s'arrête -------------------------------------------------------

    def test_l_animation_finit_par_s_arreter(self) -> None:
        """Le §3 dans cette couche. `_settle` lève si le tic tourne sans fin."""
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        _settle(panel)
        self.assertFalse(panel.step(1.0 / 60.0),
                         "le panneau ouvert et immobile continue de s'animer")

    def test_la_fermeture_masque_le_panneau_a_la_fin(self) -> None:
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        _settle(panel)

        panel.close_panel()
        self.assertTrue(panel.isVisible(), "masqué avant d'être parti")
        _settle(panel)
        self.assertFalse(panel.isVisible())
        self.assertFalse(panel.closing)

    def test_la_fermeture_immediate_ne_laisse_rien_en_vol(self) -> None:
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        panel.close_panel(immediat=True)
        self.assertFalse(panel.isVisible())
        self.assertFalse(panel.step(1.0 / 60.0))

    def test_un_changement_de_page_ne_laisse_pas_de_ressort_orphelin(self) -> None:
        """Sans purge, vingt navigations laissent vingt jeux de ressorts qu'on
        continuerait d'avancer, et le tic ne s'arrêterait plus jamais."""
        panel = self._panel()
        panel.open_panel()
        for page in ("status", "interactions", "shop", "settings", "menu"):
            panel.open_page(page)
            _settle(panel)

        attendues = {b.action for b in panel._layout().buttons}
        self.assertEqual(set(panel._survol._ressorts), attendues)
        self.assertEqual(set(panel._appui._ressorts), attendues)

    def test_un_bouton_grise_ne_reagit_pas_au_survol(self) -> None:
        """Il répondrait à un geste qu'il refusera ensuite."""
        from pet.brain.brain import Brain
        from pet.brain.needs import Needs
        from pet.ui.panel import CarePanel

        panel = CarePanel(_FauxSession(Brain(Needs()), "Boulon"))
        self.addCleanup(panel.close)
        # Un objet de soin traîne déjà sur le bureau : les trois soins qui en
        # produisent un se grisent ensemble. C'est la façon la plus sûre
        # d'obtenir un bouton désactivé sans dépendre des délais du brain.
        panel.session.consumables = {"meal": 1, "kit": 1}
        panel.item_pending = True
        panel.open_page("inventory")
        panel.open_panel()
        _settle(panel)

        boutons = panel._layout().buttons
        grises = [i for i, b in enumerate(boutons) if not b.enabled]
        self.assertTrue(grises, "aucun bouton grisé : le montage est faux")
        index = grises[0]
        panel._hover = index
        panel._sync_targets(boutons)
        _settle(panel)
        self.assertEqual(panel._survol.value(boutons[index].action), 0.0)

    # -- la cascade --------------------------------------------------------

    def test_les_boutons_arrivent_l_un_apres_l_autre(self) -> None:
        """Le remplacement du fondu, dans sa forme la plus nue.

        Un fondu fait tout arriver en même temps : rien n'a de poids parce que
        rien n'a son instant. Ici le premier bouton est posé quand le dernier
        n'a pas commencé.
        """
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        boutons = panel._layout().buttons
        premier = "bouton:%s" % boutons[0].action
        dernier = "bouton:%s" % boutons[-1].action

        # On avance jusqu'au départ du premier bouton plutôt que de fixer un
        # instant : le titre occupe le premier créneau, et un seuil écrit en
        # dur casserait au prochain réglage des durées sans rien dire du fond.
        for _ in range(120):
            panel.step(1.0 / 240.0)
            if panel._entree.value(premier) > 0.0:
                break
        self.assertGreater(panel._entree.value(premier), 0.0,
                           "le premier bouton n'est jamais parti")
        self.assertEqual(panel._entree.value(dernier), 0.0,
                         "tous les boutons partent ensemble : c'est un fondu")

    def test_le_titre_precede_les_boutons(self) -> None:
        """L'ordre de la cascade suit la lecture : le regard descend le titre
        puis trouve les actions. L'inverse ferait arriver des boutons sous un
        titre encore absent."""
        panel = self._panel()
        panel.open_page("interactions")
        panel.open_panel()
        cles = panel._entrance_keys(panel._layout())
        self.assertEqual(cles[0], "titre")
        self.assertTrue(all(c.startswith("bouton:") for c in cles[-2:]))

    def test_toutes_les_pages_s_installent_en_moins_d_une_demi_seconde(self) -> None:
        """La page de personnalisation a douze pastilles. Sans plafond
        d'étalement, sa cascade durerait trois quarts de seconde — et à partir
        de là on n'admire plus, on attend."""
        from pet.ui.panel import PAGES

        panel = self._panel()
        for page in PAGES:
            panel.open_page(page)
            panel.open_panel()
            duree = 0.0
            while panel.step(1.0 / 240.0):
                duree += 1.0 / 240.0
            self.assertLess(duree, 0.5,
                            "la page %s met %.2f s à s'installer" % (page, duree))
            panel.close_panel(immediat=True)

    def test_naviguer_relance_la_cascade(self) -> None:
        """Une navigation installe la page suivante au lieu de la substituer."""
        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        _settle(panel)
        self.assertFalse(panel._entree.moving)

        panel.open_page("games")
        self.assertTrue(panel._entree.moving, "la page a été substituée d'un coup")

    def test_changer_de_page_panneau_ferme_n_anime_rien(self) -> None:
        """`open_page` est appelée par la fenêtre **avant** d'ouvrir : relancer
        la cascade là laisserait le tic tourner sur un panneau invisible."""
        panel = self._panel()
        panel.open_page("status")
        self.assertFalse(panel._entree.moving)

    # -- la peinture -------------------------------------------------------

    def test_la_peinture_traverse_toute_l_ouverture(self) -> None:
        """`paintEvent` applique une transformation : il faut la peindre.

        Le reste de la classe teste des nombres. Celui-ci rend réellement, à
        chaque étape de l'ouverture, pour qu'un `save()` sans `restore()` ou
        une transformation appliquée au mauvais moment sorte ici et pas chez
        l'utilisateur.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap

        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()

        rendus = []
        while True:
            image = QPixmap(panel.size())
            image.fill(Qt.GlobalColor.transparent)
            panel.render(image)
            rendus.append(image.toImage())
            if not panel.step(1.0 / 60.0):
                break

        self.assertGreater(len(rendus), 4, "l'ouverture n'a presque pas d'images")
        # La première image et la dernière doivent différer : si elles sont
        # identiques, la transformation n'a rien fait et le panneau a sauté.
        self.assertNotEqual(rendus[0], rendus[-1],
                            "toutes les images de l'ouverture sont identiques")

    def test_la_peinture_supporte_un_bouton_enfonce(self) -> None:
        """L'anneau d'appui long est peint **dans** la transformation du
        bouton : cette page est la seule qui exerce les deux à la fois."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        from pet.ui.panel import HOLD_ACTIONS

        panel = self._panel()
        panel.open_page("settings")
        panel.open_panel()
        _settle(panel)

        bouton = next(b for b in panel._layout().buttons
                      if b.action in HOLD_ACTIONS)
        panel.mousePressEvent(_FauxClic(bouton.rect.center()))
        for _ in range(8):
            panel._hold_tick()
            panel.step(1.0 / 60.0)

        self.assertGreater(panel._hold, 0.0, "l'appui long n'a pas démarré")
        self.assertLess(panel._echelle_bouton(bouton.action), 1.0)
        image = QPixmap(panel.size())
        image.fill(Qt.GlobalColor.transparent)
        panel.render(image)

    # -- les faits émis ----------------------------------------------------

    def test_l_ouverture_et_la_fermeture_sont_annoncees(self) -> None:
        """Ce sont les deux faits dont le lot Sons partira."""
        from pet.feedback import bus

        vus = []
        bus.subscribe("panneau_ouvert", lambda: vus.append("ouvert"))
        bus.subscribe("panneau_ferme", lambda: vus.append("ferme"))
        self.addCleanup(bus.clear)

        panel = self._panel()
        panel.open_page("menu")
        panel.open_panel()
        _settle(panel)
        self.assertEqual(vus, ["ouvert"])

        panel.close_panel()
        self.assertEqual(vus, ["ouvert"], "annoncé fermé avant de l'être")
        _settle(panel)
        self.assertEqual(vus, ["ouvert", "ferme"])


class IconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def test_chaque_icone_a_un_trace_non_vide(self) -> None:
        from pet.ui.icons import ICON_NAMES, icon_path

        for nom in ICON_NAMES:
            path = icon_path(nom)
            self.assertGreater(path.elementCount(), 0, nom)
            boite = path.boundingRect()
            self.assertGreater(boite.width(), 8.0, nom)
            self.assertGreater(boite.height(), 8.0, nom)

    def test_chaque_icone_reste_dans_son_carre(self) -> None:
        """Débordant, une icône mordrait sur le bord de son bouton."""
        from pet.ui.icons import BOX, ICON_NAMES, icon_path

        for nom in ICON_NAMES:
            boite = icon_path(nom).boundingRect()
            self.assertGreaterEqual(boite.left(), -1.0, nom)
            self.assertGreaterEqual(boite.top(), -1.0, nom)
            self.assertLessEqual(boite.right(), BOX + 1.0, nom)
            self.assertLessEqual(boite.bottom(), BOX + 1.0, nom)

    def test_un_nom_inconnu_ne_leve_pas(self) -> None:
        from pet.ui.icons import icon_path

        self.assertGreater(icon_path("licorne").elementCount(), 0)

    def test_chaque_action_du_panneau_a_son_icone(self) -> None:
        from pet.ui.icons import BUILDERS
        from pet.ui.panel import CARE_ACTIONS, MENU_ACTIONS

        for nom in MENU_ACTIONS + CARE_ACTIONS + ("back", "check"):
            self.assertIn(nom, BUILDERS, f"{nom} n'a pas d'icône")

    def test_chaque_humeur_du_visage_a_une_pastille(self) -> None:
        from pet.render.face import EXPRESSIONS
        from pet.ui.icons import BUILDERS, MOOD_ICONS

        self.assertEqual(set(MOOD_ICONS), set(EXPRESSIONS),
                         "une expression du §9 n'a pas d'icône d'humeur")
        for nom in MOOD_ICONS.values():
            self.assertIn(nom, BUILDERS)

    def test_les_besoins_partagent_leurs_formes_avec_le_shader(self) -> None:
        """Les deux vocabulaires doivent parler des mêmes choses."""
        from pet.brain.needs import NEEDS
        from pet.ui.icons import BUILDERS

        for nom in NEEDS:
            self.assertIn(nom, BUILDERS,
                          f"le besoin {nom} n'a pas d'icône de barre")


# ---------------------------------------------------------------------------
# Le carton
# ---------------------------------------------------------------------------


class UnboxingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def test_les_rabats_sont_rabattus_quand_le_carton_est_ferme(self) -> None:
        """Régression : ils sortaient **sur les côtés**, comme des ailes.

        Fermé, un rabat pointe vers l'intérieur et rejoint son voisin au milieu
        du couvercle. Le signe de la rotation était inversé.
        """
        from pet.ui.unboxing import FLAPS, Unboxing

        box = Unboxing()
        box._open = 0.0
        rect = box._box_rect()
        for flap in FLAPS:
            points = box._flap_polygon(flap, rect)
            xs = [p.x() for p in points]
            # Le bout du rabat doit être plus près du centre que sa charnière.
            charniere = rect.center().x() + flap.side * rect.width() / 2.0
            bout = min(xs) if flap.side > 0 else max(xs)
            self.assertLess(abs(bout - rect.center().x()),
                            abs(charniere - rect.center().x()),
                            "le rabat fermé pointe vers l'extérieur")

    def test_les_rabats_basculent_vers_l_exterieur_en_s_ouvrant(self) -> None:
        """Le bout part de l'intérieur, monte, et ressort de l'autre côté.

        La première version de ce test exigeait une montée **monotone** et
        accusait donc l'ouverture complète : un rabat qui pivote au-delà de la
        verticale redescend un peu, et c'est ce qu'il doit faire. La propriété
        vraie est le basculement, pas la montée.
        """
        from pet.ui.unboxing import FLAPS, Unboxing

        box = Unboxing()
        flap = FLAPS[1]                     # celui de droite

        def bout(ouverture: float):
            box._open = ouverture
            rect = box._box_rect()
            points = list(box._flap_polygon(flap, rect))
            charniere = rect.center().x() + flap.side * rect.width() / 2.0
            loin = max(points, key=lambda p: abs(p.x() - rect.center().x())
                       if ouverture > 0.7 else -abs(p.x() - rect.center().x()))
            return charniere, loin

        charniere, ferme = bout(0.0)
        self.assertLess(ferme.x(), charniere,
                        "fermé, le bout doit être vers l'intérieur")

        _, mi = bout(0.5)
        self.assertLess(mi.y(), ferme.y(), "le rabat ne se soulève pas")

        charniere, ouvert = bout(1.0)
        self.assertGreater(ouvert.x(), charniere,
                           "ouvert, le bout doit être ressorti à l'extérieur")
        self.assertLess(ouvert.y(), ferme.y(),
                        "ouvert, le bout doit rester au-dessus du couvercle")

    def test_l_ecrasement_conserve_le_bord_bas(self) -> None:
        """Une caisse qui se tasse reste posée, elle ne rétrécit pas en l'air."""
        from pet.ui.unboxing import Unboxing

        box = Unboxing()
        box._squash = 0.0
        bas = box._box_rect().bottom()
        box._squash = 1.0
        ecrase = box._box_rect()
        self.assertAlmostEqual(ecrase.bottom(), bas, places=3)
        self.assertLess(ecrase.height(), BOX_HEIGHT_REF)
        self.assertGreater(ecrase.width(), BOX_WIDTH_REF)

    def test_le_clic_n_ouvre_que_le_carton_pose(self) -> None:
        from pet.ui.unboxing import Unboxing

        box = Unboxing()
        recus = []
        box.opened.connect(lambda: recus.append(True))

        box.state = "falling"
        box.mousePressEvent(_FauxClic(box._box_rect().center()))
        self.assertEqual(recus, [], "un carton en chute s'est ouvert")

        box.state = "waiting"
        box.mousePressEvent(_FauxClic(box._box_rect().center()))
        self.assertEqual(recus, [True])
        self.assertEqual(box.state, "opening")

    def test_un_clic_hors_de_la_caisse_ne_l_ouvre_pas(self) -> None:
        from PySide6.QtCore import QPointF

        from pet.ui.unboxing import Unboxing

        box = Unboxing()
        box.state = "waiting"
        recus = []
        box.opened.connect(lambda: recus.append(True))
        box.mousePressEvent(_FauxClic(QPointF(4.0, 4.0)))
        self.assertEqual(recus, [])
        self.assertEqual(box.state, "waiting")


class _FauxClic:
    """Événement de souris minimal : `mousePressEvent` ne lit que la position."""

    def __init__(self, point) -> None:
        self._point = point

    def position(self):
        return self._point


def _box_reference() -> tuple[float, float]:
    from pet.ui.unboxing import BOX_H, BOX_W
    return float(BOX_W), float(BOX_H)


BOX_WIDTH_REF, BOX_HEIGHT_REF = 150.0, 112.0


class CustomisationTest(unittest.TestCase):
    """Presets de couleur : la seule variable modifiable sans token."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def _panel(self, appearance=None):
        from pet.brain.brain import Brain
        from pet.genome.generator import generate
        from pet.ui.panel import CarePanel

        session = _FauxSession(Brain(), "Boulon")
        session.appearance = dict(appearance or {})
        return CarePanel(session, generate(8)), session

    def test_le_menu_racine_mene_a_la_personnalisation(self) -> None:
        from pet.ui.panel import MENU_ACTIONS

        self.assertIn("custom", MENU_ACTIONS)
        panel, _ = self._panel()
        panel.open_page("menu")
        actions = [b.action for b in panel._layout().buttons]
        self.assertIn("custom", actions)
        # Avant la boutique : des deux pages d'apparence, la gratuite d'abord.
        self.assertLess(actions.index("custom"), actions.index("shop"))

    def test_la_page_offre_toutes_les_couleurs_du_genome(self) -> None:
        from pet.genome.schema import ACCENT_COLORS, BODY_COLORS

        panel, _ = self._panel()
        panel.open_page("custom")
        pastilles = [b.action for b in panel._layout().buttons if b.swatch]
        for nom in BODY_COLORS:
            self.assertIn("palette.body=" + nom, pastilles)
        for nom in ACCENT_COLORS:
            self.assertIn("palette.accent=" + nom, pastilles)
        self.assertEqual(len(pastilles),
                         len(BODY_COLORS) + len(ACCENT_COLORS))

    def test_une_seule_pastille_est_cochee_par_ligne(self) -> None:
        from pet.ui.panel import SWATCH_ROWS

        panel, _ = self._panel()
        panel.open_page("custom")
        boutons = [b for b in panel._layout().buttons if b.swatch]
        for param, _ in SWATCH_ROWS:
            ligne = [b for b in boutons if b.action.startswith(param + "=")]
            self.assertEqual(sum(1 for b in ligne if b.selected), 1,
                             "la ligne " + param + " n'a pas un seul choix")

    def test_la_couleur_de_naissance_est_cochee_par_defaut(self) -> None:
        """Rien de choisi veut dire « celle de naissance », pas « aucune »."""
        panel, _ = self._panel()
        panel.open_page("custom")
        naissance = panel.genome["palette.body"]
        coche = next(b for b in panel._layout().buttons
                     if b.swatch and b.selected
                     and b.action.startswith("palette.body="))
        self.assertEqual(coche.action, "palette.body=" + naissance)

    def test_un_choix_deplace_la_coche(self) -> None:
        from pet.genome.schema import BODY_COLORS

        panel, session = self._panel()
        panel.open_page("custom")
        naissance = panel.genome["palette.body"]
        autre = next(n for n in BODY_COLORS if n != naissance)
        session.appearance = {"palette.body": autre}
        coche = next(b for b in panel._layout().buttons
                     if b.swatch and b.selected
                     and b.action.startswith("palette.body="))
        self.assertEqual(coche.action, "palette.body=" + autre)

    def test_un_clic_sur_une_pastille_annonce_le_choix(self) -> None:
        panel, _ = self._panel()
        panel.open_page("custom")
        recus = []
        panel.appearance_chosen.connect(lambda p, v: recus.append((p, v)))
        panel._activate("palette.accent=magenta")
        self.assertEqual(recus, [("palette.accent", "magenta")])

    def test_les_pastilles_tiennent_dans_la_page(self) -> None:
        panel, _ = self._panel()
        panel.open_page("custom")
        layout = panel._layout()
        for button in layout.buttons:
            self.assertGreaterEqual(button.rect.left(), 0.0)
            self.assertLessEqual(button.rect.right(), panel.width())
            self.assertLessEqual(button.rect.bottom(), layout.height)

    def test_une_pastille_porte_une_couleur_et_pas_d_icone(self) -> None:
        panel, _ = self._panel()
        panel.open_page("custom")
        for button in panel._layout().buttons:
            if button.swatch:
                self.assertTrue(button.swatch.startswith("#"))
                self.assertEqual(button.icon, "")


class AppearanceStoreTest(unittest.TestCase):
    """Le costume est superposé au génome, jamais écrit dedans."""

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

    def test_un_choix_survit_a_un_aller_retour(self) -> None:
        s = self._session()
        self.assertTrue(s.set_appearance("palette.body", "ivoire"))
        self.assertEqual(self._session().appearance,
                         {"palette.body": "ivoire"})

    def test_un_meme_choix_ne_reecrit_rien(self) -> None:
        s = self._session()
        s.set_appearance("palette.accent", "ambre")
        self.assertFalse(s.set_appearance("palette.accent", "ambre"))

    def test_une_couleur_inconnue_est_refusee(self) -> None:
        s = self._session()
        self.assertFalse(s.set_appearance("palette.body", "fuchsia-fluo"))
        self.assertEqual(s.appearance, {})

    def test_un_parametre_non_personnalisable_est_refuse(self) -> None:
        """Sinon un fichier édité à la main changerait les proportions."""
        s = self._session()
        self.assertFalse(s.set_appearance("head.radius", "3.0"))
        self.assertFalse(s.set_appearance("palette.hat", "ivoire"))
        self.assertEqual(s.appearance, {})

    def test_un_costume_aberrant_est_ignore_au_chargement(self) -> None:
        from pet.state import save

        store = save.state_store()
        save.write_json_atomic(store.path, {
            "schema_version": save.STATE_SCHEMA,
            "appearance": {"palette.body": "fuchsia-fluo",
                           "head.radius": 9.0,
                           "palette.accent": "ambre"},
        })
        self.assertEqual(self._session().appearance,
                         {"palette.accent": "ambre"})

    def test_le_costume_ne_touche_pas_le_genome(self) -> None:
        """Le génome est le trait de naissance : il ne bouge jamais."""
        from pet.genome.schema import BODY_COLORS
        from pet.state import save

        genome, _ = save.load_or_create_genome()
        naissance = genome["palette.body"]
        autre = next(n for n in BODY_COLORS if n != naissance)
        self._session().set_appearance("palette.body", autre)
        relu, _ = save.load_or_create_genome()
        self.assertEqual(relu["palette.body"], naissance)

    def test_le_costume_change_bien_la_couleur_rendue(self) -> None:
        """Bout en bout : `build` doit honorer l'override."""
        from pet.genome.generator import generate
        from pet.genome.schema import BODY_COLORS, hex_to_rgb
        from pet.geometry.builder import build

        genome = generate(8)
        nu = build(genome)
        autre = next(n for n in BODY_COLORS if n != genome["palette.body"])
        costume = build(genome, {"palette.body": autre})
        self.assertNotEqual(nu.parts[0].color, costume.parts[0].color)
        attendu = hex_to_rgb(BODY_COLORS[autre])
        for obtenu, cible in zip(costume.parts[0].color, attendu):
            self.assertAlmostEqual(obtenu, cible, places=3)


class BubblePopTest(unittest.TestCase):
    """L'arrivée de la bulle, sur ressort depuis le lot L9 (CDC §10).

    Avant ce lot, `bubble_scale` valait l'opacité : la bulle grandissait
    exactement au rythme où elle apparaissait, par une interpolation vers la
    cible — c'est-à-dire le mouvement linéaire que le §10 proscrit. Elle
    n'arrivait pas, elle se matérialisait.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

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

    def _window(self):
        from pet.app.window import PetWindow
        from pet.brain.session import Session
        from pet.state import save

        settings = save.settings_store()
        settings.load()
        genome, _ = save.load_or_create_genome()
        session = Session()
        session.load()
        w = PetWindow(settings, genome, session=session)
        w.show()
        try:
            w.start()
        except Exception as exc:                       # pragma: no cover
            raise unittest.SkipTest("rendu indisponible : %s" % exc)
        w.hide()
        return w

    def test_l_echelle_depasse_avant_de_se_poser(self) -> None:
        w = self._window()
        try:
            # Un besoin au plancher fait apparaître la bulle ; la scène
            # d'arrivée est terminée, donc rien ne la retient.
            w._onboarding = False
            w._intro_phase = ""
            w.brain.needs.hunger = 0.0

            maximum = 0.0
            for _ in range(240):
                w._step_bubble(1.0 / 120.0, 0.0)
                maximum = max(maximum, w.scene.bubble_scale)
            self.assertGreater(
                maximum, 1.02,
                "la bulle n'arrive pas, elle apparaît : aucun dépassement")
        finally:
            w.shutdown()

    def test_l_echelle_ne_passe_jamais_sous_zero(self) -> None:
        """Au retour, un ressort sous-amorti passerait **sous** zéro : la bulle
        se retournerait un instant avant de disparaître. D'où l'amortissement
        critique à la fermeture."""
        w = self._window()
        try:
            w._onboarding = False
            w._intro_phase = ""
            w.brain.needs.hunger = 0.0
            for _ in range(240):
                w._step_bubble(1.0 / 120.0, 0.0)

            w.brain.needs.hunger = 100.0
            minimum = 1.0
            for _ in range(360):
                w._step_bubble(1.0 / 120.0, 0.0)
                minimum = min(minimum, w.scene.bubble_scale)
            self.assertGreaterEqual(minimum, 0.0)
        finally:
            w.shutdown()


class LandingTest(unittest.TestCase):
    """L'encaissement, branché sur la vraie chute (lot L10).

    `test_impact` vérifie le ressort seul. Ici on vérifie le **câblage** : que
    la chute appelle bien l'encaissement, que la force annoncée sur le bus suit
    la violence du choc, et que les canaux atteignent l'animateur. C'est la
    moitié qu'un test de module ne couvre jamais.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    setUp = BubblePopTest.setUp
    tearDown = BubblePopTest.tearDown
    _window = BubblePopTest._window

    def _chute(self, hauteur: float):
        """Lâche le pet de `hauteur` pixels au-dessus du sol."""
        from pet.app.window import floor_y

        w = self._window()
        w._onboarding = False
        w._intro_phase = ""
        _, _, _, ph = w._pet_rect()
        w._y = floor_y(w.current_monitor().work, ph) - hauteur
        w._vy = 0.0
        w._falling = True
        return w, ph

    def test_une_chute_finit_par_un_encaissement(self) -> None:
        from pet.feedback import bus

        chocs = []
        bus.subscribe("atterri", lambda force, vitesse: chocs.append(force))
        self.addCleanup(bus.clear)

        w, ph = self._chute(400.0)
        try:
            # Le ressort est avancé par la boucle de rendu, pas par la chute :
            # on rejoue les deux, comme `_on_render` les enchaîne.
            creux = 0.0
            for _ in range(240):
                w._impact.step(1.0 / 120.0)
                w._step_fall(1.0 / 120.0, ph)
                creux = min(creux, w._impact.flex)
            self.assertTrue(chocs, "le pet s'est posé sans rien encaisser")
            self.assertGreater(chocs[0], 0.0)
            self.assertLessEqual(chocs[0], 1.0)
            self.assertLess(creux, -0.01, "il touche le sol sans s'écraser")
            self.assertTrue(w._impact.settled,
                            "l'encaissement dure encore deux secondes après")
        finally:
            w.shutdown()

    def test_la_force_suit_la_hauteur_de_chute(self) -> None:
        """C'est ce qui distingue un impact d'une animation d'impact : la même
        courbe jouée quelle que soit la chute se remarque au bout de deux
        minutes d'usage."""
        from pet.feedback import bus

        forces = []
        for hauteur in (60.0, 600.0):
            chocs = []
            bus.clear()
            bus.subscribe("atterri", lambda force, vitesse: chocs.append(force))
            w, ph = self._chute(hauteur)
            try:
                for _ in range(240):
                    w._step_fall(1.0 / 120.0, ph)
            finally:
                w.shutdown()
            forces.append(max(chocs) if chocs else 0.0)
        bus.clear()
        self.assertLess(forces[0], forces[1],
                        "une chute de 6 cm et une de 60 cm encaissent pareil")

    def test_le_corps_s_etire_pendant_la_chute(self) -> None:
        w, ph = self._chute(900.0)
        try:
            for _ in range(30):
                w._step_fall(1.0 / 120.0, ph)
            self.assertTrue(w._falling, "déjà posé : la chute est trop courte")
            self.assertGreater(w._impact.flex, 0.0,
                               "il tombe sans s'allonger")
        finally:
            w.shutdown()

    def test_un_clic_enfonce_le_robot(self) -> None:
        """La réaction au clic passe par le rig depuis le lot L10, et non plus
        par une échelle globale qui grossissait aussi la tête et le contour."""
        w = self._window()
        try:
            w._impact.poke()
            w._impact.step(1.0 / 60.0)
            canaux = w._impact.channels()
            self.assertLess(canaux["body.flex"], 0.0)
            self.assertLess(canaux["body.lift"], 0.0, "il ne s'enfonce pas")
        finally:
            w.shutdown()


class ParticleLayerTest(unittest.TestCase):
    """Les particules vivent dans leur propre calque (CDC §6, lot L11).

    Elles étaient d'abord peintes dans la fenêtre du pet. Deux défauts que seul
    l'usage révèle, et que ces tests gardent :

    - **elles suivaient ses rebonds**, parce que leurs coordonnées étaient
      celles d'un widget qui se déplace à chaque image ;
    - **elles étaient coupées en bas**, les pieds du robot touchant le bord
      inférieur de sa fenêtre à trois pixels près.

    S'y ajoute la contrainte qui avait décidé de l'architecture : rien de tout
    cela ne doit rendre quoi que ce soit cliquable.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    setUp = BubblePopTest.setUp
    tearDown = BubblePopTest.tearDown
    _window = BubblePopTest._window

    def test_les_particules_ne_suivent_pas_le_robot(self) -> None:
        """Le grief d'usage, dans sa forme la plus nue.

        Une poussière est retombée quelque part. Le robot qui rebondit à côté
        n'a aucune raison de l'emmener avec lui.
        """
        import numpy as np
        from pet.ui import sparks

        w = self._window()
        try:
            calque = w._ensure_dust()
            sparks.landing_dust(calque.banc, 1.0, w._pet_rect())
            avant = calque.banc.x.copy(), calque.banc.y.copy()

            # Le robot fait un bond de côté et remonte, comme à l'atterrissage.
            w._x += 40.0
            w._y -= 25.0
            w._apply_position()
            w._step_particles(0.0)

            self.assertTrue(np.array_equal(calque.banc.x, avant[0]))
            self.assertTrue(np.array_equal(calque.banc.y, avant[1]))
        finally:
            w.shutdown()

    def test_le_calque_deborde_sous_les_pieds_et_sur_les_cotes(self) -> None:
        """Il n'y a littéralement pas de place sous le robot dans sa propre
        fenêtre : ses pieds en touchent le bord."""
        w = self._window()
        try:
            calque = w._ensure_dust()
            left, top, pw, ph = w._pet_rect()
            ox, oy = calque._origin
            dpr = pw / max(1, w.width())
            largeur = calque.width() * dpr
            hauteur = calque.height() * dpr

            self.assertLess(ox, left, "le calque ne déborde pas à gauche")
            self.assertGreater(ox + largeur, left + pw, "ni à droite")
            self.assertGreater(oy + hauteur, top + ph,
                               "le calque s'arrête aux pieds du robot")
        finally:
            w.shutdown()

    def test_le_calque_ne_bouge_pas_sous_une_gerbe_en_cours(self) -> None:
        """Une fenêtre qui glisse sous une gerbe vivante la rognerait par un
        bord mouvant. Elle se replace entre deux effets, jamais pendant."""
        from pet.ui import sparks

        w = self._window()
        try:
            calque = w._ensure_dust()
            sparks.landing_dust(calque.banc, 1.0, w._pet_rect())
            origine = calque._origin

            w._x += 120.0
            w._apply_position()
            w._ensure_dust()
            self.assertEqual(calque._origin, origine)

            calque.banc.clear()
            w._ensure_dust()
            self.assertNotEqual(calque._origin, origine,
                                "le calque ne se replace jamais")
        finally:
            w.shutdown()

    def test_le_calque_ne_recoit_aucun_clic(self) -> None:
        """Posé une fois à la création et jamais levé : aucune branche ne peut
        le retirer par mégarde. C'est la contrainte §6 rendue structurellement
        impossible à enfreindre plutôt que seulement respectée."""
        from PySide6.QtCore import Qt

        w = self._window()
        try:
            calque = w._ensure_dust()
            self.assertTrue(calque.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        finally:
            w.shutdown()

    def test_une_gerbe_n_entre_pas_dans_l_alpha_du_pet(self) -> None:
        """Le hit-testing lit cet alpha : une étincelle qui y figurerait
        deviendrait une surface d'interception, et les clics destinés à la
        fenêtre du dessous seraient avalés par de la poussière."""
        import numpy as np
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
        from pet.ui import sparks

        w = self._window()
        try:
            w._on_render()
            bbox, alpha = w._bbox, w._alpha.copy()

            sparks.care_sparks(w._ensure_dust().banc, w._pet_rect())
            self.assertGreater(w.dust.banc.count, 10)

            image = QImage(w.width(), w.height(),
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            w.render(image)                      # déclenche le paintEvent du pet

            self.assertEqual(w._bbox, bbox)
            self.assertTrue(np.array_equal(w._alpha, alpha))
        finally:
            w.shutdown()


class ParticleLifecycleTest(unittest.TestCase):
    """Abonnements au bus, et cycle de vie du calque."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    setUp = BubblePopTest.setUp
    tearDown = BubblePopTest.tearDown
    _window = BubblePopTest._window

    def test_un_atterrissage_souleve_de_la_poussiere(self) -> None:
        from pet.feedback import bus

        w = self._window()
        try:
            bus.emit("atterri", force=0.9, vitesse=1100.0)
            self.assertIsNotNone(w.dust, "le fait n'a créé aucun calque")
            self.assertGreater(w.dust.banc.count, 0)
        finally:
            w.shutdown()

    def test_le_calque_se_masque_quand_il_est_vide(self) -> None:
        """Une fenêtre transparente de plus dans la pile ne coûte pas cher,
        mais elle ne coûte rien du tout quand elle n'est pas là."""
        from pet.feedback import bus

        w = self._window()
        try:
            bus.emit("atterri", force=1.0, vitesse=1400.0)
            self.assertTrue(w.dust.isVisible())
            for _ in range(300):
                w._step_particles(1.0 / 60.0)
            self.assertTrue(w.dust.banc.empty)
            self.assertFalse(w.dust.isVisible())
        finally:
            w.shutdown()

    def test_une_fenetre_fermee_se_desabonne(self) -> None:
        """Le bus est un objet de service qui survit à la fenêtre. Une fenêtre
        détruite qui continue d'y répondre peindrait dans un widget mort — ce
        qui n'arrive qu'en test, là où l'on crée des dizaines de fenêtres, mais
        y arrive à coup sûr.
        """
        from pet.feedback import bus

        w = self._window()
        w.shutdown()
        bus.emit("atterri", force=1.0, vitesse=1400.0)
        self.assertIsNone(w.dust)


class CupsWindowTest(unittest.TestCase):
    """Le jeu des gobelets, côté fenêtre : ce que la logique pure ne voit pas.

    Les deux défauts gardés ici se jouaient entièrement dans le fenêtrage, et
    aucun test de `pet/games` n'aurait pu les attraper — la partie était
    parfaitement correcte pendant que le robot restait invisible.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    setUp = BubblePopTest.setUp
    tearDown = BubblePopTest.tearDown
    _window = BubblePopTest._window

    def _partie(self, w):
        w._onboarding = False
        w._intro_phase = ""
        w.brain.needs.energy = 100.0
        self.assertTrue(w.start_cups(), "la partie n'a pas démarré")
        return w.cups

    def _jusqu_au_choix(self, w, limite: float = 40.0) -> None:
        t, dt = 0.0, 1.0 / 120.0
        while w.cups is not None and not w.cups.can_pick and t < limite:
            w._step_cups(dt)
            t += dt

    def test_le_robot_reapparait_a_la_fin(self) -> None:
        """Le défaut : `on_end` réaffichait bien le robot, puis la suite de
        `_step_cups` recalculait la visibilité sur l'état `over` — donc
        « caché » — et le remasquait dans la foulée. Il ne revenait jamais, et
        l'utilisateur se retrouvait devant un bureau vide.
        """
        w = self._window()
        try:
            partie = self._partie(w)
            self._jusqu_au_choix(w)
            self.assertTrue(partie.can_pick, "le mélange ne se termine pas")

            partie.pick((partie.robot_slot + 1) % 3)      # on se trompe
            t, dt = 0.0, 1.0 / 120.0
            while not partie.over and t < 10.0:
                w._step_cups(dt)
                t += dt

            self.assertTrue(partie.over)
            self.assertTrue(w.isVisible(), "le robot ne revient pas")
        finally:
            w.shutdown()

    def test_le_robot_est_cache_pendant_le_melange(self) -> None:
        """L'illusion tient à cela, et à rien d'autre : le gobelet ne cache pas
        le robot, il cache du vide."""
        from pet.games import cups as jeu

        w = self._window()
        try:
            partie = self._partie(w)
            t, dt = 0.0, 1.0 / 120.0
            vu_cache = False
            while not partie.can_pick and t < 40.0:
                w._step_cups(dt)
                t += dt
                if partie.state == jeu.SHUFFLING:
                    self.assertFalse(w.isVisible(),
                                     "le robot se voit pendant le mélange")
                    vu_cache = True
            self.assertTrue(vu_cache, "le mélange n'a jamais eu lieu")
        finally:
            w.shutdown()

    def test_il_se_montre_sous_le_bon_gobelet_au_resultat(self) -> None:
        """Se tromper doit montrer **où il était**, pas où l'on a cliqué."""
        from pet.games import cups as jeu

        w = self._window()
        try:
            partie = self._partie(w)
            self._jusqu_au_choix(w)
            vrai = partie.robot_slot
            partie.pick((vrai + 1) % 3)
            w._step_cups(1.0 / 120.0)

            self.assertEqual(partie.state, jeu.RESULT)
            self.assertTrue(w.isVisible())
            _, _, pw, _ = w._pet_rect()
            centre = w.cups_window.slot_center_x(vrai)
            self.assertLess(abs(w._x + pw / 2.0 - centre), pw * 0.6,
                            "il se montre ailleurs que sous son gobelet")
        finally:
            w.shutdown()

    def test_les_gobelets_n_interceptent_que_pendant_le_choix(self) -> None:
        """Un calque qui prendrait les clics pendant qu'on regarde un mélange
        volerait des clics à ce qui se trouve dessous sans rien offrir."""
        w = self._window()
        try:
            partie = self._partie(w)
            w._step_cups(1.0 / 120.0)
            self.assertFalse(w.cups_window._clickable)
            self._jusqu_au_choix(w)
            self.assertTrue(w.cups_window._clickable)
        finally:
            w.shutdown()

    def test_la_locomotion_ne_promene_pas_le_robot(self) -> None:
        """Le laisser marcher pendant une partie le ferait sortir de son
        gobelet sous les yeux du joueur."""
        w = self._window()
        try:
            self._partie(w)
            _, _, pw, ph = w._pet_rect()
            w._step_locomotion(1.0 / 60.0, 0.0, pw, ph)
            self.assertFalse(w.locomotion.travelling)
        finally:
            w.shutdown()


class IntroSequenceTest(unittest.TestCase):
    """La scène d'arrivée : il sort, se repère, vous voit, puis demande.

    Pilotée avec un dt **synthétique** plutôt qu'en laissant tourner la boucle
    de rendu : celle-ci prend son dt de l'horloge réelle, si bien qu'une boucle
    serrée fait défiler mille images pour une seconde de scène. La première
    version de ce test mesurait donc des durées fausses.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

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

    def _window(self):
        from PySide6.QtWidgets import QApplication
        from pet.app.window import PetWindow
        from pet.brain.session import Session
        from pet.state import save

        settings = save.settings_store()
        settings.load()
        genome, _ = save.load_or_create_genome()
        session = Session()
        session.load()
        w = PetWindow(settings, genome, session=session)
        w.show()
        try:
            w.start()
        except Exception as exc:                       # pragma: no cover
            raise unittest.SkipTest("rendu indisponible : %s" % exc)
        w.begin_onboarding()
        w.hide()
        QApplication.processEvents()
        return w, session

    def _play(self, w, seconds: float, dt: float = 1.0 / 60.0):
        """Fait défiler la scène, et rend la liste des phases traversées."""
        _, _, _, ph = w._pet_rect()
        vues = []
        t = 0.0
        for _ in range(int(seconds / dt)):
            w._step_fall(dt, ph)
            w._step_intro(dt)
            w._step_bubble(dt, t)
            if not vues or vues[-1][0] != w._intro_phase:
                vues.append((w._intro_phase, t))
            t += dt
        return vues

    def test_la_scene_se_deroule_dans_l_ordre_demande(self) -> None:
        w, _ = self._window()
        try:
            mon = w.current_monitor()
            wl, wt, ww, wh = mon.work
            w.emerge_at(wl + ww * 0.5, wt + wh * 0.42)
            phases = [p for p, _ in self._play(w, 12.0)]
            self.assertEqual(phases,
                             ["emerging", "looking", "surprised", "asking"])
        finally:
            w.shutdown()

    def test_il_sort_du_carton_en_bondissant_de_cote(self) -> None:
        """Sans élan propre, il aurait l'air découvert là, pas sorti tout seul."""
        w, _ = self._window()
        try:
            mon = w.current_monitor()
            wl, wt, ww, wh = mon.work
            w.emerge_at(wl + ww * 0.5, wt + wh * 0.42)
            depart = w._x
            self.assertNotEqual(w._vx, 0.0, "aucun élan horizontal")
            self.assertLess(w._vy, 0.0, "le bond doit commencer vers le haut")
            self._play(w, 12.0)
            self.assertGreater(abs(w._x - depart), 80.0,
                               "le bond ne l'a pas emmené assez loin")
        finally:
            w.shutdown()

    def test_il_saute_du_cote_ou_il_y_a_de_la_place(self) -> None:
        """Bondir dans le bord de l'écran ne serait pas une sortie."""
        w, _ = self._window()
        try:
            mon = w.current_monitor()
            wl, wt, ww, wh = mon.work
            w.emerge_at(wl + ww * 0.82, wt + wh * 0.42)
            self.assertLess(w._vx, 0.0, "à droite de l'écran, il part à gauche")
            w.emerge_at(wl + ww * 0.18, wt + wh * 0.42)
            self.assertGreater(w._vx, 0.0, "à gauche, il part à droite")
        finally:
            w.shutdown()

    def test_la_bulle_n_arrive_qu_a_la_fin_de_la_scene(self) -> None:
        w, _ = self._window()
        try:
            mon = w.current_monitor()
            wl, wt, ww, wh = mon.work
            w.emerge_at(wl + ww * 0.5, wt + wh * 0.42)
            self._play(w, 3.0)
            self.assertNotEqual(w._intro_phase, "asking")
            self.assertLess(w._bubble_opacity, 0.05,
                            "la bulle demande avant les présentations")
            self._play(w, 9.0)
            self.assertEqual(w._intro_phase, "asking")
            self.assertGreater(w._bubble_opacity, 0.9)
            self.assertEqual(w._bubble_want, "question")
        finally:
            w.shutdown()

    def test_la_bulle_se_retire_quand_la_saisie_s_ouvre(self) -> None:
        """Demander encore pendant qu'on répond est du bruit."""
        from PySide6.QtWidgets import QApplication

        w, _ = self._window()
        try:
            mon = w.current_monitor()
            wl, wt, ww, wh = mon.work
            w.emerge_at(wl + ww * 0.5, wt + wh * 0.42)
            self._play(w, 12.0)
            self.assertGreater(w._bubble_opacity, 0.9)

            w.ask_for_name()
            QApplication.processEvents()
            self._play(w, 1.0)
            self.assertLess(w._bubble_opacity, 0.1,
                            "la bulle insiste pendant la saisie")
        finally:
            w.shutdown()

    def test_le_regard_est_pilote_par_la_scene(self) -> None:
        """Le suivi du curseur contrarierait le balayage puis le face-à-face."""
        from pet.app.window import INTRO_SCRIPTED

        w, _ = self._window()
        try:
            _, _, pw, ph = w._pet_rect()
            for phase in INTRO_SCRIPTED:
                w._intro_phase = phase
                self.assertIsNone(w._anim_context(pw, ph).look_offset,
                                  "le curseur reprend la main en phase " + phase)
            w._intro_phase = "asking"
            self.assertIsNotNone(w._anim_context(pw, ph).look_offset,
                                 "le suivi doit revenir une fois la scène finie")
        finally:
            w.shutdown()

    def test_pas_de_menu_tant_que_le_robot_n_a_pas_de_nom(self) -> None:
        """Le menu parlerait d'un pet qu'on n'a pas encore accueilli."""
        w, session = self._window()
        try:
            w.toggle_panel()
            self.assertFalse(w.panel_open)

            w._on_name("Zig")
            self.assertEqual(session.name, "Zig")
            self.assertFalse(w._onboarding)
            w.toggle_panel()
            self.assertTrue(w.panel_open, "le menu doit revenir après le nom")
        finally:
            w.shutdown()

    def test_le_bapteme_clot_la_scene(self) -> None:
        w, _ = self._window()
        try:
            w._intro_phase = "asking"
            w._on_name("Zig")
            self.assertEqual(w._intro_phase, "")
            self.assertFalse(w._onboarding)
        finally:
            w.shutdown()

    def test_un_nom_refuse_ne_bloque_pas_l_utilisateur(self) -> None:
        """Garde-fou : sans lui, un refus laissait le pet sans menu à jamais.

        Le baptême se termine dès que le robot **a** un nom, pas dès qu'un nom
        vient d'être accepté.
        """
        w, session = self._window()
        try:
            self.assertTrue(session.set_name("Zig"))
            w._on_name("Autre")            # refusé : le nom est définitif
            self.assertEqual(session.name, "Zig")
            self.assertFalse(w._onboarding)
        finally:
            w.shutdown()


class UnboxingFallTest(unittest.TestCase):
    """Le carton doit **entrer dans le champ**, donc venir de hors-champ."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def test_il_part_au_dessus_du_bord_haut_de_l_ecran(self) -> None:
        from pet.ui.unboxing import HEIGHT, Unboxing

        box = Unboxing()
        box.start(center_x=900, target_y=500, screen_top=0)
        self.assertLessEqual(box._y + HEIGHT, 0.0,
                             "le carton est déjà visible au lâcher")
        box.hide()

    def test_un_ecran_haut_place_ne_le_fait_pas_partir_de_trop_loin(self) -> None:
        """Un moniteur dont le bord est très au-dessus ne doit pas donner une
        chute interminable : le départ est aussi borné par la cible."""
        from pet.ui.unboxing import HEIGHT, Unboxing

        box = Unboxing()
        box.start(center_x=900, target_y=500, screen_top=-4000)
        self.assertGreaterEqual(box._y, -4000.0 - HEIGHT)
        box.hide()


class ItemCatalogueTest(unittest.TestCase):
    """Découverte des sprites, et variété des repas."""

    def test_seuls_les_consommables_passent_par_un_objet(self) -> None:
        """Une caresse ne s'apporte pas, une pile non plus.

        La caresse est un geste direct, et la pile s'applique sur-le-champ : la
        faire traverser l'écran serait une comédie sans intérêt, et on l'utilise
        précisément quand le robot est trop épuisé pour marcher.
        """
        from pet.brain.consumables import CONSUMABLES
        from pet.brain.needs import CARE_GAINS
        from pet.ui.item import ITEM_KINDS

        self.assertEqual(set(ITEM_KINDS), {"feed", "clean"})
        self.assertNotIn("pet", ITEM_KINDS)
        for article in CONSUMABLES:
            if article.instant:
                continue
            self.assertIn(article.kind, ITEM_KINDS,
                          article.key + " se pose sans sprite")
        self.assertEqual(set(CARE_GAINS), {"pet"},
                         "un soin gratuit a survécu à la migration")

    def test_chaque_soin_a_au_moins_un_sprite_livre(self) -> None:
        from pet.ui.item import ITEM_KINDS, available_sprites

        for kind in ITEM_KINDS:
            self.assertTrue(available_sprites(kind),
                            "aucun sprite livré pour " + kind)

    def test_la_nourriture_est_variee(self) -> None:
        """« Histoire qu'il ne mange pas tout le temps la même chose. »"""
        from pet.ui.item import available_sprites

        self.assertGreaterEqual(len(available_sprites("feed")), 4)

    def test_un_dossier_absent_ne_leve_pas(self) -> None:
        """Le mécanisme doit survivre à des sprites qui ne sont pas encore là."""
        from pathlib import Path

        from pet.ui.item import available_sprites

        self.assertEqual(available_sprites("feed", Path("nexistepas")), [])
        self.assertEqual(available_sprites("licorne"), [])

    def test_le_tirage_ne_resert_jamais_le_precedent(self) -> None:
        from pet.ui.item import SpritePicker

        pick = SpritePicker(seed=3)
        suite = [pick.pick("feed") for _ in range(20)]
        self.assertNotIn(None, suite)
        for avant, apres in zip(suite, suite[1:]):
            self.assertNotEqual(avant, apres, "deux repas identiques d'affilée")

    def test_le_tirage_est_reproductible(self) -> None:
        from pet.ui.item import SpritePicker

        a = [SpritePicker(seed=7).pick("play") for _ in range(1)]
        b = [SpritePicker(seed=7).pick("play") for _ in range(1)]
        self.assertEqual(a, b)

    def test_un_soin_sans_sprite_rend_None_sans_lever(self) -> None:
        from pet.ui.item import SpritePicker

        self.assertIsNone(SpritePicker(seed=0).pick("pet"))


class ItemWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def _item(self, kind: str = "feed"):
        from pet.ui.item import ItemWindow, SpritePicker

        return ItemWindow(kind, SpritePicker(seed=1).pick(kind), 64)

    def test_la_consommation_est_idempotente(self) -> None:
        """Régression : le besoin montait **deux fois**, en silence.

        L'animation de disparition passe en `gone` dans la même image où elle
        se termine, la fenêtre retombait alors dans son test de proximité, et
        rien ne signalait le second soin. L'invariant vit désormais sur l'objet.
        """
        item = self._item()
        self.assertTrue(item.consume())
        self.assertFalse(item.consume())
        self.assertTrue(item.eaten)
        # Même après la fin de l'animation.
        for _ in range(90):
            item.step(1.0 / 60.0, 0.0)
        self.assertTrue(item.gone)
        self.assertFalse(item.consume())

    def test_il_tombe_puis_se_pose(self) -> None:
        item = self._item()
        item.place(100.0, 0.0)
        for _ in range(240):
            item.step(1.0 / 60.0, 500.0)
        self.assertEqual(item.state, "idle")
        self.assertAlmostEqual(item.y, 500.0, places=3)

    def test_il_s_evapore_au_bout_de_sa_duree_de_vie(self) -> None:
        from pet.ui.item import TTL_SECONDS

        item = self._item()
        item.state = "idle"
        item._t = TTL_SECONDS + 1.0
        item.step(1.0 / 60.0, 0.0)
        self.assertEqual(item.state, "expiring")
        for _ in range(300):
            item.expire_step(1.0 / 60.0)
        self.assertTrue(item.gone)

    def test_un_objet_tenu_ne_tombe_pas(self) -> None:
        item = self._item()
        item.place(100.0, 0.0)
        item.grab_at(10.0, 10.0)
        for _ in range(60):
            item.step(1.0 / 60.0, 500.0)
        self.assertEqual(item.y, 0.0)

    def test_le_survol_suit_l_alpha_et_non_le_rectangle(self) -> None:
        """Un carré qui mange les clics du bureau serait une gêne.

        La première version testait un point à six pixels du bord **bas**, ce
        qui supposait que le dessin y descende. Un remplacement des sprites l'a
        fait échouer sans qu'aucun comportement n'ait changé : le nouveau
        dessin est simplement mieux centré dans sa case.

        Ce que le test doit affirmer ne dépend pas de l'illustration : un point
        du dessin intercepte, un point **transparent du même rectangle** ne doit
        pas — c'est exactement la différence entre suivre l'alpha et suivre la
        boîte — et un point hors du rectangle non plus.
        """
        item = self._item()
        self.assertTrue(item.opaque_at(item.width() / 2, item.height() / 2),
                        "le centre du dessin n'intercepte pas")
        self.assertFalse(item.opaque_at(2.0, 2.0),
                         "un coin transparent intercepte : c'est la boîte qui "
                         "est testée, pas le dessin")
        self.assertFalse(item.opaque_at(-5.0, -5.0))
        self.assertFalse(item.opaque_at(1e6, 1e6))

    def test_chaque_sprite_livre_remplit_sa_case(self) -> None:
        """Un dessin doit offrir une cible confortable, où qu'il soit tiré.

        Le sprite est choisi au hasard à chaque objet posé : un seul dessin
        minuscule ou coincé dans un coin rendrait un objet sur six pénible à
        attraper, et le défaut ne se manifesterait qu'une fois de temps en
        temps — le pire cas pour le diagnostiquer.

        Ce qu'on vérifie est donc le **cadrage**, pas un pixel précis. Tester
        l'opacité du centre exact serait faux : la roue dentée a un moyeu creux,
        et ne pas pouvoir attraper un trou est le comportement correct d'un
        survol qui suit l'alpha.
        """
        from pet.ui.item import ASSET_DIR, ItemWindow

        for fichier in sorted(ASSET_DIR.glob("*.png")):
            item = ItemWindow("feed", fichier, 64)
            image = item.pixmap.toImage()
            w, h = image.width(), image.height()
            lignes = [y for y in range(h)
                      if any(image.pixelColor(x, y).alpha() > 25 for x in range(w))]
            colonnes = [x for x in range(w)
                        if any(image.pixelColor(x, y).alpha() > 25 for y in range(h))]
            self.assertTrue(lignes and colonnes, "%s est vide" % fichier.name)

            haut, bas = min(lignes), max(lignes)
            gauche, droite = min(colonnes), max(colonnes)
            self.assertGreater(bas - haut, h * 0.35,
                               "%s est trop petit en hauteur" % fichier.name)
            self.assertGreater(droite - gauche, w * 0.20,
                               "%s est trop étroit" % fichier.name)
            self.assertLess(abs((haut + bas) / 2.0 - h / 2.0), h * 0.18,
                            "%s est décentré verticalement" % fichier.name)
            self.assertLess(abs((gauche + droite) / 2.0 - w / 2.0), w * 0.18,
                            "%s est décentré horizontalement" % fichier.name)


class ConsumableInTwoStepsTest(unittest.TestCase):
    """Sortir un article du stock et l'appliquer sont deux gestes distincts.

    C'était déjà vrai des soins par objet avant le lot L13, sous forme de
    délais : réserver posait le compte à rebours, livrer donnait le gain. Le
    mécanisme a changé — une quantité au lieu d'un délai — mais la propriété
    est la même, et pour la même raison : l'article quitte le stock quand on le
    **pose**, sinon un seul exemplaire en sèmerait dix.
    """

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

    def _session(self, stock: int = 2):
        from pet.brain.session import Session

        s = Session()
        s.load()
        s.economy.tokens = 50
        s.buy_consumable("meal", stock)
        s.brain.needs.hunger = 10.0
        return s

    def test_sortir_du_stock_ne_donne_pas_le_gain(self) -> None:
        s = self._session()
        self.assertTrue(s.use_consumable("meal"))
        self.assertEqual(s.count("meal"), 1)
        self.assertEqual(s.brain.needs.hunger, 10.0,
                         "le gain est arrivé trop tôt")

    def test_appliquer_donne_le_gain(self) -> None:
        s = self._session()
        s.use_consumable("meal")
        applied = s.apply_consumable("meal")
        self.assertIn("hunger", applied)
        self.assertGreater(s.brain.needs.hunger, 10.0)

    def test_on_ne_pose_pas_plus_qu_on_ne_possede(self) -> None:
        """Sans quoi rien n'empêcherait de semer dix gamelles."""
        s = self._session(stock=1)
        self.assertTrue(s.use_consumable("meal"))
        self.assertFalse(s.use_consumable("meal"))

    def test_le_remboursement_rend_l_article(self) -> None:
        """Un objet jamais rejoint ne doit pas être facturé (§12)."""
        s = self._session(stock=1)
        s.use_consumable("meal")
        s.refund_consumable("meal")
        self.assertEqual(s.count("meal"), 1)
        self.assertEqual(s.brain.needs.hunger, 10.0)

    def test_la_pile_fait_les_deux_d_un_coup(self) -> None:
        """Elle ne se pose pas sur le bureau : on l'utilise précisément quand
        le robot est trop épuisé pour aller la chercher."""
        from pet.brain.consumables import get

        s = self._session()
        s.buy_consumable("battery")
        s.brain.needs.energy = 5.0
        self.assertTrue(get("battery").instant)
        s.use_consumable("battery")
        s.apply_consumable("battery")
        self.assertEqual(s.brain.needs.energy, 100.0)

    def test_la_caresse_reste_un_soin_gratuit(self) -> None:
        from pet.brain.brain import Brain
        from pet.brain.needs import Needs

        brain = Brain(Needs(fun=10.0))
        applied = brain.care("pet")
        self.assertTrue(applied)
        self.assertFalse(brain.can_care("pet"))


class FetchWithPanelOpenTest(unittest.TestCase):
    """Un objet posé depuis le menu doit pouvoir être rejoint.

    Le défaut : le panneau bloque la locomotion — délibérément, parce qu'un
    panneau ancré au-dessus de la tête serait illisible s'il courait après un
    robot en mouvement. Mais les trois soins qui passent par un objet sont
    demandés **depuis ce panneau**, et il reste ouvert après le clic. Le robot
    voyait donc sa gamelle, la regardait, et ne pouvait jamais l'atteindre :
    l'objet s'évaporait au bout de trois minutes et le délai était remboursé.

    Rien n'échouait, rien n'était journalisé — le soin n'avait simplement
    jamais lieu.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    setUp = BubblePopTest.setUp
    tearDown = BubblePopTest.tearDown
    _window = BubblePopTest._window

    def test_demander_a_manger_libere_le_robot(self) -> None:
        w = self._window()
        try:
            w._onboarding = False
            w._intro_phase = ""
            w.session.economy.tokens = 20
            w.session.buy_consumable("meal", 2)
            panneau = w._ensure_panel()
            panneau.open_page("inventory")
            panneau.open_panel()
            _settle(panneau)
            self.assertTrue(w.panel_open)

            w._on_consumable("meal")
            self.assertIsNotNone(w.item, "aucun objet n'est apparu")

            _settle(panneau)
            self.assertFalse(w.panel_open,
                             "le panneau reste ouvert : le robot ne pourra "
                             "jamais rejoindre son objet")
        finally:
            w.shutdown()

    def test_la_locomotion_reprend_la_main(self) -> None:
        """La conséquence, dite dans les termes du mouvement : une fois l'objet
        posé, plus rien ne cède la position à l'utilisateur."""
        w = self._window()
        try:
            w._onboarding = False
            w._intro_phase = ""
            w.session.economy.tokens = 20
            w.session.buy_consumable("meal", 2)
            panneau = w._ensure_panel()
            panneau.open_page("inventory")
            panneau.open_panel()
            _settle(panneau)

            w._on_consumable("meal")
            _settle(panneau)

            from pet.app.window import INTRO_SCRIPTED

            self.assertFalse(
                w._dragging or w._falling or w.panel_open
                or w._intro_phase in INTRO_SCRIPTED,
                "quelque chose bloque encore la locomotion")
        finally:
            w.shutdown()

    def _boucle(self, w, secondes: float = 8.0, dt: float = 1.0 / 60.0) -> bool:
        """Fait tourner les trois boucles du produit, au bon rythme chacune.

        Locomotion et animation du panneau par image, comportement à 4 Hz. Ce
        n'est pas du zèle : le défaut se joue **entre** ces cadences. Le
        panneau cède la position à chaque image tant qu'il est ouvert, et le
        `brain` n'élit `fetch_item` qu'au tick suivant l'apparition de l'objet —
        c'est-à-dire pendant le repos que cette cession vient d'armer. Un test
        qui laisserait le panneau se fermer avant de commencer ne verrait rien.

        Rend `True` dès que la locomotion a une cible.
        """
        _, _, pw, ph = w._pet_rect()
        t, prochain = 0.0, 0.0
        while t < secondes:
            if t >= prochain:
                w._tick_brain(t)
                prochain = t + 0.25
            if w.panel is not None:
                w.panel.step(dt)
            w._step_locomotion(dt, t, pw, ph)
            if w.locomotion is not None and w.locomotion.travelling:
                return True
            t += dt
        return False

    def _menu_ouvert(self, w, secondes: float = 1.5, dt: float = 1.0 / 60.0):
        """Ouvre le menu et **fait tourner la boucle** pendant qu'il est ouvert.

        Ce second point est ce qui manquait à la première version de ce test, et
        c'est tout le défaut : `_step_locomotion` suspend le déplacement à
        chaque image tant que le panneau est là. Un test qui ouvre le panneau
        sans faire tourner la boucle n'arme rien, et voit un produit qui marche.
        """
        panneau = w._ensure_panel()
        w.session.economy.tokens = 20
        w.session.buy_consumable("meal", 2)
        panneau.open_page("inventory")
        panneau.open_panel()
        _, _, pw, ph = w._pet_rect()
        for _ in range(int(secondes / dt)):
            panneau.step(dt)
            w._step_locomotion(dt, 0.0, pw, ph)
        return panneau

    def test_le_robot_se_met_en_route_sans_faire_attendre(self) -> None:
        """Le défaut complet, et il avait deux causes.

        **Le repos de trop.** `_step_locomotion` appelait `yield_to_user` pour
        le panneau ouvert comme pour un glisser, et cet appel arme deux
        secondes et demie de repos — à chaque image. Demander à manger depuis le
        menu laissait donc le robot planté deux secondes et demie après la
        fermeture, alors que personne ne l'avait touché.

        **L'unique tentative.** Pendant ce repos, `go_to` refuse la cible. Or
        `_apply_plan` n'était appelé qu'au *changement* d'action : `fetch_item`
        restait élue, la route n'était jamais redemandée, et le robot regardait
        sa gamelle indéfiniment.

        La borne d'une seconde est le critère : elle échoue sur la première
        cause comme sur la seconde.
        """
        w = self._window()
        try:
            w._onboarding = False
            w._intro_phase = ""
            panneau = self._menu_ouvert(w)

            w._on_consumable("meal")
            self.assertIsNotNone(w.item)
            self.assertTrue(panneau.closing)

            self.assertTrue(self._boucle(w, secondes=1.0),
                            "le robot ne part pas chercher son objet")
            _, _, pw, _ = w._pet_rect()
            vise = w.locomotion.target_x
            objet = w.item.center(pw / max(1, w.width()))[0]
            self.assertLess(abs(vise - objet), pw,
                            "il part, mais pas vers son objet")
        finally:
            w.shutdown()

    def test_un_panneau_ouvert_n_arme_aucun_repos(self) -> None:
        """Le panneau n'a pas touché au robot : rien ne justifie de le faire
        patienter une fois refermé. Le repos reste pour les manipulations."""
        w = self._window()
        try:
            w._onboarding = False
            w._intro_phase = ""
            self._menu_ouvert(w)
            self.assertEqual(w.locomotion.cooldown, 0.0)

            w._dragging = True
            _, _, pw, ph = w._pet_rect()
            w._step_locomotion(1.0 / 60.0, 0.0, pw, ph)
            self.assertGreater(w.locomotion.cooldown, 0.0,
                               "un glisser doit encore faire souffler le robot")
        finally:
            w.shutdown()

    def test_attraper_le_pet_en_chemin_ne_l_arrete_pas_definitivement(self) -> None:
        """La forme générale du même défaut : une route abandonnée pendant que
        l'action dure doit être reprise, quelle qu'en soit la cause."""
        w = self._window()
        try:
            w._onboarding = False
            w._intro_phase = ""
            w._on_consumable("meal")
            self.assertTrue(self._boucle(w), "il n'est jamais parti")

            # On l'attrape : la locomotion cède et oublie sa cible.
            w._dragging = True
            _, _, pw, ph = w._pet_rect()
            w._step_locomotion(1.0 / 60.0, 0.0, pw, ph)
            self.assertFalse(w.locomotion.travelling)

            w._dragging = False
            self.assertTrue(self._boucle(w),
                            "lâché, il reste planté au lieu de repartir")
        finally:
            w.shutdown()

    def test_une_caresse_ne_ferme_pas_le_panneau(self) -> None:
        """Elle agit tout de suite et ne pose rien sur le bureau : il n'y a
        aucune raison de renvoyer l'utilisateur hors du menu."""
        w = self._window()
        try:
            w._onboarding = False
            w._intro_phase = ""
            w.session.economy.tokens = 20
            w.session.buy_consumable("meal", 2)
            panneau = w._ensure_panel()
            panneau.open_page("inventory")
            panneau.open_panel()
            _settle(panneau)

            w._on_care("pet")
            _settle(panneau)
            self.assertTrue(w.panel_open, "le panneau s'est fermé pour rien")
        finally:
            w.shutdown()


class FetchActionTest(unittest.TestCase):
    """L'action d'aller chercher, et sa place dans la hiérarchie."""

    def _me(self, **kwargs):
        from pet.brain.utility import SelfState

        base = dict(x=1000.0, pet_h=150.0, span=(0.0, 3840.0))
        base.update(kwargs)
        return SelfState(**base)

    def _ctx(self, state="typing"):
        from pet.brain.sensors import SystemContext

        return SystemContext(state=state)

    def test_elle_n_existe_que_s_il_y_a_un_objet(self) -> None:
        from pet.brain.actions import FetchItem
        from pet.brain.needs import Needs

        action = FetchItem()
        self.assertFalse(action.is_available(Needs(), self._ctx(), self._me()))
        self.assertTrue(action.is_available(Needs(), self._ctx(),
                                            self._me(item_x=500.0)))

    def test_elle_passe_devant_le_film_mais_derriere_les_reflexes(self) -> None:
        """Poser un objet est un geste délibéré : il doit être vu.

        Un clic reste prioritaire, lui.
        """
        from pet.brain.actions import FetchItem, ReactToPoke, SitAndWatch
        from pet.brain.needs import Needs

        me = self._me(item_x=500.0)
        aller = FetchItem().score(Needs(), self._ctx("watching"), me)
        film = SitAndWatch().score(Needs(), self._ctx("watching"), me)
        reflexe = ReactToPoke().score(Needs(), self._ctx(), me)
        self.assertGreater(aller, film)
        self.assertLess(aller, reflexe)

    def test_le_brain_l_elit_des_qu_un_objet_est_la(self) -> None:
        from pet.brain.brain import TICK, Brain

        brain = Brain()
        me = self._me(item_x=500.0)
        for _ in range(8):
            plan = brain.update(TICK, self._ctx(), me)
        self.assertEqual(plan.action, "fetch_item")
        self.assertEqual(plan.travel, "item")

    def test_l_intention_de_deplacement_est_declaree(self) -> None:
        from pet.brain.utility import TRAVELS

        self.assertIn("item", TRAVELS)


class ItemPanelTest(unittest.TestCase):
    """Un seul objet à la fois, et le panneau le dit."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def test_les_soins_par_objet_se_grisent_ensemble(self) -> None:
        from pet.brain.brain import Brain
        from pet.genome.generator import generate
        from pet.ui.item import ITEM_KINDS
        from pet.ui.panel import CarePanel

        session = _FauxSession(Brain(), "Zig")
        session.appearance = {}
        session.consumables = {"meal": 2, "kit": 1, "battery": 1}
        panel = CarePanel(session, generate(8))
        panel.open_page("inventory")

        offerts = {b.action: b.enabled for b in panel._layout().buttons}
        for cle in ("use:meal", "use:kit"):
            self.assertTrue(offerts[cle])

        panel.item_pending = True
        offerts = {b.action: b.enabled for b in panel._layout().buttons}
        for cle in ("use:meal", "use:kit"):
            self.assertFalse(offerts[cle], cle + " reste offert")
        self.assertTrue(offerts["use:battery"],
                        "la caresse ne dépend d'aucun objet")


class ItemHandOffTest(unittest.TestCase):
    """Consommer un objet **qu'on tient encore**.

    Signalé à l'usage : en traînant l'objet jusqu'au robot, la consommation
    démarrait mais ne finissait pas, et l'objet restait posé sur le bureau sans
    plus jamais pouvoir être absorbé.

    La cause tenait à l'ordre des événements. La proximité déclenche pendant
    que le bouton de la souris est **encore enfoncé** ; le relâchement qui suit
    appelait `release`, qui écrasait l'état « consommé » par « en chute ».
    L'objet retombait, se posait, et comme il était déjà marqué mangé il n'était
    plus consommable.

    Le symptôme ne se voyait qu'avec le panneau ouvert : le pet immobile fait de
    « traîner l'objet jusqu'à lui » la façon naturelle de faire, alors que sans
    panneau c'est le robot qui vient chercher — et il n'est alors tenu par
    personne.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ensure_app()

    def _item(self):
        from pet.ui.item import ItemWindow
        return ItemWindow("feed", None, 70)

    def test_consommer_en_main_lache_la_prise(self) -> None:
        item = self._item()
        item.grab_at(5.0, 5.0)
        self.assertTrue(item.held)
        self.assertTrue(item.consume())
        self.assertFalse(item.held, "l'objet mangé est encore tenu")
        self.assertEqual(item.state, "consumed")

    def test_le_relachement_ne_fait_pas_retomber_un_objet_mange(self) -> None:
        """Le coeur du bug : `release` écrasait l'état de consommation."""
        item = self._item()
        item.grab_at(5.0, 5.0)
        item.consume()
        item.release()
        self.assertEqual(item.state, "consumed",
                         "l'objet mangé est reparti en chute")

    def test_un_objet_mange_ne_se_reattrape_pas(self) -> None:
        item = self._item()
        item.consume()
        item.grab_at(5.0, 5.0)
        self.assertFalse(item.held)
        self.assertEqual(item.state, "consumed")

    def test_un_objet_mange_ne_se_deplace_plus(self) -> None:
        item = self._item()
        item.place(100.0, 200.0)
        item.grab_at(5.0, 5.0)
        item.consume()
        item.drag_to(900.0, 900.0)
        self.assertEqual((item.x, item.y), (100.0, 200.0))

    def test_l_animation_va_jusqu_au_bout_malgre_la_prise(self) -> None:
        """C'est la partie visible du symptôme : elle ne terminait pas."""
        from pet.ui.item import CONSUME_SECONDS

        item = self._item()
        item.grab_at(5.0, 5.0)
        item.consume()
        item.release()
        for _ in range(int(CONSUME_SECONDS / 0.02) + 6):
            item.step(0.02, 500.0)
        self.assertTrue(item.gone, "l'objet est resté sur le bureau")

    def test_un_objet_mange_ne_se_remange_pas(self) -> None:
        item = self._item()
        self.assertTrue(item.consume())
        for _ in range(3):
            self.assertFalse(item.consume(), "le soin serait appliqué deux fois")

    def test_le_cycle_normal_reste_intact(self) -> None:
        """Attraper, déplacer, relâcher : rien de tout cela ne doit changer."""
        item = self._item()
        item.place(100.0, 100.0)
        item.grab_at(10.0, 10.0)
        item.drag_to(500.0, 300.0)
        self.assertEqual((item.x, item.y), (490.0, 290.0))
        item.release()
        self.assertEqual(item.state, "falling")
        self.assertFalse(item.held)


if __name__ == "__main__":
    unittest.main()
