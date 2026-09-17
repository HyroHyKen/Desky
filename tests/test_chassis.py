"""Critères d'acceptation du châssis monobloc, lot L17 (CDC §7, §10).

Un second châssis a une propriété désagréable : **il double silencieusement la
surface de tout ce qui touche à la géométrie**. La dalle faciale, les oreilles,
les chapeaux et la respiration étaient réglés sur une tête posée sur un corps ;
aucun d'eux ne signale qu'il est devenu faux, ils se contentent d'être un peu
moins bien placés — ou de disparaître.

C'est exactement ce qui est arrivé pendant l'écriture du lot : sur les génomes
dont l'effilement élargit le haut, la dalle s'enfonçait entièrement dans la
coque et le robot n'avait plus de visage. Le défaut ne se voyait que sur trois
génomes de la planche de contact, et pas du tout dans le code. D'où le poids
donné ici à ce qui se mesure sur la géométrie assemblée plutôt qu'à ce qui se
relit.
"""

from __future__ import annotations

import unittest

import numpy as np

from pet.anim.layers import (MAX_MONOBLOC_PITCH, MAX_MONOBLOC_YAW,
                             MONOBLOC_TRANSFER, apply_channels)
from pet.anim.rig_pose import RigPose
from pet.genome import generator, migration
from pet.genome.schema import CHASSIS, PARAMS, PARAMS_BY_KEY, defaults
from pet.geometry import proportions
from pet.geometry.builder import build

GRAINES = (11, 23, 47, 88, 101, 233, 512, 777, 1234, 4242)


def _genome(seed: int, chassis: str) -> dict:
    """Le même robot, monté sur l'un ou l'autre châssis."""
    g = generator.generate(seed)
    g["chassis"] = chassis
    if chassis == "monobloc" and g["ear.type"] == "antenna":
        g["ear.type"] = "disc"
    return g


def _monde(robot, nom: str) -> np.ndarray:
    """Sommets d'une partie, en coordonnées du robot au repos."""
    matrices = {part.name: m for part, m in robot.part_matrices()}
    part = next(p for p in robot.parts if p.name == nom)
    v = part.mesh.positions
    return (matrices[nom] @ np.c_[v, np.ones(len(v))].T).T[:, :3]


class SchemaTest(unittest.TestCase):
    def test_le_chassis_est_le_dernier_parametre(self) -> None:
        """`generator.draw` consomme le PRNG dans l'ordre de `PARAMS` : un
        paramètre inséré ailleurs qu'à la fin décalerait tous les tirages
        suivants, et chaque graine donnerait un autre robot."""
        self.assertEqual(PARAMS[-1].key, "chassis")

    def test_le_repli_est_la_capsule(self) -> None:
        """C'est ce qui fait qu'une sauvegarde d'avant le lot garde son robot :
        le paramètre manquant est complété par le défaut, et le défaut d'un
        `Choice` est son option dominante."""
        self.assertEqual(PARAMS_BY_KEY["chassis"].default, "capsule")

    def test_une_sauvegarde_d_avant_le_lot_reste_une_capsule(self) -> None:
        ancien = {k: v for k, v in defaults().items() if k != "chassis"}
        ancien["head.radius"] = 1.21          # un trait reconnaissable
        migre = migration.migrate(ancien, from_version=1)
        self.assertEqual(migre["chassis"], "capsule")
        self.assertAlmostEqual(migre["head.radius"], 1.21,
                               msg="la migration a touché un trait existant")


class CoherenceTest(unittest.TestCase):
    def test_un_monobloc_n_a_jamais_d_antenne(self) -> None:
        """Une tige plantée dans un bloc sans tête distincte ne se lit pas
        comme une oreille mais comme une erreur de montage."""
        vus = 0
        for seed in range(400):
            g = generator.generate(seed)
            if g["chassis"] == "monobloc":
                vus += 1
                self.assertNotEqual(g["ear.type"], "antenna", "graine %d" % seed)
        self.assertGreater(vus, 20, "trop peu de monoblocs tirés pour conclure")

    def test_la_regle_rejette_bien(self) -> None:
        mauvais = defaults()
        mauvais["chassis"] = "monobloc"
        mauvais["ear.type"] = "antenna"
        self.assertIn("monobloc_avec_antenne",
                      generator.viability_issues(mauvais))

    def test_les_deux_chassis_sortent_du_tirage(self) -> None:
        tires = {generator.generate(s)["chassis"] for s in range(200)}
        self.assertEqual(tires, set(CHASSIS))

    def test_le_taux_d_acceptation_reste_praticable(self) -> None:
        """La nouvelle règle rejette environ un tirage sur neuf ; elle ne doit
        pas pour autant vider le nuage morphologique."""
        rate, reasons = generator.acceptance_rate(2000)
        self.assertGreater(rate, 0.40, "taux trop bas : %s" % reasons)
        self.assertIn("monobloc_avec_antenne", reasons)


class GeometrieTest(unittest.TestCase):
    def test_le_monobloc_est_d_un_seul_tenant(self) -> None:
        """Une seule pièce de coque, ni cou ni tête : c'est la définition."""
        for seed in GRAINES:
            robot = build(_genome(seed, "monobloc"))
            noms = {p.name for p in robot.parts}
            self.assertIn("shell", noms, "graine %d" % seed)
            self.assertNotIn("neck", noms, "graine %d" % seed)
            self.assertNotIn("head", noms, "graine %d" % seed)
            self.assertNotIn("body", noms, "graine %d" % seed)

    def test_la_capsule_est_inchangee(self) -> None:
        """Le lot ne doit rien avoir bougé pour les robots existants."""
        for seed in GRAINES:
            noms = {p.name for p in build(_genome(seed, "capsule")).parts}
            self.assertIn("body", noms)
            self.assertIn("head", noms)
            self.assertNotIn("shell", noms)

    def test_la_coque_pose_au_sol(self) -> None:
        """Un robot qui flotte ou qui s'enfonce se remarque immédiatement."""
        for seed in GRAINES:
            bas = _monde(build(_genome(seed, "monobloc")), "shell")[:, 1].min()
            self.assertAlmostEqual(bas, 0.0, places=2, msg="graine %d" % seed)

    def test_la_dalle_depasse_de_la_coque(self) -> None:
        """**La régression du lot.** La dalle est un morceau de la surface de la
        coque, légèrement gonflé. Si elle ne suit pas la même déformation —
        l'effilement, en l'occurrence — elle s'enfonce dedans et le robot perd
        purement et simplement son visage.

        Mesuré et non relu : on compare la profondeur de la dalle à celle de la
        coque **à la même hauteur**.
        """
        for seed in GRAINES:
            robot = build(_genome(seed, "monobloc"))
            coque, dalle = _monde(robot, "shell"), _monde(robot, "face")
            y = float(dalle[:, 1].mean())
            # Fenêtre élargie jusqu'à capturer de la matière : les anneaux de
            # sommets de la coque sont espacés, et une fenêtre fixe tombe parfois
            # entre deux. C'est un artefact de la sonde, pas du produit — mais il
            # ferait échouer le test sur une géométrie parfaitement saine.
            voisins = coque[:0]
            fenetre = 0.08
            while len(voisins) < 8 and fenetre < 1.0:
                voisins = coque[np.abs(coque[:, 1] - y) < fenetre]
                fenetre *= 1.6
            self.assertGreater(len(voisins), 0, "graine %d : coque trop creuse" % seed)
            self.assertGreater(
                float(dalle[:, 2].max()), float(voisins[:, 2].max()),
                "graine %d : la dalle est enterrée dans la coque" % seed)

    def test_la_dalle_est_haute_sur_le_bloc(self) -> None:
        """Un bloc qui regarde depuis son milieu n'a pas un visage, il a un
        hublot."""
        for seed in GRAINES:
            robot = build(_genome(seed, "monobloc"))
            coque, dalle = _monde(robot, "shell"), _monde(robot, "face")
            part = float(dalle[:, 1].mean()) / float(coque[:, 1].max())
            self.assertGreater(part, 0.60, "graine %d : visage trop bas" % seed)
            self.assertLess(part, 0.92, "graine %d : visage sur le crâne" % seed)


class RegardTest(unittest.TestCase):
    """Ce qui tourne quand un monobloc regarde le curseur."""

    def _pose(self, chassis: str, channels: dict):
        robot = build(_genome(11, chassis))
        pose = RigPose(robot.rig, robot.base_pose)
        apply_channels(pose, channels, robot.dims)
        return pose

    def test_le_monobloc_tourne_du_corps_et_non_de_la_dalle(self) -> None:
        """Faire pivoter le nœud `head` n'y tournerait que la dalle, qui épouse
        la surface du bloc et s'en décollerait aussitôt."""
        pose = self._pose("monobloc", {"head.yaw": 0.5})
        self.assertAlmostEqual(float(pose.rig.nodes["head"].rotation[1]), 0.0,
                               places=5)
        self.assertAlmostEqual(float(pose.rig.nodes["body"].rotation[1]),
                               0.5 * MONOBLOC_TRANSFER, places=5)

    def test_la_capsule_tourne_toujours_de_la_tete(self) -> None:
        pose = self._pose("capsule", {"head.yaw": 0.5})
        self.assertAlmostEqual(float(pose.rig.nodes["head"].rotation[1]), 0.5,
                               places=5)

    def test_le_bloc_ne_bascule_pas(self) -> None:
        """Un bloc qui pivoterait autant qu'une tête ne se lit pas comme un
        regard mais comme une chute."""
        pose = self._pose("monobloc", {"head.yaw": 3.0, "head.pitch": 3.0,
                                       "body.yaw": 1.0, "body.pitch": 1.0})
        self.assertLessEqual(abs(float(pose.rig.nodes["body"].rotation[1])),
                             MAX_MONOBLOC_YAW + 1e-6)
        self.assertLessEqual(abs(float(pose.rig.nodes["body"].rotation[0])),
                             MAX_MONOBLOC_PITCH + 1e-6)


class RespirationTest(unittest.TestCase):
    """L'écrasement du lot L10, sur un maillage qui n'a plus la même hauteur."""

    def _pieds(self, chassis: str, flex: float) -> float:
        robot = build(_genome(11, chassis))
        pose = RigPose(robot.rig, robot.base_pose)
        apply_channels(pose, {"body.flex": flex}, robot.dims)
        nom = "shell" if chassis == "monobloc" else "body"
        matrices = {p.name: m for p, m in robot.part_matrices()}
        part = next(p for p in robot.parts if p.name == nom)
        v = part.mesh.positions
        monde = (matrices[nom] @ np.c_[v, np.ones(len(v))].T).T[:, :3]
        return float(monde[:, 1].min())

    def test_les_pieds_restent_plantes_sur_les_deux_chassis(self) -> None:
        """La compensation qui replante les pieds est calée sur la demi-hauteur
        du maillage porteur. Elle vaut donc autre chose pour une coque que pour
        un corps, et l'oublier ferait s'enfoncer le robot dans le sol."""
        for chassis in CHASSIS:
            for flex in (-0.12, -0.05, 0.08):
                self.assertAlmostEqual(
                    self._pieds(chassis, flex), 0.0, places=2,
                    msg="%s, flex %.2f" % (chassis, flex))

    def test_le_visage_ne_glisse_pas_sur_le_bloc(self) -> None:
        """Ce que `carrier_top` sert vraiment à tenir.

        La dalle est portée par `face`, qui pend sous `neck` — un nœud que
        l'échelle de `body_flex` n'atteint pas. Sa remontée doit donc être
        recopiée à la main, et la hauteur à recopier n'est pas la même selon le
        châssis. Se tromper ne déplace pas les pieds, donc le test précédent ne
        le voit pas : ça fait **glisser le visage sur la coque** à chaque
        atterrissage, ce qui se mesure ici en écart au sommet.
        """
        for chassis in CHASSIS:
            nom = "shell" if chassis == "monobloc" else "head"
            ecarts = []
            for flex in (0.0, -0.10, 0.09):
                robot = build(_genome(11, chassis))
                pose = RigPose(robot.rig, robot.base_pose)
                apply_channels(pose, {"body.flex": flex}, robot.dims)
                matrices = {p.name: m for p, m in robot.part_matrices()}
                haut = {}
                for cible in (nom, "face"):
                    part = next(p for p in robot.parts if p.name == cible)
                    v = part.mesh.positions
                    monde = (matrices[cible] @ np.c_[v, np.ones(len(v))].T).T[:, :3]
                    haut[cible] = float(monde[:, 1].max())
                ecarts.append(haut[nom] - haut["face"])
            self.assertAlmostEqual(
                max(ecarts), min(ecarts), places=2,
                msg="%s : le visage glisse de %.3f sous l'écrasement"
                    % (chassis, max(ecarts) - min(ecarts)))

    def test_le_sommet_porteur_suit_le_chassis(self) -> None:
        capsule = proportions.dimensions(_genome(11, "capsule"))
        mono = proportions.dimensions(_genome(11, "monobloc"))
        self.assertAlmostEqual(capsule.carrier_top, 2.0 * capsule.body_b)
        self.assertAlmostEqual(mono.carrier_top, 2.0 * mono.shell_b)
        self.assertGreater(mono.carrier_top, capsule.carrier_top)


if __name__ == "__main__":
    unittest.main()
