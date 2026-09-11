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
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from ..anim.curiosity import CuriousGaze
from ..anim.easing import Spring
from ..anim.impact import Impact
from ..anim.layers import AnimContext, Animator
from ..anim.locomotion import Locomotion, Terrain
from ..brain.session import Session
from ..brain.sensors import Sensors
from ..brain.utility import Plan, SelfState
from ..feedback import bus
from ..geometry.builder import Robot, build
from ..render.context import RenderContext
from ..render.glyphs import GLYPH_FOR_NEED
from ..render.scene import Scene
from ..ui.item import ItemWindow, SpritePicker
from ..ui import sparks
from ..ui.dust import ParticleWindow
from ..ui.panel import CarePanel
from ..state.save import Store
from . import win32
from .clock import Regime, RenderClock
# Réexportées : elles ont changé de fichier, pas de sens, et c'est de ce
# module que les tests les importent depuis le lot L1.
from .ground import (                                           # noqa: F401
    choose_monitor, floor_y, frac_to_position, position_to_frac,
)
from .parts import (BehaviourMixin, CareMixin, DiagnosticsMixin, ItemsMixin,
                    OnboardingMixin)
from .parts.behaviour import BUBBLE_POP_OMEGA, BUBBLE_POP_ZETA
# Réexportées : elles vivent désormais avec le code qui les utilise, mais
# `INTRO_SCRIPTED` est lue par les tests depuis ce module, et rien ne justifie
# de leur faire suivre un déménagement interne.
from .parts.onboarding import (                                    # noqa: F401
    INTRO_SCRIPTED, LEAP_VX, LEAP_VY, LOOK_SECONDS, SETTLE_SECONDS,
    SURPRISE_SECONDS, SURPRISE_VY,
)

log = logging.getLogger("desky.window")



# Durée d'affichage par les yeux après un clic sur la bulle. Assez long pour
# être lu sans avoir à se dépêcher, assez court pour que le pet redevienne



# Actions pendant lesquelles le pet est réputé curieux. Les trois partagent
# déjà l'expression `curieux` ; la liste est explicite pour que le regard ne
# dépende pas d'un détail d'expression qui pourrait changer.
CURIOUS_ACTIONS = frozenset({"sniff_around", "look_around", "idle_wander"})

# Fréquence de relecture de la fenêtre de premier plan, en secondes. `GetWindowRect`
# est bon marché mais il n'a aucune raison d'être appelé à chaque image : une
# fenêtre ne se déplace pas trente fois par seconde.
FOREGROUND_REFRESH = 0.5


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

# Intervalle entre deux « Z » de sommeil (lot L11). Long : un robot qui dort ne
# doit surtout pas attirer l'attention, et une lettre toutes les deux secondes
# suffit à dire qu'il dort sans le rendre bavard.
SLEEP_Z_PERIOD = 2.3

# Chute vers le sol. Une parabole plutôt qu'une interpolation linéaire, avec un
# rebond amorti : le CDC §10 interdit toute interpolation linéaire sur un
# mouvement visible, et cette exigence vaut dès qu'un mouvement existe. Les
# couches d'animation à ressorts du lot L4 remplaceront cette intégration ad hoc.
GRAVITY = 2600.0              # px/s²
RESTITUTION = 0.28            # part de vitesse conservée au rebond
REST_VELOCITY = 45.0          # px/s en dessous desquels on considère posé
FALL_DRAG = 1.1               # amortissement de la composante horizontale





class PetWindow(BehaviourMixin, ItemsMixin, OnboardingMixin, CareMixin,
                DiagnosticsMixin, QWidget):
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
        # L'échelle de la bulle est un **ressort**, pas un fondu (lot L9). Elle
        # arrive en dépassant sa taille puis se pose : c'est l'arrivée que le
        # §10 demande, et c'est ce qui distingue une bulle qui « pop » d'une
        # bulle qui se contente d'apparaître.
        #
        # Sous-amorti à l'aller, critique au retour. Un ressort sous-amorti
        # ramené à zéro passe **sous** zéro, c'est-à-dire une échelle négative :
        # la bulle se retournerait un instant avant de disparaître.
        self._bubble_scale = Spring(0.0, omega=BUBBLE_POP_OMEGA,
                                    zeta=BUBBLE_POP_ZETA)
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
        # Poids du robot : encaissement, rebond, étirement en vol (lot L10).
        # Remplace un `_pulse` qui décroissait d'un facteur fixe **par image**,
        # donc trois fois plus lentement en temps réel à 10 fps qu'à 30 : le pet
        # réagissait au clic d'autant plus mollement qu'il était occupé.
        self._impact = Impact()

        # Particules (lot L11). Dans **leur propre fenêtre**, pas dans celle
        # du pet : ici elles suivraient ses rebonds et seraient coupées à ses
        # pieds. Voir `ui/dust`. Construite au premier effet, comme le panneau.
        self.dust: ParticleWindow | None = None
        self._sleep_t = 0.0
        self._abonnements: list[tuple[str, object]] = []
        self._subscribe_effects()
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

        self._impact.step(dt)
        self._step_particles(dt)
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
            # Les canaux d'impact **s'ajoutent** à ceux de la locomotion, ils
            # ne les remplacent pas : les deux écrivent `body.flex`, et un saut
            # qui atterrit doit cumuler son écrasement de démarche et son
            # encaissement de choc.
            extra = dict(self._loco_channels)
            for nom, valeur in self._impact.channels().items():
                extra[nom] = extra.get(nom, 0.0) + valeur
            self.animator.update(dt, self._anim_context(pw, ph), extra=extra)
            self.scene.face_state = self.animator.face

        # Cadence : sollicitée par ce que le pet **fait**, et non plus seulement
        # par la proximité du curseur (cf. `_wants_frames`).
        if self._wants_frames():
            self.clock.poke()

        mon = self.current_monitor()
        lift = max(0.0, floor_y(mon.work, ph) - self._y) / max(1.0, ph)

        self.rc.begin()
        # L'échelle globale reste à 1 : la réaction au clic passe désormais
        # par `body.flex`, donc par le rig. Un agrandissement uniforme du robot
        # entier grossissait aussi sa tête et son contour — ce n'était pas une
        # réaction, c'était un zoom.
        self.scene.draw(yaw=self._yaw, pitch=0.16,
                        scale=1.0, time_s=t, lift=lift)
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

        # Étirement en vol : le corps s'allonge dans l'axe de son mouvement,
        # et cesse de s'allonger dès qu'il ralentit. Posé avant le test du sol
        # pour que la dernière image de chute soit encore étirée — c'est le
        # contraste avec l'écrasement qui suit qui donne le choc.
        self._impact.set_flight(self._vy)

        if self._y >= floor:
            self._y = floor
            arrivee = abs(self._vy)
            force = self._impact.land(arrivee)
            if force:
                # Le fait, pas l'effet : c'est de là que partiront la poussière
                # du lot Particules et le son du lot Sons, chacun dosé par la
                # même force.
                bus.emit("atterri", force=force, vitesse=arrivee)
            if abs(self._vy) < REST_VELOCITY:
                self._vy = 0.0
                self._vx = 0.0
                self._falling = False
                self._impact.set_flight(0.0)
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

    # -- particules (lot L11) -------------------------------------------------

    def _subscribe_effects(self) -> None:
        """Branche les gerbes sur les faits du bus.

        Un abonnement plutôt qu'un appel direct depuis `_step_fall` : ajouter
        un effet à un fait existant ne demande alors de toucher ni la chute, ni
        le soin, ni l'achat. C'est précisément ce pour quoi le bus a été posé au
        lot L9, et c'est le lot Sons qui en profitera ensuite sans rien modifier
        de ce fichier.

        Les abonnements sont **mémorisés** pour être retirés à la fermeture : le
        bus est un objet de service qui survit à la fenêtre, et une fenêtre
        détruite qui continue d'y répondre peindrait dans un widget mort — un
        défaut qui ne se manifeste qu'en test, là où l'on crée des dizaines de
        fenêtres, mais qui s'y manifeste à coup sûr.
        """
        for nom, fonction in (("atterri", self._on_landed),
                              ("soin_accepte", self._on_care_sparks),
                              ("achat_refuse", self._on_refusal)):
            bus.subscribe(nom, fonction)
            self._abonnements.append((nom, fonction))

    def _unsubscribe_effects(self) -> None:
        for nom, fonction in self._abonnements:
            bus.unsubscribe(nom, fonction)
        self._abonnements.clear()

    def _ensure_dust(self) -> ParticleWindow:
        """Le calque, créé au premier effet et recentré sur le pet.

        Recentré **ici** et non à chaque image : `reframe` ne fait rien tant
        qu'une particule vit, donc le calque se replace entre deux gerbes et
        jamais pendant. Une fenêtre qui glisse sous une gerbe en cours la
        rognerait par un bord mouvant.
        """
        if self.dust is None:
            self.dust = ParticleWindow()
        _, _, pw, _ = self._pet_rect()
        self.dust.reframe(self._pet_rect(), pw / max(1, self.width()))
        return self.dust

    def _on_landed(self, force: float, vitesse: float) -> None:
        sparks.landing_dust(self._ensure_dust().banc, force, self._pet_rect())

    def _on_care_sparks(self, soin: str) -> None:
        sparks.care_sparks(self._ensure_dust().banc, self._pet_rect())

    def _on_refusal(self, emplacement: str, cle: str, raison: str) -> None:
        sparks.refusal_puff(self._ensure_dust().banc, self._pet_rect())

    def _step_particles(self, dt: float) -> None:
        """Avance le calque, et laisse tomber un « Z » quand le pet dort.

        Le sommeil est le seul effet **continu** du lot : il n'a pas de fait
        déclencheur, c'est un état. D'où l'émission au compte-gouttes ici plutôt
        qu'un abonnement — et un intervalle long, parce qu'un robot qui dort ne
        doit surtout pas attirer l'attention.
        """
        if self._plan.action == "nap" and not self._dragging:
            self._sleep_t += dt
            if self._sleep_t >= SLEEP_Z_PERIOD:
                self._sleep_t = 0.0
                sparks.sleep_z(self._ensure_dust().banc, self._pet_rect())
        else:
            self._sleep_t = SLEEP_Z_PERIOD * 0.6

        if self.dust is not None:
            _, _, _, ph = self._pet_rect()
            # Le sol que la poussière ne doit pas traverser est celui sur
            # lequel le robot se tient : une seule définition, et c'est déjà
            # celle qu'utilise la chute.
            sol = floor_y(self.current_monitor().work, ph) + ph
            self.dust.step(dt, float(ph), sol)

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
        # Un encaissement en cours ne déplace pas la fenêtre — il déforme le
        # corps sur place. Sans cette ligne, le rebond d'un atterrissage se
        # jouerait à 10 fps, c'est-à-dire par paliers, juste après la chute qui,
        # elle, tournait à 30.
        if not self._impact.settled:
            return True
        if self.dust is not None and not self.dust.banc.empty:
            return True
        return False

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
        self._impact.poke()
        bus.emit("pousse")
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

    def shutdown(self) -> None:
        self._unsubscribe_effects()
        if self.dust is not None:
            self.dust.close()
            self.dust = None
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
