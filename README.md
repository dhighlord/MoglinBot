# Moglin Bot — Cross-platform desktop client for AdventureQuest Worlds

**Moglin Bot** is a cross-platform (Windows + Linux) AQW bot/trainer with the
**real game display** and a full **trainer/bot engine**, powered by the
[`aqw-python`](../aqw-python) core.

> **Official website: [www.epicalyx.org](https://www.epicalyx.org)**

## Features

- **Real game display** — runs the actual AQW client via the bundled Ruffle
  Flash emulator (the same approach Artix's own launcher uses post-Flash-EOL).
- **Trainer** — account login, live player stats (HP/MP/gold/EXP, map/cell,
  inventory/bank counts), start/stop the bot engine.
- **Scripts** — pick from 45+ scriptable bot modules shipped with aqw-python
  (farming, questing, reputations, Nulgath/LR materials, and more).
- **Logs** — live engine output streamed to the GUI console.

## How the game display works

```
app.py  (pywebview desktop window)
   ├─ Api.launch_game()
   │    └─ ruffle_launcher.launch_game()
   │         └─ spawns:  ruffle(.exe) <AQW Loader3.swf> \
   │                      --tcp-connections allow --player-version 9 \
   │                      --width 960 --height 550 --no-gui
   └─ Api.bot_start()
        └─ bot_engine.BotController -> core.bot.Bot (aqw-python)
```

Ruffle runs the real AQW client (raw TCP socket networking via
`--tcp-connections allow`; `--no-gui` hides the toolbar). The window is
retitled to **"Moglin Bot by Epicalyx"**.

## Project layout

```
MoglinBot/
├── app.py                  # pywebview app + JS bridge (Api)
├── bot_engine.py           # bridges the aqw-python engine into the GUI
├── ruffle_launcher.py      # locates & spawns the bundled Ruffle binary
├── requirements.txt
├── app/web/                # frontend (HTML/CSS/JS)
├── vendor/ruffle/          # Ruffle binaries (ruffle / ruffle.exe)
├── MoglinBot.ico           # Windows icon
├── MoglinBot1024.png       # Linux/macOS + in-app icon
└── scripts/build.py        # PyInstaller build script
```

## Getting started (development)

```bash
# Linux (needs GTK/WebKit bindings)
python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt

# Windows
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

Run it (the aqw-python engine must be a sibling directory, i.e. `../aqw-python`):

```bash
venv/bin/python app.py          # Linux
venv\Scripts\python app.py      # Windows
```

### System requirements

- **Windows 10/11**: PyQt5 is installed automatically as a dependency and
  bundled into the executable (the self-contained QtWebEngine backend). The
  Edge WebView2 runtime is only needed as a fallback.
- **Linux**: GTK 3 + WebKit2GTK (pywebview's backend). On Debian/Ubuntu:
  ```bash
  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
  ```

## Building standalone executables

> **⚠️ PyInstaller cannot cross-compile.** A Windows `.exe` must be built **on
> Windows**; a Linux binary must be built **on Linux**. The build script now
> *refuses* `--platform windows` when run on Linux (and vice versa) rather than
> silently producing a Linux ELF named `MoglinBot.exe` that Windows can't run.

Place the Ruffle binary for the target platform in `vendor/ruffle/`, then build
**on the target OS**:

### Windows (run on Windows)

```powershell
# 1. Install Python 3.9+ (check "Add to PATH") and Git, then clone:
git clone <repo-url> MoglinBot
cd MoglinBot

# 2. Create the venv and install deps
python -m venv venv
venv\Scripts\pip install -r requirements.txt pyinstaller

# 3. Build
venv\Scripts\python scripts\build.py --platform windows --onefile
```

Output: `dist\MoglinBot.exe`. Copy that single file to any Windows 10/11
machine (it bundles the webview assets, the aqw-python engine, Ruffle, and the
Flash projector — no external dependencies beyond the built-in Edge WebView2
runtime).

### Linux (run on Linux)

```bash
python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt pyinstaller
venv/bin/python scripts/build.py --platform linux --onefile
```

Output: `dist/MoglinBot` (an ELF binary).

The Ruffle binary, the aqw-python engine, the frontend, and the icons are all
bundled into the executable and extracted at runtime, so the standalone binary
has no external dependencies.

## Notes

- **Verified**: Ruffle `0.6.0-stable` loads AQW `Loader3.swf` and reaches the
  title screen; the TCP socket flag is enabled.
- **Flash fallback**: Ruffle's AQW title-screen rendering can be incomplete on
  some hardware. Use **Open in Flash** to run the game in the bundled Adobe
  Flash 32 projector (rBot's original runtime), which is the proven AQW renderer.
- The engine reuses the fully-working aqw-python `Bot`/`Command` API (questing,
  combat, inventory, bank, navigation, drop whitelist, auto-relogin, anti-mod).

> Educational/assistive use only; ensure compliance with AQW's terms of service.
