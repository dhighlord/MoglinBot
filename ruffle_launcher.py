"""Cross-platform AQW game launcher using the Ruffle Flash emulator.

This module locates the bundled Ruffle desktop binary for the current platform
and spawns it pointed at the official AQW game SWF (Loader3.swf), exactly the
way Artix's own cross-platform "Artix Games Launcher" ships Flash games after
Adobe Flash's end of life.

Ruffle is an open-source Flash Player emulator (Rust -> native binary) that
replaces the retired Adobe Flash / Pepper Flash runtimes. AQW's game client is
a Flash SWF that talks to the game server over a raw TCP socket, which is why
we pass ``--tcp-connections allow``.

Reference (Artix's own launcher does the same thing):
    ruffle <swfUrl> --tcp-connections allow --player-version 9 --width 960 --height 580
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import subprocess
import sys
import time

# Application branding (see README / www.epicalyx.org).
APP_NAME = "Moglin Bot"
WEBSITE = "www.epicalyx.org"
WINDOW_TITLE = f"{APP_NAME} by {WEBSITE}"

# Official AQW game loader SWF (the real client entry point).
AQW_LOADER_URL = "https://game.aq.com/game/gamefiles/Loader3.swf?ver=a"

# Default game canvas size (AQW native aspect ratio is 960x550).
DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 550

# How long to keep trying to retitle the Ruffle window after spawn (seconds).
_RETITLE_TIMEOUT = 12.0


# --------------------------------------------------------------------------- #
# Binary discovery
# --------------------------------------------------------------------------- #

def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _project_root() -> str:
    """Directory containing the running executable (frozen) or this module."""
    if _is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _binary_name() -> str:
    return "ruffle.exe" if platform.system().lower() == "windows" else "ruffle"


def candidate_locations() -> list[tuple[str, str]]:
    """Return (path, description) pairs to search for the Ruffle binary.

    Order matters and covers every packaging layout:

    * Development: ``<repo>/vendor/ruffle/<bin>``
    * PyInstaller onedir/onefile: the ``--add-data`` payload is extracted into
      ``sys._MEIPASS`` (``.../_internal/`` for onedir, a temp dir for onefile).
    * Also fall back to next-to-executable and ``vendor/ruffle`` next to the
      executable for manually-assembled distributions.
    """
    name = _binary_name()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(path: str, desc: str) -> None:
        p = os.path.abspath(path)
        if p not in seen:
            seen.add(p)
            found.append((p, desc))

    if _is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        exe_dir = _project_root()
        if meipass:
            add(os.path.join(meipass, name), "bundle (_MEIPASS)")
            add(os.path.join(meipass, "vendor", "ruffle", name), "bundle (_MEIPASS/vendor)")
        add(os.path.join(exe_dir, name), "next to executable")
        add(os.path.join(exe_dir, "_internal", name), "bundle (_internal)")
        add(os.path.join(exe_dir, "vendor", "ruffle", name), "vendor next to executable")
    else:
        root = _project_root()
        add(os.path.join(root, "vendor", "ruffle", name), "repo vendor dir")
        add(os.path.join(root, name), "repo root")
    return found


def find_ruffle() -> str | None:
    """Return the path to the bundled Ruffle binary, or ``None`` if missing."""
    for path, _desc in candidate_locations():
        if os.path.isfile(path):
            return path
    return None


def ruffle_status() -> str:
    path = find_ruffle()
    if path:
        return f"Ruffle ready: {path}"
    searched = ", ".join(desc for _p, desc in candidate_locations())
    return f"Ruffle binary not found. Searched: {searched}"


# --------------------------------------------------------------------------- #
# Game launch
# --------------------------------------------------------------------------- #

def launch_game(
    swf_url: str = AQW_LOADER_URL,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    player_version: int = 9,
    tcp_connections: str = "allow",
    extra_args: list[str] | None = None,
    set_title: str | None = WINDOW_TITLE,
) -> subprocess.Popen:
    """Spawn the Ruffle binary to run the AQW game SWF.

    Returns the spawned :class:`subprocess.Popen` so the caller can manage its
    lifetime. Raises :class:`FileNotFoundError` when the binary is missing and
    :class:`RuntimeError` when spawning fails for any other reason.
    """
    ruffle = find_ruffle()
    if not ruffle:
        raise FileNotFoundError(ruffle_status())

    args = [
        ruffle,
        swf_url,
        "--tcp-connections", tcp_connections,
        "--player-version", str(player_version),
        "--width", str(width),
        "--height", str(height),
        # Hide Ruffle's own menu/toolbar so the user sees a clean game window.
        "--no-gui",
    ]
    if extra_args:
        args.extend(extra_args)

    # Detach so the game keeps running even if the parent GUI exits (matches
    # Artix's launcher behaviour), and use a fresh process group on POSIX.
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(args, **kwargs)
    except OSError as exc:  # e.g. permission denied / not executable
        raise RuntimeError(f"Failed to start Ruffle: {exc}") from exc

    # Retitle the native window asynchronously (Ruffle has no --title flag).
    if set_title:
        _retitle_window_async(proc.pid, set_title)
    return proc


def is_process_running(proc: subprocess.Popen | None) -> bool:
    """Return True when ``proc`` has not yet exited."""
    return proc is not None and proc.poll() is None


# --------------------------------------------------------------------------- #
# Native window retitling (Ruffle hard-codes "Ruffle - <file>" as its title)
# --------------------------------------------------------------------------- #

def _retitle_window_async(pid: int, title: str) -> None:
    """Best-effort background retitling; never blocks or raises."""
    try:
        import threading
        t = threading.Thread(target=_retitle_window, args=(pid, title), daemon=True)
        t.start()
    except Exception:
        pass


def _retitle_window(pid: int, title: str) -> None:
    deadline = time.time() + _RETITLE_TIMEOUT
    while time.time() < deadline:
        try:
            if platform.system().lower() == "windows":
                done = _set_windows_title(pid, title)
            else:
                done = _set_x11_title(pid, title)
            if done:
                return
        except Exception:
            pass
        time.sleep(0.4)


# ---- Windows ------------------------------------------------------------- #

def _set_windows_title(pid: int, title: str) -> bool:
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    title_buf = ctypes.create_unicode_buffer(title)
    results: dict = {"changed": False}

    def callback(hwnd, lparam):
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value == pid:
            # Only touch the top-level (owned) window. GW_OWNER == 4.
            if user32.GetWindow(hwnd, 4) == 0:
                user32.SetWindowTextW(hwnd, title_buf)
                results["changed"] = True
                return False  # stop enumeration
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return results["changed"]


# ---- Linux (X11) --------------------------------------------------------- #

def _set_x11_title(pid: int, title: str) -> bool:
    x11_name = ctypes.util.find_library("X11") or "libX11.so.6"
    x11 = ctypes.CDLL(x11_name)

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]

    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        root = x11.XDefaultRootWindow(display)
        atom_pid = _x11_intern_atom(x11, display, b"_NET_WM_PID")
        atom_net_name = _x11_intern_atom(x11, display, b"_NET_WM_NAME")
        atom_utf8 = _x11_intern_atom(x11, display, b"UTF8_STRING")

        if 0 in (atom_pid, atom_net_name, atom_utf8):
            return False

        windows = _x11_collect_windows(x11, display, root)
        changed = False
        for win in windows:
            try:
                if _x11_read_pid(x11, display, win, atom_pid) == pid:
                    _x11_store_name(x11, display, win, atom_net_name, atom_utf8, title)
                    changed = True
            except Exception:
                continue
        return changed
    finally:
        x11.XCloseDisplay(display)


def _x11_intern_atom(x11, display, name: bytes) -> int:
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    return int(x11.XInternAtom(display, name, 0))


def _x11_collect_windows(x11, display, root: int) -> list[int]:
    x11.XQueryTree.restype = ctypes.c_int
    x11.XQueryTree.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XFree.restype = None
    x11.XFree.argtypes = [ctypes.c_void_p]

    root_ret = ctypes.c_ulong()
    parent_ret = ctypes.c_ulong()
    children = ctypes.POINTER(ctypes.c_ulong)()
    nchildren = ctypes.c_uint()

    result: list[int] = []
    try:
        if not x11.XQueryTree(display, root, ctypes.byref(root_ret), ctypes.byref(parent_ret),
                              ctypes.byref(children), ctypes.byref(nchildren)):
            return result
        for i in range(nchildren.value):
            result.append(int(children[i]))
    finally:
        if children:
            x11.XFree(children)
    return result


def _x11_read_pid(x11, display, window: int, atom_pid: int) -> int | None:
    x11.XGetWindowProperty.restype = ctypes.c_int
    x11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    x11.XFree.restype = None
    x11.XFree.argtypes = [ctypes.c_void_p]

    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    nitems = ctypes.c_ulong()
    bytes_after = ctypes.c_ulong()
    prop = ctypes.c_void_p()

    try:
        status = x11.XGetWindowProperty(
            display, window, atom_pid, 0, 1, 0, 0,
            ctypes.byref(actual_type), ctypes.byref(actual_format),
            ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop),
        )
        if status != 0 or not prop or nitems.value == 0:
            return None
        # _NET_WM_PID is a CARDINAL (32-bit).
        return int(ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong))[0])
    finally:
        if prop:
            x11.XFree(prop)


def _x11_store_name(x11, display, window: int, atom_net_name: int, atom_utf8: int,
                    title: str) -> None:
    x11.XChangeProperty.restype = ctypes.c_int
    x11.XChangeProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
    ]

    encoded = title.encode("utf-8")
    buf = ctypes.create_string_buffer(encoded + b"\x00")
    data = ctypes.cast(buf, ctypes.c_void_p)
    # Set _NET_WM_NAME (modern WM hint, UTF-8).
    x11.XChangeProperty(display, window, atom_net_name, atom_utf8, 8, 0, data, len(encoded))
