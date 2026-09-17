"""Critères d'acceptation du nom de modèle, lot L18 (CDC §7, §13).

La référence d'un robot a une exigence qui prime sur toutes les autres : **elle
ne doit jamais changer**. Un utilisateur la lit une fois, la retient, la donne à
un ami ; si elle bouge parce qu'il a repeint son robot ou simplement relancé
l'application, elle ne valait rien.

D'où les deux familles de tests ci-dessous : ce qui doit la laisser intacte, et
ce qui doit la faire varier. Le reste — le format, la lisibilité — se relit ;
ces deux-là ne se voient pas sans les mesurer.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter

from pet.genome.generator import generate
from pet.genome.model import (LETTRES_ECRAN, LETTRES_OREILLES, chiffre_forme,
                              libelle_famille, model_name)
from pet.genome.schema import ACCENT_COLORS, BODY_COLORS, defaults

FORMAT = re.compile(r"^[CM][1-4]-[ADIXNSG][0-9]$")


class FormatTest(unittest.TestCase):
    def test_toutes_les_references_suivent_le_format(self) -> None:
        for seed in range(500):
            nom = model_name(generate(seed))
            self.assertRegex(nom, FORMAT, "graine %d" % seed)

    def test_la_lettre_de_famille_suit_le_chassis(self) -> None:
        for seed in range(200):
            g = generate(seed)
            attendu = "M" if g["chassis"] == "monobloc" else "C"
            self.assertEqual(model_name(g)[0], attendu, "graine %d" % seed)

    def test_la_capsule_annonce_ses_oreilles(self) -> None:
        for seed in range(200):
            g = generate(seed)
            if g["chassis"] != "capsule":
                continue
            self.assertEqual(model_name(g)[3], LETTRES_OREILLES[g["ear.type"]],
                             "graine %d" % seed)

    def test_le_monobloc_annonce_son_ecran(self) -> None:
        """Il n'a pas d'oreilles : lui garder la lettre des oreilles aurait
        donné le même `X` à quatre robots sur dix, soit un code sans pouvoir
        distinctif."""
        vus = 0
        for seed in range(200):
            g = generate(seed)
            if g["chassis"] != "monobloc":
                continue
            vus += 1
            self.assertEqual(model_name(g)[3], LETTRES_ECRAN[g["screen.height"]],
                             "graine %d" % seed)
        self.assertGreater(vus, 20, "trop peu de monoblocs pour conclure")

    def test_le_chiffre_de_forme_va_du_cube_a_la_sphere(self) -> None:
        cube, sphere = defaults(), defaults()
        cube["head.exponent_n1"] = 0.35
        sphere["head.exponent_n1"] = 1.00
        self.assertEqual(chiffre_forme(cube), 1)
        self.assertEqual(chiffre_forme(sphere), 4)

    def test_le_libelle_est_lisible(self) -> None:
        g = defaults()
        self.assertEqual(libelle_famille(g), "Capsule")
        g["chassis"] = "monobloc"
        self.assertEqual(libelle_famille(g), "Monobloc")


class StabiliteTest(unittest.TestCase):
    """Ce qui ne doit rien changer à la référence."""

    def test_la_couleur_ne_change_rien(self) -> None:
        """C'est la raison d'être de la règle : la couleur s'achète et se
        change, la référence non."""
        base = generate(11)
        attendu = model_name(base)
        for corps in BODY_COLORS:
            for accent in ACCENT_COLORS:
                variante = dict(base)
                variante["palette.body"] = corps
                variante["palette.accent"] = accent
                self.assertEqual(model_name(variante), attendu,
                                 "%s / %s" % (corps, accent))

    def test_un_cosmetique_ne_change_rien(self) -> None:
        """Les chapeaux vivent dans `appearance`, pas dans le génome — mais un
        jour quelqu'un passera un costume à cette fonction, et il ne doit rien
        s'y passer."""
        base = generate(23)
        habille = dict(base)
        habille.update({"hat": "crown", "moustache": "walrus"})
        self.assertEqual(model_name(habille), model_name(base))

    def test_la_reference_est_la_meme_d_un_lancement_a_l_autre(self) -> None:
        """**Le piège de ce lot.** `hash()` sur une chaîne est randomisé à
        chaque processus Python : la référence aurait changé à chaque
        démarrage, et personne ne l'aurait remarqué en la testant dans un seul
        processus. La valeur est donc figée ici en dur — si quelqu'un remplace
        `crc32` par autre chose, ce test tombe.
        """
        self.assertEqual(model_name(defaults()), "C3-A6")
        mono = defaults()
        mono["chassis"] = "monobloc"
        mono["ear.type"] = "none"
        mono["screen.height"] = "large"
        self.assertEqual(model_name(mono), "M3-G7")

    def test_un_parametre_absent_ne_fait_pas_echouer(self) -> None:
        """Un génome d'avant le lot, lu avant migration, ne doit pas faire
        planter la page de statut."""
        ancien = {k: v for k, v in defaults().items()
                  if k not in ("chassis", "screen.height")}
        self.assertRegex(model_name(ancien), FORMAT)


class VarianceTest(unittest.TestCase):
    """Ce qui doit la faire varier."""

    def test_deux_robots_differents_portent_rarement_le_meme_code(self) -> None:
        """Mesuré, pas supposé. Une référence est un **modèle**, pas un numéro
        de série : deux robots peuvent la partager comme deux voitures
        partagent leur modèle. Mais si une référence écrasait tout le reste, le
        code ne dirait plus rien.
        """
        codes = Counter(model_name(generate(s)) for s in range(3000))
        self.assertGreater(len(codes), 200,
                           "trop peu de références distinctes : %d" % len(codes))
        part = codes.most_common(1)[0][1] / 3000.0
        self.assertLess(part, 0.05,
                        "une référence rafle %.1f %% des robots" % (part * 100))

    def test_la_forme_fait_varier_le_code(self) -> None:
        cube, sphere = defaults(), defaults()
        cube["head.exponent_n1"] = 0.36
        sphere["head.exponent_n1"] = 0.99
        self.assertNotEqual(model_name(cube), model_name(sphere))

    def test_le_chassis_fait_varier_le_code(self) -> None:
        capsule = defaults()
        mono = dict(capsule)
        mono["chassis"] = "monobloc"
        mono["ear.type"] = "none"
        self.assertNotEqual(model_name(capsule), model_name(mono))

    def test_une_proportion_fait_varier_la_signature(self) -> None:
        """Sans quoi la signature ne servirait à rien : deux robots de même
        famille, même forme et même trait auraient toujours le même code."""
        a = defaults()
        b = dict(a)
        b["body.height"] = a["body.height"] * 1.25
        self.assertNotEqual(model_name(a), model_name(b))


if __name__ == "__main__":
    unittest.main()
