"""Traces de contexte : enregistrer une journée réelle, ou en fabriquer une.

Deux critères d'acceptation du lot L6 ne sont pas vérifiables sans cet outil —
« aucun clignotement entre actions » sur trente minutes rejouées, et « aucune
action inatteignable ni dominante » sur une journée de 24 h. Les deux demandent
de faire vivre au `brain` un temps long, en quelques secondes et de façon
reproductible.

**Une trace ne contient que des changements d'état symbolique et leur date.**
Ni titre de fenêtre, ni URL, ni nom de process, ni position de curseur : la
garantie du §11 est ici vérifiable à l'oeil sur le fichier lui-même. Le curseur
nécessaire à `follow_cursor` est **synthétisé** au rejeu depuis une graine, ce
qui est une limite assumée — la trace ne rejoue pas les trajectoires réelles du
curseur, seulement le rythme d'activité qui gouverne les besoins.

Module pur, comme le reste du `brain` : aucun GPU, aucun Qt.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

HOUR = 3600.0

STATES: tuple[str, ...] = ("typing", "browsing", "watching", "idle", "away")

# Journées types, en blocs de (durée en heures, mélange d'états pondéré). Elles
# commencent à minuit. Les poids ne sont pas des probabilités instantanées : un
# état tiré est **tenu** pendant `HOLD_SECONDS`, sinon le pet verrait un
# scintillement de contexte qu'aucun capteur réel ne produirait.
PROFILES: dict[str, tuple[tuple[float, dict[str, float]], ...]] = {
    # Journée de bureau : nuit, matinée dense, pause déjeuner, après-midi,
    # soirée devant un film.
    "bureau": (
        (7.5, {"away": 1.0}),
        (0.5, {"idle": 0.6, "browsing": 0.4}),
        (3.5, {"typing": 0.62, "browsing": 0.28, "idle": 0.10}),
        (1.0, {"away": 0.85, "idle": 0.15}),
        (4.5, {"typing": 0.55, "browsing": 0.30, "idle": 0.15}),
        (2.0, {"away": 0.9, "idle": 0.1}),
        (2.5, {"watching": 0.88, "browsing": 0.12}),
        (1.5, {"browsing": 0.5, "idle": 0.3, "away": 0.2}),
        (1.0, {"away": 1.0}),
    ),
    # Machine allumée mais utilisateur rare : le cas qui doit faire dormir le
    # pet et faire descendre `fun`.
    "absent": (
        (22.0, {"away": 0.95, "idle": 0.05}),
        (1.5, {"typing": 0.4, "browsing": 0.4, "idle": 0.2}),
        (0.5, {"away": 1.0}),
    ),
    # Utilisateur du soir, et gros consommateur de vidéo.
    "soiree": (
        (9.0, {"away": 1.0}),
        (8.0, {"away": 0.8, "idle": 0.2}),
        (1.0, {"browsing": 0.7, "typing": 0.3}),
        (4.0, {"watching": 0.85, "browsing": 0.15}),
        (2.0, {"typing": 0.45, "browsing": 0.35, "idle": 0.20}),
    ),
}

# Durée moyenne pendant laquelle un état tiré est tenu, et sa dispersion.
HOLD_SECONDS = 240.0
HOLD_JITTER = 0.6


# Résolution de l'horodatage d'une trace. Arrondir à la source plutôt qu'à
# l'écriture garantit qu'une trace relue est **identique** à celle enregistrée :
# sans cela, l'aller-retour par le disque perdait des décimales et un rejeu
# n'était plus tout à fait le même.
TIME_PLACES = 3


@dataclass(frozen=True)
class Sample:
    """Un changement d'état, et la seconde où il survient."""

    t: float
    state: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "t", round(float(self.t), TIME_PLACES))


@dataclass
class Trace:
    """Suite de changements d'état, croissante en temps."""

    samples: tuple[Sample, ...] = ()
    duration: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        last = -1.0
        for s in self.samples:
            if s.t < last:
                raise ValueError("trace non croissante en temps")
            if s.state not in STATES:
                raise ValueError(f"état inconnu dans la trace : {s.state!r}")
            last = s.t

    def state_at(self, t: float) -> str:
        """État en vigueur à l'instant `t`. Recherche linéaire assumée.

        Le rejeu avance monotonement, donc `replay` maintient son propre index
        et n'appelle pas cette méthode dans sa boucle ; elle n'existe que pour
        l'inspection et les tests.
        """
        current = "idle"
        for s in self.samples:
            if s.t > t:
                break
            current = s.state
        return current

    def histogram(self) -> dict[str, float]:
        """Secondes passées dans chaque état. Sert à valider un profil."""
        out = {name: 0.0 for name in STATES}
        for index, s in enumerate(self.samples):
            end = (self.samples[index + 1].t if index + 1 < len(self.samples)
                   else self.duration)
            out[s.state] += max(0.0, end - s.t)
        return out

    def save(self, path: Path) -> None:
        payload = {
            "label": self.label,
            "duration": round(self.duration, TIME_PLACES),
            "samples": [[s.t, s.state] for s in self.samples],
        }
        Path(path).write_text(json.dumps(payload, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Trace":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        samples = tuple(Sample(float(t), str(state))
                        for t, state in raw.get("samples", ()))
        return cls(samples, float(raw.get("duration", 0.0)),
                   str(raw.get("label", "")))


def synthetic_day(profile: str = "bureau", seed: int = 0,
                  hours: float = 24.0) -> Trace:
    """Fabrique une journée type, reproductible pour une graine donnée."""
    blocks = PROFILES.get(profile)
    if blocks is None:
        raise KeyError(f"profil inconnu : {profile!r}")

    rng = random.Random(seed)
    total = sum(d for d, _ in blocks) * HOUR
    scale = (hours * HOUR) / total if total > 0 else 1.0

    samples: list[Sample] = []
    t = 0.0
    limit = hours * HOUR
    previous = ""

    for duration, mix in blocks:
        end = min(limit, t + duration * HOUR * scale)
        names = tuple(mix)
        weights = tuple(mix[n] for n in names)
        while t < end:
            state = rng.choices(names, weights=weights, k=1)[0]
            if state != previous:
                samples.append(Sample(t, state))
                previous = state
            hold = HOLD_SECONDS * (1.0 + rng.uniform(-HOLD_JITTER, HOLD_JITTER))
            t += max(30.0, hold)
        t = end

    if not samples:
        samples.append(Sample(0.0, "idle"))
    return Trace(tuple(samples), limit, f"{profile}#{seed}")


class Recorder:
    """Enregistre les changements d'état d'une session réelle.

    N'écrit qu'à la demande : un enregistreur qui écrit en continu ferait du
    lot L6 la première brique du projet à produire un journal permanent, et le
    §11 mérite mieux que ça. C'est un outil de mise au point, pas un capteur.
    """

    def __init__(self, label: str = "session") -> None:
        self.label = label
        self._samples: list[Sample] = []
        self._t = 0.0
        self._state = ""

    def feed(self, dt: float, state: str) -> None:
        self._t += max(0.0, float(dt))
        if state in STATES and state != self._state:
            self._samples.append(Sample(self._t, state))
            self._state = state

    def trace(self) -> Trace:
        return Trace(tuple(self._samples), round(self._t, TIME_PLACES),
                     self.label)
