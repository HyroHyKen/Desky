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

# Gain par soin **livré**. Uniforme : un soin qui rapporterait plus qu'un autre
# pousserait à ne faire que celui-là, alors que les quatre besoins du §12 ont
# tous besoin d'être servis.
AWARD_PER_CARE = 1


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
