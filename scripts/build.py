#!/usr/bin/env python3
"""Build Moglin Bot into a standalone executable (PyInstaller).

Usage:
    python scripts/build.py [--platform windows|linux|macos] [--onefile]

The build bundles:
  - the Python app (pywebview + Bottle frontend server)
  - the ``app/web`` frontend assets
  - the Ruffle Flash-emulator binary for the target platform (``vendor/ruffle``)

The bundled Ruffle binary is what renders the real AQW game client, since Adobe
Flash is end-of-life. Only the binary matching the *target* platform is shipped
(``ruffle.exe`` on Windows, ``ruffle`` on Linux/macOS).

At runtime, the Ruffle binary is extracted into PyInstaller's ``sys._MEIPASS``
temporary directory and located by ``ruffle_launcher.candidate_locations()``,
so the standalone executable has **no external dependency** on ``vendor/ruffle``.
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

    # PyInstaller data spec (POSIX uses ':', Windows uses ';').
    sep = ";" if os.name == "nt" else ":"
    # Frontend assets -> extracted under "web/" in _MEIPASS.
    add_web = f"app/web{sep}web"
    # Ruffle binary -> extracted at the _MEIPASS root (named ruffle / ruffle.exe),
    # which `ruffle_launcher.candidate_locations()` finds as "bundle (_MEIPASS)".
    add_ruffle = f"{ruffle_path}{sep}."

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        "--add-data", add_web,
        "--add-data", add_ruffle,
        "--paths", ROOT,
    ]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")
    if platform != "windows":
        cmd.append("--windowed")
    if platform == "windows":
        cmd.append("--noconsole")

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
