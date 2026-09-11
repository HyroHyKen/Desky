"""Critères d'acceptation de l'animation, lot L4 (CDC §10).

Quatre propriétés y sont vérifiées mécaniquement :

- **Aucune interpolation linéaire sur un mouvement visible.** Mesuré sur le
  profil de vitesse : une interpolation linéaire a une vitesse constante, donc
  une variation nulle. Toute courbe et tout easing doivent varier.
- **Les ressorts sont exacts à tout `dt`.** La cadence du projet passe de 30 à
  10 fps selon le régime (CDC §3) : si le ressort dépendait du pas, l'animation
  changerait avec le régime.
- **Les bornes du §10.2** — ±55° en lacet, ±35° en tangage — et l'étagement des
  vitesses : pupilles avant tête, corps en dernier.
- **Le pet reste intéressant sans interaction.** Proxy mécanique et non
  jugement : on exige que la pose continue de changer et qu'aucun canal ne se
  fige, sur 120 secondes simulées.

Aucun GPU n'est nécessaire : le rig et les canaux sont du calcul pur.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from pet.anim import layers
from pet.anim.layers import (
    ACTION_DAMPING,
    ACTIONS,
    MAX_BODY_YAW,
    MAX_HEAD_PITCH,
    MAX_HEAD_YAW,
    ActionLayer,
    AnimContext,
    Animator,
    IdleLayer,
    LookAtLayer,
    apply_channels,
)
from pet.anim.rig_pose import (
    CHANNELS,
    EASINGS,
    Key,
    PoseCurve,
    RigPose,
    Spring,
    add_channels,
    zero_channels,
)
from pet.genome.generator import generate
from pet.geometry.builder import build


def _velocity_variation(fn, n: int = 60) -> float:
    """Variation relative de la vitesse d'une courbe sur [0, 1].

    Zéro pour une interpolation linéaire, strictement positif sinon. C'est la
    mesure qui permet de vérifier l'exigence du §10 sans juger à l'œil.
    """
    h = 1.0 / n
    speeds = [(fn(min(1.0, t + h)) - fn(t)) / h for t in np.linspace(0.0, 1.0 - h, n)]
    mean = sum(speeds) / len(speeds)
    if abs(mean) < 1e-12:
        return float("inf")
    return (max(speeds) - min(speeds)) / abs(mean)


class SpringTest(unittest.TestCase):
    def test_exact_quel_que_soit_le_pas(self) -> None:
        """Même trajectoire à 10 fps et à 30 fps.

        Sans quoi le changement de régime du lot L1 modifierait le mouvement.
        """
        def value_at(dt: float, upto: float) -> float:
            s = Spring(0.0, omega=10.0, zeta=1.0)
            for _ in range(round(upto / dt)):
                s.step(1.0, dt)
            return float(s.value)

        for upto in (0.2, 0.5, 1.0):
            fine = value_at(0.001, upto)
            for dt in (1 / 60, 1 / 30, 1 / 10):
                self.assertAlmostEqual(value_at(dt, upto), fine, places=9,
                                       msg=f"dt={dt} à t={upto}")

    def test_stable_sur_un_pas_enorme(self) -> None:
        """Un réveil tardif ne doit pas faire exploser le ressort."""
        for dt in (0.5, 1.0, 5.0):
            s = Spring(0.0, omega=18.0, zeta=0.55)
            for _ in range(40):
                s.step(1.0, dt)
            self.assertAlmostEqual(float(s.value), 1.0, places=5, msg=f"dt={dt}")
            self.assertTrue(math.isfinite(float(s.velocity)))

    def test_sous_amorti_depasse(self) -> None:
        """Le §10 demande un léger dépassement à l'arrivée."""
        s = Spring(0.0, omega=12.0, zeta=0.45)
        peak = 0.0
        for _ in range(400):
            peak = max(peak, float(s.step(1.0, 1 / 120)))
        self.assertGreater(peak, 1.02, "un ressort sous-amorti doit dépasser")
        self.assertLess(peak, 1.5, "mais pas rebondir comme un ballon")

    def test_critique_ne_depasse_pas(self) -> None:
        s = Spring(0.0, omega=12.0, zeta=1.0)
        peak = max(float(s.step(1.0, 1 / 120)) for _ in range(400))
        self.assertLessEqual(peak, 1.0 + 1e-6)

    def test_sur_amorti_traine(self) -> None:
        rapide = Spring(0.0, omega=12.0, zeta=1.0)
        lent = Spring(0.0, omega=12.0, zeta=2.5)
        for _ in range(30):
            rapide.step(1.0, 1 / 60)
            lent.step(1.0, 1 / 60)
        self.assertGreater(float(rapide.value), float(lent.value))

    def test_vectoriel(self) -> None:
        s = Spring(np.zeros(3), omega=10.0, zeta=1.0)
        cible = np.array([1.0, -2.0, 0.5])
        for _ in range(200):
            s.step(cible, 1 / 60)
        np.testing.assert_allclose(s.value, cible, atol=1e-4)

    def test_pas_nul_ne_change_rien(self) -> None:
        s = Spring(0.3, omega=10.0, zeta=1.0)
        self.assertEqual(s.step(1.0, 0.0), 0.3)
        self.assertEqual(s.step(1.0, -1.0), 0.3)


class EasingTest(unittest.TestCase):
    def test_aucun_easing_n_est_lineaire(self) -> None:
        """Exigence explicite du CDC §10."""
        for name, fn in EASINGS.items():
            variation = _velocity_variation(fn)
            self.assertGreater(variation, 0.2,
                               f"{name} a une vitesse trop constante ({variation:.3f})")

    def test_bornes_respectees(self) -> None:
        for name, fn in EASINGS.items():
            self.assertAlmostEqual(fn(0.0), 0.0, places=6, msg=name)
            self.assertAlmostEqual(fn(1.0), 1.0, places=6, msg=name)

    def test_anticipation_recule_avant_de_partir(self) -> None:
        self.assertLess(EASINGS["in_back"](0.12), 0.0,
                        "l'anticipation doit passer sous zéro")

    def test_depassement_franchit_la_cible(self) -> None:
        for name in ("out_back", "out_elastic"):
            peak = max(EASINGS[name](t) for t in np.linspace(0, 1, 200))
            self.assertGreater(peak, 1.02, name)


class PoseCurveTest(unittest.TestCase):
    def test_les_courbes_du_cdc_existent(self) -> None:
        """CDC §10.3 : sit, stand, yawn, look_around, poke_reaction, sleep, celebrate."""
        attendues = {"sit", "stand", "yawn", "look_around", "poke_reaction",
                     "sleep", "celebrate"}
        self.assertTrue(attendues.issubset(set(ACTIONS)),
                        f"manquantes : {attendues - set(ACTIONS)}")

    def test_toutes_les_courbes_sont_valides(self) -> None:
        for name, curve in ACTIONS.items():
            self.assertEqual(curve.name, name)
            self.assertGreater(curve.duration, 0.0, name)
            for key in curve.keys:
                self.assertIn(key.ease, EASINGS, f"{name} : {key.ease}")
                for channel in key.values:
                    self.assertIn(channel, CHANNELS, f"{name} : {channel}")

    def test_aucun_segment_n_est_lineaire(self) -> None:
        """Chaque segment de chaque action doit porter un easing non linéaire."""
        for name, curve in ACTIONS.items():
            for key in curve.keys[1:]:
                variation = _velocity_variation(EASINGS[key.ease])
                self.assertGreater(variation, 0.2,
                                   f"{name} : segment vers t={key.t} trop linéaire")

    def test_les_mouvements_marques_ont_anticipation_ou_depassement(self) -> None:
        """Le §10 exige « anticipation avant les mouvements marqués et léger
        dépassement à l'arrivée ». Vérifié sur les actions les plus franches."""
        for name in ("poke_reaction", "celebrate", "sit", "stand", "look_around"):
            eases = {k.ease for k in ACTIONS[name].keys}
            self.assertTrue(eases & {"in_back", "out_back", "out_elastic"},
                            f"{name} n'a ni anticipation ni dépassement : {eases}")

    def test_echantillonnage_aux_bornes(self) -> None:
        curve = ACTIONS["poke_reaction"]
        self.assertEqual(curve.sample(-1.0), dict(curve.keys[0].values))
        self.assertEqual(curve.sample(curve.duration + 5.0),
                         dict(curve.keys[-1].values))

    def test_echantillonnage_continu(self) -> None:
        """Pas de saut : deux instants voisins donnent des valeurs voisines."""
        for name, curve in ACTIONS.items():
            prev = curve.sample(0.0)
            for t in np.linspace(0.0, curve.duration, 400)[1:]:
                cur = curve.sample(float(t))
                for channel in set(prev) | set(cur):
                    saut = abs(cur.get(channel, 0.0) - prev.get(channel, 0.0))
                    self.assertLess(saut, 0.25, f"{name} : saut sur {channel} à t={t:.3f}")
                prev = cur

    def test_courbe_invalide_refusee(self) -> None:
        with self.assertRaises(ValueError):
            PoseCurve("une_cle", (Key(0.0, {}),))
        with self.assertRaises(ValueError):
            PoseCurve("desordre", (Key(0.0, {}), Key(0.5, {}), Key(0.2, {})))
        with self.assertRaises(ValueError):
            PoseCurve("tardive", (Key(0.3, {}), Key(0.9, {})))
        with self.assertRaises(ValueError):
            PoseCurve("ease", (Key(0.0, {}), Key(0.5, {}, ease="lineaire")))
        with self.assertRaises(ValueError):
            PoseCurve("canal", (Key(0.0, {}), Key(0.5, {"tail.wag": 1.0})))


class RigPoseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.robot = build(generate(8))
        self.pose = RigPose(self.robot.rig)

    def test_la_pose_de_base_n_est_pas_detruite(self) -> None:
        """Animer une translation ne doit pas altérer la morphologie.

        Les translations du rig **sont** la morphologie : c'est là que le lot L2
        a encodé les proportions issues du génome.
        """
        base = self.pose.base_translation("neck").copy()
        for _ in range(5):
            self.pose.offset("neck", translation=(0.0, 0.05, 0.0))
            self.pose.apply()
        self.pose.restore()
        np.testing.assert_allclose(self.robot.rig["neck"].translation, base, atol=1e-6)

    def test_les_offsets_s_accumulent(self) -> None:
        self.pose.reset()
        self.pose.offset("head", rotation=(0.1, 0.0, 0.0))
        self.pose.offset("head", rotation=(0.2, 0.0, 0.0))
        self.pose.apply()
        self.assertAlmostEqual(float(self.robot.rig["head"].rotation[0]), 0.3, places=5)

    def test_un_noeud_absent_est_ignore(self) -> None:
        """Un robot sans oreilles ne doit pas faire échouer une couche."""
        genome = dict(self.robot.genome)
        genome["ear.type"] = "none"
        robot = build(genome)
        pose = RigPose(robot.rig)
        pose.offset("ear_l", rotation=(0.0, 0.0, 0.4))       # ne doit pas lever
        pose.apply()

    def test_l_echelle_est_multiplicative(self) -> None:
        self.pose.reset()
        self.pose.offset("body_flex", scale=(1.0, 1.1, 1.0))
        self.pose.offset("body_flex", scale=(1.0, 1.1, 1.0))
        self.pose.apply()
        self.assertAlmostEqual(float(self.robot.rig["body_flex"].scale[1]),
                               1.21, places=4)


class BreathingTest(unittest.TestCase):
    """La respiration ne doit déformer que le corps (CDC §10.1)."""

    def setUp(self) -> None:
        self.robot = build(generate(8))
        self.pose = RigPose(self.robot.rig)

    def _world_span(self, part_name: str) -> tuple[float, float]:
        part = next(p for p in self.robot.parts if p.name == part_name)
        matrix = self.robot.rig.world_matrices()[part.node] @ part.offset_matrix()
        pos = part.mesh.positions
        homo = np.hstack([pos, np.ones((len(pos), 1), dtype="f4")])
        world = (matrix @ homo.T).T[:, :3]
        return float(world[:, 1].min()), float(world[:, 1].max())

    def test_les_pieds_restent_plantes(self) -> None:
        for flex in (-0.05, -0.02, 0.0, 0.02, 0.05):
            channels = zero_channels()
            channels["body.flex"] = flex
            apply_channels(self.pose, channels, self.robot.dims)
            bas, _ = self._world_span("body")
            self.assertAlmostEqual(bas, 0.0, places=5, msg=f"flex={flex}")

    def test_la_tete_ne_s_etire_pas(self) -> None:
        """L'échelle d'un nœud se propage : sans `body_flex`, la tête gonflerait."""
        hauteurs = []
        for flex in (-0.05, 0.0, 0.05):
            channels = zero_channels()
            channels["body.flex"] = flex
            apply_channels(self.pose, channels, self.robot.dims)
            bas, haut = self._world_span("head")
            hauteurs.append(haut - bas)
        self.assertAlmostEqual(hauteurs[0], hauteurs[1], places=6)
        self.assertAlmostEqual(hauteurs[1], hauteurs[2], places=6)

    def test_la_tete_monte_avec_la_poitrine(self) -> None:
        positions = []
        for flex in (-0.04, 0.0, 0.04):
            channels = zero_channels()
            channels["body.flex"] = flex
            apply_channels(self.pose, channels, self.robot.dims)
            _, haut = self._world_span("head")
            positions.append(haut)
        self.assertLess(positions[0], positions[1])
        self.assertLess(positions[1], positions[2])


class LookAtTest(unittest.TestCase):
    def _settle(self, layer: LookAtLayer, ctx: AnimContext,
                seconds: float = 4.0) -> dict[str, float]:
        out: dict[str, float] = {}
        for _ in range(int(seconds * 120)):
            out = layer.update(1 / 120, ctx)
        return out

    def test_bornes_du_cdc(self) -> None:
        """±55° en lacet, ±35° en tangage, corps borné aussi."""
        for dx, dy in ((60.0, 60.0), (-60.0, -60.0)):
            layer = LookAtLayer()
            ctx = AnimContext(look_offset=(dx, dy))
            out = self._settle(layer, ctx)
            self.assertLessEqual(abs(out["head.yaw"]), MAX_HEAD_YAW + 1e-6)
            self.assertLessEqual(abs(out["head.pitch"]), MAX_HEAD_PITCH + 1e-6)
            self.assertLessEqual(abs(out["body.yaw"]), MAX_BODY_YAW + 1e-6)

    def test_le_pet_suit_le_bon_cote(self) -> None:
        droite = self._settle(LookAtLayer(), AnimContext(look_offset=(1.2, 0.0)))
        gauche = self._settle(LookAtLayer(), AnimContext(look_offset=(-1.2, 0.0)))
        self.assertGreater(droite["head.yaw"], 0.05)
        self.assertLess(gauche["head.yaw"], -0.05)
        self.assertGreater(droite["face.gaze_x"], 0.05)
        self.assertLess(gauche["face.gaze_x"], -0.05)

    def test_les_pupilles_arrivent_avant_la_tete(self) -> None:
        """CDC §10.2, littéralement.

        Comparé en fraction de course parcourue, les deux n'ayant pas la même
        amplitude : la question est qui arrive le premier, pas qui va le plus loin.
        """
        layer = LookAtLayer()
        ctx = AnimContext(look_offset=(1.4, 0.0))
        final = self._settle(LookAtLayer(), ctx)

        gaze_done = head_done = None
        t = 0.0
        for _ in range(600):
            out = layer.update(1 / 120, ctx)
            t += 1 / 120
            if gaze_done is None and out["face.gaze_x"] >= 0.9 * final["face.gaze_x"]:
                gaze_done = t
            if head_done is None and out["head.yaw"] >= 0.9 * final["head.yaw"]:
                head_done = t
        self.assertIsNotNone(gaze_done)
        self.assertIsNotNone(head_done)
        self.assertLess(gaze_done, head_done,
                        "les pupilles doivent atteindre la cible avant la tête")

    def test_le_corps_traine_derriere_la_tete(self) -> None:
        """« Au-delà, le corps pivote avec retard » (CDC §10.2)."""
        layer = LookAtLayer()
        ctx = AnimContext(look_offset=(6.0, 0.0))
        final = self._settle(LookAtLayer(), ctx)
        self.assertGreater(final["body.yaw"], 0.02, "le corps doit prendre le relais")

        layer = LookAtLayer()
        head_done = body_done = None
        t = 0.0
        for _ in range(900):
            out = layer.update(1 / 120, ctx)
            t += 1 / 120
            if head_done is None and out["head.yaw"] >= 0.9 * final["head.yaw"]:
                head_done = t
            if body_done is None and out["body.yaw"] >= 0.9 * final["body.yaw"]:
                body_done = t
        self.assertLess(head_done, body_done, "la tête doit arriver avant le corps")

    def test_le_corps_ne_bouge_pas_pour_une_cible_proche(self) -> None:
        """Tant que la tête suffit, le corps reste immobile."""
        final = self._settle(LookAtLayer(), AnimContext(look_offset=(0.5, 0.0)))
        self.assertLess(abs(final["body.yaw"]), 1e-3)

    def test_le_curseur_lointain_n_interesse_plus(self) -> None:
        layer = LookAtLayer()
        self._settle(layer, AnimContext(look_offset=(0.5, 0.0)))
        proche = layer.interest
        self._settle(layer, AnimContext(look_offset=(20.0, 0.0)))
        self.assertGreater(proche, 0.5)
        self.assertAlmostEqual(layer.interest, 0.0, places=6)

    def test_sans_cible_tout_revient_au_repos(self) -> None:
        layer = LookAtLayer()
        self._settle(layer, AnimContext(look_offset=(2.0, 1.0)))
        out = self._settle(layer, AnimContext(look_offset=None), seconds=6.0)
        for channel in ("head.yaw", "head.pitch", "body.yaw",
                        "face.gaze_x", "face.gaze_y"):
            self.assertAlmostEqual(out[channel], 0.0, places=4, msg=channel)

    def test_mouvement_progressif_et_non_instantane(self) -> None:
        """Un ressort ne saute pas : la première image ne doit pas tout faire."""
        layer = LookAtLayer()
        ctx = AnimContext(look_offset=(1.4, 0.0))
        premier = layer.update(1 / 30, ctx)["head.yaw"]
        final = self._settle(LookAtLayer(), ctx)["head.yaw"]
        self.assertLess(premier, 0.35 * final,
                        "la tête ne doit pas se téléporter en une image")


class ActionLayerTest(unittest.TestCase):
    def test_une_action_se_termine_seule(self) -> None:
        layer = ActionLayer()
        layer.play("poke_reaction")
        duree = ACTIONS["poke_reaction"].duration
        for _ in range(int((duree + 1.5) * 120)):
            layer.update(1 / 120)
        self.assertIsNone(layer.name, "l'action doit s'être terminée")

    def test_les_actions_soutenues_tiennent_leur_pose(self) -> None:
        for name in ("sit", "sleep"):
            layer = ActionLayer()
            layer.play(name)
            for _ in range(int(12.0 * 60)):
                layer.update(1 / 60)
            self.assertEqual(layer.name, name, f"{name} doit se maintenir")

    def test_stop_termine_une_action_soutenue(self) -> None:
        layer = ActionLayer()
        layer.play("sleep")
        for _ in range(120):
            layer.update(1 / 60)
        layer.stop()
        for _ in range(120):
            layer.update(1 / 60)
        self.assertIsNone(layer.name)

    def test_le_poids_monte_et_descend_en_fondu(self) -> None:
        """Une action ne doit ni apparaître ni disparaître d'un coup."""
        layer = ActionLayer()
        layer.play("celebrate")
        poids = [layer.update(1 / 120)[1] for _ in range(int(2.5 * 120))]
        self.assertLess(poids[0], 0.2, "pas d'apparition brutale")
        self.assertGreater(max(poids), 0.95)
        self.assertLess(poids[-1], 0.2, "pas de disparition brutale")

    def test_dormir_coupe_le_suivi_du_curseur(self) -> None:
        """Sinon le pet suit la souris les yeux fermés."""
        layer = ActionLayer()
        layer.play("sleep")
        for _ in range(int(1.0 * 120)):
            _, _, (damp_look, _) = layer.update(1 / 120)
        self.assertGreater(damp_look, 0.9)

    def test_s_asseoir_laisse_le_regard_libre(self) -> None:
        layer = ActionLayer()
        layer.play("sit")
        for _ in range(int(1.0 * 120)):
            _, _, (damp_look, _) = layer.update(1 / 120)
        self.assertLess(damp_look, 0.3)

    def test_toutes_les_actions_ont_une_attenuation_declaree(self) -> None:
        for name in ACTIONS:
            self.assertIn(name, ACTION_DAMPING, name)

    def test_action_inconnue_refusee(self) -> None:
        with self.assertRaises(KeyError):
            ActionLayer().play("danser_la_gigue")


class IdleTest(unittest.TestCase):
    def test_la_respiration_oscille(self) -> None:
        layer = IdleLayer(seed=3)
        valeurs = [layer.update(1 / 30)["body.flex"] for _ in range(int(12 * 30))]
        a = np.array(valeurs)
        self.assertGreater(a.max(), 0.01)
        self.assertLess(a.min(), -0.01)
        self.assertLess(abs(a.mean()), 0.005, "la respiration doit être centrée")

    def test_les_clignements_sont_irreguliers(self) -> None:
        """Un rythme régulier est ce qui trahit le plus vite une boucle."""
        layer = IdleLayer(seed=5)
        instants, t = [], 0.0
        precedent = 0
        for _ in range(int(240 * 60)):
            layer.update(1 / 60)
            t += 1 / 60
            if layer.blinks != precedent:
                precedent = layer.blinks
                instants.append(t)
        self.assertGreater(len(instants), 25, "trop peu de clignements en 4 minutes")
        ecarts = np.diff(instants)
        self.assertGreater(ecarts.std(), 0.4, "les intervalles sont trop réguliers")

    def test_le_clignement_se_ferme_et_se_rouvre(self) -> None:
        layer = IdleLayer(seed=7)
        valeurs = [layer.update(1 / 120)["face.blink"] for _ in range(int(30 * 120))]
        a = np.array(valeurs)
        self.assertGreater(a.max(), 0.9, "l'œil doit se fermer complètement")
        self.assertLess(a[-1], 0.5, "et se rouvrir")

    def test_les_saccades_bougent_le_regard(self) -> None:
        layer = IdleLayer(seed=11)
        gaze = [layer.update(1 / 60)["face.gaze_x"] for _ in range(int(60 * 60))]
        a = np.array(gaze)
        self.assertGreater(a.std(), 0.02, "le regard doit vagabonder")
        self.assertLess(np.abs(a).max(), 0.5, "mais rester des micro-saccades")

    def test_deux_robots_ne_respirent_pas_a_l_unisson(self) -> None:
        a = IdleLayer(seed=1)
        b = IdleLayer(seed=2)
        va = [a.update(1 / 30)["body.flex"] for _ in range(120)]
        vb = [b.update(1 / 30)["body.flex"] for _ in range(120)]
        self.assertGreater(float(np.abs(np.array(va) - np.array(vb)).mean()), 1e-3)

    def test_le_meme_genome_rejoue_le_meme_idle(self) -> None:
        """Le rythme fait partie de l'identité du robot, donc il est reproductible."""
        a = [IdleLayer(seed=42).update(1 / 30)["body.flex"] for _ in range(60)]
        b = [IdleLayer(seed=42).update(1 / 30)["body.flex"] for _ in range(60)]
        self.assertEqual(a, b)


class AnimatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.robot = build(generate(8))
        self.animator = Animator(self.robot.rig, self.robot.dims, seed=8)

    def test_le_pet_reste_interessant_sans_interaction(self) -> None:
        """Critère d'acceptation du lot, en proxy mécanique.

        « Le robot reste intéressant à regarder plus de 60 s sans aucune
        interaction. » Ce n'est pas jugeable par un test ; on vérifie donc les
        conditions nécessaires : la pose continue de changer, plusieurs canaux
        bougent, et rien ne se figera jamais.
        """
        canaux = ("body.flex", "body.yaw", "head.roll", "face.blink",
                  "face.gaze_x", "face.gaze_y")
        traces: dict[str, list[float]] = {c: [] for c in canaux}
        pire_figement = 0
        figement = 0
        precedent = None

        pas = 1 / 30
        for _ in range(int(120 / pas)):
            self.animator.update(pas, AnimContext())
            ch = self.animator.channels
            for c in canaux:
                traces[c].append(ch[c])
            courant = tuple(round(ch[c], 4) for c in canaux)
            figement = figement + 1 if courant == precedent else 0
            pire_figement = max(pire_figement, figement)
            precedent = courant

        for c in canaux:
            self.assertGreater(float(np.std(traces[c])), 1e-4,
                               f"{c} ne bouge pas sur 120 s")
        # Ce qui compte est l'absence de figement **durable**, non l'absence de
        # deux images identiques : au sommet d'une sinusoïde la dérivée est
        # nulle, donc deux images consécutives peuvent coïncider à l'arrondi
        # près sans que rien ne soit figé. Exiger zéro testerait l'arrondi
        # flottant, pas la vie du pet.
        self.assertLess(pire_figement, 15,
                        f"pose figée {pire_figement} images d'affilée (0,5 s)")

        stats = self.animator.stats
        self.assertGreater(stats.blinks, 12, f"seulement {stats.blinks} clignements en 120 s")
        self.assertGreater(stats.saccades, 40, f"seulement {stats.saccades} saccades")

    def test_l_idle_tourne_sans_capteur_ni_comportement(self) -> None:
        """Le lot L4 ne doit dépendre ni du lot L5 ni du lot L6."""
        for _ in range(300):
            face = self.animator.update(1 / 30, None)
        self.assertIsNotNone(face)

    def test_les_couches_s_ajoutent(self) -> None:
        """Une respiration doit continuer pendant une action."""
        self.animator.play("yawn")
        flex = []
        for _ in range(int(1.5 * 60)):
            self.animator.update(1 / 60, AnimContext())
            flex.append(self.animator.channels["body.flex"])
        self.assertGreater(float(np.std(flex)), 1e-4,
                           "la respiration s'est arrêtée pendant l'action")

    def test_dormir_immobilise_la_tete_malgre_le_curseur(self) -> None:
        ctx = AnimContext(look_offset=(2.0, 0.0), action="sleep")
        for _ in range(int(3.0 * 60)):
            self.animator.update(1 / 60, ctx)
        self.assertLess(abs(self.animator.channels["head.yaw"]), 0.10)

    def test_l_etat_de_visage_reste_dans_les_bornes(self) -> None:
        for action in ACTIONS:
            animator = Animator(self.robot.rig, self.robot.dims, seed=1)
            animator.play(action)
            ctx = AnimContext(look_offset=(1.5, -0.8))
            for _ in range(int(4.0 * 60)):
                face = animator.update(1 / 60, ctx)
                self.assertTrue(0.0 <= face.blink <= 1.0, action)
                self.assertTrue(0.0 <= face.squint <= 1.0, action)
                self.assertTrue(0.5 <= face.pupil_scale <= 2.0, action)
                self.assertTrue(-1.0 <= face.gaze_x <= 1.0, action)
                self.assertTrue(-1.0 <= face.gaze_y <= 1.0, action)

    def test_le_rig_reste_fini(self) -> None:
        ctx = AnimContext(look_offset=(3.0, 2.0))
        for action in ACTIONS:
            self.animator.play(action)
            for _ in range(int(3.0 * 60)):
                self.animator.update(1 / 60, ctx)
            for name, node in self.robot.rig.nodes.items():
                for field in (node.translation, node.rotation, node.scale):
                    self.assertTrue(np.isfinite(field).all(), f"{action}/{name}")

    def test_meme_animation_a_10_et_a_30_fps(self) -> None:
        """La cadence adaptative du lot L1 ne doit pas changer le mouvement.

        Seul le look-at est comparé : l'idle avance ses minuteries au pas de
        temps et n'a pas vocation à être identique, alors que le suivi du
        curseur, lui, est un pur ressort.
        """
        ctx = AnimContext(look_offset=(1.3, 0.4))
        a, b = LookAtLayer(), LookAtLayer()
        for _ in range(30):
            a.update(1 / 30, ctx)
        for _ in range(10):
            b.update(1 / 10, ctx)
        for channel in ("head.yaw", "head.pitch", "body.yaw"):
            self.assertAlmostEqual(a.update(0.0, ctx)[channel],
                                   b.update(0.0, ctx)[channel], places=6,
                                   msg=channel)


class PitchDirectionTest(unittest.TestCase):
    """Sens du tangage, vérifié sur la direction réelle du visage.

    Le lot L4 a livré ce sens **inversé** : la tête se baissait quand le curseur
    montait. Les tests de l'époque ne vérifiaient que les bornes du tangage, pas
    sa direction, et le défaut est passé. Ils mesurent maintenant où le visage
    pointe dans le monde, ce qui ne peut pas être satisfait par erreur.
    """

    def setUp(self) -> None:
        self.robot = build(generate(8))

    def _face_direction(self, offset, action=None) -> np.ndarray:
        """Direction du visage dans le monde, après stabilisation."""
        animator = Animator.for_robot(self.robot, seed=8)
        ctx = AnimContext(look_offset=offset, action=action)
        for _ in range(600):
            animator.update(1 / 120, ctx)
        rotation = self.robot.rig.world_matrices()["head"][:3, :3]
        direction = rotation @ np.array([0.0, 0.0, 1.0])
        return direction / np.linalg.norm(direction)

    def test_curseur_en_haut_leve_la_tete(self) -> None:
        self.assertGreater(self._face_direction((0.0, 2.0))[1], 0.2,
                           "le visage doit pointer vers le haut")

    def test_curseur_en_bas_baisse_la_tete(self) -> None:
        self.assertLess(self._face_direction((0.0, -2.0))[1], -0.2,
                        "le visage doit pointer vers le bas")

    def test_curseur_a_droite_tourne_la_tete_a_droite(self) -> None:
        self.assertGreater(self._face_direction((2.0, 0.0))[0], 0.2)

    def test_curseur_a_gauche_tourne_la_tete_a_gauche(self) -> None:
        self.assertLess(self._face_direction((-2.0, 0.0))[0], -0.2)

    def test_dormir_baisse_la_tete(self) -> None:
        """Une action de sommeil incline la tête vers le bas, pas en arrière."""
        self.assertLess(self._face_direction(None, action="sleep")[1], -0.05)

    def test_bailler_rejette_la_tete_en_arriere(self) -> None:
        """Un bâillement lève la tête. C'est le second défaut que l'inversion
        masquait : `yawn` s'inclinait du mauvais côté."""
        animator = Animator.for_robot(self.robot, seed=8)
        animator.play("yawn")
        haut = -1.0
        for _ in range(int(1.6 * 120)):
            animator.update(1 / 120, AnimContext())
            rotation = self.robot.rig.world_matrices()["head"][:3, :3]
            haut = max(haut, float((rotation @ np.array([0.0, 0.0, 1.0]))[1]))
        self.assertGreater(haut, 0.05, "le bâillement doit lever la tête")

    def test_le_canal_de_tangage_est_coherent_avec_le_rig(self) -> None:
        """Un pitch positif lève le visage, indépendamment des couches."""
        pose = RigPose(self.robot.rig, self.robot.base_pose)
        hauteurs = []
        for pitch in (-0.4, 0.0, 0.4):
            channels = zero_channels()
            channels["head.pitch"] = pitch
            apply_channels(pose, channels, self.robot.dims)
            rotation = self.robot.rig.world_matrices()["head"][:3, :3]
            hauteurs.append(float((rotation @ np.array([0.0, 0.0, 1.0]))[1]))
        self.assertLess(hauteurs[0], hauteurs[1])
        self.assertLess(hauteurs[1], hauteurs[2])


class ChannelsTest(unittest.TestCase):
    def test_superposition_additive(self) -> None:
        base = zero_channels()
        add_channels(base, {"head.yaw": 0.2})
        add_channels(base, {"head.yaw": 0.3})
        self.assertAlmostEqual(base["head.yaw"], 0.5)

    def test_poids_applique(self) -> None:
        base = zero_channels()
        add_channels(base, {"head.yaw": 1.0}, weight=0.25)
        self.assertAlmostEqual(base["head.yaw"], 0.25)

    def test_tous_les_canaux_sont_traduits_ou_documentes(self) -> None:
        """Un canal déclaré mais jamais lu serait du code mort trompeur."""
        source = (layers.apply_channels.__doc__ or "")
        import inspect
        code = inspect.getsource(layers.apply_channels)
        for channel in CHANNELS:
            self.assertIn(channel, code + source, f"{channel} n'est jamais traduit")


if __name__ == "__main__":
    unittest.main()


class ActionAnimatingTest(unittest.TestCase):
    """`animating` contre `busy` : la distinction dont dépend la cadence.

    Ajoutée après avoir mesuré un pet **endormi** qui tenait l'application à
    30 fps : `busy` dit qu'une action est chargée, pas qu'elle bouge, et les
    poses soutenues restent chargées indéfiniment.
    """

    def test_une_pose_soutenue_cesse_d_animer(self) -> None:
        from pet.anim.layers import ACTIONS, SUSTAINED, ActionLayer

        nom = sorted(SUSTAINED)[0]
        layer = ActionLayer()
        layer.play(nom)
        for _ in range(4):
            layer.update(0.1)
        self.assertTrue(layer.animating, "le fondu d'entrée est un mouvement")

        for _ in range(int(ACTIONS[nom].duration / 0.1) + 12):
            layer.update(0.1)
        self.assertTrue(layer.busy, "la pose est toujours tenue")
        self.assertFalse(layer.animating,
                         "une pose tenue ne bouge plus, donc n'exige rien")

    def test_une_action_ordinaire_anime_jusqu_a_sa_fin(self) -> None:
        from pet.anim.layers import ACTIONS, SUSTAINED, ActionLayer

        nom = next(n for n in ACTIONS if n not in SUSTAINED)
        layer = ActionLayer()
        layer.play(nom)
        vus = []
        for _ in range(int(ACTIONS[nom].duration / 0.05) + 40):
            layer.update(0.05)
            vus.append(layer.animating)
        self.assertTrue(vus[0], "elle doit animer dès le départ")
        self.assertFalse(vus[-1], "elle doit avoir fini")

    def test_sans_action_rien_n_anime(self) -> None:
        from pet.anim.layers import ActionLayer

        layer = ActionLayer()
        self.assertFalse(layer.animating)
        self.assertFalse(layer.busy)
