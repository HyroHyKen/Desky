"""Wrappers ctypes sur user32/kernel32.

Choix imposé par le CDC §4 : pas de pywin32, dépendance lourde et bruyante au
packaging. Tout passe par ctypes.

Garanties de vie privée (CDC §3), tenues au niveau de ce module :
  - aucun hook, ni clavier ni souris : rien qui installe un WH_* ;
  - aucune lecture de contenu de frappe ;
  - les seules entrées consultées sont la position du curseur et, à partir du
    lot L5, le délai depuis la dernière interaction via GetLastInputInfo.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- Styles étendus (CDC §6) -------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020   # click-through, basculé dynamiquement
WS_EX_TOOLWINDOW = 0x00000080    # hors barre des tâches et hors alt-tab
WS_EX_NOACTIVATE = 0x08000000    # ne vole jamais le focus

# Contexte d'awareness DPI : PER_MONITOR_AWARE_V2 (CDC §6).
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

LONG_PTR = ctypes.c_ssize_t

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND


def set_dpi_awareness() -> str:
    """Passe le process en PER_MONITOR_AWARE_V2.

    Doit être appelé **avant** toute création de fenêtre, donc avant
    QApplication. Qt6 pose lui aussi PMv2 par défaut ; l'appeler explicitement
    rend le comportement déterministe et documente l'intention. Un échec
    signifie simplement que le contexte est déjà fixé, ce n'est pas une erreur.
    """
    fn = getattr(user32, "SetProcessDpiAwarenessContext", None)
    if fn is None:                                    # antérieur à Win10 1703
        return "indisponible"
    fn.argtypes = [ctypes.c_void_p]
    fn.restype = wintypes.BOOL
    if fn(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
        return "per-monitor-v2"
    return "déjà défini"


def apply_pet_window_styles(hwnd: int) -> None:
    """Applique les styles étendus de la fenêtre du pet.

    Le pet est click-through au départ : le hit-testing par alpha (CDC §6)
    retirera WS_EX_TRANSPARENT quand le curseur survolera un pixel opaque.

    À noter pour le lot L5 : le panneau de soin est un autre top-level et ne
    doit PAS recevoir WS_EX_NOACTIVATE, sinon il ne peut plus prendre le focus
    clavier.
    """
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Active ou retire WS_EX_TRANSPARENT.

    Volontairement sans lecture-comparaison côté appelant : c'est le seul
    appel Win32 du timer de hit-testing, et il est idempotent.
    """
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    new = ex | WS_EX_TRANSPARENT if enabled else ex & ~WS_EX_TRANSPARENT
    if new != ex:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)


def is_click_through(hwnd: int) -> bool:
    return bool(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT)


def get_cursor_pos() -> tuple[int, int]:
    """Position du curseur en **pixels physiques** (process PMv2)."""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Rect de la fenêtre en **pixels physiques** : (left, top, width, height).

    C'est la clé de la conversion du hit-testing : curseur et fenêtre sont
    tous deux lus en physique via Win32, la soustraction indexe donc
    directement le buffer alpha du FBO, lui aussi dimensionné en physique.
    Aucun calcul de facteur d'échelle, donc aucun risque de double scaling Qt,
    et le résultat reste juste sur un montage multi-écran à DPI mixtes.
    """
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def get_foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


# --- Instance unique (CDC §6) -----------------------------------------------


class SingleInstance:
    """Mutex nommé via CreateMutexW.

    Nom sans préfixe : CreateMutexW le place alors dans l'espace de noms de la
    session courante, ce qui correspond au périmètre voulu (une instance par
    session Windows, pas une par machine). Le handle est conservé en attribut :
    le mutex ne doit vivre que le temps du
    process, sa libération par le système à la sortie suffit.
    """

    def __init__(self, name: str) -> None:
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._handle = kernel32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


# --- Mesure CPU (critère d'acceptation L0) ----------------------------------


class FILETIME(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    @property
    def ticks(self) -> int:
        return (self.high << 32) | self.low


class CpuMeter:
    """Charge CPU du process, exprimée en pourcentage d'**un** cœur.

    Passe par GetProcessTimes plutôt que psutil : le critère d'acceptation de
    L0 exige une mesure, et psutil n'entre dans les dépendances qu'au lot L5.
    """

    def __init__(self) -> None:
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        self._proc = kernel32.GetCurrentProcess()
        self._last_cpu = self._cpu_seconds()
        self._last_wall = self._wall_seconds()

    def _cpu_seconds(self) -> float:
        creation, exit_, kernel, user = (FILETIME() for _ in range(4))
        kernel32.GetProcessTimes(
            self._proc, ctypes.byref(creation), ctypes.byref(exit_),
            ctypes.byref(kernel), ctypes.byref(user),
        )
        return (kernel.ticks + user.ticks) * 1e-7   # unités de 100 ns

    @staticmethod
    def _wall_seconds() -> float:
        import time
        return time.monotonic()

    def sample(self) -> float:
        cpu, wall = self._cpu_seconds(), self._wall_seconds()
        d_cpu, d_wall = cpu - self._last_cpu, wall - self._last_wall
        self._last_cpu, self._last_wall = cpu, wall
        return 100.0 * d_cpu / d_wall if d_wall > 0 else 0.0


# --- Moniteurs (CDC §6, multi-écran) ----------------------------------------

MONITOR_DEFAULTTONEAREST = 2
MONITOR_DEFAULTTOPRIMARY = 1
MONITORINFOF_PRIMARY = 0x1
EDD_GET_DEVICE_INTERFACE_NAME = 0x1
CCHDEVICENAME = 32


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * CCHDEVICENAME),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


class Monitor:
    """Un moniteur, en pixels physiques.

    `key` est l'identifiant sous lequel la position du pet est mémorisée. Il
    vient du DeviceID matériel et non du nom de périphérique renvoyé par
    GetMonitorInfo, qui n'est qu'un rang d'énumération : rebrancher les câbles
    dans l'autre ordre suffirait à le faire changer, et le pet réapparaîtrait
    alors sur le mauvais écran.
    """

    __slots__ = ("key", "device", "label", "rect", "work", "primary")

    def __init__(self, key, device, label, rect, work, primary):
        self.key = key
        self.device = device
        self.label = label
        self.rect = rect        # (left, top, w, h) écran complet
        self.work = work        # (left, top, w, h) hors barre des tâches
        self.primary = primary

    def __repr__(self) -> str:
        return f"<Monitor {self.label} {self.rect} primary={self.primary}>"


def _rect_tuple(r: wintypes.RECT) -> tuple[int, int, int, int]:
    return r.left, r.top, r.right - r.left, r.bottom - r.top


# Cache des identifiants matériels, par nom de périphérique.
#
# `EnumDisplayDevicesW` coûte **1,26 ms par moniteur**, mesuré au lot L4, et son
# résultat ne change jamais pour un périphérique donné. Sans ce cache,
# `monitor_from_window` appelé une fois par image consommait à lui seul 1,8 ms —
# davantage que tout le rendu.
_identity_cache: dict[str, tuple[str, str]] = {}


def _monitor_identity(device: str) -> tuple[str, str]:
    """(clé matérielle, libellé) pour un nom de périphérique, mis en cache."""
    cached = _identity_cache.get(device)
    if cached is not None:
        return cached

    key, label = device, device
    dd = DISPLAY_DEVICEW()
    dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    if user32.EnumDisplayDevicesW(device, 0, ctypes.byref(dd), EDD_GET_DEVICE_INTERFACE_NAME):
        if dd.DeviceID:
            key = dd.DeviceID
        if dd.DeviceString:
            label = dd.DeviceString
    _identity_cache[device] = (key, label)
    return key, label


def clear_monitor_cache() -> None:
    """Vide le cache. À appeler quand la configuration d'écrans change."""
    _identity_cache.clear()


def _monitor_from_handle(hmonitor) -> Monitor:
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
    user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi))
    device = mi.szDevice
    key, label = _monitor_identity(device)

    return Monitor(
        key=key,
        device=device,
        label=label,
        rect=_rect_tuple(mi.rcMonitor),
        work=_rect_tuple(mi.rcWork),
        primary=bool(mi.dwFlags & MONITORINFOF_PRIMARY),
    )


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
)


def list_monitors() -> list[Monitor]:
    """Tous les moniteurs actifs, l'écran principal en premier.

    Invalide le cache d'identités si l'ensemble des périphériques a changé :
    débrancher un écran peut faire réattribuer son nom à un autre.
    """
    found: list[Monitor] = []

    def cb(hmonitor, hdc, lprect, lparam):
        found.append(_monitor_from_handle(hmonitor))
        return True

    user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(cb), 0)

    devices = {m.device for m in found}
    if _identity_cache and set(_identity_cache) != devices:
        clear_monitor_cache()
        found = []
        user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(cb), 0)

    found.sort(key=lambda m: not m.primary)
    return found


def primary_monitor() -> Monitor:
    return _monitor_from_handle(user32.MonitorFromPoint(
        wintypes.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY))


def monitor_from_point(x: int, y: int) -> Monitor:
    return _monitor_from_handle(user32.MonitorFromPoint(
        wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST))


def monitor_from_window(hwnd: int) -> Monitor:
    return _monitor_from_handle(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))


# --- Plein écran exclusif (CDC §6) ------------------------------------------

# Fenêtres du shell qui couvrent légitimement tout l'écran en permanence : les
# prendre pour du plein écran masquerait le pet en continu sur le bureau nu.
_SHELL_CLASSES = frozenset({
    "Progman",              # bureau
    "WorkerW",              # bureau, couche des fonds animés
    "Shell_TrayWnd",        # barre des tâches
    "Shell_SecondaryTrayWnd",
    "DV2ControlHost",       # menu Démarrer (Win10)
    "Windows.UI.Core.CoreWindow",
    "ApplicationFrameWindow",
    "XamlExplorerHostIslandWindow",  # Task View / Snap Assist
})

# Tolérance en pixels : certaines applications plein écran débordent ou
# manquent l'écran de quelques pixels.
_FULLSCREEN_SLACK = 2


def get_window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_zoomed(hwnd: int) -> bool:
    """Vrai si la fenêtre est **maximisée**, au sens de Windows."""
    user32.IsZoomed.restype = wintypes.BOOL
    return bool(user32.IsZoomed(wintypes.HWND(hwnd)))


def foreground_fullscreen_monitor(own_hwnd: int) -> Monitor | None:
    """Le moniteur couvert par une fenêtre plein écran, ou None.

    Ne stocke ni ne renvoie jamais de titre de fenêtre (CDC §11) : uniquement
    un nom de classe, qui sert à écarter le shell, et un moniteur.

    **Le test géométrique ne suffit pas.** Sur un moniteur secondaire, la barre
    des tâches est absente, donc la zone de travail égale le rectangle de
    l'écran : une fenêtre simplement *maximisée* y couvre exactement la même
    surface qu'une fenêtre plein écran. Sans discrimination, le pet disparaît
    dès qu'on maximise quoi que ce soit sur cet écran.

    Le discriminant a été **mesuré**, et il écarte l'idée évidente :

    | fenêtre                      | IsZoomed | WS_CAPTION |
    |------------------------------|----------|------------|
    | app à chrome propre, maximisée |    1     |     0      |
    | Qt plein écran                 |    0     |     0      |
    | fenêtre classique, maximisée   |    1     |     1      |

    La barre de titre ne discrimine donc rien : une application Electron —
    Claude, VS Code, Discord — n'en a pas, même simplement maximisée. C'est
    `IsZoomed` qui sépare les deux cas, et lui seul.

    Limite assumée : un jeu en « maximisé sans bordure » ne masquera pas le pet.
    C'est la moins mauvaise des deux erreurs — un pet resté visible se déplace,
    un pet qui s'évanouit à chaque fenêtre maximisée est une gêne permanente.
    """
    fg = get_foreground_window()
    if not fg or fg == own_hwnd:
        return None
    if get_window_class(fg) in _SHELL_CLASSES:
        return None
    if is_zoomed(fg):
        return None

    left, top, w, h = get_window_rect(fg)
    if w <= 0 or h <= 0:
        return None

    mon = monitor_from_window(fg)
    ml, mt, mw, mh = mon.rect
    covers = (
        left <= ml + _FULLSCREEN_SLACK
        and top <= mt + _FULLSCREEN_SLACK
        and left + w >= ml + mw - _FULLSCREEN_SLACK
        and top + h >= mt + mh - _FULLSCREEN_SLACK
    )
    return mon if covers else None


SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

HWND_TOPMOST = -1


def set_window_pos(hwnd: int, x: int, y: int) -> None:
    """Déplace la fenêtre en **pixels physiques**.

    Passe par SetWindowPos plutôt que par QWidget.move(), qui attend des
    coordonnées logiques Qt. Tout ce module raisonne en physique — curseur,
    rects de fenêtre, rects de moniteur — et mélanger les deux espaces est
    précisément ce qui casse sur un montage à DPI mixtes. SWP_NOACTIVATE est
    indispensable : sans lui, un déplacement volerait le focus.
    """
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


# --- Activité utilisateur (CDC §3, §11) -------------------------------------


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL

# restype explicite : sans lui, ctypes rend un entier **signé** et le compteur
# de tics repasse en négatif au-delà de 24,8 jours d'uptime. Mesuré : une
# inactivité de −4 294 967 secondes sur une machine allumée depuis un mois.
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.GetTickCount.argtypes = []

_TICK_MASK = 0xFFFFFFFF


def get_idle_seconds() -> float:
    """Secondes depuis la dernière interaction utilisateur.

    **C'est le seul mécanisme d'observation du clavier de tout le projet.**
    `GetLastInputInfo` renvoie l'instant de la dernière entrée sans installer le
    moindre hook, donc sans jamais voir *ce* qui a été tapé. Le CDC §3 interdit
    formellement un hook clavier global — faux positifs antivirus, perception de
    keylogger — et cette fonction est ce qui rend l'interdiction tenable.

    La soustraction est faite en arithmétique 32 bits, ce qui traite
    naturellement le rebouclage du compteur de tics à 49,7 jours d'uptime.
    """
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    delta = (int(kernel32.GetTickCount()) - int(info.dwTime)) & _TICK_MASK
    return delta / 1000.0


# --- Process de la fenêtre au premier plan (CDC §11) ------------------------

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def get_window_process_id(hwnd: int) -> int:
    """PID propriétaire d'une fenêtre. 0 si indéterminable."""
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def assert_topmost(hwnd: int) -> None:
    """Réaffirme le rang le plus élevé, sans bouger ni activer la fenêtre.

    Le drapeau `WS_EX_TOPMOST` seul ne suffit pas : MSDN précise que le rang Z
    ne se change que par `SetWindowPos`, et divers évènements du shell — bascule
    de bureau virtuel, sortie de veille, application passant en plein écran sans
    bordure — peuvent redescendre une fenêtre sans toucher son style.

    Appelé à 4 Hz. Idempotent et mesuré à quelques microsecondes, donc sans
    conséquence sur le budget.

    **Remède au symptôme, pas à une cause identifiée** : le pet passait sous
    d'autres fenêtres sur un poste, et aucune des trois hypothèses testées —
    bascule du click-through, activation d'un rival, cycle hide/show — n'a
    reproduit le défaut en laboratoire.
    """
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.SetWindowPos(hwnd, ctypes.cast(HWND_TOPMOST, wintypes.HWND),
                        0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def raise_above(hwnd: int, other: int) -> None:
    """Place `hwnd` juste **au-dessus** de `other` dans la pile.

    Entre deux fenêtres toutes deux « toujours au-dessus », l'ordre relatif
    dépend de la dernière activation, et rien ne le garantit. Deux fenêtres du
    produit se recouvrent — les gobelets et le robot — et il faut que l'une soit
    devant l'autre de façon reproductible, faute de quoi le robot réapparaît
    par-dessus son gobelet une fois sur dix.

    `SWP_NOACTIVATE` est indispensable, ici comme partout ailleurs : réordonner
    ne doit jamais voler le focus.
    """
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.SetWindowPos(hwnd, wintypes.HWND(int(other)), 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


# --- Point d'attention (regard du pet) --------------------------------------


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def caret_position() -> tuple[int, int] | None:
    """Position du curseur de saisie de la fenêtre active, ou None.

    Sert à faire regarder le pet **là où on écrit** plutôt que la souris, qui
    est immobile pendant qu'on tape.

    Aucun hook n'est installé : `GetGUIThreadInfo` interroge l'état déjà publié
    par le thread de la fenêtre active, exactement comme `GetLastInputInfo`
    interroge l'horloge d'inactivité. Rien du contenu saisi n'est lu — seulement
    un rectangle à l'écran —, donc l'interdiction du §3 est respectée et le §11
    aussi.

    Retourne None **souvent**, et c'est normal : beaucoup d'applications
    modernes dessinent leur propre caret sans le publier. L'appelant doit avoir
    un repli.
    """
    fg = get_foreground_window()
    if not fg:
        return None
    thread = user32.GetWindowThreadProcessId(wintypes.HWND(fg), None)
    if not thread:
        return None

    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
        return None
    if not info.hwndCaret:
        return None

    rect = info.rcCaret
    if rect.right <= rect.left and rect.bottom <= rect.top:
        return None

    # Le rectangle est en coordonnées **client** de la fenêtre qui porte le
    # caret : sans cette conversion, le pet regarderait le coin de l'écran.
    point = wintypes.POINT((rect.left + rect.right) // 2,
                           (rect.top + rect.bottom) // 2)
    if not user32.ClientToScreen(info.hwndCaret, ctypes.byref(point)):
        return None
    return int(point.x), int(point.y)


def foreground_window_center(own_hwnd: int = 0) -> tuple[int, int] | None:
    """Centre de la fenêtre au premier plan, ou None.

    Ne lit **que la géométrie** : ni titre, ni contenu, ni capture. C'est ce qui
    rend ce point d'attention compatible avec le §11, là où lire ce qu'affiche
    la fenêtre ne le serait pas.
    """
    fg = get_foreground_window()
    if not fg or fg == own_hwnd:
        return None
    if get_window_class(fg) in _SHELL_CLASSES:
        return None
    left, top, width, height = get_window_rect(fg)
    if width <= 0 or height <= 0:
        return None
    return left + width // 2, top + height // 2


def foreground_window_center(own_hwnd: int) -> tuple[int, int] | None:
    """Centre de la fenêtre de premier plan, ou None si c'est la nôtre.

    Sert à faire regarder le pet **la fenêtre qu'on utilise** — une vidéo, un
    document — plutôt que la souris, qui ne dit rien quand elle ne bouge pas.

    Ne lit qu'une **géométrie** : ni titre, ni classe, ni contenu. Le §11
    interdit de stocker des titres de fenêtre ; un rectangle n'en est pas un, et
    il ne quitte de toute façon jamais la mémoire.

    Le shell est écarté comme ailleurs : regarder fixement la barre des tâches
    parce qu'on a cliqué sur le bureau n'aurait aucun sens.
    """
    fg = get_foreground_window()
    if not fg or fg == own_hwnd:
        return None
    if get_window_class(fg) in _SHELL_CLASSES:
        return None
    left, top, w, h = get_window_rect(fg)
    if w <= 0 or h <= 0:
        return None
    # Un peu au-dessus du centre géométrique : le contenu utile d'une fenêtre —
    # l'image d'une vidéo, le corps d'un texte — est rarement dans sa moitié
    # basse, qui porte plutôt des barres d'état.
    return left + w // 2, top + int(h * 0.42)


# --- Lancement au démarrage (CDC §13) ---------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _run_value_name() -> str:
    from .. import APP_NAME
    return APP_NAME


def autostart_enabled() -> bool:
    r"""Le pet est-il inscrit au démarrage de session ?

    Lit `HKCU\...\Run`, comme le §13 le prescrit. **Jamais HKLM** : celui-là
    demande l'élévation et inscrit pour tous les comptes de la machine, ce qui
    serait une prise de pouvoir disproportionnée pour un animal de compagnie.
    """
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as cle:
            valeur, _ = winreg.QueryValueEx(cle, _run_value_name())
            return bool(valeur)
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Inscrit ou retire le lancement au démarrage. Retourne True si ça a pris.

    Échoue silencieusement plutôt que de lever : une stratégie de groupe peut
    verrouiller cette clé, et un pet qui plante parce qu'il ne peut pas
    s'inscrire au démarrage serait une réponse démesurée. L'appelant relit
    l'état pour savoir ce qui s'est réellement passé.
    """
    import sys
    import winreg

    nom = _run_value_name()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as cle:
            if not enabled:
                try:
                    winreg.DeleteValue(cle, nom)
                except FileNotFoundError:
                    pass
                return True
            # Guillemets autour du chemin : `Program Files` en contient un.
            commande = '"%s" -m pet.main' % sys.executable
            winreg.SetValueEx(cle, nom, 0, winreg.REG_SZ, commande)
            return True
    except OSError as exc:
        log.warning("lancement au démarrage refusé : %s", type(exc).__name__)
        return False
