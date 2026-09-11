"""Critères d'acceptation du rendu, lot L3 (CDC §8, §9).

Tests headless sur un contexte OpenGL standalone : ils rendent réellement et
mesurent les pixels. Ce qui est vérifié ici et non à l'œil :

- l'alpha reste **prémultiplié** avec les quatre passes actives, faute de quoi
  le liseré noir du lot L0 revient ;
- le contour est un **trait** et non un aplat, et son épaisseur est constante
  sous rotation et proportionnelle au gène ;
- les **coques ouvertes** sont exclues du contour ;
- le visage est piloté **entièrement par uniformes**.

Le jugement esthétique se rend sur les planches de `tools/`, pas ici.
"""

from __future__ import annotations

import unittest

import numpy as np

from pet.genome.generator import generate
from pet.genome.schema import defaults
from pet.geometry.builder import build
from pet.render.context import RenderContext
from pet.render.face import EXPRESSIONS, FaceState
from pet.render.outline import BASE_WIDTH_PX, OutlinePass
from pet.render.scene import Scene

SIZE = 220


class _GLTest(unittest.TestCase):
    """Base : un contexte et une scène partagés par la classe."""

    rc: RenderContext
    scene: Scene

    @classmethod
    def setUpClass(cls) -> None:
        cls.rc = RenderContext((SIZE, SIZE), samples=4)
        cls.scene = Scene(cls.rc)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.scene.release()
        cls.rc.release()

    def render(self, yaw: float = 0.4, pitch: float = 0.16,
               time_s: float = 0.0) -> np.ndarray:
        self.rc.begin()
        self.scene.draw(yaw=yaw, pitch=pitch, time_s=time_s)
        return self.rc.read_rgba().copy()

    def alpha_mask(self, **kw) -> np.ndarray:
        return self.render(**kw)[:, :, 3] > 127


class PremultipliedTest(_GLTest):
    def test_invariant_avec_les_quatre_passes(self) -> None:
        """Aucun canal couleur ne peut dépasser l'alpha.

        Une violation signifie de l'alpha droit, donc le liseré noir que le lot
        L0 avait éliminé. Le contour et l'ombre sont les deux passes les plus
        susceptibles de le réintroduire, puisqu'elles écrivent du sombre sur le
        pourtour de la silhouette.
        """
        self.scene.set_robot(build(generate(8)))
        for yaw in (0.0, 1.1, 2.3, 3.7, 5.2):
            px = self.render(yaw=yaw)
            a = px[:, :, 3].astype(np.int32)
            rgb = px[:, :, :3].astype(np.int32)
            violations = int((rgb > a[:, :, None] + 1).sum())
            self.assertEqual(violations, 0, f"yaw={yaw}")

    def test_bord_anti_aliase(self) -> None:
        self.scene.set_robot(build(generate(8)))
        a = self.render()[:, :, 3]
        partiel = int(((a > 8) & (a < 248)).sum())
        self.assertGreater(partiel, 100, "le pourtour doit rester anti-aliasé")

    def test_fond_reellement_transparent(self) -> None:
        self.scene.set_robot(build(generate(8)))
        px = self.render()
        # Les quatre coins sont hors du robot et hors de l'ombre.
        for y, x in ((0, 0), (0, SIZE - 1), (SIZE - 1, 0), (SIZE - 1, SIZE - 1)):
            self.assertEqual(int(px[y, x, 3]), 0, f"coin ({y},{x})")


class OutlineTest(_GLTest):
    @staticmethod
    def _perimeter(mask: np.ndarray) -> int:
        inner = (mask
                 & np.roll(mask, 1, 0) & np.roll(mask, -1, 0)
                 & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
        return int(mask.sum() - inner.sum())

    def _thickness(self, yaw: float) -> float:
        """Épaisseur du trait, mesurée par différence d'images.

        Compter les pixels sombres ne marche pas : la dalle faciale en est. On
        mesure donc la frange réellement **ajoutée** par la passe, rapportée au
        périmètre de la silhouette.
        """
        self.scene.draw_outline = False
        sans = self.alpha_mask(yaw=yaw)
        self.scene.draw_outline = True
        avec = self.alpha_mask(yaw=yaw)
        return int((avec & ~sans).sum()) / max(1, self._perimeter(sans))

    def test_le_contour_est_un_trait_et_non_un_aplat(self) -> None:
        """Le sens de culling est mesuré, pas déduit.

        Avec l'axe Y inversé de la projection, se tromper de sens remplit toute
        la silhouette de sombre au lieu de la border. La prédiction faite au lot
        L2 — culler GL_BACK — était fausse : c'est bien GL_FRONT, comme l'écrit
        le CDC §8, parce que l'enroulement des maillages a justement été choisi
        pour que les faces extérieures restent front-facing après l'inversion.
        """
        self.scene.set_robot(build(generate(8)))

        self.scene.CULL_FACE = "front"
        px = self.render()
        a = px[:, :, 3].astype(np.int32)
        lum = px[:, :, :3].astype(np.int32).sum(axis=2)
        opaque = a > 250
        part_juste = (lum < 90)[opaque].mean()

        self.scene.CULL_FACE = "back"
        px = self.render()
        opaque_faux = px[:, :, 3].astype(np.int32) > 250
        lum_faux = px[:, :, :3].astype(np.int32).sum(axis=2)
        part_fausse = (lum_faux < 90)[opaque_faux].mean()

        self.scene.CULL_FACE = "front"
        self.assertLess(part_juste, 0.40, "GL_FRONT doit border, pas remplir")
        self.assertGreater(part_fausse, 0.95, "GL_BACK doit remplir : sens inversé")

    def test_epaisseur_constante_sous_rotation(self) -> None:
        """CDC §8 : « contour d'épaisseur uniforme sous toutes les rotations »."""
        self.scene.set_robot(build(generate(1)))
        widths = [self._thickness(yaw) for yaw in np.linspace(0, 2 * np.pi, 10,
                                                              endpoint=False)]
        w = np.array(widths)
        self.assertGreater(w.min(), 0.5, "le trait ne doit jamais s'interrompre")
        variation = (w.max() - w.min()) / w.mean()
        self.assertLess(variation, 0.25, f"variation {variation:.0%} sur {w.round(2)}")

    def test_pas_de_fente_aux_exposants_extremes(self) -> None:
        """Le risque redouté au cadrage : une extrusion qui ouvre le trait.

        Il ne se matérialise pas, et la raison est dans le maillage du lot L2 :
        aucun sommet n'y est dupliqué — indices bouclés, pôles uniques — donc
        les normales sont déjà partagées et il n'y a rien à souder.
        """
        g = dict(defaults())
        g["head.exponent_n1"] = g["head.exponent_n2"] = 0.35
        g["outline.width"] = 1.6
        self.scene.set_robot(build(g))
        widths = np.array([self._thickness(yaw)
                           for yaw in np.linspace(0, 2 * np.pi, 12, endpoint=False)])
        self.assertGreater(widths.min(), 0.5 * widths.mean(),
                           f"trait interrompu : {widths.round(2)}")

    def test_l_epaisseur_suit_le_gene(self) -> None:
        """Décision §17.3 : l'épaisseur du contour est un trait génétique."""
        mesures = []
        for width in (0.80, 1.20, 1.60):
            g = dict(defaults())
            g["outline.width"] = width
            self.scene.set_robot(build(g))
            mesures.append((width, self._thickness(0.4)))
        genes = np.array([m[0] for m in mesures])
        px = np.array([m[1] for m in mesures])
        self.assertTrue(np.all(np.diff(px) > 0), f"non monotone : {mesures}")
        # Proportionnel, pas seulement croissant.
        ratio = px / genes
        self.assertLess(ratio.std() / ratio.mean(), 0.15, f"non proportionnel : {mesures}")

    def test_conversion_pixels_vers_monde(self) -> None:
        """Un pixel vaut 2·half_extent/hauteur en unités monde (caméra ortho)."""
        p = OutlinePass.__new__(OutlinePass)
        w = OutlinePass.world_width(p, half_extent=2.0, height_px=200,
                                    genetic_width=1.0)
        self.assertAlmostEqual(w, BASE_WIDTH_PX * 2.0 * 2.0 / 200.0, places=9)
        self.assertEqual(OutlinePass.world_width(p, 2.0, 0, 1.0), 0.0,
                         "hauteur nulle ne doit pas diviser par zéro")

    def test_les_coques_ouvertes_sont_exclues(self) -> None:
        """Extruder la dalle dessinerait un liseré autour de l'écran.

        Vérifié structurellement : la coque faciale se déclare ouverte, et c'est
        ce drapeau que la passe de contour consulte.
        """
        robot = build(generate(8))
        face = next(p for p in robot.parts if p.name == "face")
        self.assertFalse(face.mesh.closed)
        self.assertIsNotNone(face.mesh.uv)
        for part in robot.parts:
            if part.name != "face":
                self.assertTrue(part.mesh.closed, part.name)
                self.assertIsNone(part.mesh.uv, part.name)


class ShadowTest(_GLTest):
    def test_l_ombre_ajoute_des_pixels_sous_le_robot(self) -> None:
        """Le seuil est sur alpha > 0, pas > 127.

        L'ombre est translucide par conception — 0,40 d'opacité, soit 102 au
        maximum sur 255. La mesurer avec un seuil à mi-course n'en voyait
        aucun pixel et faisait croire qu'elle ne rendait pas.
        """
        self.scene.set_robot(build(generate(8)))
        self.scene.draw_shadow = False
        sans = self.render()[:, :, 3] > 0
        self.scene.draw_shadow = True
        avec = self.render()[:, :, 3] > 0
        ajoutes = int((avec & ~sans).sum())
        self.assertGreater(ajoutes, 500, "l'ombre doit être visible")

    def test_l_ombre_n_est_pas_un_filet(self) -> None:
        """Elle doit avoir une emprise verticale réelle.

        Couchée dans le plan du sol, elle ne mesurait que 8 pixels de haut : la
        caméra n'a que 9° de tangage. Le quad est donc aligné sur l'écran.
        """
        self.scene.set_robot(build(generate(8)))
        self.scene.draw_outline = self.scene.draw_face = False
        parts, self.scene._buffers = self.scene._buffers, []
        try:
            a = self.render()[:, :, 3]
        finally:
            self.scene._buffers = parts
            self.scene.draw_outline = self.scene.draw_face = True
        ys = np.flatnonzero((a > 0).any(axis=1))
        self.assertGreater(int(ys[-1] - ys[0] + 1), 16,
                           "l'ombre est trop plate pour se voir")

    def test_l_ombre_s_efface_quand_le_robot_monte(self) -> None:
        """CDC §8 : « l'opacité et le rayon suivent sa hauteur »."""
        self.scene.set_robot(build(generate(8)))
        self.scene.draw_outline = False

        def opacite(lift: float) -> float:
            self.rc.begin()
            self.scene.draw(yaw=0.4, pitch=0.16, lift=lift)
            px = self.rc.read_rgba()
            # Bande basse de l'image : l'ombre y est seule.
            bande = px[int(SIZE * 0.86):, :, 3].astype(np.float64)
            return float(bande.mean())

        au_sol = opacite(0.0)
        en_l_air = opacite(2.0)
        self.scene.draw_outline = True
        self.assertGreater(au_sol, 0.0, "l'ombre doit exister au contact")
        self.assertLess(en_l_air, au_sol,
                        "l'ombre doit pâlir quand le robot est soulevé")

    def test_l_ombre_n_ecrit_pas_la_profondeur(self) -> None:
        """Sinon elle disputerait le test de profondeur aux pieds du robot."""
        self.assertTrue(self.rc.ctx.depth_mask,
                        "le masque de profondeur doit être rétabli après l'ombre")


class FaceTest(_GLTest):
    # Écart bleu-rouge minimal pour retenir le **cœur** d'une pupille.
    #
    # Deux confusions à écarter, chacune mesurée :
    #   - un seuil de luminance compte le corps en plastique blanc, plus
    #     lumineux que les pupilles ;
    #   - un écart bleu-rouge faible (30) attrape le rim light, qui reprend
    #     l'accent du génome et est donc cyan lui aussi, ainsi que le halo du
    #     visage — et le halo ne rétrécit presque pas quand l'œil se ferme.
    # À 120, mesuré : 654 pixels œil ouvert contre 55 œil fermé, strictement
    # décroissant. À 30 : 1321 contre 799, non monotone.
    PUPIL_CORE = 120

    @classmethod
    def _cyan(cls, px: np.ndarray) -> np.ndarray:
        """Cœur des pupilles, halo et rim light exclus."""
        return (px[:, :, 2].astype(np.int32)
                > px[:, :, 0].astype(np.int32) + cls.PUPIL_CORE)

    def test_les_uniformes_du_cdc_existent(self) -> None:
        """Les sept commandes du CDC §9 doivent être exposées par le shader."""
        program = self.scene.face.program
        for name in ("uBlink", "uGaze", "uLidTop", "uLidBottom", "uSquint",
                     "uPupilScale", "uGlitch"):
            self.assertIn(name, program, name)

    def test_toutes_les_expressions_sont_rendables(self) -> None:
        """Aucune branche côté CPU : une expression n'est qu'un jeu de valeurs."""
        self.scene.set_robot(build(generate(8)))
        for name, state in EXPRESSIONS.items():
            self.scene.face_state = state
            px = self.render(time_s=0.42)
            a = px[:, :, 3].astype(np.int32)
            rgb = px[:, :, :3].astype(np.int32)
            self.assertEqual(int((rgb > a[:, :, None] + 1).sum()), 0, name)
            self.assertTrue(np.isfinite(px).all(), name)
        self.scene.face_state = FaceState()

    def test_les_expressions_se_distinguent(self) -> None:
        """Deux expressions différentes doivent produire deux images différentes."""
        self.scene.set_robot(build(generate(8)))
        images = {}
        for name in ("neutre", "joyeux", "fache", "endormi", "surpris"):
            self.scene.face_state = EXPRESSIONS[name]
            images[name] = self.render(time_s=0.0).astype(np.int32)
        self.scene.face_state = FaceState()

        noms = list(images)
        for i, a in enumerate(noms):
            for b in noms[i + 1:]:
                ecart = float(np.abs(images[a] - images[b]).mean())
                self.assertGreater(ecart, 0.05, f"{a} et {b} rendent pareil")

    def test_le_clignement_ferme_progressivement(self) -> None:
        """La surface éclairée doit décroître de façon monotone."""
        self.scene.set_robot(build(generate(8)))
        self.scene.draw_outline = self.scene.draw_shadow = False
        surfaces = []
        for blink in (0.0, 0.3, 0.6, 0.9, 1.0):
            self.scene.face_state = FaceState(blink=blink)
            # Face à la caméra : de biais, la dalle est raccourcie et la mesure
            # dépend de l'angle plus que du clignement.
            surfaces.append(int(self._cyan(self.render(yaw=0.0)).sum()))
        self.scene.draw_outline = self.scene.draw_shadow = True
        self.scene.face_state = FaceState()
        self.assertTrue(all(a >= b for a, b in zip(surfaces, surfaces[1:])),
                        f"non monotone : {surfaces}")
        self.assertGreater(surfaces[0], surfaces[-1] * 5,
                           f"l'œil doit se fermer franchement : {surfaces}")
        self.assertGreater(surfaces[-1], 0,
                           "un œil fermé doit rester un trait, pas disparaître")

    def test_le_regard_deplace_les_pupilles(self) -> None:
        self.scene.set_robot(build(generate(8)))
        self.scene.draw_outline = self.scene.draw_shadow = False

        def barycentre_x(state: FaceState) -> float:
            self.scene.face_state = state
            ys, xs = np.nonzero(self._cyan(self.render(yaw=0.0)))
            return float(xs.mean()) if xs.size else 0.0

        gauche = barycentre_x(FaceState().with_gaze(-1.0, 0.0))
        droite = barycentre_x(FaceState().with_gaze(1.0, 0.0))
        self.scene.draw_outline = self.scene.draw_shadow = True
        self.scene.face_state = FaceState()
        self.assertLess(gauche, droite,
                        "un regard vers la gauche doit déplacer les pupilles à gauche")


class FaceStateTest(unittest.TestCase):
    """Le mélange d'expressions, sans GPU."""

    def test_lerp_aux_bornes(self) -> None:
        a = EXPRESSIONS["neutre"]
        b = EXPRESSIONS["joyeux"]
        self.assertEqual(a.lerp(b, 0.0), a)
        self.assertEqual(a.lerp(b, 1.0), b)

    def test_lerp_borne_le_parametre(self) -> None:
        a, b = EXPRESSIONS["neutre"], EXPRESSIONS["fache"]
        self.assertEqual(a.lerp(b, -3.0), a)
        self.assertEqual(a.lerp(b, 9.0), b)

    def test_lerp_au_milieu(self) -> None:
        a = FaceState(blink=0.0, pupil_scale=1.0)
        b = FaceState(blink=1.0, pupil_scale=2.0)
        m = a.lerp(b, 0.5)
        self.assertAlmostEqual(m.blink, 0.5)
        self.assertAlmostEqual(m.pupil_scale, 1.5)

    def test_with_gaze_ne_touche_que_le_regard(self) -> None:
        base = EXPRESSIONS["joyeux"]
        moved = base.with_gaze(0.5, -0.25)
        self.assertEqual((moved.gaze_x, moved.gaze_y), (0.5, -0.25))
        self.assertEqual(moved.squint, base.squint)
        self.assertEqual(moved.pupil_scale, base.pupil_scale)

    def test_les_expressions_restent_dans_des_bornes_saines(self) -> None:
        for name, s in EXPRESSIONS.items():
            self.assertTrue(0.0 <= s.blink <= 1.0, name)
            self.assertTrue(0.0 <= s.squint <= 1.0, name)
            self.assertTrue(0.0 <= s.glitch <= 1.0, name)
            self.assertTrue(0.5 <= s.pupil_scale <= 2.0, name)
            self.assertTrue(-0.5 <= s.lid_top <= 1.0, name)
            self.assertTrue(-0.5 <= s.lid_bottom <= 1.0, name)

    def test_l_expression_neutre_est_l_etat_par_defaut(self) -> None:
        self.assertEqual(EXPRESSIONS["neutre"], FaceState())


if __name__ == "__main__":
    unittest.main()
