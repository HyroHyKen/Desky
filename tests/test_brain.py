"""Critères d'acceptation du comportement, lot L6 phase A (CDC §12, §14).

Cinq familles de vérifications :

- **L'économie inversée**, qui est le point que le §12 qualifie d'impératif.
  Chaque règle de la table de taux y est vérifiée séparément : `fun` monte à la
  frappe, `energy` remonte en l'absence, et `hunger` et `hygiene` sont les seuls
  à s'écouler avec le temps.
- **L'absence d'état irréversible**, également imposée par le §12. Un mois
  d'abandon suivi de soins doit tout ramener.
- **L'élection** : hystérésis, bonus de nouveauté, repos forcé, déterminisme.
- **Le temps** : plancher de durée, plafond, réflexes, délais de soin.
- **Les critères mesurés** du lot, rejoués sur journée synthétique — aucun
  clignotement, aucune action inatteignable ni dominante.

S'y ajoute la vérification que le vocabulaire symbolique du `brain` se résout
bien dans `anim` et `render`. C'est le seul test autorisé à importer les trois :
la cloison du §5 interdit au `brain` de les connaître, pas au test de vérifier
que les noms qu'il publie existent.

Aucun GPU, aucune fenêtre.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from pet.brain import needs as needs_mod
from pet.brain.actions import (
    ACTION_NAMES,
    BORED_FUN,
    NAP_ENERGY,
    BoredSlump,
    FollowCursor,
    IdleWander,
    Nap,
    default_actions,
)
from pet.brain.brain import REST_RATIO, TICK, Brain
from pet.brain.needs import (
    CARE_COOLDOWN,
    CARE_GAINS,
    FULL,
    MOOD_HAPPY,
    MOOD_NEUTRAL,
    NEEDS,
    OFFLINE_CAP_SECONDS,
    RATES,
    Needs,
    offline_elapsed,
)
from pet.brain.replay import replay
from pet.brain.sensors import SystemContext
from pet.brain.trace import PROFILES, Recorder, Sample, Trace, synthetic_day
from pet.brain.utility import (
    HYSTERESIS,
    RECENCY_BONUS,
    RECENCY_FULL,
    TRAVELS,
    Action,
    SelfState,
    elect,
)

PET_ROOT = Path(__file__).resolve().parents[1] / "pet"

HOUR = 3600.0


def ctx(state: str = "typing", **kwargs) -> SystemContext:
    return SystemContext(state=state, **kwargs)


def me(**kwargs) -> SelfState:
    base = dict(x=1000.0, pet_h=150.0, span=(0.0, 3840.0))
    base.update(kwargs)
    return SelfState(**base)


# ---------------------------------------------------------------------------
# L'économie inversée du §12
# ---------------------------------------------------------------------------


class InvertedEconomyTest(unittest.TestCase):
    """« Les besoins ne décroissent pas linéairement avec le temps. »"""

    def test_fun_monte_a_la_frappe_et_a_la_navigation(self) -> None:
        for state in ("typing", "browsing"):
            n = Needs(fun=40.0)
            n.tick(state, HOUR)
            self.assertGreater(n.fun, 40.0, f"fun devrait monter en {state}")

    def test_fun_descend_en_l_absence(self) -> None:
        for state in ("idle", "away"):
            n = Needs(fun=60.0)
            n.tick(state, HOUR)
            self.assertLess(n.fun, 60.0, f"fun devrait descendre en {state}")

    def test_energy_remonte_pendant_idle_et_away(self) -> None:
        for state in ("idle", "away"):
            n = Needs(energy=40.0)
            n.tick(state, HOUR)
            self.assertGreater(n.energy, 40.0)

    def test_energy_se_depense_en_activite(self) -> None:
        for state in ("typing", "browsing"):
            n = Needs(energy=80.0)
            n.tick(state, HOUR)
            self.assertLess(n.energy, 80.0)

    def test_hunger_et_hygiene_sont_les_seuls_a_s_ecouler(self) -> None:
        """Leur taux doit être négatif et **identique** dans tous les états."""
        for index, name in enumerate(NEEDS):
            colonne = {rates[index] for rates in RATES.values()}
            if name in ("hunger", "hygiene"):
                self.assertEqual(len(colonne), 1,
                                 f"{name} varie selon l'état, contre le §12")
                self.assertLess(colonne.pop(), 0.0)
            else:
                self.assertGreater(len(colonne), 1,
                                   f"{name} ne dépend pas du contexte")

    def test_la_table_couvre_tous_les_etats_du_capteur(self) -> None:
        from pet.brain.sensors import derive_state
        vus = {
            derive_state(0.0, 0.0, False),
            derive_state(0.0, 99.0, False),
            derive_state(1e9, 0.0, False),
            derive_state(200.0, 0.0, False),
            derive_state(0.0, 0.0, True),
        }
        for state in vus:
            self.assertIn(state, RATES, f"état {state!r} sans taux")

    def test_un_etat_inconnu_ne_leve_pas(self) -> None:
        n = Needs()
        n.tick("etat_de_demain", HOUR)
        self.assertTrue(all(0.0 <= getattr(n, k) <= FULL for k in NEEDS))

    def test_les_besoins_restent_bornes(self) -> None:
        n = Needs()
        for state in ("typing", "away"):
            n.tick(state, 400.0 * HOUR)
            for name in NEEDS:
                self.assertGreaterEqual(getattr(n, name), 0.0)
                self.assertLessEqual(getattr(n, name), FULL)

    def test_un_dt_nul_ou_negatif_ne_change_rien(self) -> None:
        n = Needs()
        avant = n.as_dict()
        n.tick("typing", 0.0)
        n.tick("typing", -HOUR)
        self.assertEqual(n.as_dict(), avant)


class NoIrreversibleStateTest(unittest.TestCase):
    """« Aucune mort, aucun état irréversible » (§12)."""

    def test_un_mois_d_abandon_est_entierement_rattrapable(self) -> None:
        n = Needs()
        n.tick("away", 30.0 * 24.0 * HOUR)
        # Le plancher est atteint, ce qui est permis : c'est l'irréversibilité
        # qui est interdite, pas le zéro.
        self.assertEqual(n.hunger, 0.0)

        for kind in CARE_GAINS:
            for _ in range(4):
                n.care(kind)
        # Chaque besoin remonte par **son** vecteur : `hunger` et `hygiene` par
        # le soin, `fun` par l'activité, `energy` par le repos. Faire suivre les
        # soins d'une seule tranche d'activité épuiserait justement `energy`.
        n.tick("typing", 4.0 * HOUR)
        n.tick("idle", 4.0 * HOUR)
        for name in NEEDS:
            self.assertGreater(getattr(n, name), 50.0,
                               f"{name} n'est pas remonté après soins")

    def test_aucun_besoin_ne_se_verrouille_a_zero(self) -> None:
        for name in NEEDS:
            n = Needs(**{k: 0.0 for k in NEEDS})
            monte = [s for s, r in RATES.items()
                     if r[NEEDS.index(name)] > 0.0] or ["typing"]
            for kind, gains in CARE_GAINS.items():
                if name in gains and gains[name] > 0:
                    n.care(kind)
            n.tick(monte[0], 8.0 * HOUR)
            self.assertGreater(getattr(n, name), 0.0,
                               f"{name} est irrécupérable")


class CareTest(unittest.TestCase):
    def test_un_soin_retourne_le_delta_reellement_applique(self) -> None:
        n = Needs(hunger=90.0)
        applied = n.care("feed")
        self.assertAlmostEqual(applied["hunger"], 10.0, places=6)
        self.assertEqual(n.hunger, FULL)

    def test_un_soin_sur_un_besoin_plein_ne_rend_rien(self) -> None:
        n = Needs(hunger=FULL)
        self.assertEqual(n.care("feed"), {})

    def test_un_soin_inconnu_ne_rend_rien(self) -> None:
        n = Needs()
        avant = n.as_dict()
        self.assertEqual(n.care("astiquer"), {})
        self.assertEqual(n.as_dict(), avant)

    def test_jouer_coute_de_l_energie(self) -> None:
        """Le couplage qui rend `nap` atteignable après une session de jeu."""
        n = Needs(fun=20.0, energy=60.0)
        n.care("play")
        self.assertGreater(n.fun, 20.0)
        self.assertLess(n.energy, 60.0)

    def test_chaque_soin_vise_un_besoin_connu(self) -> None:
        for kind, gains in CARE_GAINS.items():
            self.assertIn(kind, CARE_COOLDOWN, f"{kind} sans délai")
            for name in gains:
                self.assertIn(name, NEEDS)


class MoodTest(unittest.TestCase):
    def test_l_humeur_suit_le_besoin_le_plus_faible(self) -> None:
        n = Needs(hunger=90.0, fun=10.0, energy=90.0, hygiene=90.0)
        self.assertEqual(n.weakest()[0], "fun")
        self.assertEqual(n.mood(), needs_mod.MOOD_BY_NEED["fun"])

    def test_tout_comble_donne_un_visage_joyeux(self) -> None:
        n = Needs(**{k: MOOD_HAPPY + 1.0 for k in NEEDS})
        self.assertEqual(n.mood(), "joyeux")

    def test_la_bande_intermediaire_reste_neutre(self) -> None:
        n = Needs(**{k: 0.5 * (MOOD_HAPPY + MOOD_NEUTRAL) for k in NEEDS})
        self.assertEqual(n.mood(), "neutre")

    def test_chaque_besoin_a_son_propre_visage(self) -> None:
        """Distincts, sinon l'icône d'humeur ne dit pas ce qui manque."""
        visages = set(needs_mod.MOOD_BY_NEED.values())
        self.assertEqual(len(visages), len(NEEDS))
        self.assertEqual(set(needs_mod.MOOD_BY_NEED), set(NEEDS))

    def test_un_seuil_neutre_bas_garde_les_visages_tristes_rares(self) -> None:
        """Régression : à 45, une journée de bureau donnait un pet fâché.

        L'humeur étant portée par le besoin le **plus faible**, un seuil haut
        assombrit le pet dès qu'un seul de ses quatre besoins baisse un peu.
        """
        self.assertLessEqual(MOOD_NEUTRAL, 35.0)


class OfflineDecayTest(unittest.TestCase):
    def test_l_absence_est_plafonnee(self) -> None:
        semaine = 7.0 * 24.0 * HOUR
        self.assertEqual(offline_elapsed(semaine, 1.0), OFFLINE_CAP_SECONDS)

    def test_une_horloge_qui_recule_ne_credite_rien(self) -> None:
        """§14 : « détecter les reculs d'horloge, pas de crédit rétroactif »."""
        self.assertEqual(offline_elapsed(100.0, 500.0), 0.0)

    def test_un_premier_lancement_ne_facture_rien(self) -> None:
        self.assertEqual(offline_elapsed(time.time(), 0.0), 0.0)

    def test_une_courte_absence_est_facturee_telle_quelle(self) -> None:
        self.assertAlmostEqual(offline_elapsed(1000.0, 400.0), 600.0)

    def test_le_plafond_evite_le_retour_de_vacances_desastreux(self) -> None:
        n = Needs()
        n.tick("away", offline_elapsed(10.0 * 24.0 * HOUR, 1.0))
        self.assertGreater(n.hunger, 30.0,
                           "revenir de vacances devant un pet à plat est "
                           "exactement ce que le §12 interdit")


# ---------------------------------------------------------------------------
# L'élection
# ---------------------------------------------------------------------------


class _Fixed(Action):
    """Action de test à score constant."""

    def __init__(self, name: str, value: float, varies: bool = False,
                 available: bool = True) -> None:
        self.name = name
        self.value = value
        self.varies = varies
        self.available = available

    def is_available(self, needs, ctx_, me_) -> bool:
        return self.available

    def score(self, needs, ctx_, me_) -> float:
        return self.value


class ElectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.needs = Needs()
        self.ctx = ctx()
        self.me = me()

    def _elect(self, actions, current="", since=None):
        return elect(actions, self.needs, self.ctx, self.me, current,
                     since if since is not None else {})

    def test_le_meilleur_score_gagne(self) -> None:
        chosen, _ = self._elect([_Fixed("a", 0.3), _Fixed("b", 0.7)])
        self.assertEqual(chosen.name, "b")

    def test_l_hysteresis_vaut_le_bonus_du_paragraphe_12(self) -> None:
        self.assertAlmostEqual(HYSTERESIS, 1.15, places=6)

    def test_l_action_en_cours_gagne_a_egalite_approchee(self) -> None:
        """0,64 contre 0,60 : sans hystérésis, `a` perdrait à chaque tick."""
        chosen, _ = self._elect([_Fixed("a", 0.60), _Fixed("b", 0.64)],
                                current="a")
        self.assertEqual(chosen.name, "a")

    def test_l_hysteresis_ne_sauve_pas_un_ecart_franc(self) -> None:
        chosen, _ = self._elect([_Fixed("a", 0.60), _Fixed("b", 0.95)],
                                current="a")
        self.assertEqual(chosen.name, "b")

    def test_l_hysteresis_ne_penalise_pas_un_score_negatif(self) -> None:
        """Régression : un bonus proportionnel sur un négatif l'aggrave."""
        _, table = self._elect([_Fixed("a", -1.0)], current="a")
        self.assertGreaterEqual(table[0].hysteresis, 0.0)

    def test_le_bonus_de_nouveaute_ne_touche_que_les_ambiances(self) -> None:
        since = {"fixe": 0.0, "varie": RECENCY_FULL}
        _, table = self._elect(
            [_Fixed("fixe", 0.3), _Fixed("varie", 0.3, varies=True)],
            since=since)
        par_nom = {c.name: c for c in table}
        self.assertEqual(par_nom["fixe"].recency, 0.0)
        self.assertAlmostEqual(par_nom["varie"].recency, RECENCY_BONUS)

    def test_le_bonus_de_nouveaute_est_plafonne(self) -> None:
        _, table = self._elect([_Fixed("v", 0.0, varies=True)],
                               since={"v": 99.0 * RECENCY_FULL})
        self.assertAlmostEqual(table[0].recency, RECENCY_BONUS)

    def test_une_action_indisponible_ne_concourt_pas(self) -> None:
        chosen, table = self._elect(
            [_Fixed("a", 0.2), _Fixed("b", 9.0, available=False)])
        self.assertEqual(chosen.name, "a")
        self.assertEqual([c.name for c in table], ["a"])

    def test_une_action_au_repos_est_ecartee(self) -> None:
        chosen, _ = elect([_Fixed("a", 0.2), _Fixed("b", 9.0)], self.needs,
                          self.ctx, self.me, "", {}, blocked=frozenset({"b"}))
        self.assertEqual(chosen.name, "a")

    def test_les_egalites_suivent_l_ordre_de_la_liste(self) -> None:
        """Condition du rejeu : l'élection doit être déterministe."""
        for _ in range(5):
            chosen, _ = self._elect([_Fixed("premier", 0.5),
                                     _Fixed("second", 0.5)])
            self.assertEqual(chosen.name, "premier")

    def test_aucun_candidat_rend_none(self) -> None:
        chosen, table = self._elect([_Fixed("a", 1.0, available=False)])
        self.assertIsNone(chosen)
        self.assertEqual(table, [])


class ActionCatalogTest(unittest.TestCase):
    def test_les_neuf_actions_du_paragraphe_12_sont_la(self) -> None:
        """Les neuf du §12, plus celles ajoutées après le lot.

        `fetch_item` n'est pas au CDC : elle vient du remplacement du bouton de
        soin par un objet posé sur le bureau. Le §12 fixe un plancher, pas un
        plafond.
        """
        attendues = {
            "idle_wander", "follow_cursor", "sit_and_watch", "nap",
            "look_around", "sniff_around", "react_to_poke", "bored_slump",
            "happy_bounce",
        }
        self.assertTrue(attendues <= set(ACTION_NAMES),
                        "une action du §12 manque : %s"
                        % (attendues - set(ACTION_NAMES),))
        self.assertEqual(len(ACTION_NAMES), len(set(ACTION_NAMES)),
                         "des doublons de nom")

    def test_la_flanerie_est_l_action_plancher(self) -> None:
        """Toujours disponible : une élection doit toujours rendre quelque chose."""
        action = IdleWander()
        for state in RATES:
            self.assertTrue(action.is_available(Needs(), ctx(state),
                                                me(span=(0.0, 0.0))))

    def test_chaque_deplacement_demande_est_connu(self) -> None:
        for action in default_actions():
            self.assertIn(action.travel, TRAVELS)
            self.assertIn(action.plan().travel, TRAVELS)

    def test_la_disponibilite_ne_depend_d_aucune_grandeur_rapide(self) -> None:
        """Règle apprise en mesurant : la grille est grossière, le score fin.

        Une disponibilité posée sur la distance au curseur ou sur
        `idle_seconds` bascule en pleine action, court-circuite le plancher de
        durée et produisait 101 épisodes de moins d'une seconde par journée.
        """
        suivre = FollowCursor()
        base = dict(state="typing")
        for x in range(0, 3800, 40):
            proche = suivre.is_available(Needs(), ctx(cursor=(x, 500), **base),
                                         me())
            self.assertTrue(proche, "la disponibilité varie avec la distance")

        regarder = next(a for a in default_actions() if a.name == "look_around")
        for idle in (0.0, 1.0, 3.9, 4.1, 100.0):
            self.assertTrue(regarder.is_available(
                Needs(), ctx(idle_seconds=idle), me()))

    def test_le_suivi_ne_score_rien_quand_le_pet_est_deja_a_cote(self) -> None:
        suivre = FollowCursor()
        etat = me(x=1000.0)
        self.assertEqual(
            suivre.score(Needs(), ctx(cursor=(1010, 500)), etat), 0.0)
        self.assertGreater(
            suivre.score(Needs(), ctx(cursor=(1600, 500)), etat), 0.0)

    def test_le_suivi_ne_score_rien_a_l_autre_bout_du_bureau(self) -> None:
        suivre = FollowCursor()
        self.assertEqual(
            suivre.score(Needs(), ctx(cursor=(3800, 500)), me(x=100.0)), 0.0)

    def test_la_sieste_gagne_pendant_une_absence(self) -> None:
        """Décision §17.4 : il dort vraiment quand l'utilisateur est parti."""
        b = Brain()
        for _ in range(40):
            plan = b.update(TICK, ctx("away", idle_seconds=900.0), me())
        self.assertEqual(plan.action, "nap")
        self.assertFalse(plan.look_at_cursor,
                         "un pet endormi ne suit pas la souris")

    def test_la_sieste_monte_avec_la_fatigue(self) -> None:
        dodo = Nap()
        faible = dodo.score(Needs(energy=5.0), ctx("idle"), me())
        haute = dodo.score(Needs(energy=NAP_ENERGY - 1.0), ctx("idle"), me())
        self.assertGreater(faible, haute)

    def test_l_ennui_ne_score_que_sous_le_seuil(self) -> None:
        morose = BoredSlump()
        self.assertEqual(morose.score(Needs(fun=BORED_FUN), ctx(), me()), 0.0)
        self.assertGreater(morose.score(Needs(fun=0.0), ctx(), me()), 0.0)

    def test_seul_l_affaissement_porte_un_plafond(self) -> None:
        """Il faut un plafond là, et nulle part ailleurs.

        À `fun` nul l'affaissement bat toutes les ambiances : sans plafond, un
        pet délaissé resterait affaissé pour toujours. Les autres actions n'ont
        pas ce défaut et un plafond y couperait un comportement légitime — une
        sieste de nuit, un film de deux heures.
        """
        plafonnees = {a.name for a in default_actions() if a.max_seconds > 0.0}
        self.assertEqual(plafonnees, {"bored_slump"})


# ---------------------------------------------------------------------------
# Le temps
# ---------------------------------------------------------------------------


class BrainTimingTest(unittest.TestCase):
    def test_le_plancher_retient_l_action_en_cours(self) -> None:
        tenace = _Fixed("tenace", 0.5)
        tenace.min_seconds = 2.0
        rival = _Fixed("rival", 0.0)
        b = Brain(actions=[tenace, rival])
        b.update(TICK, ctx(), me())
        self.assertEqual(b.current, "tenace")

        rival.value = 5.0
        for _ in range(4):                      # 1,0 s : sous le plancher
            b.update(TICK, ctx(), me())
        self.assertEqual(b.current, "tenace", "le plancher n'a pas tenu")

        for _ in range(6):                      # au-delà du plancher
            b.update(TICK, ctx(), me())
        self.assertEqual(b.current, "rival")

    def test_le_plancher_ne_retient_pas_une_action_devenue_indisponible(self) -> None:
        fugace = _Fixed("fugace", 5.0)
        fugace.min_seconds = 10.0
        secours = _Fixed("secours", 0.1)
        b = Brain(actions=[fugace, secours])
        b.update(TICK, ctx(), me())
        self.assertEqual(b.current, "fugace")
        fugace.available = False
        b.update(TICK, ctx(), me())
        self.assertEqual(b.current, "secours")

    def test_le_plafond_met_l_action_au_repos(self) -> None:
        collante = _Fixed("collante", 0.9)
        collante.max_seconds = 1.0
        autre = _Fixed("autre", 0.3)
        b = Brain(actions=[collante, autre])
        for _ in range(8):
            b.update(TICK, ctx(), me())
        self.assertEqual(b.current, "autre", "le plafond n'a pas libéré le pet")

        # Le repos est temporaire, donc c'est le **retour** de l'action qu'il
        # faut observer, et non son état à un instant précis : le cycle
        # « action, repos, action » ne s'arrête jamais sur une image fixe.
        repos = collante.max_seconds * REST_RATIO
        revenue = False
        for _ in range(int((repos + collante.max_seconds) / TICK) + 4):
            b.update(TICK, ctx(), me())
            revenue = revenue or b.current == "collante"
        self.assertTrue(revenue, "le repos ne s'est jamais levé")

    def test_le_clic_bat_tout_y_compris_le_sommeil(self) -> None:
        b = Brain(Needs(energy=0.0))
        for _ in range(40):
            b.update(TICK, ctx("away", idle_seconds=900.0), me())
        self.assertEqual(b.current, "nap")
        b.poke()
        plan = b.update(TICK, ctx("away", idle_seconds=900.0), me())
        self.assertEqual(plan.action, "react_to_poke")

    def test_la_fenetre_de_reflexe_depasse_son_plancher(self) -> None:
        """Sinon le réflexe s'interrompt avant d'avoir été joué."""
        from pet.brain.actions import CHEER_WINDOW, POKE_WINDOW
        par_nom = {a.name: a for a in default_actions()}
        self.assertGreater(POKE_WINDOW, par_nom["react_to_poke"].min_seconds)
        self.assertGreater(CHEER_WINDOW, par_nom["happy_bounce"].min_seconds)

    def test_le_retour_apres_une_absence_est_fete(self) -> None:
        """Décision §17.4 : sieste pendant `away`, `happy_bounce` au retour."""
        b = Brain()
        for _ in range(20):
            b.update(TICK, ctx("away", idle_seconds=900.0), me())
        plan = b.update(TICK, ctx("typing"), me())
        self.assertEqual(plan.action, "happy_bounce")

    def test_un_soin_declenche_la_celebration(self) -> None:
        b = Brain(Needs(hunger=10.0))
        self.assertTrue(b.care("feed"))
        plan = b.update(TICK, ctx("typing"), me())
        self.assertEqual(plan.action, "happy_bounce")

    def test_un_soin_est_refuse_pendant_son_delai(self) -> None:
        b = Brain(Needs(hunger=0.0))
        self.assertTrue(b.care("feed"))
        self.assertFalse(b.can_care("feed"))
        self.assertEqual(b.care("feed"), {}, "le délai a été ignoré")
        self.assertGreater(b.cooldown("feed"), 0.0)

    def test_un_delai_de_soin_s_epuise(self) -> None:
        b = Brain(Needs(hunger=0.0))
        b.care("feed")
        b.update(CARE_COOLDOWN["feed"] + 1.0, ctx(), me())
        self.assertTrue(b.can_care("feed"))

    def test_un_soin_inconnu_est_refuse_sans_lever(self) -> None:
        b = Brain()
        self.assertFalse(b.can_care("astiquer"))
        self.assertEqual(b.care("astiquer"), {})

    def test_le_visage_vient_de_l_action_sinon_de_l_humeur(self) -> None:
        b = Brain(Needs(**{k: 90.0 for k in NEEDS}))
        b.update(TICK, ctx("away", idle_seconds=900.0), me())
        self.assertEqual(b.expression, "endormi")     # imposé par l'action

        muette = _Fixed("muette", 1.0)
        b2 = Brain(Needs(**{k: 90.0 for k in NEEDS}), actions=[muette])
        b2.update(TICK, ctx(), me())
        self.assertEqual(b2.expression, "joyeux")     # laissé à l'humeur

    def test_le_tick_impose_par_le_paragraphe_12(self) -> None:
        self.assertAlmostEqual(TICK, 0.25, places=6)

    def test_un_dt_nul_ne_reelit_rien(self) -> None:
        b = Brain()
        b.update(TICK, ctx(), me())
        avant = b.changes
        b.update(0.0, ctx(), me())
        self.assertEqual(b.changes, avant)


# ---------------------------------------------------------------------------
# Le vocabulaire symbolique, résolu de part et d'autre de la cloison
# ---------------------------------------------------------------------------


class SymbolicVocabularyTest(unittest.TestCase):
    """Le `brain` publie des noms ; ce test vérifie qu'ils existent ailleurs."""

    def test_chaque_courbe_annoncee_existe_dans_anim(self) -> None:
        from pet.anim.layers import ACTIONS
        for action in default_actions():
            if action.curve:
                self.assertIn(action.curve, ACTIONS,
                              f"{action.name} annonce une courbe inconnue")

    def test_chaque_expression_annoncee_existe_dans_render(self) -> None:
        from pet.render.face import EXPRESSIONS
        for action in default_actions():
            if action.expression:
                self.assertIn(action.expression, EXPRESSIONS)
        for name in needs_mod.MOOD_BY_NEED.values():
            self.assertIn(name, EXPRESSIONS)
        for name in ("joyeux", "neutre"):
            self.assertIn(name, EXPRESSIONS)

    def test_le_brain_n_importe_ni_render_ni_anim_ni_qt(self) -> None:
        """La cloison du §5, vérifiée sur les modules ajoutés au lot L6."""
        import ast
        interdits = ("render", "anim", "pet.render", "pet.anim", "PySide6",
                     "moderngl")
        for path in (PET_ROOT / "brain").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    noms = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    noms = [("." * node.level) + (node.module or "")]
                else:
                    continue
                for nom in noms:
                    self.assertFalse(
                        nom.lstrip(".").startswith(interdits),
                        f"{path.name} importe {nom} — cloison du §5")

    def test_tout_le_brain_s_importe_sans_qt_ni_gpu(self) -> None:
        import subprocess
        import sys
        code = ("import sys, pet.brain.brain, pet.brain.replay, "
                "pet.brain.session, pet.brain.trace; "
                "print('PySide6' in sys.modules, 'moderngl' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, cwd=str(PET_ROOT.parent))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False False")


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------


class TraceTest(unittest.TestCase):
    def test_un_profil_synthetique_est_reproductible(self) -> None:
        a = synthetic_day("bureau", seed=7, hours=6.0)
        b = synthetic_day("bureau", seed=7, hours=6.0)
        self.assertEqual(a.samples, b.samples)

    def test_deux_graines_donnent_deux_journees(self) -> None:
        a = synthetic_day("bureau", seed=1, hours=6.0)
        b = synthetic_day("bureau", seed=2, hours=6.0)
        self.assertNotEqual(a.samples, b.samples)

    def test_l_histogramme_couvre_toute_la_duree(self) -> None:
        t = synthetic_day("bureau", seed=4, hours=12.0)
        self.assertAlmostEqual(sum(t.histogram().values()), t.duration, places=3)

    def test_chaque_profil_rend_une_trace_utilisable(self) -> None:
        for profile in PROFILES:
            t = synthetic_day(profile, seed=5, hours=8.0)
            self.assertGreater(len(t.samples), 0)
            self.assertAlmostEqual(t.duration, 8.0 * HOUR, places=3)

    def test_un_profil_inconnu_est_refuse(self) -> None:
        with self.assertRaises(KeyError):
            synthetic_day("vacances", seed=0)

    def test_une_trace_non_croissante_est_refusee(self) -> None:
        with self.assertRaises(ValueError):
            Trace((Sample(10.0, "idle"), Sample(5.0, "typing")), 20.0)

    def test_un_etat_inconnu_est_refuse(self) -> None:
        with self.assertRaises(ValueError):
            Trace((Sample(0.0, "reveur"),), 10.0)

    def test_l_etat_avant_le_premier_echantillon_est_idle(self) -> None:
        t = Trace((Sample(50.0, "typing"),), 100.0)
        self.assertEqual(t.state_at(0.0), "idle")
        self.assertEqual(t.state_at(60.0), "typing")

    def test_une_trace_fait_l_aller_retour_par_le_disque(self) -> None:
        t = synthetic_day("soiree", seed=9, hours=5.0)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trace.json"
            t.save(path)
            relue = Trace.load(path)
        self.assertEqual(relue.samples, t.samples)
        self.assertAlmostEqual(relue.duration, t.duration, places=3)

    def test_une_trace_ne_contient_que_des_categories(self) -> None:
        """Garantie du §11, vérifiable à l'oeil sur le fichier lui-même."""
        from pet.brain.trace import STATES
        t = synthetic_day("bureau", seed=2, hours=10.0)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trace.json"
            t.save(path)
            texte = path.read_text(encoding="utf-8")
        mots = {m for m in __import__("re").findall(r"[A-Za-z_]{3,}", texte)}
        autorises = set(STATES) | {"label", "duration", "samples", "bureau"}
        self.assertEqual(mots - autorises, set(),
                         "un mot inattendu a atteint le fichier de trace")

    def test_l_enregistreur_ne_retient_que_les_changements(self) -> None:
        r = Recorder("essai")
        for _ in range(10):
            r.feed(1.0, "typing")
        r.feed(1.0, "away")
        r.feed(1.0, "away")
        t = r.trace()
        self.assertEqual([s.state for s in t.samples], ["typing", "away"])
        self.assertAlmostEqual(t.duration, 12.0)

    def test_l_enregistreur_ignore_un_etat_inconnu(self) -> None:
        r = Recorder()
        r.feed(1.0, "reveur")
        self.assertEqual(r.trace().samples, ())


# ---------------------------------------------------------------------------
# Les critères mesurés du lot
# ---------------------------------------------------------------------------


class AcceptanceTest(unittest.TestCase):
    """Les deux critères qui ne se vérifient que sur un temps long.

    Rejoués sur une journée entière ici, sur toute la suite de profils dans
    `tools/day_sim.py` — la joignabilité de `sit_and_watch` demande un profil
    avec de la vidéo, et celle de `bored_slump` un pet mal soigné.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.trace = synthetic_day("bureau", seed=3, hours=24.0)
        _, cls.report = replay(cls.trace, care="reasonable", seed=3)

    def test_aucun_clignotement(self) -> None:
        """Ni réflexe, ni épisode écourté par un réflexe : du vrai vacillement.

        La première version de ce test accusait `follow_cursor` et
        `idle_wander` dès que les réflexes ont pu traverser le plancher de
        durée — alors qu'être interrompu par un clic est précisément ce qui doit
        arriver. La définition partagée vit maintenant dans `Report.flickers`.
        """
        clignote = self.report.flickers(1.0)
        self.assertEqual(clignote, {}, f"actions clignotantes : {clignote}")

    def test_les_episodes_sont_assez_longs_pour_se_lire(self) -> None:
        self.assertGreaterEqual(self.report.episode_stats()["median"], 8.0)

    def test_aucune_action_ne_monopolise_la_presence(self) -> None:
        """Mesuré sur le temps de **présence**, seul dénominateur qui a un sens.

        Sur l'horloge murale, ce critère accuserait `nap` de dominer une
        journée où la machine tourne seule vingt-deux heures — alors qu'un pet
        laissé seul doit précisément dormir.
        """
        self.assertEqual(self.report.dominant(60.0), ())

    def test_le_pet_ne_broie_pas_du_noir_le_matin(self) -> None:
        """Régression : `fun` perdait 67 points par nuit.

        L'utilisateur retrouvait chaque matin un pet affaissé d'ennui, ce qui
        est la culpabilisation que le §12 interdit.
        """
        n = Needs()
        n.tick("away", 8.0 * HOUR)
        self.assertGreater(n.fun, BORED_FUN,
                           "une nuit suffit à rendre le pet morose")

    def test_les_besoins_tiennent_dans_une_bande_saine_avec_du_soin(self) -> None:
        for name in ("hunger", "hygiene"):
            self.assertGreater(self.report.needs_mean[name], 40.0,
                               f"{name} reste bas malgré un soin raisonnable")

    def test_une_journee_de_soin_nul_ne_bloque_personne(self) -> None:
        _, rapport = replay(synthetic_day("absent", seed=3, hours=24.0),
                            care="none", seed=3)
        joues = {n for n, s in rapport.seconds_by_action.items() if s > 0.0}
        self.assertIn("bored_slump", joues)
        self.assertIn("nap", joues)

    def test_le_rejeu_est_deterministe(self) -> None:
        trace = synthetic_day("bureau", seed=3, hours=6.0)
        a = replay(trace, care="reasonable", seed=3)[1]
        b = replay(trace, care="reasonable", seed=3)[1]
        self.assertEqual(a.seconds_by_action, b.seconds_by_action)
        self.assertEqual(a.changes, b.changes)


# ---------------------------------------------------------------------------
# Persistance de l'état vivant
# ---------------------------------------------------------------------------


class SessionTest(unittest.TestCase):
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

    def _session(self, clock=None):
        from pet.brain.session import Session
        s = Session(clock=clock) if clock else Session()
        s.load()
        return s

    def test_un_premier_lancement_part_des_valeurs_par_defaut(self) -> None:
        s = self._session()
        self.assertEqual(s.brain.needs.as_dict(), Needs().as_dict())
        self.assertEqual(s.offline_seconds, 0.0)
        self.assertEqual(s.name, "")

    def test_les_besoins_survivent_a_un_aller_retour(self) -> None:
        s = self._session()
        s.brain.needs.hunger = 33.0
        s.flush(force=True)
        maintenant = time.time()
        self.assertAlmostEqual(
            self._session(clock=lambda: maintenant).brain.needs.hunger,
            33.0, places=1)

    def test_l_absence_hors_ligne_est_facturee_et_plafonnee(self) -> None:
        s = self._session()
        s.flush(force=True)
        plus_tard = time.time() + 30.0 * HOUR
        s2 = self._session(clock=lambda: plus_tard)
        self.assertAlmostEqual(s2.offline_seconds, OFFLINE_CAP_SECONDS, places=1)

    def test_une_horloge_qui_recule_ne_facture_rien(self) -> None:
        s = self._session()
        s.flush(force=True)
        avant = time.time() - 10.0 * HOUR
        self.assertEqual(self._session(clock=lambda: avant).offline_seconds, 0.0)

    def test_les_delais_de_soin_survivent_a_une_fermeture(self) -> None:
        s = self._session()
        s.brain.needs.hunger = 0.0
        s.care("feed")
        reste = s.brain.cooldown("feed")
        self.assertGreater(reste, 0.0)
        peu_apres = time.time() + 60.0
        s2 = self._session(clock=lambda: peu_apres)
        self.assertGreater(s2.brain.cooldown("feed"), 0.0)
        self.assertLess(s2.brain.cooldown("feed"), reste)

    def test_un_delai_expire_pendant_l_absence(self) -> None:
        s = self._session()
        s.brain.needs.hunger = 0.0
        s.care("feed")
        bien_apres = time.time() + CARE_COOLDOWN["feed"] + 60.0
        s2 = self._session(clock=lambda: bien_apres)
        self.assertTrue(s2.brain.can_care("feed"))

    def test_le_nom_est_definitif(self) -> None:
        s = self._session()
        self.assertTrue(s.set_name("Bidule"))
        self.assertEqual(s.name, "Bidule")
        self.assertFalse(s.set_name("Autre"), "le nom doit être définitif")
        self.assertEqual(self._session().name, "Bidule")

    def test_un_nom_vide_est_refuse(self) -> None:
        s = self._session()
        self.assertFalse(s.set_name("   "))
        self.assertEqual(s.name, "")

    def test_un_nom_est_normalise(self) -> None:
        s = self._session()
        s.set_name("  Grand   Robot  ")
        self.assertEqual(s.name, "Grand Robot")

    def test_un_etat_aberrant_est_borne_et_non_rejete(self) -> None:
        """§14 : borner plutôt que rejeter, le pet doit démarrer."""
        from pet.state import save
        store = save.state_store()
        save.write_json_atomic(store.path, {
            "schema_version": save.STATE_SCHEMA,
            "needs": {"hunger": 500.0, "fun": -20.0, "energy": "oui"},
            "last_seen": "hier",
            "cooldowns": {"feed": "beaucoup", "play": -5.0},
            "name": 42,
            "tokens": -9,
            "inventory": "pas une liste",
        })
        s = self._session()
        self.assertEqual(s.brain.needs.hunger, FULL)
        self.assertEqual(s.brain.needs.fun, 0.0)
        self.assertEqual(s.brain.needs.energy, 80.0)
        self.assertEqual(s.name, "")
        self.assertEqual(s.store.data["tokens"], 0)
        self.assertEqual(s.store.data["inventory"], [])
        self.assertEqual(s.store.data["cooldowns"], {})

    def test_l_enregistrement_periodique_a_lieu(self) -> None:
        from pet.brain.session import SAVE_SECONDS
        s = self._session()
        s.store.path.unlink(missing_ok=True)
        s.update(SAVE_SECONDS + 1.0, ctx(), me())
        self.assertTrue(s.store.path.exists(), "aucune écriture périodique")

    def test_le_champ_de_version_est_present(self) -> None:
        s = self._session()
        s.flush(force=True)
        import json
        raw = json.loads(s.store.path.read_text(encoding="utf-8"))
        self.assertIn("schema_version", raw)


if __name__ == "__main__":
    unittest.main()
