"""Integration bridge between the Moglin Bot GUI and the aqw-python engine.

This module locates the sibling ``aqw-python`` project (dev) or the bundled
copy (frozen), makes it importable, and provides a :class:`BotController` that
runs the ``core.bot.Bot`` engine in a background thread with its own asyncio
loop. Log output from the engine is captured and made available to the GUI.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import queue
import re
import sys
import threading
from typing import Any, Callable

# Name of the bundled aqw-python package directory inside PyInstaller _MEIPASS.
BUNDLED_DIRNAME = "aqw_python"

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def aqw_python_roots() -> list[str]:
    """Candidate directories that contain the aqw-python package tree."""
    roots: list[str] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if meipass:
            roots.append(os.path.join(meipass, BUNDLED_DIRNAME))
        roots.append(os.path.join(exe_dir, BUNDLED_DIRNAME))
        roots.append(os.path.join(exe_dir, "_internal", BUNDLED_DIRNAME))
    else:
        # Development: aqw-python is a sibling of MoglinBot.
        roots.append(os.path.join(os.path.dirname(_project_root()), "aqw-python"))
    return roots


def ensure_aqw_python() -> str | None:
    """Add the aqw-python root to sys.path and return it, or None."""
    for root in aqw_python_roots():
        if os.path.isdir(os.path.join(root, "core")) and os.path.isfile(
            os.path.join(root, "core", "bot.py")
        ):
            if root not in sys.path:
                sys.path.insert(0, root)
            return root
    return None


def find_aqw_python() -> str | None:
    """Return the aqw-python root directory without mutating sys.path."""
    for root in aqw_python_roots():
        if os.path.isdir(os.path.join(root, "core")) and os.path.isfile(
            os.path.join(root, "core", "bot.py")
        ):
            return root
    return None


class LogBus:
    """Replaces sys.stdout/sys.stderr to capture engine output thread-safely."""

    def __init__(self) -> None:
        self.queue: "queue.Queue[str]" = queue.Queue()
        self._out = sys.stdout
        self._err = sys.stderr

    def write(self, message: str) -> int:
        if message:
            self.queue.put(message)
            try:
                return self._out.write(message)
            except Exception:
                return 0
        return 0

    def flush(self) -> None:
        try:
            self._out.flush()
        except Exception:
            pass

    def drain(self) -> list[str]:
        items: list[str] = []
        while True:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return items


class BotController:
    """Owns a single running aqw-python ``Bot`` and exposes its state."""

    def __init__(self, log_bus: LogBus) -> None:
        self._log_bus = log_bus
        self.bot: Any = None
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.current_module: str = ""
        self._last_error: str = ""

    # ---- lifecycle ---------------------------------------------------------
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, config: dict) -> dict:
        if self.is_running():
            return {"success": False, "error": "Bot is already running."}

        root = ensure_aqw_python()
        if not root:
            return {
                "success": False,
                "error": (
                    "aqw-python engine not found. Searched: "
                    + ", ".join(aqw_python_roots())
                ),
            }

        try:
            from core.bot import Bot
        except Exception as exc:  # pragma: no cover
            return {"success": False, "error": f"Failed to import engine: {exc}"}

        module_path = (config.get("bot_path") or "").strip()
        bot_main: Callable | None = None
        if module_path and module_path != "__idle__":
            try:
                mod = importlib.import_module(module_path)
                bot_main = getattr(mod, "main", None)
                if bot_main is None:
                    return {
                        "success": False,
                        "error": f"Bot module {module_path} has no main(cmd) function.",
                    }
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"Failed to load bot module '{module_path}': {exc}",
                }
        else:
            bot_main = _idle_main

        whitelist = config.get("whitelist") or []
        if isinstance(whitelist, str):
            whitelist = [w.strip() for w in whitelist.split("\n") if w.strip()]

        try:
            bot = Bot(
                roomNumber=int(config.get("room_number") or 1),
                itemsDropWhiteList=whitelist,
                cmdDelay=int(config.get("cmd_delay") or 1000),
                showLog=True,
                showDebug=False,
                showChat=bool(config.get("show_chat", True)),
                isScriptable=True,
                followPlayer="",
                slavesPlayer=[],
                farmClass=(config.get("farm_class") or None),
                soloClass=(config.get("solo_class") or None),
                autoRelogin=bool(config.get("auto_relogin", True)),
                muteSpamWarning=bool(config.get("mute_spam", True)),
                antiMod=bool(config.get("anti_mod", True)),
            )
            bot.set_login_info(
                config.get("username") or "",
                config.get("password") or "",
                config.get("server") or "Artix",
            )
        except Exception as exc:
            return {"success": False, "error": f"Failed to create bot: {exc}"}

        self.bot = bot
        self.current_module = module_path or "__idle__"
        self._last_error = ""

        self.thread = threading.Thread(
            target=self._run, args=(bot, bot_main), daemon=True, name="aqw-bot"
        )
        self.thread.start()
        return {"success": True}

    def stop(self) -> dict:
        if self.bot is not None:
            try:
                self.bot.stop_bot(user_triggered=True)
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        return {"success": True}

    def _run(self, bot: Any, bot_main: Callable) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(bot.start_bot(bot_main))
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            print(f"Bot engine stopped: {exc}")
        finally:
            try:
                self.loop.close()
            except Exception:
                pass

    # ---- status ------------------------------------------------------------
    def status(self) -> dict:
        if self.bot is None:
            return {"running": self.is_running(), "connected": False}

        p = self.bot.player
        running = self.is_running()
        connected = bool(self.bot.is_client_connected)

        return {
            "running": running,
            "connected": connected,
            "username": p.USER or "",
            "server": self.bot.server or "",
            "map": getattr(self.bot, "strMapName", "") or "",
            "area_name": getattr(self.bot, "areaName", "") or "",
            "cell": p.CELL or "",
            "pad": p.PAD or "",
            "gold": p.GOLD,
            "gold_farmed": p.GOLDFARMED,
            "exp_farmed": p.EXPFARMED,
            "hp": p.CURRENT_HP,
            "max_hp": p.MAX_HP,
            "mp": p.MANA,
            "max_mp": p.MAX_MP,
            "is_dead": bool(p.ISDEAD),
            "in_combat": bool(p.IS_IN_COMBAT),
            "is_member": bool(getattr(p, "is_member", False)),
            "inventory_count": len(p.INVENTORY),
            "bank_count": len(p.BANK),
            "temp_count": len(p.TEMPINVENTORY),
            "monster_count": len(getattr(self.bot, "monsters", [])),
            "player_count": len(getattr(self.bot, "user_ids", [])),
            "quest_count": len(getattr(self.bot, "loaded_quest_datas", [])),
            "module": self.current_module,
            "last_error": self._last_error,
        }

    def inventory(self, limit: int = 100) -> list[dict]:
        if self.bot is None:
            return []
        out = []
        for item in self.bot.player.INVENTORY[:limit]:
            out.append(
                {
                    "name": item.item_name,
                    "qty": item.qty,
                    "equipped": bool(item.is_equipped),
                    "acs": bool(item.is_acs),
                }
            )
        return out

    def bank(self, limit: int = 100) -> list[dict]:
        if self.bot is None:
            return []
        out = []
        for item in self.bot.player.BANK[:limit]:
            out.append({"name": item.item_name, "qty": item.qty})
        return out

    def monsters(self, limit: int = 100) -> list[dict]:
        if self.bot is None:
            return []
        out = []
        for m in getattr(self.bot, "monsters", [])[:limit]:
            out.append(
                {
                    "name": m.mon_name or ("id." + str(m.mon_map_id)),
                    "hp": m.current_hp,
                    "max_hp": m.max_hp,
                    "alive": bool(m.is_alive),
                    "cell": m.frame or "",
                }
            )
        return out

    def quests(self, limit: int = 50) -> list[dict]:
        if self.bot is None:
            return []
        out = []
        for q in getattr(self.bot, "loaded_quest_datas", [])[:limit]:
            out.append(
                {
                    "id": q.get("QuestID"),
                    "name": q.get("sName", "") or q.get("name", ""),
                }
            )
        return out

    # ---- module discovery ---------------------------------------------------
    def list_bot_modules(self) -> list[dict]:
        root = ensure_aqw_python()
        if not root:
            return []
        bot_dir = os.path.join(root, "bot")
        if not os.path.isdir(bot_dir):
            return []

        modules: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(bot_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith("_")]
            for fn in sorted(filenames):
                if not fn.endswith(".py") or fn.startswith("_"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                modpath = rel[:-3].replace(os.sep, ".")
                if modpath == "bot":
                    continue
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    continue
                # Only expose scriptable modules that define a main(cmd) entry.
                if not re.search(r"(async\s+def|def)\s+main\s*\(", text):
                    continue
                modules.append({"path": modpath, "name": modpath})
        return modules

    def drain_logs(self) -> list[str]:
        return [strip_ansi(m) for m in self._log_bus.drain()]


async def _idle_main(cmd: Any) -> None:
    """Default scriptable entry that keeps the connection alive and idle."""
    while cmd.is_still_connected():
        await cmd.sleep(1000)
