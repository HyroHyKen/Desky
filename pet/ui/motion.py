"""Animation de l'interface : tweens, ressorts indexés, tic qui s'arrête (L9).

Le §10 exige « aucune interpolation linéaire sur un mouvement visible ». Un
panneau qui apparaît d'un coup ne l'enfreint pas — il fait pire, il ne bouge
pas du tout. Ce module apporte à `pet/ui` le vocabulaire que `pet/anim/easing`
donne déjà au rig.

Deux mécanismes, parce que l'interface a deux besoins qui ne se ressemblent
pas :

- `Tween` — une progression **une fois**, de A vers B, sur une durée connue et
  à travers une courbe choisie. C'est l'ouverture du panneau : on sait où on
  va, on sait en combien de temps, et on veut précisément `ease_out_back` à
  l'aller et `ease_in` au retour.
- `SpringBank` — des ressorts **qui poursuivent** une cible qui change sous
  eux. C'est la réaction d'un bouton : la souris entre, sort, ré-entre avant la
  fin du mouvement, et un tween devrait être relancé à chaque fois depuis une
  valeur intermédiaire. Un ressort absorbe cela sans discontinuité, puisqu'il
  transporte sa vitesse.

**Le tic doit s'arrêter.** C'est la contrainte §3 (< 4 % d'un cœur) traduite
dans cette couche : un panneau ouvert et immobile ne doit rien coûter de plus
qu'avant ce lot. D'où `moving` sur les deux mécanismes, et un `Ticker` qui
éteint son timer dès que plus rien n'est en vol.

**Tout avance par un `dt` fourni.** Jamais `time.perf_counter()` à l'intérieur :
`tests/test_ui.py` pilote déjà la scène d'arrivée avec un `dt` synthétique,
précisément parce qu'une boucle serrée sur l'horloge réelle mesure des durées
fausses. L'interface doit être testable de la même façon.
"""

from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QObject, QTimer, Qt

from ..anim.easing import Spring, ease_in_out

# 30 fps, la cadence « en interaction » du §3. Le panneau n'est ouvert que
# lorsque l'utilisateur s'en occupe, donc ce régime est le bon, et
# `PreciseTimer` pour la même raison que dans `app/clock` : à 33 ms demandés,
# un CoarseTimer arrondit à 3 tics de 15,625 ms et ne délivre que 21 fps.
TICK_MS = 1000 // 30


class Tween:
    """Progression une-fois de la valeur courante vers une cible.

    `to()` repart **de la valeur atteinte**, pas de zéro : refermer un panneau
    à moitié ouvert doit partir d'où il en est, sinon il saute avant de
    disparaître.
    """

    __slots__ = ("value", "_depart", "_cible", "_t", "_duree", "_courbe")

    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)
        self._depart = float(value)
        self._cible = float(value)
        self._t = 1.0
        self._duree = 1.0
        self._courbe: Callable[[float], float] = ease_in_out

    def to(self, cible: float, duree: float,
           courbe: Callable[[float], float] = ease_in_out) -> None:
        self._depart = self.value
        self._cible = float(cible)
        self._t = 0.0
        self._duree = max(1e-6, float(duree))
        self._courbe = courbe

    def jump(self, valeur: float) -> None:
        """Pose la valeur sans mouvement. Pour un état initial, pas pour une
        transition : sauter est exactement ce que ce lot supprime."""
        self.value = self._depart = self._cible = float(valeur)
        self._t = 1.0

    def step(self, dt: float) -> bool:
        """Avance. Rend `True` si la valeur a changé."""
        if self._t >= 1.0:
            return False
        self._t = min(1.0, self._t + dt / self._duree)
        k = self._courbe(self._t)
        self.value = self._depart + (self._cible - self._depart) * k
        return True

    @property
    def moving(self) -> bool:
        return self._t < 1.0

    @property
    def target(self) -> float:
        return self._cible


class SpringBank:
    """Ressorts d'une même famille, indexés par une identité stable.

    L'identité est celle que porte déjà l'objet animé — pour un bouton du
    panneau, sa chaîne `action`, qui sert déjà au test de clic. Réutiliser
    celle-là plutôt qu'un indice de liste est ce qui rend la purge correcte :
    entre deux mises en page, les boutons changent de place, et l'indice 3
    d'une page n'est pas l'indice 3 de la suivante.

    `keep()` oublie les identités disparues. Sans elle, changer de page vingt
    fois laisse vingt jeux de ressorts orphelins qu'on continuerait d'avancer,
    et le tic ne s'arrêterait plus jamais.
    """

    __slots__ = ("_ressorts", "_cibles", "_omega", "_zeta", "_repos")

    def __init__(self, omega: float = 22.0, zeta: float = 0.7,
                 repos: float = 0.0) -> None:
        self._ressorts: dict[str, Spring] = {}
        self._cibles: dict[str, float] = {}
        self._omega = float(omega)
        self._zeta = float(zeta)
        self._repos = float(repos)

    def target(self, cle: str, valeur: float) -> None:
        if cle not in self._ressorts:
            self._ressorts[cle] = Spring(self._repos, omega=self._omega,
                                         zeta=self._zeta)
        self._cibles[cle] = float(valeur)

    def value(self, cle: str) -> float:
        ressort = self._ressorts.get(cle)
        return self._repos if ressort is None else float(ressort.value)

    def keep(self, cles: Iterable[str]) -> None:
        """Ne garde que ces identités."""
        vivantes = set(cles)
        for morte in [c for c in self._ressorts if c not in vivantes]:
            del self._ressorts[morte]
            self._cibles.pop(morte, None)

    def step(self, dt: float) -> bool:
        bouge = False
        for cle, ressort in self._ressorts.items():
            cible = self._cibles.get(cle, self._repos)
            if ressort.settled(cible):
                # Coller à la cible plutôt que de traîner à 1e-4 : sans cela le
                # prédicat oscille autour de son seuil et le tic se rallume.
                ressort.reset(cible)
                continue
            ressort.step(cible, dt)
            bouge = True
        return bouge

    @property
    def moving(self) -> bool:
        return any(not r.settled(self._cibles.get(c, self._repos))
                   for c, r in self._ressorts.items())

    def clear(self) -> None:
        self._ressorts.clear()
        self._cibles.clear()


class Ticker(QObject):
    """Timer d'animation qui s'éteint dès que plus rien ne bouge.

    Il ne connaît ni le panneau ni ce qu'il anime : on lui donne une fonction
    `step(dt) -> bool`, qui rend `True` tant qu'il reste du mouvement, et une
    fonction à appeler pour repeindre. C'est tout ce qu'il faut pour tenir la
    contrainte §3, et c'est assez peu pour être réutilisé par la bulle et par
    les lots suivants.

    Le `dt` est mesuré sur l'horloge, mais `step` reste appelable directement
    avec un `dt` synthétique : c'est ce que font les tests, sans timer du tout.
    """

    def __init__(self, step, repaint, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._step = step
        self._repaint = repaint
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self._dt = TICK_MS / 1000.0

    def wake(self) -> None:
        """À appeler quand une cible vient de changer."""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def _on_tick(self) -> None:
        # `dt` nominal et non mesuré : les ressorts sont exacts à tout pas, et
        # une mesure réelle ferait varier le mouvement avec la charge de la
        # machine — le genre de différence qu'on ne voit qu'en vidéo, chez
        # quelqu'un d'autre.
        if not self._step(self._dt):
            self._timer.stop()
        self._repaint()
