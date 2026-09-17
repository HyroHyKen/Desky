"""Critères d'acceptation du génome, lot L2 (CDC §7).

Le critère central est le **déterminisme** : une même graine doit toujours
produire le même génome, donc la même géométrie. Aucun GPU n'est nécessaire.
"""

from __future__ import annotations

import random
import unittest

from pet.genome import generator, migration
from pet.genome.schema import (
    ACCENT_COLORS,
    BODY_COLORS,
    PARAMS,
    PARAMS_BY_KEY,
    SCHEMA_VERSION,
    Choice,
    Num,
    clamp_genome,
    defaults,
    hex_to_rgb,
)

# Ordre de déclaration attendu. Ce n'est pas une redondance : l'ordre de `PARAMS`
# fixe l'ordre de consommation du PRNG, donc insérer un paramètre ailleurs qu'à
# la fin change **tous** les robots régénérés depuis leur graine. Ce test est là
# pour que cette conséquence ne passe pas inaperçue.
EXPECTED_ORDER = [
    "head.radius", "head.squash_y", "head.exponent_n1", "head.exponent_n2",
    "body.height", "body.width", "body.taper",
    "neck.length",
    "ear.type", "ear.spread", "ear.size",
    "face.plate_ratio", "eye.spacing", "eye.size", "eye.corner_radius",
    "palette.body", "palette.accent",
    "outline.width",
    # Lot L17. Ajoutés en fin de liste, et c'est tout l'objet du test ci-dessous.
    "chassis", "screen.height",
]


class SchemaTest(unittest.TestCase):
    def test_ordre_de_declaration_inchange(self) -> None:
        self.assertEqual([p.key for p in PARAMS], EXPECTED_ORDER,
                         "l'ordre de PARAMS a changé : tout paramètre nouveau doit être "
                         "ajouté À LA FIN, sinon les robots existants régénérés depuis "
                         "leur graine deviennent différents")

    def test_cles_uniques(self) -> None:
        keys = [p.key for p in PARAMS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_bornes_coherentes(self) -> None:
        for p in PARAMS:
            if isinstance(p, Num):
                self.assertLess(p.lo, p.hi, p.key)
                self.assertTrue(p.lo <= p.default <= p.hi, p.key)

    def test_poids_alignes_sur_les_options(self) -> None:
        for p in PARAMS:
            if isinstance(p, Choice):
                self.assertEqual(len(p.options), len(p.weights), p.key)
                self.assertTrue(all(w > 0 for w in p.weights), p.key)

    def test_palettes_completes(self) -> None:
        self.assertEqual(set(PARAMS_BY_KEY["palette.body"].options), set(BODY_COLORS))
        self.assertEqual(set(PARAMS_BY_KEY["palette.accent"].options), set(ACCENT_COLORS))

    def test_le_defaut_de_palette_est_l_option_dominante(self) -> None:
        """Le repli doit être la teinte neutre, pas une teinte rare."""
        self.assertEqual(PARAMS_BY_KEY["palette.body"].default, "blanc-casse")
        self.assertEqual(PARAMS_BY_KEY["palette.accent"].default, "cyan")

    def test_bornage_des_valeurs_aberrantes(self) -> None:
        borne = clamp_genome({"head.radius": 99.0, "body.width": -5.0,
                              "ear.type": "tentacule", "palette.body": "fuchsia"})
        self.assertEqual(borne["head.radius"], PARAMS_BY_KEY["head.radius"].hi)
        self.assertEqual(borne["body.width"], PARAMS_BY_KEY["body.width"].lo)
        self.assertEqual(borne["ear.type"], PARAMS_BY_KEY["ear.type"].default)
        self.assertEqual(borne["palette.body"], "blanc-casse")

    def test_valeurs_non_numeriques_et_nan(self) -> None:
        borne = clamp_genome({"head.radius": "grande", "body.height": float("nan")})
        self.assertEqual(borne["head.radius"], PARAMS_BY_KEY["head.radius"].default)
        self.assertEqual(borne["body.height"], PARAMS_BY_KEY["body.height"].default)

    def test_les_cles_inconnues_sont_conservees(self) -> None:
        """Un retour en arrière de version ne doit rien détruire."""
        borne = clamp_genome({"tail.length": 0.4})
        self.assertEqual(borne["tail.length"], 0.4)

    def test_defauts_complets_et_valides(self) -> None:
        d = defaults()
        self.assertEqual(set(d), set(PARAMS_BY_KEY))
        self.assertEqual(generator.viability_issues(d), [],
                         "le génome médian doit être viable")

    def test_conversion_hex(self) -> None:
        self.assertEqual(hex_to_rgb("#FFFFFF"), (1.0, 1.0, 1.0))
        self.assertEqual(hex_to_rgb("#000000"), (0.0, 0.0, 0.0))
        for mauvais in ("", "#GGG", "pas une couleur", "#12345"):
            r, g, b = hex_to_rgb(mauvais)
            self.assertTrue(all(0.0 <= c <= 1.0 for c in (r, g, b)), mauvais)


class DeterminismTest(unittest.TestCase):
    SEEDS = (1, 2, 42, 1337, 999983, 2 ** 40 + 7)

    def test_meme_graine_meme_genome(self) -> None:
        for seed in self.SEEDS:
            a = generator.generate(seed)
            b = generator.generate(seed)
            self.assertEqual(a, b, f"graine {seed}")

    def test_graines_differentes_genomes_differents(self) -> None:
        vus = {}
        for seed in range(1, 60):
            g = generator.generate(seed)
            cle = tuple(round(v, 9) if isinstance(v, float) else v
                        for k, v in sorted(g.items()) if k in PARAMS_BY_KEY)
            self.assertNotIn(cle, vus, f"graines {vus.get(cle)} et {seed} identiques")
            vus[cle] = seed

    def test_immunise_contre_le_prng_global(self) -> None:
        """Le générateur ne doit pas dépendre de l'état de `random` global.

        Un appel étranger n'importe où dans le process suffirait sinon à décaler
        la séquence, et le robot de l'utilisateur changerait sans raison.
        """
        random.seed(1)
        a = generator.generate(12345)
        random.seed(2)
        [random.random() for _ in range(50)]
        b = generator.generate(12345)
        self.assertEqual(a, b)

    def test_la_graine_est_tracee_dans_le_genome(self) -> None:
        g = generator.generate(777)
        self.assertEqual(g["seed"], 777)
        self.assertEqual(g["schema_version"], SCHEMA_VERSION)
        self.assertGreaterEqual(g["attempts"], 1)

    def test_nouvelle_graine_dans_les_bornes(self) -> None:
        for _ in range(50):
            self.assertTrue(1 <= generator.new_seed() < 2 ** 53)


class ViabilityTest(unittest.TestCase):
    def test_tout_genome_genere_est_viable(self) -> None:
        for seed in range(1, 400):
            g = generator.generate(seed)
            self.assertEqual(generator.viability_issues(g), [], f"graine {seed}")

    def test_tout_genome_genere_est_dans_les_bornes(self) -> None:
        for seed in range(1, 200):
            g = generator.generate(seed)
            for p in PARAMS:
                if isinstance(p, Num):
                    self.assertTrue(p.lo <= g[p.key] <= p.hi, f"{p.key} graine {seed}")
                else:
                    self.assertIn(g[p.key], p.options, f"{p.key} graine {seed}")

    def test_taux_d_acceptation_praticable(self) -> None:
        """Les bornes du §7 et ses règles de cohérence doivent être compatibles.

        Un taux très bas signifierait que le nuage morphologique visé est en
        réalité presque vide, et que les bornes ou les règles sont à revoir.
        """
        rate, reasons = generator.acceptance_rate(4000)
        self.assertGreater(rate, 0.40, f"taux trop bas ({rate:.0%}), rejets : {reasons}")
        self.assertLess(rate, 1.0, "aucun rejet : la règle de cohérence ne sert à rien")

    def test_la_regle_de_tete_rejette_bien(self) -> None:
        mauvais = defaults()
        mauvais["head.radius"] = 1.35
        mauvais["body.width"] = 0.75
        issues = generator.viability_issues(mauvais)
        self.assertTrue(any(i.startswith("tete_trop_large") for i in issues), issues)

    def test_la_regle_des_pupilles_rejette_bien(self) -> None:
        """Règle de garde : ne se déclenche pas sur un tirage, mais protège
        contre une édition manuelle ou un élargissement futur des plages."""
        mauvais = defaults()
        mauvais["eye.spacing"] = 1.4
        mauvais["eye.size"] = 0.9
        issues = generator.viability_issues(mauvais)
        self.assertTrue(any(i.startswith("pupilles_hors_dalle") for i in issues), issues)

    def test_cou_imperceptible_ramene_a_zero(self) -> None:
        g = dict(defaults())
        g["neck.length"] = generator.NECK_MIN_VISIBLE / 2.0
        self.assertEqual(generator.normalize(g)["neck.length"], 0.0)

    def test_echec_signale_si_rien_n_est_viable(self) -> None:
        """Bornes et règles incompatibles doivent lever, pas boucler."""
        original = generator.viability_issues
        generator.viability_issues = lambda g: ["impossible"]
        try:
            with self.assertRaises(generator.GenomeGenerationError):
                generator.generate(1)
        finally:
            generator.viability_issues = original


class MigrationTest(unittest.TestCase):
    def test_meme_version_ne_change_rien(self) -> None:
        g = generator.generate(4242)
        migre = migration.migrate(dict(g), from_version=SCHEMA_VERSION)
        for key in PARAMS_BY_KEY:
            self.assertEqual(migre[key], g[key], key)

    def test_parametre_absent_complete_sans_toucher_aux_autres(self) -> None:
        """Cœur du critère : migrer ne doit produire aucune dérive.

        On simule un fichier écrit par une version antérieure, qui ne connaissait
        pas encore `outline.width`. Le paramètre doit apparaître à sa valeur par
        défaut, et **tous les autres rester au bit près**.
        """
        g = generator.generate(31337)
        ancien = {k: v for k, v in g.items() if k != "outline.width"}
        ancien["schema_version"] = 0

        migre = migration.migrate(ancien, from_version=0)

        self.assertEqual(migre["outline.width"], PARAMS_BY_KEY["outline.width"].default)
        for key in PARAMS_BY_KEY:
            if key == "outline.width":
                continue
            self.assertEqual(migre[key], g[key], f"dérive sur {key}")
        self.assertEqual(migre["seed"], g["seed"])
        self.assertEqual(migre["schema_version"], SCHEMA_VERSION)

    def test_liste_des_parametres_ajoutes(self) -> None:
        g = generator.generate(5)
        partiel = {k: v for k, v in g.items() if k not in ("ear.size", "outline.width")}
        self.assertEqual(sorted(migration.added_params(partiel)),
                         ["ear.size", "outline.width"])

    def test_version_plus_recente_conserve_ses_inconnues(self) -> None:
        g = generator.generate(6)
        futur = dict(g)
        futur["tail.length"] = 0.7
        futur["schema_version"] = SCHEMA_VERSION + 1

        migre = migration.migrate(futur, from_version=SCHEMA_VERSION + 1)

        self.assertEqual(migre["tail.length"], 0.7,
                         "un retour en arrière ne doit pas détruire les paramètres "
                         "d'une version plus récente")
        self.assertEqual(migration.unknown_params(migre), ["tail.length"])

    def test_valeurs_aberrantes_bornees_a_la_migration(self) -> None:
        g = generator.generate(7)
        abime = dict(g)
        abime["head.radius"] = 999.0
        migre = migration.migrate(abime, from_version=SCHEMA_VERSION)
        self.assertEqual(migre["head.radius"], PARAMS_BY_KEY["head.radius"].hi)

    def test_migration_explicite_appelee_dans_l_ordre(self) -> None:
        appels: list[int] = []
        original = dict(migration.MIGRATIONS)
        migration.MIGRATIONS.clear()
        try:
            for v in (0, 1, 2):
                def fn(data, v=v):
                    appels.append(v)
                    return data
                migration.MIGRATIONS[v] = fn
            migration.migrate(defaults(), from_version=0, to_version=3)
            self.assertEqual(appels, [0, 1, 2])
        finally:
            migration.MIGRATIONS.clear()
            migration.MIGRATIONS.update(original)

    def test_double_enregistrement_refuse(self) -> None:
        original = dict(migration.MIGRATIONS)
        try:
            migration.register(99)(lambda d: d)
            with self.assertRaises(ValueError):
                migration.register(99)(lambda d: d)
        finally:
            migration.MIGRATIONS.clear()
            migration.MIGRATIONS.update(original)

    def test_genome_migre_reste_viable(self) -> None:
        for seed in range(1, 60):
            g = generator.generate(seed)
            tronque = {k: v for k, v in g.items()
                       if k not in ("outline.width", "eye.size", "ear.spread")}
            migre = migration.migrate(tronque, from_version=0)
            self.assertEqual(generator.viability_issues(migre), [], f"graine {seed}")


if __name__ == "__main__":
    unittest.main()
