"""Poids du robot : ce qu'il encaisse, et ce qu'il rend (CDC §10, lot L10).

Le §10 demande « anticipation avant les mouvements marqués et léger dépassement
à l'arrivée ». Un robot qui tombe et s'arrête net à la hauteur du sol n'a pas de
masse : il a une position. Ce module lui en donne une, par la plus vieille
recette de l'animation — **squash and stretch**.

Trois apports, et un seul ressort.

**L'impact est une impulsion, pas une position.** On ne pose pas « le robot est
comprimé de 8 % » : on retire de la vitesse au ressort, et il se comprime puis
repasse au-dessus de sa taille avant de se poser. C'est la différence entre un
robot qui *encaisse* et un robot qui *joue une animation d'encaissement* — et
elle se voit, parce que la profondeur de l'écrasement suit alors la vitesse
d'arrivée sans qu'on ait à la scénariser.

**L'étirement en vol n'est pas un ressort.** Il suit directement la vitesse
verticale : un corps rapide s'allonge dans l'axe de son mouvement, et cesse de
s'allonger dès qu'il ralentit. Le confier à un ressort le ferait traîner après
l'atterrissage, exactement là où il faut de la compression.

**Le ressort est exact à tout `dt`.** C'est ce qui remplace le `_pulse *= 0.88`
par image d'avant ce lot : à 10 fps le retour prenait trois fois moins de temps
réel qu'à 30, si bien que le pet réagissait au clic d'autant plus mollement
qu'il était occupé. Personne ne l'avait signalé, et c'est bien le problème — ce
genre de défaut ne se dit pas, il se ressent comme « c'est pas très réactif ».
"""

from __future__ import annotations

from .easing import Spring

# Réponse du ressort d'encaissement. Sous-amorti : sans cela il n'y a pas de
# rebond, et sans rebond il n'y a pas de poids — juste un aplatissement qui
# se résorbe.
IMPACT_OMEGA = 26.0
IMPACT_ZETA = 0.34

# Vitesse d'arrivée, en px/s, au-delà de laquelle l'écrasement est maximal. Le
# pet lâché du haut d'un écran arrive vers 1400 px/s ; posé doucement, vers 200.
LAND_FULL_SPEED = 1300.0

# Impulsion retirée au ressort pour un atterrissage à pleine vitesse. C'est le
# nombre à toucher en premier si l'impact paraît mou ou caricatural.
LAND_KICK = 6.5

# En dessous de cette vitesse, l'atterrissage ne produit rien. Un rebond de
# faible amplitude en fin de chute ne doit pas relancer un écrasement à chaque
# fois, sinon le pet frissonne en se posant.
LAND_MIN_SPEED = 120.0

# Réaction au clic. Plus sèche que l'atterrissage — c'est une surprise, pas une
# chute — et sans rapport avec une vitesse, donc à valeur fixe.
POKE_KICK = 3.8

# Étirement en vol. Plafonné : au-delà, le robot devient une nouille, ce qui
# appartient au dessin animé et pas à ce produit.
FLIGHT_FULL_SPEED = 1100.0
FLIGHT_STRETCH_MAX = 0.085

# Part de l'encaissement reportée sur `body.lift`, c'est-à-dire sur la
# translation du robot **entier**.
#
# Sans elle, l'impact ne déforme que le corps — et sur un génome à grosse tête
# et petit corps, le corps est la moitié la moins visible du robot. Le choc
# passait donc inaperçu sur la moitié des robots tirés, ce qui est exactement le
# genre de défaut qu'un rendu procédural fabrique : ce qui se voit sur la graine
# du développeur ne se voit pas ailleurs.
#
# L'enfoncement, lui, fait plonger la silhouette entière. Il se lit quelle que
# soit la morphologie.
LIFT_RATIO = 0.85


def _borne(valeur: float, bas: float, haut: float) -> float:
    return max(bas, min(haut, valeur))


class Impact:
    """Déformation verticale du corps : encaissement, rebond, étirement.

    Produit un seul canal, `body.flex`, que la fenêtre superpose aux couches du
    §10 comme elle le fait déjà pour la locomotion. Rien ici ne connaît la
    géométrie du robot ni le rendu : c'est un nombre, et le rig sait quoi en
    faire.
    """

    __slots__ = ("_ressort", "_vol")

    def __init__(self) -> None:
        self._ressort = Spring(0.0, omega=IMPACT_OMEGA, zeta=IMPACT_ZETA)
        self._vol = 0.0

    # -- entrées -------------------------------------------------------------

    def land(self, vitesse: float) -> float:
        """Encaisse un atterrissage à `vitesse` px/s. Rend la force dans [0, 1].

        La force est rendue pour que l'appelant puisse la transmettre : un son
        d'atterrissage et un nuage de poussière dépendent tous deux de la
        violence du choc, et c'est ici qu'elle est connue.
        """
        vitesse = abs(float(vitesse))
        if vitesse < LAND_MIN_SPEED:
            return 0.0
        force = _borne(vitesse / LAND_FULL_SPEED, 0.0, 1.0)
        # Impulsion **négative** : le corps part vers la compression, puis le
        # ressort le ramène en dépassant.
        self._ressort.velocity -= force * LAND_KICK
        return force

    def poke(self) -> None:
        """Réaction au clic."""
        self._ressort.velocity -= POKE_KICK

    def set_flight(self, vitesse_y: float) -> None:
        """Vitesse verticale courante, en px/s. Zéro au repos."""
        self._vol = _borne(abs(float(vitesse_y)) / FLIGHT_FULL_SPEED,
                           0.0, 1.0) * FLIGHT_STRETCH_MAX

    def reset(self) -> None:
        self._ressort.reset(0.0)
        self._vol = 0.0

    # -- sortie --------------------------------------------------------------

    def step(self, dt: float) -> None:
        self._ressort.step(0.0, dt)

    @property
    def flex(self) -> float:
        """Déformation totale. Négatif = comprimé, positif = étiré."""
        return float(self._ressort.value) + self._vol

    @property
    def settled(self) -> bool:
        """Plus rien à jouer. Sert à décider si l'image suivante est utile."""
        return self._vol == 0.0 and self._ressort.settled(0.0, epsilon=2e-3)

    def channels(self) -> dict[str, float]:
        """Canaux à superposer aux couches du §10.

        L'enfoncement ne prend **que** la part ressort, jamais l'étirement en
        vol : un robot qui monte s'allonge, il ne s'enfonce pas dans le sol.
        """
        out: dict[str, float] = {}
        flex = self.flex
        if flex:
            out["body.flex"] = flex
        ressort = float(self._ressort.value)
        if ressort:
            out["body.lift"] = ressort * LIFT_RATIO
        return out
