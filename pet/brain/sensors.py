"""Capteurs système et dérivation du contexte (CDC §11).

Tous les capteurs sont interrogés par polling et n'exposent au `brain` que des
**agrégats**. Aucun n'installe de hook, aucun ne lit de contenu.

**Les interdictions du §11 sont tenues ici, structurellement :**

- *Aucun hook clavier.* L'activité utilisateur passe exclusivement par
  `GetLastInputInfo`, qui donne l'instant de la dernière entrée sans jamais voir
  ce qui a été tapé. Le CDC §3 l'interdit formellement et un test vérifie
  qu'aucun `SetWindowsHookEx` n'apparaît dans le code.
- *Aucun titre de fenêtre.* On lit le **process** de la fenêtre au premier plan,
  jamais son titre. Le titre est précisément ce qui contient les noms de
  documents et les URL.
- *Rien de sensible sur disque.* `SystemContext.redacted()` est la seule forme
  autorisée à sortir vers le journal : elle ne contient que des catégories, des
  booléens et des nombres. Un test relit le journal pour s'en assurer.

**Cadences.** Le §11 prescrit 4 Hz pour les capteurs et 60 Hz pour le curseur.
Le curseur est échantillonné par le timer de hit-testing de la fenêtre, qui
oscille déjà entre 8 et 60 Hz selon la proximité du pet : les deux ont besoin
exactement de la même donnée, et ajouter un troisième timer coûterait des
réveils pour rien — ce qui compte pour l'autonomie (CDC §3). Le 60 Hz est donc
tenu là où il sert, quand le curseur est près du pet.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..app import win32

log = logging.getLogger("desky.sensors")

# --- Catégories de process (CDC §11, extensible par fichier de config) ------

CATEGORIES: tuple[str, ...] = ("dev", "browser", "media", "game", "office",
                               "shell", "other")

DEFAULT_PROCESSES: dict[str, tuple[str, ...]] = {
    "dev": (
        "code.exe", "devenv.exe", "pycharm64.exe", "idea64.exe", "rider64.exe",
        "clion64.exe", "webstorm64.exe", "sublime_text.exe", "notepad++.exe",
        "windowsterminal.exe", "wt.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
        "mintty.exe", "bash.exe", "git-bash.exe", "conemu64.exe", "alacritty.exe",
        "claude.exe", "cursor.exe", "godot.exe", "unity.exe", "unrealeditor.exe",
        "blender.exe", "docker desktop.exe",
    ),
    "browser": (
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
        "operagx.exe", "vivaldi.exe", "chromium.exe", "iexplore.exe",
    ),
    "media": (
        "vlc.exe", "mpv.exe", "mpc-hc.exe", "mpc-hc64.exe", "mpc-be64.exe",
        "potplayermini64.exe", "potplayermini.exe", "wmplayer.exe",
        "video.ui.exe", "movies & tv.exe", "spotify.exe", "itunes.exe",
        "музыка.exe", "music.ui.exe", "foobar2000.exe", "aimp.exe",
        "deezer.exe", "tidal.exe", "audacity.exe", "obs64.exe",
    ),
    "game": (
        "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
        "battle.net.exe", "riotclientux.exe", "leagueclient.exe",
        "goggalaxy.exe", "eadesktop.exe", "ubisoftconnect.exe",
    ),
    "office": (
        "winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe",
        "onenote.exe", "msaccess.exe", "teams.exe", "ms-teams.exe",
        "slack.exe", "discord.exe", "notion.exe", "obsidian.exe",
        "acrobat.exe", "acrord32.exe", "thunderbird.exe", "zoom.exe",
    ),
    "shell": (
        "explorer.exe", "searchhost.exe", "searchapp.exe",
        "startmenuexperiencehost.exe", "shellexperiencehost.exe",
        "applicationframehost.exe", "dwm.exe", "lockapp.exe",
        "taskmgr.exe", "systemsettings.exe",
    ),
}

# Sources dont un son signale une **vidéo**. C'est la moitié utile de la
# décision `watching` : le §11 ne peut pas la déduire de l'audio seul, puisque
# WASAPI ne dit pas si un flux est une vidéo.
VIDEO_SOURCES: frozenset[str] = frozenset({
    "vlc.exe", "mpv.exe", "mpc-hc.exe", "mpc-hc64.exe", "mpc-be64.exe",
    "potplayermini64.exe", "potplayermini.exe", "wmplayer.exe",
    "video.ui.exe", "movies & tv.exe",
})

# Sources dont un son ne signale **jamais** une vidéo : un lecteur de musique
# tourne en fond pendant qu'on travaille, et ne doit pas faire asseoir le pet.
AUDIO_ONLY_SOURCES: frozenset[str] = frozenset({
    "spotify.exe", "itunes.exe", "foobar2000.exe", "aimp.exe", "deezer.exe",
    "tidal.exe", "music.ui.exe", "musique.exe",
})

# Hôtes de fenêtres UWP. Une application du Store — « Films et TV » par
# exemple — voit son process réel masqué derrière l'un de ces hôtes : le PID de
# la fenêtre au premier plan est celui de l'hôte, pas celui du lecteur. Le
# rapprochement par nom est alors impossible, et on retombe sur la liste des
# lecteurs vidéo connus.
UWP_HOSTS: frozenset[str] = frozenset({
    "applicationframehost.exe", "windowsapps.exe",
})

# Nom du fichier de configuration, dans le répertoire de données.
PROCESS_CONFIG = "processes.json"


# --- Seuils de dérivation (CDC §11) -----------------------------------------

IDLE_SECONDS = 90.0             # au-delà : idle
AWAY_SECONDS = 600.0            # au-delà : away
# Durée de son continu exigée avant de conclure à un visionnage.
#
# **Écart assumé au §11**, qui écrit « plus de 20 s ». Ces 20 s devaient filtrer
# les sons transitoires — notification, pub, scrub dans une timeline. Mais la
# condition « la source du son est l'application au premier plan », ajoutée après
# sondage du système réel, fait déjà ce travail : une notification vient d'un
# process en arrière-plan et se trouve donc déjà exclue.
#
# À 20 s, la réaction du pet n'était plus rattachable au fait d'avoir lancé une
# vidéo, et le comportement devenait invisible. À 8 s elle reste délibérée sans
# être imperceptible. Remettre 20.0 restaure le texte du CDC à l'identique.
WATCH_MEDIA_SECONDS = 8.0

# Curseur immobile. Court en parallèle du seuil ci-dessus, donc la latence
# effective est le maximum des deux, pas leur somme.
WATCH_STILL_SECONDS = 6.0

# Un navigateur qui émet du son est ambigu : ce peut être une vidéo ou de la
# musique. On tranche sur la surface occupée — une vidéo se regarde en grand.
WATCH_COVERAGE = 0.60

# Déplacement au-delà duquel le curseur est considéré comme bougeant, en pixels.
CURSOR_MOVE_EPS = 3.0

# Un pic audio isolé ne suffit pas, et un silence de dialogue ne doit pas
# réinitialiser le compteur : la lecture est considérée continue tant qu'un pic
# a été vu dans cette fenêtre.
AUDIO_STICKY_SECONDS = 3.0
AUDIO_PEAK_THRESHOLD = 0.001

# L'énumération des sessions WASAPI coûte 28,1 ms (mesuré au lot L5) : la faire
# à 4 Hz consommerait 11 % d'un cœur. Les sessions sont donc énumérées
# rarement, et seuls leurs peak meters — 0,21 ms pour cinq sessions — sont lus à
# chaque poll.
SESSION_REFRESH_SECONDS = 8.0


# --- Contexte ---------------------------------------------------------------


@dataclass(frozen=True)
class SystemContext:
    """Agrégats exposés au `brain`. Aucun titre, aucune URL, aucune frappe."""

    state: str = "typing"
    idle_seconds: float = 0.0
    cursor: tuple[int, int] = (0, 0)
    cursor_speed: float = 0.0           # pixels par seconde
    cursor_still_seconds: float = 0.0
    foreground_category: str = "other"
    # Nom du process au premier plan. Présent parce que le §11 le liste comme
    # sortie du capteur, mais **jamais persisté** : seul `redacted()` sort vers
    # le journal, et un test vérifie qu'aucun nom de process n'atteint le disque.
    foreground_process: str = ""
    fullscreen: bool = False
    media_playing: bool = False
    media_category: str = "other"
    media_seconds: float = 0.0

    def redacted(self) -> dict[str, Any]:
        """Forme publiable : catégories, booléens, nombres arrondis.

        C'est la seule représentation autorisée à sortir vers le journal ou vers
        un fichier (CDC §11).
        """
        return {
            "state": self.state,
            "idle_s": round(self.idle_seconds, 1),
            "categorie": self.foreground_category,
            "plein_ecran": self.fullscreen,
            "media": self.media_playing,
            "media_categorie": self.media_category,
            "media_s": round(self.media_seconds, 1),
            "curseur_vitesse": round(self.cursor_speed, 1),
        }


def load_categories(directory=None) -> dict[str, frozenset[str]]:
    """Catégories par défaut, complétées par le fichier de configuration.

    Le §11 demande des listes « extensibles par fichier de config ». Le fichier
    **ajoute** aux défauts et ne les remplace pas : un utilisateur qui déclare
    son éditeur exotique ne doit pas perdre au passage la liste des navigateurs.
    """
    table = {name: set(values) for name, values in DEFAULT_PROCESSES.items()}

    if directory is None:
        from ..state.save import app_dir
        directory = app_dir()

    path = directory / PROCESS_CONFIG
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = None
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("%s illisible, catégories par défaut (%s)",
                    PROCESS_CONFIG, type(exc).__name__)
        raw = None

    if isinstance(raw, dict):
        for category, names in raw.items():
            if category not in CATEGORIES:
                log.warning("catégorie inconnue ignorée dans %s", PROCESS_CONFIG)
                continue
            if isinstance(names, list):
                table.setdefault(category, set()).update(
                    str(n).lower() for n in names if isinstance(n, str))

    return {name: frozenset(values) for name, values in table.items()}


def categorize(process: str, table: dict[str, frozenset[str]]) -> str:
    """Catégorie d'un nom de process. `other` si inconnu."""
    needle = process.lower()
    for category in CATEGORIES:
        if needle in table.get(category, frozenset()):
            return category
    return "other"


# --- Capteurs ---------------------------------------------------------------


class CursorSensor:
    """Position, vitesse et immobilité du curseur (CDC §11)."""

    def __init__(self) -> None:
        self.position = (0, 0)
        self.speed = 0.0
        self.still_seconds = 0.0
        self._last_t: float | None = None

    def observe(self, now: float, position: tuple[int, int] | None = None) -> None:
        if position is None:
            position = win32.get_cursor_pos()

        if self._last_t is None:
            self.position, self._last_t = position, now
            return

        dt = now - self._last_t
        if dt <= 0.0:
            return

        dx = position[0] - self.position[0]
        dy = position[1] - self.position[1]
        distance = (dx * dx + dy * dy) ** 0.5

        self.speed = distance / dt
        if distance > CURSOR_MOVE_EPS:
            self.still_seconds = 0.0
        else:
            self.still_seconds += dt

        self.position = position
        self._last_t = now


class ForegroundSensor:
    """Process et catégorie de la fenêtre au premier plan, plus plein écran.

    Le nom du process est mis en cache par PID : le premier plan change bien
    moins souvent qu'on ne l'interroge, et une interrogation psutil par poll
    serait du gaspillage.
    """

    def __init__(self, table: dict[str, frozenset[str]]) -> None:
        self.table = table
        self.process = ""
        self.category = "other"
        self.fullscreen = False
        self.coverage = 0.0
        self._pid_cache: dict[int, str] = {}

    def observe(self, own_hwnd: int = 0) -> None:
        hwnd = win32.get_foreground_window()
        if not hwnd or hwnd == own_hwnd:
            return

        pid = win32.get_window_process_id(hwnd)
        self.process = self._name_for(pid)
        self.category = categorize(self.process, self.table)

        monitor = win32.foreground_fullscreen_monitor(own_hwnd)
        self.fullscreen = monitor is not None
        self.coverage = self._coverage(hwnd, own_hwnd)

    def _name_for(self, pid: int) -> str:
        if pid <= 0:
            return ""
        cached = self._pid_cache.get(pid)
        if cached is not None:
            return cached

        name = ""
        try:
            import psutil
            name = psutil.Process(pid).name()
        except Exception:                       # noqa: BLE001
            # Process disparu, ou accès refusé sur un process système : ce n'est
            # pas une erreur, seulement une catégorie inconnue.
            name = ""

        # Le cache est borné : un poste qui ouvre et ferme des milliers de
        # process ne doit pas faire grossir la mémoire indéfiniment.
        if len(self._pid_cache) > 256:
            self._pid_cache.clear()
        self._pid_cache[pid] = name
        return name

    @staticmethod
    def _coverage(hwnd: int, own_hwnd: int) -> float:
        """Part du moniteur couverte par la fenêtre, dans [0, 1].

        Sert à trancher le cas ambigu du navigateur qui émet du son : une vidéo
        se regarde en grand, une playlist tourne dans un onglet.
        """
        try:
            left, top, w, h = win32.get_window_rect(hwnd)
            monitor = win32.monitor_from_window(hwnd)
        except Exception:                       # noqa: BLE001
            return 0.0
        _, _, mw, mh = monitor.rect
        if mw <= 0 or mh <= 0 or w <= 0 or h <= 0:
            return 0.0
        return min(1.0, (w * h) / float(mw * mh))


class MediaSensor:
    """Lecture audio par session WASAPI (CDC §11).

    Deux cadences, imposées par la mesure : l'énumération des sessions coûte
    28,1 ms et n'a lieu que toutes les 8 secondes ; la lecture des peak meters
    coûte 0,21 ms et a lieu à chaque poll.
    """

    def __init__(self) -> None:
        self.playing = False
        self.source = ""
        self.seconds = 0.0
        self.available = True
        self._meters: list[tuple[Any, Any]] = []
        self._enumerated_at: float | None = None
        self._last_peak_at: float | None = None
        self._started_at: float | None = None

    def observe(self, now: float) -> None:
        if not self.available:
            return

        if (self._enumerated_at is None
                or now - self._enumerated_at >= SESSION_REFRESH_SECONDS):
            self._enumerate()
            self._enumerated_at = now

        loud, source = self._read_peaks()

        if loud:
            self._last_peak_at = now
            if self._started_at is None:
                self._started_at = now
            self.source = source

        # Lecture « collante » : un silence de dialogue ne doit pas remettre le
        # compteur à zéro, sinon `watching` ne se déclencherait jamais.
        recent = (self._last_peak_at is not None
                  and now - self._last_peak_at <= AUDIO_STICKY_SECONDS)
        self.playing = recent
        if recent and self._started_at is not None:
            self.seconds = now - self._started_at
        else:
            self.seconds = 0.0
            self._started_at = None
            self.source = ""

    def _enumerate(self) -> None:
        self._meters = []
        try:
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
        except Exception as exc:                # noqa: BLE001
            log.warning("pycaw indisponible, capteur média désactivé (%s)",
                        type(exc).__name__)
            self.available = False
            return

        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception as exc:                # noqa: BLE001
            log.warning("énumération des sessions audio impossible (%s)",
                        type(exc).__name__)
            return

        for session in sessions:
            try:
                meter = session._ctl.QueryInterface(IAudioMeterInformation)
            except Exception:                   # noqa: BLE001
                continue
            name = ""
            try:
                if session.Process is not None:
                    name = session.Process.name()
            except Exception:                   # noqa: BLE001
                name = ""
            self._meters.append((name, meter))

    def _read_peaks(self) -> tuple[bool, str]:
        best, loudest = "", 0.0
        stale = False
        for name, meter in self._meters:
            try:
                peak = float(meter.GetPeakValue())
            except Exception:                   # noqa: BLE001
                # Session dont le process est mort : on réénumérera.
                stale = True
                continue
            if peak > loudest:
                best, loudest = name, peak
        if stale:
            self._enumerated_at = None
        return loudest > AUDIO_PEAK_THRESHOLD, best


# --- Dérivation ------------------------------------------------------------


def is_watching(media_playing: bool, media_seconds: float, media_source: str,
                foreground_process: str, cursor_still_seconds: float,
                coverage: float) -> bool:
    """Le §11 : « media_playing vrai depuis plus de 20 s, curseur immobile ».

    **Le critère d'acceptation du CDC §16 phase 4 n'est pas atteignable tel
    qu'il est écrit.** Il exige que `sit_and_watch` se déclenche sur une vidéo
    et pas sur de la musique de fond, or WASAPI ne dit pas si un flux est une
    vidéo : côté son, YouTube et Spotify Web sont indiscernables.

    D'où cette heuristique, qui ajoute deux discriminants au texte du §11 :

    - un lecteur **vidéo** connu qui émet du son suffit ;
    - un lecteur **musical** connu ne suffit jamais ;
    - tout le reste — navigateur inclus — doit en plus occuper une large part de
      l'écran, parce qu'une vidéo se regarde en grand alors qu'une playlist
      tourne dans un onglet.

    S'y ajoute une condition trouvée en sondant le système réel : **la source du
    son doit être l'application au premier plan.** Sans elle, travailler dans son
    éditeur pendant qu'une vidéo joue derrière était compté comme un visionnage,
    puisque le test de couverture porte sur la fenêtre au premier plan alors que
    le son venait d'ailleurs. « Regarder » et « travailler avec du son derrière »
    seraient sinon indiscernables.

    Faux positif résiduel assumé : une vidéo musicale regardée en plein écran est
    comptée comme vidéo, ce qui est d'ailleurs défendable.
    """
    if not media_playing or media_seconds < WATCH_MEDIA_SECONDS:
        return False
    if cursor_still_seconds < WATCH_STILL_SECONDS:
        return False

    source = media_source.lower()
    if not source or source in AUDIO_ONLY_SOURCES:
        return False

    foreground = foreground_process.lower()
    if foreground != source and foreground not in UWP_HOSTS:
        return False

    if source in VIDEO_SOURCES:
        return True
    return coverage >= WATCH_COVERAGE


def derive_state(idle_seconds: float, cursor_speed: float,
                 watching: bool) -> str:
    """État symbolique, selon le §11.

    Ordre de priorité, et le premier point est une interprétation :
    `watching` passe **avant** `idle` et `away`. Ces deux derniers sont déduits
    d'une *absence* de preuve, alors qu'un média qui joue devant un curseur
    immobile est une preuve *positive* de présence. Un film de deux heures ne
    doit pas faire croire le pet abandonné.
    """
    if watching:
        return "watching"
    if idle_seconds >= AWAY_SECONDS:
        return "away"
    if idle_seconds >= IDLE_SECONDS:
        return "idle"
    # Interaction récente : le curseur bouge ou non (CDC §11).
    return "browsing" if cursor_speed > CURSOR_MOVE_EPS else "typing"


class Sensors:
    """Façade : agrège les capteurs et publie un `SystemContext`.

    Ne connaît ni `render` ni `anim` (cloison du CDC §5), et n'a besoin d'aucun
    GPU ni d'aucune fenêtre Qt : tous les capteurs sont injectables, ce qui rend
    la dérivation testable sur des scénarios écrits à la main.
    """

    def __init__(self, table: dict[str, frozenset[str]] | None = None) -> None:
        self.table = table if table is not None else load_categories()
        self.cursor = CursorSensor()
        self.foreground = ForegroundSensor(self.table)
        self.media = MediaSensor()
        self.idle_seconds = 0.0
        self._context = SystemContext()

    # -- polling -------------------------------------------------------------

    def observe_cursor(self, now: float,
                       position: tuple[int, int] | None = None) -> None:
        """Cadence rapide. Appelé par le timer de hit-testing (8–60 Hz)."""
        self.cursor.observe(now, position)

    def observe_slow(self, now: float, own_hwnd: int = 0) -> None:
        """Cadence lente, 4 Hz (CDC §11)."""
        self.idle_seconds = win32.get_idle_seconds()
        self.foreground.observe(own_hwnd)
        self.media.observe(now)
        self._context = self._derive()

    # -- publication ---------------------------------------------------------

    @property
    def context(self) -> SystemContext:
        return self._context

    def _derive(self) -> SystemContext:
        media_category = categorize(self.media.source, self.table) \
            if self.media.source else "other"
        watching = is_watching(
            self.media.playing, self.media.seconds, self.media.source,
            self.foreground.process, self.cursor.still_seconds,
            self.foreground.coverage,
        )
        return SystemContext(
            state=derive_state(self.idle_seconds, self.cursor.speed, watching),
            idle_seconds=self.idle_seconds,
            cursor=self.cursor.position,
            cursor_speed=self.cursor.speed,
            cursor_still_seconds=self.cursor.still_seconds,
            foreground_category=self.foreground.category,
            foreground_process=self.foreground.process,
            fullscreen=self.foreground.fullscreen,
            media_playing=self.media.playing,
            media_category=media_category,
            media_seconds=self.media.seconds,
        )
