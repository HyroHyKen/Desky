"""Suivi des trophées : ce qui transforme des faits en compteurs (lot L22).

Deux sources, et elles ne se ressemblent pas.

**Les faits du bus** — une partie finie, un bain terminé, une poussée — sont des
instants : le suivi s'y abonne et incrémente. C'est là que se voit l'intérêt
d'avoir nommé les événements par ce qui s'est produit plutôt que par l'effet
attendu : aucun point d'émission n'a eu à bouger pour que les trophées existent.

**Le temps** — l'âge, les journées, les séances passées à regarder quelque chose
— n'est annoncé par personne : il s'écoule. Le suivi le lit au tick de
comportement, qui bat déjà à 4 Hz, plutôt que d'ouvrir un minuteur de plus (§3).

Ni Qt ni disque ici : le module se teste en `dt` synthétique, et c'est ce qui
permet de vérifier qu'une séance de deux heures compte pour une et pas pour
mille.
"""

from __future__ import annotations

import logging

from ..feedback import bus as bus_par_defaut
from . import achievements as A

log = logging.getLogger("desky.trophees")

# Ce qui fait une séance. Cinq minutes continues : en dessous, une notification
# sonore et un onglet oublié suffiraient à la déclencher, et « 50 séances » ne
# voudrait plus rien dire.
SEANCE = 300.0

# Interruption au-delà de laquelle la séance suivante en est une autre. Deux
# minutes laissent passer une pause, une pub ou un aller-retour à la cuisine
# sans compter le film en double.
PAUSE = 120.0

# Satiété au-dessous de laquelle un repas est un sauvetage. Le relevé est pris
# au tick précédent, donc **avant** que le repas remonte la jauge : lu après, il
# serait toujours élevé et le trophée inatteignable.
FAIM_CRITIQUE = 15.0

# Force d'atterrissage à partir de laquelle la chute mérite son nom. Mesuré :
# la force atteint 1 à 1300 px/s, soit une chute de 325 px sous une gravité de
# 2600 px/s². À 0,9 il faut encore le lâcher de 263 px de haut, ce qu'aucun
# glisser ordinaire ne produit.
CHUTE_FRANCHE = 0.9

# Articles de nourriture. Le bain a son propre fait, plus riche — il sait s'il a
# été mené à son terme —, donc le kit est écarté ici pour ne pas compter deux
# fois le même geste.
REPAS = ("snack", "meal")


class Suivi:
    """Relie les faits du produit aux compteurs de la session."""

    def __init__(self, session, bus=None) -> None:
        self.session = session
        self.bus = bus if bus is not None else bus_par_defaut
        self._abonnements: list[tuple[str, object]] = []

        # Relevés du dernier tick. Ils servent aux trophées qui dépendent de ce
        # qui était vrai **avant** le geste : nourrir un robot à bout, le
        # caresser pendant sa sieste.
        self._faim = 100.0
        self._action = ""

        # Séance en cours.
        self._vu = 0.0
        self._pause = 0.0
        self._comptee = False

    # -- abonnement ---------------------------------------------------------

    def subscribe(self) -> None:
        for nom, fonction in (
            ("partie_finie", self._partie_finie),
            ("bain_fini", self._bain_fini),
            ("soin_accepte", self._soin_accepte),
            ("article_achete", self._article_achete),
            ("apparence_changee", self._apparence_changee),
            ("nom_donne", self._nom_donne),
            ("pousse", self._pousse),
            ("atterri", self._atterri),
        ):
            self.bus.subscribe(nom, fonction)
            self._abonnements.append((nom, fonction))

    def unsubscribe(self) -> None:
        for nom, fonction in self._abonnements:
            self.bus.unsubscribe(nom, fonction)
        self._abonnements.clear()

    # -- faits --------------------------------------------------------------

    def _partie_finie(self, jeu: str, score: int, record: bool) -> None:
        self.session.bump(A.PARTIES)
        if record:
            self.session.bump(A.RECORDS)
        self.verifier()

    def _bain_fini(self, complet: bool) -> None:
        self.session.bump(A.BAINS)
        if complet:
            self.session.bump(A.BAINS_COMPLETS)
            # La série vit dans les compteurs et non dans l'objet : fermer
            # l'application au milieu d'une série de trois remettrait sinon le
            # compte à zéro, ce qui serait une punition pour avoir éteint son
            # ordinateur.
            serie = self.session.bump("serie_courante")
            self.session.record_stat(A.SERIE_BAINS, serie)
        else:
            # Un bain abandonné casse la série. Il ne retire rien d'autre : le
            # maximum atteint reste acquis, et le trophée avec lui.
            self.session.set_stat("serie_courante", 0.0)
        self.verifier()

    def _soin_accepte(self, soin: str) -> None:
        if soin == "pet":
            self.session.bump(A.CARESSES)
            if self._action == "nap":
                self.session.bump(A.CARESSES_SIESTE)
        elif soin in REPAS:
            self.session.bump(A.REPAS)
            if self._faim < FAIM_CRITIQUE:
                self.session.bump(A.REPAS_URGENCE)
        else:
            return
        self.verifier()

    def _article_achete(self, emplacement: str, cle: str) -> None:
        self.session.bump(A.ACHATS)
        self.verifier()

    def _apparence_changee(self, param: str, cle: str) -> None:
        # Seules les couleurs comptent ici : porter un chapeau est déjà couvert
        # par l'achat, et compter les deux ferait monter un même geste deux fois.
        if param.startswith("palette."):
            self.session.bump(A.COULEURS)
            self.verifier()

    def _nom_donne(self, nom: str) -> None:
        self.session.record_stat(A.BAPTEME, 1.0)
        self.verifier()

    def _pousse(self) -> None:
        self.session.bump(A.POUSSEES)
        self.verifier()

    def _atterri(self, force: float, vitesse: float) -> None:
        if force >= CHUTE_FRANCHE:
            self.session.bump(A.CHUTES)
            self.verifier()

    # -- temps --------------------------------------------------------------

    def tick(self, dt: float, ctx=None, brain=None) -> None:
        """Avance ce qui ne s'annonce pas : les journées et les séances.

        Branché sur le tick de comportement, donc sur un `dt` déjà mesuré.
        """
        dt = max(0.0, float(dt))
        if brain is not None:
            self._faim = float(getattr(brain.needs, "hunger", self._faim))
            self._action = str(getattr(brain, "current", ""))

        etat = str(getattr(ctx, "state", ""))
        if etat == "watching":
            self._pause = 0.0
            self._vu += dt
            self.session.bump(A.HEURES_VIDEO, dt / 3600.0)
            if not self._comptee and self._vu >= SEANCE:
                self._comptee = True
                self.session.bump(A.VIDEOS)
                log.info("seance comptee : %d au total",
                         round(self.session.stats.get(A.VIDEOS, 0.0)))
        else:
            self._pause += dt
            if self._pause >= PAUSE and (self._vu or self._comptee):
                self._vu = 0.0
                self._comptee = False

        self.session.mark_day()
        self.verifier()

    # -- déblocage ----------------------------------------------------------

    def verifier(self) -> list[str]:
        """Débloque ce qui est dû, et l'annonce. Retourne les clés nouvelles.

        L'annonce est un fait comme les autres : le suivi ne sait pas qu'une
        fenêtre viendra le montrer en bas à droite, et il n'a pas à le savoir.
        """
        neufs = self.session.check_achievements()
        for cle in neufs:
            log.info("trophee debloque : %s", cle)
            self.bus.emit("succes_debloque", cle=cle)
        return neufs
