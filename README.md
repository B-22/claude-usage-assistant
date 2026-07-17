# AI Usage Assistant (Claude / Codex / Gemini)

A tiny, always-on-top desktop card for **Windows, macOS, and Linux** that shows your **Claude Code**, **OpenAI Codex**, and **Google Gemini** usage limits in real time — the 5-hour and 7-day / weekly rolling windows (plus per-model windows such as Claude's 7-day Sonnet / Opus / Fable), each with its **reset time in your local timezone**. Mix and match **any of the three sources**. Includes a system-tray indicator.

It does **not** bypass any limit — it just makes the official numbers visible so you can pace yourself.

> **Refreshes without the terminal.** If you use only the **Claude desktop app / Cowork**, you've probably hit "the local token expired, usage won't refresh" — because the card read only the CLI's credential file, and if you never run the CLI, nothing keeps that file fresh. The card now **reuses the desktop app's continuously-refreshed login token** (read-only, decrypted locally) and **auto-refreshes the CLI credential via its refreshToken** when needed. **Result: usage keeps refreshing without ever going back to `claude` in a terminal.**

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

- **Claude, Codex, and Gemini together** — show **any combination** (toggle in the menu). With multiple sources the card splits into per-source sections, each with its own plan badge (e.g. Claude `MAX`, Codex `PRO LITE`).
- **No terminal login, tokens don't go stale** — prefers the **Claude desktop app's** continuously-refreshed token; when using the CLI credential it **auto-refreshes via refreshToken and writes it back**. Codex works the same way (reads `~/.codex/auth.json` and auto-refreshes). All local, read-only against your existing login.
- **Live 5-hour & 7-day (weekly) usage** (and any other windows your account exposes), color-coded green / amber / red.
- **Stale data turns red immediately** — if a source fails to refresh (rate-limit backoff, network drop, dead token, Gemini tab closed… **or it silently stalls with no error at all**), that source's **title and dot go red**, with how long it's been stale next to it, and the footer names exactly which source is lagging. **The card never passes an old number off as current** — you can always tell at a glance whether to trust the percentage.
- **Real reset time, your timezone** — shown as a local clock like `今天 04:19` / `06-17 21:59`, derived from your system timezone (UTC+8, UTC+7, …) automatically. A live system clock sits in the footer.
- **System-tray icon** showing a chosen window's percentage with a `%` sign (default: Claude 5-hour). Left-click toggles the card; hover for a full breakdown.
- **Follows your system theme** — light/dark switch automatically (Windows reads `AppsUseLightTheme`, macOS `AppleInterfaceStyle`, Linux `gsettings`); or lock it to light or dark from the menu. **Change your system theme while it's running and the card catches up within 10s**, tray icon included — no restart.
- **Optional title** — turn it off from the menu for a tighter card: just the dot and the plan badge.
- **Frameless, draggable, always-on-top card.** Resize by mouse-wheel, by dragging the window edges/corners, or via the menu.
- **Menu** (right-click or the `☰` button): **pick data sources** (Claude / Codex / Gemini), **show or hide each window individually**, pick **which one the tray reflects**, plus zoom, opacity, and reset-display mode (clock vs. countdown).
- Remembers position, size, opacity, sources, and preferences. **Single-instance guard.** Optional **autostart**.
- **Cross-platform** — one file runs on Windows, macOS, and Linux; the transparent look adapts per OS.
- Pure standard-library **tkinter** UI — no heavy UI framework. A single file, fully auditable.

## Where the token comes from · why it stops expiring

The card only uses the login state **already on your machine**, picking whichever copy is freshest so you don't have to think about it:

**Claude** (uses the currently-valid, freshest copy):
1. **Desktop-app token** — reads the OAuth cache in the Claude desktop app / Cowork `config.json` and **decrypts it locally** (Windows: system DPAPI + BCrypt via pure `ctypes`, no extra dependency; macOS/Linux: best-effort). The desktop app keeps this refreshed, so it's **always alive** — this is what makes "refreshes even when you only use the desktop app" work.
2. **CLI credential** `~/.claude/.credentials.json` — when near expiry, **auto-refreshed via its refreshToken and written back** (atomic write, `0600` perms).
3. **macOS Keychain** — `security find-generic-password` (read-only), auto-refreshed the same way.

Desktop-app tokens are **read-only** — the card never refreshes them. An OAuth refreshToken is **single-use**: the moment a third party redeems one, the desktop app's copy is dead and it gets logged out. So that path simply doesn't exist here.

**Codex:** reads `~/.codex/auth.json` (ChatGPT login mode); when near expiry or rejected, **auto-refreshes via its refreshToken and writes it back**.

**Gemini:** the web app's quota lives only in your **browser session** — there's no CLI credential to read, and since Chrome 127+ cookies are sealed with App-Bound Encryption (`v20`), which the system DPAPI key cannot open (getting around it means impersonating the browser's COM elevation service or killing a browser subprocess to race the file — this project does neither). So Gemini works in reverse: a userscript, [`gemini_bridge.user.js`](gemini_bridge.user.js), reads the numbers **in the page, using the page's own session**, and `POST`s the two percentages to the card listening on `127.0.0.1:47615`. **The card never touches a Google credential.**

> To install: right-click the card → **Data sources → Install Gemini script…** The card serves the script with the port already filled in, so your userscript manager just shows its install page — nothing to edit by hand. With a Gemini tab open you get live numbers; close the tab and the card shows the last value and when it arrived. Requires a userscript manager such as [Tampermonkey](https://www.tampermonkey.net/).

- The token goes **only** in the `Authorization` header: Claude only to **`api.anthropic.com`**, Codex only to **`chatgpt.com`** — the same calls their official clients make.
- The local listener binds **only** to `127.0.0.1` (unreachable from the network), accepts **only** Gemini's two percentages, and cross-origin writes die at the CORS preflight — only `https://gemini.google.com` is allowed through.
- **No telemetry, no third-party servers.** Nothing is written out, cached, or uploaded anywhere, except refreshing **your own** credential files and a local `card_state.json` holding UI preferences (it contains **no** credentials).
- Decrypting the desktop token is **entirely local** and reads only what your current Windows/macOS user is already entitled to decrypt (the same protection the OS gives the desktop app); it never touches, rewrites, or uploads it.
- It only **displays** official usage; it does **not** bypass, modify, or work around any limit.
- All of it lives in [`quota_card.py`](quota_card.py) — read every line.

## Disclaimer

This tool reads usage from `https://api.anthropic.com/api/oauth/usage` (Claude), `https://chatgpt.com/backend-api/wham/usage` (Codex), and `gemini.google.com`'s `batchexecute` (Gemini, called in-page by the userscript) — all **undocumented internal endpoints** used by their respective clients. None is a public/official API, and **any of them may change or stop working at any time**. Endpoint URLs and field names are kept as constants near the top of `quota_card.py` so a fix is a one-line change. This project is **not affiliated with or endorsed by Anthropic, OpenAI, or Google**.

> **About Claude's 429s.** `/api/oauth/usage` is rate-limited **per account**, and **every Claude Code session** plus the desktop app itself background-polls the same bucket ([claude-code#30930](https://github.com/anthropics/claude-code/issues/30930)). Poll it hard and everyone eats 429s together.
>
> This card's approach is **fast when healthy, back off on impact**: a real request every 60s (`CLAUDE_MIN_INTERVAL`); on an actual 429 it backs off per `retry-after` (that header sometimes says `0`, which is not to be trusted — then it falls back to a 120→900s exponential backoff), sends **nothing at all** while backing off, and keeps showing the last numbers. That beats blanket slow polling: data is fresh when things are fine, and it yields only when they aren't — and **the moment data goes stale the card turns red** (below), so an old number never masquerades as a current one.
>
> If you run many Claude Code sessions and hit 429s often, just raise `CLAUDE_MIN_INTERVAL`. Also worth knowing: **the reset countdown is computed locally from `resets_at`, so it stays exact even when the percentage is stale.**

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
- **Claude:** signed in to Claude at least once — **the desktop app alone is enough**, or a terminal `claude` login (token in `~/.claude/.credentials.json` / macOS Keychain).
- **Codex (optional):** signed in to OpenAI Codex (`codex` login → `~/.codex/auth.json`). No Codex? Just leave only Claude ticked in the menu.
- **Desktop-token decryption (optional enhancement):** works out of the box on Windows (system-provided, no extra dependency); on macOS/Linux, `pip install cryptography` enables reading the desktop token, otherwise it falls back to the CLI credential.
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
4. Make sure you have signed in to **Claude** at least once — the **desktop app alone is enough**, or a terminal `claude` login. *(Optional: sign in to **Codex** with `codex` for the second source.)*
5. Run it:
   ```sh
   python quota_card.py        # Windows  (or double-click 启动卡片.bat)
   python3 quota_card.py       # macOS / Linux  (or ./start.sh)
   ```
6. *(Optional)* Autostart on boot — see [Autostart](#autostart-optional) below.

## One-paste AI setup

Don't want to do it by hand? Paste the block below to an AI coding assistant (e.g. **Claude Code**) and it will set everything up for you:

```text
When you read this, you are an AI coding assistant. Please deploy "AI Usage Assistant (Claude / Codex)" on this machine (it supports Windows, macOS, and Linux — detect the OS first):
1. git clone https://github.com/huanchong-99/claude-usage-assistant and cd into the folder.
2. Detect Python (3.10+) and install dependencies: pip install requests pystray pillow (on macOS/Linux add cryptography if I want the desktop token read).
3. Confirm I have signed in to Claude (the Claude desktop app is enough, or a terminal `claude` login; token in ~/.claude/.credentials.json or the macOS Keychain). If I also use OpenAI Codex, confirm I'm logged in (`codex` → ~/.codex/auth.json).
4. Run the app (python quota_card.py on Windows, python3 quota_card.py on macOS/Linux) and verify the card shows my usage; if it errors, diagnose and fix it. You can run `python quota_card.py --check` for a quick self-test.
5. Ask whether I want it to start automatically on boot; if yes, set it up the right way for my OS (Windows: a shortcut in shell:startup; macOS: a Login Item or LaunchAgent; Linux: a ~/.config/autostart entry).
Report back in my language when done.
```

## Controls

- **Drag** the card to move it (position is remembered).
- **Mouse-wheel** to zoom · **drag window edges/corners** to resize · **Ctrl + wheel** to fine-tune opacity.
- **Top bar:** `▲` keep-on-top · `☰` menu · `↻` refresh · `✕` quit.
- **Menu** (right-click or `☰`): Refresh · **Data sources** (tick Claude / Codex / Gemini — multi-select; **Install Gemini script…** at the bottom) · **Card items** (show or hide each window) · **Tray item** (which window's % the tray shows) · Zoom · Opacity · Reset display · **Theme** (follow system / light / dark) · **Show title** · Keep on top · Click-through · Hide to tray · Quit.
- **Tray icon:** shows the selected window's `%`; left-click toggles the card; right-click for the menu.

Bar colors: green `< 50%`, amber `50–80%`, red `≥ 80%`.

## Configuration

Constants near the top of `quota_card.py`:

- `REFRESH_INTERVAL` — UI polling tick, in seconds (default `60`).
- `CLAUDE_MIN_INTERVAL` — minimum seconds between **real** Claude requests (default `60`). Raise it if you hit 429s often (see "About Claude's 429s" above).
- `CLAUDE_BACKOFF_MIN` / `CLAUDE_BACKOFF_MAX` — exponential backoff range used on a 429 when `retry-after` isn't trustworthy (default `120` → `900` seconds).
- `STALE_AFTER` — go red after this many seconds without a successful refresh (default `180`, i.e. 3 refresh cycles).
- `GEMINI_PORT` — local port for the Gemini bridge (default `47615`, bound to `127.0.0.1` only). If you change it, reinstall the script (menu → **Install Gemini script…**) — the port is baked in when the card serves it.
- `API_URL_USAGE` (Claude), `CODEX_USAGE_URL` (Codex), and the field names — edit here if an endpoint ever changes.
- `CLAUDE_TOKEN_URLS` / `CODEX_TOKEN_URL` — the OAuth endpoints used for auto-refresh.

- `PALETTES` — the light and dark color palettes; edit here to restyle (change both).

Preferences (position, zoom, opacity, sources, shown items, tray item, reset mode, theme, title visibility) are saved to `card_state.json`.

**Environment variables:**

- `QUOTA_CARD_OPAQUE=1` — force an opaque, square-cornered card on any OS (handy on Linux/macOS if the transparent corners ever render oddly).
- `CLAUDE_CONFIG_DIR` — if you point Claude Code at a custom config dir, the app honors it too.
- `CODEX_HOME` — if you point Codex at a custom config dir, the app honors it too (default `~/.codex`).

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
