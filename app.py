"""Moglin Bot — cross-platform desktop client for AdventureQuest Worlds.

Moglin Bot embeds the real AQW game display (via the bundled Ruffle Flash
emulator) and drives the aqw-python automation engine from a native desktop
window (pywebview + Bottle-served web frontend).

Official website: https://www.epicalyx.org
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
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
from bot_engine import BotController, LogBus, ensure_aqw_python, find_aqw_python  # noqa: E402

_WINDOW_TITLE = f"{APP_NAME} by {WEBSITE}"
_CONFIG_PATH = os.path.join(_ROOT, "moglinbot_config.json")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_static_server(web_dir: str) -> str:
    """Serve the frontend from a local thread (avoids WebView file:// quirks)."""
    from bottle import Bottle, static_file

    app = Bottle()

    @app.route("/")
    def index():
        return static_file("index.html", root=web_dir)

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
        self._bot = BotController(self._log_bus)

    def set_window(self, window: Any) -> None:
        self._window = window

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

    def bot_monsters(self) -> list[dict]:
        return self._bot.monsters()

    def bot_quests(self) -> list[dict]:
        return self._bot.quests()

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


def main() -> None:
    api = Api()

    web_dir = _web_dir()
    url = _start_static_server(web_dir)

    window = webview.create_window(
        title=_WINDOW_TITLE,
        url=url,
        js_api=api,
        width=1200,
        height=800,
        min_size=(960, 640),
        resizable=True,
    )
    api.set_window(window)

    icon = _icon_path()
    webview.start(debug=False, icon=icon)


if __name__ == "__main__":
    main()
