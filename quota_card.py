# -*- coding: utf-8 -*-
"""
Claude / Codex 实时限额卡片  (quota_card.py)
============================================
常驻桌面、置顶、卡片式小部件,实时显示 AI 编码助手的额度使用情况,
并按"系统本地时区"显示每个窗口的实际重置时刻。附带系统托盘图标。
支持两个数据源,可在菜单"数据源"里同时显示或只选其一:

  · Claude —— GET https://api.anthropic.com/api/oauth/usage(与 Claude Code 同源)
      额度在服务端按账号统计:CLI / 桌面版 / 网页的用量都计入同一份额度。
      凭证:~/.claude/.credentials.json(macOS 亦支持登录钥匙串)。
      accessToken 过期时自动用 refreshToken 续期并写回,不再依赖终端登录刷新。
  · Codex —— GET https://chatgpt.com/backend-api/wham/usage(与 Codex CLI 同源)
      凭证:~/.codex/auth.json(ChatGPT 登录模式);同样自动续期并写回。

凭证只放进 HTTP Authorization 头、只发往各自官方域名,绝不上传到任何其它地方。

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

C_CARD = "#1b1c20"
C_BORDER = "#2e3038"
C_TITLE = "#ECECEC"
C_SUB = "#9aa0aa"
C_DIM = "#6b7280"
C_TRACK = "#2a2c33"
C_ACCENT = "#c96442"
C_GREEN = "#46c46a"
C_AMBER = "#e0a23a"
C_RED = "#ef5350"

PROVIDERS = ("claude", "codex")
PROVIDER_TITLES = {"claude": "Claude", "codex": "Codex"}
PROVIDER_DOTS = {"claude": C_ACCENT, "codex": "#10a37f"}
CLAUDE_PLAN_BADGES = {"max": "MAX", "pro": "PRO", "team": "TEAM", "enterprise": "ENT"}
CODEX_PLAN_BADGES = {"free": "FREE", "plus": "PLUS", "pro": "PRO", "prolite": "PRO LITE",
                     "team": "TEAM", "business": "BIZ", "enterprise": "ENT", "edu": "EDU"}

LABELS = {
    "five_hour": "5 小时",
    "seven_day": "7 天",
    "seven_day_opus": "7 天 · Opus",
    "seven_day_sonnet": "7 天 · Sonnet",
    "seven_day_cowork": "7 天 · Cowork",
    "seven_day_oauth_apps": "7 天 · 应用",
}
ORDER = ["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet",
         "seven_day_cowork", "seven_day_oauth_apps"]
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
       [{'token','expiresAt'(秒),'refreshToken','plan'}],按 api.anthropic.com + user:inference 过滤。只读。"""
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
                merged.setdefault(k, v)  # V2 优先
    out = []
    for k, v in merged.items():
        if not isinstance(v, dict):
            continue
        tok = v.get("token") or v.get("accessToken")
        if not tok or "user:inference" not in k or "api.anthropic.com" not in k:
            continue
        exp = float(v.get("expiresAt") or 0)
        exp_s = exp / 1000.0 if exp > 1e12 else exp
        out.append({
            "token": tok,
            "expiresAt": exp_s,
            "refreshToken": v.get("refreshToken"),
            "plan": CLAUDE_PLAN_BADGES.get(str(v.get("subscriptionType") or "").lower()),
        })
    return out


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
       桌面版令牌(持续自动续期,只读)与 CLI 凭证文件二选其新;都过期时才用 refreshToken 续期。
       force_refresh=True(收到 401 后)跳过刚被拒的桌面令牌,直接走 CLI 凭证续期。"""
    now = time.time()
    if not force_refresh:
        desk_valid = [d for d in _claude_desktop_tokens() if d["expiresAt"] > now + 60]
        if desk_valid:
            best = max(desk_valid, key=lambda d: d["expiresAt"])
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
                desk = _claude_desktop_tokens()
                if desk:
                    best = max(desk, key=lambda d: d["expiresAt"])
                    return _claude_bearer_headers(best["token"]), None, best.get("plan")
                return None, err, plan
        tok = creds.get("claudeAiOauth", {}).get("accessToken")
        return _claude_bearer_headers(tok), None, plan

    # 无 CLI 凭证:最后再看桌面令牌(含已过期的兜底)
    desk = _claude_desktop_tokens()
    if desk:
        best = max(desk, key=lambda d: d["expiresAt"])
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


def fetch_claude() -> dict:
    """拉取 Claude 用量。返回 {"windows": [(key, util, resets_at, label)], "plan": …} 或 {"error": …}。"""
    global _profile_plan, _profile_tried
    h, err, plan = claude_headers()
    if not h:
        return {"error": err}
    try:
        r = requests.get(API_URL_USAGE, headers=h, timeout=10)
        if r.status_code == 401:  # 服务端拒绝旧 token → 强制续期后重试一次
            h, err, plan = claude_headers(force_refresh=True)
            if not h:
                return {"error": err}
            r = requests.get(API_URL_USAGE, headers=h, timeout=10)
            if r.status_code == 401:
                return {"error": "登录已过期:请在终端运行一次 claude 重新登录"}
        if r.status_code == 429:
            return {"error": "请求过于频繁,稍后自动重试"}
        r.raise_for_status()
        data = r.json()
    except requests.ConnectionError:
        return {"error": "网络连接失败,重试中…"}
    except Exception as e:
        return {"error": f"获取失败:{type(e).__name__}"}
    wins = []
    for key, val in data.items():
        if (isinstance(val, dict) and val.get("utilization") is not None
                and val.get("resets_at")):
            wins.append((key, float(val["utilization"]), val["resets_at"], LABELS.get(key, key)))
    wins.sort(key=lambda it: (ORDER.index(it[0]) if it[0] in ORDER else len(ORDER), it[0]))
    if plan is None and not _profile_tried:  # 老版本凭证无 subscriptionType → 拉一次 profile 兜底
        _profile_tried = True
        acc = (fetch_profile(h) or {}).get("account", {})
        _profile_plan = "MAX" if acc.get("has_claude_max") else ("PRO" if acc.get("has_claude_pro") else None)
    return {"windows": wins, "plan": plan or _profile_plan}


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


def fetch_codex() -> dict:
    """拉取 Codex(ChatGPT 登录)限额。返回结构与 fetch_claude 一致。"""
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


FETCHERS = {"claude": fetch_claude, "codex": fetch_codex}


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
        self.hidden = set(cfg.get("hidden", []))
        self.reset_mode = cfg.get("reset_mode", "clock")
        self.tray_key = cfg.get("tray_key", DEFAULT_TRAY_KEY)
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
        canvas_bg = C_CARD
        force_opaque = bool(os.environ.get("QUOTA_CARD_OPAQUE"))
        if not force_opaque and IS_WIN:
            try:
                self.root.attributes("-transparentcolor", TRANSPARENT)
                canvas_bg = TRANSPARENT
            except Exception:
                canvas_bg = C_CARD
        elif not force_opaque and IS_MAC:
            try:
                self.root.configure(bg="systemTransparent")
                canvas_bg = "systemTransparent"
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
        while not self._stop:
            for p in PROVIDERS:
                if not self.providers.get(p) or self._stop:
                    continue
                res = FETCHERS[p]()
                old = self.state.get(p) or {}
                if "windows" in res:
                    cur = {"windows": res["windows"], "plan": res.get("plan") or old.get("plan"),
                           "error": None, "updated": time.time()}
                else:  # 失败时保留上一次数据,只标注错误
                    cur = {"windows": old.get("windows") or [], "plan": old.get("plan"),
                           "error": res.get("error"), "updated": old.get("updated", 0)}
                self.state = {**self.state, p: cur}
            self._refresh_evt.wait(REFRESH_INTERVAL)
            self._refresh_evt.clear()

    def _tick(self):
        if self._stop:
            return
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
        cv.create_oval(PAD, hy - self.s(4), PAD + self.s(8), hy + self.s(4), fill=C_ACCENT, outline="")
        if not multi and secs:
            title, badge = f"{PROVIDER_TITLES[secs[0]['p']]} 用量", secs[0]["plan"]
        else:
            title, badge = "AI 用量", None
        tid = cv.create_text(PAD + self.s(16), hy, text=title, anchor="w",
                             fill=C_TITLE, font=self.f(15, "bold"))
        if badge:
            self._draw_badge(cv, cv.bbox(tid)[2] + self.s(8), hy, badge)
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

    def _draw_badge(self, cv, x, cy, text, small=False):
        bw = self.s((10 if small else 12) + (6 if small else 7) * len(text))
        bh = self.s(7 if small else 8)
        round_rect(cv, x, cy - bh, x + bw, cy + bh, self.s(6), fill=C_ACCENT, outline="")
        cv.create_text(x + bw / 2, cy, text=text, fill="#ffffff", font=self.f(8 if small else 9, "bold"))

    def _draw_section(self, cv, y, SEC, s_, W, PAD):
        cy = y + SEC / 2 + self.s(3)
        cv.create_oval(PAD, cy - self.s(3), PAD + self.s(6), cy + self.s(3),
                       fill=PROVIDER_DOTS.get(s_["p"], C_SUB), outline="")
        tid = cv.create_text(PAD + self.s(12), cy, text=PROVIDER_TITLES[s_["p"]], anchor="w",
                             fill=C_TITLE, font=self.f(12, "bold"))
        if s_["plan"]:
            self._draw_badge(cv, cv.bbox(tid)[2] + self.s(6), cy, s_["plan"], small=True)
        if s_["error"] and s_["shown"]:  # 有旧数据但本轮刷新失败 → 分节右侧亮警示
            cv.create_text(W - PAD, cy, text="⚠", anchor="e", fill=C_AMBER, font=self.f(11))

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
        if not secs:
            dot, text = C_DIM, "未启用数据源"
        elif not have_data:
            dot, text = (C_RED, "未连接") if has_err else (C_AMBER, "正在加载…")
        else:
            ago = int(time.time() - max(s_["updated"] for s_ in have_data))
            text = "刚刚更新" if ago < 5 else (f"{ago} 秒前更新" if ago < 60 else f"{ago // 60} 分前更新")
            dot, text = (C_AMBER, text + " · 可能过期") if has_err else (C_GREEN, text)
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
        # 背景几乎填满整张图(让托盘里看起来和别的图标一样大),用量色描边
        d.rounded_rectangle([1, 1, sz - 2, sz - 2], radius=14,
                            fill=(27, 28, 32, 255), outline=tuple(rgb) + (255,), width=4)
        txt = f"{int(round(util))}%"
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

        m.add_separator()
        self._pin_var = tk.BooleanVar(value=self.pinned)
        m.add_checkbutton(label="窗口置顶", variable=self._pin_var, command=self.toggle_pin)
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
                "pinned": self.pinned, "hidden": sorted(self.hidden),
                "reset_mode": self.reset_mode, "tray_key": self.tray_key,
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
    print("User-Agent:", user_agent())
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
