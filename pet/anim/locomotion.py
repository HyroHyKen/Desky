"""Déplacement du pet sur l'écran (lot L5b).

**Extension au CDC.** Le §6 ne prévoit que le déplacement à la souris ; la
locomotion autonome n'y est qu'implicite, dans trois des neuf actions v1 du §12 —
`idle_wander`, `follow_cursor` et `sniff_around` (« fouine près du bord de
l'écran »). Ce module fournit la **mécanique** ; c'est le lot L6 qui décidera
quand et où aller.

Module **pur** : il calcule une position désirée et des canaux de démarche, sans
toucher à la fenêtre. Même patron que l'animateur, et pour la même raison —
c'est ce qui le rend testable sans fenêtre ni GPU, sur des terrains écrits à la
main.

**Le domicile est défini par le dernier glisser de l'utilisateur.** La flânerie
revient toujours dans ses environs. Sans cette règle, la locomotion autonome
écraserait en permanence la position que le lot L1 persiste par moniteur, et
l'intention de l'utilisateur serait perdue au premier pas.

Toutes les positions publiques sont des **centres** en pixels physiques : c'est
ainsi qu'on pense une cible. La conversion vers le coin de la fenêtre, dont
`SetWindowPos` a besoin, se fait à la lecture.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass

from .rig_pose import Channels, Spring, ease_in_out, ease_out_back, zero_channels

log = logging.getLogger("desky.locomotion")


# --- Terrain ---------------------------------------------------------------

# Largeur de la bande, en pixels, sur laquelle deux sols de hauteurs différentes
# sont mélangés. Les moniteurs n'ont pas la même zone de travail — sur la machine
# de dev, trois écrans avec des décalages verticaux de −10 et −19 — donc le sol
# saute à la frontière. Mélangé sur une bande, le pas devient une pente.
FLOOR_BLEND_PX = 90.0


@dataclass(frozen=True)
class Ground:
    """Zone de travail d'un **moniteur**, en coordonnées d'écran.

    Les bornes sont celles de la zone de travail elle-même, sans retrait : le
    retrait d'une demi-largeur de pet est appliqué au niveau du segment, ce qui
    est la seule façon de laisser le pet franchir la frontière entre deux écrans.
    """

    key: str
    x_left: float
    x_right: float
    floor_y: float          # y du **coin haut** de la fenêtre, pet posé

    def contains(self, x: float) -> bool:
        return self.x_left <= x <= self.x_right


@dataclass(frozen=True)
class Segment:
    """Bande continue praticable, formée de moniteurs adjacents.

    C'est la correction d'un défaut trouvé sur la première frise : en rentrant
    les bornes moniteur par moniteur, il subsistait entre deux écrans un trou de
    la largeur du pet — sur la machine de dev, de 1810 à 2030 — où le centre du
    pet ne pouvait pas se trouver. La démarche par sauts le franchissait par
    chance, en progressant de 220 px à la fois ; le glissement s'y coinçait
    définitivement.

    Deux écrans qui se touchent forment donc une seule bande, et le retrait
    n'est appliqué qu'à ses deux extrémités.
    """

    grounds: tuple[Ground, ...]
    left: float             # centre minimal
    right: float            # centre maximal

    def contains(self, x: float) -> bool:
        return self.left <= x <= self.right

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    def clamp(self, x: float) -> float:
        return max(self.left, min(self.right, x))

    def distance_to(self, x: float) -> float:
        if self.contains(x):
            return 0.0
        return min(abs(x - self.left), abs(x - self.right))

    def floor_at(self, x: float) -> float:
        """Sol en x, adouci aux frontières internes entre moniteurs."""
        floor = None
        for ground in self.grounds:
            if ground.contains(x):
                floor = ground.floor_y
                break
        if floor is None:
            proche = min(self.grounds,
                         key=lambda g: min(abs(x - g.x_left), abs(x - g.x_right)))
            floor = proche.floor_y

        for gauche, droite in zip(self.grounds, self.grounds[1:]):
            if gauche.floor_y == droite.floor_y:
                continue
            frontiere = (gauche.x_right + droite.x_left) / 2.0
            distance = x - frontiere
            if abs(distance) > FLOOR_BLEND_PX:
                continue
            t = ease_in_out((distance + FLOOR_BLEND_PX) / (2.0 * FLOOR_BLEND_PX))
            floor = gauche.floor_y + (droite.floor_y - gauche.floor_y) * t
        return floor


# Tolérance d'adjacence entre deux zones de travail, en pixels. Deux écrans
# collés partagent normalement une abscisse à l'unité près ; on tolère quelques
# pixels pour les configurations approximatives.
ADJACENCY_TOL = 4.0


@dataclass(frozen=True)
class Terrain:
    """Les bandes praticables, ordonnées de gauche à droite."""

    segments: tuple[Segment, ...]

    @classmethod
    def from_monitors(cls, monitors, pet_w: int, pet_h: int) -> "Terrain":
        grounds = []
        for monitor in monitors:
            wl, wt, ww, wh = monitor.work
            if ww < pet_w or wh < pet_h:
                continue                    # écran trop petit pour le pet
            grounds.append(Ground(
                key=monitor.key,
                x_left=float(wl),
                x_right=float(wl + ww),
                floor_y=float(wt + wh - pet_h),
            ))
        return cls.from_grounds(grounds, pet_w)

    @classmethod
    def from_grounds(cls, grounds, pet_w: int) -> "Terrain":
        """Regroupe les sols adjacents en bandes continues."""
        ordonnes = sorted(grounds, key=lambda g: g.x_left)
        half = pet_w / 2.0
        segments: list[Segment] = []
        courant: list[Ground] = []

        def cloturer() -> None:
            if not courant:
                return
            gauche = courant[0].x_left + half
            droite = courant[-1].x_right - half
            if droite >= gauche:
                segments.append(Segment(tuple(courant), gauche, droite))

        for ground in ordonnes:
            if courant and ground.x_left <= courant[-1].x_right + ADJACENCY_TOL:
                courant.append(ground)
            else:
                cloturer()
                courant = [ground]
        cloturer()
        return cls(tuple(segments))

    @property
    def empty(self) -> bool:
        return not self.segments

    @property
    def grounds(self) -> tuple[Ground, ...]:
        return tuple(g for s in self.segments for g in s.grounds)

    @property
    def span(self) -> tuple[float, float]:
        """Bornes praticables, gauche et droite.

        Propriété et non méthode, comme `empty` et `grounds` : livrée en
        méthode au milieu de deux propriétés, elle s'est fait lire de travers au
        lot L6 et le pet plantait au premier tick de comportement.
        """
        if self.empty:
            return 0.0, 0.0
        return self.segments[0].left, self.segments[-1].right

    def segment_at(self, x: float) -> Segment:
        if self.empty:
            raise ValueError("terrain vide")
        for segment in self.segments:
            if segment.contains(x):
                return segment
        return min(self.segments, key=lambda s: s.distance_to(x))

    def clamp_x(self, x: float) -> float:
        """Ramène x dans la bande la plus proche.

        Deux bandes disjointes — écrans non contigus — ne sont pas franchissables
        à pied : on colle au bord de la plus proche plutôt que de flotter.
        """
        if self.empty:
            return x
        return self.segment_at(x).clamp(x)

    def floor_at(self, x: float) -> float:
        if self.empty:
            return 0.0
        return self.segment_at(x).floor_at(x)


# --- Démarches -------------------------------------------------------------

# Un robot sans jambes qui glisse lit comme un objet poussé ; un robot qui
# saute lit comme un être qui se déplace. Le saut a un second mérite : son arc
# masque le pas de sol au franchissement d'un moniteur.
GAITS = ("hop", "glide")

# Saut, en part de la hauteur du pet. Les valeurs de la première frise
# donnaient un traînement plutôt qu'un saut : arc de 0,20 à peine visible et
# portée trop courte pour que la traversée d'un écran soit supportable.
HOP_DISTANCE = 1.00            # portée horizontale d'un saut
HOP_HEIGHT = 0.28              # hauteur de l'arc
HOP_CROUCH = 0.11              # accroupissement d'anticipation
HOP_SQUASH = 0.065             # écrasement à l'atterrissage

# Durées des phases, en secondes.
CROUCH_TIME = 0.10
AIR_TIME = 0.30
LAND_TIME = 0.13
PAUSE_RANGE = (0.04, 0.16)

# Inclinaison dans le sens du mouvement, en radians par millier de pixels/s.
# Relevée après la première frise, où elle était invisible.
LEAN_PER_KPX = 0.62
MAX_LEAN = 0.26

# Glissement continu.
#
# Ressort sur la **vitesse**, pas sur la position. Un ressort de position va
# d'autant plus vite que la distance est grande : mesuré sur la première frise,
# il traversait 1440 px en 0,82 s, soit 1756 px/s — une téléportation, et
# l'inverse du comportement d'une marche. Une vitesse plafonnée donne un départ
# et une arrivée adoucis avec une croisière constante entre les deux.
GLIDE_CRUISE = 1.95            # hauteurs de pet par seconde
GLIDE_APPROACH = 4.0           # gain d'approche, par seconde
GLIDE_ACCEL_OMEGA = 7.0        # vivacité du changement de vitesse
GLIDE_ACCEL_ZETA = 1.0
GLIDE_BOB_WAVELENGTH = 0.50    # en hauteurs de pet
GLIDE_BOB_HEIGHT = 0.034

# Tolérance d'arrivée, en part de la hauteur du pet.
ARRIVE_EPS = 0.06

# Deux cibles plus proches que ça l'une de l'autre ne justifient pas de
# reprendre la route : c'est l'hystérésis qui évite le va-et-vient.
RETARGET_EPS = 0.45

# Après un glisser, le pet ne repart pas tout de suite : sinon c'est un bras de
# fer avec l'utilisateur.
USER_COOLDOWN = 2.5

# Flânerie : rayon autour du domicile, en hauteurs de pet.
WANDER_RANGE = 2.6

# Un trajet qui ne progresse plus pendant ce délai est abandonné. Défensif, mais
# nécessaire : sur la première version du terrain, le glissement se coinçait
# indéfiniment au bord d'une bande, et un pet bloqué est pire qu'un pet qui
# renonce.
STUCK_SECONDS = 1.5
STUCK_EPS = 1.0                # pixels de progrès minimaux


@dataclass
class Locomotion:
    """Position au sol, démarche, et cible courante.

    `pet_h` sert d'unité : toutes les constantes de démarche sont exprimées en
    hauteurs de pet, pour que le déplacement soit le même à 120 px qu'à 400 px
    (le CDC §17.1 rend la taille réglable).
    """

    terrain: Terrain
    pet_w: int
    pet_h: int
    x: float = 0.0                  # centre, physique
    gait: str = "hop"
    seed: int = 0

    def __post_init__(self) -> None:
        if self.gait not in GAITS:
            raise ValueError(f"démarche inconnue : {self.gait!r}")
        self.rng = random.Random(self.seed ^ 0x10C0)
        self.x = self.terrain.clamp_x(self.x)
        self.home_x = self.x
        self.target_x: float | None = None
        self.arc = 0.0              # élévation au-dessus du sol, en pixels
        self.cooldown = 0.0
        self._phase = "idle"
        self._phase_t = 0.0
        self._hop_from = self.x
        self._hop_to = self.x
        self._glide = Spring(0.0, omega=GLIDE_ACCEL_OMEGA,
                             zeta=GLIDE_ACCEL_ZETA)
        self._travelled = 0.0
        self.velocity = 0.0
        self.hops = 0
        self._stuck_t = 0.0
        self._stuck_x = self.x
        self.abandons = 0

    # -- lecture ------------------------------------------------------------

    @property
    def travelling(self) -> bool:
        return self.target_x is not None

    @property
    def floor_y(self) -> float:
        return self.terrain.floor_at(self.x)

    @property
    def window_x(self) -> float:
        """Coin gauche de la fenêtre, ce dont `SetWindowPos` a besoin."""
        return self.x - self.pet_w / 2.0

    @property
    def window_y(self) -> float:
        return self.floor_y - self.arc

    # -- pilotage -----------------------------------------------------------

    def set_home(self, x: float) -> None:
        """Fixe le domicile. Appelé quand l'utilisateur relâche un glisser."""
        self.home_x = self.terrain.clamp_x(x)
        self.x = self.home_x
        self.stop()

    def yield_to_user(self, x: float) -> None:
        """L'utilisateur a pris la main : on abandonne la cible et on attend."""
        self.x = self.terrain.clamp_x(x)
        self.stop()
        self.cooldown = USER_COOLDOWN

    def stop(self) -> None:
        self.target_x = None
        self._stuck_t = 0.0
        self._stuck_x = self.x
        self.arc = 0.0
        self.velocity = 0.0
        self._phase = "idle"
        self._phase_t = 0.0
        self._glide.reset(0.0)

    def go_to(self, x: float) -> bool:
        """Vise une position. Retourne False si la cible est refusée.

        Refusée quand le pet se repose après un glisser, ou quand la nouvelle
        cible est trop proche de la précédente pour justifier de repartir.
        """
        if self.cooldown > 0.0:
            return False

        cible = self.terrain.clamp_x(x)
        seuil = RETARGET_EPS * self.pet_h

        if self.target_x is not None and abs(cible - self.target_x) < seuil:
            return False
        if self.target_x is None and abs(cible - self.x) < max(
                seuil, ARRIVE_EPS * self.pet_h):
            return False

        self.target_x = cible
        return True

    def wander(self) -> bool:
        """Cible tirée au hasard près du domicile (CDC §12, `idle_wander`)."""
        rayon = WANDER_RANGE * self.pet_h
        return self.go_to(self.home_x + self.rng.uniform(-rayon, rayon))

    def go_home(self) -> bool:
        return self.go_to(self.home_x)

    # -- avance -------------------------------------------------------------

    def update(self, dt: float) -> Channels:
        out = zero_channels()
        if dt <= 0.0:
            return out

        if self.cooldown > 0.0:
            self.cooldown = max(0.0, self.cooldown - dt)

        if self.target_x is None:
            self.velocity = 0.0
            self.arc = 0.0
            return out

        if abs(self.target_x - self.x) <= ARRIVE_EPS * self.pet_h:
            self.x = self.target_x
            self.stop()
            return out

        # Abandon si le trajet ne progresse plus : cible dans une bande
        # inatteignable, ou blocage contre un bord.
        if abs(self.x - self._stuck_x) > STUCK_EPS:
            self._stuck_x, self._stuck_t = self.x, 0.0
        else:
            self._stuck_t += dt
            if self._stuck_t >= STUCK_SECONDS:
                log.debug("trajet abandonné, aucun progrès")
                self.abandons += 1
                self.stop()
                return out

        if self.gait == "hop":
            self._update_hop(dt, out)
        else:
            self._update_glide(dt, out)

        # Inclinaison dans le sens du mouvement, quelle que soit la démarche.
        lean = -self.velocity / 1000.0 * LEAN_PER_KPX
        out["body.roll"] = max(-MAX_LEAN, min(MAX_LEAN, lean))
        return out

    def _update_hop(self, dt: float, out: Channels) -> None:
        """Accroupissement, vol, atterrissage, courte pause. Puis on répète."""
        self._phase_t += dt
        portee = HOP_DISTANCE * self.pet_h

        if self._phase in ("idle", "pause"):
            duree = 0.0 if self._phase == "idle" else self._pause_time
            if self._phase_t >= duree:
                self._phase, self._phase_t = "crouch", 0.0
            return

        if self._phase == "crouch":
            t = min(1.0, self._phase_t / CROUCH_TIME)
            # Anticipation : il se tasse avant de partir (CDC §10).
            out["body.lift"] = -HOP_CROUCH * ease_in_out(t)
            out["body.flex"] = HOP_SQUASH * ease_in_out(t)
            if self._phase_t >= CROUCH_TIME:
                reste = self.target_x - self.x
                pas = math.copysign(min(portee, abs(reste)), reste)
                self._hop_from, self._hop_to = self.x, self.x + pas
                self._phase, self._phase_t = "air", 0.0
                self.hops += 1
            return

        if self._phase == "air":
            t = min(1.0, self._phase_t / AIR_TIME)
            avant = self.x
            self.x = self._hop_from + (self._hop_to - self._hop_from) * t
            self.velocity = (self.x - avant) / dt
            # Arc parabolique : vertical vrai, ni sinusoïde ni interpolation.
            self.arc = HOP_HEIGHT * self.pet_h * 4.0 * t * (1.0 - t)
            if self._phase_t >= AIR_TIME:
                self.x = self._hop_to
                self.arc = 0.0
                self._phase, self._phase_t = "land", 0.0
            return

        if self._phase == "land":
            t = min(1.0, self._phase_t / LAND_TIME)
            # Écrasement puis récupération avec dépassement (CDC §10).
            amorti = 1.0 - ease_out_back(t)
            out["body.flex"] = HOP_SQUASH * amorti
            out["body.lift"] = -HOP_CROUCH * 0.5 * amorti
            self.velocity *= max(0.0, 1.0 - t)
            if self._phase_t >= LAND_TIME:
                self._phase, self._phase_t = "pause", 0.0
                self._pause_time = self.rng.uniform(*PAUSE_RANGE)

    def _update_glide(self, dt: float, out: Channels) -> None:
        """Vitesse de croisière plafonnée, adoucie par un ressort."""
        cruise = GLIDE_CRUISE * self.pet_h
        reste = self.target_x - self.x
        # La vitesse voulue est proportionnelle à ce qui reste, mais bornée :
        # départ et arrivée sont donc adoucis, la croisière est constante.
        voulue = max(-cruise, min(cruise, reste * GLIDE_APPROACH))

        self.velocity = float(self._glide.step(voulue, dt))
        avant = self.x
        self.x = self.terrain.clamp_x(self.x + self.velocity * dt)
        self.velocity = (self.x - avant) / dt

        self._travelled += abs(self.x - avant)
        phase = self._travelled / (GLIDE_BOB_WAVELENGTH * self.pet_h)
        bob = abs(math.sin(phase * math.pi))
        out["body.lift"] = GLIDE_BOB_HEIGHT * bob
        out["body.flex"] = -GLIDE_BOB_HEIGHT * 0.5 * bob
        self.arc = 0.0
