"""Premier lancement : le robot sort du carton et se présente (lot L6 phase B).

Extrait de `window` au lot L10. Une petite scène muette en quatre phases —
`emerging`, `looking`, `surprised`, `asking` — dont les durées sont réglées pour
se lire sans se faire attendre : moins de cinq secondes en tout.

Elle arrive une fois dans la vie du produit, et c'est précisément pour cela
qu'elle mérite son propre fichier : personne ne la relira en cherchant autre
chose, et elle n'a pas à encombrer la lecture du reste.
"""

from __future__ import annotations

# Sortie du carton et présentations. Les durées sont celles d'une petite scène
# muette : assez lentes pour se lire, assez courtes pour ne pas se faire
# attendre. Le tout dure un peu moins de cinq secondes.
LEAP_VX = 330.0               # px/s, élan horizontal hors du carton
LEAP_VY = -300.0              # px/s, impulsion vers le haut du même bond
SETTLE_SECONDS = 0.45         # temps de repos après l'atterrissage
LOOK_SECONDS = 2.9            # il se repère, de gauche à droite
SURPRISE_SECONDS = 1.4        # il vous voit, et sursaute
SURPRISE_VY = -620.0          # px/s, le sursaut lui-même

# Phases où le regard est **piloté par la scène** et non par le curseur : le pet
# doit balayer l'écran puis regarder droit devant, et le suivi du curseur du
# lot L4 contrarierait les deux.
INTRO_SCRIPTED = ("emerging", "looking", "surprised")


class OnboardingMixin:
    """La scène d'arrivée, et elle seule."""

    # -- premier lancement (lot L6 phase B) ----------------------------------

    def begin_onboarding(self) -> None:
        """Le robot est neuf et sans nom : il attend dans son carton."""
        self._onboarding = True

    def emerge_at(self, center_x: float, floor_y: float) -> None:
        """Le robot **bondit** hors du carton, à cette position physique.

        Il ne tombe pas, il saute de côté. La nuance compte : le carton part en
        fondu, et sans élan propre le robot aurait l'air d'avoir été découvert
        là plutôt que d'être sorti tout seul. Un bond latéral raconte l'inverse,
        et il ne coûte qu'une vitesse horizontale sur la chute du lot L1.

        Le côté est choisi sur la **place disponible** et non tiré au hasard :
        sauter dans le bord de l'écran pour s'y écraser aussitôt ne serait pas
        une sortie triomphale.
        """
        _, _, pw, ph = self._pet_rect()
        self._x = float(center_x) - pw / 2.0
        self._y = float(floor_y) - ph

        mon = self.current_monitor()
        wl, _, ww, _ = mon.work
        centre_ecran = wl + ww / 2.0
        cote = -1.0 if center_x > centre_ecran else 1.0

        self._apply_position()
        self.show()
        self._falling = True
        self._vx = cote * LEAP_VX
        self._vy = LEAP_VY
        if self.animator is not None:
            self.animator.play("celebrate")
        self._intro_phase = "emerging"
        self._intro_t = 0.0
        self._settle_home()
        self.clock.poke()

    def _step_intro(self, dt: float) -> None:
        """Avance la petite scène d'arrivée, une phase à la fois.

        Écrite comme une suite d'états plutôt qu'en minuteries enchaînées :
        chaque phase sait ce qui la termine, donc l'ensemble se relit comme le
        scénario qu'il est — il sort, il se repère, il vous voit, il demande.
        """
        if not self._intro_phase:
            return
        self._intro_t += dt

        if self._intro_phase == "emerging":
            # Le bond finit quand il a touché le sol, plus un temps de pose :
            # enchaîner sur l'atterrissage même donnerait une scène pressée.
            if not self._falling and self._intro_t > SETTLE_SECONDS:
                self._enter_intro("looking")
            return

        if self._intro_phase == "looking":
            if self._intro_t >= LOOK_SECONDS:
                self._enter_intro("surprised")
            return

        if self._intro_phase == "surprised":
            if self._intro_t >= SURPRISE_SECONDS:
                # « asking » n'a pas de fin : c'est la bulle qui prend le
                # relais, et elle attend un clic.
                self._enter_intro("asking")

    def _enter_intro(self, phase: str) -> None:
        self._intro_phase = phase
        self._intro_t = 0.0
        if self.animator is None:
            return
        if phase == "looking":
            # Balayage de gauche à droite : la courbe du lot L4 fait
            # exactement ça, et le suivi du curseur est coupé le temps qu'elle
            # joue (cf. INTRO_SCRIPTED).
            self.animator.play("look_around")
        elif phase == "surprised":
            # Il regarde droit devant — le suivi est toujours coupé, donc la
            # tête revient d'elle-même au centre — et sursaute. Le sursaut est
            # un vrai saut, pas une pose : la chute du lot L1 le redescend.
            self.animator.play("poke_reaction")
            self.animator.set_mood("surpris")
            self._falling = True
            self._vx = 0.0
            self._vy = SURPRISE_VY
        self.clock.poke()

    def ask_for_name(self) -> None:
        """Ouvre la saisie du nom, après l'avoir annoncée par les yeux.

        L'ordre est celui demandé : d'abord les deux sigles à la place des
        pupilles — un robot et un point d'interrogation, « qui suis-je » —, puis
        le champ de saisie.
        """
        self.show_in_eyes("robot", "question", seconds=3.4)
        panel = self._ensure_panel()
        panel.open_page("name")
        self.place_panel()
        panel.open_panel()
