# Moglin Bot — Cross-platform desktop client for AdventureQuest Worlds

**Moglin Bot** is a running, cross-platform (Windows + Linux) GUI shell for a
new AQW bot/trainer, with the **real game display** — the actual AQW client —
working today.

> **Official website: [www.epicalyx.org](https://www.epicalyx.org)**

The trainer/bot features (questing, combat, inventory, bank, drop whitelist,
auto-relogin, anti-mod, etc.) build on the already-working
[`aqw-python`](../aqw-python) core and land in the next milestone. This
milestone delivers the running GUI and the game screen.

---

## The problem it solves

`RBot` (the 6-year-old C# bot) shows a black screen because it embedded the game
through Adobe's **Flash ActiveX control**, which is end-of-life and uninstallable
now. `aqw-python` works but is CLI-only.

AQW's game client is still a **Flash SWF** (`game.aq.com/game/gamefiles/Loader3.swf`).
This project runs that SWF using **Ruffle** — an open-source Flash emulator
(Rust → native binary) — the *same* mechanism Artix's own cross-platform
"Artix Games Launcher" uses to keep its Flash games playable post-EOL.

## How the game display works

```
app.py  (pywebview desktop window)
   └─ Api.launch_game()
        └─ ruffle_launcher.launch_game()
             └─ spawns:  ruffle(.exe) <AQW Loader3.swf> \
                          --tcp-connections allow --player-version 9 \
                          --width 960 --height 550 --no-gui
```

Ruffle runs the real AQW client. AQW's networking uses `flash.net.Socket`
(raw TCP + null-terminated messages), which is why we pass
`--tcp-connections allow` — the exact flag Artix's launcher uses. `--no-gui`
hides Ruffle's own menu/toolbar for a clean game window, and the window title
is retitled to **"Moglin Bot by www.epicalyx.org"** via the OS window API
(Ruffle has no `--title` flag).

## Project layout

```
MoglinBot/
├── app.py                  # pywebview app + JS bridge (Api)
├── ruffle_launcher.py      # locates & spawns the bundled Ruffle binary
├── requirements.txt
├── app/web/                # frontend (HTML/CSS/JS)
│   ├── index.html
│   ├── style.css
│   └── main.js
├── vendor/ruffle/          # Ruffle Flash-emulator binaries (per platform)
│   ├── ruffle              # Linux/macOS
│   └── ruffle.exe          # Windows
└── scripts/build.py        # PyInstaller build script
```

## Getting started (development)

```bash
# Linux (needs GTK/WebKit bindings; see below)
python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt

# Windows
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

Run it:

```bash
venv/bin/python app.py          # Linux
venv\Scripts\python app.py      # Windows
```

Click **Launch Game** — the AQW client opens in a Ruffle window.

### System requirements

- **Windows 10/11**: Edge WebView2 runtime (bundled with Windows, or install it).
  Ruffle renders via its own window, so no WebView2 GPU feature is required.
- **Linux**: GTK 3 + WebKit2GTK (pywebview's backend). On Debian/Ubuntu:
  ```bash
  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
  ```
  (pywebview falls back to Qt if you install `PyQt5`/`PyQt6`/`PySide6` instead.)

## Building standalone executables

First download the Ruffle binary for the **target** platform from
<https://github.com/ruffle-rs/ruffle/releases> and place it in `vendor/ruffle/`:

| Target  | Ruffle file                     |
|---------|---------------------------------|
| Windows | `ruffle.exe` (windows-x86_64)   |
| Linux   | `ruffle`     (linux-x86_64)     |
| macOS   | `ruffle`     (macos-universal)  |

Then build **on the target OS** (PyInstaller is not cross-compiling):

```bash
# Windows
venv\Scripts\pip install pyinstaller
venv\Scripts\python scripts/build.py --platform windows --onefile

# Linux
venv/bin/pip install pyinstaller
venv/bin/python scripts/build.py --platform linux --onefile
```

The output lands in `dist/`. The Ruffle binary is bundled into the executable
and extracted at runtime into PyInstaller's `_MEIPASS` temp directory, then
located by `ruffle_launcher.candidate_locations()`. **The standalone executable
has no external dependency on `vendor/ruffle/`.**

## Notes / roadmap

- **Verified**: the bundled Ruffle `0.6.0-stable` loads AQW `Loader3.swf`,
  fetches `Game3098r27.swf` and the `Generic2.swf` background, and reaches the
  title screen. The socket flag is present and enabled.
- **Next milestone**: wire the `aqw-python` `Bot`/`Command` engine into `Api`
  so the Trainer/Scripts tabs get real automation (questing, combat, inventory,
  bank, navigation, drop whitelist, auto-relogin, anti-mod).

> Educational/assistive use only; ensure compliance with AQW's terms of service.
