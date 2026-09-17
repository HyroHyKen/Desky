"""Économie de tokens (CDC §14, lot L7).

« Les tokens sont versés pour la présence effective et le soin, avec un plafond
quotidien pour que l'idle infini ne soit pas la stratégie optimale. »

**Un token par soin délivré**, et le plafond fait tout le reste du travail. Les
délais de soin à eux seuls ne suffisent pas : caresser revient toutes les deux
minutes, soit trente tokens par heure, et le chapeau le plus cher tomberait en
deux heures de clics. Le plafond quotidien ramène le rythme à ce qu'il doit
être — deux jours pour l'objet le plus cher, une journée pour le moins cher.

**Versé à la livraison, pas au clic.** Depuis que les soins passent par un objet
posé sur le bureau, créditer au moment du bouton laisserait faire apparaître dix
gamelles sans jamais en livrer une seule.

Sur la triche, le §14 est explicite : « ne pas investir dans du chiffrement ou
de la signature ». Ce module détecte donc le recul d'horloge, refuse tout crédit
rétroactif, et s'arrête là — c'est ce que le cahier des charges demande, et pas
un octet de plus.

Module pur : ni GPU, ni Qt, ni disque.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# Plafond quotidien, décidé avec l'utilisateur. C'est le seul chiffre qui règle
# le rythme de la boutique : à 25, l'article le plus cher — 50 tokens — se
# mérite en deux jours, et le moins cher dans la journée.
DAILY_CAP = 25

# Gains, désormais **par partie jouée** et non plus par soin livré (lot L13).
#
# Le renversement est volontaire : les soins sont devenus des objets qu'on
# achète, donc ils ne peuvent plus être ce qui finance leur propre achat. Les
# jeux sont la source, ce qui veut dire que la monnaie s'obtient en passant du
# temps avec le robot — et ce temps remonte aussi son amusement.
#
# Cinq pour un record, parce qu'un record est rare et qu'il doit valoir le coup
# de viser haut plutôt que d'enchaîner les parties bâclées.
AWARD_PER_GAME = 1
AWARD_PER_RECORD = 5

# Conservé sous son ancien nom le temps que les anciens appels disparaissent.
AWARD_PER_CARE = AWARD_PER_GAME


def day_key(when: float | None = None) -> str:
    """Jour local, en clé comparable. C'est la granularité du plafond."""
    return time.strftime("%Y-%m-%d", time.localtime(
        time.time() if when is None else when))


@dataclass
class Economy:
    """Solde, et ce qui a déjà été gagné aujourd'hui."""

    tokens: int = 0
    day: str = ""
    today: int = 0

    # --- plafond ----------------------------------------------------------

    def _roll(self, when: float | None = None) -> None:
        """Ouvre une nouvelle journée, mais **seulement vers l'avant**.

        C'est toute la détection de recul d'horloge, et elle tient en une
        comparaison. Reculer la date ne rouvre pas le quota : la clé du jour
        doit être **strictement postérieure** à celle qui est enregistrée.
        Avancer l'horloge ouvre bien une journée — comme pour n'importe quel
        logiciel hors ligne — mais la reculer ensuite ne la rouvrira pas, donc
        le va-et-vient ne rapporte rien.

        Limite assumée : avancer l'horloge d'un jour à chaque fois reste
        payant. Le §14 demande explicitement de ne pas aller plus loin, l'appli
        étant gratuite, hors ligne, sans classement et à récompenses purement
        cosmétiques.
        """
        aujourdhui = day_key(when)
        if not self.day:
            self.day = aujourdhui
            return
        if aujourdhui > self.day:
            self.day = aujourdhui
            self.today = 0

    @property
    def remaining(self) -> int:
        """Ce qui peut encore être gagné aujourd'hui."""
        return max(0, DAILY_CAP - self.today)

    def award(self, amount: int = AWARD_PER_CARE,
              when: float | None = None) -> int:
        """Verse jusqu'à `amount` tokens. Retourne ce qui a réellement été versé.

        Le retour est le montant **effectif** et non le nominal : c'est lui que
        l'interface doit montrer, et promettre un token pour n'en donner aucun
        une fois le plafond atteint serait exactement le genre de petit mensonge
        qui fait douter du reste.
        """
        self._roll(when)
        gagne = max(0, min(int(amount), self.remaining))
        self.tokens += gagne
        self.today += gagne
        return gagne

    def grant(self, amount: int) -> int:
        """Verse **hors plafond**. Réservé aux récompenses de trophée (L22).

        Le plafond existe pour que l'oisiveté ne soit pas la stratégie
        optimale : il borne ce qu'une journée de présence peut rapporter. Un
        trophée n'est pas de la présence, c'est une chose faite une fois dans la
        vie du robot, et la faire passer sous le plafond aurait un effet absurde
        — débloquer « 1 an » un jour où l'on a déjà joué perdrait 75 des 100
        jetons promis, sans que rien ne l'explique à l'utilisateur.

        Ne touche donc ni `day` ni `today` : ce versement n'entame pas le quota
        du jour et ne le rouvre pas non plus.
        """
        gagne = max(0, int(amount))
        self.tokens += gagne
        return gagne

    # --- dépense ----------------------------------------------------------

    def can_afford(self, price: int) -> bool:
        return self.tokens >= max(0, int(price))

    def spend(self, price: int) -> bool:
        """Débite si le solde suffit. Ne descend jamais sous zéro."""
        prix = max(0, int(price))
        if self.tokens < prix:
            return False
        self.tokens -= prix
        return True

    # --- persistance ------------------------------------------------------

    def as_dict(self) -> dict:
        return {"tokens": self.tokens, "tokens_day": self.day,
                "tokens_today": self.today}

    @classmethod
    def from_dict(cls, raw: dict) -> "Economy":
        """Reconstruit en **bornant**, comme tout le reste du §14."""
        out = cls()
        try:
            out.tokens = max(0, int(raw.get("tokens", 0)))
        except (TypeError, ValueError):
            out.tokens = 0
        jour = raw.get("tokens_day")
        out.day = jour if isinstance(jour, str) else ""
        try:
            out.today = max(0, min(DAILY_CAP, int(raw.get("tokens_today", 0))))
        except (TypeError, ValueError):
            out.today = 0
        return out
