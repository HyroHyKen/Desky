"""La partie de « ne pas laisser tomber le ballon » (lot L12).

Les règles, séparées de la physique et de l'affichage. Aucune de ces lignes ne
sait ce qu'est une fenêtre : une partie entière se joue en mémoire, au pas de
temps synthétique, et c'est ce qui permet de la tester — y compris le robot,
qu'on peut faire jouer mille échanges en une seconde.

**Alternance stricte.** Chacun son tour, et le robot ne sauve pas une balle qui
vous revenait. C'est la règle qui donne un sens au score : « douze échanges »
veut dire douze fois où vous avez touché le ballon, pas douze fois où le robot
a rattrapé vos ratés.

Le corollaire est que la partie doit être **lisible** — il faut savoir à qui
c'est. D'où `turn`, exposé pour que l'interface le montre.

**Ce qui y met fin est une erreur, pas un chronomètre.** Le ballon s'alourdit à
chaque échange : mesuré, son temps de vol passe de 3,3 s au premier échange à
1,4 s au vingt-quatrième, après quoi le poids plafonne. C'est cette réduction
qui finit par mettre le joueur en défaut.

Un joueur qui ne raterait jamais jouerait donc indéfiniment — je l'ai simulé,
six cents échanges sans fin. C'est assumé : le plafond de poids existe pour que
la difficulté cesse de croître, sans quoi un jeu d'adresse devient un compte à
rebours. Le robot, lui, reste fiable jusqu'au bout : avec l'alternance stricte,
perdre à cause de son coéquipier serait une punition imméritée.
"""

from __future__ import annotations

from .balloon import Balloon

PLAYER = "player"
ROBOT = "robot"

# État de la partie.
SERVING = "serving"            # le ballon monte, personne n'a encore frappé
PLAYING = "playing"
OVER = "over"

# Durée du service : le ballon est lancé en l'air et **personne** ne peut le
# frapper pendant ce court instant. Sans ce délai, le curseur qui se trouvait
# déjà là au lancement frapperait aussitôt, et la partie commencerait par un
# échange que le joueur n'a pas voulu.
SERVE_SECONDS = 0.45

# Service. Le ballon part **plus bas** et avec beaucoup plus d'élan qu'à la
# première version : il montait alors de deux dixièmes de hauteur avant de
# redescendre, ce qui se lisait comme une balle lâchée et non comme une
# baudruche lancée.
#
# Mesuré avec ces valeurs : il s'élève de 1,3 hauteur de pet en 1,1 seconde et
# culmine à 3,3 au-dessus du sol. C'est cette ascension lente et ample qui dit
# « c'est léger » — davantage que n'importe quel réglage de gravité.
SERVE_HEIGHT = 2.0
SERVE_IMPULSE = 3.0            # h/s, vers le haut


class Rally:
    """Une partie : un ballon, un tour, un score.

    `on_hit` est appelé à chaque frappe avec le nom du frappeur. La fenêtre s'en
    sert pour les particules et l'animation ; les règles, elles, n'ont pas à
    savoir qu'il existe des particules.
    """

    __slots__ = ("balloon", "turn", "state", "score", "best", "_serve_t",
                 "on_hit", "on_end")

    def __init__(self, balloon: Balloon, best: int = 0,
                 first: str = PLAYER) -> None:
        self.balloon = balloon
        # Le joueur sert en premier : le robot ouvrirait sur une frappe que
        # personne n'a demandée, et la partie commencerait sans le joueur.
        self.turn = first
        self.state = SERVING
        self.score = 0
        self.best = int(best)
        self._serve_t = 0.0
        self.on_hit = None
        self.on_end = None

    # -- lecture -------------------------------------------------------------

    @property
    def over(self) -> bool:
        return self.state == OVER

    @property
    def record(self) -> bool:
        """La partie a-t-elle battu le record ? Vrai dès l'échange qui le bat."""
        return self.score > self.best

    @property
    def player_turn(self) -> bool:
        return self.state == PLAYING and self.turn == PLAYER

    @property
    def robot_turn(self) -> bool:
        return self.state == PLAYING and self.turn == ROBOT

    # -- déroulement ---------------------------------------------------------

    def step(self, dt: float) -> None:
        if self.state == OVER:
            return

        self.balloon.step(dt)

        if self.state == SERVING:
            self._serve_t += dt
            if self._serve_t >= SERVE_SECONDS:
                self.state = PLAYING
            return

        if self.balloon.grounded:
            self._finish()

    def hit(self, who: str, from_x: float) -> bool:
        """Tente une frappe. Rend `True` si elle a eu lieu.

        Refusée si ce n'est pas le tour de `who` : c'est ici, et nulle part
        ailleurs, que l'alternance est appliquée. Ni la fenêtre ni le robot
        n'ont à connaître la règle — ils tentent, et la partie tranche.
        """
        if self.state != PLAYING or self.turn != who:
            return False

        # Vers l'autre : le ballon repart du côté où se trouve celui qui doit
        # le reprendre. Sans cela, un échange sur deux serait injouable.
        vers = 1.0 if self.balloon.x < from_x else -1.0
        if not self.balloon.hit(from_x, -vers):
            return False

        self.score += 1
        self.turn = ROBOT if who == PLAYER else PLAYER
        if self.on_hit is not None:
            self.on_hit(who)
        return True

    def _finish(self) -> None:
        self.state = OVER
        if self.score > self.best:
            self.best = self.score
        if self.on_end is not None:
            self.on_end(self.score)

    def abandon(self) -> None:
        """Fin demandée de l'extérieur — le pet est masqué, l'utilisateur ferme.

        Le score acquis compte : abandonner n'est pas perdre, et effacer douze
        échanges parce qu'une vidéo est passée en plein écran serait une
        punition que le §12 interdit.
        """
        if self.state != OVER:
            self._finish()
