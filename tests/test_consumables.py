"""Critères d'acceptation de l'économie des consommables, lot L13 (CDC §14).

Le renversement du lot : les soins ne sont plus des boutons gratuits bornés par
un délai, mais des objets qu'on achète avec des jetons gagnés en jouant.

Ces tests gardent les trois propriétés dont dépend l'équilibre — la migration
est additive, la boucle se referme, et rien ne se perd.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from pet.brain import consumables
from pet.brain.consumables import AISLES, CONSUMABLES, by_need
from pet.brain.economy import AWARD_PER_GAME, AWARD_PER_RECORD


class CatalogueTest(unittest.TestCase):
    def test_chaque_article_sert_un_besoin_connu(self) -> None:
        from pet.brain.needs import NEEDS

        for article in CONSUMABLES:
            self.assertIn(article.need, NEEDS, article.key)
            self.assertGreater(article.gain, 0.0, article.key)

    def test_chaque_rayon_a_des_articles(self) -> None:
        """Les rayons sont dérivés du catalogue : un rayon vide voudrait dire
        qu'on a renommé un besoin d'un côté seulement."""
        for rayon in AISLES:
            self.assertTrue(by_need(rayon), "rayon vide : " + rayon)

    def test_le_rayon_est_trie_du_moins_cher_au_plus_cher(self) -> None:
        for rayon in AISLES:
            prix = [a.price for a in by_need(rayon)]
            self.assertEqual(prix, sorted(prix), rayon)

    def test_la_pile_remplit_l_energie(self) -> None:
        pile = consumables.get("battery")
        self.assertIsNotNone(pile)
        self.assertEqual(pile.need, "energy")
        self.assertGreaterEqual(pile.gain, 100.0, "elle ne remplit pas la jauge")
        self.assertTrue(pile.instant, "une pile ne se pose pas sur le bureau")

    def test_seule_la_pile_agit_sur_le_champ(self) -> None:
        """Tout le reste passe par le bureau, et doit donc avoir un sprite."""
        from pet.ui.item import ITEM_KINDS

        for article in CONSUMABLES:
            if article.instant:
                continue
            self.assertIn(article.kind, ITEM_KINDS, article.key)

    def test_un_prix_reste_accessible_en_une_ou_deux_parties(self) -> None:
        """À un jeton par partie, l'entretien courant ne doit pas devenir une
        corvée à financer. Seule la pile se mérite."""
        courants = [a for a in CONSUMABLES if not a.instant]
        self.assertTrue(courants)
        self.assertLessEqual(max(a.price for a in courants), 2)


class EconomyTest(unittest.TestCase):
    """Les jeux financent les soins, et non l'inverse."""

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

    def _session(self):
        from pet.brain.session import Session

        s = Session()
        s.load()
        return s

    def test_un_record_rapporte_plus_qu_une_partie(self) -> None:
        """Sans quoi il vaudrait mieux enchaîner les parties bâclées que viser
        haut, ce qui viderait le score de son sens."""
        self.assertGreater(AWARD_PER_RECORD, AWARD_PER_GAME)

    def test_soigner_ne_rapporte_plus_rien(self) -> None:
        """Les soins étant devenus des objets qu'on achète, ils ne peuvent plus
        financer leur propre achat."""
        from pet.brain.needs import Needs

        s = self._session()
        s.brain.needs = Needs(fun=10.0)
        avant = s.tokens
        s.care("pet")
        self.assertEqual(s.tokens, avant)

    def test_acheter_debite_exactement(self) -> None:
        s = self._session()
        s.economy.tokens = 10
        self.assertTrue(s.buy_consumable("meal", 2))
        self.assertEqual(s.tokens, 10 - 2 * consumables.price("meal"))
        self.assertEqual(s.count("meal"), 2)

    def test_un_achat_trop_cher_ne_prend_rien(self) -> None:
        """Tout ou rien : acheter trois gamelles avec de quoi en payer deux ne
        doit pas en livrer deux et prendre l'argent des trois."""
        s = self._session()
        s.economy.tokens = 3
        self.assertFalse(s.buy_consumable("meal", 3))
        self.assertEqual(s.tokens, 3)
        self.assertEqual(s.count("meal"), 0)

    def test_le_stock_survit_au_redemarrage(self) -> None:
        s = self._session()
        s.economy.tokens = 10
        s.buy_consumable("kit", 3)
        s.flush(force=True)
        self.assertEqual(self._session().count("kit"), 3)

    def test_une_ancienne_sauvegarde_se_charge(self) -> None:
        """La migration est purement **additive** : `consumables` est absent des
        sauvegardes d'avant le lot, et son absence ne doit rien casser.

        C'est la seule chose qui compte pour un utilisateur qui avait déjà un
        robot : ses jetons, ses chapeaux et son nom traversent la migration
        intacts, et il se retrouve simplement avec un inventaire vide.
        """
        import json
        from pathlib import Path

        from pet.state import save

        dossier = Path(save.app_dir())
        fichier = dossier / "state.json"
        etat = (json.loads(fichier.read_text(encoding="utf-8"))
                if fichier.exists() else {})
        etat.update({"schema_version": save.STATE_SCHEMA, "tokens": 9,
                     "inventory": ["bow"], "name": "Boulon"})
        etat.pop("consumables", None)
        fichier.write_text(json.dumps(etat), encoding="utf-8")

        s = self._session()
        self.assertEqual(s.tokens, 9)
        self.assertEqual(s.inventory, ["bow"])
        self.assertEqual(s.name, "Boulon")
        self.assertEqual(s.consumables, {})

    def test_un_stock_corrompu_ne_bloque_pas_le_demarrage(self) -> None:
        """Le §14 borne plutôt que de rejeter : une valeur absurde vient d'une
        édition manuelle ou d'une migration ratée, et dans les deux cas le pet
        doit démarrer."""
        s = self._session()
        s.store.set(consumables={"meal": "trois", "kit": -2, "inconnu": 4})
        self.assertEqual(s.consumables, {})

    def test_les_articles_retires_deviennent_des_kits(self) -> None:
        """Lot L15 : la lingette et le savon n'existent plus, mais ils ont été
        **payés**. Les faire disparaître d'un inventaire serait une punition
        rétroactive, et le §12 l'interdit. Ils valent un bain chacun.

        Vérifié sur la session, qui est ce que voit l'inventaire, et non
        seulement sur le fichier : c'est la session qui décide ce qui
        s'affiche.
        """
        s = self._session()
        s.store.set(consumables={"wipe": 2, "soap": 1, "meal": 1})
        self.assertEqual(s.consumables, {"kit": 3, "meal": 1})

    def test_un_article_inconnu_ne_reste_pas_dans_l_inventaire(self) -> None:
        """Une clé venue d'une version plus récente, ou d'une édition à la
        main, ne doit pas produire une case qu'on ne sait ni dessiner ni
        utiliser."""
        s = self._session()
        s.store.set(consumables={"licorne": 5})
        self.assertEqual(s.consumables, {})


if __name__ == "__main__":
    unittest.main()
