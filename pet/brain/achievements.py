"""Trophées : le catalogue, et rien que le catalogue (lot L22).

Module **pur** — ni Qt, ni disque, ni horloge. Il déclare ce qui se débloque,
sous quelle condition, et ce que ça rapporte ; il ne compte rien lui-même. Les
compteurs vivent dans la session, leur mise à jour dans le suivi, et l'affichage
dans le panneau. Cette séparation est ce qui permet de vérifier les
trente-quatre trophées sans ouvrir une fenêtre.

**Un trophée est une mesure et un seuil.** Pas une fonction, pas une règle
écrite en code : un nom de mesure, un nombre à atteindre. C'est ce qui rend la
barre d'avancement gratuite — elle est le rapport des deux — et c'est ce qui
garantit qu'aucun trophée ne peut se débloquer autrement que par la progression
qu'il affiche. Une condition écrite en Python quelque part donnerait des
trophées qui s'obtiennent d'un coup avec une barre restée à zéro.

**Rien ne se retire.** Un trophée obtenu l'est pour toujours, même si la mesure
qui l'a produit redescend — on peut retirer un chapeau après avoir complété la
collection. Le §12 interdit de punir, et reprendre une récompense obtenue en
serait la forme la plus brutale.

**Les récompenses échappent au plafond quotidien.** Le plafond du §14 existe
pour que l'oisiveté ne soit pas la stratégie optimale ; un trophée n'est pas de
l'oisiveté, c'est une chose faite une seule fois dans la vie du robot. Le faire
tomber sous le plafond aurait un effet absurde : débloquer « 1 an » un jour où
l'on a déjà joué perdrait 75 des 100 jetons.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- mesures ----------------------------------------------------------------
#
# Le vocabulaire des compteurs, déclaré une fois. Les trophées s'y réfèrent, le
# suivi les alimente, et un test vérifie qu'aucun trophée ne vise une mesure que
# personne ne remplit — une barre qui ne bouge jamais est pire qu'un trophée
# absent.
#
# Quatre d'entre elles sont **dérivées** et non accumulées : l'âge se calcule
# sur la date de naissance, les records de jeu sont déjà tenus par
# `best_scores`, et le nombre d'accessoires est la taille de l'inventaire. Les
# stocker une seconde fois aurait créé deux vérités pour une seule information.
AGE = "age_jours"
JOURS_VUS = "jours_vus"
PARTIES = "parties"
RECORDS = "records"
RALLY = "rally"
CUPS = "cups"
REPAS = "repas"
REPAS_URGENCE = "repas_urgence"
BAINS = "bains"
BAINS_COMPLETS = "bains_complets"
SERIE_BAINS = "serie_bains"
VIDEOS = "videos"
HEURES_VIDEO = "heures_video"
CARESSES = "caresses"
CARESSES_SIESTE = "caresses_sieste"
POUSSEES = "poussees"
CHUTES = "chutes"
JETONS = "jetons"
JOURS_PLEINS = "jours_pleins"
ACHATS = "achats"
ACCESSOIRES = "accessoires"
COULEURS = "couleurs"
BAPTEME = "bapteme"

# Mesures que le suivi ne calcule pas : elles sont lues ailleurs et injectées au
# moment de l'évaluation.
DERIVEES: frozenset[str] = frozenset({AGE, RALLY, CUPS, ACCESSOIRES})

# Récompenses admises. La liste est fermée et vérifiée par un test : sans elle,
# les barèmes dérivent trophée par trophée et plus personne ne sait ce que vaut
# une ligne du catalogue.
RECOMPENSES: tuple[int, ...] = (1, 2, 5, 10, 15, 20, 100)

# Familles, dans l'ordre d'affichage.
FAMILLES: tuple[str, ...] = ("temps", "jeux", "repas", "bain", "video",
                             "bureau", "boutique")


@dataclass(frozen=True)
class Trophee:
    """Une ligne du catalogue.

    `titre` et `description` sont du texte d'affichage, et ils sont ici plutôt
    que dans le panneau volontairement : le seuil et la phrase qui le décrit
    doivent se corriger au même endroit, sinon « 25 parties » finit par annoncer
    un objectif qui n'est plus le sien.
    """

    cle: str
    titre: str
    description: str
    icone: str
    mesure: str
    cible: float
    recompense: int
    famille: str


TROPHEES: tuple[Trophee, ...] = (
    # --- temps ------------------------------------------------------------
    #
    # Les cinq premiers sont ceux que l'utilisateur a imposés, dans ses termes.
    # L'âge court même application fermée : c'est une vie partagée, pas un temps
    # de jeu, et compter les heures d'exécution récompenserait de laisser un
    # logiciel ouvert pour rien.
    Trophee("jour_1", "Jour 1", "1 jour avec votre Desky",
            "clock", AGE, 1, 1, "temps"),
    Trophee("semaine_1", "Semaine 1", "1 semaine avec votre Desky",
            "clock", AGE, 7, 5, "temps"),
    Trophee("mois_1", "Mois 1", "1 mois avec votre Desky",
            "clock", AGE, 30, 10, "temps"),
    Trophee("mois_6", "Mois 6", "6 mois avec votre Desky",
            "clock", AGE, 182, 20, "temps"),
    Trophee("anniversaire", "Joyeux anniversaire",
            "Votre Desky fête ses 1 an", "cake", AGE, 365, 100, "temps"),
    # L'âge s'écoule tout seul ; celui-ci demande d'être là. Les deux ne
    # récompensent pas la même chose, et c'est pour ça qu'ils coexistent.
    Trophee("habitue", "Habitué", "30 journées passées ensemble",
            "clock", JOURS_VUS, 30, 15, "temps"),
    # --- jeux -------------------------------------------------------------
    Trophee("premiere_partie", "Première manche", "Terminer une partie",
            "games", PARTIES, 1, 1, "jeux"),
    Trophee("joueur", "Joueur", "25 parties jouées",
            "games", PARTIES, 25, 5, "jeux"),
    Trophee("increvable", "Increvable", "100 parties jouées",
            "games", PARTIES, 100, 15, "jeux"),
    Trophee("premier_record", "Nouveau record", "Battre son meilleur score",
            "trophy", RECORDS, 1, 2, "jeux"),
    # Mesuré : le ballon atteint son poids maximal au vingt-quatrième échange,
    # donc 25 est le seuil au-delà duquel la difficulté ne monte plus. Viser
    # plus haut ne demanderait que de l'endurance.
    Trophee("rally_10", "Ça tient !", "10 échanges dans une partie",
            "rally", RALLY, 10, 2, "jeux"),
    Trophee("rally_25", "Main de maître", "25 échanges dans une partie",
            "rally", RALLY, 25, 10, "jeux"),
    Trophee("cups_5", "Bon œil", "5 manches de suite aux gobelets",
            "cups", CUPS, 5, 2, "jeux"),
    Trophee("cups_10", "Œil de lynx", "10 manches de suite aux gobelets",
            "cups", CUPS, 10, 10, "jeux"),
    # --- repas ------------------------------------------------------------
    Trophee("premier_repas", "À table", "Lui donner à manger",
            "hunger", REPAS, 1, 1, "repas"),
    Trophee("cantine", "Cantine", "25 repas servis",
            "hunger", REPAS, 25, 5, "repas"),
    Trophee("festin", "Festin", "100 repas servis",
            "hunger", REPAS, 100, 15, "repas"),
    Trophee("aux_petits_soins", "Aux petits soins",
            "Le nourrir alors qu'il est à bout",
            "hunger", REPAS_URGENCE, 1, 2, "repas"),
    # --- bain -------------------------------------------------------------
    Trophee("premier_bain", "Premier bain", "Terminer un nettoyage",
            "hygiene", BAINS, 1, 1, "bain"),
    Trophee("impeccable", "Impeccable", "Un bain mené à 100 %",
            "hygiene", BAINS_COMPLETS, 1, 2, "bain"),
    Trophee("thermes", "Thermes", "10 bains complets",
            "hygiene", BAINS_COMPLETS, 10, 10, "bain"),
    Trophee("rien_ne_depasse", "Rien ne dépasse",
            "3 bains complets d'affilée", "hygiene", SERIE_BAINS, 3, 5, "bain"),
    # --- vidéo ------------------------------------------------------------
    #
    # « Regarder ensemble » et non « une vidéo » : l'état se déduit d'un son
    # émis et d'une inactivité, jamais d'un titre ni d'une URL (§11). De la
    # musique compte donc aussi, et la formulation ne doit pas promettre le
    # contraire.
    Trophee("seance_privee", "Séance privée",
            "Regarder quelque chose ensemble",
            "screen", VIDEOS, 1, 1, "video"),
    Trophee("cinephile", "Cinéphile", "10 séances passées ensemble",
            "screen", VIDEOS, 10, 5, "video"),
    Trophee("abonne", "Abonné", "50 séances passées ensemble",
            "screen", VIDEOS, 50, 15, "video"),
    Trophee("marathon", "Marathon", "3 heures de visionnage ensemble",
            "screen", HEURES_VIDEO, 3, 10, "video"),
    # --- bureau -----------------------------------------------------------
    Trophee("premiere_caresse", "Première caresse", "Le caresser",
            "pet", CARESSES, 1, 1, "bureau"),
    Trophee("calin", "Câlin", "100 caresses",
            "pet", CARESSES, 100, 5, "bureau"),
    Trophee("reveil_doux", "Réveil en douceur",
            "Le caresser pendant sa sieste",
            "pet", CARESSES_SIESTE, 1, 2, "bureau"),
    Trophee("petite_poussee", "Petite poussée", "Le pousser du doigt",
            "fun", POUSSEES, 1, 1, "bureau"),
    Trophee("insistant", "Insistant", "200 poussées",
            "fun", POUSSEES, 200, 5, "bureau"),
    Trophee("vol_plane", "Vol plané", "Le lâcher de très haut",
            "fun", CHUTES, 1, 2, "bureau"),
    # --- boutique ---------------------------------------------------------
    Trophee("premier_jeton", "Premier jeton", "Gagner son premier jeton",
            "token", JETONS, 1, 1, "boutique"),
    Trophee("plein_pot", "Plein pot", "Atteindre le plafond d'une journée",
            "token", JOURS_PLEINS, 1, 5, "boutique"),
    Trophee("premier_achat", "Premier achat", "Acheter quelque chose",
            "shop", ACHATS, 1, 1, "boutique"),
    Trophee("dressing", "Dressing", "Posséder 3 accessoires",
            "shop_hat", ACCESSOIRES, 3, 5, "boutique"),
    Trophee("collection", "Collection complète",
            "Posséder tous les accessoires",
            "shop_hat", ACCESSOIRES, 10, 20, "boutique"),
    Trophee("relooking", "Relooking", "Changer sa couleur",
            "custom", COULEURS, 1, 1, "boutique"),
    Trophee("bapteme", "Baptême", "Lui donner son nom",
            "check", BAPTEME, 1, 1, "boutique"),
)

BY_KEY: dict[str, Trophee] = {t.cle: t for t in TROPHEES}

# Ordre d'affichage : par famille, puis dans l'ordre du catalogue. Les familles
# gouvernent parce qu'une liste de trente-quatre lignes sans regroupement se
# parcourt à l'aveugle.
ORDRE: tuple[str, ...] = tuple(
    t.cle for famille in FAMILLES for t in TROPHEES if t.famille == famille)


def progres(trophee: Trophee, mesures: dict) -> float:
    """Avancement dans [0, 1]. C'est la barre, et c'est aussi la condition."""
    try:
        valeur = float(mesures.get(trophee.mesure, 0.0))
    except (TypeError, ValueError):
        return 0.0
    if trophee.cible <= 0.0:
        return 1.0
    return max(0.0, min(1.0, valeur / float(trophee.cible)))


def obtenus(mesures: dict) -> list[str]:
    """Clés des trophées que ces mesures suffisent à débloquer."""
    return [t.cle for t in TROPHEES if progres(t, mesures) >= 1.0]


def recompense(cle: str) -> int:
    trophee = BY_KEY.get(cle)
    return trophee.recompense if trophee is not None else 0
