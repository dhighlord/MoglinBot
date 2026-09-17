"""Moglin Bot — cross-platform desktop client for AdventureQuest Worlds.

Moglin Bot embeds the real AQW game display (via the bundled Ruffle Flash
emulator) and drives the aqw-python automation engine from a native desktop
window (pywebview + Bottle-served web frontend).

Official website: https://www.epicalyx.org
"""

from __future__ import annotations

import json
import os
import asyncio
import socket
import subprocess
import sys
import threading
import traceback
from typing import Any

import webview

# Make the repo root importable so we can import the local modules.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ruffle_launcher import (  # noqa: E402
    APP_NAME,
    AQW_LOADER_URL,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    WEBSITE,
    is_process_running,
    launch_game,
    ruffle_status,
)
from bot_engine import (  # noqa: E402
    BotController,
    LiveBotController,
    LogBus,
    ensure_aqw_python,
    find_aqw_python,
)
from live_client import LiveClient  # noqa: E402

_WINDOW_TITLE = f"{APP_NAME} by {WEBSITE}"

# Local WebSocket<->TCP relay port, so the game's flash.net.Socket can reach
# AQW's servers from inside the Ruffle web player (browsers can't open raw TCP).
RELAY_PORT = 8088


def _start_relay() -> None:
    """Run the WS<->TCP relay in a background thread with its own event loop."""
    from ws_relay import TcpWsRelay

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(TcpWsRelay("127.0.0.1", RELAY_PORT).serve_forever())
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name="ws-relay").start()


def _config_dir() -> str:
    """Return a writable, persistent config directory.

    In frozen builds ``__file__`` lives in PyInstaller's temp ``_MEIPASS``
    directory which is deleted on exit, so we use the user's home directory
    instead. In development we keep it next to the source for convenience.
    """
    if getattr(sys, "frozen", False):
        d = os.path.join(os.path.expanduser("~"), ".moglinbot")
    else:
        d = _ROOT
    os.makedirs(d, exist_ok=True)
    return d


_CONFIG_PATH = os.path.join(_config_dir(), "moglinbot_config.json")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_static_server(web_dir: str) -> str:
    """Serve the frontend from a local thread (avoids WebView file:// quirks).

    Also proxies AQW game HTTP requests (game.aq.com) so the game client can
    fetch its version/manifest from a same-origin URL (game.aq.com does not
    send CORS headers, which blocks cross-origin fetches from the webview).
    """
    import requests as _requests
    from bottle import Bottle, static_file, request as _request, response as _response

    app = Bottle()

    @app.route("/")
    def index():
        return static_file("index.html", root=web_dir)

    # Proxy for the game's HTTP API. The game client requests
    # https://game.aq.com/game/... — we rewrite to /proxy/game/... and relay.
    @app.route("/proxy/<path:path>")
    def proxy(path):
        target = f"https://game.aq.com/{path}"
        if _request.query_string:
            target += "?" + _request.query_string
        try:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            }
            if _request.method == "POST":
                resp = _requests.post(
                    target, data=_request.body.read(), headers=headers, timeout=30
                )
            else:
                resp = _requests.get(target, headers=headers, timeout=30)
            _response.status = resp.status_code
            _response.content_type = resp.headers.get("Content-Type", "application/octet-stream")
            _response.set_header("Access-Control-Allow-Origin", "*")
            return resp.content
        except Exception as exc:
            _response.status = 502
            return f"Proxy error: {exc}"

    @app.route("/<path:path>")
    def assets(path):
        return static_file(path, root=web_dir)

    port = _free_port()
    t = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, quiet=True), daemon=True
    )
    t.start()
    return f"http://127.0.0.1:{port}"


_DEFAULT_CONFIG = {
    "username": "",
    "password": "",
    "server": "Artix",
    "room_number": 1,
    "cmd_delay": 1000,
    "bot_path": "__idle__",
    "farm_class": "",
    "solo_class": "",
    "whitelist": [],
    "auto_relogin": True,
    "show_chat": True,
    "mute_spam": True,
    "anti_mod": True,
}


class Api:
    """JS-accessible bridge (``window.pywebview.api.*``)."""

    def __init__(self) -> None:
        self._window: Any = None
        self._game_proc: subprocess.Popen | None = None
        self._log_bus = LogBus()
        self._live = LiveClient()
        self._bot = LiveBotController(self._log_bus, self._live)
        # Redirect stdout/stderr so the aqw-python engine's print() output is
        # captured and streamed to the GUI console.
        sys.stdout = self._log_bus
        sys.stderr = self._log_bus

    def set_window(self, window: Any) -> None:
        self._window = window
        # Route live-client JS calls through the webview.
        self._live.set_eval_js(lambda js: window.evaluate_js(js))

    # ---- live game client (called from the Ruffle embed in JS) -------------
    def game_loaded(self) -> dict:
        """JS signals the game has fully loaded in the Ruffle player."""
        self._live.mark_game_loaded()
        return {"success": True}

    def game_closed(self) -> dict:
        self._live.mark_game_closed()
        return {"success": True}

    def game_packet(self, packet: str) -> dict:
        """JS forwards a server packet from the live client."""
        self._live.on_packet(packet)
        return {"success": True}

    def game_pext(self, packet: str) -> dict:
        self._live.on_pext(packet)
        return {"success": True}

    def game_debug(self, message: str) -> dict:
        self._live.on_debug(message)
        return {"success": True}

    # ---- game display -----------------------------------------------------
    def launch_game(self, url: str | None = None) -> dict:
        """Launch the bundled Ruffle player pointed at the AQW game SWF."""
        if is_process_running(self._game_proc):
            return {"success": False, "error": "Game window is already open."}
        try:
            self._game_proc = launch_game(url or AQW_LOADER_URL)
            return {"success": True, "pid": self._game_proc.pid}
        except FileNotFoundError as exc:
            return {"success": False, "error": str(exc)}
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

    def launch_flash(self) -> dict:
        """Launch the game in the real Adobe Flash projector (rBot's runtime).

        The Ruffle web embed renders AQW's title black on some setups; the
        official Flash 32 standalone projector is the exact runtime rBot used
        and is the proven renderer for AQW. It is looked up in the bundle's
        ``vendor/flash`` directory (Windows: flashplayer.exe, Linux: flashplayer).
        """
        import platform as _platform

        system = _platform.system().lower()
        name = "flashplayer.exe" if system == "windows" else "flashplayer"
        root = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            candidates = [
                os.path.join(meipass, "flash", name) if meipass else "",
                os.path.join(root, "flash", name),
                os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "flash", name),
            ]
        else:
            candidates = [os.path.join(root, "vendor", "flash", name)]
        flash = next((c for c in candidates if c and os.path.isfile(c)), None)
        if not flash:
            return {
                "success": False,
                "error": (
                    "Flash projector not found. Place the official Adobe Flash 32 "
                    "standalone projector at vendor/flash/"
                    + name
                ),
            }
        if is_process_running(self._game_proc):
            return {"success": False, "error": "Game window is already open."}
        try:
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if os.name == "nt":
                kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                kwargs["start_new_session"] = True
            self._game_proc = subprocess.Popen([flash, AQW_LOADER_URL], **kwargs)
            return {"success": True, "pid": self._game_proc.pid}
        except OSError as exc:
            return {"success": False, "error": f"Failed to start Flash: {exc}"}

    def close_game(self) -> dict:
        if is_process_running(self._game_proc):
            try:
                self._game_proc.terminate()
            except Exception:
                pass
        self._game_proc = None
        return {"success": True}

    def game_status(self) -> dict:
        running = is_process_running(self._game_proc)
        return {
            "running": running,
            "pid": self._game_proc.pid if running else None,
            "ruffle": ruffle_status(),
        }

    # ---- bot engine -------------------------------------------------------
    def bot_start(self, config: dict) -> dict:
        return self._bot.start(config)

    def bot_stop(self) -> dict:
        return self._bot.stop()

    def bot_status(self) -> dict:
        return self._bot.status()

    def bot_inventory(self) -> list[dict]:
        return self._bot.inventory()

    def bot_bank(self) -> list[dict]:
        return self._bot.bank()

    def bot_modules(self) -> list[dict]:
        return self._bot.list_bot_modules()

    def bot_logs(self) -> list[str]:
        return self._bot.drain_logs()

    # ---- info / branding --------------------------------------------------
    def app_info(self) -> dict:
        return {
            "name": APP_NAME,
            "website": WEBSITE,
            "website_url": "https://www.epicalyx.org",
            "engine_ready": find_aqw_python() is not None,
            "engine_path": find_aqw_python() or "",
        }

    # ---- settings ---------------------------------------------------------
    def load_settings(self) -> dict:
        cfg = dict(_DEFAULT_CONFIG)
        try:
            if os.path.exists(_CONFIG_PATH):
                with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
                    cfg.update(json.load(fh))
        except Exception:
            pass
        cfg["engine_ready"] = find_aqw_python() is not None
        return cfg

    def save_settings(self, settings: dict) -> dict:
        try:
            clean = {k: settings.get(k, v) for k, v in _DEFAULT_CONFIG.items()}
            tmp = _CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(clean, fh, indent=2)
            os.replace(tmp, _CONFIG_PATH)
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


def _web_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "web")
    return os.path.join(_ROOT, "app", "web")


def _icon_path() -> str | None:
    """Return an icon path usable by pywebview (GTK/QT) when available."""
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, "MoglinBot1024.png"))
        candidates.append(os.path.join(_ROOT, "MoglinBot1024.png"))
    else:
        candidates.append(os.path.join(_ROOT, "MoglinBot1024.png"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _crash_log_path() -> str:
    """Return a writable log file path for uncaught exceptions.

    In a PyInstaller ``--noconsole`` build, stderr is discarded, so startup
    errors vanish silently. We write them to ``MoglinBot_crash.log`` next to the
    executable (or in the user's home dir if that's not writable).
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = _ROOT
    candidate = os.path.join(base, "MoglinBot_crash.log")
    try:
        with open(candidate, "a", encoding="utf-8"):
            pass
        return candidate
    except OSError:
        return os.path.join(os.path.expanduser("~"), "MoglinBot_crash.log")


def _log_exception(exc: BaseException) -> None:
    """Append an exception + traceback to the crash log."""
    path = _crash_log_path()
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 60 + "\n")
            fh.write(f"[{__import__('datetime').datetime.now()}] Uncaught exception:\n")
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            fh.write("=" * 60 + "\n")
    except OSError:
        pass


def _trace(message: str) -> None:
    """Append a step marker to the launcher log file (bypasses redirected stdout).

    This is for diagnosing silent startup failures in --noconsole frozen builds.
    """
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(os.path.abspath(sys.executable))
        else:
            base = _ROOT
        path = os.path.join(base, "MoglinBot_log.txt")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{__import__('datetime').datetime.now()}] {message}\n")
    except OSError:
        pass


def _check_windows_webview2() -> None:
    """Fail loudly if the Edge WebView2 runtime is missing on Windows.

    pywebview's Windows backend (EdgeChromium) requires the WebView2 runtime,
    which is absent on some systems. Without a console, the failure is silent,
    so we detect it up front and raise a clear error.
    """
    if os.name != "nt":
        return
    _trace("webview2 check: importing edgechromium backend...")
    try:
        import ctypes
        # WebView2Loader.dll is shipped with pywebview; its absence or an
        # inability to find the runtime surfaces as an OSError on import/init.
        import webview.platforms.edgechromium  # noqa: F401
        _trace("webview2 check: edgechromium import OK")
    except Exception as exc:  # noqa: BLE001
        _trace(f"webview2 check FAILED: {exc}")
        raise RuntimeError(
            "Edge WebView2 runtime is required but could not be loaded. "
            "Install it from https://developer.microsoft.com/microsoft-edge/webview2/ "
            f"(detail: {exc})"
        ) from exc

    # Check the WebView2 runtime is actually installed (not just the Python shim).
    _trace("webview2 check: probing runtime registry...")
    import winreg
    found = False
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ):
            try:
                with winreg.OpenKey(root, sub) as k:
                    val, _ = winreg.QueryValueEx(k, "pv")
                    _trace(f"webview2 runtime found: {val}")
                    found = True
                    break
            except OSError:
                continue
        if found:
            break
    if not found:
        _trace("webview2 runtime NOT FOUND in registry")
        raise RuntimeError(
            "The Microsoft Edge WebView2 runtime is not installed. "
            "Download and install it from:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/"
        )
    _trace("webview2 check passed")


def main() -> None:
    _trace("app.main() entered")
    _check_windows_webview2()
    _trace("webview2 check passed")

    api = Api()
    _trace("Api() created")

    # Start the WS<->TCP relay so the game's socket can reach AQW servers.
    _start_relay()
    _trace("relay started")

    web_dir = _web_dir()
    _trace(f"web_dir = {web_dir}")
    url = _start_static_server(web_dir)
    _trace(f"static server at {url}")

    window = webview.create_window(
        title=_WINDOW_TITLE,
        url=url,
        js_api=api,
        width=1200,
        height=800,
        min_size=(960, 640),
        resizable=True,
        focus=True,
    )
    _trace("window created")
    api.set_window(window)
    _trace("api.set_window done")

    icon = _icon_path()
    _trace(f"icon = {icon}")

    # ---- backend selection (Windows) ---------------------------------------
    # EdgeChromium depends on pythonnet/.NET/WebView2 interop, which is fragile
    # under PyInstaller onefile and can block webview.start() with no window and
    # no error. Prefer the self-contained Qt backend when available.
    gui = None
    if os.name == "nt":
        try:
            import PyQt5  # noqa: F401
            gui = "qt"
            _trace("backend: using qt (PyQt5 detected)")
        except ImportError:
            gui = "edgechromium"
            _trace("backend: PyQt5 missing, using edgechromium")

    _trace("calling webview.start() ...")

    # Watchdog: if no window shows within 15s on Windows, raise a visible error
    # instead of blocking forever with no feedback.
    if os.name == "nt":
        def _watchdog():
            import time as _time
            _time.sleep(15)
            try:
                import webview as _wv
                shown = False
                for w in _wv.windows:
                    try:
                        if w.events.shown.is_set():
                            shown = True
                            break
                    except Exception:
                        continue
                _trace(f"watchdog: {len(_wv.windows)} window(s), shown={shown}")
                if _wv.windows and not shown:
                    _trace("watchdog: window failed to show — forcing exit")
                    import ctypes as _ctypes
                    _ctypes.windll.user32.MessageBoxW(
                        0,
                        "Moglin Bot could not open its window.\n\n"
                        "The GUI backend failed to initialize. Please install the "
                        "Microsoft Edge WebView2 runtime or report this log.",
                        "Moglin Bot",
                        0x10,
                    )
                    import os as _os
                    _os._exit(3)
            except Exception as exc:  # noqa: BLE001
                _trace(f"watchdog error: {exc}")
        threading.Thread(target=_watchdog, daemon=True).start()

    webview.start(debug=False, icon=icon, gui=gui)
    _trace("webview.start() returned")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        _log_exception(exc)
        # Surface the error to the user in a way that works headless (frozen)
        # without a console: show a native message box if possible, else re-raise.
        try:
            if getattr(sys, "frozen", False) and os.name == "nt":
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "Moglin Bot failed to start.\n\n"
                    f"{type(exc).__name__}: {exc}\n\n"
                    f"Details logged to:\n{_crash_log_path()}",
                    "Moglin Bot Error",
                    0x10,  # MB_ICONERROR
                )
            else:
                print(f"Fatal error: {exc}", file=sys.stderr)
                traceback.print_exc()
        except Exception:
            pass
        raise
