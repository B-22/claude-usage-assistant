# -*- coding: utf-8 -*-
"""
Claude / Codex 实时限额卡片  (quota_card.py)
============================================
常驻桌面、置顶、卡片式小部件,实时显示 AI 编码助手的额度使用情况,
并按"系统本地时区"显示每个窗口的实际重置时刻。附带系统托盘图标。
支持三个数据源,可在菜单"数据源"里任意组合:

  · Claude —— GET https://api.anthropic.com/api/oauth/usage(与 Claude Code 同源)
      额度在服务端按账号统计:CLI / 桌面版 / 网页的用量都计入同一份额度。
      凭证:~/.claude/.credentials.json(macOS 亦支持登录钥匙串),或直接复用 Claude
      桌面版持续续期的令牌(只读)。accessToken 过期时用 refreshToken 续期并写回。
      注意该接口按**账号**限流,且 Claude Code 每个会话自己也在轮询同一个桶,
      所以这里最多 5 分钟才真拉一次(见 CLAUDE_MIN_INTERVAL)。
  · Codex —— GET https://chatgpt.com/backend-api/wham/usage(与 Codex CLI 同源)
      凭证:~/.codex/auth.json(ChatGPT 登录模式);同样自动续期并写回。
  · Gemini —— 由油猴脚本 gemini_bridge.user.js 从页面里取数后推送到 127.0.0.1。
      网页版配额只存在于浏览器会话里,且 cookie 被 Chrome 的 App-Bound Encryption 锁死,
      所以是"页面推给卡片",而不是卡片去读凭证。装法:右键 → 数据源 → 安装 Gemini 脚本。

凭证只放进 HTTP Authorization 头、只发往各自官方域名,绝不上传到任何其它地方;
Gemini 一路更是完全不接触 Google 凭证。

界面:Python 自带 tkinter;托盘:pystray + Pillow(缺失时自动降级为仅卡片)。

操作:
  · 拖动卡片移动(记忆位置)
  · 滚轮缩放 / 拖动窗口边缘缩放 / 右键菜单选档位     · Ctrl+滚轮 微调不透明度
  · 顶部按钮:图钉=置顶  ≡=菜单  ↻=刷新  ✕=退出
  · 右键空白处 或 点 ≡ = 打开菜单(数据源 / 卡片显示 / 托盘显示 / 缩放 / 不透明度 / 重置显示 …)
  · 托盘图标:默认显示 Claude 5 小时用量(可在菜单切换);左键单击=显示/隐藏卡片
"""
from __future__ import annotations

import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

# ---------------- 平台判定 ----------------
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC

# ---------------- DPI 自适应(仅 Windows 需手动处理;mac/Linux 由 Tk 自行缩放)----------------
SCALE = 1.0
if IS_WIN:
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            SCALE = ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            SCALE = 1.0
    except Exception:
        SCALE = 1.0

# ---------------- 字体(按平台挑第一个系统真正装了的中文字体)----------------
if IS_WIN:
    _FONT_CANDIDATES = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei"]
elif IS_MAC:
    _FONT_CANDIDATES = ["PingFang SC", "Hiragino Sans GB", "Heiti SC", "STHeiti", "Arial Unicode MS"]
else:
    _FONT_CANDIDATES = ["Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
                        "WenQuanYi Zen Hei", "Noto Sans CJK", "DejaVu Sans"]
FONT = _FONT_CANDIDATES[0]


def _resolve_font(root) -> None:
    """创建窗口后,从候选里挑第一个系统真正装了的字体;都没有就保持默认让 Tk 自行回退。"""
    global FONT
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
        for cand in _FONT_CANDIDATES:
            if cand in fams:
                FONT = cand
                return
    except Exception:
        pass

# ---------------- 配置 ----------------
REFRESH_INTERVAL = 60
REFRESH_RETRY_COOLDOWN = 60  # token 续期失败后的最小重试间隔(秒)

# /api/oauth/usage 是**按账号**限流的元数据接口,而且 Claude Code 每个会话、桌面版自己
# 都在后台轮询它——大家共用同一个桶(anthropics/claude-code#30930)。
# 策略是"平时快、撞墙就退":正常 60 秒刷一次拿新鲜数字;一旦真吃到 429,就按 retry-after
# 退避(该头有时返回 0,不可信,此时改用指数退避),退避期间一个请求都不发。
# 这比"一律慢轮询"好——健康时数据是新的,出问题时才让路,而且卡片会把"数据不新鲜"
# 明确标红(见 STALE_AFTER / QuotaCard._stale),不会拿旧数字冒充新的。
# 若你同时开着很多 Claude Code 会话、频繁吃 429,把 CLAUDE_MIN_INTERVAL 调大即可。
CLAUDE_MIN_INTERVAL = 60            # 两次真实请求之间的最小间隔(秒)
CLAUDE_BACKOFF_MIN = 120.0          # 吃到 429 且无可信 retry-after 时的起始退避
CLAUDE_BACKOFF_MAX = 900.0          # 退避上限

# 距上次成功刷新超过这么久 → 视为"不新鲜",标题标红。取 3 个刷新周期:偶尔漏一拍不报警,
# 真的连不上/在退避才报。
STALE_AFTER = 180

# Claude(与 Claude Code CLI 同源的官方接口与 OAuth 客户端)
API_URL_USAGE = "https://api.anthropic.com/api/oauth/usage"
API_URL_PROFILE = "https://api.anthropic.com/api/oauth/profile"
CLAUDE_TOKEN_URLS = ("https://platform.claude.com/v1/oauth/token",
                     "https://console.anthropic.com/v1/oauth/token")
CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
CREDENTIALS = CONFIG_DIR / ".credentials.json"
FALLBACK_UA = "claude-code/2.1.85"

# Codex(与 Codex CLI 同源的官方接口与 OAuth 客户端)
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
CODEX_AUTH = CODEX_HOME / "auth.json"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_UA = "codex-cli"

STATE_FILE = Path(__file__).with_name("card_state.json")

MIN_ZOOM, MAX_ZOOM = 0.6, 2.2
EDGE = 7  # 边缘缩放感应区(基准像素)
DEFAULT_TRAY_KEY = "five_hour"

BW, BPAD, BROW, BHEADER, BFOOTER, BRAD = 300, 15, 52, 34, 32, 15
BSEC, BMSG = 26, 36  # 分节标题高度 / 单行提示高度(基准像素)
TRANSPARENT = "#ff00ff"

# ---------------- 主题 ----------------
# 两套调色板。C_* 保持模块级常量(卡片里 40 多处直接引用),换肤时由 apply_theme() 整体
# 改写——这样绘制代码一行都不用动。
PALETTES = {
    "light": {"card": "#ffffff", "border": "#e0e0e0", "title": "#1a1a1a", "sub": "#666666",
              "dim": "#999999", "track": "#ebebeb", "accent": "#c96442",
              "green": "#2ea84a", "amber": "#d4940a", "red": "#e53935",
              "tray_bg": (255, 255, 255, 230)},
    "dark":  {"card": "#1b1c20", "border": "#2e3038", "title": "#ECECEC", "sub": "#9aa0aa",
              "dim": "#6b7280", "track": "#2a2c33", "accent": "#c96442",
              "green": "#46c46a", "amber": "#e0a23a", "red": "#ef5350",
              "tray_bg": (27, 28, 32, 255)},
}
C_CARD = C_BORDER = C_TITLE = C_SUB = C_DIM = C_TRACK = C_ACCENT = C_GREEN = C_AMBER = C_RED = ""
C_TRAY_BG = (255, 255, 255, 230)
THEME_MODES = (("auto", "跟随系统"), ("light", "浅色"), ("dark", "深色"))


def system_theme() -> str:
    """读系统的浅/深色偏好,读不到就当浅色。"""
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                # 要读 AppsUseLightTheme(应用主题);SystemUsesLightTheme 管的是任务栏/开始菜单,
                # 两者可以不一致,卡片是应用,所以跟前者。
                return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
        except Exception:
            return "light"
    if IS_MAC:
        try:
            import subprocess
            p = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                               capture_output=True, text=True, timeout=5)
            # 浅色时这个键根本不存在(命令返回非 0),所以只认明确的 "Dark"
            return "dark" if "dark" in (p.stdout or "").strip().lower() else "light"
        except Exception:
            return "light"
    try:  # Linux/GNOME:先看 color-scheme,老版本没有就退回看 gtk-theme 名里带不带 dark
        import subprocess
        for args, hit in ((["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], "prefer-dark"),
                          (["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"], "dark")):
            p = subprocess.run(args, capture_output=True, text=True, timeout=5)
            if p.returncode == 0 and hit in (p.stdout or "").lower():
                return "dark"
    except Exception:
        pass
    return "light"


def apply_theme(mode: str) -> str:
    """mode ∈ {'auto','light','dark'};返回实际生效的 'light' / 'dark'。"""
    global C_CARD, C_BORDER, C_TITLE, C_SUB, C_DIM, C_TRACK
    global C_ACCENT, C_GREEN, C_AMBER, C_RED, C_TRAY_BG
    eff = system_theme() if mode == "auto" else (mode if mode in PALETTES else "light")
    p = PALETTES[eff]
    C_CARD, C_BORDER, C_TITLE, C_SUB, C_DIM, C_TRACK = (
        p["card"], p["border"], p["title"], p["sub"], p["dim"], p["track"])
    C_ACCENT, C_GREEN, C_AMBER, C_RED = p["accent"], p["green"], p["amber"], p["red"]
    C_TRAY_BG = p["tray_bg"]
    return eff


apply_theme("auto")  # 先给 C_* 一套值:下面的 PROVIDER_DOTS 等常量在导入期就要用

PROVIDERS = ("claude", "codex", "gemini")
PROVIDER_TITLES = {"claude": "Claude", "codex": "Codex", "gemini": "Gemini"}
PROVIDER_DOTS = {"claude": C_ACCENT, "codex": "#10a37f", "gemini": "#4285f4"}
CLAUDE_PLAN_BADGES = {"max": "MAX", "pro": "PRO", "team": "TEAM", "enterprise": "ENT"}
CODEX_PLAN_BADGES = {"free": "FREE", "plus": "PLUS", "pro": "PRO", "prolite": "PRO LITE",
                     "team": "TEAM", "business": "BIZ", "enterprise": "ENT", "edu": "EDU"}

LABELS = {
    "five_hour": "5 小时",
    "seven_day": "7 天",
    "seven_day_opus": "7 天 · Opus",
    "seven_day_sonnet": "7 天 · Sonnet",
    "seven_day_fable": "7 天 · Fable",
    "seven_day_cowork": "7 天 · Cowork",
    "seven_day_oauth_apps": "7 天 · 应用",
}
ORDER = ["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet",
         "seven_day_fable", "seven_day_cowork", "seven_day_oauth_apps"]
WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ================= 通用工具 =================
def _atomic_write_json(path: Path, obj) -> None:
    """先写临时文件再原子替换,避免并发写坏凭证文件;POSIX 上收紧权限。"""
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    if not IS_WIN:
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
    os.replace(tmp, path)


def _jwt_exp(tok: str) -> float | None:
    """读 JWT 的 exp 声明(不校验签名,只用来判断是否临期)。"""
    try:
        import base64
        seg = tok.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return float(json.loads(base64.urlsafe_b64decode(seg))["exp"])
    except Exception:
        return None


_ua_cache: str | None = None


def user_agent() -> str:
    global _ua_cache
    if _ua_cache:
        return _ua_cache
    ver = None
    try:
        import re
        import shutil
        import subprocess
        claude = shutil.which("claude")
        if claude:
            p = subprocess.run([claude, "--version"], capture_output=True, text=True,
                               timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            m = re.match(r"(\d+\.\d+\.\d+)", (p.stdout or "").strip())
            if m:
                ver = m.group(1)
    except Exception:
        pass
    _ua_cache = f"claude-code/{ver}" if ver else FALLBACK_UA
    return _ua_cache


# ================= Claude Desktop 常驻令牌(免终端登录) =================
# 桌面版(Claude Desktop / Cowork)会自己不断续期 OAuth 令牌,并用 Electron
# safeStorage 加密后存进其 config.json。只要读它,卡片就永远有一份"活着"的令牌,
# 无需终端 claude 登录——这正是"只用桌面版、CLI 令牌总过期"场景的根治办法。
# 全过程只读、best-effort:任何一步失败都静默跳过,回退到 CLI 凭证文件路径。
def _desktop_dir() -> Path | None:
    if IS_WIN:
        # MSIX (Microsoft Store) 版本:数据在 LocalAppData\Packages 下
        local = os.environ.get("LOCALAPPDATA")
        if local:
            pkg = Path(local) / "Packages"
            for d in pkg.glob("Claude_*"):
                candidate = d / "LocalCache" / "Roaming" / "Claude" / "config.json"
                if candidate.exists():
                    return candidate.parent
        # 经典安装版本:数据在 %APPDATA%\Claude
        base = os.environ.get("APPDATA")
        return Path(base) / "Claude" if base else None
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Claude"
    return Path.home() / ".config" / "Claude"


def _win_dpapi_unprotect(blob: bytes) -> bytes | None:
    """CryptUnprotectData(纯 ctypes,无三方依赖)。"""
    import ctypes
    import ctypes.wintypes as wt

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    bi = BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob, len(blob)),
                                     ctypes.POINTER(ctypes.c_char)))
    bo = BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(bi), None, None, None, None, 0, ctypes.byref(bo)):
        return None
    try:
        buf = ctypes.create_string_buffer(bo.cbData)
        ctypes.memmove(buf, bo.pbData, bo.cbData)
        return buf.raw
    finally:
        ctypes.windll.kernel32.LocalFree(bo.pbData)


def _win_gcm_decrypt(key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes | None:
    """AES-256-GCM via Windows BCrypt(纯 ctypes,无三方依赖)。"""
    import ctypes
    import ctypes.wintypes as wt
    bcrypt = ctypes.windll.bcrypt

    class AUTH_INFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.ULONG), ("dwInfoVersion", wt.ULONG),
                    ("pbNonce", ctypes.c_void_p), ("cbNonce", wt.ULONG),
                    ("pbAuthData", ctypes.c_void_p), ("cbAuthData", wt.ULONG),
                    ("pbTag", ctypes.c_void_p), ("cbTag", wt.ULONG),
                    ("pbMacContext", ctypes.c_void_p), ("cbMacContext", wt.ULONG),
                    ("cbAAD", wt.ULONG), ("cbData", ctypes.c_ulonglong), ("dwFlags", wt.ULONG)]
    hAlg = ctypes.c_void_p()
    hKey = ctypes.c_void_p()
    try:
        if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(hAlg), "AES", None, 0) != 0:
            return None
        mode = "ChainingModeGCM".encode("utf-16-le") + b"\x00\x00"
        if bcrypt.BCryptSetProperty(hAlg, "ChainingMode", mode, len(mode), 0) != 0:
            return None
        if bcrypt.BCryptGenerateSymmetricKey(hAlg, ctypes.byref(hKey), None, 0, key, len(key), 0) != 0:
            return None
        ai = AUTH_INFO()
        ai.cbSize = ctypes.sizeof(ai)
        ai.dwInfoVersion = 1
        nb, tb = ctypes.create_string_buffer(nonce, len(nonce)), ctypes.create_string_buffer(tag, len(tag))
        ai.pbNonce, ai.cbNonce = ctypes.cast(nb, ctypes.c_void_p), len(nonce)
        ai.pbTag, ai.cbTag = ctypes.cast(tb, ctypes.c_void_p), len(tag)
        out = ctypes.create_string_buffer(len(ct))
        cb = wt.ULONG(0)
        if bcrypt.BCryptDecrypt(hKey, ct, len(ct), ctypes.byref(ai), None, 0, out, len(ct), ctypes.byref(cb), 0) != 0:
            return None
        return out.raw[:cb.value]
    except Exception:
        return None
    finally:
        if hKey:
            bcrypt.BCryptDestroyKey(hKey)
        if hAlg:
            bcrypt.BCryptCloseAlgorithmProvider(hAlg, 0)


def _gcm_decrypt(key: bytes, nonce: bytes, ct_tag: bytes) -> bytes | None:
    """AES-GCM:优先第三方库(若已装),否则用 Windows BCrypt。"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM(key).decrypt(nonce, ct_tag, None)
    except ImportError:
        pass
    except Exception:
        return None
    try:
        from Crypto.Cipher import AES
        c = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return c.decrypt_and_verify(ct_tag[:-16], ct_tag[-16:])
    except ImportError:
        pass
    except Exception:
        return None
    if IS_WIN:
        return _win_gcm_decrypt(key, nonce, ct_tag[:-16], ct_tag[-16:])
    return None


def _cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes | None:
    """AES-128-CBC(mac/Linux 的 safeStorage 用),需第三方库;无库则返回 None。"""
    pt = None
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        pt = d.update(ct) + d.finalize()
    except ImportError:
        try:
            from Crypto.Cipher import AES
            pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
        except Exception:
            return None
    except Exception:
        return None
    if not pt:
        return None
    pad = pt[-1]  # 去 PKCS7 填充
    return pt[:-pad] if 1 <= pad <= 16 else pt


_ss_key_cache = 0  # 0=未尝试;None=尝试过但不可用;(key, algo)=已缓存


def _safestorage_key():
    """返回 (aes_key, 'gcm'|'cbc') 或 None。密钥在一个进程内稳定,缓存一次即可
       (避免每 60 秒刷新都读一次 Local State / mac 钥匙串反复弹授权框)。"""
    global _ss_key_cache
    if _ss_key_cache != 0:
        return _ss_key_cache
    _ss_key_cache = _compute_safestorage_key()
    return _ss_key_cache


def _compute_safestorage_key():
    """Windows=DPAPI 解出的 32 字节 GCM 密钥;mac/Linux=PBKDF2 派生 16 字节 CBC 密钥。"""
    d = _desktop_dir()
    if not d:
        return None
    if IS_WIN:
        try:
            ls = json.loads((d / "Local State").read_text(encoding="utf-8"))
            import base64
            enc = base64.b64decode(ls["os_crypt"]["encrypted_key"])
            if enc[:5] != b"DPAPI":
                return None
            key = _win_dpapi_unprotect(enc[5:])
            return (key, "gcm") if key else None
        except Exception:
            return None
    # mac / Linux:PBKDF2-HMAC-SHA1(salt=b"saltysalt", dklen=16)
    try:
        import hashlib
        if IS_MAC:
            import subprocess
            p = subprocess.run(["security", "find-generic-password", "-w", "-s", "Claude Safe Storage"],
                               capture_output=True, text=True, timeout=8)
            if p.returncode != 0 or not p.stdout.strip():
                return None
            pw, iters = p.stdout.strip().encode(), 1003
        else:  # Linux:无 libsecret 依赖时退回默认口令 "peanuts"
            pw, iters = b"peanuts", 1
        return (hashlib.pbkdf2_hmac("sha1", pw, b"saltysalt", iters, 16), "cbc")
    except Exception:
        return None


def _desktop_decrypt(b64_value: str, keyinfo) -> bytes | None:
    import base64
    try:
        blob = base64.b64decode(b64_value)
    except Exception:
        return None
    key, algo = keyinfo
    if blob[:3] in (b"v10", b"v11"):
        blob = blob[3:]
        if algo == "gcm":
            return _gcm_decrypt(key, blob[:12], blob[12:])
        return _cbc_decrypt(key, b" " * 16, blob)
    # 无版本前缀:Windows 上可能是旧版直接 DPAPI 加密的值
    if IS_WIN:
        return _win_dpapi_unprotect(blob)
    return None


def _claude_desktop_tokens() -> list[dict]:
    """读桌面版 config.json 里的 OAuth 令牌缓存,返回可用于 /api/oauth/usage 的候选:
       [{'token','expiresAt'(秒),'plan','client','v2'}]。

       缓存键形如 "{client_id}:{org_id}:{audience}:{scopes}"。过滤按 **user:profile** 而不是
       user:inference:/api/oauth/usage 要求的是 user:profile 作用域,缺它的令牌(桌面版缓存里
       那个 "user:inference user:office" 的 Cowork 令牌)会被服务端以
       403 permission_error "does not meet scope requirement user:profile" 拒绝。
       反过来,只有 user:profile 的令牌是能用的——所以旧的 user:inference 过滤恰好是反的。

       只读:不返回 refreshToken,也绝不续期/写回。桌面版自己会持续续期这些令牌,
       任何第三方去轮换它们都会把桌面版挤下线(refreshToken 是一次性的)。"""
    d = _desktop_dir()
    if not d:
        return []
    cfg_path = d / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    keyinfo = _safestorage_key()
    if not keyinfo:
        return []
    merged: dict = {}
    for cache_key in ("oauth:tokenCacheV2", "oauth:tokenCache"):
        enc = cfg.get(cache_key)
        if not isinstance(enc, str):
            continue
        raw = _desktop_decrypt(enc, keyinfo)
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            for k, v in obj.items():
                merged.setdefault(k, (v, cache_key == "oauth:tokenCacheV2"))  # V2 优先
    out = []
    for k, (v, is_v2) in merged.items():
        if not isinstance(v, dict):
            continue
        tok = v.get("token") or v.get("accessToken")
        if not tok or "api.anthropic.com" not in k or "user:profile" not in k:
            continue
        exp = float(v.get("expiresAt") or 0)
        exp_s = exp / 1000.0 if exp > 1e12 else exp
        out.append({
            "token": tok,
            "expiresAt": exp_s,
            "plan": CLAUDE_PLAN_BADGES.get(str(v.get("subscriptionType") or "").lower()),
            "client": k.split(":", 1)[0],
            "v2": is_v2,
        })
    return out


def _best_desktop_token(cands: list[dict]) -> dict | None:
    """挑最合适的桌面令牌。优先级:
       1. client_id == CLAUDE_CLIENT_ID —— 与我们发出的 claude-code User-Agent 身份一致;
          拿桌面版别的客户端(如 Cowork)的令牌冒充 claude-code 去请求,既容易触发风控,
          也是之前 403 风暴的来源。
       2. V2 缓存 —— 桌面版当前在用的那份,最新鲜。
       3. 过期时间最晚。"""
    if not cands:
        return None
    return max(cands, key=lambda d: (d["client"] == CLAUDE_CLIENT_ID, d["v2"], d["expiresAt"]))


# ================= 数据层:Claude(与 Claude Code 同源) =================
_keychain_service: str | None = None


def _keychain_read_raw() -> str | None:
    """mac:从登录钥匙串读取 Claude Code 凭证原文(service 名个别版本不一致,逐个尝试)。"""
    global _keychain_service
    import subprocess
    for service in ("Claude Code-credentials", "Claude Code"):
        try:
            p = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True, text=True, timeout=8)
        except Exception:
            continue
        out = (p.stdout or "").strip()
        if p.returncode == 0 and out:
            _keychain_service = service
            return out
    return None


def _keychain_write_raw(payload: str) -> bool:
    """mac:把续期后的凭证写回钥匙串(-U 覆盖同名项,账户名沿用原条目)。"""
    import subprocess
    service = _keychain_service or "Claude Code-credentials"
    acct = os.environ.get("USER") or ""
    try:
        p = subprocess.run(["security", "find-generic-password", "-s", service],
                           capture_output=True, text=True, timeout=8)
        for line in (p.stdout or "").splitlines():
            line = line.strip()
            if line.startswith('"acct"') and "=" in line:
                val = line.split("=", 1)[1].strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if val and val != "<NULL>":
                    acct = val
                break
    except Exception:
        pass
    try:
        p = subprocess.run(["security", "add-generic-password", "-U",
                            "-s", service, "-a", acct, "-w", payload],
                           capture_output=True, text=True, timeout=8)
        return p.returncode == 0
    except Exception:
        return False


def _claude_load() -> tuple[dict | None, str | None]:
    """读取完整 Claude 凭证。返回 (creds, source),source ∈ {'file', 'keychain', None}。"""
    try:
        creds = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
        if creds.get("claudeAiOauth", {}).get("accessToken"):
            return creds, "file"
    except Exception:
        pass
    if IS_MAC:
        raw = _keychain_read_raw()
        if raw:
            try:
                creds = json.loads(raw)
            except Exception:
                # 个别版本钥匙串里直接存 token 本身(无 refreshToken,过期后只能重新登录)
                creds = {"claudeAiOauth": {"accessToken": raw}} if (raw.startswith("ey") or len(raw) > 40) else None
            if creds and creds.get("claudeAiOauth", {}).get("accessToken"):
                return creds, "keychain"
    return None, None


def _claude_persist(creds: dict, source: str | None) -> None:
    """把续期后的凭证写回原存储;钥匙串写失败时落盘到官方 SSH 回退位置,避免丢失轮换后的 refreshToken。"""
    if source == "keychain" and _keychain_write_raw(json.dumps(creds, ensure_ascii=False)):
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(CREDENTIALS, creds)
    except Exception:
        pass


_claude_refresh_block_until = 0.0


def _claude_refresh(creds: dict, source: str | None) -> str | None:
    """用 refreshToken 换新 accessToken 并写回。成功返回 None,失败返回展示给用户的错误文案。"""
    global _claude_refresh_block_until
    oauth = creds.get("claudeAiOauth", {})
    rt = oauth.get("refreshToken")
    if not rt:
        return "凭证不含 refreshToken:请在终端运行一次 claude 登录"
    if time.time() < _claude_refresh_block_until:
        return "token 续期失败,稍后自动重试"
    body = {"grant_type": "refresh_token", "refresh_token": rt, "client_id": CLAUDE_CLIENT_ID}
    err = "token 续期失败,稍后自动重试"
    for url in CLAUDE_TOKEN_URLS:
        try:
            r = requests.post(url, json=body, timeout=15, headers={"User-Agent": user_agent()})
        except requests.RequestException:
            err = "网络连接失败,重试中…"
            continue
        if r.ok:
            d = r.json()
            if not d.get("access_token"):
                err = "token 续期响应异常,稍后重试"
                continue
            oauth["accessToken"] = d["access_token"]
            if d.get("refresh_token"):
                oauth["refreshToken"] = d["refresh_token"]
            oauth["expiresAt"] = int((time.time() + float(d.get("expires_in") or 3600)) * 1000)
            creds["claudeAiOauth"] = oauth
            _claude_persist(creds, source)
            return None
        if r.status_code in (400, 401):
            _claude_refresh_block_until = time.time() + 300
            return "凭证已失效:请在终端运行一次 claude 重新登录(此后卡片会自动续期)"
        err = f"token 续期失败(HTTP {r.status_code}),稍后重试"  # 403/429/5xx → 退避后重试
    _claude_refresh_block_until = time.time() + REFRESH_RETRY_COOLDOWN
    return err


def _claude_bearer_headers(tok: str) -> dict:
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "User-Agent": user_agent(),
        "anthropic-beta": "oauth-2025-04-20",
    }


def claude_headers(force_refresh: bool = False):
    """返回 (headers, error, plan)。取"最新鲜的有效令牌":
       优先桌面版令牌——桌面版自己会持续续期,我们只读,不会打扰它的登录态;
       没有可用桌面令牌时才动 CLI 凭证(续期会轮换 refreshToken,属于有副作用的路径)。
       force_refresh=True(收到 401 后)跳过刚被拒的桌面令牌,直接走 CLI 凭证续期。"""
    now = time.time()
    if not force_refresh:
        best = _best_desktop_token([d for d in _claude_desktop_tokens() if d["expiresAt"] > now + 60])
        if best:
            return _claude_bearer_headers(best["token"]), None, best.get("plan")

    creds, source = _claude_load()
    if creds:
        oauth = creds.get("claudeAiOauth", {})
        plan = CLAUDE_PLAN_BADGES.get(str(oauth.get("subscriptionType") or "").lower())
        exp = float(oauth.get("expiresAt") or 0)
        exp_s = exp / 1000.0 if exp > 1e12 else exp
        if force_refresh or (exp_s and exp_s - now < 120):
            err = _claude_refresh(creds, source)
            if err and (force_refresh or not exp_s or exp_s <= now):
                # CLI 续期失败:退回任何还能用的桌面令牌(即便临期,也比无令牌强)
                best = _best_desktop_token(_claude_desktop_tokens())
                if best:
                    return _claude_bearer_headers(best["token"]), None, best.get("plan")
                return None, err, plan
        tok = creds.get("claudeAiOauth", {}).get("accessToken")
        return _claude_bearer_headers(tok), None, plan

    # 无 CLI 凭证:最后再看桌面令牌(含已过期的兜底)
    best = _best_desktop_token(_claude_desktop_tokens())
    if best:
        return _claude_bearer_headers(best["token"]), None, best.get("plan")
    return None, "未找到登录凭证:打开一次 Claude 桌面版,或在终端运行一次 claude 登录", None


def fetch_profile(headers: dict) -> dict | None:
    try:
        r = requests.get(API_URL_PROFILE, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


_profile_plan: str | None = None
_profile_tried = False

_usage_cache: dict | None = None     # 上次成功的结果(含 updated 时刻)
_usage_next_at = 0.0                 # 软间隔:到点前不发请求,手动刷新可跳过
_usage_block_until = 0.0             # 硬退避(429):手动刷新也得等
_usage_backoff = 0.0                 # 当前退避时长,成功后清零


def _retry_after(r) -> float:
    """取 retry-after。#30930 里服务端限流时会返回 retry-after: 0(误导性的),
       所以只接受 > 0 的值,其余交给指数退避。"""
    try:
        v = float((r.headers.get("retry-after") or "").strip())
        return v if v > 0 else 0.0
    except ValueError:
        return 0.0


def _usage_error(msg: str) -> dict:
    """失败时保留上次的好数据,只挂错误标记 —— 与官方 /usage "显示上次已知用量 + as of"
       的行为一致,总比整张卡片变成一行报错好。"""
    if _usage_cache is not None:
        return {**_usage_cache, "error": msg}
    return {"error": msg}


def fetch_claude(force: bool = False) -> dict:
    """拉取 Claude 用量。返回 {"windows": [(key, util, resets_at, label)], "plan": …, "updated": …}
       或 {"error": …}(失败时附带上次的 windows)。"""
    global _profile_plan, _profile_tried, _usage_cache, _usage_next_at, _usage_block_until, _usage_backoff
    now = time.time()
    if now < _usage_block_until:               # 429 退避中:一个请求都不发
        return _usage_error(f"接口限流中,{int(_usage_block_until - now)} 秒后重试")
    if not force and _usage_cache is not None and now < _usage_next_at:
        return _usage_cache                    # 未到间隔:直接回缓存,不打扰共用的限流桶

    h, err, plan = claude_headers()
    if not h:
        return _usage_error(err)
    try:
        _usage_next_at = now + CLAUDE_MIN_INTERVAL
        r = requests.get(API_URL_USAGE, headers=h, timeout=10)
        if r.status_code == 401:  # 服务端拒绝旧 token → 强制续期后重试一次
            h, err, plan = claude_headers(force_refresh=True)
            if not h:
                return _usage_error(err)
            r = requests.get(API_URL_USAGE, headers=h, timeout=10)
            if r.status_code == 401:
                return _usage_error("登录已过期:打开一次 Claude 桌面版,或在终端运行 claude 重新登录")
        if r.status_code == 429:
            _usage_backoff = min(max(_usage_backoff * 2, CLAUDE_BACKOFF_MIN), CLAUDE_BACKOFF_MAX)
            wait = _retry_after(r) or _usage_backoff
            _usage_block_until = now + wait
            return _usage_error(f"接口限流,{int(wait)} 秒后重试")
        if r.status_code == 403:
            msg = ""
            try:
                msg = ((r.json() or {}).get("error") or {}).get("message") or ""
            except Exception:
                pass
            if "user:profile" in msg:  # 令牌作用域不对(见 _claude_desktop_tokens 注释)
                return _usage_error("令牌缺少 user:profile 作用域:请打开一次 Claude 桌面版")
            return _usage_error(f"无权访问(403){(':' + msg[:40]) if msg else ''}")
        if not r.ok:
            return _usage_error(f"获取失败(HTTP {r.status_code}),稍后重试")
        data = r.json()
    except (requests.ConnectionError, requests.Timeout):
        _usage_next_at = now + REFRESH_INTERVAL  # 没打到服务端,不必按 5 分钟等
        return _usage_error("网络连接失败,重试中…")
    except Exception as e:
        return _usage_error(f"获取失败:{type(e).__name__}")
    _usage_backoff = 0.0
    wins = []
    for key, val in data.items():
        if (isinstance(val, dict) and val.get("utilization") is not None
                and val.get("resets_at")):
            wins.append((key, float(val["utilization"]), val["resets_at"], LABELS.get(key, key)))
    # 解析 limits 数组(新版 API:含 per-model scoped 限额,如 Fable)
    seen = {w[0] for w in wins}
    limits = data.get("limits")
    if isinstance(limits, list):
        for entry in limits:
            if not isinstance(entry, dict) or entry.get("percent") is None or not entry.get("resets_at"):
                continue
            kind = entry.get("kind", "")
            scope = entry.get("scope") or {}
            model_name = (scope.get("model") or {}).get("display_name") or ""
            if kind == "session":
                key = "five_hour"
            elif kind == "weekly_all":
                key = "seven_day"
            elif kind == "weekly_scoped" and model_name:
                key = f"seven_day_{model_name.lower().replace(' ', '_')}"
            else:
                continue
            label = LABELS.get(key, f"7 天 · {model_name}" if model_name else key)
            item = (key, float(entry["percent"]), entry["resets_at"], label)
            if key in seen:
                wins = [item if w[0] == key else w for w in wins]
            else:
                wins.append(item)
                seen.add(key)
    wins.sort(key=lambda it: (ORDER.index(it[0]) if it[0] in ORDER else len(ORDER), it[0]))
    if plan is None and not _profile_tried:  # 老版本凭证无 subscriptionType → 拉一次 profile 兜底
        _profile_tried = True
        acc = (fetch_profile(h) or {}).get("account", {})
        _profile_plan = "MAX" if acc.get("has_claude_max") else ("PRO" if acc.get("has_claude_pro") else None)
    _usage_cache = {"windows": wins, "plan": plan or _profile_plan, "updated": time.time()}
    return _usage_cache


# ================= 数据层:Codex(与 Codex CLI 同源) =================
def _codex_load() -> dict | None:
    try:
        return json.loads(CODEX_AUTH.read_text(encoding="utf-8"))
    except Exception:
        return None


_codex_refresh_block_until = 0.0


def _codex_refresh(auth: dict) -> str | None:
    """用 refresh_token 续期 Codex 凭证并写回 auth.json。成功返回 None。"""
    global _codex_refresh_block_until
    toks = auth.get("tokens") or {}
    rt = toks.get("refresh_token")
    if not rt:
        return "Codex 凭证不含 refresh_token:请运行 codex 重新登录"
    if time.time() < _codex_refresh_block_until:
        return "Codex token 续期失败,稍后自动重试"
    body = {"client_id": CODEX_CLIENT_ID, "grant_type": "refresh_token", "refresh_token": rt}
    try:
        r = requests.post(CODEX_TOKEN_URL, json=body, timeout=15, headers={"User-Agent": CODEX_UA})
    except requests.RequestException:
        return "网络连接失败,重试中…"
    if not r.ok:
        if r.status_code in (400, 401):
            _codex_refresh_block_until = time.time() + 300
            return "Codex 凭证已失效:请运行 codex 重新登录"
        _codex_refresh_block_until = time.time() + REFRESH_RETRY_COOLDOWN
        return f"Codex token 续期失败(HTTP {r.status_code}),稍后重试"
    d = r.json()
    for k in ("id_token", "access_token", "refresh_token"):
        if d.get(k):
            toks[k] = d[k]
    auth["tokens"] = toks
    auth["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        _atomic_write_json(CODEX_AUTH, auth)
    except Exception:
        pass
    return None


def _codex_window_label(secs: float) -> str:
    if not secs:
        return "窗口"
    h = secs / 3600.0
    if h <= 47:
        return f"{max(1, round(h))} 小时"
    d = round(secs / 86400.0)
    return "每周" if d == 7 else f"{d} 天"


def fetch_codex(force: bool = False) -> dict:
    """拉取 Codex(ChatGPT 登录)限额。返回结构与 fetch_claude 一致。
       force 仅为与 fetch_claude 保持同签名——Codex 的接口不共用 Claude 那种账号级限流桶。"""
    auth = _codex_load()
    if auth is None:
        return {"error": "未找到 Codex 凭证:请先运行 codex 登录"}
    toks = auth.get("tokens") or {}
    if not toks.get("access_token"):
        if auth.get("OPENAI_API_KEY"):
            return {"error": "Codex 当前为 API Key 计费模式,无订阅限额可查"}
        return {"error": "Codex 凭证不完整:请运行 codex 重新登录"}
    exp = _jwt_exp(toks["access_token"])
    if exp and exp - time.time() < 120:  # 临期 → 先续期;失败且确已过期才报错
        err = _codex_refresh(auth)
        if err and exp <= time.time():
            return {"error": err}
        toks = auth.get("tokens") or {}

    def _get():
        headers = {"Authorization": f"Bearer {toks.get('access_token', '')}", "User-Agent": CODEX_UA}
        if toks.get("account_id"):
            headers["ChatGPT-Account-Id"] = toks["account_id"]
        return requests.get(CODEX_USAGE_URL, headers=headers, timeout=10)

    try:
        r = _get()
        if r.status_code == 401:  # 服务端拒绝旧 token → 续期后重试一次
            err = _codex_refresh(auth)
            if err:
                return {"error": err}
            toks = auth.get("tokens") or {}
            r = _get()
            if r.status_code == 401:
                return {"error": "Codex 登录已过期:请运行 codex 重新登录"}
        if r.status_code == 429:
            return {"error": "请求过于频繁,稍后自动重试"}
        r.raise_for_status()
        data = r.json()
    except requests.ConnectionError:
        return {"error": "网络连接失败,重试中…"}
    except Exception as e:
        return {"error": f"获取失败:{type(e).__name__}"}
    rl = data.get("rate_limit") or {}
    wins = []
    for key, win in (("codex_5h", rl.get("primary_window")), ("codex_weekly", rl.get("secondary_window"))):
        if not isinstance(win, dict) or win.get("used_percent") is None:
            continue
        if win.get("reset_at"):
            iso = datetime.fromtimestamp(float(win["reset_at"]), timezone.utc).isoformat()
        elif win.get("reset_after_seconds") is not None:
            iso = datetime.fromtimestamp(time.time() + float(win["reset_after_seconds"]), timezone.utc).isoformat()
        else:
            iso = ""
        wins.append((key, float(win["used_percent"]), iso,
                     _codex_window_label(float(win.get("limit_window_seconds") or 0))))
    if not wins:
        return {"error": "Codex 暂无限额数据"}
    plan = str(data.get("plan_type") or "").lower()
    return {"windows": wins, "plan": CODEX_PLAN_BADGES.get(plan) or (plan.replace("_", " ").upper()[:8] if plan else None)}


# ================= 数据层:Gemini(油猴脚本推送) =================
# 别的数据源都是"读本地凭证 → 调官方接口",Gemini 走不通这条路:
#   · 没有 CLI 凭证可读(gemini-cli 的 OAuth 也够不到网页版的配额);
#   · 浏览器 cookie 从 Chrome 127+ 起是 App-Bound Encryption(v20),DPAPI 密钥解不开。
#     绕过它只有"冒充浏览器的 COM 提权接口"或"杀 network service 子进程抢文件"两条路,
#     都不是一张用量卡片该干的事。
# 所以反过来:页面里本来就有活着的会话,让油猴脚本(gemini_bridge.user.js)在页面里取数,
# 把算好的百分比推给我们。卡片只在 127.0.0.1 上收数显示,永不接触任何 Google 凭证。
GEMINI_PORT = 47615
GEMINI_ORIGIN = "https://gemini.google.com"
GEMINI_STALE_AFTER = 900  # 超过这么久没收到推送 → 标记可能过期(标签页多半关了)
GEMINI_SCRIPT = Path(__file__).with_name("gemini_bridge.user.js")
GEMINI_INSTALL_URL = f"http://127.0.0.1:{GEMINI_PORT}/gemini.user.js"

_gemini_lock = threading.Lock()
_gemini_data: dict | None = None
_gemini_server = None  # None=未起;False=端口占用,不再重试;否则=server 实例


def _gemini_windows(obj) -> list:
    """把脚本推来的 {'five_hour': {'percent','resets_at'}, …} 转成卡片内部的窗口元组。"""
    if not isinstance(obj, dict):
        return []
    wins = []
    for src, key, label in (("five_hour", "gemini_5h", "5 小时"),
                            ("seven_day", "gemini_weekly", "本周")):
        v = obj.get(src)
        if not isinstance(v, dict) or v.get("percent") is None:
            continue
        try:
            pct = float(v["percent"])
        except (TypeError, ValueError):
            continue
        try:
            ts = v.get("resets_at")
            iso = datetime.fromtimestamp(float(ts), timezone.utc).isoformat() if ts else ""
        except (TypeError, ValueError, OSError, OverflowError):
            iso = ""
        wins.append((key, max(0.0, min(pct, 100.0)), iso, label))
    return wins


class _GeminiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # 别把访问日志刷到 stderr

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 这几个头**不是**给自家脚本用的:油猴的 GM_xmlhttpRequest 走扩展后台发请求,
        # 本来就不受 CORS 约束(而且它也只能走那条路——Google 给 gemini.google.com 下发的
        # CSP connect-src 里没有 127.0.0.1,页面内的 fetch 打不到这儿来)。
        # 配 CORS 纯粹是为了挡住**别的**网站:它们要 POST 就得带 application/json(见
        # do_POST 的 415),而那必然触发预检,预检拿到的 ACAO 只认 Gemini,于是被浏览器拦掉。
        self.send_header("Access-Control-Allow-Origin", GEMINI_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        # 顺手把脚本自己发出去 —— 端口已经填好,装的时候不用手改
        if self.path.split("?")[0] != "/gemini.user.js":
            return self._send(404)
        try:
            src = GEMINI_SCRIPT.read_text(encoding="utf-8").replace("__PORT__", str(GEMINI_PORT))
        except Exception:
            return self._send(404, b"gemini_bridge.user.js not found")
        self._send(200, src.encode("utf-8"), "application/javascript; charset=utf-8")

    def do_POST(self):
        global _gemini_data
        if self.path.split("?")[0] != "/gemini":
            return self._send(404)
        # 必须是 JSON:跨源请求带这个 Content-Type 就一定要先过预检,而预检只放行 Gemini。
        # 少了这一条,任意网站都能用 text/plain 的"简单请求"往卡片塞假数字。
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(415)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 65536:
                return self._send(400)
            obj = json.loads(self.rfile.read(n))
        except Exception:
            return self._send(400)
        wins = _gemini_windows(obj)
        if not wins:
            return self._send(400)
        with _gemini_lock:
            _gemini_data = {"windows": wins, "plan": None, "updated": time.time()}
        self._send(204)


class _GeminiServer(ThreadingHTTPServer):
    daemon_threads = True
    # HTTPServer 默认 allow_reuse_address=1,这里必须关掉。Windows 上 SO_REUSEADDR 的语义
    # 跟 Unix 不同 —— 它允许**直接抢占**一个已经在监听的端口:两个进程都 bind 成功,然后
    # 连接被随机分给其中之一。那样端口冲突就不会抛 OSError,下面"端口被占用"的提示成了
    # 死代码,故障现场只会表现成"脚本明明在推,卡片却一直收不到数据",极难排查。
    allow_reuse_address = False


def _gemini_serve() -> None:
    """起本地监听。只在 Gemini 数据源启用后第一次取数时调用 —— 不用就不占端口。"""
    global _gemini_server
    if _gemini_server is not None:
        return
    try:
        _gemini_server = _GeminiServer(("127.0.0.1", GEMINI_PORT), _GeminiHandler)
    except OSError:
        _gemini_server = False  # 端口被占(多半是另一个实例),别反复重试
        return
    threading.Thread(target=_gemini_server.serve_forever, daemon=True).start()


def fetch_gemini(force: bool = False) -> dict:
    """取最近一次油猴脚本推来的用量。这里不发任何网络请求 —— 数据是被推过来的。"""
    _gemini_serve()
    if _gemini_server is False:
        return {"error": f"端口 {GEMINI_PORT} 被占用,Gemini 收不到数据"}
    with _gemini_lock:
        data = _gemini_data
    if data is None:
        return {"error": "等待 Gemini 脚本推送…右键菜单可装脚本"}
    if time.time() - data["updated"] > GEMINI_STALE_AFTER:
        return {**data, "error": "Gemini 标签页未打开,数据可能过期"}
    return data


FETCHERS = {"claude": fetch_claude, "codex": fetch_codex, "gemini": fetch_gemini}


# ================= 展示辅助 =================
def parse_dt(s: str):
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def fmt_reset_clock(resets_at: str) -> str:
    """按系统本地时区显示实际重置时刻,如 '今天 04:19' / '明天 09:00' / '06-17 周三 21:59'。"""
    dt = parse_dt(resets_at)
    if not dt:
        return "—"
    local = dt.astimezone()
    now = datetime.now(local.tzinfo)
    days = (local.date() - now.date()).days
    hm = local.strftime("%H:%M")
    if days <= 0:
        return f"今天 {hm}"
    if days == 1:
        return f"明天 {hm}"
    return f"{local.strftime('%m-%d')} {WEEK[local.weekday()]} {hm}"


def fmt_countdown(resets_at: str) -> str:
    dt = parse_dt(resets_at)
    if not dt:
        return "—"
    delta = (dt - datetime.now(timezone.utc)).total_seconds()
    if delta <= 0:
        return "即将重置"
    d, h, m, s = (int(delta // 86400), int(delta % 86400 // 3600),
                  int(delta % 3600 // 60), int(delta % 60))
    if d > 0:
        return f"还有 {d} 天 {h} 时"
    if h > 0:
        return f"还有 {h} 时 {m} 分"
    return f"还有 {m} 分 {s} 秒"


def bar_color(util: float) -> str:
    return C_RED if util >= 80 else (C_AMBER if util >= 50 else C_GREEN)


def _hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# ================= 主程序 =================
class QuotaCard:
    _CURSORS = {"l": "sb_h_double_arrow", "r": "sb_h_double_arrow",
                "t": "sb_v_double_arrow", "b": "sb_v_double_arrow",
                "tl": "size_nw_se", "br": "size_nw_se",
                "tr": "size_ne_sw", "bl": "size_ne_sw"}

    def __init__(self):
        cfg = self._load_cfg()
        self.zoom = float(cfg.get("zoom", 1.0))
        self.alpha = float(cfg.get("alpha", 0.97))
        self.pinned = bool(cfg.get("pinned", True))
        self.clickthrough = bool(cfg.get("clickthrough", False))
        self.hidden = set(cfg.get("hidden", []))
        self.reset_mode = cfg.get("reset_mode", "clock")
        self.tray_key = cfg.get("tray_key", DEFAULT_TRAY_KEY)
        self.theme_mode = cfg.get("theme", "auto")
        self.show_title = bool(cfg.get("show_title", True))
        self._theme_eff = apply_theme(self.theme_mode)
        self._theme_checked = 0.0
        prov = cfg.get("providers")
        if not isinstance(prov, dict):  # 首次运行/旧配置:Claude 默认开;装了 Codex 就一并开
            prov = {"claude": True, "codex": CODEX_AUTH.exists()}
        self.providers = {p: bool(prov.get(p, p == "claude")) for p in PROVIDERS}

        self.root = tk.Tk()
        self.root.title("AI 用量")
        _resolve_font(self.root)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.pinned)

        # 透明/圆角:按平台选最稳妥的方案
        #   Windows -> 洋红色键(-transparentcolor):真透明、圆角
        #   macOS   -> systemTransparent 背景:真透明、圆角
        #   Linux   -> 无色键,退化为不透明卡片(方角),仍可整体半透明
        # 设环境变量 QUOTA_CARD_OPAQUE=1 可在任意系统强制不透明(用于排查显示异常)。
        # _canvas_keyed:画布底色是不是"透明色键"。是的话它与主题无关(卡片本体由 render()
        # 画的圆角矩形着色);不是的话换肤必须同步改画布底色,否则深色卡片会顶着一圈白边。
        canvas_bg = C_CARD
        self._canvas_keyed = False
        force_opaque = bool(os.environ.get("QUOTA_CARD_OPAQUE"))
        if not force_opaque and IS_WIN:
            try:
                self.root.attributes("-transparentcolor", TRANSPARENT)
                canvas_bg = TRANSPARENT
                self._canvas_keyed = True
            except Exception:
                canvas_bg = C_CARD
        elif not force_opaque and IS_MAC:
            try:
                self.root.configure(bg="systemTransparent")
                canvas_bg = "systemTransparent"
                self._canvas_keyed = True
            except Exception:
                canvas_bg = C_CARD
        else:
            try:
                self.root.configure(bg=C_CARD)
            except Exception:
                pass
            canvas_bg = C_CARD
        try:
            self.root.attributes("-alpha", self.alpha)
        except Exception:
            pass

        self._cur_w = self._cur_h = -1
        self.canvas = tk.Canvas(self.root, bg=canvas_bg, highlightthickness=0,
                                width=self.s(BW), height=self.s(120))
        self.canvas.pack(fill="both", expand=True)
        self._place_window(cfg)

        # 应用鼠标穿透设置
        if self.clickthrough:
            self._apply_clickthrough(True)

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", lambda *_: self.open_menu())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda *_: self._set_cursor(""))
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.root.bind("<MouseWheel>", self._on_wheel)

        self.state = {p: None for p in PROVIDERS}
        self._buttons = []
        self._pending = None
        self._drag = None
        self._resize = None
        self._cursor = None
        self._moved = False
        self._hidden_card = False
        self._refresh_evt = threading.Event()
        self._stop = False
        self.cmd_q: queue.Queue = queue.Queue()

        self.tray = None
        self._tray_sig = None
        self._setup_tray()

        threading.Thread(target=self._worker, daemon=True).start()
        self._poll_cmds()
        self._tick()
        self.root.mainloop()

    # ---- 缩放助手 ----
    def s(self, v: float) -> int:
        return int(round(v * SCALE * self.zoom))

    def f(self, px: int, weight: str = "normal"):
        return (FONT, -int(round(px * SCALE * self.zoom)), weight)

    # ---- 后台轮询 ----
    def _worker(self):
        force = False
        while not self._stop:
            for p in PROVIDERS:
                if not self.providers.get(p) or self._stop:
                    continue
                res = FETCHERS[p](force=force)
                old = self.state.get(p) or {}
                if "windows" in res:
                    # fetch_* 在限流/网络故障时会连同 error 一起回上次的好数据,此时
                    # updated 是那份数据真正的取得时刻,不能盖成"现在"——否则卡片会
                    # 谎称"刚刚更新"。
                    cur = {"windows": res["windows"], "plan": res.get("plan") or old.get("plan"),
                           "error": res.get("error"), "updated": res.get("updated") or time.time()}
                else:  # 连上次数据都没有:只标注错误
                    cur = {"windows": old.get("windows") or [], "plan": old.get("plan"),
                           "error": res.get("error"), "updated": old.get("updated", 0)}
                self.state = {**self.state, p: cur}
            # wait 返回 True = 被"立即刷新"唤醒 → 下一轮跳过软间隔,真正发一次请求
            force = self._refresh_evt.wait(REFRESH_INTERVAL)
            self._refresh_evt.clear()

    def _tick(self):
        if self._stop:
            return
        # 跟随系统时,系统主题是可能中途被改的。10 秒探一次:每秒读注册表太浪费,
        # 而换肤本来也不急在一秒。
        if self.theme_mode == "auto" and time.time() - self._theme_checked > 10:
            self._theme_checked = time.time()
            eff = system_theme()
            if eff != self._theme_eff:
                self._theme_eff = apply_theme("auto")
                self._repaint_theme()  # 不落盘:模式没变,变的是系统
        if not self._hidden_card:
            self.render()
        self.root.after(1000, self._tick)

    def _poll_cmds(self):
        if self._stop:
            return
        try:
            while True:
                cmd, _ = self.cmd_q.get_nowait()
                {"toggle_card": self.toggle_card, "refresh": self.refresh_now,
                 "quit": self.quit}.get(cmd, lambda: None)()
        except queue.Empty:
            pass
        if not self._stop:
            self.root.after(120, self._poll_cmds)

    # ---- 绘制 ----
    def _sections(self):
        """按 PROVIDERS 顺序返回启用数据源的展示数据。"""
        out = []
        for p in PROVIDERS:
            if not self.providers.get(p):
                continue
            st = self.state.get(p) or {"windows": [], "plan": None, "error": "正在加载…", "updated": 0}
            wins = st.get("windows") or []
            out.append({"p": p, "plan": st.get("plan"), "error": st.get("error"),
                        "updated": st.get("updated", 0), "wins": wins,
                        "shown": [w for w in wins if w[0] not in self.hidden]})
        return out

    def render(self):
        cv = self.canvas
        cv.delete("all")
        self._buttons = []

        PAD, HEADER, ROW, FOOTER, RAD = self.s(BPAD), self.s(BHEADER), self.s(BROW), self.s(BFOOTER), self.s(BRAD)
        W = self.s(BW)
        secs = self._sections()
        multi = len(secs) >= 2
        SEC, MSG = (self.s(BSEC) if multi else 0), self.s(BMSG)
        body = sum(SEC + (len(s_["shown"]) * ROW if s_["shown"] else MSG) for s_ in secs) or MSG
        H = PAD + HEADER + body + FOOTER

        if (W, H) != (self._cur_w, self._cur_h):
            self._cur_w, self._cur_h = W, H
            cv.config(width=W, height=H)
            self.root.geometry(f"{W}x{H}+{self.root.winfo_x()}+{self.root.winfo_y()}")

        round_rect(cv, self.s(1), self.s(1), W - self.s(1), H - self.s(1), RAD, fill=C_CARD, outline=C_BORDER)

        # 头部:单数据源沿用旧样式(标题+套餐徽标);多数据源标题改为 AI 用量,徽标移到各分节
        hy = PAD + self.s(11)
        # 单数据源时分节标题不画,警示就得落在这个大标题上,否则只剩底部一行小字
        head_stale = bool(secs) and not multi and self._stale(secs[0])
        cv.create_oval(PAD, hy - self.s(4), PAD + self.s(8), hy + self.s(4),
                       fill=C_RED if head_stale else C_ACCENT, outline="")
        badge = secs[0]["plan"] if (not multi and secs) else None
        if not self.show_title:
            title = ""
        elif not multi and secs:
            title = f"{PROVIDER_TITLES[secs[0]['p']]} 用量"
        else:
            title = "AI 用量"
        tid = cv.create_text(PAD + self.s(16), hy, text=title, anchor="w",
                             fill=C_RED if head_stale else C_TITLE, font=self.f(15, "bold"))
        if badge:
            # 标题关掉时文本是空的,bbox 可能拿不到 → 退回贴着圆点放
            bb = cv.bbox(tid)
            self._draw_badge(cv, (bb[2] if bb else PAD + self.s(14)) + self.s(8), hy, badge)
        # 顶部按钮(统一尺寸 + 统一线条风格,从右往左):关闭 / 刷新 / 菜单 / 图钉
        ri = self.s(7)
        sw = max(2, int(round(1.7 * SCALE * self.zoom)))
        cx = W - PAD - self.s(6)
        for kind, cb in (("close", self.quit), ("refresh", self.refresh_now),
                         ("menu", self.open_menu), ("top", self.toggle_pin)):
            col = (C_ACCENT if self.pinned else C_SUB) if kind == "top" else C_SUB
            self._draw_icon(cv, kind, cx, hy, ri, sw, col)
            r = self.s(11)
            self._buttons.append((cx - r, hy - r, cx + r, hy + r, cb))
            cx -= self.s(23)
        cv.create_line(PAD, PAD + HEADER - self.s(8), W - PAD, PAD + HEADER - self.s(8), fill=C_BORDER)

        # 内容:各数据源分节与行
        y = PAD + HEADER
        if not secs:
            cv.create_text(W / 2, y + MSG / 2, text="未启用数据源 · 右键 → 数据源",
                           fill=C_DIM, font=self.f(10), justify="center")
        for s_ in secs:
            if multi:
                self._draw_section(cv, y, SEC, s_, W, PAD)
                y += SEC
            if s_["shown"]:
                for _key, util, resets_at, label in s_["shown"]:
                    self._draw_row(cv, y, label, util, resets_at, W, PAD)
                    y += ROW
            else:
                if s_["wins"]:
                    msg, color = "已全部隐藏 · 右键 → 卡片显示", C_DIM
                else:
                    msg, color = (s_["error"] or "暂无数据"), C_SUB
                cv.create_text(W / 2, y + MSG / 2, text=msg, fill=color, font=self.f(10),
                               width=W - 2 * PAD, justify="center")
                y += MSG

        self._draw_footer(cv, W, H, PAD, secs)
        self._update_tray(secs)

    def _stale(self, s_) -> bool:
        """这一节的数字还能不能信?两种情况都算不新鲜:
           · 有 error —— 限流、断网、令牌问题…本轮没拿到新数据;
           · 太久没成功刷新 —— 有些故障不报错,只表现为 updated 不再前进。
           不新鲜就把标题标红:宁可显眼,也不能让旧数字冒充新的。"""
        if s_["error"]:
            return True
        up = s_["updated"]
        return bool(up) and (time.time() - up) > STALE_AFTER

    def _stale_note(self, s_) -> str:
        """标题旁边那句短提示:说清"多久没更新了",光一个 ⚠ 说明不了问题。"""
        up = s_["updated"]
        if not up:
            return "无数据"
        ago = int(time.time() - up)
        if ago < 60:
            return f"{ago} 秒前"
        if ago < 3600:
            return f"{ago // 60} 分前"
        return f"{ago // 3600} 时前"

    def _draw_badge(self, cv, x, cy, text, small=False):
        bw = self.s((10 if small else 12) + (6 if small else 7) * len(text))
        bh = self.s(7 if small else 8)
        round_rect(cv, x, cy - bh, x + bw, cy + bh, self.s(6), fill=C_ACCENT, outline="")
        cv.create_text(x + bw / 2, cy, text=text, fill="#ffffff", font=self.f(8 if small else 9, "bold"))

    def _draw_section(self, cv, y, SEC, s_, W, PAD):
        cy = y + SEC / 2 + self.s(3)
        stale = self._stale(s_)
        cv.create_oval(PAD, cy - self.s(3), PAD + self.s(6), cy + self.s(3),
                       fill=C_RED if stale else PROVIDER_DOTS.get(s_["p"], C_SUB), outline="")
        tid = cv.create_text(PAD + self.s(12), cy, text=PROVIDER_TITLES[s_["p"]], anchor="w",
                             fill=C_RED if stale else C_TITLE, font=self.f(12, "bold"))
        if s_["plan"]:
            self._draw_badge(cv, cv.bbox(tid)[2] + self.s(6), cy, s_["plan"], small=True)
        if stale and s_["shown"]:  # 有旧数据但没刷上 → 右侧写明多久没更新了
            cv.create_text(W - PAD, cy, text=f"⚠ {self._stale_note(s_)}", anchor="e",
                           fill=C_RED, font=self.f(9, "bold"))

    def _draw_row(self, cv, y, label, util, resets_at, W, PAD):
        col = bar_color(util)
        cy1 = y + self.s(10)
        cv.create_text(PAD, cy1, text=label, anchor="w", fill=C_SUB, font=self.f(12))
        cv.create_text(W - PAD, cy1, text=f"{util:.0f}%", anchor="e", fill=col, font=self.f(16, "bold"))
        by, bx2 = y + self.s(22), W - PAD
        round_rect(cv, PAD, by, bx2, by + self.s(8), self.s(4), fill=C_TRACK, outline="")
        fw = (bx2 - PAD) * max(0.0, min(util, 100.0)) / 100.0
        if fw >= self.s(8):
            round_rect(cv, PAD, by, PAD + fw, by + self.s(8), self.s(4), fill=col, outline="")
        elif fw > 0:
            cv.create_rectangle(PAD, by, PAD + fw, by + self.s(8), fill=col, outline="")
        cy3 = y + self.s(42)
        if self.reset_mode == "count":
            cv.create_text(PAD, cy3, text="重置", anchor="w", fill=C_DIM, font=self.f(10))
            cv.create_text(W - PAD, cy3, text=fmt_countdown(resets_at), anchor="e", fill=C_DIM, font=self.f(10))
        else:
            cv.create_text(PAD, cy3, text="重置于", anchor="w", fill=C_DIM, font=self.f(10))
            cv.create_text(W - PAD, cy3, text=fmt_reset_clock(resets_at), anchor="e", fill=C_SUB, font=self.f(10))

    def _draw_footer(self, cv, W, H, PAD, secs):
        fy = H - PAD + self.s(2)
        have_data = [s_ for s_ in secs if s_["updated"]]
        has_err = any(s_["error"] for s_ in secs)
        stale = [s_ for s_ in secs if self._stale(s_)]
        if not secs:
            dot, text = C_DIM, "未启用数据源"
        elif not have_data:
            dot, text = (C_RED, "未连接") if has_err else (C_AMBER, "正在加载…")
        else:
            # 用最**旧**的一节算年龄:多数据源时,一个卡住了另一个还在刷,取 max 会把
            # 卡住的那个藏起来,底部显示"刚刚更新"就成了谎话。
            ago = int(time.time() - min(s_["updated"] for s_ in have_data))
            text = "刚刚更新" if ago < 5 else (f"{ago} 秒前更新" if ago < 60 else f"{ago // 60} 分前更新")
            if stale:
                # 把具体是谁出问题写出来 —— 多数据源时"可能过期"根本不知道说的是哪个
                who = "、".join(PROVIDER_TITLES[s_["p"]] for s_ in stale)
                dot, text = C_RED, f"{text} · {who} 未刷新"
            else:
                dot, text = C_GREEN, text
        cv.create_oval(PAD, fy - self.s(3), PAD + self.s(6), fy + self.s(3), fill=dot, outline="")
        cv.create_text(PAD + self.s(12), fy, text=text, anchor="w", fill=C_DIM, font=self.f(10))
        cv.create_text(W - PAD, fy, text=datetime.now().strftime("%H:%M:%S"),
                       anchor="e", fill=C_DIM, font=self.f(10))

    def _draw_icon(self, cv, kind, cx, cy, ri, sw, col):
        """统一尺寸 / 统一线条风格(2px 圆头描边)的矢量图标。"""
        if kind == "close":
            d = ri * 0.62
            cv.create_line(cx - d, cy - d, cx + d, cy + d, fill=col, width=sw, capstyle="round")
            cv.create_line(cx - d, cy + d, cx + d, cy - d, fill=col, width=sw, capstyle="round")
        elif kind == "menu":
            d, g = ri * 0.66, ri * 0.46
            for yo in (-g, 0.0, g):
                cv.create_line(cx - d, cy + yo, cx + d, cy + yo, fill=col, width=sw, capstyle="round")
        elif kind == "refresh":
            R = ri * 0.66
            cv.create_arc(cx - R, cy - R, cx + R, cy + R, start=75, extent=250,
                          style="arc", outline=col, width=sw)
            a = math.radians(75)                       # 弧起点(顶部)
            ex, ey = cx + R * math.cos(a), cy - R * math.sin(a)
            tx, ty = math.sin(a), math.cos(a)          # 顺时针切线方向
            nx, ny = -ty, tx
            t = ri * 0.55
            cv.create_polygon(ex + tx * t, ey + ty * t,
                              ex + nx * t * 0.7, ey + ny * t * 0.7,
                              ex - nx * t * 0.7, ey - ny * t * 0.7,
                              fill=col, outline="")
        else:  # top —— 纯色三角形 ▲(置顶=橙色,取消=灰色)
            cv.create_polygon(cx, cy - ri * 0.66,
                              cx - ri * 0.66, cy + ri * 0.56,
                              cx + ri * 0.66, cy + ri * 0.56,
                              fill=col, outline="")

    # ---- 托盘 ----
    def _setup_tray(self):
        try:
            import pystray
            import PIL
            _ = PIL.__version__
        except Exception:
            self.tray = None
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示/隐藏卡片", lambda *_: self.cmd_q.put(("toggle_card", None)), default=True),
            pystray.MenuItem("立即刷新", lambda *_: self.cmd_q.put(("refresh", None))),
            pystray.MenuItem("退出", lambda *_: self.cmd_q.put(("quit", None))),
        )
        self.tray = pystray.Icon("claude_quota", self._tray_image(0, (70, 196, 106)), "AI 用量", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _tray_image(self, util, rgb):
        from PIL import Image, ImageDraw
        sz = 64
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # 白底 + 用量色描边 + 用量色数字——在深/浅任务栏上都清晰可辨
        d.rounded_rectangle([1, 1, sz - 2, sz - 2], radius=14,
                            fill=C_TRAY_BG, outline=tuple(rgb) + (255,), width=4)
        txt = f"{int(round(util))}"
        # 自适应字号:在留白内尽量放大
        font = self._load_font(16)
        for size in range(46, 14, -2):
            cand = self._load_font(size)
            bb = d.textbbox((0, 0), txt, font=cand)
            if bb[2] - bb[0] <= sz - 12 and bb[3] - bb[1] <= sz - 18:
                font = cand
                break
        bb = d.textbbox((0, 0), txt, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text(((sz - tw) / 2 - bb[0], (sz - th) / 2 - bb[1]), txt, font=font, fill=tuple(rgb) + (255,))
        return img

    @staticmethod
    def _load_font(size):
        from PIL import ImageFont
        for fp in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _update_tray(self, secs):
        if not self.tray:
            return
        avail = [(s_["p"], k, u, lbl) for s_ in secs for (k, u, _r, lbl) in s_["wins"]]
        if not avail:
            return
        p, key, util, lbl = next((it for it in avail if it[1] == self.tray_key), avail[0])
        rgb = _hex_rgb(bar_color(util))
        sig = (key, int(round(util)), rgb)
        if sig == self._tray_sig:
            return
        self._tray_sig = sig
        try:
            self.tray.icon = self._tray_image(util, rgb)
            lines = "\n".join(f"{PROVIDER_TITLES[pp]} · {ll} {uu:.0f}%" for pp, _kk, uu, ll in avail)
            self.tray.title = (f"AI 用量(托盘:{PROVIDER_TITLES[p]} · {lbl})\n" + lines)[:120]
        except Exception:
            pass

    # ---- 边缘缩放 ----
    def _region(self, x, y):
        W, H = self._cur_w, self._cur_h
        if W <= 0 or H <= 0:
            return ""
        m = self.s(EDGE)
        left, right, top, bot = x <= m, x >= W - m, y <= m, y >= H - m
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bot and left:
            return "bl"
        if bot and right:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bot:
            return "b"
        return ""

    def _set_cursor(self, region):
        if region == self._cursor:
            return
        self._cursor = region
        name = self._CURSORS.get(region, "arrow")
        for cand in (name, "sizing", "arrow"):
            try:
                self.canvas.config(cursor=cand)
                return
            except tk.TclError:
                continue

    def _on_motion(self, e):
        if self._resize or self._drag:
            return
        self._set_cursor(self._region(e.x, e.y))

    def _do_resize(self, e):
        rs = self._resize
        if rs is None:
            return
        reg = rs["region"]
        if "l" in reg:
            newdim, base = rs["w"] - (e.x_root - rs["mx"]), rs["w"]
        elif "r" in reg:
            newdim, base = rs["w"] + (e.x_root - rs["mx"]), rs["w"]
        elif reg == "t":
            newdim, base = rs["h"] - (e.y_root - rs["my"]), rs["h"]
        else:  # "b"
            newdim, base = rs["h"] + (e.y_root - rs["my"]), rs["h"]
        if base <= 0:
            return
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, rs["zoom"] * newdim / base))
        self.render()
        nx = (rs["x"] + rs["w"] - self._cur_w) if "l" in reg else rs["x"]
        ny = (rs["y"] + rs["h"] - self._cur_h) if "t" in reg else rs["y"]
        self.root.geometry(f"+{nx}+{ny}")

    # ---- 交互 ----
    def _on_press(self, e):
        for x1, y1, x2, y2, cb in self._buttons:
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                self._pending, self._drag, self._resize = cb, None, None
                return
        self._pending = None
        region = self._region(e.x, e.y)
        if region:
            self._resize = {"region": region, "mx": e.x_root, "my": e.y_root,
                            "zoom": self.zoom, "w": self._cur_w, "h": self._cur_h,
                            "x": self.root.winfo_x(), "y": self.root.winfo_y()}
            self._drag = None
            return
        self._moved = False
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _on_drag(self, e):
        if self._resize:
            self._do_resize(e)
        elif self._drag:
            sx, sy, ox, oy = self._drag
            self.root.geometry(f"+{ox + e.x_root - sx}+{oy + e.y_root - sy}")
            self._moved = True

    def _on_release(self, e):
        if self._resize:
            self._resize = None
            self._save_cfg()
            return
        if self._pending:
            for x1, y1, x2, y2, cb in self._buttons:
                if x1 <= e.x <= x2 and y1 <= e.y <= y2 and cb is self._pending:
                    cb()
                    break
            self._pending = None
        elif self._drag and self._moved:
            self._save_cfg()
        self._drag = None

    def _on_wheel(self, e):
        if e.state & 0x0004:  # Ctrl → 微调不透明度
            self.set_alpha(self.alpha + (0.02 if e.delta > 0 else -0.02))
        else:                 # 滚轮 → 缩放
            self.set_zoom(self.zoom * (1.08 if e.delta > 0 else 1 / 1.08))

    # ---- 菜单 ----
    def open_menu(self):
        self._build_menu()
        x, y = self.root.winfo_pointerxy()
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="立即刷新", command=self.refresh_now)
        secs = self._sections()
        flat = [(s_["p"], k, lbl) for s_ in secs for (k, _u, _r, lbl) in s_["wins"]]

        # 数据源(勾选启用 Claude / Codex,可多选)
        pm = tk.Menu(m, tearoff=0)
        self._prov_vars = {}
        for p in PROVIDERS:
            var = tk.BooleanVar(value=self.providers.get(p, False))
            self._prov_vars[p] = var
            pm.add_checkbutton(label=PROVIDER_TITLES[p], variable=var,
                               command=lambda pp=p: self.toggle_provider(pp))
        pm.add_separator()
        pm.add_command(label="安装 Gemini 脚本…", command=self.install_gemini_script)
        m.add_cascade(label="数据源", menu=pm)

        # 卡片显示(勾选要显示哪几个窗口)
        sub = tk.Menu(m, tearoff=0)
        if flat:
            self._show_vars = {}
            for p, key, lbl in flat:
                var = tk.BooleanVar(value=key not in self.hidden)
                self._show_vars[key] = var
                sub.add_checkbutton(label=f"{PROVIDER_TITLES[p]} · {lbl}", variable=var,
                                    command=lambda k=key: self._toggle_show(k))
        else:
            sub.add_command(label="(暂无数据)", state="disabled")
        m.add_cascade(label="卡片显示", menu=sub)

        # 托盘显示(单选托盘图标显示哪个)
        if self.tray:
            tm = tk.Menu(m, tearoff=0)
            self._tray_var = tk.StringVar(value=self.tray_key)
            if flat:
                for p, key, lbl in flat:
                    tm.add_radiobutton(label=f"{PROVIDER_TITLES[p]} · {lbl}", value=key,
                                       variable=self._tray_var,
                                       command=lambda k=key: self.set_tray_key(k))
            else:
                tm.add_command(label="(暂无数据)", state="disabled")
            m.add_cascade(label="托盘显示", menu=tm)

        # 缩放
        zm = tk.Menu(m, tearoff=0)
        self._zoom_var = tk.DoubleVar(value=round(self.zoom, 2))
        for label, z in (("60%", 0.6), ("80%", 0.8), ("100%", 1.0), ("120%", 1.2),
                         ("140%", 1.4), ("160%", 1.6), ("180%", 1.8), ("200%", 2.0)):
            zm.add_radiobutton(label=label, value=z, variable=self._zoom_var, command=lambda zz=z: self.set_zoom(zz))
        m.add_cascade(label="缩放", menu=zm)

        # 不透明度
        om = tk.Menu(m, tearoff=0)
        self._alpha_var = tk.IntVar(value=int(round(self.alpha * 100)))
        for p in (100, 95, 90, 85, 80, 75, 70, 65, 60, 50):
            om.add_radiobutton(label=f"{p}%", value=p, variable=self._alpha_var, command=lambda v=p: self.set_alpha(v / 100))
        m.add_cascade(label="不透明度", menu=om)

        # 重置显示
        rm = tk.Menu(m, tearoff=0)
        self._reset_var = tk.StringVar(value=self.reset_mode)
        rm.add_radiobutton(label="重置时刻(系统时区)", value="clock", variable=self._reset_var,
                           command=lambda: self.set_reset_mode("clock"))
        rm.add_radiobutton(label="倒计时", value="count", variable=self._reset_var,
                           command=lambda: self.set_reset_mode("count"))
        m.add_cascade(label="重置显示", menu=rm)

        # 主题(跟随系统 / 浅色 / 深色)
        tm2 = tk.Menu(m, tearoff=0)
        self._theme_var = tk.StringVar(value=self.theme_mode)
        for val, lbl in THEME_MODES:
            show = f"{lbl}(当前:{'浅色' if self._theme_eff == 'light' else '深色'})" \
                if val == "auto" else lbl
            tm2.add_radiobutton(label=show, value=val, variable=self._theme_var,
                                command=lambda v=val: self.set_theme(v))
        m.add_cascade(label="主题", menu=tm2)

        m.add_separator()
        self._title_var = tk.BooleanVar(value=self.show_title)
        m.add_checkbutton(label="显示标题", variable=self._title_var, command=self.toggle_title)
        self._pin_var = tk.BooleanVar(value=self.pinned)
        m.add_checkbutton(label="窗口置顶", variable=self._pin_var, command=self.toggle_pin)
        if IS_WIN:
            self._clickthrough_var = tk.BooleanVar(value=self.clickthrough)
            m.add_checkbutton(label="鼠标穿透", variable=self._clickthrough_var, command=self.toggle_clickthrough)
        if self.tray:
            m.add_command(label="隐藏到托盘", command=self.toggle_card)
        m.add_command(label="退出", command=self.quit)
        self.menu = m

    # ---- 动作 ----
    def refresh_now(self):
        self._refresh_evt.set()

    def toggle_provider(self, p):
        self.providers[p] = not self.providers.get(p, False)
        if self.providers[p]:
            self.refresh_now()  # 新启用的数据源立即拉一次
        self.render()
        self._save_cfg()

    def install_gemini_script(self):
        """在浏览器里打开脚本地址;装了油猴的话会直接弹出安装页。"""
        import webbrowser
        self.providers["gemini"] = True  # 先把数据源打开,否则监听没起来,这个地址是打不开的
        _gemini_serve()
        self.refresh_now()
        self.render()
        self._save_cfg()
        try:
            webbrowser.open(GEMINI_INSTALL_URL)
        except Exception:
            pass

    def set_zoom(self, z):
        z = max(MIN_ZOOM, min(MAX_ZOOM, z))
        if abs(z - self.zoom) < 1e-3:
            return
        self.zoom = z
        self.render()
        self._save_cfg()

    def set_alpha(self, v):
        self.alpha = max(0.4, min(1.0, v))
        self.root.attributes("-alpha", self.alpha)
        self._save_cfg()

    def set_reset_mode(self, mode):
        self.reset_mode = mode
        self.render()
        self._save_cfg()

    def _sync_canvas_bg(self):
        """非色键模式下,画布底色得跟着主题走(色键模式下它是透明键,不能碰)。"""
        if self._canvas_keyed:
            return
        try:
            self.canvas.config(bg=C_CARD)
            self.root.configure(bg=C_CARD)
        except Exception:
            pass

    def _repaint_theme(self):
        """主题已经 apply 过了,把界面刷新一遍。"""
        self._sync_canvas_bg()
        self._tray_sig = None  # 托盘图标底色也换了,强制重画
        self.render()

    def set_theme(self, mode):
        self.theme_mode = mode
        self._theme_eff = apply_theme(mode)
        self._repaint_theme()
        self._save_cfg()

    def toggle_title(self):
        self.show_title = not self.show_title
        self.render()
        self._save_cfg()

    def set_tray_key(self, key):
        self.tray_key = key
        self._tray_sig = None
        self.render()
        self._save_cfg()

    def _toggle_show(self, key):
        self.hidden.discard(key) if key in self.hidden else self.hidden.add(key)
        self.render()
        self._save_cfg()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.render()
        self._save_cfg()

    def toggle_clickthrough(self):
        self.clickthrough = not self.clickthrough
        self._apply_clickthrough(self.clickthrough)
        self.render()
        self._save_cfg()

    def _apply_clickthrough(self, enable: bool):
        """应用鼠标穿透设置(仅 Windows 支持)"""
        if not IS_WIN:
            return
        try:
            import ctypes
            import ctypes.wintypes as wt
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enable:
                style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
            else:
                style &= ~(WS_EX_TRANSPARENT)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def toggle_card(self):
        if self._hidden_card:
            self.root.deiconify()
            self.root.attributes("-topmost", self.pinned)
            self._hidden_card = False
            self.render()
        else:
            self.root.withdraw()
            self._hidden_card = True

    def quit(self):
        self._stop = True
        self._save_cfg()
        if _gemini_server:
            try:
                _gemini_server.shutdown()
                _gemini_server.server_close()  # shutdown() 只停循环,不放端口
            except Exception:
                pass
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---- 工具 ----
    def _place_window(self, cfg):
        x, y = cfg.get("x"), cfg.get("y")
        if x is None or y is None:
            x, y = self.root.winfo_screenwidth() - self.s(BW) - self.s(24), self.s(48)
        self.root.geometry(f"+{int(x)}+{int(y)}")

    def _load_cfg(self):
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cfg(self):
        try:
            STATE_FILE.write_text(json.dumps({
                "x": self.root.winfo_x(), "y": self.root.winfo_y(),
                "alpha": round(self.alpha, 3), "zoom": round(self.zoom, 3),
                "pinned": self.pinned, "clickthrough": self.clickthrough,
                "hidden": sorted(self.hidden),
                "reset_mode": self.reset_mode, "tray_key": self.tray_key,
                "theme": self.theme_mode, "show_title": self.show_title,
                "providers": dict(self.providers),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


# ================= 自检 =================
def run_check():
    rec = getattr(sys.stdout, "reconfigure", None)
    if rec:
        try:
            rec(encoding="utf-8")
        except Exception:
            pass
    print("Claude 凭证:", CREDENTIALS, "存在" if CREDENTIALS.exists() else "不存在")
    print("Codex 凭证:", CODEX_AUTH, "存在" if CODEX_AUTH.exists() else "不存在")
    print("Gemini 脚本:", GEMINI_SCRIPT, "存在" if GEMINI_SCRIPT.exists() else "不存在")
    print("         装法: 卡片右键 → 数据源 → 安装 Gemini 脚本…  (或开卡片后访问",
          GEMINI_INSTALL_URL + ")")
    print("User-Agent:", user_agent())
    # 桌面版令牌一览:/api/oauth/usage 要 user:profile 作用域,缺它的令牌会被 403 拒绝,
    # 所以把"看到几个可用、最后选了哪个"打出来——之前选错令牌就是栽在这里。
    desk = _claude_desktop_tokens()
    best = _best_desktop_token(desk)
    print(f"桌面版令牌: {len(desk)} 个带 user:profile 可用" +
          (f",选用 client={best['client'][:8]}…({'V2' if best['v2'] else 'V1'} 缓存,"
           f"{'与 UA 同源' if best['client'] == CLAUDE_CLIENT_ID else '非 claude-code 客户端'})"
           if best else ""))
    for name, fetch in (("Claude", fetch_claude), ("Codex", fetch_codex)):
        res = fetch()
        if "error" in res:
            print(f"[{name}] 错误 -> {res['error']}")
            continue
        print(f"[{name}] 套餐: {res.get('plan') or '—'}")
        for _key, util, resets_at, label in res["windows"]:
            print(f"  {label:<14} {util:5.1f}%   重置于 {fmt_reset_clock(resets_at)}")


_SINGLETON_HANDLE = None


def acquire_single_instance() -> bool:
    """单实例保护:Windows 用命名互斥量,mac/Linux 用文件锁;占用成功返回 True。"""
    global _SINGLETON_HANDLE
    try:
        if IS_WIN:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(None, False, "ClaudeQuotaCardSingletonMutex")
            if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                return False
            _SINGLETON_HANDLE = handle  # 保持引用,进程存活期间一直持有
            return True
        # mac / Linux:对配置目录下的锁文件加排他非阻塞锁
        import fcntl
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            lock_path = CONFIG_DIR / ".quota_card.lock"
        except Exception:
            lock_path = Path.home() / ".quota_card.lock"
        f = open(lock_path, "w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]  # fcntl 仅 Unix
        except OSError:
            return False  # 已有实例持锁
        _SINGLETON_HANDLE = f  # 保持文件对象存活,进程退出自动释放锁
        return True
    except Exception:
        return True  # 出错时不阻止启动


if __name__ == "__main__":
    if "--check" in sys.argv:
        run_check()
    elif not acquire_single_instance():
        sys.exit(0)  # 已有实例,直接退出,不重复弹卡片
    else:
        QuotaCard()
