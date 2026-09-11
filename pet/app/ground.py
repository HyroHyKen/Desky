"""Où le pet se tient : géométrie de position, en fonctions pures (CDC §6).

Sortie de `window` au lot L10, et pour la même raison qui l'avait déjà isolée à
l'intérieur du fichier : ces quatre fonctions ne touchent ni au GPU, ni à un
`hwnd`, ni à Qt. Elles se testent seules, dans l'esprit de la cloison brain /
render du §5.

Le déménagement leur donne en plus un second lecteur : les objets de soin, qui
tombent sur le même sol que le pet, en ont besoin sans rien devoir savoir de la
fenêtre.
"""

from __future__ import annotations


def position_to_frac(
    x: float, y: float, pet: tuple[int, int], work: tuple[int, int, int, int]
) -> tuple[float, int]:
    """Position absolue -> (fraction horizontale, écart au sol).

    Stocker une fraction et un écart au sol, plutôt que des pixels absolus,
    garde la position juste après un changement de résolution.
    """
    pw, ph = pet
    wl, wt, ww, wh = work
    span = max(1, ww - pw)
    x_frac = max(0.0, min(1.0, (x - wl) / span))
    floor_gap = max(0, round((wt + wh - ph) - y))
    return x_frac, floor_gap


def frac_to_position(
    x_frac: float, floor_gap: int, pet: tuple[int, int], work: tuple[int, int, int, int]
) -> tuple[float, float]:
    """(fraction horizontale, écart au sol) -> position absolue."""
    pw, ph = pet
    wl, wt, ww, wh = work
    x = float(wl + max(0.0, min(1.0, x_frac)) * max(0, ww - pw))
    y = float(wt + wh - ph - max(0, floor_gap))
    return x, y


def choose_monitor(monitors: list, wanted_key: str):
    """Choisit le moniteur d'affichage : le mémorisé, sinon l'écran principal.

    C'est le cas du portable dont on débranche l'écran externe (CDC §6) : la clé
    mémorisée ne correspond plus à rien, et le pet doit réapparaître sur l'écran
    principal plutôt que dans des coordonnées qui ne sont plus affichées.

    Retourne `(moniteur, replié)`, où `replié` dit si le moniteur mémorisé
    manquait — l'appelant s'en sert pour journaliser, et pour décider s'il faut
    reprendre la position mémorisée ou repartir d'un placement par défaut.
    """
    if not monitors:
        raise ValueError("aucun moniteur actif")
    for m in monitors:
        if m.key == wanted_key:
            return m, False
    primary = next((m for m in monitors if m.primary), monitors[0])
    return primary, bool(wanted_key)


def floor_y(work: tuple[int, int, int, int], ph: int) -> float:
    """Ordonnée du pet posé sur le bord bas de la zone de travail."""
    _, wt, _, wh = work
    return float(wt + wh - ph)
