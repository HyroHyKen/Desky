"""Ce que le pet décide, et ce que la fenêtre en montre (CDC §5, §12, lot L6).

Sorti de `window` au lot L10. C'est ici que passe la **cloison du §5** : le
`brain` ne connaît pas le rendu, il ne publie qu'un plan et un nom de besoin. Ce
module est le seul endroit qui traduise l'un en poses et l'autre en bulle — et
le mettre à part rend cette frontière visible, au lieu de la laisser au milieu
de mille huit cents lignes de fenêtrage.

Trois temps :

- `_tick_brain` — l'interrogation périodique, à 4 Hz. C'est le rythme du §11,
  pas celui du rendu.
- `_apply_plan` — la traduction d'un plan en animation et en locomotion.
- `_step_bubble` — la bulle et l'afficheur par les yeux, avancés **par le
  rendu** et non par le comportement : à 4 Hz, une arrivée de 0,45 s se verrait
  par paliers.
"""

from __future__ import annotations

import logging
import math

from ...brain.utility import Plan
from ...render.glyphs import GLYPH_FOR_NEED, glyph_id

log = logging.getLogger("desky.window")

# Marge autour du curseur quand le pet le suit : il s'arrête à côté, pas
# dessus. Exprimée en largeurs de pet, la taille de rendu étant réglable.
FOLLOW_GAP = 0.85

# Retrait du bord d'écran pour `sniff_around`, en largeurs de pet.
EDGE_INSET = 0.35

# Constantes de temps de la bulle, en secondes. L'apparition est plus lente que
# la disparition : une bulle qui surgit brutalement se lit comme une alerte, et
# ce pet ne notifie jamais rien (§12).
BUBBLE_FADE_IN = 0.45
BUBBLE_FADE_OUT = 0.22

# Ressort d'arrivée de la bulle (lot L9). `zeta` en dessous de 1 fait dépasser
# la taille cible d'environ 12 %, ce qui se lit sans se remarquer ; au retour on
# repasse en amortissement critique, faute de quoi l'échelle passerait sous
# zéro.
BUBBLE_POP_OMEGA = 17.0
BUBBLE_POP_ZETA = 0.52
BUBBLE_CLOSE_ZETA = 1.0
# Période de la respiration d'appel de la bulle.
BUBBLE_PULSE_PERIOD = 2.4
# lui-même sans qu'on ait à faire quoi que ce soit.
EYE_SHOW_SECONDS = 2.6
EYE_FADE = 0.18


class BehaviourMixin:
    """Décision, plan, bulle."""

    # -- comportement (lot L6) -----------------------------------------------

    def _tick_brain(self, now: float) -> None:
        """Un tick de comportement, à 250 ms comme le §12 l'impose.

        Branché sur le timer des capteurs plutôt que sur un timer dédié : les
        deux tournent à 4 Hz et le second aurait besoin exactement des données
        que le premier vient de produire. Un troisième réveil coûterait de
        l'autonomie sans rien apporter (§3).

        Appelé **avant** toute sortie anticipée de `_on_system_check` : les
        besoins doivent continuer à s'écouler pendant qu'une vidéo plein écran
        masque le pet, sinon deux heures de film ne compteraient pas.
        """
        dt = 0.0 if self._brain_tick <= 0.0 else max(0.0, now - self._brain_tick)
        self._brain_tick = now
        if dt <= 0.0:
            return

        left, top, pw, ph = self._pet_rect()
        loco = self.locomotion
        self._me.x = self._x + pw / 2.0
        self._me.y = self._y
        # Hauteur du **corps** et non de la fenêtre : les deux coïncident au lot
        # L6 phase A, mais le bandeau de la bulle les séparera (phase B) et les
        # scores de distance se lisent en hauteurs de corps.
        self._me.pet_h = float(ph)
        self._me.travelling = bool(loco is not None and loco.travelling)
        self._me.home_x = float(loco.home_x) if loco is not None else self._me.x
        self._me.span = loco.terrain.span if loco is not None else (0.0, 0.0)
        if self.item_pending and self.item.state not in ("consumed", "expiring"):
            self._me.item_x = self.item.center(pw / max(1, self.width()))[0]
        else:
            self._me.item_x = None

        plan = self.session.update(dt, self.sensors.context, self._me)
        if plan.action != self._last_action:
            self._last_action = plan.action
            self._apply_plan(plan, pw)
        self._plan = plan
        if self.animator is not None:
            self.animator.set_mood(self.brain.expression)

    def _apply_plan(self, plan: Plan, pw: int) -> None:
        """Traduit un plan symbolique en courbe et en cible de déplacement.

        C'est **le seul** endroit qui connaisse à la fois le vocabulaire du
        `brain` et celui de `anim` et de la locomotion. Un nom inconnu y est
        ignoré, jamais rejeté : le `brain` doit pouvoir gagner une action sans
        que la fenêtre refuse de démarrer.
        """
        if self.animator is not None:
            if plan.curve:
                self.animator.play(plan.curve)
            else:
                self.animator.stop_action()

        loco = self.locomotion
        if loco is None:
            return

        if plan.travel == "stop":
            loco.stop()
        elif plan.travel == "wander":
            loco.wander()
        elif plan.travel == "home":
            loco.go_home()
        elif plan.travel == "cursor":
            cx = float(self.sensors.cursor.position[0])
            gap = FOLLOW_GAP * pw
            # On s'arrête du côté d'où l'on vient, pour ne pas traverser le
            # curseur et le regarder de l'autre bord.
            target = cx - gap if cx > self._me.x else cx + gap
            loco.go_to(target)
        elif plan.travel == "item":
            if self.item is not None and not self.item.gone:
                dpr = pw / max(1, self.width())
                cible = self.item.center(dpr)[0]
                # On s'arrête **sur** l'objet et non à côté : c'est le contact
                # qui déclenche, contrairement au suivi du curseur.
                loco.go_to(cible)
        elif plan.travel == "edge":
            # Le bord de **son écran**, et non du terrain.
            #
            # Le §12 dit « fouine près du bord de l'écran », au singulier, et
            # j'avais implémenté le bord de la bande praticable — c'est-à-dire,
            # sur un montage à trois moniteurs, une traversée de 5 540 px.
            # Mesuré avant correctif : 3 532 px de trajet médian pour cette
            # seule action, contre 379 pour la flânerie. Suivie du retour au
            # domicile, elle donnait le va-et-vient interminable que des
            # utilisateurs ont signalé.
            #
            # La cible reste bornée par le terrain : un écran peut déborder de
            # la bande praticable à ses extrémités.
            work = self.current_monitor().work
            low = float(work[0])
            high = float(work[0] + work[2])
            inset = EDGE_INSET * pw
            middle = 0.5 * (low + high)
            cible = low + inset if self._me.x > middle else high - inset
            loco.go_to(loco.terrain.clamp_x(cible))

    def _step_bubble(self, dt: float, now: float) -> None:
        """Avance l'apparition de la bulle et l'affichage par les yeux.

        Appelée par le rendu et non par le tick de comportement : à 4 Hz, un
        fondu de 0,45 s se verrait par paliers.
        """
        # La bulle se taît quand le pet dort ou qu'on le tient : il ne peut pas
        # demander à manger les yeux fermés, et une bulle qui suit un glisser
        # est du bruit.
        muet = (self._dragging or self._falling
                or not self._plan.look_at_cursor)
        if self._onboarding:
            # Pendant le baptême, la bulle porte un point d'interrogation et
            # rien d'autre : un robot qui réclamerait à manger avant d'avoir un
            # nom mettrait deux demandes en concurrence.
            #
            # Elle n'arrive qu'**à la fin** de la scène d'arrivée, et se retire
            # dès que la saisie est ouverte : une bulle qui demande encore alors
            # qu'on est en train de répondre est du bruit.
            prete = self._intro_phase == "asking"
            saisie = (self.panel is not None and self.panel.isVisible()
                      and self.panel.page == "name")
            want = "" if muet or not prete or saisie else "question"
        else:
            want = "" if muet else self.brain.needs.want()
        if want != self._bubble_want:
            self._bubble_want = want
            if want:
                # Nouveau besoin : on repart d'un affichage propre.
                self._eye_left_seconds = 0.0

        cible = 1.0 if self._bubble_want else 0.0
        # L'opacité reste un fondu : un fondu n'est pas un mouvement, et une
        # opacité qui dépasse serait écrêtée sans rien donner à voir.
        tau = BUBBLE_FADE_IN if cible > self._bubble_opacity else BUBBLE_FADE_OUT
        self._bubble_opacity += (cible - self._bubble_opacity) * min(
            1.0, dt / max(1e-3, tau))
        self._bubble_scale.zeta = (BUBBLE_POP_ZETA if cible > 0.0
                                   else BUBBLE_CLOSE_ZETA)
        self._bubble_scale.step(cible, dt)

        scene = self.scene
        if scene is None:
            return
        scene.bubble_glyph = glyph_id(
            "question" if self._bubble_want == "question"
            else GLYPH_FOR_NEED.get(self._bubble_want, ""))
        scene.bubble_opacity = self._bubble_opacity
        scene.bubble_scale = max(0.0, float(self._bubble_scale.value))
        scene.bubble_pulse = 0.5 + 0.5 * math.sin(
            now * 2.0 * math.pi / BUBBLE_PULSE_PERIOD)

        # Afficheur : décompte, puis fondu de retour vers les pupilles.
        self._eye_left_seconds = max(0.0, self._eye_left_seconds - dt)
        cible = 1.0 if self._eye_left_seconds > 0.0 else 0.0
        self._eye_mix += (cible - self._eye_mix) * min(1.0, dt / EYE_FADE)
        scene.eye_glyphs = (self._eye_left, self._eye_right)
        scene.eye_glyph_mix = self._eye_mix

    def show_in_eyes(self, left: str, right: str,
                     seconds: float = EYE_SHOW_SECONDS) -> None:
        """Affiche deux sigles à la place des pupilles.

        « C'est par ses yeux qu'on affichera ce qu'il souhaite dire à
        l'utilisateur. » Point d'entrée unique, utilisé par le clic sur la bulle
        et par le baptême du premier lancement.
        """
        self._eye_left = glyph_id(left)
        self._eye_right = glyph_id(right)
        self._eye_left_seconds = max(0.0, float(seconds))
        self.clock.poke()
