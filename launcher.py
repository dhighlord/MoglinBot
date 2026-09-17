"""Moglin Bot launcher — catches ALL failures, even import-time crashes.

This is the PyInstaller entry point. The real app lives in ``app.py``; this
wrapper exists because a ``--noconsole`` frozen build discards stderr, so any
error (including a failed import) dies without a trace. We import ``app``
lazily inside a try/except, always write a heartbeat log, and show a native
error dialog on Windows so failures are never silent.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime


def log_path() -> str:
    base = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(base, "MoglinBot_log.txt"), os.path.join(os.path.expanduser("~"), "MoglinBot_log.txt")):
        try:
            with open(candidate, "a", encoding="utf-8"):
                pass
            return candidate
        except OSError:
            continue
    return os.path.join(os.path.expanduser("~"), "MoglinBot_log.txt")


def write_log(message: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now()}] {message}\n")
    except OSError:
        pass


def show_error(title: str, message: str) -> None:
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
        else:
            print(message, file=sys.stderr)
    except Exception:
        pass


def main() -> int:
    # Heartbeat: prove the launcher itself started.
    write_log("Launcher started. Python " + sys.version.split()[0])

    try:
        import app  # noqa: F401  (runs app.__main__ via its own guard? no)
    except BaseException as exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        write_log("FATAL during import:\n" + tb)
        show_error("Moglin Bot failed to start", f"{type(exc).__name__}: {exc}\n\nDetails in: {log_path()}")
        return 1

    # app.py's __main__ block runs main() itself when executed as a script, but
    # when imported as a module it does not. Run it explicitly.
    try:
        app.main()
    except SystemExit:
        raise
    except BaseException as exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        write_log("FATAL in app.main():\n" + tb)
        show_error("Moglin Bot failed to start", f"{type(exc).__name__}: {exc}\n\nDetails in: {log_path()}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException as exc:  # noqa: BLE001
        write_log("Launcher-level exception:\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        show_error("Moglin Bot failed to start", f"{type(exc).__name__}: {exc}\n\nDetails in: {log_path()}")
        sys.exit(1)
