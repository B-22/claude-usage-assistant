# Claude Usage Assistant

A tiny, always-on-top desktop card for **Windows, macOS, and Linux** that shows your **Claude Code** usage limits in real time — the 5-hour and 7-day rolling windows (plus per-model windows such as 7-day Sonnet / Opus), each with its **reset time in your local timezone**. Includes a system-tray indicator.

It does **not** bypass any limit — it just makes the official numbers visible so you can pace yourself.

English | [简体中文](README.zh-CN.md)

<p align="center">
  <img src="assets/card.png" width="430" alt="Claude Usage Assistant — the live card"><br>
  <sub>The live card: 5-hour / 7-day / per-model windows, color-coded, each with its real reset time in your local timezone.</sub>
</p>

<p align="center">
  <img src="assets/windows.png" width="300" alt="The tray shows a window's percent right in the taskbar">
  &nbsp;&nbsp;
  <img src="assets/menu.png" width="300" alt="Right-click menu">
</p>
<p align="center">
  <sub><b>Left:</b> the tray icon shows your chosen window's % right in the taskbar (the green <b>17%</b> at the bottom-left), and the card can list every window your account exposes — here 5-hour, 7-day, and 7-day · Sonnet. &nbsp;·&nbsp; <b>Right:</b> the menu lets you toggle <b>each window on the card individually</b> and pick <b>which one the tray reflects</b>.</sub>
</p>

## Features

- **Live 5-hour & 7-day usage** (and any other windows your account exposes), color-coded green / amber / red.
- **Real reset time, your timezone** — shown as a local clock like `今天 04:19` / `06-17 21:59`, derived from your system timezone (UTC+8, UTC+7, …) automatically. A live system clock sits in the footer.
- **System-tray icon** showing a chosen window's percentage with a `%` sign (default: 5-hour). Left-click toggles the card; hover for a full breakdown.
- **Frameless, draggable, always-on-top card.** Resize by mouse-wheel, by dragging the window edges/corners, or via the menu.
- **Menu** (right-click or the `☰` button): **show or hide each window on the card individually** (5-hour, 7-day, 7-day · Sonnet, …), pick **which one the tray reflects**, plus zoom, opacity, and reset-display mode (clock vs. countdown).
- Remembers position, size, opacity, and preferences. **Single-instance guard.** Optional **autostart**.
- **Cross-platform** — one file runs on Windows, macOS, and Linux; on macOS the token is read from the **Keychain** automatically, and the transparent look adapts per OS.
- Pure standard-library **tkinter** UI — no heavy UI framework. A single ~960-line file, fully auditable.

## Security & privacy

- Reads your existing Claude Code OAuth token **read-only** — from `~/.claude/.credentials.json` on Windows/Linux, or the **macOS Keychain** (via `security find-generic-password`, read-only) on macOS.
- The token is placed **only** in the `Authorization` header and sent **only** to **`api.anthropic.com`** — the same call Claude Code itself makes.
- **No telemetry, no third-party servers.** Nothing is written out, cached, or uploaded anywhere, except a local `card_state.json` holding window position and UI preferences (it contains **no** credentials).
- It only **displays** official usage; it does **not** bypass, modify, or work around any limit.
- All of it lives in [`quota_card.py`](quota_card.py) — read every line.

## Disclaimer

This tool reads usage from `https://api.anthropic.com/api/oauth/usage`, an **undocumented internal endpoint** used by Claude Code. It is not a public/official API and **may change or stop working at any time**. The endpoint URL and field names are kept as constants near the top of `quota_card.py` so a fix is a one-line change. This project is **not affiliated with or endorsed by Anthropic**.

## Platform support

|  | Windows | macOS | Linux |
|---|:---:|:---:|:---:|
| Live usage & data | ✅ | ✅ (token via Keychain) | ✅ |
| Transparent rounded card | ✅ color-key | ✅ `systemTransparent` | ▢ opaque card (square corners) |
| System tray | ✅ | ✅ | ✅ with a tray host |
| High-DPI / Retina scaling | ✅ | ✅ | ✅ |
| Single-instance guard | ✅ mutex | ✅ file lock | ✅ file lock |

One file, no per-OS build step. On Linux the card falls back to an opaque (square-cornered) look because X11 has no color-key transparency — everything else works the same. Set `QUOTA_CARD_OPAQUE=1` to force that opaque look on any OS.

## Requirements

- **Windows 10/11, macOS, or Linux**
- Python 3.10+
- [`requests`](https://pypi.org/project/requests/) (required)
- [`pystray`](https://pypi.org/project/pystray/) + [`Pillow`](https://pypi.org/project/pillow/) (optional — for the system tray; the app degrades to card-only if missing)
- You must have signed in to Claude Code at least once (so the token exists in `~/.claude/.credentials.json`, or in the macOS Keychain).
- **Linux:** a compositing window manager (the default on GNOME/KDE) for the translucency; the tray needs a system-tray / AppIndicator host.

## Install & run

```sh
pip install requests pystray pillow

python quota_card.py     # Windows
python3 quota_card.py    # macOS / Linux
```

- **Windows:** or double-click **`启动卡片.bat`** (launches with no console window).
- **macOS / Linux:** or run **`./start.sh`** (first time: `chmod +x start.sh`).

Verify the data pull without opening the UI (add `--check`):

```sh
python quota_card.py --check     # macOS/Linux: python3 quota_card.py --check
```

## Deploy from scratch

1. Install **Python 3.10+** — [python.org](https://www.python.org/downloads/) (on Windows tick **"Add python.exe to PATH"**; on macOS/Linux it's often preinstalled, or use Homebrew / your package manager).
2. Clone the repo and enter it:
   ```sh
   git clone https://github.com/huanchong-99/claude-usage-assistant
   cd claude-usage-assistant
   ```
3. Install dependencies:
   ```sh
   pip install requests pystray pillow
   ```
4. Make sure you have signed in to **Claude Code** at least once (so the token exists in `~/.claude/.credentials.json`, or in the macOS Keychain).
5. Run it:
   ```sh
   python quota_card.py        # Windows  (or double-click 启动卡片.bat)
   python3 quota_card.py       # macOS / Linux  (or ./start.sh)
   ```
6. *(Optional)* Autostart on boot — see [Autostart](#autostart-optional) below.

## One-paste AI setup

Don't want to do it by hand? Paste the block below to an AI coding assistant (e.g. **Claude Code**) and it will set everything up for you:

```text
When you read this, you are an AI coding assistant. Please deploy "Claude Usage Assistant" on this machine (it supports Windows, macOS, and Linux — detect the OS first):
1. git clone https://github.com/huanchong-99/claude-usage-assistant and cd into the folder.
2. Detect Python (3.10+) and install dependencies: pip install requests pystray pillow
3. Confirm I have signed in to Claude Code (token in ~/.claude/.credentials.json, or the macOS Keychain); if not, tell me to run `claude` and log in first.
4. Run the app (python quota_card.py on Windows, python3 quota_card.py on macOS/Linux) and verify the card shows my usage; if it errors, diagnose and fix it.
5. Ask whether I want it to start automatically on boot; if yes, set it up the right way for my OS (Windows: a shortcut in shell:startup; macOS: a Login Item or LaunchAgent; Linux: a ~/.config/autostart entry).
Report back in my language when done.
```

## Controls

- **Drag** the card to move it (position is remembered).
- **Mouse-wheel** to zoom · **drag window edges/corners** to resize · **Ctrl + wheel** to fine-tune opacity.
- **Top bar:** `▲` keep-on-top · `☰` menu · `↻` refresh · `✕` quit.
- **Menu** (right-click or `☰`): Refresh · **Card items** (tick each window — 5-hour / 7-day / 7-day · Sonnet … — to show or hide it on the card) · **Tray item** (which window's % the tray shows) · Zoom · Opacity · Reset display · Keep on top · Hide to tray · Quit.
- **Tray icon:** shows the selected window's `%`; left-click toggles the card; right-click for the menu.

Bar colors: green `< 50%`, amber `50–80%`, red `≥ 80%`.

## Configuration

Constants near the top of `quota_card.py`:

- `REFRESH_INTERVAL` — auto-refresh seconds (default `60`).
- `API_URL_USAGE` and the field names — edit here if the endpoint ever changes.

Preferences (position, zoom, opacity, shown items, tray item, reset mode) are saved to `card_state.json`.

**Environment variables:**

- `QUOTA_CARD_OPAQUE=1` — force an opaque, square-cornered card on any OS (handy on Linux/macOS if the transparent corners ever render oddly).
- `CLAUDE_CONFIG_DIR` — if you point Claude Code at a custom config dir, the app honors it too.

## Autostart (optional)

- **Windows:** press `Win + R`, type `shell:startup`, and drop a shortcut to `启动卡片.bat` (or to `pythonw.exe "…\quota_card.py"`) into that folder.
- **macOS:** add a **Login Item** (System Settings → General → Login Items → ＋, pick `start.sh`), or install a LaunchAgent plist that runs `python3 …/quota_card.py`.
- **Linux:** drop a `.desktop` file into `~/.config/autostart/` whose `Exec=` runs `python3 /path/to/quota_card.py` (or `/path/to/start.sh`).

## Friend Links

- [LINUX DO](https://linux.do/) — a community for developers and tech enthusiasts.

## Credits

- Data approach referenced from [jens-duttke/usage-monitor-for-claude](https://github.com/jens-duttke/usage-monitor-for-claude).
- The official `rate_limits` field is documented in the [Claude Code status line docs](https://code.claude.com/docs/en/statusline).

## License

[MIT](LICENSE)
