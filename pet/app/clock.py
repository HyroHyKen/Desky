"""Boucle de rendu et framerate adaptatif (CDC §3, §5).

Trois régimes, dictés par la table des contraintes : **30 fps en interaction,
10 fps en idle, 0 quand masqué**. Le motif est l'autonomie sur portable, pas la
charge CPU en soi — ce qui a deux conséquences sur la conception :

- Le passage à 0 fps est un vrai arrêt du timer, pas une boucle qui tourne à
  vide : on veut que le process cesse d'être réveillé.
- Le régime idle utilise un `CoarseTimer`, qui laisse Windows regrouper les
  réveils. Mesure du lot L0 : à 100 ms demandés, un CoarseTimer délivre 10,0 fps,
  soit exactement la cible, donc la précision n'apporterait rien ici.

Le régime interactif, lui, exige un `PreciseTimer` : le tic natif de Windows
étant de 15,625 ms, un CoarseTimer n'atteint que des cadences de 64/n fps et
arrondit une demande de 33 ms à 3 tics, soit 21 fps au lieu de 30.

**Hystérésis.** Redescendre en idle dès la fin d'un mouvement de souris
produirait un battement de cadence perceptible. L'horloge reste donc en régime
interactif pendant `LINGER_MS` après la dernière sollicitation. C'est le même
principe que le bonus d'action en cours du CDC §12, appliqué ici à la cadence.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

from PySide6.QtCore import QObject, Qt, QTimer, Signal

log = logging.getLogger("desky.clock")


class Regime(Enum):
    INTERACTIVE = "interactive"
    IDLE = "idle"
    SUSPENDED = "suspended"


class RenderClock(QObject):
    """Émet `tick` à la cadence du régime courant."""

    tick = Signal()
    regime_changed = Signal(object)          # Regime

    FPS = {Regime.INTERACTIVE: 30, Regime.IDLE: 10, Regime.SUSPENDED: 0}
    LINGER_MS = 1200

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._regime = Regime.IDLE
        self._last_poke = 0.0
        self._suspended = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)

        # Réévalue le régime 4 fois par seconde, comme la cadence de polling des
        # capteurs du CDC §11. Ce timer est le seul à tourner en permanence, y
        # compris à 0 fps : c'est lui qui permettra de sortir de l'état masqué.
        self._supervisor = QTimer(self)
        self._supervisor.setTimerType(Qt.TimerType.CoarseTimer)
        self._supervisor.timeout.connect(self._reevaluate)

    # -- pilotage ------------------------------------------------------------

    def start(self) -> None:
        self._supervisor.start(250)
        self._apply(Regime.IDLE, force=True)

    def stop(self) -> None:
        self._timer.stop()
        self._supervisor.stop()

    def poke(self) -> None:
        """Signale une sollicitation : curseur proche, clic, déplacement.

        Au lot L1 les sollicitations viennent de la fenêtre. Au lot L5, les
        capteurs système alimenteront le même point d'entrée.
        """
        self._last_poke = time.monotonic()
        if self._regime is Regime.IDLE:
            self._reevaluate()               # réactivité immédiate, sans attendre 250 ms

    def set_suspended(self, suspended: bool) -> None:
        """Masqué : plein écran exclusif au premier plan, ou masquage manuel."""
        if suspended != self._suspended:
            self._suspended = suspended
            self._reevaluate()

    # -- état ----------------------------------------------------------------

    @property
    def regime(self) -> Regime:
        return self._regime

    @property
    def fps(self) -> int:
        return self.FPS[self._regime]

    # -- interne -------------------------------------------------------------

    def _reevaluate(self) -> None:
        if self._suspended:
            self._apply(Regime.SUSPENDED)
        elif (time.monotonic() - self._last_poke) * 1000 < self.LINGER_MS:
            self._apply(Regime.INTERACTIVE)
        else:
            self._apply(Regime.IDLE)

    def _apply(self, regime: Regime, force: bool = False) -> None:
        if regime is self._regime and not force:
            return
        self._regime = regime

        if regime is Regime.SUSPENDED:
            self._timer.stop()
        else:
            if regime is Regime.INTERACTIVE:
                self._timer.setTimerType(Qt.TimerType.PreciseTimer)
                interval = 1000 // self.FPS[regime]
            else:
                self._timer.setTimerType(Qt.TimerType.CoarseTimer)
                # 100 ms plutôt que 1000//10 : le CoarseTimer arrondit de toute
                # façon au tic, et 100 est ce qui a été mesuré à 10,0 fps.
                interval = 100
            self._timer.start(interval)

        log.info("régime %s (%d fps)", regime.value, self.FPS[regime])
        self.regime_changed.emit(regime)
