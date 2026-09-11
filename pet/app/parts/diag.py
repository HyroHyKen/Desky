"""Journal de diagnostic, activé par `--diag` (lot L5b).

Extrait de `window` au lot L10. Il n'observe que : aucune de ces lignes ne
modifie l'état du pet, et c'est ce qui rend leur sortie de `window` sans risque.
"""

from __future__ import annotations

from .. import win32


class DiagnosticsMixin:
    """Une ligne toutes les deux secondes, et rien d'autre."""

    # -- diagnostics ---------------------------------------------------------

    def _on_diag(self) -> None:
        fps = self._frames / 2.0
        ms_render = 1000.0 * self._t_render / max(1, self._frames)
        ms_paint = 1000.0 * self._t_paint / max(1, self._paints)
        paints = self._paints
        self._frames = self._paints = 0
        self._t_render = self._t_paint = 0.0
        fg = win32.get_foreground_window()
        mon = self.current_monitor()
        print(
            f"[diag] {self.clock.regime.value:11s} {fps:4.1f} fps | "
            f"CPU {self._cpu.sample():4.1f} % | rendu {ms_render:5.2f} ms | "
            f"peint {paints // 2:2d}/s a {ms_paint:5.2f} ms | "
            f"hit {1000 // max(1, self._hit_timer.interval()):2d} Hz | "
            f"ct {int(win32.is_click_through(self.hwnd))} | "
            f"pos ({round(self._x)},{round(self._y)}) ecran {mon.rect[0]},{mon.rect[1]} | "
            f"focus vole {self._focus_stolen} | fg inchange {fg == self._foreground_at_start}",
            flush=True,
        )
        # Comportement : besoins, action élue, et les trois meilleurs candidats
        # avec leur score. Sans les scores, un choix surprenant est
        # inexplicable — c'est la ligne qui sert à juger le réglage en vrai.
        besoins = "  ".join(f"{k[:3]}={v:3.0f}"
                            for k, v in self.brain.needs.as_dict().items())
        tete = sorted(self.brain.candidates, key=lambda c: -c.total)[:3]
        print(f"[diag] brain {self.brain.current:14s} depuis "
              f"{self.brain.elapsed:5.1f}s | {besoins} "
              f"| humeur {self.brain.expression:10s} "
              f"| {self.brain.changes:3d} changements "
              f"| regard {self._look_source:7s} "
              f"| bulle {self._bubble_want or '-':8s} {self._bubble_opacity:.2f} "
              f"yeux {self._eye_mix:.2f} "
              f"| " + "  ".join(f"{c.name}:{c.total:.2f}" for c in tete),
              flush=True)

        if self.animator is not None:
            st = self.animator.stats
            ch = self.animator.channels
            ctx = self.sensors.context
            print(f"[diag] ctx   {ctx.state:9s} inactif={ctx.idle_seconds:6.1f} s "
                  f"| avant-plan={ctx.foreground_category:8s} "
                  f"plein_ecran={int(ctx.fullscreen)} "
                  f"| media={int(ctx.media_playing)} ({ctx.media_category}, "
                  f"{ctx.media_seconds:5.1f} s) "
                  f"| curseur {ctx.cursor_speed:7.1f} px/s "
                  f"immobile {ctx.cursor_still_seconds:5.1f} s",
                  flush=True)
            if self.locomotion is not None:
                lo = self.locomotion
                cible = f"{lo.target_x:7.0f}" if lo.travelling else "   -   "
                print(f"[diag] loco  x={lo.x:7.0f} cible={cible} "
                      f"domicile={lo.home_x:7.0f} sol={lo.floor_y:6.0f} "
                      f"arc={lo.arc:5.1f} sauts={lo.hops:3d} "
                      f"demarche={lo.gait} repos={lo.cooldown:4.1f}s",
                      flush=True)
            print(f"[diag] anim  clignements={st.blinks:3d} saccades={st.saccades:3d} "
                  f"actions={st.actions:2d} | tete lacet={ch['head.yaw']:+.3f} "
                  f"tangage={ch['head.pitch']:+.3f} | corps lacet={ch['body.yaw']:+.3f} "
                  f"| respiration={ch['body.flex']:+.4f} "
                  f"| interet={self.animator.look.interest:.2f}",
                  flush=True)
