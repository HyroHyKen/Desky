"""Les jeux, côté fenêtre : lancer, faire tourner, arrêter (lot L12).

Les règles sont dans `pet/games`, et rien de ce qui est ici n'en décide. Ce
module est la couture : il fournit à la partie ce qu'elle ne peut pas savoir —
où est le sol, où est le curseur, où est le robot — et exécute ce qu'elle
décide.

**Le jeu vit dans la boucle de rendu**, à 30 fps, pas dans le tick de
comportement à 4 Hz. Un ballon avancé quatre fois par seconde traverserait
l'écran par sauts de cinquante pixels ; c'est du mouvement visible, donc c'est
la cadence du §3 « en interaction » qui s'applique.

**Le robot, lui, réfléchit à 4 Hz.** Il redemande sa destination au rythme du
comportement, et marche à la vitesse du produit — il n'a pas de mode « jeu »
dans lequel il se déplacerait plus vite. On le voit courir, et parfois arriver
juste.
"""

from __future__ import annotations

import logging

from ...brain.economy import AWARD_PER_GAME, AWARD_PER_RECORD
from ...brain.needs import game_fun
from ...feedback import bus
from ...games import PLAYER, Balloon, Rally
from ...games import robot as ia
from ...games.rally import SERVE_HEIGHT, SERVE_IMPULSE
from ...ui import sparks
from ...ui.balloon_window import BalloonWindow
from ..ground import floor_y

log = logging.getLogger("desky.window")

# Coût d'une partie, en points d'énergie, prélevé **au lancement**.
#
# Forfaitaire et non proportionnel à la durée : le prix doit être connu avant
# de jouer. Une partie qui coûterait d'autant plus qu'elle se passe bien
# punirait le joueur de bien jouer, ce que le §12 interdit.
ENERGY_COST = 12.0

# En dessous de ce niveau, le robot refuse de jouer. Il ne s'agit pas de
# rationner : un robot épuisé qui court après un ballon est une image triste, et
# le §12 demande qu'il ait le droit d'être fatigué.
ENERGY_FLOOR = 18.0

# Période de rafraîchissement de la visée du robot, en secondes. 5 Hz : assez
# pour rattraper un rebond sur le bord de l'écran dans les deux cents
# millisecondes, assez peu pour que la prédiction coûte 0,2 % d'un cœur au lieu
# de 1 %.
AIM_REFRESH = 0.2


class GamesMixin:
    """Cycle de vie d'une partie, et le robot qui y joue."""

    # -- lancement -----------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self.rally is not None and not self.rally.over

    def can_play(self) -> bool:
        """Le robot a-t-il l'énergie de jouer ?"""
        return self.brain.needs.energy >= ENERGY_FLOOR + ENERGY_COST

    def start_rally(self) -> bool:
        """Lance une partie. Rend `False` si le robot n'en a pas la force."""
        if self.playing or not self.can_play():
            return False

        _, _, pw, ph = self._pet_rect()
        mon = self.current_monitor()
        wl, wt, ww, _ = mon.work
        sol = floor_y(mon.work, 0)          # le sol, pas le haut du pet

        ballon = Balloon(
            x=self._x + pw / 2.0,
            y=sol - SERVE_HEIGHT * ph,
            pet_h=float(ph),
            left=float(wl), right=float(wl + ww), floor=float(sol),
            top=float(wt),
        )
        # Service : il **monte**, longuement. Sans élan franc le ballon
        # apparaîtrait et tomberait, ce qui se lit comme une balle lâchée.
        ballon.vy = -SERVE_IMPULSE * ph

        self.rally = Rally(ballon, best=self.session.best_score("rally"))
        self.rally.on_hit = self._on_rally_hit
        self.rally.on_end = self._on_rally_end

        # L'énergie est prélevée ici, et une seule fois : le prix est connu
        # avant de jouer.
        self.brain.needs.energy = max(0.0, self.brain.needs.energy - ENERGY_COST)

        self._ensure_balloon().set_dpr(pw / max(1, self.width()))
        self.clock.poke()
        bus.emit("partie_lancee", jeu="rally")
        log.info("partie lancée : rally")
        return True

    def stop_rally(self) -> None:
        """Arrête la partie en cours. Le score acquis compte."""
        if self.rally is not None and not self.rally.over:
            self.rally.abandon()
        self._close_balloon()

    def _ensure_balloon(self) -> BalloonWindow:
        if self.balloon_window is None:
            self.balloon_window = BalloonWindow()
        return self.balloon_window

    def _close_balloon(self) -> None:
        if self.balloon_window is not None:
            self.balloon_window.hide_balloon()

    def _on_game(self, jeu: str) -> None:
        """Le panneau demande une partie."""
        if jeu != "rally":
            return
        if not self.start_rally():
            # Refus : le robot n'a pas la force. Le §12 interdit de punir, donc
            # on le **dit** — par la bulle, comme tout le reste.
            self.show_in_eyes("energy", "energy", seconds=2.2)
            log.info("partie refusée : énergie insuffisante")

    # -- boucle --------------------------------------------------------------

    def _step_rally(self, dt: float) -> None:
        """Avance la partie, d'une image de rendu."""
        partie = self.rally
        if partie is None or partie.over:
            return

        # Le pet masqué — plein écran d'une autre application, session
        # verrouillée — met fin à la partie plutôt que de la laisser courir
        # dans le vide. Le score compte quand même (cf. `Rally.abandon`).
        if self._suspended:
            self.stop_rally()
            return

        partie.step(dt)
        self._aim_age += dt

        if partie.over:
            # `step` vient de conclure : `on_end` a déjà masqué le calque. Sans
            # ce retour, la suite le replacerait et le rendrait — le ballon
            # restait donc affiché, posé au sol, après la fin de la partie.
            return

        ballon = partie.balloon
        _, top, pw, ph = self._pet_rect()

        # Le joueur frappe en **effleurant** le ballon. C'est la fenêtre qui lit
        # le curseur : étant traversante, elle ne recevra jamais d'événement.
        if partie.player_turn and BalloonWindow.cursor_touches(ballon):
            cx, _cy = self._cursor_x()
            partie.hit(PLAYER, float(cx))

        # Le robot frappe quand le ballon est à portée de sa tête.
        ia.play(partie, self._x + pw / 2.0, float(top), float(ph))

        fenetre = self._ensure_balloon()
        fenetre.set_dpr(pw / max(1, self.width()))
        fenetre.follow(ballon, partie.player_turn)
        self.clock.poke()

    def _cursor_x(self) -> tuple[float, float]:
        from .. import win32

        cx, cy = win32.get_cursor_pos()
        return float(cx), float(cy)

    def _rally_travel(self) -> float | None:
        """Destination du robot pendant une partie, ou `None` s'il n'a rien à y
        faire.

        **Mise en cache, et ce n'est pas une optimisation prématurée.** La visée
        rejoue toute la trajectoire du ballon jusqu'au sol : 0,32 ms mesurées.
        Appelée à chaque image de la boucle de rendu — c'est là que la
        locomotion demande sa cible — elle coûterait 1 % d'un cœur à elle seule,
        sur un budget de 4 % (§3), pour recalculer un résultat identique.

        Identique, parce que la trajectoire ne change qu'à la **frappe**. D'où
        l'invalidation sur le score, qui est exact, doublée d'un rafraîchissement
        à 5 Hz qui rattrape le seul autre cas : un rebond sur le bord de
        l'écran, qui change la course sans que personne ait frappé.
        """
        partie = self.rally
        if partie is None or partie.over:
            self._aim_cache = None
            return None

        marque = (partie.score, partie.turn)
        assez_frais = (self._aim_cache is not None
                       and self._aim_cache[0] == marque
                       and self._aim_age < AIM_REFRESH)
        if assez_frais:
            return self._aim_cache[1]

        _, _, _, ph = self._pet_rect()
        cible = ia.aim(partie, float(ph))
        self._aim_cache = (marque, cible)
        self._aim_age = 0.0
        return cible

    # -- réactions -----------------------------------------------------------

    def _balloon_rect(self) -> tuple[float, float, float, float]:
        """Rectangle centré sur le ballon, au format des recettes de `sparks`.

        Les gerbes naissent là où le ballon est frappé, pas là où le robot se
        trouve : le calque de particules est donc recadré sur le ballon avant
        d'émettre, sans quoi l'effet serait rogné dès que les deux s'écartent.
        """
        ballon = self.rally.balloon
        cote = 2.0 * ballon.radius
        return (ballon.x - cote / 2.0, ballon.y - cote / 2.0, cote, cote)

    def _dust_on_balloon(self):
        calque = self._ensure_dust()
        _, _, pw, _ = self._pet_rect()
        calque.reframe(self._balloon_rect(), pw / max(1, self.width()))
        return calque

    def _on_rally_hit(self, qui: str) -> None:
        """Une frappe a eu lieu. Le fait, et ce qu'on en montre."""
        if qui != PLAYER and self.animator is not None:
            self.animator.play("celebrate")
        sparks.care_sparks(self._dust_on_balloon().banc, self._balloon_rect())
        bus.emit("ballon_frappe", par=qui, echange=self.rally.score)

    def _on_rally_end(self, score: int) -> None:
        record = self.session.record_score("rally", score)

        # **Les jeux sont la source des jetons** depuis le lot L13 : les soins
        # étant devenus des objets qu'on achète, ils ne peuvent plus financer
        # leur propre achat. Un jeton par partie, cinq pour un record — un
        # record est rare, et il doit valoir le coup de viser haut plutôt que
        # d'enchaîner les parties bâclées.
        gagne = self.session.award_tokens(
            AWARD_PER_RECORD if record else AWARD_PER_GAME)

        # Et jouer **est** ce qui amuse le robot. La jauge d'amusement n'a plus
        # d'autre source que la caresse, qui rend peu : c'est ici qu'elle se
        # remplit, d'autant plus que la partie a été longue.
        self.brain.needs.apply({"fun": game_fun(score)})
        self.session.flush(force=True)
        if self.diag:
            print(f"[diag] partie : {score} échanges, +{gagne} jetons",
                  flush=True)
        # La poussière tombe **là où le ballon a touché**, à pleine force : un
        # ballon qui s'échoue sans rien soulever n'aurait pas l'air d'avoir
        # touché le sol.
        sparks.landing_dust(self._dust_on_balloon().banc, 1.0,
                            self._balloon_rect())
        bus.emit("partie_finie", jeu="rally", score=score, record=record)
        log.info("partie finie : %d échanges%s", score,
                 " — record" if record else "")
        self._close_balloon()
        if self.animator is not None:
            self.animator.play("celebrate" if record else "poke_reaction")

        # Le score se **montre**. Sans cela la partie s'arrête sans rien dire,
        # et il faut rouvrir le menu pour savoir ce qu'on a fait — ce qui revient
        # à ne pas donner le score.
        panneau = self._ensure_panel()
        panneau.last_score = {"rally": score}
        panneau.can_play = self.can_play()
        panneau.open_page("games")
        self.place_panel()
        panneau.open_panel()
