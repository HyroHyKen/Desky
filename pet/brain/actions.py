"""Les neuf actions v1 du CDC §12.

Chacune se branche sur de la mécanique déjà livrée : les courbes du lot L4 et
les intentions de déplacement du lot L5b. C'est la raison d'avoir fait la
locomotion avant le comportement — trois de ces actions sont des trajets.

Les scores sont sans unité, et seule leur comparaison compte. Deux familles s'y
distinguent nettement :

- les **réflexes** (`react_to_poke`, `happy_bounce`) rendent des scores très
  au-dessus du reste, parce qu'ils doivent gagner sans discussion ;
- les **ambiances** (`idle_wander`, `look_around`, `sniff_around`,
  `follow_cursor`) se disputent une bande étroite autour de 0,3, et c'est le
  bonus de nouveauté de `utility` qui les fait tourner.

Entre les deux, `sit_and_watch`, `nap` et `bored_slump` sont pilotés par le
contexte et les besoins.

**Règle de conception, apprise en mesurant :** `is_available` est une grille
**grossière**, et c'est le score qui fait le travail fin. Une disponibilité
posée sur une grandeur continue et rapide bascule en pleine action, court-
circuite le plancher `min_seconds` — on ne peut pas retenir une action devenue
indisponible — et produit un clignotement. La première version de
`follow_cursor` conditionnait sa disponibilité à la distance au curseur : elle a
produit 101 épisodes de moins d'une seconde sur une journée. Les seuils continus
appartiennent au score, où l'hystérésis les lisse.
"""

from __future__ import annotations

from .utility import Action, SelfState

# Fenêtres pendant lesquelles un événement d'interface reste un réflexe. Elles
# n'ont pas à porter la durée du réflexe : c'est `min_seconds` qui la tient. Une
# fenêtre juste plus longue que le plancher suffit, et il **faut** qu'elle le
# soit — une fenêtre plus courte rendrait l'action indisponible avant la fin de
# son plancher, ce qui l'écourterait au lieu de la tenir.
POKE_WINDOW = 0.9
CHEER_WINDOW = 1.2

# Seuil de sieste, et de morosité. Exprimés en points de satisfaction.
NAP_ENERGY = 50.0
BORED_FUN = 35.0

# Distances de suivi du curseur, en hauteurs de corps. En dessous de la borne
# basse le pet est déjà à côté et se déplacer serait du tremblement ; au-delà de
# la borne haute, traverser deux écrans pour un curseur est du harcèlement.
FOLLOW_NEAR = 1.3
FOLLOW_FAR = 9.0

# Inactivité minimale avant que regarder autour ait un sens : pendant que
# l'utilisateur tape, le pet a le look-at du lot L4, ce qui suffit.
LOOK_IDLE = 4.0


class ReactToPoke(Action):
    """Réflexe au clic. Doit gagner contre tout, y compris le sommeil."""

    name = "react_to_poke"
    curve = "poke_reaction"
    expression = "surpris"
    travel = "stop"
    min_seconds = 0.62
    reflex = True

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return me.poke_seconds <= POKE_WINDOW

    def score(self, needs, ctx, me: SelfState) -> float:
        return 10.0


class HappyBounce(Action):
    """Célébration après un soin, ou au retour de l'utilisateur (§17.4)."""

    name = "happy_bounce"
    curve = "celebrate"
    expression = "joyeux"
    travel = "stop"
    min_seconds = 0.9
    reflex = True

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return me.cheer_seconds <= CHEER_WINDOW

    def score(self, needs, ctx, me: SelfState) -> float:
        return 8.0


class SitAndWatch(Action):
    """Déclenchée par `watching`, comme le §12 le prescrit explicitement.

    Score élevé et plat : un film de deux heures ne doit pas être entrecoupé de
    flânerie. Le pet s'assoit et regarde, et c'est tout.
    """

    name = "sit_and_watch"
    curve = "sit"
    expression = "curieux"
    travel = "stop"
    min_seconds = 4.0

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return ctx.state == "watching"

    def score(self, needs, ctx, me: SelfState) -> float:
        return 3.0


class Nap(Action):
    """Sieste. Le §17.4 est tranché : il dort vraiment pendant `away`."""

    name = "nap"
    curve = "sleep"
    expression = "endormi"
    travel = "stop"
    look_at_cursor = False
    min_seconds = 6.0

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return True

    def score(self, needs, ctx, me: SelfState) -> float:
        envie = max(0.0, (NAP_ENERGY - needs.energy) / NAP_ENERGY)
        if ctx.state == "away":
            return 1.45 + 1.20 * envie
        if ctx.state == "idle":
            return 0.30 + 1.20 * envie
        return 1.20 * envie


class BoredSlump(Action):
    """Affaissement d'ennui. Réutilise la pose assise, avec le visage `ennuye`.

    Une courbe dédiée serait mieux ; celle du lot L4 suffit à rendre l'état
    lisible, et l'écrire relève du polish du lot L9.
    """

    name = "bored_slump"
    curve = "sit"
    expression = "ennuye"
    travel = "stop"
    min_seconds = 5.0
    # Plafond, seul de la liste. À `fun` nul l'affaissement score 0,90 et bat
    # toutes les ambiances : sans plafond, un pet délaissé resterait affaissé
    # pour toujours, ce qui est moins un comportement qu'une panne.
    max_seconds = 25.0

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return True

    def score(self, needs, ctx, me: SelfState) -> float:
        if needs.fun >= BORED_FUN:
            return 0.0
        return 0.90 * (BORED_FUN - needs.fun) / BORED_FUN


class FollowCursor(Action):
    """Suit le curseur. C'est l'action qui nourrit `fun` par l'activité."""

    name = "follow_cursor"
    travel = "cursor"
    expression = "curieux"
    min_seconds = 2.5
    varies = True

    def _distance(self, ctx, me: SelfState) -> float:
        return abs(float(ctx.cursor[0]) - me.x) / max(1.0, me.pet_h)

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        # Grille grossière : l'état, et lui seul. La distance est continue et
        # rapide, donc elle appartient au score (cf. l'entête du module).
        return ctx.state not in ("idle", "away", "watching")

    def score(self, needs, ctx, me: SelfState) -> float:
        d = self._distance(ctx, me)
        if d <= FOLLOW_NEAR or d >= FOLLOW_FAR:
            return 0.0
        proche = 1.0 - (d - FOLLOW_NEAR) / (FOLLOW_FAR - FOLLOW_NEAR)
        envie = 1.0 - needs.fun / 100.0
        return 0.34 + 0.30 * proche + 0.28 * envie


class FetchItem(Action):
    """Va chercher un objet de soin posé sur le bureau.

    Score au-dessus de `sit_and_watch`, donc au-dessus de tout ce qui n'est pas
    un réflexe : poser un objet est un **geste délibéré** de l'utilisateur, et
    un pet qui continuerait à regarder son film pendant que sa gamelle refroidit
    donnerait l'impression de ne pas l'avoir vue.

    Sous les réflexes en revanche : un clic doit toujours passer devant.
    """

    name = "fetch_item"
    travel = "item"
    expression = "curieux"
    min_seconds = 2.0

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return me.item_x is not None

    def score(self, needs, ctx, me: SelfState) -> float:
        return 3.4


class SniffAround(Action):
    """Fouine près du bord de l'écran, comme le §12 le décrit."""

    # Le croisement avec la flânerie est posé sur `fun` plutôt que laissé au
    # hasard des scores : sous 69 points d'amusement le pet part fouiner, au-
    # dessus il se contente de flâner. Les deux actions ont ainsi chacune une
    # niche, et cette niche veut dire quelque chose. Avant ce réglage, fouiner
    # gagnait toujours et la flânerie tombait à 0,2 % de la journée.
    name = "sniff_around"
    travel = "edge"
    expression = "curieux"
    min_seconds = 4.0
    varies = True

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return ctx.state in ("typing", "browsing", "idle") and me.width > 0.0

    def score(self, needs, ctx, me: SelfState) -> float:
        return 0.20 + 0.26 * (1.0 - needs.fun / 100.0)


class LookAround(Action):
    """Regarde autour de lui. Sur place, donc jamais pendant un trajet."""

    name = "look_around"
    curve = "look_around"
    min_seconds = 2.5
    varies = True

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return not me.travelling

    def score(self, needs, ctx, me: SelfState) -> float:
        # `idle_seconds` retombe à zéro à chaque frappe : en faire une condition
        # de disponibilité la ferait basculer plusieurs fois par seconde.
        return 0.30 if ctx.idle_seconds >= LOOK_IDLE else 0.0


class IdleWander(Action):
    """Flânerie. **Action plancher** : toujours disponible, toujours modeste.

    Sa disponibilité inconditionnelle est ce qui garantit qu'une élection rend
    toujours quelque chose. Un terrain vide fait échouer la flânerie côté
    locomotion, pas côté décision — le pet reste alors simplement immobile.
    """

    name = "idle_wander"
    travel = "wander"
    min_seconds = 4.0
    varies = True

    def score(self, needs, ctx, me: SelfState) -> float:
        return 0.28


# L'ordre tranche les égalités de score, donc il est lisible comme une
# priorité : réflexes, puis contexte, puis besoins, puis ambiances.
def default_actions() -> list[Action]:
    return [
        ReactToPoke(),
        HappyBounce(),
        SitAndWatch(),
        FetchItem(),
        Nap(),
        BoredSlump(),
        FollowCursor(),
        SniffAround(),
        LookAround(),
        IdleWander(),
    ]


ACTION_NAMES: tuple[str, ...] = tuple(a.name for a in default_actions())

# Les réflexes, qui traversent le plancher de durée de l'action en cours.
# Exporté parce que la mesure du clignotement doit les connaître : un
# épisode écourté **par** un réflexe est légitime, pas un défaut.
REFLEXES: frozenset[str] = frozenset(
    a.name for a in default_actions() if a.reflex)
