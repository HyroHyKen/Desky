"""Migration de schéma sans altérer les pets existants (CDC §7).

L'exigence est explicite : « si le schéma évolue, le robot d'un utilisateur
existant ne doit pas être régénéré différemment ». C'est la raison pour laquelle
le génome est stocké en valeurs explicites et non en graine seule — une graine
seule serait relue par le nouveau générateur, qui consommerait le PRNG dans un
ordre différent et donnerait un autre robot.

D'où la règle qui gouverne ce module : une migration est **additive**. Elle
complète les paramètres absents et borne les valeurs aberrantes ; elle ne
retouche jamais une valeur déjà présente et valide. Un pet gardé depuis la
première version doit rester reconnaissable indéfiniment.

Deux cas particuliers assumés :

- **Retour en arrière.** Un génome écrit par une version plus récente est
  accepté : ses paramètres connus sont bornés, et ceux que cette version ne
  connaît pas encore sont **conservés tels quels** plutôt que jetés. L'utilisateur
  qui repasse à la version suivante retrouve son robot intact.
- **Paramètre retiré.** Sa valeur reste dans le fichier, inerte. Le coût est
  quelques octets ; le bénéfice est qu'un aller-retour entre versions ne perd
  rien.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .schema import PARAMS_BY_KEY, SCHEMA_VERSION, clamp_genome

log = logging.getLogger("desky.genome")

# Migrations explicites, indexées par la version de départ : `MIGRATIONS[n]`
# transforme un document de version n en document de version n+1. Le
# remplissage des paramètres nouvellement ajoutés n'a **pas** besoin d'entrée
# ici : il est générique, cf. `migrate`. On n'inscrit une fonction que pour un
# changement de sens d'un paramètre existant — renommage, changement d'unité,
# recalcul — soit précisément les cas où l'automatisme serait faux.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def register(from_version: int) -> Callable[
    [Callable[[dict[str, Any]], dict[str, Any]]],
    Callable[[dict[str, Any]], dict[str, Any]],
]:
    def decorator(fn: Callable[[dict[str, Any]], dict[str, Any]]):
        if from_version in MIGRATIONS:
            raise ValueError(f"migration déjà enregistrée depuis la version {from_version}")
        MIGRATIONS[from_version] = fn
        return fn
    return decorator


def added_params(raw: dict[str, Any]) -> list[str]:
    """Paramètres du schéma courant absents du document."""
    return [key for key in PARAMS_BY_KEY if key not in raw]


def unknown_params(raw: dict[str, Any]) -> list[str]:
    """Clés du document que le schéma courant ne connaît pas.

    Non vide signifie que le fichier vient d'une version plus récente.
    """
    reserved = {"schema_version", "seed", "attempts"}
    return [k for k in raw if k not in PARAMS_BY_KEY and k not in reserved]


def migrate(raw: dict[str, Any], from_version: int,
            to_version: int = SCHEMA_VERSION) -> dict[str, Any]:
    """Amène un génome au schéma demandé, sans dérive morphologique.

    L'ordre compte : les migrations explicites d'abord, chaînées version par
    version, puis le remplissage générique et le bornage. Une migration qui
    recalcule un paramètre doit donc pouvoir compter sur la présence des
    paramètres de **sa** version, pas de ceux qui n'existaient pas encore.
    """
    data = dict(raw)
    version = int(from_version)

    while version < to_version:
        fn = MIGRATIONS.get(version)
        if fn is not None:
            log.info("migration explicite du génome : %d -> %d", version, version + 1)
            data = fn(data)
        version += 1

    if from_version > to_version:
        kept = unknown_params(data)
        log.info("génome écrit par une version plus récente (%d > %d) ; "
                 "%d paramètre(s) inconnu(s) conservé(s)",
                 from_version, to_version, len(kept))

    new = added_params(data)
    if new:
        log.info("%d paramètre(s) complété(s) par défaut : %s", len(new), ", ".join(new))

    data = clamp_genome(data)
    data["schema_version"] = to_version
    return data
