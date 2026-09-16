"""Consommables : ce qui s'achète, se garde, et se dépense une fois (lot L13).

Le renversement de ce lot tient en une phrase : **les soins ne sont plus
gratuits et illimités, ils sont des objets qu'on possède.** Nourrir et nettoyer
passaient par des boutons toujours disponibles, bornés par un simple délai ;
ils passent maintenant par la boutique et par un inventaire.

Ce que cela change, et pourquoi c'est mieux :

- **Les jetons servent enfin à quelque chose de vital.** Ils n'achetaient que
  des chapeaux ; ils achètent désormais de quoi s'occuper du robot, ce qui
  donne un sens au fait d'en gagner.
- **Les jeux deviennent la source.** On gagne des jetons en jouant, donc en
  passant du temps avec lui — et ce temps remonte aussi son amusement. La
  boucle se referme sur elle-même sans qu'aucune règle ne la force.
- **Un délai devient une quantité.** « Reviens dans une heure et demie » est une
  interdiction ; « il te reste deux gamelles » est une ressource. La seconde se
  gère, la première se subit, et le §12 interdit de punir l'utilisateur.

**Un consommable n'a pas de délai.** Le posséder *est* la limite : superposer
un compte à rebours à une quantité limiterait deux fois la même chose, et
donnerait un objet qu'on possède sans pouvoir s'en servir — exactement le genre
de règle qu'on ne comprend qu'en la subissant.

La caresse, elle, reste gratuite et garde son délai : c'est le seul geste qui ne
coûte rien, et il fallait que le robot reste caressable sans rien acheter.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Consumable:
    """Un article consommable du rayon.

    `need` et `gain` disent ce qu'il remonte et de combien. `kind` est la
    famille de sprite posée sur le bureau — les objets de soin du lot L7 sont
    réutilisés tels quels, avec le même trajet et le même rendez-vous.

    `instant` marque ce qui agit **sans passer par le bureau** : la pile n'est
    pas une chose qu'on pose et que le robot va chercher, c'est une chose qu'on
    lui met. La faire traverser l'écran serait une petite comédie sans intérêt,
    et surtout on l'achète précisément quand il est trop épuisé pour marcher.

    `sequence` marque au contraire ce qui, une fois rejoint, **ouvre un
    rituel** au lieu de remonter la jauge sur-le-champ. Les trois valeurs
    possibles sont donc les trois moments où un article peut agir : tout de
    suite (`instant`), au contact (le défaut), ou au bout d'un geste tenu
    (`sequence`). Elles s'excluent, et rien ne les mélange.
    """

    key: str
    need: str
    gain: float
    price: int
    kind: str = "food"
    instant: bool = False
    sequence: str = ""


# Le catalogue. Un rayon de nourriture à un ou deux jetons — le prix suit ce que
# l'article remonte —, la pile à cinq, qui est d'un autre ordre puisqu'elle ne
# remonte pas une jauge mais la remplit, et le kit de bain.
#
# **Le rayon nettoyage n'a plus qu'un article, et c'est le sujet du lot L15.**
# La lingette et le savon étaient le même geste à deux doses : on posait, le
# robot venait, la jauge montait d'autant. Deux articles pour une seule action
# n'offraient pas un choix, seulement une arithmétique. Le kit les remplace tous
# les deux et remet l'hygiène à fond, parce qu'il ne se mesure plus en points :
# on lave un robot jusqu'à ce qu'il soit propre, pas de 26 %.
#
# À un jeton par partie et cinq par record, une gamelle se gagne en une partie
# et la pile en cinq. C'est le rythme voulu : de quoi s'occuper de lui en jouant
# avec lui, sans que l'entretien devienne une corvée à financer.
CONSUMABLES: tuple[Consumable, ...] = (
    # --- nourriture -------------------------------------------------------
    Consumable("snack", "hunger", 22.0, 1, kind="feed"),
    Consumable("meal", "hunger", 52.0, 2, kind="feed"),
    # --- nettoyage --------------------------------------------------------
    Consumable("kit", "hygiene", 100.0, 2, kind="clean", sequence="wash"),
    # --- énergie ----------------------------------------------------------
    Consumable("battery", "energy", 100.0, 5, instant=True),
)

# Ce que deviennent les articles retirés du catalogue, au chargement d'une
# sauvegarde antérieure. Ils ont été **payés** : les faire disparaître serait
# une punition rétroactive, et le §12 l'interdit. Une lingette comme un savon
# valent un bain — l'utilisateur y gagne, ce qui est le bon sens d'une
# migration.
RETIRED: dict[str, str] = {"wipe": "kit", "soap": "kit"}

BY_KEY: dict[str, Consumable] = {c.key: c for c in CONSUMABLES}

# Rayons, dans l'ordre d'affichage. Dérivés du catalogue plutôt que recopiés :
# ajouter un article le place dans son rayon sans qu'on y touche.
AISLES: tuple[str, ...] = ("hunger", "hygiene", "energy")


def by_need(need: str) -> tuple[Consumable, ...]:
    """Articles d'un rayon, du moins cher au plus cher."""
    return tuple(sorted((c for c in CONSUMABLES if c.need == need),
                        key=lambda c: (c.price, c.key)))


def get(key: str) -> Consumable | None:
    return BY_KEY.get(key)


def price(key: str) -> int:
    article = BY_KEY.get(key)
    return article.price if article is not None else 0
