"""Bus de rétroaction : ce qui vient de se produire dans le monde (lot L9).

Son, particules et interface veulent tous réagir aux **mêmes instants** : le
soin a été accepté, l'achat a été refusé, le panneau s'est ouvert. Sans point de
rendez-vous, chacun va se brancher séparément dans `window.py` et `panel.py`, et
le nombre d'accroches est multiplié par le nombre de lots.

**Un événement décrit le monde, jamais l'effet attendu.** `soin_accepte`, pas
`jouer_animation_soin`. La règle n'est pas cosmétique : un nom d'effet lie
l'émetteur à un seul consommateur, et le jour où le son arrive il faut
réinstrumenter tous les points d'émission. Un nom de fait en accueille trois
sans être touché. `test_feedback` fait échouer un nom impératif.

**Pourquoi pas un `Signal` Qt.** Le `brain` est testable sans GPU et sans
`QApplication` (§12), et cela doit rester vrai des faits qu'il produira. Un bus
en Python pur se teste partout, survit aux widgets qui vont et viennent, et ne
demande à personne d'hériter de `QObject`. Les `Signal` existants du panneau ne
disparaissent pas pour autant : ils alimentent le bus, ils ne sont pas doublés.

**Un abonné qui lève n'interrompt pas les autres.** Une étincelle ratée ne doit
pas empêcher le son de partir, ni surtout annuler le soin qui l'a provoquée :
l'émetteur a déjà fait son travail quand il émet.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("desky.feedback")

# Catalogue des faits. Un nom absent d'ici est refusé à l'émission : une faute
# de frappe rendrait un abonnement silencieusement inerte, et ce silence-là se
# diagnostique très mal — on ne voit pas un son qui ne part pas.
#
# Le catalogue grandit avec les lots, et chaque entrée garde la même forme : ce
# qui s'est produit, au passé, jamais ce qu'il faudrait en faire.
EVENTS: frozenset[str] = frozenset({
    # Mouvement du robot (lot L10)
    "atterri",                  # {force, vitesse} — force dans [0, 1]
    "pousse",                   # le pet a été cliqué
    # Panneau de soin
    "panneau_ouvert",
    "panneau_ferme",
    "page_changee",             # {page}
    "bouton_active",            # {action}
    "bouton_refuse",            # {action} — cliqué alors qu'il est grisé
    # Soin et économie
    "soin_accepte",             # {soin}
    "article_achete",           # {emplacement, cle}
    "achat_refuse",             # {emplacement, cle, raison}
    # Identité et réglages
    "nom_donne",                # {nom}
    "apparence_changee",        # {param, cle}
    "reglage_bascule",          # {reglage}
})

# Préfixes qui trahissent un nom d'effet plutôt qu'un nom de fait. La liste est
# courte et volontairement grossière : elle attrape l'erreur au moment où on
# l'écrit, et le test de nommage dit le reste.
_IMPERATIFS = ("jouer_", "afficher_", "animer_", "declencher_", "montrer_",
               "emettre_", "lancer_", "play_", "show_")


class Feedback:
    """Émetteur d'événements, sans dépendance et sans état partagé.

    Deux formes d'abonnement : à un fait précis, ou à tous. La seconde sert au
    journal de diagnostic et, plus tard, au mélangeur audio qui voudra voir
    passer l'ensemble pour appliquer sa propre table.
    """

    __slots__ = ("_abonnes", "_tous")

    def __init__(self) -> None:
        self._abonnes: dict[str, list[Callable[..., None]]] = {}
        self._tous: list[Callable[[str, dict[str, Any]], None]] = []

    def subscribe(self, nom: str, fonction: Callable[..., None]) -> None:
        """Abonne `fonction(**charge)` au fait `nom`."""
        if nom not in EVENTS:
            raise KeyError("fait inconnu : %r" % nom)
        self._abonnes.setdefault(nom, []).append(fonction)

    def subscribe_all(self, fonction: Callable[[str, dict[str, Any]], None]) -> None:
        """Abonne `fonction(nom, charge)` à tous les faits."""
        self._tous.append(fonction)

    def unsubscribe(self, nom: str, fonction: Callable[..., None]) -> None:
        """Retire un abonnement. Silencieux s'il n'existe pas.

        Un panneau détruit puis recréé ne doit pas laisser derrière lui un
        abonné qui peint dans un widget mort.
        """
        if nom in self._abonnes:
            try:
                self._abonnes[nom].remove(fonction)
            except ValueError:
                pass

    def emit(self, nom: str, /, **charge: Any) -> None:
        """Annonce un fait. Ne lève jamais pour le compte d'un abonné.

        Le `/` n'est pas décoratif : sans lui, `emit("nom_donne", nom="Bip")`
        lève `got multiple values for argument 'nom'`, parce que la charge
        écrase le paramètre. Un bus dont certaines clés sont interdites au
        hasard du nommage interne serait un piège permanent — en positionnel
        seul, aucune clé n'est réservée.
        """
        if nom not in EVENTS:
            raise KeyError("fait inconnu : %r — ajoutez-le à EVENTS" % nom)
        for fonction in tuple(self._abonnes.get(nom, ())):
            try:
                fonction(**charge)
            except Exception:                              # noqa: BLE001
                log.exception("abonné de %s a levé", nom)
        for fonction in tuple(self._tous):
            try:
                fonction(nom, dict(charge))
            except Exception:                              # noqa: BLE001
                log.exception("abonné global a levé sur %s", nom)

    def clear(self) -> None:
        """Oublie tous les abonnements. Pour les tests."""
        self._abonnes.clear()
        self._tous.clear()


# Instance de service, à la façon du `log` de chaque module : le panneau et la
# fenêtre s'y adressent sans se la passer de constructeur en constructeur. Les
# tests construisent leur propre `Feedback()` quand ils veulent l'isolement.
bus = Feedback()
