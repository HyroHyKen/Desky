"""Rejeu d'une trace de contexte à travers le `brain`, et son rapport.

C'est l'instrument sur lequel s'appuient deux critères d'acceptation du lot L6 :
le comptage des changements d'action sur trente minutes, et l'histogramme du
temps passé par action sur une journée de 24 h. Il sert autant à **régler** qu'à
valider — c'est la raison de l'écrire avant les scorers plutôt qu'après.

Deux approximations, assumées et à garder en tête en lisant un rapport :

- la **locomotion n'est pas simulée**. `travelling` est tenu pour vrai pendant
  quelques secondes après un plan qui demande un trajet, ce qui suffit à
  interdire `look_around` pendant un déplacement mais ne reproduit pas les
  durées réelles ;
- le **curseur est synthétisé** depuis une graine, la trace n'en contenant pas
  (cf. `trace`). L'équilibre de `follow_cursor` est donc mesuré sur un rythme
  d'activité plausible, pas sur des trajectoires réelles.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .actions import REFLEXES
from .brain import TICK, Brain
from . import consumables
from .needs import NEEDS, game_fun
from .sensors import SystemContext
from .trace import Trace
from .utility import SelfState

# Durée pendant laquelle un plan de trajet est tenu pour un déplacement en
# cours. Ordre de grandeur d'un trajet du lot L5b, pas une mesure.
TRAVEL_SECONDS = 4.0

# Le curseur ne se déplace que si l'utilisateur est là. Nouvelle cible toutes
# les vingt secondes environ, atteinte à vitesse constante.
CURSOR_RETARGET = 20.0
CURSOR_SPEED = 420.0

# Intervalle moyen entre deux frappes ou clics, par état de présence. Remettre
# `idle_seconds` à zéro à chaque tick pendant `typing` était le premier défaut
# trouvé par cet outil : c'est irréaliste — un humain qui travaille marque des
# pauses de quelques secondes en permanence — et ça rendait `look_around`
# structurellement inatteignable.
INPUT_GAP = {"typing": 3.0, "browsing": 8.0}

# Clics sur le pet par heure de présence. Sans eux, `react_to_poke` et
# `happy_bounce` sortent du rapport comme « inatteignables » alors qu'ils sont
# seulement inatteignables *par le contexte*.
POKES_PER_HOUR = 2.5

# Politique de soin « raisonnable » : un utilisateur présent qui jette un oeil
# toutes les cinq minutes et sert ce qui manque. Sert à répondre à une question
# précise — les besoins tiennent-ils dans une bande saine avec un soin normal.
CARE_CHECK = 300.0
CARE_THRESHOLD = 40.0
# Ce que sert un utilisateur attentif, besoin par besoin. Depuis le lot L13 il
# ne s'agit plus de boutons gratuits : la faim et l'hygiène passent par des
# **consommables** qu'il faut posséder, l'amusement par une **partie**, et seule
# la caresse reste un soin au sens ancien.
#
# La simulation suppose un stock fourni — la question qu'elle pose est « les
# besoins tiennent-ils dans une bande saine avec un soin normal », pas « le
# joueur a-t-il assez de jetons ». Cette seconde question est celle de
# l'économie, et elle se règle par le prix, pas ici.
CONSUMABLE_FOR_NEED = {"hunger": "meal", "hygiene": "kit"}
CARE_FOR_NEED = {"fun": "pet"}

# Échanges d'une partie type dans la simulation. Une partie honnête sans être
# brillante : c'est ce qu'un utilisateur attentif obtient en jouant de temps en
# temps, pas un record.
SIM_RALLY = 10


@dataclass
class Report:
    duration: float = 0.0
    present: float = 0.0
    seconds_by_action: dict[str, float] = field(default_factory=dict)
    present_by_action: dict[str, float] = field(default_factory=dict)
    mood_seconds: dict[str, float] = field(default_factory=dict)
    changes: int = 0
    cares: dict[str, int] = field(default_factory=dict)
    needs_min: dict[str, float] = field(default_factory=dict)
    needs_max: dict[str, float] = field(default_factory=dict)
    needs_mean: dict[str, float] = field(default_factory=dict)
    episodes: list[tuple[str, float]] = field(default_factory=list)
    curve: list[tuple[float, dict[str, float], str]] = field(default_factory=list)

    @property
    def changes_per_hour(self) -> float:
        if self.duration <= 0.0:
            return 0.0
        return self.changes / (self.duration / 3600.0)

    def share(self) -> dict[str, float]:
        """Part de la durée totale, par action, en pourcentage."""
        if self.duration <= 0.0:
            return {}
        return {name: 100.0 * s / self.duration
                for name, s in self.seconds_by_action.items()}

    def share_present(self) -> dict[str, float]:
        """Part du temps **où l'utilisateur est là**, par action.

        C'est le dénominateur qui a un sens pour juger la domination, et la
        première version de cette métrique était fausse : mesurée sur l'horloge
        murale, elle accusait `nap` de dominer à 91 % un profil où la machine
        tourne seule vingt-deux heures. Un pet laissé seul *doit* dormir. Ce que
        le critère du lot veut interdire, c'est un pet qui ne fait qu'une seule
        chose **pendant qu'on le regarde**.
        """
        if self.present <= 0.0:
            return {}
        return {name: 100.0 * s / self.present
                for name, s in self.present_by_action.items()}

    def unreachable(self) -> tuple[str, ...]:
        return tuple(n for n, s in self.seconds_by_action.items() if s <= 0.0)

    def dominant(self, limit: float = 60.0) -> tuple[str, ...]:
        return tuple(n for n, p in self.share_present().items() if p > limit)

    def flickers(self, floor: float = 1.0) -> dict[str, int]:
        """Épisodes anormalement courts, par action.

        Deux exclusions, et les deux ont été apprises en mesurant :

        - un **réflexe** est court par nature — la courbe de réaction au clic
          du lot L4 dure 0,62 s ;
        - un épisode **interrompu par** un réflexe est écourté légitimement,
          puisque c'est exactement ce qu'un réflexe est censé faire.

        Ce qui reste après ces deux retraits est du vrai clignotement : une
        action qui n'a pas tenu son plancher sans qu'on la dérange.
        """
        out: dict[str, int] = {}
        for index, (name, duration) in enumerate(self.episodes):
            if duration >= floor or name in REFLEXES:
                continue
            suivant = (self.episodes[index + 1][0]
                       if index + 1 < len(self.episodes) else "")
            if suivant in REFLEXES:
                continue
            out[name] = out.get(name, 0) + 1
        return out

    def episode_stats(self) -> dict[str, float]:
        """Statistiques de durée d'épisode, pour le critère de clignotement.

        Le nombre de changements par heure ne suffit pas à juger : c'est une
        moyenne, et un pet parfaitement stable vingt-trois heures puis frénétique
        une heure la passerait. Ce sont les épisodes **courts** qui trahissent un
        clignotement.
        """
        if not self.episodes:
            return {}
        durations = sorted(d for _, d in self.episodes)
        middle = len(durations) // 2
        median = (durations[middle] if len(durations) % 2
                  else 0.5 * (durations[middle - 1] + durations[middle]))
        return {
            "episodes": float(len(durations)),
            "min": durations[0],
            "median": median,
            "p90": durations[min(len(durations) - 1, int(0.9 * len(durations)))],
            "sous_1s": float(sum(1 for d in durations if d < 1.0)),
        }


def replay(trace: Trace, brain: Brain | None = None, dt: float = TICK,
           care: str = "none", seed: int = 0, pet_h: float = 150.0,
           span: tuple[float, float] = (0.0, 3840.0),
           sample_every: float = 120.0) -> tuple[Brain, Report]:
    """Fait vivre `trace` au `brain` et retourne le rapport."""
    brain = brain if brain is not None else Brain()
    rng = random.Random(seed)
    report = Report(duration=trace.duration)
    report.seconds_by_action = {a.name: 0.0 for a in brain.actions}
    report.present_by_action = {a.name: 0.0 for a in brain.actions}
    episode_action = ""
    episode_length = 0.0

    me = SelfState(x=0.5 * (span[0] + span[1]), pet_h=pet_h, span=span)
    me.home_x = me.x
    cursor_x = me.x
    cursor_goal = me.x
    retarget = 0.0
    travel_left = 0.0
    idle_seconds = 0.0
    next_input = 0.0
    poke_left = 3600.0 / POKES_PER_HOUR
    care_left = CARE_CHECK
    next_sample = 0.0
    totals = {name: 0.0 for name in NEEDS}
    ticks = 0

    index = 0
    state = trace.samples[0].state if trace.samples else "idle"
    t = 0.0

    while t < trace.duration:
        while (index + 1 < len(trace.samples)
               and trace.samples[index + 1].t <= t):
            index += 1
            state = trace.samples[index].state

        present = state in ("typing", "browsing")
        if present:
            next_input -= dt
            if next_input <= 0.0:
                idle_seconds = 0.0
                next_input = rng.expovariate(1.0 / INPUT_GAP[state])
            else:
                idle_seconds += dt
        else:
            idle_seconds += dt

        # Curseur synthétique.
        speed = 0.0
        if present:
            retarget -= dt
            if retarget <= 0.0:
                cursor_goal = rng.uniform(span[0], span[1])
                retarget = CURSOR_RETARGET
            step = CURSOR_SPEED * dt
            delta = cursor_goal - cursor_x
            if abs(delta) > step:
                cursor_x += step if delta > 0 else -step
                speed = CURSOR_SPEED
            else:
                cursor_x = cursor_goal

        ctx = SystemContext(
            state=state, idle_seconds=idle_seconds,
            cursor=(int(cursor_x), 500), cursor_speed=speed,
            media_playing=(state == "watching"),
        )

        travel_left = max(0.0, travel_left - dt)
        me.travelling = travel_left > 0.0

        if present:
            poke_left -= dt
            if poke_left <= 0.0:
                poke_left = rng.expovariate(POKES_PER_HOUR / 3600.0)
                brain.poke()

        plan = brain.update(dt, ctx, me)
        if plan.travel in ("wander", "cursor", "edge"):
            travel_left = TRAVEL_SECONDS

        report.seconds_by_action[plan.action] = (
            report.seconds_by_action.get(plan.action, 0.0) + dt)
        # « Présent » vaut ici « pas parti » : `idle` et `watching` sont des
        # états où l'utilisateur est devant sa machine, seul `away` ne l'est pas.
        if state != "away":
            report.present += dt
            report.present_by_action[plan.action] = (
                report.present_by_action.get(plan.action, 0.0) + dt)

        if plan.action != episode_action:
            if episode_action:
                report.episodes.append((episode_action, episode_length))
            episode_action, episode_length = plan.action, 0.0
        episode_length += dt

        mood = brain.expression
        report.mood_seconds[mood] = report.mood_seconds.get(mood, 0.0) + dt

        for name in NEEDS:
            value = getattr(brain.needs, name)
            totals[name] += value
            if name not in report.needs_min or value < report.needs_min[name]:
                report.needs_min[name] = value
            if name not in report.needs_max or value > report.needs_max[name]:
                report.needs_max[name] = value
        ticks += 1

        # Soin simulé.
        if care == "reasonable":
            care_left -= dt
            if present and care_left <= 0.0:
                care_left = CARE_CHECK
                for need, cle in CONSUMABLE_FOR_NEED.items():
                    if getattr(brain.needs, need) >= CARE_THRESHOLD:
                        continue
                    article = consumables.get(cle)
                    if article and brain.needs.apply({article.need: article.gain}):
                        report.cares[cle] = report.cares.get(cle, 0) + 1
                for need, kind in CARE_FOR_NEED.items():
                    if getattr(brain.needs, need) < CARE_THRESHOLD:
                        if brain.care(kind):
                            report.cares[kind] = report.cares.get(kind, 0) + 1
                # Une partie quand il s'ennuie : c'est désormais ce qui amuse.
                if brain.needs.fun < CARE_THRESHOLD:
                    brain.needs.apply({"fun": game_fun(SIM_RALLY)})
                    report.cares["rally"] = report.cares.get("rally", 0) + 1

        if t >= next_sample:
            report.curve.append((t, brain.needs.as_dict(), plan.action))
            next_sample = t + sample_every

        t += dt

    if episode_action:
        report.episodes.append((episode_action, episode_length))
    report.changes = brain.changes
    if ticks:
        report.needs_mean = {n: totals[n] / ticks for n in NEEDS}
    return brain, report
