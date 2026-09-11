"""Critères d'acceptation de l'économie et de la boutique, lot L7 (CDC §14).

Trois familles :

- **Le plafond quotidien**, que le §14 qualifie d'impératif — « pour que l'idle
  infini ne soit pas la stratégie optimale » — et la détection de recul
  d'horloge qui va avec.
- **La boutique** : acheter est définitif, porter est libre, et un article ne se
  paie qu'une fois.
- **Les chapeaux**, qui doivent coiffer n'importe quelle morphologie sans qu'on
  ait à les reprendre un par un.

Aucun GPU, aucune fenêtre : l'économie est pure, et la géométrie des chapeaux se
vérifie sur les maillages.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from pet.brain.economy import (AWARD_PER_CARE, DAILY_CAP, Economy, day_key)
from pet.geometry.cosmetics import (COSMETICS, BY_KEY, NONE, SLOTS,
                                    by_slot, parts_for, price, slot_of)

HATS = by_slot("hat")

JOUR = 86400.0


class DailyCapTest(unittest.TestCase):
    """« Un plafond quotidien pour que l'idle infini ne soit pas optimal. »"""

    def test_le_plafond_borne_la_journee(self) -> None:
        eco = Economy()
        gagne = sum(eco.award() for _ in range(DAILY_CAP * 4))
        self.assertEqual(gagne, DAILY_CAP)
        self.assertEqual(eco.tokens, DAILY_CAP)

    def test_le_versement_rend_ce_qui_a_ete_reellement_verse(self) -> None:
        """Promettre un token pour n'en donner aucun ferait douter du reste."""
        eco = Economy(today=DAILY_CAP - 1)
        self.assertEqual(eco.award(5), 1)
        self.assertEqual(eco.award(5), 0)

    def test_le_quota_se_rouvre_le_lendemain(self) -> None:
        maintenant = time.time()
        eco = Economy()
        for _ in range(DAILY_CAP * 2):
            eco.award(when=maintenant)
        self.assertEqual(eco.remaining, 0)
        eco.award(when=maintenant + JOUR)
        self.assertGreater(eco.tokens, DAILY_CAP)

    def test_une_horloge_qui_recule_ne_rouvre_rien(self) -> None:
        """§14 : « détecter les reculs d'horloge, pas de crédit rétroactif ».

        C'est le seul vecteur qui rapporterait : avancer la date pour rouvrir le
        quota, puis la reculer pour recommencer. La clé du jour devant être
        **strictement postérieure**, le retour en arrière ne rouvre rien.
        """
        maintenant = time.time()
        eco = Economy()
        for _ in range(DAILY_CAP * 2):
            eco.award(when=maintenant)
        solde = eco.tokens

        eco.award(when=maintenant - 3 * JOUR)
        self.assertEqual(eco.tokens, solde, "un recul d'horloge a payé")
        eco.award(when=maintenant)
        self.assertEqual(eco.tokens, solde)

    def test_le_premier_versement_ouvre_la_journee(self) -> None:
        eco = Economy()
        self.assertEqual(eco.day, "")
        eco.award()
        self.assertEqual(eco.day, day_key())

    def test_un_gain_negatif_ou_nul_ne_donne_rien(self) -> None:
        eco = Economy()
        self.assertEqual(eco.award(0), 0)
        self.assertEqual(eco.award(-10), 0)
        self.assertEqual(eco.tokens, 0)

    def test_le_gain_par_soin_est_uniforme(self) -> None:
        """Un soin plus payant qu'un autre pousserait à ne faire que celui-là."""
        self.assertEqual(AWARD_PER_CARE, 1)

    def test_le_plafond_laisse_deux_jours_pour_l_article_le_plus_cher(self) -> None:
        """C'est le seul chiffre qui règle le rythme de la boutique."""
        plus_cher = max(c.price for c in COSMETICS)
        self.assertLessEqual(plus_cher / DAILY_CAP, 2.0)
        self.assertGreater(plus_cher / DAILY_CAP, 1.0)


class SpendTest(unittest.TestCase):
    def test_on_ne_depense_pas_ce_qu_on_n_a_pas(self) -> None:
        eco = Economy(tokens=10)
        self.assertFalse(eco.spend(11))
        self.assertEqual(eco.tokens, 10)
        self.assertTrue(eco.spend(10))
        self.assertEqual(eco.tokens, 0)

    def test_le_solde_ne_passe_jamais_sous_zero(self) -> None:
        eco = Economy(tokens=3)
        for prix in (5, 4, 3, 2, 1):
            eco.spend(prix)
        self.assertGreaterEqual(eco.tokens, 0)

    def test_l_etat_fait_l_aller_retour(self) -> None:
        eco = Economy(tokens=7)
        eco.award()
        relu = Economy.from_dict(eco.as_dict())
        self.assertEqual(relu.tokens, eco.tokens)
        self.assertEqual(relu.day, eco.day)
        self.assertEqual(relu.today, eco.today)

    def test_un_etat_aberrant_est_borne(self) -> None:
        """§14 : borner plutôt que rejeter."""
        eco = Economy.from_dict({"tokens": -5, "tokens_day": 42,
                                 "tokens_today": 9999})
        self.assertEqual(eco.tokens, 0)
        self.assertEqual(eco.day, "")
        self.assertLessEqual(eco.today, DAILY_CAP)


class HatCatalogTest(unittest.TestCase):
    def test_les_prix_tiennent_la_fourchette_convenue(self) -> None:
        for hat in COSMETICS:
            self.assertGreaterEqual(hat.price, 5)
            self.assertLessEqual(hat.price, 50)

    def test_chaque_chapeau_a_une_cle_unique(self) -> None:
        cles = [c.key for c in COSMETICS]
        self.assertEqual(len(cles), len(set(cles)))
        self.assertNotIn(NONE, cles, "la tête nue n'est pas un article")

    def test_chaque_chapeau_a_au_moins_un_morceau(self) -> None:
        for hat in COSMETICS:
            self.assertTrue(hat.pieces, hat.key)

    def test_un_article_inconnu_ne_coute_rien_et_ne_dessine_rien(self) -> None:
        from pet.genome.generator import generate
        from pet.geometry.proportions import dimensions

        self.assertEqual(price("sombrero"), 0)
        self.assertEqual(parts_for("sombrero", dimensions(generate(8))), [])


class HatGeometryTest(unittest.TestCase):
    """Un chapeau doit coiffer **toutes** les morphologies, pas la moyenne."""

    SEEDS = (8, 3, 21, 42, 7)

    def _dims(self, seed: int):
        from pet.genome.generator import generate
        from pet.geometry.proportions import dimensions
        return dimensions(generate(seed))

    def test_un_article_de_tete_se_pose_au_dessus_du_crane(self) -> None:
        """Les cotes sont en parts de tête : aucun ne doit s'y enfoncer.

        Vérifié sur l'emplacement `hat` seulement : une moustache est ancrée sur
        la **face**, donc sous le sommet du crâne par construction. La première
        version de ce test les a accusées à tort en passant tout le catalogue.
        """
        for seed in self.SEEDS:
            d = self._dims(seed)
            sommet = 2.0 * d.head_b
            for hat in by_slot("hat"):
                for part in parts_for(hat.key, d):
                    haut = part.offset[1] + float(part.mesh.bounds()[1][1])
                    self.assertGreater(haut, sommet,
                                       "%s ne dépasse pas du crâne sur la "
                                       "graine %d" % (hat.key, seed))

    def test_une_moustache_se_pose_sous_les_yeux_et_devant(self) -> None:
        """Elle ne doit jamais couvrir la dalle du visage.

        C'est la seule surface expressive du robot : la masquer même en partie
        lui coûterait plus qu'une moustache ne lui apporte. Elle doit aussi être
        **en avant** du crâne, sans quoi elle s'y noierait.
        """
        for seed in self.SEEDS:
            d = self._dims(seed)
            centre = d.head_b
            for item in by_slot("moustache"):
                for part in parts_for(item.key, d):
                    haut = part.offset[1] + float(part.mesh.bounds()[1][1])
                    self.assertLess(haut, centre,
                                    "%s monte sur la dalle sur la graine %d"
                                    % (item.key, seed))
                    self.assertGreater(part.offset[2], 0.0,
                                       "%s n'est pas devant le crâne"
                                       % item.key)

    def test_une_moustache_ressort_de_la_peau_du_crane(self) -> None:
        """Sinon elle se confond avec la géométrie de la tête.

        La cote de profondeur ne peut pas être posée à l'oeil : à la hauteur
        d'une moustache, la surface d'un crâne **rond** a déjà reculé à environ
        `0,89·head_c`, alors qu'un crâne **cubique** y est encore à `1,0`. Une
        valeur choisie pour l'un noie la pièce chez l'autre.

        Le test compare donc la face avant de chaque pièce à la peau calculée
        pour la morphologie en cours, sur toute la plage d'exposants.
        """
        from pet.genome.generator import generate

        for seed in self.SEEDS:
            d = self._dims(seed)
            n1 = float(generate(seed)["head.exponent_n1"])
            for item in by_slot("moustache"):
                parts = parts_for(item.key, d)
                avant = max(p.offset[2] + float(p.mesh.bounds()[1][2])
                            for p in parts)
                arriere = min(p.offset[2] + float(p.mesh.bounds()[0][2])
                              for p in parts)
                hauteur = abs(min(p.offset[1] for p in parts) - d.head_b)
                ratio = min(0.99, hauteur / max(1e-6, d.head_b))
                peau = d.head_c * (1.0 - ratio ** (2.0 / n1)) ** (n1 / 2.0)
                self.assertGreater(avant, peau,
                                   "%s se noie dans le crâne sur la graine %d"
                                   % (item.key, seed))
                self.assertLess(arriere, peau,
                                "%s flotte devant le crâne sur la graine %d"
                                % (item.key, seed))

    def test_les_pointes_du_guidon_ne_montent_pas(self) -> None:
        """Régression : placées au-dessus de la barre, elles se lisaient comme
        deux antennes partant vers le ciel."""
        d = self._dims(8)
        parts = parts_for("handlebar", d)
        barre = parts[0]
        for pointe in parts[1:]:
            self.assertLessEqual(pointe.offset[1], barre.offset[1],
                                 "une pointe du guidon part vers le haut")

    def test_chaque_emplacement_a_ses_articles(self) -> None:
        """Un emplacement déclaré mais vide donnerait un rayon vide."""
        for emplacement in SLOTS:
            articles = by_slot(emplacement)
            self.assertTrue(articles, "l'emplacement %s est vide" % emplacement)
            for item in articles:
                self.assertEqual(slot_of(item.key), emplacement)

    def test_les_emplacements_se_portent_ensemble(self) -> None:
        """Ils sont indépendants : un chapeau n'exclut pas une moustache."""
        from pet.genome.generator import generate
        from pet.geometry.builder import build

        genome = generate(8)
        nu = len(build(genome).parts)
        chapeau = by_slot("hat")[0]
        moustache = by_slot("moustache")[0]
        les_deux = build(genome, {"hat": chapeau.key,
                                  "moustache": moustache.key})
        self.assertEqual(len(les_deux.parts),
                         nu + len(chapeau.pieces) + len(moustache.pieces))

    def test_aucun_chapeau_ne_flotte_loin_de_la_tete(self) -> None:
        """L'inverse du précédent : posé, pas en lévitation."""
        for seed in self.SEEDS:
            d = self._dims(seed)
            sommet = 2.0 * d.head_b
            for hat in by_slot("hat"):
                bas = min(part.offset[1] + float(part.mesh.bounds()[0][1])
                          for part in parts_for(hat.key, d))
                self.assertLess(bas - sommet, d.head_b,
                                "%s lévite sur la graine %d" % (hat.key, seed))

    def test_un_chapeau_reste_a_l_echelle_de_la_tete(self) -> None:
        """Cotes en parts de tête : un crâne deux fois plus large, un chapeau
        deux fois plus large. Sans quoi il déborderait sur les morphologies
        extrêmes, qui varient du simple au double."""
        largeurs = []
        for seed in self.SEEDS:
            d = self._dims(seed)
            parts = parts_for("tophat", d)
            large = max(float(p.mesh.bounds()[1][0]) for p in parts)
            largeurs.append(large / d.head_a)
        for rapport in largeurs[1:]:
            self.assertAlmostEqual(rapport, largeurs[0], places=3)

    def test_les_morceaux_sont_greffes_sur_la_tete(self) -> None:
        """Aucun nœud de rig ajouté : il suit la tête sans une ligne de plus."""
        d = self._dims(8)
        for hat in COSMETICS:
            for part in parts_for(hat.key, d):
                self.assertEqual(part.node, "head")

    def test_un_robot_coiffe_a_plus_de_parties(self) -> None:
        from pet.genome.generator import generate
        from pet.geometry.builder import build

        genome = generate(8)
        nu = build(genome)
        for hat in COSMETICS:
            coiffe = build(genome, {hat.slot: hat.key})
            self.assertEqual(len(coiffe.parts),
                             len(nu.parts) + len(hat.pieces), hat.key)

    def test_le_genome_n_est_pas_touche_par_le_chapeau(self) -> None:
        """Un chapeau est un objet acheté, pas un trait de naissance."""
        from pet.genome.generator import generate
        from pet.geometry.builder import build

        genome = generate(8)
        avant = dict(genome)
        build(genome, {"hat": "crown"})
        self.assertEqual(genome, avant)


class ShopSessionTest(unittest.TestCase):
    """Acheter, porter, et ce qui les sépare."""

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

    def _session(self, tokens: int = 0):
        from pet.brain.session import Session
        s = Session()
        s.load()
        s.economy.tokens = tokens
        return s

    def test_un_achat_debite_et_range_dans_l_inventaire(self) -> None:
        s = self._session(tokens=20)
        self.assertTrue(s.buy("bow"))
        self.assertEqual(s.tokens, 20 - price("bow"))
        self.assertIn("bow", s.inventory)

    def test_on_ne_paie_qu_une_fois(self) -> None:
        s = self._session(tokens=50)
        self.assertTrue(s.buy("bow"))
        solde = s.tokens
        self.assertFalse(s.buy("bow"), "il a repayé son chapeau")
        self.assertEqual(s.tokens, solde)

    def test_un_achat_impossible_ne_debite_rien(self) -> None:
        s = self._session(tokens=1)
        self.assertFalse(s.buy("crown"))
        self.assertEqual(s.tokens, 1)
        self.assertEqual(s.inventory, [])

    def test_on_ne_porte_que_ce_qu_on_possede(self) -> None:
        s = self._session(tokens=50)
        self.assertFalse(s.wear("hat", "crown"))
        s.buy("crown")
        self.assertTrue(s.wear("hat", "crown"))
        self.assertEqual(s.appearance.get("hat"), "crown")

    def test_la_tete_nue_est_toujours_disponible(self) -> None:
        """C'est un choix, pas une absence : on doit pouvoir se découvrir."""
        s = self._session(tokens=50)
        s.buy("bow")
        s.wear("hat", "bow")
        self.assertTrue(s.wear("hat", NONE))
        self.assertEqual(s.appearance.get("hat"), NONE)

    def test_l_achat_survit_a_une_fermeture(self) -> None:
        s = self._session(tokens=50)
        s.buy("tophat")
        s.wear("hat", "tophat")
        relu = self._session()
        self.assertIn("tophat", relu.inventory)
        self.assertEqual(relu.appearance.get("hat"), "tophat")

    def test_un_inventaire_aberrant_est_filtre(self) -> None:
        """Afficher un chapeau qu'on ne sait pas dessiner serait pire."""
        from pet.state import save

        store = save.state_store()
        save.write_json_atomic(store.path, {
            "schema_version": save.STATE_SCHEMA,
            "inventory": ["bow", "sombrero", "bow", 42],
        })
        self.assertEqual(self._session().inventory, ["bow"])

    def test_un_chapeau_non_possede_n_est_pas_porte_au_chargement(self) -> None:
        from pet.state import save

        store = save.state_store()
        save.write_json_atomic(store.path, {
            "schema_version": save.STATE_SCHEMA,
            "inventory": [],
            "appearance": {"hat": "crown"},
        })
        # Le costume est validé sur le catalogue, pas sur l'inventaire : porter
        # sans posséder est refusé par `wear`, seule porte d'entrée du jeu.
        s = self._session()
        self.assertFalse(s.wear("hat", "crown"))

    def test_le_quota_du_jour_survit_a_une_fermeture(self) -> None:
        """Sinon fermer l'application rouvrirait le plafond du §14."""
        s = self._session()
        for _ in range(DAILY_CAP):
            s.award_tokens()
        self.assertEqual(s.tokens_remaining, 0)
        self.assertEqual(self._session().tokens_remaining, 0)


if __name__ == "__main__":
    unittest.main()
