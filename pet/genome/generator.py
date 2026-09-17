"""Génération d'un génome depuis une graine (CDC §7).

Deux garanties, et ce sont les critères d'acceptation du lot L2 :

1. **Déterminisme.** Une même graine produit toujours le même génome, donc la
   même géométrie. Le PRNG est un `random.Random` dédié, jamais le module
   `random` global — un appel étranger dans le process suffirait sinon à
   décaler la séquence.
2. **Viabilité.** Après tirage, une passe de validation rejette les combinaisons
   non viables et retire. Le CDC §7 le formule ainsi : « le charme naît de la
   variation contrôlée, pas du chaos ».
"""

from __future__ import annotations

import logging
import random
from typing import Any

from ..geometry import proportions
from .schema import PARAMS, SCHEMA_VERSION, Choice, Num

log = logging.getLogger("desky.genome")

# Ratio maximal entre largeur de tête et largeur de corps (CDC §7).
MAX_HEAD_BODY_RATIO = 1.8

# Marge exigée entre le bord intérieur d'une oreille latérale et la dalle
# faciale, en unités du robot. Une valeur nulle autoriserait le contact.
EAR_PLATE_MARGIN = 0.02

# Un cou n'a de sens que s'il est visible : en dessous, on le considère nul et la
# tête est posée sur le corps. Évite un anneau d'un pixel entre deux parties.
NECK_MIN_VISIBLE = 0.04

MAX_ATTEMPTS = 64


class GenomeGenerationError(RuntimeError):
    """Aucun génome viable trouvé. Signale des bornes incohérentes, pas de la malchance."""


def new_seed(rng: random.Random | None = None) -> int:
    source = rng or random.SystemRandom()
    return source.randrange(1, 2 ** 53)


def draw(rng: random.Random) -> dict[str, Any]:
    """Tire un génome, sans validation.

    Consomme le PRNG dans l'ordre de `PARAMS`. Cet ordre est le contrat de
    déterminisme : ajouter un paramètre ailleurs qu'à la fin changerait tous les
    robots existants générés depuis leur graine.
    """
    genome: dict[str, Any] = {}
    for p in PARAMS:
        if isinstance(p, Num):
            genome[p.key] = rng.uniform(p.lo, p.hi)
        elif isinstance(p, Choice):
            genome[p.key] = rng.choices(p.options, weights=p.weights, k=1)[0]
        else:                                       # pragma: no cover
            raise TypeError(f"type de paramètre inconnu : {p!r}")
    return genome


def viability_issues(genome: dict[str, Any]) -> list[str]:
    """Liste les raisons de rejeter un génome. Vide = viable.

    Retourne des raisons plutôt qu'un booléen : c'est ce qui permet de mesurer
    quelle règle rejette quoi, et donc de régler les bornes au lot L9 au lieu de
    deviner.
    """
    d = proportions.dimensions(genome)
    issues: list[str] = []

    # 1. Tête disproportionnée (CDC §7).
    ratio = d.head_width / d.body_width
    if ratio > MAX_HEAD_BODY_RATIO:
        issues.append(f"tete_trop_large({ratio:.2f})")

    # 2. Oreille latérale croisant la dalle faciale (CDC §7). Une oreille montée
    #    sur le côté déborde vers l'avant de son propre rayon ; si ce débord
    #    atteint la profondeur de la dalle **et** que son bord intérieur entre
    #    dans l'emprise horizontale de la dalle, les deux se croisent.
    if genome["ear.type"] in proportions.SIDE_EAR_TYPES:
        inner_edge = d.ear_x - d.ear_r * 0.35      # l'oreille est mince en X
        reaches_front = d.ear_r > d.plate_z
        if reaches_front and inner_edge < d.plate_half_w + EAR_PLATE_MARGIN:
            issues.append("oreille_croise_dalle")

    # 3. Antenne sur un monobloc (lot L17). Une tige plantée dans un bloc sans
    #    tête distincte ne se lit pas comme une oreille mais comme une erreur de
    #    montage. Rejet plutôt que réparation : forcer un autre type d'oreille
    #    changerait l'identité du robot, ce que `normalize` s'interdit.
    if genome.get("chassis") == "monobloc" and genome["ear.type"] == "antenna":
        issues.append("monobloc_avec_antenne")

    # 4. Les pupilles doivent tenir dans la dalle, écart et taille compris.
    half_span = float(genome["eye.spacing"]) / 2.0 + float(genome["eye.size"])
    if half_span > 0.94:
        issues.append(f"pupilles_hors_dalle({half_span:.2f})")

    return issues


def is_viable(genome: dict[str, Any]) -> bool:
    return not viability_issues(genome)


def normalize(genome: dict[str, Any]) -> dict[str, Any]:
    """Ajustements post-tirage qui ne changent pas l'identité du robot."""
    out = dict(genome)
    if out["neck.length"] < NECK_MIN_VISIBLE:
        out["neck.length"] = 0.0
    return out


def generate(seed: int) -> dict[str, Any]:
    """Génome viable et déterministe pour cette graine.

    En cas de rejet, on **retire** avec le même PRNG : la séquence continue, donc
    le résultat reste entièrement déterminé par la graine.
    """
    rng = random.Random(seed)
    for attempt in range(MAX_ATTEMPTS):
        candidate = normalize(draw(rng))
        issues = viability_issues(candidate)
        if not issues:
            candidate["schema_version"] = SCHEMA_VERSION
            candidate["seed"] = seed
            candidate["attempts"] = attempt + 1
            if attempt:
                log.debug("génome viable au tirage %d", attempt + 1)
            return candidate
        log.debug("tirage %d rejeté : %s", attempt + 1, ",".join(issues))

    raise GenomeGenerationError(
        f"aucun génome viable en {MAX_ATTEMPTS} tirages pour la graine {seed} — "
        "les bornes du schéma et les règles de viabilité sont incompatibles"
    )


def acceptance_rate(samples: int = 5000, seed: int = 0) -> tuple[float, dict[str, int]]:
    """Part de tirages viables, et décompte par raison de rejet.

    Outil de réglage, pas de production : sert à vérifier que les bornes du
    CDC §7 et ses règles de cohérence ne se contredisent pas. Un taux très bas
    signifierait que le nuage morphologique visé est en réalité vide.
    """
    rng = random.Random(seed)
    reasons: dict[str, int] = {}
    accepted = 0
    for _ in range(samples):
        issues = viability_issues(normalize(draw(rng)))
        if not issues:
            accepted += 1
        for issue in issues:
            label = issue.split("(")[0]
            reasons[label] = reasons.get(label, 0) + 1
    return accepted / samples, reasons
