"""Moglin Bot — cross-platform desktop client for AdventureQuest Worlds.

Moglin Bot is the front-end for a new AQW bot/trainer. It embeds the *real* AQW
game display by launching the bundled Ruffle Flash emulator (the same mechanism
Artix's own launcher uses post-Flash-EOL) and provides a native-looking desktop
window (via pywebview + a Bottle-served web frontend) for trainer/bot features.

Official website: https://www.epicalyx.org
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from typing import Any

import webview

# Make the repo root importable so we can (later) import aqw-python's core.
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

_WINDOW_TITLE = f"{APP_NAME} by {WEBSITE}"


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


class Api:
    """JS-accessible bridge (``window.pywebview.api.*``)."""

    def __init__(self) -> None:
        self._window: Any = None
        self._game_proc: subprocess.Popen | None = None

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

    # ---- info / branding --------------------------------------------------
    def app_info(self) -> dict:
        return {
            "name": APP_NAME,
            "website": WEBSITE,
            "website_url": f"https://{WEBSITE}",
        }

    # ---- settings ---------------------------------------------------------
    def load_settings(self) -> dict:
        return {
            "game_url": AQW_LOADER_URL,
            "width": DEFAULT_WIDTH,
            "height": DEFAULT_HEIGHT,
        }

    def save_settings(self, settings: dict) -> dict:
        # Persisted in a later milestone; accept and echo for now.
        return {"success": True}


def _web_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "web")
    return os.path.join(_ROOT, "app", "web")


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
    webview.start(debug=False)


if __name__ == "__main__":
    main()
