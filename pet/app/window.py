"""Fenêtre translucide, compositing QPainter et comportements système (CDC §6).

Mécanismes validés au lot L0 :

1. Translucidité — QWidget frameless + WA_TranslucentBackground, alimenté par
   une QImage en RGBA8888_Premultiplied issue du FBO. Le format prémultiplié
   n'est pas un détail : c'est ce qui évite le liséré noir sur le pourtour.
2. Hit-testing par alpha — la fenêtre est click-through par défaut, et un timer
   retire WS_EX_TRANSPARENT quand le curseur survole un pixel dont l'alpha
   dépasse le seuil. Aucun setMask() par image, aucun masque à maintenir.
3. Non-activation — Qt.Tool + WS_EX_NOACTIVATE + WA_ShowWithoutActivating.

Ajoutés au lot L1 :

4. Cadence adaptative, déléguée à `clock.RenderClock` (30 / 10 / 0 fps).
5. Déplacement à la souris, chute et recalage sur le sol de l'écran.
6. Position mémorisée par identifiant matériel de moniteur, avec repli sur
   l'écran principal quand le moniteur mémorisé a disparu.
7. Masquage et arrêt du rendu sous une application en plein écran exclusif.

**Un seul espace de coordonnées : le physique.** Curseur, rect de fenêtre, rects
de moniteurs et position sont tous lus et écrits en pixels physiques via Win32,
et le buffer alpha est lui aussi dimensionné en physique. Rien ne transite par
l'espace logique de Qt, ce qui supprime par construction tout risque de double
scaling sur un montage à DPI mixtes.
"""

from __future__ import annotations

import logging
import math
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from ..anim.layers import AnimContext, Animator
from ..anim.locomotion import Locomotion, Terrain
from ..brain.session import Session
from ..brain.sensors import Sensors
from ..brain.utility import Plan, SelfState
from ..geometry.builder import Robot, build
from ..render.context import RenderContext
from ..render.glyphs import GLYPH_FOR_NEED, glyph_id
from ..render.scene import Scene
from ..ui.item import ITEM_KINDS, REACH, SIZE_RATIO, ItemWindow, SpritePicker
from ..ui.panel import CarePanel
from ..state.save import Store
from . import win32
from .clock import Regime, RenderClock

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

# Durée d'affichage par les yeux après un clic sur la bulle. Assez long pour
# être lu sans avoir à se dépêcher, assez court pour que le pet redevienne
# lui-même sans qu'on ait à faire quoi que ce soit.
EYE_SHOW_SECONDS = 2.6
EYE_FADE = 0.18

# Période de la respiration d'appel de la bulle.
BUBBLE_PULSE_PERIOD = 2.4

# Jeu entre le haut du pet et le bas du panneau, en pixels logiques.
PANEL_GAP = 8

# Coups d'oeil de curiosité : intervalle entre deux, et durée de chacun.
# L'intervalle est large parce que c'est une **ponctuation** : trop fréquent, le
# pet aurait l'air distrait plutôt que curieux.
GLANCE_GAP = (7.0, 15.0)
GLANCE_HOLD = (1.2, 2.6)

# Distance minimale du point visé, en largeurs de pet. Un coup d'oeil vers un
# point tout proche ne tourne pas la tête, donc ne se voit pas : autant ne pas
# le jouer.
GLANCE_MIN_DISTANCE = 2.2

# Actions pendant lesquelles le pet est réputé curieux. Les trois partagent
# déjà l'expression `curieux` ; la liste est explicite pour que le regard ne
# dépende pas d'un détail d'expression qui pourrait changer.
CURIOUS_ACTIONS = frozenset({"sniff_around", "look_around", "idle_wander"})

# Fréquence de relecture de la fenêtre de premier plan, en secondes. `GetWindowRect`
# est bon marché mais il n'a aucune raison d'être appelé à chaque image : une
# fenêtre ne se déplace pas trente fois par seconde.
FOREGROUND_REFRESH = 0.5

# Distance d'apparition d'un objet de soin, en largeurs de pet. Assez loin pour
# que l'aller vaille le coup d'oeil, assez près pour qu'on le retrouve sans
# chercher — un objet lâché à l'autre bout d'un montage à trois écrans serait
# une corvée, pas un jeu.
ITEM_SPAWN_MIN = 2.0
ITEM_SPAWN_MAX = 6.0

# Hauteur de lâcher, en hauteurs d'objet : il tombe et rebondit, comme tout ce
# qui arrive dans ce bureau.
ITEM_DROP_HEIGHT = 1.6

# Seuil de la surface cliquable (CDC §6).
ALPHA_HIT_THRESHOLD = int(0.15 * 255)

# Cadences du timer de hit-testing. Le CDC prescrit 60 Hz ; le tenir en
# permanence coûte pour rien quand le curseur est à l'autre bout de l'écran, donc
# on retombe à 8 Hz hors d'une bbox élargie autour du pet, et on remonte à 60 Hz
# dès qu'on s'en approche. La marge de la bbox est plus large que la distance
# qu'un curseur parcourt en un intervalle lent, ce qui interdit de traverser la
# zone sans être vu.
HIT_HZ_NEAR = 60
HIT_HZ_FAR = 8
HIT_BBOX_MARGIN = 96          # pixels physiques

# La bbox opaque coûte 0,23 ms par image (mesure L0), soit 20 % du coût d'une
# image, pour une information qui bouge lentement — et qui est de toute façon
# élargie de HIT_BBOX_MARGIN. On ne la recalcule donc qu'une image sur N.
BBOX_REFRESH_EVERY = 8

# Cadence des vérifications système, alignée sur le polling des capteurs du
# CDC §11. Au lot L5 ces contrôles rejoindront `brain/sensors.py`.
SYSTEM_CHECK_MS = 250

# Sauvegarde périodique (CDC §14).
AUTOSAVE_MS = 60_000

# Chute vers le sol. Une parabole plutôt qu'une interpolation linéaire, avec un
# rebond amorti : le CDC §10 interdit toute interpolation linéaire sur un
# mouvement visible, et cette exigence vaut dès qu'un mouvement existe. Les
# couches d'animation à ressorts du lot L4 remplaceront cette intégration ad hoc.
GRAVITY = 2600.0              # px/s²
RESTITUTION = 0.28            # part de vitesse conservée au rebond
REST_VELOCITY = 45.0          # px/s en dessous desquels on considère posé
FALL_DRAG = 1.1               # amortissement de la composante horizontale

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


# --- Géométrie de position, en fonctions pures ------------------------------
#
# Isolées de la fenêtre pour être testables sans GPU ni hwnd, dans le même
# esprit que la cloison brain / render du CDC §5.


def position_to_frac(
    x: float, y: float, pet: tuple[int, int], work: tuple[int, int, int, int]
) -> tuple[float, int]:
    """Position absolue -> (fraction horizontale, écart au sol).

    Stocker une fraction et un écart au sol, plutôt que des pixels absolus,
    garde la position juste après un changement de résolution.
    """
    pw, ph = pet
    wl, wt, ww, wh = work
    span = max(1, ww - pw)
    x_frac = max(0.0, min(1.0, (x - wl) / span))
    floor_gap = max(0, round((wt + wh - ph) - y))
    return x_frac, floor_gap


def frac_to_position(
    x_frac: float, floor_gap: int, pet: tuple[int, int], work: tuple[int, int, int, int]
) -> tuple[float, float]:
    """(fraction horizontale, écart au sol) -> position absolue."""
    pw, ph = pet
    wl, wt, ww, wh = work
    x = float(wl + max(0.0, min(1.0, x_frac)) * max(0, ww - pw))
    y = float(wt + wh - ph - max(0, floor_gap))
    return x, y


def choose_monitor(monitors: list, wanted_key: str):
    """Choisit le moniteur d'affichage : le mémorisé, sinon l'écran principal.

    C'est le cas du portable dont on débranche l'écran externe (CDC §6) : la clé
    mémorisée ne correspond plus à rien, et le pet doit réapparaître sur l'écran
    principal plutôt que dans des coordonnées qui ne sont plus affichées.

    Retourne `(moniteur, replié)`, où `replié` dit si le moniteur mémorisé
    manquait — l'appelant s'en sert pour journaliser, et pour décider s'il faut
    reprendre la position mémorisée ou repartir d'un placement par défaut.
    """
    if not monitors:
        raise ValueError("aucun moniteur actif")
    for m in monitors:
        if m.key == wanted_key:
            return m, False
    primary = next((m for m in monitors if m.primary), monitors[0])
    return primary, bool(wanted_key)


def floor_y(work: tuple[int, int, int, int], ph: int) -> float:
    """Ordonnée du pet posé sur le bord bas de la zone de travail."""
    _, wt, _, wh = work
    return float(wt + wh - ph)


class CuriousGaze:
    """Coups d'oeil du pet vers un point de son choix.

    « Comme s'il tentait d'amener l'utilisateur sur autre chose. » C'est la
    seule cible du regard qui ne vienne de rien d'observable : elle est
    **inventée** par le pet, et c'est précisément ce qui la rend vivante. Un
    regard qui ne fait que suivre des choses existantes reste réactif ; un
    regard qui part de lui-même vers un coin de l'écran suggère une intention.

    Le hasard vient d'une graine, comme le rythme des clignements du lot L4 : le
    tempérament d'attention appartient à l'identité du robot, et reste
    reproductible en test.
    """

    def __init__(self, seed: int = 0) -> None:
        import random
        self._rng = random.Random(seed)
        self.point: tuple[float, float] | None = None
        self._left = self._rng.uniform(*GLANCE_GAP)

    def update(self, dt: float, curious: bool, work, pet_x: float,
               pet_w: float) -> tuple[float, float] | None:
        """Avance l'horloge des coups d'oeil et rend le point visé, ou None."""
        self._left -= max(0.0, dt)
        if self._left > 0.0:
            return self.point

        if self.point is not None:
            # Fin du coup d'oeil : retour au régime normal.
            self.point = None
            self._left = self._rng.uniform(*GLANCE_GAP)
            return None

        if not curious:
            # Pas curieux : on repousse sans consommer le tour, sinon le
            # premier instant de curiosité déclencherait un coup d'oeil immédiat.
            self._left = self._rng.uniform(*GLANCE_GAP) * 0.5
            return None

        wl, wt, ww, wh = work
        mini = GLANCE_MIN_DISTANCE * max(1.0, pet_w)
        for _ in range(8):
            x = self._rng.uniform(wl, wl + ww)
            if abs(x - pet_x) >= mini:
                break
        else:
            x = wl if pet_x > wl + ww / 2.0 else wl + ww
        # Dans la moitié haute : regarder le sol ne raconte rien, alors qu'un
        # regard levé suggère qu'il a vu quelque chose.
        y = self._rng.uniform(wt + wh * 0.12, wt + wh * 0.55)
        self.point = (x, y)
        self._left = self._rng.uniform(*GLANCE_HOLD)
        return self.point


class PetWindow(QWidget):
    """Fenêtre du pet."""

    # La sortie est décidée par le bootstrap, pas par la fenêtre : une fenêtre
    # Qt.Tool n'étant pas primaire pour Qt, sa fermeture ne déclenche pas la
    # sortie (cf. setQuitOnLastWindowClosed dans main.py).
    quit_requested = Signal()

    def __init__(self, settings: Store, genome: dict, diag: bool = False,
                 session: Session | None = None) -> None:
        super().__init__()
        self.diag = diag
        self.settings = settings
        self.genome = genome
        self.robot: Robot | None = None
        self.animator: Animator | None = None
        self.locomotion: Locomotion | None = None
        self._loco_channels: dict[str, float] = {}
        self._gait = "hop"
        # Dernière position écrite, pour ne pas appeler SetWindowPos quand
        # l'arrondi n'a pas changé : mesuré au lot L5b, l'appel coûte
        # 0,55 ms en médiane et jusqu'à 16 ms en pointe.
        self._written: tuple[int, int] | None = None
        # Capteurs système. Créés tôt : ils ne dépendent ni du GPU ni du
        # robot, et la cloison du CDC §5 veut qu'ils ignorent le rendu.
        self.sensors = Sensors()
        self._last_state = ""

        # Comportement du lot L6. Injecte pour que la fenetre reste testable
        # sans disque ; a defaut elle ouvre elle-meme `state.json`.
        self.session = session if session is not None else Session()
        self.brain = self.session.brain
        self._plan: Plan = self.session.brain.plan
        self._me = SelfState()
        self._brain_tick = 0.0
        self._last_action = ""

        # Bulle et afficheur. L'état vit ici : c'est la fenêtre qui reçoit les
        # clics, et le `brain` ne connaît pas le rendu (cloison du §5). Lui ne
        # publie qu'un **nom de besoin**, par `Needs.want`.
        self._bubble_want = ""
        self._bubble_opacity = 0.0
        self._eye_left = 0
        self._eye_right = 0
        self._eye_left_seconds = 0.0
        self._eye_mix = 0.0

        # Position à l'image précédente, arrondie. Sert à décider si le pet
        # bouge vraiment (cf. `_wants_frames`).
        self._frame_pos: tuple[int, int] | None = None

        # Panneau de soin. Construit **au premier clic droit** et non ici : il
        # porte seize icônes et un champ de saisie, et l'immense majorité des
        # sessions ne l'ouvrira jamais.
        self.panel: CarePanel | None = None

        # Objet de soin posé sur le bureau. Un seul à la fois : deux gamelles
        # simultanées demanderaient au pet de choisir, et il n'y a rien à
        # gagner à ce choix-là.
        self.item: ItemWindow | None = None
        self._picker = SpritePicker(seed=int(genome.get("seed", 0)))

        # Premier lancement. Tant que le robot n'a pas de nom, sa bulle ne
        # demande pas à manger : elle demande qui il est.
        self._onboarding = False
        self._intro_phase = ""
        self._intro_t = 0.0
        self._vx = 0.0

        # Regard. La graine vient du génome, comme celle de l'animateur : le
        # tempérament d'attention fait partie de l'identité du robot.
        self._gaze = CuriousGaze(seed=int(genome.get("seed", 0)) ^ 0x5EED)
        self._hat_previews: dict[str, object] = {}
        self._purge_on_exit = False
        self._foreground_point: tuple[int, int] | None = None
        self._foreground_age = 0.0
        self._look_source = "cursor"
        self._look_point: tuple[float, float] = (0.0, 0.0)

        logical_size = int(settings.data["size"])

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(logical_size, logical_size)

        self._frame: np.ndarray | None = None       # buffer RGBA courant
        self._alpha: np.ndarray | None = None       # vue canal alpha, physique
        self._bbox: tuple[int, int, int, int] | None = None
        self._qimage: QImage | None = None

        self._yaw = 0.0
        self._frame_no = 0
        self._pulse = 0.0                           # réaction au clic
        self._t0 = time.perf_counter()
        self._t_last = self._t0

        # Position et physique de chute, en pixels physiques.
        self._x = 0.0
        self._y = 0.0
        self._vy = 0.0
        self._falling = False
        self._dragging = False
        self._drag_cursor0 = (0, 0)
        self._drag_origin0 = (0.0, 0.0)
        self._monitor_key = ""
        # Moniteur courant, rafraîchi par la vérification système à 4 Hz.
        # L'interroger par image coûtait 1,26 ms, plus que tout le rendu.
        self._monitor: win32.Monitor | None = None

        self._frames = 0
        self._t_render = 0.0
        self._t_paint = 0.0
        self._paints = 0
        self._cpu = win32.CpuMeter()
        self._foreground_at_start = win32.get_foreground_window()
        self._focus_stolen = False
        self._clicks = 0
        self._suspended = False

        self.rc: RenderContext | None = None
        self.scene: Scene | None = None

        self.clock = RenderClock(self)
        self.clock.tick.connect(self._on_render)
        self.clock.regime_changed.connect(self._on_regime)

        # Le hit-testing n'a pas besoin de régularité, seulement de réactivité :
        # un CoarseTimer suffit et laisse le système regrouper les réveils, ce
        # qui compte pour l'autonomie sur portable (CDC §3).
        self._hit_timer = QTimer(self)
        self._hit_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._hit_timer.timeout.connect(self._on_hit_test)

        self._system_timer = QTimer(self)
        self._system_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._system_timer.timeout.connect(self._on_system_check)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._autosave_timer.timeout.connect(self._on_autosave)

        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._on_diag)

    # -- cycle de vie --------------------------------------------------------

    @property
    def hwnd(self) -> int:
        return int(self.winId())

    def start(self) -> None:
        """À appeler après show() : le hwnd doit exister."""
        win32.apply_pet_window_styles(self.hwnd)

        # La taille de rendu est prise sur le rect physique de la fenêtre, pas
        # calculée depuis un facteur d'échelle : cf. win32.get_window_rect.
        _, _, pw, ph = win32.get_window_rect(self.hwnd)
        self.rc = RenderContext((pw, ph), samples=4)
        self.scene = Scene(self.rc)

        # La géométrie n'est construite et téléversée qu'ici, donc au changement
        # de génome et jamais par image (CDC §7).
        self.robot = build(self.genome, self.session.appearance)
        self.scene.set_robot(self.robot)

        # L'animateur est semé depuis la graine du génome : le rythme des
        # clignements et des saccades appartient à l'identité du robot.
        self.animator = Animator.for_robot(
            self.robot, seed=int(self.genome.get("seed", 0)))

        self.restore_position()
        self._rebuild_terrain()

        self.clock.start()
        self._hit_timer.start(1000 // HIT_HZ_FAR)
        self._system_timer.start(SYSTEM_CHECK_MS)
        self._autosave_timer.start(AUTOSAVE_MS)
        if self.diag:
            self._diag_timer.start(2000)
            print(f"[diag] GL {self.rc.info['version']} - {self.rc.info['renderer']}")
            print(f"[diag] rendu physique {pw}x{ph} pour {self.width()}x{self.height()} "
                  f"logiques (dpr {pw / self.width():.2f}), MSAA {self.rc.samples}x")
            for m in win32.list_monitors():
                print(f"[diag] moniteur {'primaire' if m.primary else '        '} "
                      f"rect={m.rect} work={m.work}")
            print(f"[diag] génome graine={self.genome.get('seed')} "
                  f"oreilles={self.genome['ear.type']} "
                  f"corps={self.genome['palette.body']} "
                  f"accent={self.genome['palette.accent']}")
            print(f"[diag] robot {len(self.robot.parts)} parties, "
                  f"{self.robot.triangle_count} triangles, "
                  f"construit en {self.robot.build_ms:.2f} ms")

    # -- position, sol et mémorisation par moniteur --------------------------

    def _pet_rect(self) -> tuple[int, int, int, int]:
        return win32.get_window_rect(self.hwnd)

    def current_monitor(self) -> win32.Monitor:
        """Moniteur portant le pet, mémorisé entre deux vérifications système."""
        if self._monitor is None:
            self._monitor = win32.monitor_from_window(self.hwnd)
        return self._monitor

    def refresh_monitor(self) -> win32.Monitor:
        """Force la relecture. Appelé à 4 Hz et après un déplacement."""
        self._monitor = win32.monitor_from_window(self.hwnd)
        return self._monitor

    def restore_position(self) -> None:
        """Replace le pet là où il était, ou sur le sol de l'écran principal.

        Si le moniteur mémorisé n'existe plus, on retombe sur l'écran principal
        (CDC §6). C'est le cas d'un portable dont on débranche l'écran externe.
        """
        _, _, pw, ph = self._pet_rect()
        monitors = win32.list_monitors()
        wanted = self.settings.data.get("last_monitor", "")

        mon, fell_back = choose_monitor(monitors, wanted)
        if fell_back:
            log.info("moniteur mémorisé absent, repli sur l'écran principal")

        pos = self.settings.data.get("positions", {}).get(mon.key)
        x_frac = pos["x_frac"] if pos else 0.82
        floor_gap = pos["floor_gap"] if pos else 0

        self._x, self._y = frac_to_position(x_frac, floor_gap, (pw, ph), mon.work)
        self._vy = 0.0
        self._falling = False
        self._monitor_key = mon.key
        self._apply_position()

    def configure_locomotion(self, gait: str = "hop") -> None:
        """Démarche, posée avant `start()`.

        L'échafaudage `--wander` du lot L5b a disparu ici : c'est désormais le
        `brain` qui choisit les cibles, ce que ce lot avait promis.
        """
        self._gait = gait

    def _rebuild_terrain(self) -> None:
        """(Re)construit le terrain et la locomotion depuis les moniteurs.

        Appelé au démarrage et quand la configuration d'écrans change : les
        bornes praticables et les hauteurs de sol en dépendent entièrement.
        """
        _, _, pw, ph = self._pet_rect()
        terrain = Terrain.from_monitors(win32.list_monitors(), pw, ph)
        if terrain.empty:
            self.locomotion = None
            return

        centre = self._x + pw / 2.0
        if self.locomotion is None:
            self.locomotion = Locomotion(
                terrain, pw, ph, x=centre, gait=self._gait,
                seed=int(self.genome.get("seed", 0)))
        else:
            self.locomotion.terrain = terrain
            self.locomotion.pet_w, self.locomotion.pet_h = pw, ph
            self.locomotion.set_home(centre)

    def _apply_position(self) -> None:
        pos = (round(self._x), round(self._y))
        if pos == self._written:
            return
        self._written = pos
        win32.set_window_pos(self.hwnd, *pos)

    def _settle_home(self) -> None:
        """Le glisser de l'utilisateur définit le domicile (décision du lot L5b).

        C'est **le domicile** qui est persisté, jamais la position courante :
        sinon la flânerie écraserait en permanence l'intention de l'utilisateur,
        et le pet ne reviendrait jamais là où on l'a posé.
        """
        _, _, pw, _ = self._pet_rect()
        if self.locomotion is not None:
            self.locomotion.set_home(self._x + pw / 2.0)
        self.remember_position()

    def remember_position(self) -> None:
        """Mémorise la position, en fraction de l'écran et écart au sol.

        Pas en pixels absolus : un changement de résolution replacerait sinon le
        pet hors écran ou au milieu de nulle part.
        """
        _, _, pw, ph = self._pet_rect()
        mon = self.current_monitor()
        x_frac, floor_gap = position_to_frac(self._x, self._y, (pw, ph), mon.work)

        positions = dict(self.settings.data.get("positions", {}))
        positions[mon.key] = {"x_frac": round(x_frac, 4), "floor_gap": floor_gap}
        self.settings.set(positions=positions, last_monitor=mon.key)
        self._monitor_key = mon.key


    def _anim_context(self, pw: int, ph: int) -> AnimContext:
        """Écart du curseur à la tête, en hauteurs de robot.

        Exprimé en hauteurs de robot et non en pixels : la taille de rendu est
        réglable de 120 à 400 px (CDC §17.1), et le pet doit tourner la tête de
        la même façon quelle que soit sa taille à l'écran.

        C'est le `brain` qui décide **s'il faut** suivre — `Plan.look_at_cursor`
        — et la fenêtre qui calcule **où**. La cloison du §5 est respectée : le
        `brain` produit un état symbolique et n'interroge jamais le curseur pour
        en tirer une géométrie de rendu.
        """
        if self.robot is None or self.scene is None:
            return AnimContext()

        if self._intro_phase in INTRO_SCRIPTED:
            # Le regard appartient à la scène : il balaie, puis revient de
            # lui-même au centre pour le sursaut.
            return AnimContext(dragging=self._dragging)

        if not self._plan.look_at_cursor:
            # `look_offset` à None fait cesser le suivi (cf. AnimContext) : un
            # pet endormi ne suit pas la souris des yeux.
            return AnimContext(dragging=self._dragging)

        left, top, _, _ = self._pet_rect()
        cx, cy = self._look_point

        head = self.robot.dims
        ax, ay = self.scene.project_px((0.0, head.head_center_y, 0.0))

        scale = float(max(1, ph))
        dx = (cx - (left + ax)) / scale
        # Le y de l'écran descend, celui du regard monte.
        dy = -(cy - (top + ay)) / scale

        return AnimContext(look_offset=(dx, dy), dragging=self._dragging)

    def _look_target(self, dt: float, pw: int) -> tuple[float, float]:
        """Ce que le pet regarde, en pixels physiques. Une seule liste, ici.

        Le pet ne suivait que le curseur, ce qui le rendait sourd à tout le
        reste : il fixait la souris pendant qu'il marchait vers sa gamelle, et
        pendant qu'une vidéo jouait à l'autre bout de l'écran.

        L'ordre est une **priorité**, du plus intentionnel au plus par défaut :

        1. on le tient — il regarde ce qui le porte ;
        2. il a décidé d'aller chercher un objet — il regarde l'objet ;
        3. il a un coup d'oeil de curiosité en cours — il regarde où il veut ;
        4. une vidéo joue — il regarde la fenêtre qui la joue ;
        5. on écrit — il regarde le caret, à défaut la fenêtre active ;
        6. sinon, le curseur.

        Rien de tout cela ne lit un contenu : le point 4 et le point 5 ne
        prennent que des **géométries** de fenêtre, ce que le §11 autorise, et
        le caret vient de `GetGUIThreadInfo`, sans aucun hook (§3).
        """
        curseur = self.sensors.cursor.position

        if self._dragging:
            self._look_source = "cursor"
            return curseur

        if self._plan.travel == "item" and self.item is not None \
                and not self.item.gone:
            self._look_source = "item"
            return self.item.center(pw / max(1, self.width()))

        contexte = self.sensors.context
        mon = self.current_monitor()
        curieux = (self._plan.action in CURIOUS_ACTIONS
                   or self.brain.expression == "curieux")
        coup_d_oeil = self._gaze.update(dt, curieux, mon.work,
                                        self._x + pw / 2.0, float(pw))
        if coup_d_oeil is not None:
            self._look_source = "glance"
            return coup_d_oeil

        # La fenêtre de premier plan n'est relue que deux fois par seconde.
        self._foreground_age += dt
        if self._foreground_age >= FOREGROUND_REFRESH:
            self._foreground_age = 0.0
            self._foreground_point = win32.foreground_window_center(self.hwnd)

        if contexte.media_playing and self._foreground_point is not None:
            self._look_source = "media"
            return self._foreground_point

        if contexte.state == "typing":
            caret = win32.caret_position()
            if caret is not None:
                self._look_source = "caret"
                return caret
            if self._foreground_point is not None:
                self._look_source = "window"
                return self._foreground_point

        self._look_source = "cursor"
        return curseur

    # -- rendu ---------------------------------------------------------------

    def _on_regime(self, regime: Regime) -> None:
        """Masque réellement la fenêtre quand le rendu est suspendu.

        Suspendre le rendu sans masquer laisserait la dernière image affichée,
        figée, par-dessus l'application en plein écran.
        """
        suspended = regime is Regime.SUSPENDED
        if suspended == self._suspended:
            return
        self._suspended = suspended

        if suspended:
            self._hit_timer.stop()
            win32.set_click_through(self.hwnd, True)
            self.hide()
        else:
            self.show()
            # Qt peut reposer ses propres styles étendus en réaffichant.
            win32.apply_pet_window_styles(self.hwnd)
            self._apply_position()
            self._hit_timer.start(1000 // HIT_HZ_FAR)

    def _on_render(self) -> None:
        if self.rc is None or self.scene is None or self._suspended:
            return
        _t_enter = time.perf_counter()

        # La DPR peut changer si la fenêtre passe sur un moniteur d'échelle
        # différente ; on suit la taille physique réelle.
        _, _, pw, ph = self._pet_rect()
        if (pw, ph) != self.rc.size:
            self.rc.resize((pw, ph))

        now = time.perf_counter()
        dt = min(0.1, now - self._t_last)       # borné : un réveil tardif ne doit
        self._t_last = now                      # pas téléporter le pet
        t = now - self._t0

        self._pulse *= 0.88                     # retour élastique du clic
        self._step_fall(dt, ph)
        self._look_point = self._look_target(dt, pw)
        self._step_intro(dt)
        self._step_item(dt)
        self._step_locomotion(dt, t, pw, ph)
        self._step_bubble(dt, t)
        if self.panel_open:
            # Replacé à chaque image : le pet peut encore tomber ou être
            # déplacé à la souris pendant que le panneau est ouvert.
            self.place_panel()

        # Le robot ne tourne plus sur lui-même : c'est l'animation qui l'oriente
        # désormais, et la caméra reste fixe.
        if self.animator is not None:
            self.animator.update(dt, self._anim_context(pw, ph),
                                 extra=self._loco_channels)
            self.scene.face_state = self.animator.face

        # Cadence : sollicitée par ce que le pet **fait**, et non plus seulement
        # par la proximité du curseur (cf. `_wants_frames`).
        if self._wants_frames():
            self.clock.poke()

        mon = self.current_monitor()
        lift = max(0.0, floor_y(mon.work, ph) - self._y) / max(1.0, ph)

        self.rc.begin()
        self.scene.draw(yaw=self._yaw, pitch=0.16,
                        scale=1.0 + 0.12 * self._pulse, time_s=t, lift=lift)
        frame = self.rc.read_rgba()

        # Le tableau doit rester vivant tant que la QImage l'utilise : QImage ne
        # copie pas le buffer qu'on lui donne. RenderContext le réutilise d'une
        # image sur l'autre, donc la référence reste valide.
        self._frame = frame
        self._alpha = frame[:, :, 3]
        if self._frame_no % BBOX_REFRESH_EVERY == 0 or self._bbox is None:
            self._bbox = self._opaque_bbox(self._alpha)
        self._frame_no += 1

        qi = QImage(
            self._frame.data, frame.shape[1], frame.shape[0], frame.shape[1] * 4,
            QImage.Format.Format_RGBA8888_Premultiplied,
        )
        qi.setDevicePixelRatio(frame.shape[1] / self.width())
        self._qimage = qi

        self._frames += 1
        self._t_render += time.perf_counter() - _t_enter
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self._qimage is None:
            return
        _t_enter = time.perf_counter()
        painter = QPainter(self)
        # Source déjà prémultipliée : la composition par défaut est la bonne.
        painter.drawImage(0, 0, self._qimage)
        painter.end()
        self._t_paint += time.perf_counter() - _t_enter
        self._paints += 1

    @staticmethod
    def _opaque_bbox(alpha: np.ndarray) -> tuple[int, int, int, int] | None:
        """Bbox des pixels cliquables, élargie de la marge d'approche."""
        mask = alpha > ALPHA_HIT_THRESHOLD
        rows = np.flatnonzero(mask.any(axis=1))
        if rows.size == 0:
            return None
        cols = np.flatnonzero(mask.any(axis=0))
        m = HIT_BBOX_MARGIN
        return (int(cols[0]) - m, int(rows[0]) - m, int(cols[-1]) + m, int(rows[-1]) + m)

    # -- chute et sol --------------------------------------------------------

    def _step_fall(self, dt: float, ph: int) -> None:
        if self._dragging or not self._falling:
            return

        mon = self.current_monitor()
        floor = floor_y(mon.work, ph)

        self._vy += GRAVITY * dt
        self._y += self._vy * dt

        # Composante horizontale. Nulle pour une chute ordinaire — un pet lâché
        # tombe droit —, elle n'est armée que par la sortie du carton, où elle
        # transforme la chute en **bond** : c'est ce qui fait croire que le
        # robot sort de lui-même au lieu d'être découvert sur place.
        if self._vx:
            self._x += self._vx * dt
            self._vx -= self._vx * min(1.0, FALL_DRAG * dt)

        if self._y >= floor:
            self._y = floor
            if abs(self._vy) < REST_VELOCITY:
                self._vy = 0.0
                self._vx = 0.0
                self._falling = False
                self._settle_home()
            else:
                self._vy = -self._vy * RESTITUTION

        # Reste dans la zone de travail horizontalement.
        wl, _, ww, _ = mon.work
        _, _, pw, _ = self._pet_rect()
        self._x = max(float(wl), min(float(wl + ww - pw), self._x))

        self._apply_position()
        self.clock.poke()                       # une chute est du mouvement visible

    def _step_locomotion(self, dt: float, now: float,
                         pw: int, ph: int) -> None:
        """Avance la locomotion, et lui cède la position quand elle voyage.

        **Propriété de la position, une seule à la fois** : le glisser et la
        chute du lot L1 l'emportent toujours, la locomotion ne prend la main
        qu'au repos. Sans cette règle, tirer le pet pendant qu'il marche
        donnerait deux écritures contradictoires par image.
        """
        self._loco_channels = {}
        loco = self.locomotion
        if loco is None:
            return

        # Propriété de la position : le glisser, la chute, le panneau ouvert et
        # la scène d'arrivée l'emportent tous sur la locomotion.
        if (self._dragging or self._falling or self.panel_open
                or self._intro_phase in INTRO_SCRIPTED):
            loco.yield_to_user(self._x + pw / 2.0)
            return

        self._loco_channels = loco.update(dt)
        if loco.travelling or abs(loco.window_y - self._y) > 0.5:
            self._x = loco.window_x
            self._y = loco.window_y
            self._apply_position()

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
        tau = BUBBLE_FADE_IN if cible > self._bubble_opacity else BUBBLE_FADE_OUT
        self._bubble_opacity += (cible - self._bubble_opacity) * min(
            1.0, dt / max(1e-3, tau))

        scene = self.scene
        if scene is None:
            return
        scene.bubble_glyph = glyph_id(
            "question" if self._bubble_want == "question"
            else GLYPH_FOR_NEED.get(self._bubble_want, ""))
        scene.bubble_opacity = self._bubble_opacity
        scene.bubble_scale = self._bubble_opacity
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

    # -- cadence (correctif d'après-lot L6) ----------------------------------

    def _wants_frames(self) -> bool:
        """Le pet fait-il quelque chose de visible, curseur ou pas ?

        **Correctif d'un défaut de conception du lot L1.** L'horloge adaptative
        du §3 était sollicitée par une seule chose : le curseur entrant dans la
        boîte du pet. C'était juste quand le pet ne bougeait *que* si on le
        tirait. Depuis les lots L5b et L6 il se déplace tout seul, et
        « le curseur est loin » ne veut plus dire « rien ne se passe » — c'est
        même l'inverse, ses mouvements les plus spectaculaires ont lieu quand on
        ne le survole pas. Mesuré avant correctif : 1 200 px de trajet et une
        traversée d'écran, intégralement à 9 fps.

        Le critère est le **mouvement effectif**, pas la cause : comparer la
        position arrondie d'une image à l'autre couvre d'un coup le glisser, la
        chute, la flânerie et l'arc du saut, sans avoir à énumérer les sources.
        S'y ajoutent les mouvements qui ne déplacent pas la fenêtre — une courbe
        d'animation **en train de progresser**, ce qui n'est pas la même chose
        qu'une action chargée : une pose soutenue comme le sommeil ne bouge plus
        — et les fondus de l'interface.

        La respiration et les clignements de la couche idle, eux, ne sollicitent
        rien : le §3 fixe explicitement 10 fps pour le repos, et c'est là qu'ils
        vivent.

        Le régime idle reste donc pour un pet réellement immobile, ce que le §3
        exige pour l'autonomie.
        """
        if self._dragging or self._falling or self.panel_open:
            return True
        if self._intro_phase in INTRO_SCRIPTED:
            return True
        if (self.item is not None
                and self.item.state in ("falling", "held", "consumed",
                                        "expiring")):
            return True

        position = (round(self._x), round(self._y))
        bouge = self._frame_pos is not None and position != self._frame_pos
        self._frame_pos = position
        if bouge:
            return True

        loco = self.locomotion
        if loco is not None and loco.travelling:
            return True
        if self.animator is not None and self.animator.action.animating:
            return True
        # Fondus en cours. Aux extrêmes il n'y a plus de transition à lisser :
        # une bulle posée respire assez lentement pour se contenter de 10 fps.
        if 0.01 < self._bubble_opacity < 0.99:
            return True
        if 0.01 < self._eye_mix < 0.99:
            return True
        return False

    # -- objets de soin ------------------------------------------------------

    @property
    def item_pending(self) -> bool:
        return self.item is not None and not self.item.gone

    def _spawn_item(self, kind: str) -> bool:
        """Fait apparaître un objet de soin au sol, près du pet.

        Le délai du soin est posé **ici**, à l'apparition, et non à la
        consommation : sans cela rien n'empêcherait de semer dix gamelles. S'il
        n'est jamais rejoint, l'objet s'évapore et le délai est remboursé — le
        §12 interdit de punir.
        """
        if self.item_pending or not self.session.start_care(kind):
            return False

        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        cote_logique = max(24, int(round(SIZE_RATIO * ph / dpr)))
        cote_physique = cote_logique * dpr

        item = ItemWindow(kind, self._picker.pick(kind), cote_logique)
        mon = self.current_monitor()
        sol = floor_y(mon.work, int(cote_physique))

        # Côté choisi sur la place disponible, distance tirée dans la fourchette.
        wl, _, ww, _ = mon.work
        centre = self._x + pw / 2.0
        ecart = self._picker._rng.uniform(ITEM_SPAWN_MIN, ITEM_SPAWN_MAX) * pw
        cible = centre + (-ecart if centre > wl + ww / 2.0 else ecart)
        cible = max(float(wl), min(float(wl + ww - cote_physique), cible))

        item.show()
        item.place(cible - cote_physique / 2.0,
                   sol - ITEM_DROP_HEIGHT * cote_physique)
        self.item = item
        self._sync_panel_items()
        self.clock.poke()
        log.info("objet de soin : %s", kind)
        if self.diag:
            print(f"[diag] objet {kind} en x={cible:.0f}", flush=True)
        return True

    def _step_item(self, dt: float) -> None:
        """Avance l'objet, et déclenche le soin quand les deux se rejoignent.

        **Un seul test pour les trois façons de les réunir** : que le robot y
        soit allé, qu'on l'y ait porté, ou qu'on ait traîné l'objet jusqu'à lui,
        c'est la même distance entre les deux centres qui décide.
        """
        item = self.item
        if item is None:
            return
        if item.gone:
            self.item = None
            self._sync_panel_items()
            return

        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        sol = floor_y(self.current_monitor().work, int(item.side * dpr))

        if item.state == "expiring":
            if item.expire_step(dt):
                if item.gone:
                    # Jamais rejoint : on rend le délai plutôt que de le faire
                    # payer, et le bouton redevient disponible.
                    self.session.refund_care(item.kind)
                    log.info("objet %s évaporé, délai rendu", item.kind)
            return

        item.step(dt, sol)

        if item.eaten or item.state in ("consumed", "expiring"):
            return

        ix, iy = item.center(dpr)
        px = self._x + pw / 2.0
        py = self._y + ph / 2.0
        if math.hypot(ix - px, iy - py) <= REACH * pw:
            self._consume_item(item)

    def _consume_item(self, item: ItemWindow) -> None:
        if not item.consume():
            return
        applied = self.session.deliver_care(item.kind)
        if applied:
            self._celebrate_care(item.kind, applied)
        if self.locomotion is not None:
            self.locomotion.stop()

    def _sync_panel_items(self) -> None:
        """Tient le panneau au courant : un soin par objet n'est offert que
        si le bureau est libre. Le panneau ne surveille rien de lui-même —
        c'est la fenêtre qui a la boucle de rendu."""
        panel = self.panel
        if panel is None:
            return
        if panel.item_pending != self.item_pending:
            panel.item_pending = self.item_pending
            panel.update()

    def _close_item(self) -> None:
        if self.item is not None:
            self.item.close()
            self.item = None

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
        panel.show()

    # -- panneau de soin (lot L6 phase B) ------------------------------------

    @property
    def panel_open(self) -> bool:
        return self.panel is not None and self.panel.isVisible()

    def _ensure_panel(self) -> CarePanel:
        if self.panel is None:
            self.panel = CarePanel(self.session, self.genome)
            self.panel.care_requested.connect(self._on_care)
            self.panel.quit_requested.connect(self.quit_requested.emit)
            self.panel.name_submitted.connect(self._on_name)
            self.panel.appearance_chosen.connect(self._on_appearance)
            self.panel.item_chosen.connect(self._on_cosmetic)
            self.panel.reset_requested.connect(self._on_reset)
            self.panel.autostart_toggled.connect(self._on_autostart)
            self.panel.item_preview = self.cosmetic_preview
        return self.panel

    def toggle_panel(self) -> None:
        # Tant que le robot n'a pas de nom, le clic droit ne donne rien : le
        # menu de soin parlerait d'un pet qu'on n'a pas encore accueilli, et il
        # détournerait de la seule chose à faire — le baptiser.
        if self._onboarding:
            return
        if self.panel_open:
            self.panel.hide()
            return
        panel = self._ensure_panel()
        panel.item_pending = self.item_pending
        panel.open_page("menu")
        self.place_panel()
        panel.show()
        # Le pet cesse de flâner tant qu'on s'occupe de lui : un panneau qui
        # court après un robot en mouvement serait illisible, et rester tranquille
        # quand on le regarde est de toute façon ce qu'il ferait.
        self.clock.poke()

    def place_panel(self) -> None:
        """Centre le panneau au-dessus de la tête du pet.

        **Seul point du projet qui franchit la frontière des deux espaces de
        coordonnées.** Le pet vit en pixels physiques de bout en bout ; le
        panneau est un widget Qt ordinaire, donc en pixels logiques. La
        conversion se fait ici, une fois, par le rapport mesuré entre les deux.
        """
        panel = self.panel
        if panel is None:
            return
        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        # Le haut du pet visible n'est pas le haut de la fenêtre : le bandeau de
        # la bulle est transparent, et le panneau doit se poser sur la tête.
        bandeau = ph * self.scene.headroom if self.scene is not None else 0.0
        haut_logique = (self._y + bandeau) / dpr
        cx = (self._x + pw / 2.0) / dpr
        panel.move(int(cx - panel.width() / 2.0),
                   int(haut_logique - panel.height() - PANEL_GAP))

    def _on_care(self, kind: str) -> None:
        """Un bouton de soin a été pressé.

        Deux chemins, et c'est la seule branche du mécanisme : la caresse agit
        tout de suite, les trois autres **font apparaître un objet** et
        n'agissent qu'une fois le robot et l'objet réunis.
        """
        if kind in ITEM_KINDS:
            self._spawn_item(kind)
            return
        applied = self.session.care(kind)
        if not applied:
            return
        self._celebrate_care(kind, applied)

    def _celebrate_care(self, kind: str, applied: dict) -> None:
        # Token versé ici, c'est-à-dire à la **livraison** du soin et non au
        # clic du bouton (§14). Depuis que trois soins sur quatre passent par un
        # objet posé sur le bureau, créditer au bouton laisserait faire
        # apparaître dix gamelles sans jamais en livrer une.
        gagne = self.session.award_tokens()

        # Le `brain` élira `happy_bounce` au prochain tick ; la courbe est jouée
        # tout de suite, pour que le geste ait une réponse immédiate.
        if self.animator is not None:
            self.animator.play("celebrate")
        besoin = max(applied, key=lambda k: abs(applied[k]))
        self.show_in_eyes(besoin, besoin, seconds=1.6)
        self.clock.poke()
        if self.panel is not None:
            self.panel.update()
        if self.diag:
            print(f"[diag] token +{gagne} -> {self.session.tokens}", flush=True)
        if self.diag:
            print(f"[diag] soin {kind} -> {applied}", flush=True)

    def _on_appearance(self, param: str, value: str) -> None:
        """Applique un choix de couleur, et le montre tout de suite.

        Le robot est **reconstruit** plutôt que recoloré à chaud. La couleur du
        corps et l'accent traversent la géométrie — teinte des parties, couleur
        des pupilles, configuration de la passe toon — et les retoucher une par
        une reviendrait à recopier `build`. Elle coûte 7 ms mesurées, une fois
        par clic : c'est gratuit à cette échelle.
        """
        if not self.session.set_appearance(param, value):
            return
        self._rebuild_robot()
        log.info("apparence : %s = %s", param, value)

    def _on_cosmetic(self, slot: str, key: str) -> None:
        """Un article a été touché : on l'achète, ou on le porte.

        **Un seul geste pour les deux**, et c'est volontaire : appuyer sur un
        article qu'on ne possède pas l'achète et le met aussitôt, appuyer sur un
        article possédé le porte. Séparer « acheter » de « porter » aurait
        demandé deux boutons par vignette, donc deux pictogrammes de plus à
        distinguer pour rien.
        """
        from ..geometry.cosmetics import NONE

        if key != NONE and not self.session.owns(key):
            if not self.session.buy(key):
                return
            if self.diag:
                print(f"[diag] achat {key} -> solde {self.session.tokens}",
                      flush=True)
        if not self.session.wear(slot, key):
            return
        self._rebuild_robot()
        if self.panel is not None:
            self.panel.update()
        log.info("%s : %s", slot, key or "aucun")

    def _on_autostart(self) -> None:
        """Bascule le lancement au démarrage (§13)."""
        actif = not win32.autostart_enabled()
        if win32.set_autostart(actif):
            log.info("lancement au démarrage : %s", "oui" if actif else "non")
        if self.panel is not None:
            self.panel.update()

    def _on_reset(self) -> None:
        """Purge tout et quitte. Le §13 demande un bouton, le voici.

        **Tout** : besoins, nom, génome, tokens, inventaire, réglages. Une
        réinitialisation partielle n'en serait pas une, et le §13 parle de purge
        des données. L'application se ferme derrière : recréer un robot dans une
        session qui porte encore l'ancien en mémoire serait une source de bugs
        pour un geste qui arrive une fois dans la vie du produit.
        """
        from ..state import save

        if self.panel is not None:
            self.panel.hide()
        log.info("réinitialisation demandée")
        try:
            self.session.flush(force=False)
        except OSError:
            pass
        self._purge_on_exit = True
        self.quit_requested.emit()

    def _rebuild_robot(self) -> None:
        """Reconstruit le robot avec son costume courant, et le réanime.

        Partagé par le changement de couleur et celui de chapeau : les deux
        passent par `overrides`, donc ils ont exactement le même effet.
        """
        if self.scene is None:
            return
        self.robot = build(self.genome, self.session.appearance)
        self.scene.set_robot(self.robot)
        if self.animator is not None:
            self.animator = Animator.for_robot(
                self.robot, seed=int(self.genome.get("seed", 0)))
        self._hat_previews.clear()
        self.clock.poke()

    def cosmetic_preview(self, slot: str, key: str):
        """Aperçu d'un article, rendu **sur le robot de l'utilisateur**.

        Rendu une fois puis gardé : huit vignettes coûtent huit reconstructions
        de maillage, soit une soixantaine de millisecondes à l'ouverture du
        rayon, et rien ensuite. Le cache est vidé dès que l'apparence change,
        sinon les aperçus montreraient l'ancienne couleur.

        Le robot réel est **remis en place** à la fin : la scène n'a qu'un
        maillage à la fois, et le laisser sur le dernier chapeau essayé
        remplacerait le pet à l'écran.
        """
        from PySide6.QtGui import QPixmap

        if self.scene is None or self.robot is None:
            return None
        cache_key = slot + ":" + key
        if cache_key in self._hat_previews:
            return self._hat_previews[cache_key]

        # Les **autres** emplacements gardent ce qui est porté : on montre le
        # robot tel qu'il sera, pas l'article seul sur une tête nue.
        costume = dict(self.session.appearance)
        costume[slot] = key
        try:
            self.scene.set_robot(build(self.genome, costume))
            self.rc.begin()
            self.scene.draw(yaw=0.0, pitch=0.14)
            px = self.rc.read_rgba()
            image = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                           QImage.Format.Format_RGBA8888_Premultiplied).copy()
        finally:
            self.scene.set_robot(self.robot)
        pixmap = QPixmap.fromImage(image)
        self._hat_previews[cache_key] = pixmap
        return pixmap

    def _on_name(self, name: str) -> None:
        accepte = self.session.set_name(name)

        # Le baptême se termine dès que le robot **a** un nom, et non dès que
        # celui-ci vient d'être accepté. La nuance est un garde-fou : un refus
        # — nom déjà posé par une autre voie, par exemple — laissait sinon
        # l'utilisateur sans menu contextuel, définitivement, sans rien pour
        # s'en sortir.
        if not self.session.name:
            return
        self._onboarding = False
        self._intro_phase = ""
        if not accepte:
            return
        if self.panel is not None:
            self.panel.hide()
        if self.animator is not None:
            self.animator.play("celebrate")
        self.show_in_eyes("robot", "robot", seconds=2.0)
        log.info("robot baptisé")

    # -- hit-testing ---------------------------------------------------------

    def _on_hit_test(self) -> None:
        cx, cy = win32.get_cursor_pos()
        # Le capteur de curseur est alimenté ici plutôt que par un timer dédié :
        # les deux ont besoin exactement de la même donnée, et un troisième
        # timer coûterait des réveils sans rien apporter (CDC §3, autonomie).
        self.sensors.observe_cursor(time.perf_counter(), (cx, cy))
        left, top, pw, ph = self._pet_rect()
        lx, ly = cx - left, cy - top

        opaque = False
        if self._alpha is not None and 0 <= lx < pw and 0 <= ly < ph:
            ay = min(ly, self._alpha.shape[0] - 1)
            ax = min(lx, self._alpha.shape[1] - 1)
            opaque = bool(self._alpha[ay, ax] > ALPHA_HIT_THRESHOLD)

        # Pendant un glisser, la souris est capturée par Qt : remettre le
        # click-through ferait perdre le suivi dès que le curseur sort de la
        # silhouette, ce qui arrive au premier mouvement rapide.
        win32.set_click_through(self.hwnd, not (opaque or self._dragging))

        near = self._bbox is not None and (
            self._bbox[0] <= lx <= self._bbox[2] and self._bbox[1] <= ly <= self._bbox[3]
        )
        if near:
            self.clock.poke()
        # L'objet suit la même règle que le pet : traversant par défaut, et
        # cliquable seulement là où son sprite est opaque. Piloté par ce timer
        # plutôt que par un timer propre, pour ne pas ajouter de réveil (§3).
        item = self.item
        if item is not None and not item.gone:
            dpr = pw / max(1, self.width())
            sur_objet = item.opaque_at((cx - item.x) / dpr,
                                       (cy - item.y) / dpr)
            win32.set_click_through(int(item.winId()),
                                    not (sur_objet or item.held))

        wanted = 1000 // (HIT_HZ_NEAR if near else HIT_HZ_FAR)
        if self._hit_timer.interval() != wanted:
            self._hit_timer.setInterval(wanted)

    # -- vérifications système -----------------------------------------------

    def _on_system_check(self) -> None:
        """Capteurs à 4 Hz, plein écran et disparition de moniteur (§6, §11)."""
        self.refresh_monitor()
        now = time.perf_counter()

        # Le curseur est normalement échantillonné par le timer de hit-testing,
        # mais celui-ci **s'arrête** quand le pet est masqué. Sans ce relais,
        # `cursor_still_seconds` gelait, et `watching` ne pouvait jamais
        # atteindre ses 6 secondes d'immobilité — précisément pendant une vidéo
        # en plein écran, c'est-à-dire le seul cas qui compte.
        self.sensors.observe_cursor(now)

        # Réaffirmation du rang : le style topmost ne suffit pas à garantir
        # l'ordre Z (cf. win32.assert_topmost).
        if not self._suspended:
            win32.assert_topmost(self.hwnd)

        self.sensors.observe_slow(now, own_hwnd=self.hwnd)
        self._tick_brain(now)

        # Journalisé au **changement d'état** seulement, et sous forme expurgée :
        # le journal ne doit contenir que des catégories (CDC §11).
        context = self.sensors.context
        if context.state != self._last_state:
            self._last_state = context.state
            log.info("contexte %s", context.redacted())
        fullscreen_on = win32.foreground_fullscreen_monitor(self.hwnd)

        # On ne se masque que si le plein écran couvre *notre* écran : une vidéo
        # en plein écran sur le second moniteur ne doit pas faire disparaître le
        # pet resté sur le premier.
        if fullscreen_on is not None and (
            not self._monitor_key or fullscreen_on.key == self._monitor_key
        ):
            self.clock.set_suspended(True)
            return
        self.clock.set_suspended(False)

        if self._suspended:
            return

        keys = {m.key for m in win32.list_monitors()}
        if self._monitor_key and self._monitor_key not in keys:
            log.info("moniteur courant disparu, recalage")
            self.restore_position()
            self._rebuild_terrain()

    def _on_autosave(self) -> None:
        if self.settings.save():
            log.debug("réglages sauvegardés")

    # -- interaction ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.button() == Qt.MouseButton.RightButton:
            self.toggle_panel()
            return

        # Clic sur la bulle : elle n'attrape pas le pet, elle parle. Testé
        # avant le glisser, sinon un clic sur la bulle emmènerait le robot.
        if self.scene is not None:
            left, top, pw, ph = self._pet_rect()
            cx, cy = win32.get_cursor_pos()
            if self.scene.bubble_hit((cx - left, cy - top)):
                if self._onboarding:
                    self.ask_for_name()
                else:
                    besoin = self._bubble_want
                    sigle = GLYPH_FOR_NEED.get(besoin, "question")
                    self.show_in_eyes(sigle, sigle)
                if self.diag:
                    print(f"[diag] bulle cliquée : "
                          f"{self._bubble_want}", flush=True)
                return

        self._clicks += 1
        self._pulse = 1.0
        self._dragging = True
        # Le `brain` élit `react_to_poke`, qui rejouera la courbe par le plan.
        # Elle est lancée ici quand même : le tick n'arrive que 250 ms plus tard
        # et une réaction au clic en retard d'un quart de seconde se voit.
        self.brain.poke()
        if self.animator is not None:
            self.animator.play("poke_reaction")
        self._falling = False
        self._vy = 0.0
        self._drag_cursor0 = win32.get_cursor_pos()
        self._drag_origin0 = (self._x, self._y)
        self.clock.poke()

        if win32.get_foreground_window() == self.hwnd:
            self._focus_stolen = True
        if self.diag:
            print(f"[diag] clic capté #{self._clicks} - focus volé : {self._focus_stolen}",
                  flush=True)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if not self._dragging:
            return
        # Delta calculé en physique depuis le curseur, pas depuis les positions
        # logiques de l'évènement Qt : un glisser d'un écran à l'autre reste
        # juste même si leurs facteurs d'échelle diffèrent.
        cx, cy = win32.get_cursor_pos()
        self._x = self._drag_origin0[0] + (cx - self._drag_cursor0[0])
        self._y = self._drag_origin0[1] + (cy - self._drag_cursor0[1])
        self._apply_position()
        self.clock.poke()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if not self._dragging:
            return
        self._dragging = False

        _, _, pw, ph = self._pet_rect()
        mon = self.refresh_monitor()
        if self._y < floor_y(mon.work, ph) - 1:
            self._falling = True                # il retombe (CDC §6)
            self._vy = 0.0
        else:
            self._y = floor_y(mon.work, ph)
            self._apply_position()
            self._settle_home()
        self.clock.poke()

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

    def shutdown(self) -> None:
        self._close_item()
        if self.panel is not None:
            self.panel.close()
        # Enregistrement de l'état vivant avant tout le reste : le §14 demande
        # une écriture à la fermeture propre, et elle ne doit pas dépendre de la
        # bonne fin des libérations GPU qui suivent.
        try:
            self.session.flush(force=True)
        except OSError as exc:
            log.warning("état non enregistré : %s", type(exc).__name__)

        """Arrêt propre : sauvegarde puis libération du contexte GL."""
        self.clock.stop()
        self._hit_timer.stop()
        self._system_timer.stop()
        self._autosave_timer.stop()
        self._diag_timer.stop()
        try:
            self.remember_position()
            self.settings.save()
        except Exception:                        # noqa: BLE001
            log.exception("échec de la sauvegarde à la fermeture")
        if self.scene is not None:
            self.scene.release()
            self.scene = None
        if self.rc is not None:
            self._qimage = None
            self._frame = None
            self._alpha = None
            self.rc.release()
            self.rc = None

    def closeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self.shutdown()
        super().closeEvent(event)
