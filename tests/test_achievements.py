"""Critères d'acceptation des trophées (lot L22).

Trois couches, testées séparément parce qu'elles ne cassent pas de la même
façon : le **catalogue** (des seuils et des récompenses, sans code), le **suivi**
(des faits et du temps qui deviennent des compteurs), et la **page** (une liste
qui défile et des récompenses qu'on encaisse).

Les deux points qui méritaient le plus d'attention, et qui ont chacun leur test
nommé :

- une séance de deux heures devant une vidéo doit compter pour **une**, pas pour
  vingt-huit mille — c'est le seul compteur alimenté par un `dt` ;
- une récompense de trophée ne passe **pas** sous le plafond quotidien, sans quoi
  débloquer « 1 an » un jour où l'on a joué perdrait 75 des 100 jetons.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from pet.brain import achievements as A
from pet.brain.economy import DAILY_CAP
from pet.feedback import EVENTS, Feedback


class Ctx:
    """Contexte minimal : le suivi ne lit que l'état."""

    def __init__(self, state: str = "idle") -> None:
        self.state = state


class CatalogueTest(unittest.TestCase):
    """Le catalogue est une donnée : ce sont ses invariants qu'on vérifie."""

    def test_les_cles_sont_uniques(self) -> None:
        cles = [t.cle for t in A.TROPHEES]
        self.assertEqual(len(cles), len(set(cles)))

    def test_l_ordre_d_affichage_couvre_tout_le_catalogue(self) -> None:
        """Une famille oubliée dans `FAMILLES` ferait disparaître ses trophées
        de la page sans qu'aucune erreur ne soit levée."""
        self.assertEqual(sorted(A.ORDRE), sorted(t.cle for t in A.TROPHEES))

    def test_les_recompenses_suivent_le_bareme(self) -> None:
        for trophee in A.TROPHEES:
            self.assertIn(trophee.recompense, A.RECOMPENSES,
                          "%s verse un montant hors barème" % trophee.cle)

    def test_les_cinq_trophees_imposes_existent_avec_leurs_seuils(self) -> None:
        """Ceux-là ont été dictés, jour pour jour."""
        attendus = {"jour_1": 1, "semaine_1": 7, "mois_1": 30,
                    "mois_6": 182, "anniversaire": 365}
        for cle, jours in attendus.items():
            trophee = A.BY_KEY[cle]
            self.assertEqual(trophee.mesure, A.AGE)
            self.assertEqual(trophee.cible, jours)
        self.assertEqual(A.BY_KEY["anniversaire"].recompense, 100)

    def test_chaque_trophee_a_un_titre_et_une_description(self) -> None:
        for trophee in A.TROPHEES:
            self.assertTrue(trophee.titre.strip(), trophee.cle)
            self.assertTrue(trophee.description.strip(), trophee.cle)

    def test_chaque_icone_existe(self) -> None:
        """Une icône inconnue dessine un carré : la ligne aurait l'air cassée."""
        from pet.ui.icons import BUILDERS

        for trophee in A.TROPHEES:
            self.assertIn(trophee.icone, BUILDERS, trophee.cle)

    def test_aucune_mesure_n_est_orpheline(self) -> None:
        """Une mesure que personne n'alimente donne une barre immobile.

        Le contrôle est fait sur le **code source** du suivi et de la session :
        c'est le seul moyen de repérer un compteur déclaré, affiché, et jamais
        incrémenté — un défaut qui ne lève jamais et ne se voit qu'en jouant
        des semaines.
        """
        import pathlib

        racine = pathlib.Path(__file__).resolve().parents[1] / "pet"
        source = ((racine / "brain" / "tracker.py").read_text(encoding="utf-8")
                  + (racine / "brain" / "session.py").read_text(encoding="utf-8"))
        noms = {valeur: nom for nom, valeur in vars(A).items()
                if isinstance(valeur, str) and not nom.startswith("_")}
        for trophee in A.TROPHEES:
            if trophee.mesure in A.DERIVEES:
                continue
            constante = noms[trophee.mesure]
            # Les deux formes d'appel du même symbole : le suivi importe le
            # module sous `A`, la session sous son nom complet.
            alimentee = ("A." + constante in source
                         or "achievements." + constante in source)
            self.assertTrue(alimentee,
                            "la mesure %s n'est alimentée nulle part"
                            % trophee.mesure)

    def test_l_avancement_est_borne(self) -> None:
        trophee = A.BY_KEY["calin"]
        self.assertEqual(A.progres(trophee, {}), 0.0)
        self.assertAlmostEqual(A.progres(trophee, {A.CARESSES: 50}), 0.5)
        self.assertEqual(A.progres(trophee, {A.CARESSES: 900}), 1.0)
        # Une valeur illisible ne doit pas faire tomber la page.
        self.assertEqual(A.progres(trophee, {A.CARESSES: "beaucoup"}), 0.0)

    def test_le_fait_du_deblocage_est_au_catalogue_du_bus(self) -> None:
        self.assertIn("succes_debloque", EVENTS)
        self.assertIn("recompense_encaissee", EVENTS)


class _Isole(unittest.TestCase):
    """Base des tests qui écrivent : répertoire de données jetable.

    Sans cette redirection, la suite écrirait dans le `%LOCALAPPDATA%` de
    l'utilisateur et abîmerait son robot. C'est arrivé une fois.
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

    def _session(self, horloge=None):
        from pet.brain.session import Session

        s = Session(clock=horloge or time.time)
        s.load()
        return s


class NaissanceTest(_Isole):
    def test_un_nouveau_robot_nait_maintenant(self) -> None:
        s = self._session()
        self.assertAlmostEqual(s.born_at, time.time(), delta=60)
        self.assertLess(s.mesures()[A.AGE], 0.01)

    def test_la_naissance_est_estimee_sur_le_journal(self) -> None:
        """Les trophées de temps sont arrivés après les premiers robots.

        Le journal est le seul fichier dont la date de création survive : les
        documents JSON sont remplacés par `os.replace`, qui leur en donne une
        neuve à chaque enregistrement.
        """
        from pet.state import save

        journal = save.app_dir() / "debug.log"
        journal.write_text("", encoding="utf-8")
        vieux = time.time() - 40 * 86400
        os.utime(journal, (vieux, vieux))
        # `st_ctime` ne se change pas sous Windows : on vérifie donc que
        # l'estimation ne dépasse jamais l'instant présent et qu'elle prend bien
        # le journal pour repère.
        estimee = save.estimate_birth()
        self.assertLessEqual(estimee, time.time())
        self.assertAlmostEqual(estimee, journal.stat().st_ctime, delta=1.0)

    def test_une_naissance_dans_le_futur_est_ramenee(self) -> None:
        """Une horloge reculée donnerait un âge négatif."""
        s = self._session()
        s.store.set(born_at=time.time() + 10 * 86400)
        s.flush(force=True)
        autre = self._session()
        self.assertLessEqual(autre.born_at, time.time() + 1.0)
        self.assertGreaterEqual(autre.mesures()[A.AGE], 0.0)

    def test_l_age_debloque_les_paliers(self) -> None:
        s = self._session()
        s.store.set(born_at=time.time() - 8 * 86400)
        neufs = s.check_achievements()
        self.assertIn("jour_1", neufs)
        self.assertIn("semaine_1", neufs)
        self.assertNotIn("mois_1", neufs)


class RecompenseTest(_Isole):
    def test_une_recompense_ne_se_prend_qu_une_fois(self) -> None:
        s = self._session()
        s.bump(A.POUSSEES, 1)
        s.check_achievements()
        self.assertEqual(s.claim("petite_poussee"), 1)
        self.assertEqual(s.claim("petite_poussee"), 0)
        self.assertEqual(s.tokens, 1)

    def test_un_trophee_non_debloque_ne_paie_pas(self) -> None:
        s = self._session()
        self.assertEqual(s.claim("anniversaire"), 0)
        self.assertEqual(s.tokens, 0)

    def test_la_recompense_echappe_au_plafond_quotidien(self) -> None:
        """Le point le plus important du lot.

        Le plafond borne ce qu'une journée de présence rapporte. Un trophée
        n'est pas de la présence, et le faire passer dessous ferait perdre
        75 des 100 jetons de l'anniversaire un jour où l'on a joué.
        """
        s = self._session()
        self.assertEqual(s.economy.award(DAILY_CAP), DAILY_CAP)
        self.assertEqual(s.tokens_remaining, 0)

        s.store.set(born_at=time.time() - 400 * 86400)
        s.check_achievements()
        avant = s.tokens
        self.assertEqual(s.claim("anniversaire"), 100)
        self.assertEqual(s.tokens, avant + 100)
        # Et le quota du jour n'a pas bougé pour autant : encaisser un trophée
        # ne doit pas non plus **rouvrir** ce qui est déjà gagné.
        self.assertEqual(s.tokens_remaining, 0)

    def test_ce_qui_attend_est_liste_dans_l_ordre_du_catalogue(self) -> None:
        s = self._session()
        s.bump(A.POUSSEES, 1)
        s.bump(A.CARESSES, 1)
        s.store.set(born_at=time.time() - 2 * 86400)
        s.check_achievements()
        attendus = [c for c in A.ORDRE if c in s.achievements]
        self.assertEqual(s.claimable(), attendus)
        s.claim(attendus[0])
        self.assertEqual(s.claimable(), attendus[1:])

    def test_tout_survit_a_un_rechargement(self) -> None:
        s = self._session()
        s.bump(A.PARTIES, 3)
        s.check_achievements()
        s.claim("premiere_partie")
        s.flush(force=True)

        autre = self._session()
        self.assertEqual(autre.stats.get(A.PARTIES), 3.0)
        self.assertIn("premiere_partie", autre.achievements)
        self.assertEqual(autre.claimed, ["premiere_partie"])
        self.assertEqual(autre.tokens, 1)

    def test_une_sauvegarde_d_avant_les_trophees_se_charge(self) -> None:
        """Migration additive : rien d'existant ne change de forme."""
        from pet.state import save

        save.write_json_atomic(save.app_dir() / "state.json", {
            "schema_version": 1, "tokens": 7, "name": "Boulon",
            "needs": {"hunger": 50.0, "fun": 50.0, "energy": 50.0,
                      "hygiene": 50.0},
        })
        s = self._session()
        self.assertEqual(s.tokens, 7)
        self.assertEqual(s.name, "Boulon")
        self.assertEqual(s.achievements, {})
        self.assertEqual(s.claimed, [])
        self.assertGreater(s.born_at, 0.0)

    def test_un_fichier_bricole_ne_donne_pas_de_trophee(self) -> None:
        """Encaissé sans avoir été obtenu : la clé est écartée au chargement.

        Le §14 refuse le chiffrement, donc un fichier édité à la main est un
        cas normal. Ce qu'on ne veut pas, c'est qu'il fasse **disparaître** une
        récompense que l'utilisateur n'a jamais touchée.
        """
        from pet.state import save

        save.write_json_atomic(save.app_dir() / "state.json", {
            "schema_version": 1,
            "claimed": ["anniversaire"],
            "achievements": {"sirop_derable": 1.0},
        })
        s = self._session()
        self.assertEqual(s.claimed, [])
        self.assertEqual(s.achievements, {})


class RattrapageTest(_Isole):
    """Ce que la sauvegarde d'un robot déjà vécu prouve toute seule."""

    def _ancienne_sauvegarde(self, **champs) -> None:
        from pet.state import save

        base = {"schema_version": 1,
                "needs": {"hunger": 50.0, "fun": 50.0, "energy": 50.0,
                          "hygiene": 50.0}}
        base.update(champs)
        save.write_json_atomic(save.app_dir() / "state.json", base)

    def test_un_robot_baptise_a_son_bapteme(self) -> None:
        """Le fait est passé depuis des semaines : personne ne le rejouera."""
        self._ancienne_sauvegarde(name="Boulon")
        s = self._session()
        self.assertEqual(s.stats.get(A.BAPTEME), 1.0)
        s.check_achievements()
        self.assertIn("bapteme", s.achievements)

    def test_un_record_inscrit_prouve_une_partie(self) -> None:
        self._ancienne_sauvegarde(best_scores={"rally": 12})
        s = self._session()
        self.assertEqual(s.stats.get(A.PARTIES), 1.0)
        self.assertEqual(s.stats.get(A.RECORDS), 1.0)
        # Et le score lui-même est une mesure dérivée : il compte tel quel.
        self.assertIn("rally_10", A.obtenus(s.mesures()))

    def test_un_inventaire_prouve_des_achats(self) -> None:
        self._ancienne_sauvegarde(inventory=["bow", "cap"], tokens=4)
        s = self._session()
        self.assertEqual(s.stats.get(A.ACHATS), 2.0)
        self.assertEqual(s.stats.get(A.JETONS), 4.0)

    def test_rien_n_est_invente(self) -> None:
        """Les repas et les bains ne se déduisent d'aucun champ : ils restent
        à zéro. Un compteur en retard vaut mieux qu'un compteur inventé."""
        self._ancienne_sauvegarde(name="Boulon", tokens=9,
                                  best_scores={"cups": 3})
        s = self._session()
        self.assertIsNone(s.stats.get(A.REPAS))
        self.assertIsNone(s.stats.get(A.BAINS))
        self.assertIsNone(s.stats.get(A.CARESSES))

    def test_le_rattrapage_n_a_lieu_qu_une_fois(self) -> None:
        """Il ne doit pas écraser des compteurs qui ont commencé à vivre."""
        self._ancienne_sauvegarde(name="Boulon", inventory=["bow", "cap"])
        s = self._session()
        s.bump(A.ACHATS, 5)                        # sept achats au total
        s.flush(force=True)
        reprise = self._session()
        self.assertEqual(reprise.stats.get(A.ACHATS), 7.0)

    def test_un_robot_tout_neuf_ne_recoit_rien(self) -> None:
        s = self._session()
        self.assertEqual(s.claimable(), [])
        self.assertIsNone(s.stats.get(A.BAPTEME))


class SuiviTest(_Isole):
    def _suivi(self):
        from pet.brain.tracker import Suivi

        session = self._session()
        bus = Feedback()
        vus: list[str] = []
        bus.subscribe("succes_debloque", lambda cle: vus.append(cle))
        suivi = Suivi(session, bus)
        suivi.subscribe()
        return session, suivi, bus, vus

    def test_une_seance_de_deux_heures_compte_pour_une(self) -> None:
        """Le seul compteur alimenté par un `dt`, donc le seul qui puisse
        compter vingt-huit mille fois la même chose."""
        from pet.brain.tracker import SEANCE

        session, suivi, _, _ = self._suivi()
        ctx = Ctx("watching")
        for _ in range(int(7200 / 0.25)):
            suivi.tick(0.25, ctx)
        self.assertEqual(session.stats.get(A.VIDEOS), 1.0)
        self.assertAlmostEqual(session.stats.get(A.HEURES_VIDEO), 2.0, places=3)
        self.assertGreater(SEANCE, 60.0)

    def test_une_video_trop_courte_ne_compte_pas(self) -> None:
        session, suivi, _, _ = self._suivi()
        for _ in range(240):                       # une minute
            suivi.tick(0.25, Ctx("watching"))
        self.assertIsNone(session.stats.get(A.VIDEOS))

    def test_une_pause_courte_ne_coupe_pas_la_seance(self) -> None:
        """Une coupure publicitaire ne doit pas compter un second film."""
        from pet.brain.tracker import PAUSE, SEANCE

        session, suivi, _, _ = self._suivi()
        for _ in range(int((SEANCE + 60) / 0.5)):
            suivi.tick(0.5, Ctx("watching"))
        for _ in range(int((PAUSE / 2) / 0.5)):
            suivi.tick(0.5, Ctx("idle"))
        for _ in range(int((SEANCE + 60) / 0.5)):
            suivi.tick(0.5, Ctx("watching"))
        self.assertEqual(session.stats.get(A.VIDEOS), 1.0)

    def test_une_vraie_coupure_ouvre_une_autre_seance(self) -> None:
        from pet.brain.tracker import PAUSE, SEANCE

        session, suivi, _, _ = self._suivi()
        for _ in range(int((SEANCE + 60) / 0.5)):
            suivi.tick(0.5, Ctx("watching"))
        for _ in range(int((PAUSE + 60) / 0.5)):
            suivi.tick(0.5, Ctx("idle"))
        for _ in range(int((SEANCE + 60) / 0.5)):
            suivi.tick(0.5, Ctx("watching"))
        self.assertEqual(session.stats.get(A.VIDEOS), 2.0)

    def test_les_faits_du_bus_alimentent_les_compteurs(self) -> None:
        session, _, bus, _ = self._suivi()
        bus.emit("pousse")
        bus.emit("pousse")
        bus.emit("partie_finie", jeu="rally", score=4, record=True)
        bus.emit("article_achete", emplacement="hat", cle="bow")
        bus.emit("apparence_changee", param="palette.body", cle="turquoise")
        bus.emit("nom_donne", nom="Boulon")
        self.assertEqual(session.stats.get(A.POUSSEES), 2.0)
        self.assertEqual(session.stats.get(A.PARTIES), 1.0)
        self.assertEqual(session.stats.get(A.RECORDS), 1.0)
        self.assertEqual(session.stats.get(A.ACHATS), 1.0)
        self.assertEqual(session.stats.get(A.COULEURS), 1.0)
        self.assertEqual(session.stats.get(A.BAPTEME), 1.0)

    def test_porter_un_chapeau_ne_compte_pas_comme_une_couleur(self) -> None:
        session, _, bus, _ = self._suivi()
        bus.emit("apparence_changee", param="hat", cle="bow")
        self.assertIsNone(session.stats.get(A.COULEURS))

    def test_seule_une_chute_franche_compte(self) -> None:
        from pet.brain.tracker import CHUTE_FRANCHE

        session, _, bus, _ = self._suivi()
        bus.emit("atterri", force=CHUTE_FRANCHE - 0.2, vitesse=600.0)
        self.assertIsNone(session.stats.get(A.CHUTES))
        bus.emit("atterri", force=1.0, vitesse=1400.0)
        self.assertEqual(session.stats.get(A.CHUTES), 1.0)

    def test_un_repas_de_sauvetage_se_juge_sur_la_faim_d_avant(self) -> None:
        """Le soin est **appliqué** avant d'être annoncé : lue après coup, la
        satiété est déjà remontée et le trophée serait inatteignable."""
        from pet.brain.brain import Brain

        session, suivi, bus, _ = self._suivi()
        cerveau = Brain()
        cerveau.needs.hunger = 8.0
        suivi.tick(0.25, Ctx(), cerveau)
        cerveau.needs.hunger = 60.0                # la gamelle a fait effet
        bus.emit("soin_accepte", soin="meal")
        self.assertEqual(session.stats.get(A.REPAS_URGENCE), 1.0)
        self.assertEqual(session.stats.get(A.REPAS), 1.0)

    def test_une_caresse_hors_sieste_ne_reveille_personne(self) -> None:
        from pet.brain.brain import Brain

        session, suivi, bus, _ = self._suivi()
        cerveau = Brain()
        cerveau.current = "idle_wander"
        suivi.tick(0.25, Ctx(), cerveau)
        bus.emit("soin_accepte", soin="pet")
        self.assertIsNone(session.stats.get(A.CARESSES_SIESTE))

        cerveau.current = "nap"
        suivi.tick(0.25, Ctx(), cerveau)
        bus.emit("soin_accepte", soin="pet")
        self.assertEqual(session.stats.get(A.CARESSES_SIESTE), 1.0)
        self.assertEqual(session.stats.get(A.CARESSES), 2.0)

    def test_le_bain_est_compte_par_son_propre_fait(self) -> None:
        """Le kit émet **aussi** `soin_accepte` en fin de rituel : le compter
        des deux côtés doublerait chaque bain."""
        session, _, bus, _ = self._suivi()
        bus.emit("bain_fini", complet=True)
        bus.emit("soin_accepte", soin="kit")
        self.assertEqual(session.stats.get(A.BAINS), 1.0)
        self.assertEqual(session.stats.get(A.BAINS_COMPLETS), 1.0)
        self.assertIsNone(session.stats.get(A.REPAS))

    def test_la_serie_de_bains_se_casse_puis_repart(self) -> None:
        session, _, bus, _ = self._suivi()
        for _ in range(2):
            bus.emit("bain_fini", complet=True)
        bus.emit("bain_fini", complet=False)
        bus.emit("bain_fini", complet=True)
        self.assertEqual(session.stats.get(A.SERIE_BAINS), 2.0)
        self.assertEqual(session.stats.get("serie_courante"), 1.0)

    def test_la_serie_survit_a_une_fermeture(self) -> None:
        """Perdre sa série parce qu'on a éteint son ordinateur serait une
        punition, et le §12 les interdit."""
        from pet.brain.tracker import Suivi

        session, _, bus, _ = self._suivi()
        for _ in range(2):
            bus.emit("bain_fini", complet=True)
        session.flush(force=True)

        reprise = self._session()
        bus2 = Feedback()
        suivi = Suivi(reprise, bus2)
        suivi.subscribe()
        bus2.emit("bain_fini", complet=True)
        self.assertEqual(reprise.stats.get(A.SERIE_BAINS), 3.0)
        self.assertIn("rien_ne_depasse", reprise.achievements)

    def test_un_trophee_n_est_annonce_qu_une_fois(self) -> None:
        session, _, bus, vus = self._suivi()
        for _ in range(5):
            bus.emit("pousse")
        self.assertEqual(vus.count("petite_poussee"), 1)

    def test_un_trophee_obtenu_ne_se_reprend_jamais(self) -> None:
        """La collection se complète, puis on retire un chapeau."""
        session, suivi, _, _ = self._suivi()
        session.store.set(inventory=["bow", "cap", "crown"])
        suivi.verifier()
        self.assertIn("dressing", session.achievements)
        session.store.set(inventory=["bow"])
        suivi.verifier()
        self.assertIn("dressing", session.achievements)

    def test_les_jetons_gagnes_alimentent_la_bourse_des_trophees(self) -> None:
        session, suivi, _, _ = self._suivi()
        session.award_tokens(1)
        suivi.verifier()
        self.assertIn("premier_jeton", session.achievements)

    def test_le_plafond_atteint_compte_une_seule_fois(self) -> None:
        session, suivi, _, _ = self._suivi()
        for _ in range(DAILY_CAP + 5):
            session.award_tokens(1)
        self.assertEqual(session.stats.get(A.JOURS_PLEINS), 1.0)

    def test_une_journee_de_presence_est_comptee_une_fois(self) -> None:
        session, suivi, _, _ = self._suivi()
        for _ in range(20):
            suivi.tick(0.25, Ctx())
        self.assertEqual(session.stats.get(A.JOURS_VUS), 1.0)




class PageTest(_Isole):
    """La page des trophées : une liste qui défile, et des jetons à prendre.

    C'est la première liste du panneau après huit pages de grilles, et ce qu'on
    vérifie ici est précisément ce qu'une grille n'avait jamais eu à garantir :
    que le défilement déplace **ensemble** ce qu'on voit et ce qu'on clique.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from .qt_app import ensure_app
        ensure_app()

    def _panel(self):
        from pet.ui.panel import CarePanel

        session = self._session()
        panel = CarePanel(session, {})
        panel.open_page("trophies")
        return panel, session

    def test_la_page_est_au_menu(self) -> None:
        from pet.ui.panel import MENU_ACTIONS, PAGES, PAGE_TITLES

        self.assertIn("trophies", PAGES)
        self.assertIn("trophies", MENU_ACTIONS)
        self.assertTrue(PAGE_TITLES["trophies"].strip())

    def test_la_liste_montre_tout_le_catalogue(self) -> None:
        panel, _ = self._panel()
        lignes = panel._layout().rows
        self.assertEqual(len(lignes), len(A.TROPHEES))
        self.assertEqual({ligne.title for ligne in lignes},
                         {t.titre for t in A.TROPHEES})

    def test_ce_qui_attend_est_en_tete(self) -> None:
        panel, session = self._panel()
        session.bump(A.POUSSEES, 1)
        session.check_achievements()
        self.assertEqual(panel._layout().rows[0].title,
                         A.BY_KEY["petite_poussee"].titre)

    def test_seul_un_trophee_obtenu_et_non_encaisse_porte_son_bouton(self) -> None:
        panel, session = self._panel()
        self.assertEqual([b for b in panel._layout().buttons
                          if b.action.startswith("claim:")], [])

        session.bump(A.POUSSEES, 1)
        session.check_achievements()
        boutons = [b for b in panel._layout().buttons
                   if b.action.startswith("claim:")]
        self.assertEqual([b.action for b in boutons], ["claim:petite_poussee"])
        self.assertEqual(boutons[0].price,
                         A.BY_KEY["petite_poussee"].recompense)

        session.claim("petite_poussee")
        self.assertEqual([b for b in panel._layout().buttons
                          if b.action.startswith("claim:")], [])

    def test_le_clic_demande_l_encaissement(self) -> None:
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        panel, session = self._panel()
        session.bump(A.POUSSEES, 1)
        session.check_achievements()
        recues: list[str] = []
        panel.reward_claimed.connect(recues.append)

        bouton = next(b for b in panel._layout().buttons
                      if b.action.startswith("claim:"))
        centre = bouton.rect.center()
        panel.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(centre),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        self.assertEqual(recues, ["petite_poussee"])

    def test_le_defilement_est_borne(self) -> None:
        panel, _ = self._panel()
        panel._scroll_to(-500.0)
        self.assertEqual(panel._defilement, 0.0)
        panel._scroll_to(1e6)
        layout = panel._layout()
        self.assertAlmostEqual(
            panel._defilement,
            panel._course(len(layout.rows), layout.clip), places=3)

    def test_le_defilement_deplace_la_ligne_et_son_bouton_ensemble(self) -> None:
        """L'invariant de la page.

        Décaler la peinture seule laisserait les zones cliquables immobiles :
        on encaisserait le trophée d'à côté.
        """
        panel, session = self._panel()
        session.bump(A.POUSSEES, 1)
        session.check_achievements()

        avant = panel._layout()
        ligne0 = avant.rows[0].rect.top()
        bouton0 = next(b for b in avant.buttons
                       if b.action.startswith("claim:")).rect.top()
        panel._scroll_to(40.0)
        apres = panel._layout()
        self.assertAlmostEqual(apres.rows[0].rect.top(), ligne0 - 40.0)
        bouton1 = next(b for b in apres.buttons
                       if b.action.startswith("claim:")).rect.top()
        self.assertAlmostEqual(bouton1, bouton0 - 40.0)

    def test_un_bouton_sorti_du_cadre_ne_repond_plus(self) -> None:
        """Il reste dans la mise en page, décalé hors de la fenêtre. Sans
        découpe du test de clic, il continuerait de répondre par-dessus le
        titre de la page."""
        from PySide6.QtCore import QPointF

        panel, session = self._panel()
        session.bump(A.POUSSEES, 1)
        session.check_achievements()
        panel._scroll_to(1e6)                      # tout en bas
        layout = panel._layout()
        bouton = next(b for b in layout.buttons
                      if b.action.startswith("claim:"))
        self.assertLess(bouton.rect.center().y(), layout.clip.top())
        self.assertEqual(panel._at(QPointF(bouton.rect.center())), -1)

    def test_les_lignes_disent_leur_avancement(self) -> None:
        panel, session = self._panel()
        session.bump(A.CARESSES, 50)
        lignes = {ligne.title: ligne for ligne in panel._layout().rows}
        calin = lignes[A.BY_KEY["calin"].titre]
        self.assertAlmostEqual(calin.progress, 0.5)
        self.assertFalse(calin.unlocked)

    def test_la_page_montre_le_solde(self) -> None:
        """Encaisser fait monter un nombre : il faut qu'il soit à l'écran."""
        panel, session = self._panel()
        self.assertEqual(panel._layout().tokens, session.tokens)


class ToastTest(unittest.TestCase):
    """La bannière du coin bas droit."""

    @classmethod
    def setUpClass(cls) -> None:
        from .qt_app import ensure_app
        ensure_app()

    def test_une_banniere_finit_toujours_par_partir(self) -> None:
        from pet.ui.toast import ENTREE, SORTIE, TENUE, Toast

        toast = Toast()
        toast.annoncer(A.BY_KEY["anniversaire"].titre)
        self.assertTrue(toast.titre)
        for _ in range(int((ENTREE + TENUE + SORTIE + 1.0) * 60)):
            toast.step(1.0 / 60.0)
        self.assertEqual(toast.titre, "")
        self.assertFalse(toast.isVisible())
        toast.close()

    def test_les_annonces_defilent_l_une_apres_l_autre(self) -> None:
        from pet.ui.toast import ENTREE, SORTIE, TENUE, Toast

        toast = Toast()
        toast.annoncer("Jour 1")
        toast.annoncer("Semaine 1")
        self.assertEqual(toast.titre, "Jour 1")
        for _ in range(int((ENTREE + TENUE + SORTIE + 0.2) * 60)):
            toast.step(1.0 / 60.0)
        self.assertEqual(toast.titre, "Semaine 1")
        toast.close()

    def test_une_salve_tient_moins_longtemps_qu_une_annonce_seule(self) -> None:
        """Sept trophées rattrapés d'un coup ne doivent pas occuper le coin de
        l'écran une demi-minute : tant qu'il y a du monde derrière, chaque
        bannière tient moins longtemps."""
        from pet.ui.toast import TENUE, TENUE_FILE, Toast

        toast = Toast()
        toast.annoncer("Jour 1")
        self.assertEqual(toast.passage.tenue, TENUE)   # seule, donc au complet

        toast.annoncer("Semaine 1")
        toast.annoncer("Mois 1")
        while toast.titre == "Jour 1":
            toast.step(1.0 / 60.0)
        self.assertEqual(toast.passage.tenue, TENUE_FILE)
        self.assertLess(TENUE_FILE, TENUE)
        toast.close()

    def test_la_file_est_bornee(self) -> None:
        """Trente-neuf trophées rattrapés d'un coup feraient deux minutes
        d'annonces : au-delà, la page des trophées dit la suite mieux."""
        from pet.ui.toast import FILE_MAX, Toast

        toast = Toast()
        for index in range(FILE_MAX * 3):
            toast.annoncer("Trophée %d" % index)
        self.assertLessEqual(len(toast._file), FILE_MAX)
        toast.close()

    def test_une_annonce_vide_est_ignoree(self) -> None:
        from pet.ui.toast import Toast

        toast = Toast()
        toast.annoncer("   ")
        self.assertEqual(toast.titre, "")
        toast.close()

    def test_la_banniere_se_pose_en_bas_a_droite(self) -> None:
        from pet.ui.toast import HEIGHT, MARGE, WIDTH, Toast

        toast = Toast()
        toast.set_corner((0, 0, 1920, 1040), 1.0)
        toast.annoncer("Jour 1")
        for _ in range(60):                        # entrée terminée
            toast.step(1.0 / 60.0)
        self.assertEqual(toast.x(), 1920 - WIDTH - MARGE)
        self.assertEqual(toast.y(), 1040 - HEIGHT - MARGE)
        toast.close()

    def test_elle_laisse_passer_les_clics(self) -> None:
        """Elle se pose sur le bureau de quelqu'un qui travaille."""
        from PySide6.QtCore import Qt
        from pet.ui.toast import Toast

        toast = Toast()
        self.assertTrue(toast.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        toast.close()


if __name__ == "__main__":
    unittest.main()
