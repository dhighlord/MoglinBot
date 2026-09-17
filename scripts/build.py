#!/usr/bin/env python3
"""Build Moglin Bot into a standalone executable (PyInstaller).

Usage:
    python scripts/build.py [--platform windows|linux|macos] [--onefile]

**IMPORTANT — PyInstaller cannot cross-compile.** A Windows ``.exe`` must be
built *on Windows*; a Linux binary must be built *on Linux*. The ``--platform``
flag only selects naming/icons/runtime flags for the *current* host; if it does
not match the host OS, this script refuses to run so you don't get a Linux ELF
masquerading as ``MoglinBot.exe`` (which won't launch on Windows).

The build bundles:
  - the Python app (pywebview + Bottle frontend server)
  - the ``app/web`` frontend assets
  - the aqw-python automation engine (``../aqw-python``)
  - the Ruffle Flash-emulator binary for the target platform (``vendor/ruffle``)
  - the application icon
  - the Adobe Flash projector (optional, ``vendor/flash``)

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
import platform as _platform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "app", "web")
VENDOR_DIR = os.path.join(ROOT, "vendor", "ruffle")
ENTRYPOINT = os.path.join(ROOT, "app.py")
APP_NAME = "MoglinBot"

# The aqw-python engine lives one level up in the repo (dev layout).
AQW_PYTHON_DIR = os.path.join(os.path.dirname(ROOT), "aqw-python")


def host_platform() -> str:
    """Detect the platform this build is running on."""
    sys_name = _platform.system().lower()
    if sys_name == "windows":
        return "windows"
    if sys_name == "darwin":
        return "macos"
    return "linux"


def ruffle_binary_for(platform: str) -> str:
    return "ruffle.exe" if platform == "windows" else "ruffle"


def flash_binary_for(platform: str) -> str:
    return "flashplayer.exe" if platform == "windows" else "flashplayer"


def build(platform: str, onefile: bool) -> int:
    host = host_platform()

    # PyInstaller produces a binary for the HOST OS only. Refuse a cross-build.
    if platform != host:
        print("=" * 70)
        print(f"ERROR: cannot build for '{platform}' on a '{host}' host.")
        print("PyInstaller is not a cross-compiler — the output binary is for")
        print(f"the host OS, so a '{platform}' build here would produce a")
        print(f"'{host}' binary with the wrong name/extension and would NOT run")
        print(f"on {platform}.")
        print("")
        print(f"To build for {platform}, run this command ON {platform}:")
        print(f"    python scripts/build.py --platform {platform} --onefile")
        print("=" * 70)
        return 1

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

    # Adobe Flash projector (the proven AQW renderer, rBot's runtime) ->
    # extracted under "flash/" in _MEIPASS. Optional but recommended.
    flash_name = flash_binary_for(platform)
    flash_path = os.path.join(ROOT, "vendor", "flash", flash_name)
    add_flash = f"{flash_path}{sep}flash" if os.path.isfile(flash_path) else None

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
    if add_flash:
        cmd += ["--add-data", add_flash]
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
                        default=host_platform())
    parser.add_argument("--onefile", action="store_true",
                        help="Build a single-file executable (else onedir).")
    args = parser.parse_args()
    return build(args.platform, args.onefile)


if __name__ == "__main__":
    raise SystemExit(main())

