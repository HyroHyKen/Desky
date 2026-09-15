"""Économie de besoins, telle que le CDC §12 la prescrit.

Convention capitale, et contre-intuitive au vu des noms : les quatre besoins
sont des **niveaux de satisfaction** dans [0, 100], où 100 vaut « comblé » et 0
« demande de l'attention ». `hunger` à 100 est donc un pet rassasié, pas un pet
affamé. C'est le §12 qui impose cette lecture en écrivant que « hunger et
hygiene sont les seuls à décroître dans le temps » : ce qui décroît est la
satiété, pas la faim.

Le point que le §12 qualifie d'impératif est que les besoins **ne décroissent
pas linéairement avec le temps**. Ils sont majoritairement alimentés par ce que
l'utilisateur fait déjà : `fun` monte quand il travaille, `energy` remonte quand
il s'absente. Seuls `hunger` et `hygiene` s'écoulent, et ce sont eux les vecteurs
du soin actif.

Module pur : ni GPU, ni Qt, ni `anim`, ni `render` (cloison du §5).
"""

from __future__ import annotations

from dataclasses import dataclass

NEEDS: tuple[str, ...] = ("hunger", "fun", "energy", "hygiene")

FULL = 100.0
EMPTY = 0.0

HOUR = 3600.0

# Taux de variation en points par heure, par état de contexte du §11. C'est la
# table de réglage centrale du comportement : tout le tempérament du pet en
# sort. Les valeurs se lisent comme des durées — -4,3 pt/h vide la satiété en
# vingt-trois heures, -2,5 pt/h l'hygiène en quarante — et c'est cette lecture
# qui les rend arbitrables autrement qu'au doigt mouillé.
#
# Deux colonnes ont été refaites après mesure sur journée synthétique, et les
# deux défauts avaient la même cause : l'état `away` sert à la fois pour une
# absence de dix minutes et pour une nuit entière, et des taux calibrés sur la
# première sont ruineux sur la seconde.
#
# `fun` perdait 9 pt/h en absence, soit 67 points sur une nuit : l'utilisateur
# retrouvait **chaque matin** un pet affaissé d'ennui. C'est précisément la
# culpabilisation que le §12 interdit. Ramené à 4 pt/h, une nuit coûte 30 points
# et la matinée les regagne.
#
# `energy` récupérait plus vite qu'elle ne se dépensait : sur une journée de
# bureau, elle ne descendait jamais sous 68 et valait 89 en moyenne. Le besoin
# existait sans jamais rien décider — `nap` n'était déclenché que par l'état
# `away`, jamais par la fatigue. La dépense est passée devant la récupération,
# et l'arc voulu est maintenant obtenu : pleine le matin, basse le soir.
#
# Les colonnes `hunger` et `hygiene` sont constantes d'un état à l'autre, et
# c'est voulu : le §12 les veut seules à s'écouler avec le temps. La colonne est
# conservée plutôt que factorisée pour que la table entière se lise d'un coup.
#
#                    hunger    fun  energy  hygiene
RATES: dict[str, tuple[float, float, float, float]] = {
    "typing":         (-4.3,   9.0,   -9.0,    -2.5),
    "browsing":       (-4.3,   7.0,   -9.0,    -2.5),
    "watching":       (-4.3,   5.0,    2.0,    -2.5),
    "idle":           (-4.3,  -3.0,    6.0,    -2.5),
    "away":           (-4.3,  -4.0,    6.0,    -2.5),
}

# État retenu quand le contexte est inconnu. `idle` plutôt que `typing` : en
# l'absence de preuve de présence, on ne crédite pas d'activité.
FALLBACK_STATE = "idle"

# Gains de soin, et délai avant de pouvoir resservir. Les délais existent pour
# que le gavage ne soit pas la stratégie optimale — c'est le pendant, côté soin,
# du plafond quotidien que le §14 impose aux tokens.
# Soins **gratuits**. Il n'en reste qu'un depuis le lot L13 : nourrir et
# nettoyer sont devenus des consommables qu'on achète (cf. `consumables`), et
# jouer est devenu un jeu.
#
# La caresse survit seule parce qu'il fallait que le robot reste caressable sans
# rien posséder. C'est le geste qu'on fait en passant, et il ne doit rien
# coûter — ni jeton, ni objet.
CARE_GAINS: dict[str, dict[str, float]] = {
    "pet":   {"fun": 16.0},
}

# Amusement rendu par une partie : un socle, plus un bonus par échange, plafonné.
#
# Le socle récompense d'avoir joué même une partie ratée — le §12 interdit de
# punir. Le bonus récompense d'avoir bien joué. Le plafond empêche qu'une seule
# très longue partie remplisse la jauge pour la journée, ce qui retirerait toute
# raison de rejouer.
GAME_FUN_BASE = 8.0
GAME_FUN_PER_RALLY = 1.6
GAME_FUN_MAX = 46.0


def game_fun(score: int) -> float:
    """Amusement rendu par une partie de `score` échanges."""
    return min(GAME_FUN_MAX, GAME_FUN_BASE + GAME_FUN_PER_RALLY * max(0, score))

# Délai du seul soin gratuit. Les consommables, eux, n'en ont pas : les
# posséder **est** la limite, et superposer un compte à rebours à une quantité
# donnerait un objet qu'on a sans pouvoir s'en servir.
CARE_COOLDOWN: dict[str, float] = {
    "pet": 2.0 * 60.0,
}

# Plafond de décroissance hors ligne. Revenir de vacances devant un pet
# maximalement triste est exactement le mode d'échec culpabilisant que le §12
# interdit : au-delà de huit heures d'absence, le temps ne compte plus.
OFFLINE_CAP_SECONDS = 8.0 * HOUR

# Seuil au-dessous duquel le pet exprime un besoin dans sa bulle. Plus haut
# que le seuil d'humeur : la bulle **demande**, l'humeur **subit**, donc la
# demande doit venir avant que le visage s'assombrisse. Une bulle qui n'apparaît
# qu'au moment où le pet a déjà l'air malheureux arrive trop tard pour servir.
WANT_THRESHOLD = 45.0

# Seuil au-dessous duquel le pet exprime un besoin dans sa bulle. Plus haut
# que le seuil d'humeur : la bulle **demande**, l'humeur **subit**, donc la
# demande doit venir avant que le visage s'assombrisse. Une bulle qui n'apparaît
# qu'au moment où le pet a déjà l'air malheureux arrive trop tard pour servir.
WANT_THRESHOLD = 45.0

# Seuils d'humeur, sur le besoin le plus faible.
# Le seuil neutre est bas volontairement. Avec l'humeur portée par le besoin le
# **plus faible**, un seuil haut donne un pet à la mine sombre dès qu'un seul de
# ses quatre besoins descend un peu — soit presque tout le temps. Les visages
# tristes doivent rester rares pour vouloir dire quelque chose.
MOOD_HAPPY = 72.0
MOOD_NEUTRAL = 30.0

# Sous le seuil neutre, c'est le besoin le plus faible qui choisit le visage.
# Un visage n'est pas un reproche : le §12 autorise explicitement qu'un besoin
# bas change « son humeur et son animation, jamais plus ».
MOOD_BY_NEED: dict[str, str] = {
    "hunger": "fache",
    "fun": "ennuye",
    "energy": "somnolent",
    "hygiene": "mefiant",
}


def clamp(value: float) -> float:
    return max(EMPTY, min(FULL, float(value)))


def offline_elapsed(now: float, last_seen: float,
                    cap: float = OFFLINE_CAP_SECONDS) -> float:
    """Durée d'absence à facturer, plafonnée, jamais négative.

    Le §14 demande de détecter les reculs d'horloge et de refuser tout crédit
    rétroactif. Une horloge qui recule donne ici zéro, et non une durée
    négative qui recréditerait les besoins.
    """
    if last_seen <= 0.0:
        return 0.0
    delta = float(now) - float(last_seen)
    if delta <= 0.0:
        return 0.0
    return min(delta, float(cap))


@dataclass
class Needs:
    """Les quatre satisfactions du §12, plus l'horodatage des soins.

    Les valeurs de départ ne sont pas à 100 : un pet neuf entièrement comblé
    n'a rien à exprimer, et sa bulle resterait vide le premier jour.
    """

    hunger: float = 70.0
    fun: float = 70.0
    energy: float = 80.0
    hygiene: float = 80.0

    def as_dict(self) -> dict[str, float]:
        return {name: round(getattr(self, name), 3) for name in NEEDS}

    @classmethod
    def from_dict(cls, raw: dict) -> "Needs":
        """Reconstruit en **bornant** plutôt qu'en rejetant (§14).

        Une valeur hors plage vient soit d'une édition manuelle, soit d'une
        migration ratée ; dans les deux cas le pet doit démarrer.
        """
        out = cls()
        for name in NEEDS:
            try:
                setattr(out, name, clamp(float(raw.get(name, getattr(out, name)))))
            except (TypeError, ValueError):
                pass
        return out

    def weakest(self) -> tuple[str, float]:
        """Besoin le plus faible. L'ordre de `NEEDS` tranche les égalités."""
        name = min(NEEDS, key=lambda n: getattr(self, n))
        return name, getattr(self, name)

    def mood(self) -> str:
        """Nom d'expression, à charge du rendu de le résoudre.

        Retourne une chaîne et non un `FaceState` : la cloison du §5 interdit au
        `brain` de connaître `render`.
        """
        name, level = self.weakest()
        if level >= MOOD_HAPPY:
            return "joyeux"
        if level >= MOOD_NEUTRAL:
            return "neutre"
        return MOOD_BY_NEED[name]

    def want(self) -> str:
        """Besoin à exprimer dans la bulle, ou chaîne vide.

        Un seul à la fois, le plus faible : une bulle qui empilerait les
        demandes serait une liste de reproches, et le §12 interdit de
        culpabiliser l'utilisateur.
        """
        name, level = self.weakest()
        return name if level < WANT_THRESHOLD else ""

    def want(self) -> str:
        """Besoin à exprimer dans la bulle, ou chaîne vide.

        Un seul à la fois, le plus faible : une bulle qui empilerait les
        demandes serait une liste de reproches, et le §12 interdit de
        culpabiliser l'utilisateur.
        """
        name, level = self.weakest()
        return name if level < WANT_THRESHOLD else ""

    def tick(self, state: str, dt: float) -> None:
        """Applique `dt` secondes passées dans l'état de contexte `state`."""
        if dt <= 0.0:
            return
        rates = RATES.get(state) or RATES[FALLBACK_STATE]
        hours = dt / HOUR
        for name, rate in zip(NEEDS, rates):
            setattr(self, name, clamp(getattr(self, name) + rate * hours))

    def apply(self, gains: dict[str, float]) -> dict[str, float]:
        """Applique des deltas, et rend ceux qui ont **effectivement** pris.

        Le même contrat que `care`, dont c'est désormais le cœur commun : le
        delta réel diffère du nominal dès qu'un besoin sature, et c'est la
        valeur réelle que l'interface doit montrer. Promettre +52 puis n'en
        donner que 4 est le genre de détail qui fait paraître un logiciel faux.
        """
        applied: dict[str, float] = {}
        for name, gain in gains.items():
            if name not in NEEDS:
                continue
            before = getattr(self, name)
            after = clamp(before + gain)
            if after != before:
                applied[name] = after - before
            setattr(self, name, after)
        return applied

    def care(self, kind: str) -> dict[str, float]:
        """Applique un soin. Retourne les deltas **effectivement** appliqués.

        Le delta réel diffère du gain nominal dès qu'un besoin sature, et c'est
        cette valeur que l'interface doit afficher : promettre +46 puis n'en
        donner que 4 est le genre de détail qui fait paraître un logiciel faux.
        """
        gains = CARE_GAINS.get(kind)
        return self.apply(gains) if gains else {}
