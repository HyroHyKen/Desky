"""Critères d'acceptation de l'horloge du lot L1.

Vérifie ce que le CDC §3 exige de la cadence — 30 fps en interaction, 10 en
idle, 0 quand masqué — sur les ticks **réellement délivrés**, et non sur
l'intervalle demandé : le lot L0 a montré que la granularité du timer Windows
peut transformer une demande de 33 ms en 21 fps.
"""

from __future__ import annotations

import unittest

from PySide6.QtCore import QElapsedTimer, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pet.app.clock import Regime, RenderClock

from .qt_app import ensure_app

TOLERANCE = 0.15          # 15 % d'écart admis sur la cadence délivrée


class ClockTest(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_app()

    def setUp(self) -> None:
        self.clock = RenderClock()
        self.ticks = 0
        self.clock.tick.connect(self._count)
        self.regimes: list[Regime] = []
        self.clock.regime_changed.connect(self.regimes.append)

    def tearDown(self) -> None:
        self.clock.stop()

    def _count(self) -> None:
        self.ticks += 1

    def _spin(self, ms: int, poke_every: int | None = None) -> float:
        """Fait tourner la boucle `ms` millisecondes, retourne les fps mesurés."""
        self.ticks = 0
        loop = QEventLoop()
        elapsed = QElapsedTimer()

        poker = None
        if poke_every is not None:
            poker = QTimer()
            poker.timeout.connect(self.clock.poke)
            poker.start(poke_every)

        QTimer.singleShot(ms, loop.quit)
        elapsed.start()
        loop.exec()
        if poker is not None:
            poker.stop()
        return self.ticks / (elapsed.elapsed() / 1000.0)

    # -- cadences délivrées --------------------------------------------------

    def test_idle_delivre_10_fps(self) -> None:
        self.clock.start()
        fps = self._spin(2500)
        self.assertEqual(self.clock.regime, Regime.IDLE)
        self.assertAlmostEqual(fps, 10.0, delta=10.0 * TOLERANCE,
                               msg=f"idle devrait tourner à 10 fps, mesuré {fps:.1f}")

    def test_interactif_delivre_30_fps(self) -> None:
        """C'est le test qui aurait attrapé le défaut de timer du lot L0."""
        self.clock.start()
        fps = self._spin(2500, poke_every=100)
        self.assertEqual(self.clock.regime, Regime.INTERACTIVE)
        self.assertAlmostEqual(fps, 30.0, delta=30.0 * TOLERANCE,
                               msg=f"interactif devrait tourner à 30 fps, mesuré {fps:.1f}")

    def test_suspendu_ne_delivre_aucun_tick(self) -> None:
        self.clock.start()
        self.clock.set_suspended(True)
        fps = self._spin(1200)
        self.assertEqual(self.clock.regime, Regime.SUSPENDED)
        self.assertEqual(fps, 0.0, "aucun tick ne doit être délivré à l'état masqué")

    def test_reprise_apres_suspension(self) -> None:
        self.clock.start()
        self.clock.set_suspended(True)
        self._spin(600)
        self.clock.set_suspended(False)
        fps = self._spin(1500)
        self.assertGreater(fps, 5.0, "le rendu doit reprendre après la suspension")

    # -- hystérésis ----------------------------------------------------------

    def test_poke_fait_passer_en_interactif_immediatement(self) -> None:
        self.clock.start()
        self._spin(400)
        self.assertEqual(self.clock.regime, Regime.IDLE)
        self.clock.poke()
        self.assertEqual(self.clock.regime, Regime.INTERACTIVE,
                         "une sollicitation doit être prise en compte sans attendre "
                         "le superviseur")

    def test_hysteresis_maintient_l_interactif(self) -> None:
        """Pas de battement de cadence à la fin d'un mouvement (CDC §12)."""
        self.clock.start()
        self.clock.poke()
        self._spin(int(RenderClock.LINGER_MS * 0.6))
        self.assertEqual(self.clock.regime, Regime.INTERACTIVE,
                         "l'interactif doit tenir pendant la fenêtre d'hystérésis")

    def test_retombe_en_idle_apres_l_hysteresis(self) -> None:
        self.clock.start()
        self.clock.poke()
        self._spin(RenderClock.LINGER_MS + 600)
        self.assertEqual(self.clock.regime, Regime.IDLE)

    def test_la_suspension_gagne_sur_une_sollicitation(self) -> None:
        """Une appli plein écran doit masquer le pet même si le curseur bouge."""
        self.clock.start()
        self.clock.set_suspended(True)
        self.clock.poke()
        self.assertEqual(self.clock.regime, Regime.SUSPENDED)

    def test_pas_de_battement_de_regime(self) -> None:
        """Sollicitations régulières : un seul changement de régime, pas dix."""
        self.clock.start()
        self.regimes.clear()
        self._spin(2000, poke_every=80)
        self.assertLessEqual(len(self.regimes), 1,
                             f"régimes traversés : {[r.value for r in self.regimes]}")


if __name__ == "__main__":
    unittest.main()
