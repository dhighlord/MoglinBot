#!/usr/bin/env python3
"""Build Moglin Bot into a standalone executable (PyInstaller).

Usage:
    python scripts/build.py [--platform windows|linux|macos] [--onefile]

The build bundles:
  - the Python app (pywebview + Bottle frontend server)
  - the ``app/web`` frontend assets
  - the aqw-python automation engine (``../aqw-python``)
  - the Ruffle Flash-emulator binary for the target platform (``vendor/ruffle``)
  - the application icon

At runtime, the Ruffle binary and the aqw-python engine are extracted into
PyInstaller's ``sys._MEIPASS`` temporary directory and located by the app, so
the standalone executable has **no external dependency** on the source tree.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "app", "web")
VENDOR_DIR = os.path.join(ROOT, "vendor", "ruffle")
ENTRYPOINT = os.path.join(ROOT, "app.py")
APP_NAME = "MoglinBot"

# The aqw-python engine lives one level up in the repo (dev layout).
AQW_PYTHON_DIR = os.path.join(os.path.dirname(ROOT), "aqw-python")


def ruffle_binary_for(platform: str) -> str:
    return "ruffle.exe" if platform == "windows" else "ruffle"


def build(platform: str, onefile: bool) -> int:
    print(f"Building {APP_NAME} for {platform} ({'onefile' if onefile else 'onedir'})...")

    # Verify the Ruffle binary exists for the target platform.
    ruffle = ruffle_binary_for(platform)
    ruffle_path = os.path.join(VENDOR_DIR, ruffle)
    if not os.path.isfile(ruffle_path):
        print(f"ERROR: Ruffle binary missing for {platform}: {ruffle_path}")
        print("       Download it from https://github.com/ruffle-rs/ruffle/releases")
        print("       and place it in vendor/ruffle/")
        return 1

    if not os.path.isdir(AQW_PYTHON_DIR):
        print(f"ERROR: aqw-python engine not found at {AQW_PYTHON_DIR}")
        return 1

    # PyInstaller data spec (POSIX uses ':', Windows uses ';').
    sep = ";" if os.name == "nt" else ":"
    add_web = f"app/web{sep}web"
    # Ruffle binary -> extracted at the _MEIPASS root.
    add_ruffle = f"{ruffle_path}{sep}."
    # aqw-python engine -> extracted under "aqw_python/" in _MEIPASS.
    add_engine = f"{AQW_PYTHON_DIR}{sep}aqw_python"
    # Icons -> extracted at the _MEIPASS root.
    ico = os.path.join(ROOT, "MoglinBot.ico")
    png = os.path.join(ROOT, "MoglinBot1024.png")
    add_ico = f"{ico}{sep}."
    add_png = f"{png}{sep}."

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        "--add-data", add_web,
        "--add-data", add_ruffle,
        "--add-data", add_engine,
        "--add-data", add_ico,
        "--add-data", add_png,
        "--paths", ROOT,
        "--paths", AQW_PYTHON_DIR,
        "--hidden-import", "requests",
        "--hidden-import", "colorama",
        "--collect-submodules", "core",
        "--collect-submodules", "commands",
        "--collect-submodules", "templates",
        "--collect-submodules", "handlers",
        "--collect-submodules", "model",
        "--collect-submodules", "abstracts",
    ]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")
    if platform != "windows":
        cmd.append("--windowed")
    if platform == "windows":
        cmd.append("--noconsole")

    # Windows app icon (embedded in the exe); Linux/macOS use the PNG via webview.
    if platform == "windows":
        cmd.append(f"--icon={ico}")
    else:
        cmd.append(f"--icon={png}")

    cmd.append(ENTRYPOINT)

    print("Executing:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print("\nBuild FAILED.")
        return result.returncode

    out_name = APP_NAME + (".exe" if platform == "windows" else "")
    out = os.path.join(ROOT, "dist", out_name)
    print("\n" + "=" * 56)
    print("BUILD SUCCESS")
    print(f"Output: {os.path.abspath(out)}")
    print("=" * 56)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["windows", "linux", "macos"],
                        default="windows" if os.name == "nt" else "linux")
    parser.add_argument("--onefile", action="store_true",
                        help="Build a single-file executable (else onedir).")
    args = parser.parse_args()
    return build(args.platform, args.onefile)


if __name__ == "__main__":
    raise SystemExit(main())
