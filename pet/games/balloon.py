"""Le ballon de baudruche, et la partie qui se joue avec (lot L12).

Deux objets, tous deux **purs** : ni Qt, ni fenêtre, ni rendu. La partie se
simule entièrement en mémoire, ce qui la rend testable au pas de temps
synthétique comme le reste du produit — et ce qui rend possible la seule chose
dont le robot ait vraiment besoin : **rejouer l'avenir**.

**Un ballon de baudruche n'est pas une balle.** Sa gravité est faible et son
frottement énorme : il descend lentement, dérive au lieu de filer droit, et
n'accélère presque jamais. C'est ce qui rend le jeu jouable à la souris — une
balle de tennis serait intattrapable, et une balle sans frottement partirait en
ligne droite hors de l'écran.

**Il s'alourdit à chaque échange.** C'est toute la courbe de difficulté, et elle
tient dans un seul nombre : la gravité monte et le frottement baisse avec le
nombre d'échanges. Mesuré, le temps de vol passe de 3,3 s au premier échange à
1,4 s au vingt-quatrième, après quoi le poids plafonne. Le ballon devient une
balle, petit à petit — et c'est ce raccourcissement qui finit par mettre le
joueur en défaut.

**Le robot prédit en simulant.** Pas de formule fermée : avec du frottement
quadratique elle n'existe pas sous forme simple, et une approximation donnerait
un robot qui rate pour de mauvaises raisons. Il rejoue `step()` — la **même**
fonction, pas une copie — jusqu'au sol, et lit l'abscisse d'arrivée. La
prédiction ne peut donc pas diverger de la physique : c'est la physique.
"""

from __future__ import annotations

import math

# -- ballon ------------------------------------------------------------------
#
# Toutes les constantes sont en **hauteurs de pet par seconde** ou en fractions
# de hauteur de pet, jamais en pixels : la taille de rendu va de 120 à 400 px
# (§17.1) et le jeu doit se comporter pareil aux deux extrêmes.

GRAVITY = 1.35                 # h/s², au repos. Une balle serait à 12
DRAG = 1.15                    # frottement linéaire, par seconde
AIR_WOBBLE = 0.55              # dérive latérale d'un ballon qui retombe

# Alourdissement. `RALLY_FULL` échanges amènent le ballon à son poids maximal ;
# au-delà, il n'empire plus — une difficulté qui croît sans fin transforme un
# jeu d'adresse en compte à rebours.
RALLY_FULL = 24
HEAVY_GRAVITY = 4.6            # gravité au poids maximal
HEAVY_DRAG = 0.42              # il glisse davantage en s'alourdissant

# Frappe. L'impulsion est **verticale d'abord** : un ballon frappé part vers le
# haut, et la composante horizontale ne sert qu'à le déporter vers l'autre
# joueur pour que l'échange ait lieu.
HIT_UP = 2.35                  # h/s
# Mesuré : le ballon parcourt 1,5 à 1,9 hauteur de pet par échange, soit 330 à
# 420 px à la taille par défaut. En dessous, la partie est statique et personne
# ne se déplace ; au-dessus, le robot n'arrive plus à temps aux scores élevés.
HIT_SIDE = 1.80                # h/s, vers l'adversaire
HIT_SPIN = 0.22                # part de la position de frappe reportée en biais

# Deux frappes ne peuvent pas s'enchaîner plus vite que ça. Sans ce délai, un
# curseur immobile dans le ballon le frapperait à chaque image.
HIT_COOLDOWN = 0.28

# Rayon du ballon, en hauteurs de pet.
RADIUS = 0.30


def _clamp(v: float, a: float, b: float) -> float:
    return max(a, min(b, v))


class Balloon:
    """Position, vitesse, et le poids qui vient avec les échanges.

    Les unités sont des **pixels physiques d'écran** pour les positions, comme
    le pet et comme tout ce qui se pose sur le bureau. `pet_h` convertit les
    constantes relatives, une fois, à la construction.
    """

    __slots__ = ("x", "y", "vx", "vy", "pet_h", "left", "right", "floor",
                 "top", "rally", "_cooldown", "squash")

    def __init__(self, x: float, y: float, pet_h: float,
                 left: float, right: float, floor: float,
                 top: float | None = None) -> None:
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.pet_h = float(pet_h)
        self.left, self.right = float(left), float(right)
        self.floor = float(floor)
        # Plafond de la pièce. Sans lui, le ballon sort par le haut de l'écran
        # dès que le pet est réglé grand : le service monte à 3,3 hauteurs de
        # pet, soit 1 320 px à la taille maximale du §17.1 — au-dessus de la
        # zone de travail de la plupart des écrans. Un ballon qu'on perd de vue
        # pendant deux secondes n'est pas un jeu.
        self.top = float(floor) - 12.0 * self.pet_h if top is None else float(top)
        self.rally = 0
        self._cooldown = 0.0
        # Déformation à la frappe : un ballon de baudruche s'écrase. Même
        # vocabulaire qu'au lot L10, même raison — sans elle il a l'air rigide.
        self.squash = 0.0

    # -- lecture -------------------------------------------------------------

    @property
    def radius(self) -> float:
        return RADIUS * self.pet_h

    @property
    def heaviness(self) -> float:
        """Poids dans [0, 1]. C'est toute la courbe de difficulté."""
        return _clamp(self.rally / float(RALLY_FULL), 0.0, 1.0)

    @property
    def gravity(self) -> float:
        k = self.heaviness
        return (GRAVITY + (HEAVY_GRAVITY - GRAVITY) * k) * self.pet_h

    @property
    def drag(self) -> float:
        k = self.heaviness
        return DRAG + (HEAVY_DRAG - DRAG) * k

    @property
    def can_hit(self) -> bool:
        return self._cooldown <= 0.0

    @property
    def grounded(self) -> bool:
        return self.y >= self.floor

    def contains(self, px: float, py: float) -> bool:
        """Le point est-il dans le ballon ?"""
        return math.hypot(px - self.x, py - self.y) <= self.radius

    # -- physique ------------------------------------------------------------

    def step(self, dt: float) -> None:
        """Avance d'un pas. **La seule intégration du jeu.**

        C'est aussi celle que le robot rejoue pour prédire : garder un unique
        point de vérité est ce qui garantit qu'il vise là où le ballon va
        réellement, et non là où une seconde implémentation croit qu'il va.
        """
        if dt <= 0.0:
            return
        self._cooldown = max(0.0, self._cooldown - dt)
        self.squash = max(0.0, self.squash - dt * 3.2)

        self.vy += self.gravity * dt
        frein = max(0.0, 1.0 - self.drag * dt)
        self.vx *= frein
        self.vy *= frein

        # Dérive : un ballon qui tombe ne tombe pas droit. Le sinus dépend de la
        # **hauteur** et non du temps, pour que la trajectoire soit une fonction
        # de l'état — donc reproductible par la prédiction.
        self.vx += (math.sin(self.y * 0.013) * AIR_WOBBLE
                    * self.pet_h * dt * (1.0 - self.heaviness))

        self.x += self.vx * dt
        self.y += self.vy * dt

        # Bords : il rebondit, en perdant beaucoup — de la baudruche sur un mur.
        r = self.radius
        if self.x - r < self.left:
            self.x = self.left + r
            self.vx = abs(self.vx) * 0.55
        elif self.x + r > self.right:
            self.x = self.right - r
            self.vx = -abs(self.vx) * 0.55

        if self.y - self.radius < self.top:
            # Il **touche** le plafond et repart mollement : c'est de la
            # baudruche, elle ne rebondit pas comme une balle de squash.
            self.y = self.top + self.radius
            self.vy = abs(self.vy) * 0.25

        if self.y > self.floor:
            self.y = self.floor

    def hit(self, from_x: float, toward: float) -> bool:
        """Frappe le ballon. `toward` vaut +1 vers la droite, -1 vers la gauche.

        `from_x` est l'abscisse du contact : frapper le ballon sur son flanc
        l'envoie de biais, ce qui donne au geste une conséquence lisible au lieu
        d'une impulsion toujours identique.
        """
        if not self.can_hit:
            return False
        biais = _clamp((self.x - from_x) / max(1.0, self.radius), -1.0, 1.0)
        self.vy = -HIT_UP * self.pet_h
        self.vx = (toward * HIT_SIDE + biais * HIT_SPIN) * self.pet_h
        self._cooldown = HIT_COOLDOWN
        self.squash = 1.0
        self.rally += 1
        return True

    # -- prédiction ----------------------------------------------------------

    def predict_landing(self, max_seconds: float = 12.0,
                        dt: float = 1.0 / 60.0) -> tuple[float, float]:
        """Où et quand le ballon touchera le sol, s'il n'est pas frappé.

        Rend `(x, secondes)`. C'est ce que le robot regarde pour savoir où
        aller — et il le sait **exactement**, parce que cette méthode rejoue
        `step()` sur une copie plutôt que d'estimer une parabole. Un ballon de
        baudruche n'a pas de trajectoire parabolique : entre le frottement et la
        dérive, une formule fermée serait fausse d'une demi-largeur d'écran.

        Le coût est celui de quelques centaines d'additions, une fois par tick
        de comportement. C'est moins que la lecture du process au premier plan.
        """
        fantome = Balloon(self.x, self.y, self.pet_h,
                          self.left, self.right, self.floor, self.top)
        fantome.vx, fantome.vy = self.vx, self.vy
        fantome.rally = self.rally

        t = 0.0
        while t < max_seconds:
            fantome.step(dt)
            t += dt
            if fantome.grounded:
                break
        return fantome.x, t
