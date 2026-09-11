"""Critères d'acceptation du bus de rétroaction, lot L9.

Le bus est une couture : il ne fait presque rien, et c'est trois lots plus tard
qu'on saura s'il a été bien posé. Ces tests gardent les quatre propriétés dont
dépendra cette suite.

Aucune QApplication ici, volontairement : le bus doit rester utilisable depuis
le `brain`, que le §12 exige testable sans GPU ni interface.
"""

from __future__ import annotations

import unittest

from pet.feedback import EVENTS, Feedback, _IMPERATIFS


class CatalogueTest(unittest.TestCase):
    """Un événement décrit le monde, jamais l'effet attendu."""

    def test_aucun_nom_n_est_un_imperatif(self) -> None:
        """C'est toute la discipline du bus, et elle ne tient qu'à ça.

        `jouer_son_de_soin` lie l'émetteur à un consommateur unique : le jour
        où les particules veulent la même information, il faut soit un second
        événement, soit renommer celui-ci et retoucher tous les points
        d'émission. `soin_accepte` en accueille trois sans bouger.
        """
        fautifs = [nom for nom in EVENTS
                   if nom.startswith(_IMPERATIFS)]
        self.assertEqual(fautifs, [],
                         "ces noms décrivent un effet, pas un fait : %s" % fautifs)

    def test_les_noms_sont_au_passe_ou_substantifs(self) -> None:
        """Garde-fou grossier : un fait ne s'écrit pas à l'infinitif.

        On ne cherche pas à conjuguer — juste à attraper `ouvrir_panneau` posé
        à la place de `panneau_ouvert` au moment où quelqu'un l'écrit.
        """
        fautifs = [nom for nom in EVENTS
                   if nom.split("_")[0].endswith(("er", "ir")) and nom != "ouvrir"]
        self.assertEqual(fautifs, [], "noms à l'infinitif : %s" % fautifs)


class EmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = Feedback()

    def test_un_abonne_recoit_la_charge(self) -> None:
        recus = []
        self.bus.subscribe("page_changee", lambda page: recus.append(page))
        self.bus.emit("page_changee", page="shop")
        self.assertEqual(recus, ["shop"])

    def test_une_cle_de_charge_peut_s_appeler_nom(self) -> None:
        """Régression : `emit(self, nom, **charge)` entrait en collision.

        `emit("nom_donne", nom="Bip")` levait `got multiple values for argument
        'nom'`. Le paramètre est désormais positionnel seul, donc aucune clé de
        charge n'est réservée — et personne n'a à connaître le nom des
        variables internes du bus pour s'en servir.
        """
        recus = []
        self.bus.subscribe("nom_donne", lambda nom: recus.append(nom))
        self.bus.emit("nom_donne", nom="Bip")
        self.assertEqual(recus, ["Bip"])

    def test_un_fait_inconnu_est_refuse(self) -> None:
        """Une faute de frappe rendrait un abonnement silencieusement inerte,
        et on ne voit pas un son qui ne part pas."""
        with self.assertRaises(KeyError):
            self.bus.emit("panneau_ouvvert")
        with self.assertRaises(KeyError):
            self.bus.subscribe("panneau_ouvvert", lambda: None)

    def test_un_abonne_qui_leve_n_interrompt_pas_les_autres(self) -> None:
        """L'émetteur a déjà fait son travail quand il émet.

        Une étincelle ratée ne doit pas empêcher le son de partir, et surtout
        pas annuler le soin qui l'a provoquée.
        """
        vus = []

        def casse() -> None:
            raise RuntimeError("particule absente")

        self.bus.subscribe("panneau_ouvert", casse)
        self.bus.subscribe("panneau_ouvert", lambda: vus.append(1))
        with self.assertLogs("desky.feedback", level="ERROR"):
            self.bus.emit("panneau_ouvert")
        self.assertEqual(vus, [1])

    def test_l_abonnement_global_voit_tout(self) -> None:
        """C'est la forme dont le mélangeur audio aura besoin : voir passer
        l'ensemble pour appliquer sa propre table."""
        vus = []
        self.bus.subscribe_all(lambda nom, charge: vus.append((nom, charge)))
        self.bus.emit("bouton_active", action="status")
        self.bus.emit("panneau_ferme")
        self.assertEqual(vus, [("bouton_active", {"action": "status"}),
                               ("panneau_ferme", {})])

    def test_un_desabonnement_arrete_la_reception(self) -> None:
        """Un panneau détruit puis recréé ne doit pas laisser derrière lui un
        abonné qui peint dans un widget mort."""
        vus = []

        def ecoute() -> None:
            vus.append(1)

        self.bus.subscribe("panneau_ferme", ecoute)
        self.bus.emit("panneau_ferme")
        self.bus.unsubscribe("panneau_ferme", ecoute)
        self.bus.emit("panneau_ferme")
        self.assertEqual(vus, [1])

    def test_se_desabonner_deux_fois_ne_leve_pas(self) -> None:
        self.bus.unsubscribe("panneau_ferme", lambda: None)


if __name__ == "__main__":
    unittest.main()
