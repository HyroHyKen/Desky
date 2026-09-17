"""Superposition des couches idle / look-at / action (CDC §5, §10).

Les trois couches du §10, appliquées dans cet ordre :

1. **Idle procédural** — respiration, oscillation lente, clignements
   pseudo-aléatoires, micro-saccades du regard. « Cette couche tourne en
   permanence et porte l'essentiel de l'illusion de vie. » C'est aussi la seule
   qui n'a besoin de rien : elle rend le pet vivant sans capteur ni
   comportement, ce qui est le critère d'acceptation du lot.
2. **Look-at** — la tête s'oriente vers le curseur par ressort amorti, bornée à
   ±55° en lacet et ±35° en tangage. Au-delà, le corps pivote avec retard, et
   les pupilles atteignent la cible avant la tête.
3. **Action** — courbes de pose nommées pour les mouvements discrets.

Les couches **s'ajoutent**, elles ne s'écrasent pas : une respiration continue
pendant un bâillement. Une action peut cependant atténuer les couches
inférieures — dormir doit couper le suivi du curseur, sinon le pet suit la souris
les yeux fermés.

Le hasard de la couche idle est tiré d'un PRNG **dérivé de la graine du génome** :
le rythme des clignements et des saccades fait donc partie de l'identité du
robot, comme sa morphologie, et reste reproductible en test.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field

import numpy as np

from ..geometry.proportions import Dimensions
from ..render.face import EXPRESSIONS, FaceState
from .rig_pose import (
    Channels,
    Key,
    PoseCurve,
    RigPose,
    Spring,
    add_channels,
    ease_in_out,
    zero_channels,
)

log = logging.getLogger("desky.anim")

# Bornes du §10.2, en radians.
MAX_HEAD_YAW = math.radians(55.0)
MAX_HEAD_PITCH = math.radians(35.0)
MAX_BODY_YAW = math.radians(26.0)

# Profondeur virtuelle du regard, en hauteurs de robot. Elle décide de la
# vitesse à laquelle l'angle sature quand le curseur s'éloigne latéralement :
# petite, le pet tourne brusquement la tête dès qu'on bouge un peu.
LOOK_DEPTH = 1.7

# Distance, en hauteurs de robot, au-delà de laquelle le curseur ne l'intéresse
# plus. Le pet cesse alors de suivre et l'idle reprend la main.
#
# La valeur est contrainte par la géométrie, et non choisie librement : la tête
# sature à ±55° dès que le curseur est à `LOOK_DEPTH · tan(55°)` ≈ 2,4 hauteurs,
# et le corps finit son relais vers 11 hauteurs. Avec une portée de 5, mesurée
# au lot L4, l'intérêt tombait à zéro avant que le relais du §10.2 n'ait pu se
# produire — celui-ci était donc du code mort.
LOOK_INTEREST_RANGE = 13.0


# ---------------------------------------------------------------------------
# Contexte
# ---------------------------------------------------------------------------


@dataclass
class AnimContext:
    """Ce que l'animation reçoit du monde extérieur.

    Au lot L4 c'est la fenêtre qui le remplit, depuis le curseur. Au lot L6 ce
    sera le `brain`, qui produit un état symbolique — `action`, `look_target` —
    exactement conforme à la cloison du CDC §5 : `brain` ne connaît pas `render`.
    """

    # Décalage du curseur par rapport à la tête, **en hauteurs de robot**.
    # None quand il n'y a pas de cible : le pet cesse de suivre.
    look_offset: tuple[float, float] | None = None
    action: str | None = None
    dragging: bool = False


# ---------------------------------------------------------------------------
# Couche 1 — idle procédural
# ---------------------------------------------------------------------------

# Clignement : fermeture vive, ouverture plus lente. C'est cette asymétrie qui
# le fait lire comme un clignement et non comme un battement mécanique.
BLINK = PoseCurve("blink", (
    Key(0.00, {"face.blink": 0.0}),
    Key(0.07, {"face.blink": 1.0}, ease="out"),
    Key(0.21, {"face.blink": 0.0}, ease="in_out"),
))

# Respiration : période et amplitude. 2,4 % d'étirement suffisent — au-delà le
# robot lit comme un ballon qu'on gonfle.
BREATH_PERIOD = 3.7
BREATH_AMPLITUDE = 0.024

# Oscillation lente du corps, en radians. Volontairement incommensurable avec la
# respiration, pour que les deux ne se resynchronisent pas en un motif audible.
SWAY_PERIOD = 8.9
SWAY_AMPLITUDE = math.radians(2.6)

BLINK_INTERVAL = (2.4, 6.8)         # secondes entre deux clignements
DOUBLE_BLINK_CHANCE = 0.18
SACCADE_INTERVAL = (0.7, 2.4)       # secondes entre deux micro-saccades
SACCADE_AMPLITUDE = 0.26            # en part de la course des pupilles


class IdleLayer:
    """Respiration, oscillation, clignements, micro-saccades (CDC §10.1)."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed ^ 0x1D1E)
        self.t = 0.0
        # Phases initiales tirées au hasard : deux robots lancés en même temps
        # ne respirent pas à l'unisson.
        self._breath_phase = self.rng.uniform(0.0, math.tau)
        self._sway_phase = self.rng.uniform(0.0, math.tau)

        self._blink_at = self.rng.uniform(*BLINK_INTERVAL)
        self._blink_t: float | None = None
        self._blink_again = False

        self._saccade_at = self.rng.uniform(*SACCADE_INTERVAL)
        self._gaze = Spring(np.zeros(2), omega=24.0, zeta=0.78)
        self._gaze_target = np.zeros(2)

        self.blinks = 0
        self.saccades = 0

    def update(self, dt: float) -> Channels:
        self.t += dt
        out = zero_channels()

        # Respiration : sinusoïde sur l'échelle Y du corps (CDC §10.1).
        out["body.flex"] = BREATH_AMPLITUDE * math.sin(
            math.tau * self.t / BREATH_PERIOD + self._breath_phase)

        # Oscillation lente, et un léger contre-roulis de tête : une masse qui
        # tourne entraîne sa tête avec un temps de retard.
        sway = math.sin(math.tau * self.t / SWAY_PERIOD + self._sway_phase)
        out["body.yaw"] = SWAY_AMPLITUDE * sway
        out["head.roll"] = -0.22 * SWAY_AMPLITUDE * sway

        self._update_blink(dt, out)
        self._update_saccade(dt, out)
        return out

    def _update_blink(self, dt: float, out: Channels) -> None:
        if self._blink_t is None:
            self._blink_at -= dt
            if self._blink_at <= 0.0:
                self._blink_t = 0.0
                self.blinks += 1
                # Un double clignement de temps en temps : le rythme régulier
                # est ce qui trahit le plus vite une boucle.
                self._blink_again = self.rng.random() < DOUBLE_BLINK_CHANCE
            return

        self._blink_t += dt
        out["face.blink"] = BLINK.sample(self._blink_t)["face.blink"]
        if self._blink_t >= BLINK.duration:
            self._blink_t = None
            if self._blink_again:
                self._blink_again = False
                self._blink_at = 0.12
            else:
                self._blink_at = self.rng.uniform(*BLINK_INTERVAL)

    def _update_saccade(self, dt: float, out: Channels) -> None:
        self._saccade_at -= dt
        if self._saccade_at <= 0.0:
            self._saccade_at = self.rng.uniform(*SACCADE_INTERVAL)
            self.saccades += 1
            self._gaze_target = np.array([
                self.rng.uniform(-1.0, 1.0) * SACCADE_AMPLITUDE,
                self.rng.uniform(-0.6, 0.6) * SACCADE_AMPLITUDE,
            ])
        gaze = self._gaze.step(self._gaze_target, dt)
        out["face.gaze_x"] = float(gaze[0])
        out["face.gaze_y"] = float(gaze[1])


# ---------------------------------------------------------------------------
# Couche 2 — look-at
# ---------------------------------------------------------------------------


class LookAtLayer:
    """Suivi du curseur par ressorts amortis (CDC §10.2).

    Trois vitesses différentes, et c'est de cet étagement que vient le naturel :
    les pupilles sont les plus rapides, la tête suit, le corps traîne. Une seule
    vitesse pour les trois donnerait un mouvement de bloc.
    """

    # Pulsations propres et amortissements. La tête est légèrement sous-amortie :
    # elle dépasse un peu puis revient, ce que le §10 demande explicitement.
    GAZE = (27.0, 0.80)
    HEAD = (9.5, 0.72)
    BODY = (3.6, 1.00)

    def __init__(self) -> None:
        self._gaze = Spring(np.zeros(2), *self.GAZE)
        self._head = Spring(np.zeros(2), *self.HEAD)
        self._body = Spring(0.0, *self.BODY)
        self.interest = 0.0

    def update(self, dt: float, ctx: AnimContext) -> Channels:
        out = zero_channels()

        if ctx.look_offset is None:
            head_target = np.zeros(2)
            body_target = 0.0
            gaze_target = np.zeros(2)
            self.interest = 0.0
        else:
            dx, dy = ctx.look_offset
            distance = math.hypot(dx, dy)
            # Le curseur lointain n'intéresse plus : l'attention décroît au lieu
            # de se couper net, sinon le pet se figerait d'un coup.
            self.interest = max(0.0, 1.0 - distance / LOOK_INTEREST_RANGE)
            self.interest = ease_in_out(self.interest)

            # L'angle brut vient de la géométrie seule. L'intérêt n'intervient
            # qu'ensuite, sur le résultat : l'appliquer avant l'écrêtage
            # empêchait la tête d'atteindre sa borne, et donc le corps de
            # prendre le relais.
            raw_yaw = math.atan2(dx, LOOK_DEPTH)
            raw_pitch = math.atan2(dy, LOOK_DEPTH)

            head_yaw = max(-MAX_HEAD_YAW, min(MAX_HEAD_YAW, raw_yaw))
            head_pitch = max(-MAX_HEAD_PITCH, min(MAX_HEAD_PITCH, raw_pitch))

            # Au-delà des bornes de la tête, le corps prend le relais (§10.2).
            excess = raw_yaw - head_yaw
            body_yaw = max(-MAX_BODY_YAW, min(MAX_BODY_YAW, excess))

            head_target = np.array([head_yaw, head_pitch]) * self.interest
            body_target = body_yaw * self.interest

            # Les pupilles visent la direction brute, bornée : leur ressort étant
            # le plus rapide, elles atteignent la cible avant la tête.
            gaze_target = np.array([
                max(-1.0, min(1.0, dx / LOOK_DEPTH)),
                max(-1.0, min(1.0, dy / LOOK_DEPTH)),
            ]) * self.interest

        head = self._head.step(head_target, dt)
        body = self._body.step(body_target, dt)
        gaze = self._gaze.step(gaze_target, dt)

        out["head.yaw"] = float(head[0])
        out["head.pitch"] = float(head[1])
        out["body.yaw"] = float(body)
        out["face.gaze_x"] = float(gaze[0])
        out["face.gaze_y"] = float(gaze[1])
        return out


# ---------------------------------------------------------------------------
# Couche 3 — actions
# ---------------------------------------------------------------------------
#
# Courbes de pose nommées (CDC §10.3). Chaque segment porte un easing, et les
# mouvements marqués sont encadrés par une anticipation (`in_back`) et un
# dépassement (`out_back` ou `out_elastic`), comme le §10 l'exige.

ACTIONS: dict[str, PoseCurve] = {
    "poke_reaction": PoseCurve("poke_reaction", (
        Key(0.00, {}),
        Key(0.06, {"body.lift": 0.055, "head.pitch": 0.16,
                   "face.pupil": 0.34, "head.lift": 0.02}, ease="out"),
        Key(0.30, {"body.lift": -0.012, "head.pitch": -0.05,
                   "face.pupil": 0.12}, ease="in_out"),
        Key(0.62, {}, ease="out_back"),
    )),
    "yawn": PoseCurve("yawn", (
        Key(0.00, {}),
        Key(0.22, {"head.pitch": -0.06, "face.squint": 0.18}, ease="in_back"),
        # Anticipation vers le bas, puis la tête part franchement en arrière.
        Key(0.80, {"head.pitch": 0.30, "face.blink": 0.72,
                   "face.squint": 0.55, "body.flex": 0.045}, ease="in_out"),
        Key(1.35, {"head.pitch": 0.24, "face.blink": 0.86,
                   "face.squint": 0.62}, ease="in_out"),
        Key(1.95, {"face.blink": 0.10}, ease="out"),
        Key(2.30, {}, ease="in_out"),
    )),
    "look_around": PoseCurve("look_around", (
        Key(0.00, {}),
        Key(0.55, {"head.yaw": -0.52, "face.gaze_x": -0.55}, ease="in_out"),
        Key(1.05, {"head.yaw": -0.46, "face.gaze_x": -0.30}, ease="in_out"),
        Key(1.75, {"head.yaw": 0.54, "face.gaze_x": 0.58,
                   "body.yaw": 0.10}, ease="in_out"),
        Key(2.25, {"head.yaw": 0.48, "face.gaze_x": 0.32}, ease="in_out"),
        Key(2.95, {}, ease="out_back"),
    )),
    "celebrate": PoseCurve("celebrate", (
        Key(0.00, {}),
        Key(0.10, {"body.lift": -0.030, "body.flex": -0.030}, ease="in_back"),
        Key(0.34, {"body.lift": 0.120, "body.flex": 0.055,
                   "face.squint": 0.50, "face.pupil": 0.18}, ease="out"),
        Key(0.62, {"body.lift": 0.0, "face.squint": 0.42}, ease="in"),
        Key(0.90, {"body.lift": 0.070, "face.squint": 0.46}, ease="out"),
        Key(1.45, {}, ease="out_elastic"),
    )),
    "sit": PoseCurve("sit", (
        Key(0.00, {}),
        Key(0.16, {"body.lift": 0.022}, ease="in_back"),
        Key(0.70, {"body.lift": -0.115, "body.flex": 0.060,
                   "head.pitch": -0.06}, ease="in_out"),
        Key(0.95, {"body.lift": -0.100, "body.flex": 0.050,
                   "head.pitch": -0.04}, ease="out_back"),
    )),
    "stand": PoseCurve("stand", (
        Key(0.00, {"body.lift": -0.100, "body.flex": 0.050}),
        Key(0.44, {"body.lift": 0.026, "body.flex": -0.014}, ease="out"),
        Key(0.78, {}, ease="out_back"),
    )),
    "sleep": PoseCurve("sleep", (
        Key(0.00, {}),
        Key(0.90, {"head.pitch": -0.22, "face.blink": 0.55,
                   "ear.droop": 0.30, "body.lift": -0.045}, ease="in_out"),
        Key(1.70, {"head.pitch": -0.30, "face.blink": 0.90,
                   "face.lid_bottom": 0.28, "ear.droop": 0.52,
                   "body.lift": -0.060}, ease="in_out"),
    )),
}

# Atténuation des couches inférieures pendant une action : (look-at, idle).
# Dormir doit couper le suivi du curseur, sinon le pet suit la souris les yeux
# fermés. S'asseoir, au contraire, laisse le regard libre.
ACTION_DAMPING: dict[str, tuple[float, float]] = {
    "sleep": (1.00, 0.55),
    "yawn": (0.70, 0.20),
    "look_around": (0.95, 0.10),
    "celebrate": (0.60, 0.15),
    "poke_reaction": (0.35, 0.05),
    "sit": (0.10, 0.05),
    "stand": (0.20, 0.05),
}

# Les actions qui tiennent leur pose finale au lieu de se terminer.
SUSTAINED = frozenset({"sit", "sleep"})

FADE_IN = 0.18
FADE_OUT = 0.28


class ActionLayer:
    """Joue une courbe de pose nommée, avec entrée et sortie en fondu."""

    def __init__(self) -> None:
        self.name: str | None = None
        self.t = 0.0
        self._weight = 0.0
        self._fading_out = False
        self.played = 0

    @property
    def busy(self) -> bool:
        return self.name is not None and not self._fading_out

    @property
    def animating(self) -> bool:
        """Une pose est-elle en train de **changer** ?

        À distinguer de `busy`, qui dit seulement qu'une action est chargée.
        Les deux diffèrent exactement sur les actions soutenues — `sit`, `sleep`
        — qui tiennent leur pose finale indéfiniment : `busy` y reste vrai pour
        toujours alors que plus rien ne bouge.

        La distinction n'existait pas avant que la cadence en dépende. Elle a
        été ajoutée après avoir mesuré un pet **endormi** qui tenait
        l'application à 30 fps.
        """
        if self.name is None:
            return False
        if self._fading_out or self._weight < 1.0:
            return True                     # fondu d'entrée ou de sortie
        if self.name in SUSTAINED:
            return self.t < ACTIONS[self.name].duration
        return True

    def play(self, name: str) -> None:
        if name not in ACTIONS:
            raise KeyError(f"action inconnue : {name!r}")
        if self.name == name and not self._fading_out:
            return
        self.name = name
        self.t = 0.0
        self._fading_out = False
        self.played += 1
        log.debug("action %s", name)

    def stop(self) -> None:
        if self.name is not None:
            self._fading_out = True

    def update(self, dt: float) -> tuple[Channels, float, tuple[float, float]]:
        """Retourne (canaux, poids, atténuation des couches inférieures)."""
        if self.name is None:
            return {}, 0.0, (0.0, 0.0)

        curve = ACTIONS[self.name]
        self.t += dt

        # Fin naturelle d'une action non soutenue.
        if not self._fading_out and self.name not in SUSTAINED:
            if self.t >= curve.duration:
                self._fading_out = True

        target = 0.0 if self._fading_out else 1.0
        rate = dt / (FADE_OUT if self._fading_out else FADE_IN)
        self._weight += max(-rate, min(rate, target - self._weight))
        # Fondu adouci : une rampe linéaire de poids se verrait à la jonction.
        weight = ease_in_out(max(0.0, min(1.0, self._weight)))

        if self._fading_out and self._weight <= 0.0:
            self.name = None
            self._weight = 0.0
            self._fading_out = False
            return {}, 0.0, (0.0, 0.0)

        damping = ACTION_DAMPING.get(self.name, (0.0, 0.0))
        return curve.sample(self.t), weight, (damping[0] * weight,
                                              damping[1] * weight)


# ---------------------------------------------------------------------------
# Traduction des canaux vers le rig et le visage
# ---------------------------------------------------------------------------


# Répartition du regard sur un monobloc (lot L17).
#
# Une coque d'un seul tenant n'a pas de tête à tourner. Faire pivoter le nœud
# `head` n'y ferait tourner que la dalle faciale, qui épouse la surface du bloc
# et s'en décollerait aussitôt. La rotation est donc **reportée sur le corps** :
# c'est le bloc entier qui s'oriente, et les pupilles — dont le ressort est le
# plus rapide des trois (§10.2) — font le reste du travail.
#
# Le report est partiel et borné : un bloc qui pivoterait autant qu'une tête ne
# se lirait pas comme un regard mais comme une chute.
MONOBLOC_TRANSFER = 0.52
MAX_MONOBLOC_YAW = math.radians(24.0)
MAX_MONOBLOC_PITCH = math.radians(15.0)


def apply_channels(pose: RigPose, channels: Channels, dims: Dimensions) -> FaceState:
    """Écrit les canaux dans le rig, et retourne l'état de visage correspondant.

    C'est le **seul** point de code qui connaisse à la fois les canaux et la
    géométrie. Les couches produisent des noms, ce module les traduit, et rien
    d'autre n'a besoin de savoir comment un canal devient une matrice.
    """
    pose.reset()

    # Convention des canaux de tangage : **positif = vers le haut**.
    #
    # `rotation_x` positive envoie l'axe +Z — la direction du visage — vers les y
    # négatifs, donc vers le bas. Le signe est donc inversé ici, une fois, plutôt
    # que dans chaque couche et chaque courbe. Sans cette convention explicite,
    # le suivi du curseur baissait la tête quand la souris montait, et le
    # bâillement s'inclinait du mauvais côté.
    head_yaw = channels.get("head.yaw", 0.0)
    head_pitch = channels.get("head.pitch", 0.0)
    body_yaw = channels.get("body.yaw", 0.0)
    body_pitch = channels.get("body.pitch", 0.0)

    if dims.monobloc:
        body_yaw = _clamp(body_yaw + head_yaw * MONOBLOC_TRANSFER,
                          -MAX_MONOBLOC_YAW, MAX_MONOBLOC_YAW)
        body_pitch = _clamp(body_pitch + head_pitch * MONOBLOC_TRANSFER,
                            -MAX_MONOBLOC_PITCH, MAX_MONOBLOC_PITCH)
        # La dalle ne bouge plus du tout : elle est collée au bloc.
        head_yaw = head_pitch = 0.0

    pose.offset("body", rotation=(-body_pitch, body_yaw,
                                  channels.get("body.roll", 0.0)))
    pose.offset("body", translation=(0.0, channels.get("body.lift", 0.0), 0.0))

    # Respiration : échelle Y du corps, compensée pour que les pieds restent
    # plantés au sol, et report de la montée de poitrine sur le cou.
    #
    # Le maillage du corps est porté par `body_flex`, un nœud enfant dédié :
    # mettre l'échelle sur `body` lui-même la propagerait au cou et à la tête,
    # qui s'étireraient avec la respiration.
    flex = channels.get("body.flex", 0.0)
    if flex:
        # Plancher : `body.flex` cumule la respiration, la démarche et
        # l'encaissement du lot L10, et rien n'empêche la somme de descendre
        # sous -1. Une échelle nulle aplatit le corps sur un plan, une échelle
        # négative le retourne — deux façons de transformer un défaut de
        # réglage en robot méconnaissable.
        s = max(0.35, 1.0 + flex)
        # **Volume conservé** : ce qui s'écrase s'élargit. Sans cette largeur,
        # un corps comprimé rétrécit tout court, et le §10 n'y voit qu'un objet
        # qui diminue au lieu d'un objet qui encaisse. C'est ce seul facteur qui
        # sépare un écrasement d'une réduction de taille.
        w = 1.0 / math.sqrt(s)
        pose.offset("body_flex", scale=(w, s, w),
                    translation=(0.0, dims.body_b * (s - 1.0), 0.0))
        # Report de la montée de poitrine sur le cou. Le sommet du maillage
        # porteur n'est pas le même selon le châssis — `carrier_top` le dit —
        # et sans cette distinction le visage d'un monobloc glisserait sur son
        # bloc à chaque atterrissage.
        pose.offset("neck", translation=(0.0, dims.carrier_top * (s - 1.0), 0.0))

    pose.offset("head", rotation=(-head_pitch, head_yaw,
                                  channels.get("head.roll", 0.0)))
    pose.offset("head", translation=(0.0, channels.get("head.lift", 0.0), 0.0))

    droop = channels.get("ear.droop", 0.0)
    if droop:
        # Signes opposés : les deux oreilles tombent vers l'extérieur.
        pose.offset("ear_l", rotation=(0.0, 0.0, droop))
        pose.offset("ear_r", rotation=(0.0, 0.0, -droop))

    pose.apply()

    return FaceState(
        blink=_clamp(channels.get("face.blink", 0.0), 0.0, 1.0),
        gaze_x=_clamp(channels.get("face.gaze_x", 0.0), -1.0, 1.0),
        gaze_y=_clamp(channels.get("face.gaze_y", 0.0), -1.0, 1.0),
        lid_top=_clamp(channels.get("face.lid_top", 0.0), -0.5, 1.0),
        lid_bottom=_clamp(channels.get("face.lid_bottom", 0.0), -0.5, 1.0),
        squint=_clamp(channels.get("face.squint", 0.0), 0.0, 1.0),
        pupil_scale=_clamp(1.0 + channels.get("face.pupil", 0.0), 0.5, 2.0),
        glitch=_clamp(channels.get("face.glitch", 0.0), 0.0, 1.0),
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Couche 4 — humeur (lot L6)
# ---------------------------------------------------------------------------

# Constante de temps du glissement vers une nouvelle humeur. Un changement
# instantané se lit comme un défaut d'affichage ; au-delà d'une seconde, le pet
# a l'air de ne pas réagir à ce qu'on vient de lui faire.
MOOD_TAU = 0.32


def blend_mood(mood: FaceState, animated: FaceState) -> FaceState:
    """Superpose le visage animé sur la ligne de base de l'humeur.

    Un simple `lerp` ne conviendrait pas : à mi-chemin d'un mélange, un
    clignement ne fermerait les yeux qu'à moitié et l'humeur serait diluée.
    Les occlusions **s'ajoutent** — un clignement pendant un sourire ferme bien
    les yeux — la dilatation se **multiplie**, et le regard n'appartient qu'à
    l'animation : une humeur ne décide pas où le pet regarde.
    """
    return FaceState(
        blink=_clamp(mood.blink + animated.blink, 0.0, 1.0),
        gaze_x=animated.gaze_x,
        gaze_y=animated.gaze_y,
        lid_top=_clamp(mood.lid_top + animated.lid_top, -0.5, 1.0),
        lid_bottom=_clamp(mood.lid_bottom + animated.lid_bottom, -0.5, 1.0),
        squint=_clamp(mood.squint + animated.squint, 0.0, 1.0),
        pupil_scale=_clamp(mood.pupil_scale * animated.pupil_scale, 0.5, 2.0),
        glitch=_clamp(mood.glitch + animated.glitch, 0.0, 1.0),
    )


class MoodLayer:
    """Ligne de base du visage, glissée vers l'expression demandée.

    Le `brain` publie un **nom** d'expression, jamais un `FaceState` : c'est la
    cloison du §5. La résolution du nom se fait ici, contre la table du §9.
    """

    def __init__(self, name: str = "neutre") -> None:
        self.name = name
        self.face = EXPRESSIONS.get(name, FaceState())

    def set(self, name: str) -> None:
        if name and name != self.name and name in EXPRESSIONS:
            self.name = name

    def update(self, dt: float) -> FaceState:
        target = EXPRESSIONS.get(self.name, FaceState())
        if dt > 0.0:
            # Glissement exponentiel : exact pour n'importe quel dt, ce qui
            # compte ici parce que dt triple entre les régimes de la cadence.
            self.face = self.face.lerp(target, 1.0 - math.exp(-dt / MOOD_TAU))
        return self.face


@dataclass
class AnimStats:
    """Compteurs d'activité. Servent au diagnostic et au test d'intérêt."""

    blinks: int = 0
    saccades: int = 0
    actions: int = 0


class Animator:
    """Enchaîne les trois couches et écrit dans le rig et le visage.

    `base_pose` doit venir de `Robot.base_pose` : c'est la pose de repos relevée
    à la construction. L'omettre fait relever l'état courant du rig, ce qui n'est
    juste que si rien ne l'a encore animé.
    """

    @classmethod
    def for_robot(cls, robot, seed: int = 0) -> "Animator":
        """Constructeur recommandé : prend la base de repos du robot."""
        return cls(robot.rig, robot.dims, seed=seed, base_pose=robot.base_pose)

    def __init__(self, rig, dims: Dimensions, seed: int = 0,
                 base_pose: dict | None = None) -> None:
        self.pose = RigPose(rig, base_pose)
        self.dims = dims
        self.idle = IdleLayer(seed)
        self.look = LookAtLayer()
        self.action = ActionLayer()
        self.mood = MoodLayer()
        self.face = FaceState()
        self.channels: Channels = zero_channels()

    def play(self, name: str) -> None:
        self.action.play(name)

    def set_mood(self, name: str) -> None:
        """Change l'humeur de fond. Un nom inconnu est ignoré, pas rejeté."""
        self.mood.set(name)

    def stop_action(self) -> None:
        self.action.stop()

    @property
    def stats(self) -> AnimStats:
        return AnimStats(self.idle.blinks, self.idle.saccades, self.action.played)

    def update(self, dt: float, ctx: AnimContext | None = None,
               extra: Channels | None = None) -> FaceState:
        """`extra` superpose une couche produite ailleurs.

        La démarche du lot L5b arrive par là : la locomotion est une affaire de
        **position**, pas de pose, donc elle vit hors de l'animateur — mais son
        balancement doit se superposer aux trois couches du §10 comme les autres.
        """
        ctx = ctx or AnimContext()
        if ctx.action is not None:
            self.action.play(ctx.action)

        action_ch, weight, (damp_look, damp_idle) = self.action.update(dt)

        channels = zero_channels()
        add_channels(channels, self.idle.update(dt), 1.0 - damp_idle)
        add_channels(channels, self.look.update(dt, ctx), 1.0 - damp_look)
        if weight > 0.0:
            add_channels(channels, action_ch, weight)
        if extra:
            add_channels(channels, extra)

        self.channels = channels
        animated = apply_channels(self.pose, channels, self.dims)
        self.face = blend_mood(self.mood.update(dt), animated)
        return self.face
