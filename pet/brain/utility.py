"""Élection d'action par utilité, selon le CDC §12.

« Pas d'arbre de comportement, pas de machine à états monolithique. » Chaque
action expose `is_available(context)` et `score(needs, context)`, et l'action de
score maximal est élue avec un bonus d'hystérésis pour l'action en cours.

Ce module ne contient que le mécanisme et le vocabulaire ; les actions elles-
mêmes sont dans `actions.py`, et leur ordonnancement dans le temps dans
`brain.py`. Aucun import de `anim` ni de `render` (cloison du §5) : l'action
élue publie un `Plan`, fait de **noms** que le rendu résoudra de son côté.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bonus de l'action en cours, imposé par le §12.3. Sans lui, deux actions de
# scores voisins alternent à chaque tick de 250 ms et le pet clignote.
HYSTERESIS = 1.15

# Les actions d'ambiance reçoivent un bonus qui croît avec le temps écoulé
# depuis leur dernière élection. Sans ce terme, la comparaison de scores quasi
# constants élit toujours la même et les autres sont mortes : le pet aurait neuf
# actions et n'en jouerait que trois. C'est aussi ce qui remplace un tirage
# aléatoire, lequel serait irreproductible en test et ferait vibrer les scores.
RECENCY_BONUS = 0.18
RECENCY_FULL = 420.0

# Déplacements qu'une action peut demander. Chaînes et non appels : le `brain`
# ne connaît pas la locomotion, il exprime une intention.
TRAVELS = frozenset({"none", "stop", "wander", "cursor", "edge", "home",
                     "item"})


@dataclass(frozen=True)
class Plan:
    """État symbolique publié par l'action élue, consommé par `anim` (§12.4)."""

    action: str
    curve: str = ""             # courbe d'animation, "" si aucune
    expression: str = ""        # "" laisse l'humeur choisir le visage
    travel: str = "none"
    look_at_cursor: bool = True

    def __post_init__(self) -> None:
        if self.travel not in TRAVELS:
            raise ValueError(f"déplacement inconnu : {self.travel!r}")


@dataclass
class SelfState:
    """Ce que le pet sait de lui-même, en nombres nus.

    Existe pour que `follow_cursor` puisse mesurer une distance sans que le
    `brain` importe la locomotion : la fenêtre recopie ici trois flottants.
    """

    x: float = 0.0                          # centre du pet, pixels physiques
    y: float = 0.0
    pet_h: float = 150.0                    # hauteur du **corps**, unité d'échelle
    travelling: bool = False
    home_x: float = 0.0
    span: tuple[float, float] = (0.0, 0.0)  # étendue du terrain praticable
    # Abscisse d'un objet de soin posé sur le bureau, ou None. Le `brain` n'en
    # sait pas plus : ni ce que c'est, ni à quoi il ressemble — juste qu'il y a
    # quelque chose à aller chercher, et où.
    item_x: float | None = None
    # Âges des deux événements d'interface qui court-circuitent l'élection. Le
    # `Brain` les renseigne lui-même : la fenêtre signale un clic, pas un âge.
    poke_seconds: float = 1e9
    cheer_seconds: float = 1e9

    @property
    def width(self) -> float:
        return max(0.0, self.span[1] - self.span[0])


class Action:
    """Candidate à l'élection.

    `min_seconds` est une durée plancher : une fois élue, l'action tient au
    moins ce temps. L'hystérésis du §12 empêche le clignotement entre scores
    voisins, mais elle n'empêche pas une action de durer trois ticks quand un
    besoin franchit un seuil — le plancher, si.
    """

    name: str = ""
    curve: str = ""
    expression: str = ""
    travel: str = "none"
    look_at_cursor: bool = True
    min_seconds: float = 0.0
    max_seconds: float = 0.0        # 0 = sans limite
    varies: bool = False            # reçoit le bonus de nouveauté
    # Un réflexe **traverse le plancher** de l'action en cours. Sans cela, une
    # célébration de soin pouvait arriver jusqu'à six secondes après le clic,
    # retenue par le plancher d'une sieste : le pet paraissait sourd.
    reflex: bool = False

    def is_available(self, needs, ctx, me: SelfState) -> bool:
        return True

    def score(self, needs, ctx, me: SelfState) -> float:
        return 0.0

    def plan(self) -> Plan:
        return Plan(self.name, self.curve, self.expression, self.travel,
                    self.look_at_cursor)

    def __repr__(self) -> str:
        return f"<{self.name}>"


@dataclass
class Candidate:
    """Trace d'un candidat pour un tick. Sert au diagnostic et aux tests."""

    name: str
    raw: float
    recency: float = 0.0
    hysteresis: float = 0.0

    @property
    def total(self) -> float:
        return self.raw + self.recency + self.hysteresis


def elect(actions, needs, ctx, me: SelfState, current: str,
          since: dict[str, float],
          blocked=frozenset()) -> tuple[Action | None, list[Candidate]]:
    """Élit l'action de score maximal. Retourne aussi la table des candidats.

    `since` donne, par nom d'action, le temps écoulé depuis sa dernière
    élection. `blocked` retire de la course les actions au repos forcé, celles
    qui ont épuisé leur `max_seconds`.

    Les égalités sont tranchées par l'ordre de la liste d'actions, ce
    qui rend l'élection déterministe — condition pour que la journée synthétique
    de 24 h soit rejouable.
    """
    table: list[Candidate] = []
    best: Action | None = None
    best_total = float("-inf")

    for action in actions:
        if action.name in blocked:
            continue
        if not action.is_available(needs, ctx, me):
            continue
        raw = float(action.score(needs, ctx, me))
        entry = Candidate(action.name, raw)
        if action.varies:
            age = float(since.get(action.name, RECENCY_FULL))
            entry.recency = RECENCY_BONUS * min(1.0, age / RECENCY_FULL)
        if action.name == current:
            # Borné à zéro : un bonus proportionnel appliqué à un score négatif
            # pénaliserait l'action en cours au lieu de la favoriser.
            entry.hysteresis = max(0.0, entry.total) * (HYSTERESIS - 1.0)
        table.append(entry)
        if entry.total > best_total:
            best_total, best = entry.total, action

    return best, table
