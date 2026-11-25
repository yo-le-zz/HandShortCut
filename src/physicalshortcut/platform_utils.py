"""Abstraction Windows / Linux : ecrans, lancement d'apps, fenetres, touches, systeme.

Windows -> pygetwindow, ctypes, winreg, PowerShell
Linux   -> wmctrl (ou xdotool) pour les fenetres, playerctl / wpctl / pactl pour le
           media, gsettings / KDE pour le theme et le fond d'ecran, pyautogui pour les
           touches. Sous Wayland pur, seules les fenetres XWayland sont pilotables.

Toutes les fonctions publiques renvoient ``True`` / ``False`` (jamais d'exception pour
un outil absent) et expliquent dans le journal ce qu'il faut installer.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
IS_WAYLAND = IS_LINUX and (
    os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
)


def current_os() -> str:
    """``windows`` | ``linux`` | ``other`` (valeur comparee au champ ``only_on`` des etapes)."""
    return "windows" if IS_WINDOWS else "linux" if IS_LINUX else "other"


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def expand_path(path) -> str:
    """``~``, ``$VAR`` et ``%VAR%`` developpes (un meme fichier d'actions sert partout)."""
    return os.path.expandvars(os.path.expanduser(str(path))) if path is not None else ""


# --------------------------------------------------------------------------
# Processus
# --------------------------------------------------------------------------


def _windows_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def spawn(cmd, *, shell: bool = False, env: dict | None = None) -> bool:
    """Lance un processus detache, sans bloquer ni laisser de zombie."""
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "shell": shell,
    }
    if env:
        kwargs["env"] = {**os.environ, **env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | _windows_flags()
    else:
        kwargs["start_new_session"] = True
        kwargs["close_fds"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except (OSError, ValueError) as exc:
        log.error("Lancement impossible de %r : %s", cmd, exc)
        return False
    threading.Thread(target=proc.wait, daemon=True).start()  # recolte le code retour
    return True


def run(cmd: list[str], timeout: float = 5.0, env: dict | None = None):
    """Execute une commande et attend son resultat ; ``None`` si elle n'a pas pu tourner."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, **env} if env else None,
            creationflags=_windows_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


_run = run  # ancien nom, conserve pour les tests et les scripts


def _ok(result) -> bool:
    return result is not None and result.returncode == 0


def powershell(script: str, *, timeout: float = 15.0, env: dict | None = None):
    """Execute un script PowerShell (Windows). Les valeurs variables passent par ``env``."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if exe is None:
        log.error("PowerShell introuvable")
        return None
    return run(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
        env=env,
    )


# --------------------------------------------------------------------------
# pyautogui (clavier / souris / capture)
# --------------------------------------------------------------------------


def pyautogui_module():
    """pyautogui configure pour un daemon, ou ``None`` s'il est inutilisable."""
    try:
        import pyautogui
    except Exception as exc:  # ImportError, ou pas d'affichage X11 sous Linux
        hint = " (necessite X11 ou XWayland)" if IS_LINUX else ""
        log.error("pyautogui indisponible : %s%s", exc, hint)
        return None
    # Le daemon tourne en arriere-plan : le failsafe (souris dans un coin) ferait
    # lever une exception a chaque action, et la pause par defaut ralentit.
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    return pyautogui


# --------------------------------------------------------------------------
# Ecrans
# --------------------------------------------------------------------------


def list_monitors() -> list[dict]:
    """Ecrans tries : principal en premier (index 1), puis de gauche a droite.

    Retourne une liste vide si aucun ecran n'est detectable (session sans
    affichage, Wayland sans XWayland...) au lieu de lever une exception.
    """
    try:
        from screeninfo import get_monitors

        monitors = list(get_monitors())
    except Exception as exc:  # screeninfo.ScreenInfoError, ImportError, erreurs X11...
        log.warning("Detection des ecrans impossible : %s", exc)
        return []

    primary = [m for m in monitors if getattr(m, "is_primary", False)]
    others = sorted((m for m in monitors if not getattr(m, "is_primary", False)), key=lambda m: m.x)
    return [
        {
            "index": i,
            "x": m.x,
            "y": m.y,
            "width": m.width,
            "height": m.height,
            "is_primary": bool(getattr(m, "is_primary", False)),
        }
        for i, m in enumerate(primary + others, start=1)
    ]


def get_monitor(index: int) -> dict | None:
    monitors = list_monitors()
    for m in monitors:
        if m["index"] == index:
            return m
    return monitors[0] if monitors else None  # repli : ecran principal


def rect_for_position(monitor: dict, position: str) -> tuple[int, int, int, int]:
    """(x, y, largeur, hauteur) pour un mot-cle de position sur un ecran."""
    x, y, w, h = monitor["x"], monitor["y"], monitor["width"], monitor["height"]
    half_w, half_h, third = w // 2, h // 2, w // 3
    layouts = {
        "left_half": (x, y, half_w, h),
        "right_half": (x + half_w, y, w - half_w, h),
        "top_half": (x, y, w, half_h),
        "bottom_half": (x, y + half_h, w, h - half_h),
        "center": (x + w // 4, y + h // 4, half_w, half_h),
        "top_left": (x, y, half_w, half_h),
        "top_right": (x + half_w, y, w - half_w, half_h),
        "bottom_left": (x, y + half_h, half_w, h - half_h),
        "bottom_right": (x + half_w, y + half_h, w - half_w, h - half_h),
        "left_third": (x, y, third, h),
        "center_third": (x + third, y, third, h),
        "right_third": (x + 2 * third, y, w - 2 * third, h),
    }
    return layouts.get((position or "fullscreen").lower(), (x, y, w, h))  # defaut : plein ecran


# --------------------------------------------------------------------------
# Applications / URL / fichiers
# --------------------------------------------------------------------------


def launch_app(path, args=None, shell_cmd=None) -> bool:
    """Lance une application (chemin, executable du PATH, URI sous Windows, .desktop sous Linux)."""
    if shell_cmd:
        return spawn(shell_cmd, shell=True)
    if not path:
        log.error("launch : aucun chemin / commande fourni")
        return False

    path = expand_path(path)
    args = [str(a) for a in (args or [])]
    if IS_WINDOWS:
        if not args:
            try:
                os.startfile(path)  # type: ignore[attr-defined]  # gere aussi les URI ("spotify:")
                return True
            except OSError:
                pass
        return spawn([path, *args], shell=True)

    command = [path, *args]
    if not args and " " in path.strip() and not os.path.exists(path):
        command = shlex.split(path)  # "firefox --private-window"
    program = command[0]
    if os.path.exists(program) or have(program):
        return spawn(command)
    # Nom d'une application installee (fichier .desktop) : "spotify", "org.gnome.Nautilus"...
    if len(command) == 1 and have("gtk-launch") and _ok(run(["gtk-launch", program], timeout=10)):
        return True
    log.error("launch : %r est introuvable (PATH, chemin ou fichier .desktop)", program)
    return False


def open_path(path) -> bool:
    """Ouvre un fichier ou un dossier avec l'application par defaut."""
    target = expand_path(path)
    if not target:
        log.error("open_path : chemin vide")
        return False
    if IS_WINDOWS:
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        except OSError as exc:
            log.error("open_path %s : %s", target, exc)
            return False
    for opener in ("xdg-open", "gio", "kde-open", "gnome-open"):
        if have(opener):
            return spawn([opener, "open", target] if opener == "gio" else [opener, target])
    log.error("open_path : xdg-open introuvable (sudo apt install xdg-utils)")
    return False


def open_url(url) -> bool:
    if not url:
        log.error("open_url : URL vide")
        return False
    if webbrowser.open(url):
        return True
    return IS_LINUX and have("xdg-open") and spawn(["xdg-open", url])


# --------------------------------------------------------------------------
# Fenetres
# --------------------------------------------------------------------------


def move_window(
    title_contains: str,
    monitor_index: int = 1,
    position: str = "fullscreen",
    retries: int = 15,
    retry_delay: float = 0.8,
) -> bool:
    """Deplace/redimensionne la fenetre dont le titre contient `title_contains`.

    Reessaie car la fenetre peut mettre du temps a apparaitre apres un launch.
    """
    monitor = get_monitor(monitor_index)
    if monitor is None:
        log.error("move_window : aucun ecran detecte")
        return False
    rect = rect_for_position(monitor, position)

    for attempt in range(retries):
        if _move_window_impl(title_contains, *rect):
            return True
        if attempt < retries - 1:
            time.sleep(retry_delay)
    log.warning("Fenetre introuvable pour %r apres %d essais", title_contains, retries)
    return False


def _move_window_impl(title: str, x: int, y: int, w: int, h: int) -> bool:
    if IS_WINDOWS:
        return _windows_window_op(title, "move", rect=(x, y, w, h))
    if IS_LINUX:
        return _linux_window_op(title, "move", rect=(x, y, w, h))
    return False


def close_window(title_contains: str, retries: int = 4, retry_delay: float = 0.4) -> bool:
    return _retry_window_op(title_contains, "close", retries, retry_delay)


def focus_window(title_contains: str, retries: int = 4, retry_delay: float = 0.4) -> bool:
    return _retry_window_op(title_contains, "focus", retries, retry_delay)


def minimize_window(title_contains: str, retries: int = 4, retry_delay: float = 0.4) -> bool:
    return _retry_window_op(title_contains, "minimize", retries, retry_delay)


def maximize_window(title_contains: str, retries: int = 4, retry_delay: float = 0.4) -> bool:
    return _retry_window_op(title_contains, "maximize", retries, retry_delay)


def restore_window(title_contains: str, retries: int = 4, retry_delay: float = 0.4) -> bool:
    return _retry_window_op(title_contains, "restore", retries, retry_delay)


def _retry_window_op(title: str, op: str, retries: int, delay: float) -> bool:
    for attempt in range(retries):
        if _window_op(title, op):
            return True
        if attempt < retries - 1:
            time.sleep(delay)
    log.warning("%s : fenetre introuvable pour %r", op, title)
    return False


def _window_op(title: str, op: str) -> bool:
    if IS_WINDOWS:
        return _windows_window_op(title, op)
    if IS_LINUX:
        return _linux_window_op(title, op)
    return False


def window_exists(title_contains: str) -> bool:
    """Une fenetre dont le titre contient ce texte est-elle ouverte ?"""
    if IS_WINDOWS:
        return _windows_window_op(title_contains, "exists")
    if IS_LINUX:
        return _linux_find(title_contains) is not None
    return False


def wait_for_window(title_contains: str, timeout_s: float = 10.0, poll_s: float = 0.3) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        if window_exists(title_contains):
            return True
        if time.monotonic() >= deadline:
            log.warning("Fenetre %r : delai d'attente depasse (%.1f s)", title_contains, timeout_s)
            return False
        time.sleep(poll_s)


# -- Windows ---------------------------------------------------------------


def _windows_window_op(title: str, op: str, rect: tuple[int, int, int, int] | None = None) -> bool:
    try:
        import pygetwindow as gw
    except ImportError:
        log.error("pygetwindow n'est pas installe")
        return False

    needle = title.lower()
    for win in gw.getAllWindows():
        try:
            win_title = (win.title or "").strip()
            if not win_title or needle not in win_title.lower():
                continue
            if op == "exists":
                return True
            if op == "close":
                win.close()
                return True
            if op == "minimize":
                win.minimize()
                return True
            if op == "maximize":
                win.maximize()
                _activate(win)
                return True
            if op == "restore":
                win.restore()
                _activate(win)
                return True
            if op == "move" and rect is not None:
                win.restore()
                win.moveTo(rect[0], rect[1])
                win.resizeTo(rect[2], rect[3])
            _activate(win)
            return True
        except Exception as exc:
            log.debug("Fenetre %r ignoree : %s", getattr(win, "title", "?"), exc)
    return False


def _activate(win) -> None:
    # pygetwindow leve parfois une exception alors que l'activation a reussi.
    try:
        win.activate()
    except Exception as exc:
        log.debug("activate : %s", exc)


# -- Linux : wmctrl, a defaut xdotool ---------------------------------------


def _linux_backend() -> str | None:
    if have("wmctrl"):
        return "wmctrl"
    if have("xdotool"):
        return "xdotool"
    return None


def _regex_escape(text: str) -> str:
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", text)


def _linux_find(title: str) -> str | None:
    backend = _linux_backend()
    if backend is None:
        log.error(
            "Aucun outil de gestion des fenetres (sudo apt install wmctrl / sudo dnf install wmctrl)%s",
            " ; Wayland pur : seules les fenetres XWayland sont pilotables" if IS_WAYLAND else "",
        )
        return None
    needle = title.lower()
    if backend == "wmctrl":
        result = run(["wmctrl", "-l"])
        if not _ok(result):
            return None
        for line in result.stdout.splitlines():
            parts = line.split(None, 3)  # id, bureau, machine, titre
            if len(parts) == 4 and needle in parts[3].lower():
                return parts[0]
        return None
    result = run(["xdotool", "search", "--onlyvisible", "--name", _regex_escape(title)])
    if _ok(result):
        ids = result.stdout.split()
        return ids[0] if ids else None
    return None


def _linux_window_op(title: str, op: str, rect: tuple[int, int, int, int] | None = None) -> bool:
    win_id = _linux_find(title)
    if win_id is None:
        return False
    if _linux_backend() == "wmctrl":
        return _wmctrl_op(win_id, op, rect)
    return _xdotool_op(win_id, op, rect)


_WM_BOTH = "maximized_vert,maximized_horz"


def _wmctrl_op(win_id: str, op: str, rect) -> bool:
    if op == "move" and rect is not None:
        x, y, w, h = rect
        run(["wmctrl", "-i", "-r", win_id, "-b", f"remove,{_WM_BOTH}"])
        if not _ok(run(["wmctrl", "-i", "-r", win_id, "-e", f"0,{x},{y},{w},{h}"])):
            return False
        run(["wmctrl", "-i", "-a", win_id])
        return True
    if op == "close":
        return _ok(run(["wmctrl", "-i", "-c", win_id]))
    if op == "minimize":
        return _ok(run(["wmctrl", "-i", "-r", win_id, "-b", "add,hidden"]))
    if op == "maximize":
        ok = _ok(run(["wmctrl", "-i", "-r", win_id, "-b", f"add,{_WM_BOTH}"]))
        run(["wmctrl", "-i", "-a", win_id])
        return ok
    if op == "restore":
        ok = _ok(run(["wmctrl", "-i", "-r", win_id, "-b", f"remove,{_WM_BOTH},hidden"]))
        run(["wmctrl", "-i", "-a", win_id])
        return ok
    return _ok(run(["wmctrl", "-i", "-a", win_id]))  # focus


def _xdotool_op(win_id: str, op: str, rect) -> bool:
    if op == "move" and rect is not None:
        x, y, w, h = rect
        return _ok(run(["xdotool", "windowmove", win_id, str(x), str(y)])) and _ok(
            run(["xdotool", "windowsize", win_id, str(w), str(h)])
        )
    if op == "maximize":
        monitor = get_monitor(1)
        if monitor is None:
            return False
        return _xdotool_op(win_id, "move", (monitor["x"], monitor["y"], monitor["width"], monitor["height"]))
    if op == "close":
        return _ok(run(["xdotool", "windowquit", win_id]))
    if op == "minimize":
        return _ok(run(["xdotool", "windowminimize", win_id]))
    if op == "restore":
        run(["xdotool", "windowmap", win_id])
    return _ok(run(["xdotool", "windowactivate", win_id]))  # focus / restore


# -- Bureau : afficher / bureaux virtuels --------------------------------------


def show_desktop(mode: str = "toggle") -> bool:
    """Affiche (show), masque (hide) ou bascule (toggle) le bureau."""
    if IS_WINDOWS:
        action = {"show": "MinimizeAll", "hide": "UndoMinimizeAll", "toggle": "ToggleDesktop"}.get(mode)
        if action is None:
            return False
        return _ok(powershell(f"(New-Object -ComObject Shell.Application).{action}()"))
    if IS_LINUX and have("wmctrl"):
        if mode == "toggle":
            state = run(["xprop", "-root", "_NET_SHOWING_DESKTOP"]) if have("xprop") else None
            showing = state is not None and state.stdout.strip().endswith("= 1")
            mode = "hide" if showing else "show"
        return _ok(run(["wmctrl", "-k", "on" if mode == "show" else "off"]))
    log.error("show_desktop : wmctrl requis sous Linux (sudo apt install wmctrl)")
    return False


def switch_desktop(target: str = "next", index: int | None = None) -> bool:
    """Bureau virtuel suivant / precedent ; sous Linux, ou numero precis (1 = premier)."""
    if IS_WINDOWS:
        if index:
            log.warning("switch_desktop : le numero de bureau n'est pas gere sous Windows")
        gui = pyautogui_module()
        if gui is None:
            return False
        gui.hotkey("ctrl", "win", "right" if target == "next" else "left")
        return True
    if IS_LINUX and have("wmctrl"):
        listing = run(["wmctrl", "-d"])
        if not _ok(listing):
            return False
        lines = [line for line in listing.stdout.splitlines() if line.strip()]
        if not lines:
            return False
        count = len(lines)
        current = next((i for i, line in enumerate(lines) if line.split()[1] == "*"), 0)
        wanted = (index - 1) if index else (current + (1 if target == "next" else -1)) % count
        wanted = min(max(wanted, 0), count - 1)
        return _ok(run(["wmctrl", "-s", str(wanted)]))
    log.error("switch_desktop : wmctrl requis sous Linux (sudo apt install wmctrl)")
    return False


# --------------------------------------------------------------------------
# Clavier / media
# --------------------------------------------------------------------------

MEDIA_KEY_LINUX = {
    "play_pause": "XF86AudioPlay",
    "next": "XF86AudioNext",
    "prev": "XF86AudioPrev",
    "volume_up": "XF86AudioRaiseVolume",
    "volume_down": "XF86AudioLowerVolume",
    "mute": "XF86AudioMute",
}
MEDIA_KEY_WINDOWS = {  # codes de touches virtuelles (keybd_event)
    "play_pause": 0xB3,
    "next": 0xB0,
    "prev": 0xB1,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}
_PLAYERCTL = {"play_pause": "play-pause", "next": "next", "prev": "previous"}
_WPCTL = {
    "volume_up": ["set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"],
    "volume_down": ["set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
    "mute": ["set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
}
_PACTL = {
    "volume_up": ["set-sink-volume", "@DEFAULT_SINK@", "+5%"],
    "volume_down": ["set-sink-volume", "@DEFAULT_SINK@", "-5%"],
    "mute": ["set-sink-mute", "@DEFAULT_SINK@", "toggle"],
}

# Noms de touches equivalents d'un systeme a l'autre : une meme action sert partout.
KEY_ALIASES = {
    "super": "win",
    "meta": "win",
    "cmd": "win",
    "command": "win",
    "windows": "win",
    "control": "ctrl",
    "return": "enter",
    "escape": "esc",
    "del": "delete",
    "ins": "insert",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "option": "alt",
    "spacebar": "space",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
}


def normalize_keys(keys: str) -> list[str]:
    """'Ctrl + Super+D' -> ['ctrl', 'win', 'd']."""
    combo = [k.strip().lower() for k in (keys or "").split("+") if k.strip()]
    return [KEY_ALIASES.get(k, k) for k in combo]


def send_keypress(keys: str) -> bool:
    """Envoie une combinaison, ex: 'ctrl+shift+m' (noms de touches pyautogui)."""
    combo = normalize_keys(keys)
    if not combo:
        log.error("keypress : aucune touche fournie")
        return False
    gui = pyautogui_module()
    if gui is None:
        return False

    unknown = [k for k in combo if k not in gui.KEYBOARD_KEYS]
    if unknown:
        log.error("keypress : touche(s) inconnue(s) %s", ", ".join(unknown))
        return False
    if len(combo) == 1:
        gui.press(combo[0])
    else:
        gui.hotkey(*combo)
    return True


def type_text(text: str, interval_s: float = 0.0) -> bool:
    """Tape un texte ; les caracteres hors ASCII passent par le presse-papiers."""
    gui = pyautogui_module()
    if gui is None:
        return False
    if text.isascii():
        gui.write(text, interval=interval_s)
        return True
    try:
        import pyperclip
    except ImportError:
        log.error("pyperclip requis pour taper des accents / symboles")
        return False
    previous = None
    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001 - presse-papiers illisible : on n'essaie pas de le restaurer
        previous = None
    pyperclip.copy(text)
    time.sleep(0.05)
    gui.hotkey("ctrl", "v")
    time.sleep(0.15)
    if previous is not None:
        pyperclip.copy(previous)
    return True


def media_control(action: str) -> bool:
    """Lecture/pause, suivant, precedent, volume, muet."""
    if action not in MEDIA_KEY_LINUX:
        log.error("media_control : action inconnue %r", action)
        return False
    if IS_LINUX:
        return _media_linux(action)
    if IS_WINDOWS:
        return _windows_media_key(MEDIA_KEY_WINDOWS[action])
    return False


def _windows_media_key(code: int) -> bool:
    try:
        import ctypes

        ctypes.windll.user32.keybd_event(code, 0, 0, 0)  # type: ignore[attr-defined]
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)  # type: ignore[attr-defined]  # KEYUP
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Touche media a echoue : %s", exc)
        return False


def _media_linux(action: str) -> bool:
    if action in _PLAYERCTL and have("playerctl") and _ok(run(["playerctl", _PLAYERCTL[action]], timeout=2)):
        return True
    # Volume : PipeWire/PulseAudio fonctionnent aussi sous Wayland, contrairement a xdotool.
    for tool, commands in (("wpctl", _WPCTL), ("pactl", _PACTL)):
        if action in commands and have(tool) and _ok(run([tool, *commands[action]], timeout=2)):
            return True
    if have("xdotool") and _ok(run(["xdotool", "key", MEDIA_KEY_LINUX[action]], timeout=2)):
        return True
    log.error("media_control %s : aucun outil disponible (playerctl, wpctl/pactl ou xdotool)", action)
    return False


# --------------------------------------------------------------------------
# Volume, luminosite, theme, fond d'ecran
# --------------------------------------------------------------------------


def set_volume(level: int) -> bool:
    level = max(0, min(100, int(level)))
    if IS_LINUX:
        if have("wpctl") and _ok(run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"], timeout=3)):
            return True
        if have("pactl") and _ok(run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"], timeout=3)):
            return True
        if have("amixer") and _ok(run(["amixer", "-q", "sset", "Master", f"{level}%"], timeout=3)):
            return True
        log.error("set_volume : wpctl, pactl ou amixer requis")
        return False
    if IS_WINDOWS:
        return _windows_set_volume(level)
    return False


def _windows_set_volume(level: int) -> bool:
    try:  # pycaw (installe avec le paquet sous Windows) : volume exact
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        speakers = AudioUtilities.GetSpeakers()
        endpoint = getattr(speakers, "EndpointVolume", None)  # pycaw recents
        if endpoint is None:  # pycaw anciens
            from ctypes import POINTER, cast

            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(interface, POINTER(IAudioEndpointVolume))
        endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("pycaw indisponible (%s) : repli sur les touches volume", exc)
    # Repli sans dependance : chaque appui sur une touche volume = 2 %.
    for _ in range(50):
        _windows_media_key(MEDIA_KEY_WINDOWS["volume_down"])
    for _ in range(round(level / 2)):
        _windows_media_key(MEDIA_KEY_WINDOWS["volume_up"])
    return True


def set_brightness(level: int) -> bool:
    level = max(0, min(100, int(level)))
    if IS_LINUX:
        if have("brightnessctl") and _ok(run(["brightnessctl", "set", f"{level}%"], timeout=3)):
            return True
        if have("xbacklight") and _ok(run(["xbacklight", "-set", str(level)], timeout=3)):
            return True
        log.error("change_brightness : brightnessctl ou xbacklight requis")
        return False
    if IS_WINDOWS:
        script = (
            "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
            f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}}"
        )
        if _ok(powershell(script)):
            return True
        log.error("change_brightness : ecran non compatible (seuls les ecrans internes sont geres)")
        return False
    return False


def _desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def set_theme(mode: str = "toggle") -> bool:
    """Theme sombre / clair du systeme."""
    if IS_WINDOWS:
        return _windows_set_theme(mode)
    if IS_LINUX:
        desktop = _desktop()
        if "kde" in desktop and have("plasma-apply-colorscheme"):
            reader = shutil.which("kreadconfig6") or shutil.which("kreadconfig5")
            dark = False
            if reader:
                result = run([reader, "--file", "kdeglobals", "--group", "General", "--key", "ColorScheme"])
                dark = result is not None and "dark" in result.stdout.lower()
            want_dark = (not dark) if mode == "toggle" else mode == "dark"
            return _ok(run(["plasma-apply-colorscheme", "BreezeDark" if want_dark else "BreezeLight"], timeout=10))
        if have("gsettings"):
            current = run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
            dark = current is not None and "dark" in current.stdout
            want_dark = (not dark) if mode == "toggle" else mode == "dark"
            value = "prefer-dark" if want_dark else "default"
            return _ok(run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", value]))
        log.error("set_theme : GNOME (gsettings) ou KDE Plasma requis")
    return False


def _windows_set_theme(mode: str) -> bool:
    try:
        import ctypes
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            try:
                is_light = winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 1
            except FileNotFoundError:
                is_light = True
            want_light = (not is_light) if mode == "toggle" else mode == "light"
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1 if want_light else 0)
        # previent les applications ouvertes
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "ImmersiveColorSet", 2, 5000, None)  # type: ignore[attr-defined]
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("set_theme a echoue : %s", exc)
        return False


def set_wallpaper(path) -> bool:
    image = Path(expand_path(path)).expanduser().resolve()
    if not image.is_file():
        log.error("change_wallpaper : image introuvable (%s)", image)
        return False
    if IS_WINDOWS:
        import ctypes

        ok = ctypes.windll.user32.SystemParametersInfoW(20, 0, str(image), 3)  # type: ignore[attr-defined]
        return bool(ok)
    if IS_LINUX:
        desktop = _desktop()
        uri = image.as_uri()
        if "kde" in desktop and have("plasma-apply-wallpaperimage"):
            return _ok(run(["plasma-apply-wallpaperimage", str(image)], timeout=10))
        if ("xfce" in desktop) and have("xfconf-query"):
            listing = run(["xfconf-query", "-c", "xfce4-desktop", "-l"])
            props = [p for p in (listing.stdout.splitlines() if listing else []) if p.endswith("/last-image")]
            return bool(props) and all(
                _ok(run(["xfconf-query", "-c", "xfce4-desktop", "-p", p, "-s", str(image)])) for p in props
            )
        if have("gsettings") and (not desktop or any(d in desktop for d in ("gnome", "unity", "cinnamon", "budgie", "pantheon", "ubuntu"))):
            schema = "org.cinnamon.desktop.background" if "cinnamon" in desktop else "org.gnome.desktop.background"
            ok = _ok(run(["gsettings", "set", schema, "picture-uri", uri]))
            run(["gsettings", "set", schema, "picture-uri-dark", uri])  # GNOME >= 42 (theme sombre)
            return ok
        if have("feh"):
            return _ok(run(["feh", "--bg-fill", str(image)]))
        log.error("change_wallpaper : GNOME, KDE Plasma, XFCE ou feh requis")
    return False


# --------------------------------------------------------------------------
# Notifications, sons, voix, capture, alimentation
# --------------------------------------------------------------------------


def notify(title: str, message: str) -> bool:
    if IS_LINUX and have("notify-send"):
        return spawn(["notify-send", "--app-name=PhysicalShortCut", title, message])
    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name="PhysicalShortCut", timeout=5)
        return True
    except Exception as exc:  # noqa: BLE001 - plyer absent ou backend indisponible
        log.debug("plyer indisponible : %s", exc)
    if IS_WINDOWS:  # repli : bulle de la zone de notification
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$n = New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
            "$n.ShowBalloonTip(5000, $env:HSC_TITLE, $env:HSC_MESSAGE, 'Info'); Start-Sleep 6; $n.Dispose()"
        )
        exe = shutil.which("powershell") or "powershell"
        return spawn(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            env={"HSC_TITLE": title, "HSC_MESSAGE": message},
        )
    log.error("Notification impossible (sudo apt install libnotify-bin)")
    return False


def play_sound(path) -> bool:
    target = expand_path(path)
    if not os.path.isfile(target):
        log.error("play_sound : fichier introuvable (%s)", target)
        return False
    if IS_WINDOWS:
        if target.lower().endswith(".wav"):
            import winsound

            winsound.PlaySound(target, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        return open_path(target)  # autres formats : lecteur par defaut
    players = (
        ["paplay", target],
        ["pw-play", target],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", target],
        ["mpv", "--no-video", "--really-quiet", target],
        ["play", "-q", target],
        ["aplay", "-q", target],
    )
    for command in players:
        if have(command[0]):
            return spawn(command)
    log.error("play_sound : aucun lecteur (paplay, pw-play, ffplay, mpv ou aplay)")
    return False


def speak(text: str) -> bool:
    if IS_WINDOWS:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:HSC_SPEAK_TEXT)"
        )
        exe = shutil.which("powershell") or "powershell"
        return spawn([exe, "-NoProfile", "-NonInteractive", "-Command", script], env={"HSC_SPEAK_TEXT": text})
    for tool, command in (
        ("spd-say", ["spd-say", "--", text]),
        ("espeak-ng", ["espeak-ng", "--", text]),
        ("espeak", ["espeak", "--", text]),
    ):
        if have(tool):
            return spawn(command)
    log.error("speak : spd-say, espeak-ng ou espeak requis (sudo apt install speech-dispatcher)")
    return False


def screenshot(path) -> bool:
    target = Path(expand_path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    gui = pyautogui_module()
    if gui is not None:
        try:
            gui.screenshot().save(str(target))
            return True
        except Exception as exc:  # noqa: BLE001 - Wayland : pas de capture X11
            log.debug("pyautogui.screenshot a echoue : %s", exc)
    if IS_LINUX:
        for command in (
            ["grim", str(target)],
            ["gnome-screenshot", "-f", str(target)],
            ["spectacle", "-b", "-n", "-f", "-o", str(target)],
            ["scrot", "-o", str(target)],
        ):
            if have(command[0]) and _ok(run(command, timeout=15)):
                return True
        log.error("screenshot : grim, gnome-screenshot, spectacle ou scrot requis")
    return False


def power_action(action: str) -> bool:
    """Verrouille, met en veille, ferme la session, redemarre ou eteint."""
    if IS_WINDOWS:
        commands = {
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "logout": ["shutdown", "/l"],
            "restart": ["shutdown", "/r", "/t", "0"],
            "shutdown": ["shutdown", "/s", "/t", "0"],
        }
        command = commands.get(action)
        return command is not None and spawn(command)
    if IS_LINUX:
        if action == "lock":
            for command in (
                ["loginctl", "lock-session"],
                ["xdg-screensaver", "lock"],
                ["gnome-screensaver-command", "-l"],
                ["xflock4"],
                ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Lock"],
            ):
                if have(command[0]) and _ok(run(command, timeout=5)):
                    return True
            log.error("lock : loginctl, xdg-screensaver ou equivalent requis")
            return False
        commands = {
            "sleep": ["systemctl", "suspend"],
            "logout": ["loginctl", "terminate-session", os.environ.get("XDG_SESSION_ID", "")],
            "restart": ["systemctl", "reboot"],
            "shutdown": ["systemctl", "poweroff"],
        }
        command = commands.get(action)
        if command is None or not have(command[0]):
            return False
        if action == "logout" and not command[-1]:
            command = ["loginctl", "terminate-user", os.environ.get("USER", "")]
        return spawn(command)
    return False


def executable_command() -> list[str]:
    """Commande qui relance PhysicalShortCut (pour le demarrage automatique)."""
    found = shutil.which("physicalshortcut")
    if found:
        return [found]
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return [str(Path(sys.argv[0]).resolve())]
    return [sys.executable, "-m", "physicalshortcut"]
