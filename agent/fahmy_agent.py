"""CMSync Client — Local synchronization agent for ARC Raiders.

Capabilities:
  1) Scans ARC Raiders launcher/game memory for Pioneer JWT (read-only).
  2) Sends token to server (/api/accounts/auto) to link subscriber and pull inventory.
  3) Periodically repulls inventory (read-only) every PULL_SECONDS.
  4) Monitors game process every WATCH_SECONDS.
  5) Reads Embark Game Launcher early memory before engine window opens.
  6) Keeps manifest up to date.

Usage:
  python agent/fahmy_agent.py              # run in system tray
  python agent/fahmy_agent.py --once       # single cycle and print result
  python agent/fahmy_agent.py --console    # run in terminal without tray icon
  python agent/fahmy_agent.py --install    # desktop shortcut + Windows startup
  python agent/fahmy_agent.py --uninstall  # remove Windows startup
"""
import argparse
import ctypes
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import winreg
import tkinter as tk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memtoken  # noqa: E402

# Permanent cloud backend URL
SERVER_URL = "https://arccm.fastapicloud.dev"
CURRENT_SERVER_URL = SERVER_URL

# Set process AppUserModelID so Windows taskbar icon binds to this app
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CM.CMSync.Client.1.0")
except Exception:
    pass

SHOW_EVENT_NAME = "Local\\CMSync.ShowWindowEvent"
APP_NAME = "CMSync"
APP_DISPLAY_NAME = "CMSync Client"
APP_VERSION = "2.3.0"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")
LOG_FILE = os.path.join(CONFIG_DIR, "agent.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_PROJECT = r"C:\Users\Administrator\Desktop\tt_8004"
DEFAULT_PORT = 8004
RESCAN_SECONDS = 300
PULL_SECONDS = 120
LAUNCHER_SCAN_SECONDS = 60
BOOT_GAP = 15
BOOT_WINDOW = 300
LAUNCHER_BUDGET_MB = 768
SCAN_BUDGET_SECONDS = 25
LOG_KEEP = 400

PRIMARY_TOKEN_JSON = r"C:\tokens.json"
PRIMARY_TOKEN_TXT = r"C:\tokens.txt"
FALLBACK_TOKEN_JSON = os.path.join(CONFIG_DIR, "tokens.json")
FALLBACK_TOKEN_TXT = os.path.join(CONFIG_DIR, "tokens.txt")
DEFAULT_TOKEN_FILE = PRIMARY_TOKEN_JSON

# Thread-safe UI message queue for cross-thread communications
ui_queue = queue.Queue()


def log(message):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        lines = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.read().splitlines()[-LOG_KEEP:]
        lines.append(line.strip())
        with open(LOG_FILE, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass
    print(line.strip())


def refresh_server_url(force=False):
    """Refreshes SERVER_URL - returns hardcoded permanent server URL."""
    global SERVER_URL, CURRENT_SERVER_URL
    SERVER_URL = "https://arccm.fastapicloud.dev"
    CURRENT_SERVER_URL = SERVER_URL
    return SERVER_URL


def default_config():
    python = sys.executable
    if getattr(sys, "frozen", False):
        python = os.environ.get("FAHMY_PYTHON") or _find_python() or python
    return {
        "project": DEFAULT_PROJECT,
        "port": DEFAULT_PORT,
        "python": python,
        "ensure_site": True,
        "idle_seconds": 30,
        "open_browser": False,
        "token_file": DEFAULT_TOKEN_FILE,
        "server_url": SERVER_URL,
        "subscriber_token": "",
        "subscriber_name": "",
    }


def _find_python():
    for name in ("python", "python3", "py"):
        found = subprocess.run(["where", name], capture_output=True, text=True, shell=False)
        for line in (found.stdout or "").splitlines():
            candidate = line.strip()
            if candidate.lower().endswith("python.exe") and "WindowsApps" not in candidate:
                return candidate
    return ""


def load_config():
    cfg = default_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh) or {})
    except (OSError, ValueError):
        pass
    # Strictly lock server_url and base_url to https://arccm.fastapicloud.dev
    # while preserving subscriber_token and subscriber_name!
    global SERVER_URL, CURRENT_SERVER_URL
    SERVER_URL = "https://arccm.fastapicloud.dev"
    CURRENT_SERVER_URL = SERVER_URL
    cfg["server_url"] = SERVER_URL
    cfg["base_url"] = SERVER_URL
    save_config(cfg)
    return cfg


def save_config(cfg):
    cfg["server_url"] = SERVER_URL
    cfg["base_url"] = SERVER_URL
    os.makedirs(CONFIG_DIR, exist_ok=True)
    body = {k: v for k, v in cfg.items() if k != "base_url"}
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2, ensure_ascii=False)


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def http(method, url, body=None, headers=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    base_headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }
    if headers:
        base_headers.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=base_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except Exception:
            return exc.code, {}
    except Exception as exc:
        return 0, {"error": str(exc)[:160]}


def site_status(cfg):
    """Ping /api/status — sends X-Subscriber-Token so middleware allows it without cookie."""
    headers = {}
    if cfg.get("subscriber_token"):
        headers["X-Subscriber-Token"] = cfg["subscriber_token"]
    status, body = http("GET", SERVER_URL + "/api/status", headers=headers, timeout=4)
    log("site_status: HTTP %s — %s" % (status, body))
    return status, body


def agent_key(cfg):
    """Device key: returns subscriber_token if configured, else retrieves shared key."""
    if cfg.get("subscriber_token"):
        return cfg["subscriber_token"]
    status, body = http("GET", SERVER_URL + "/api/agent/handshake", timeout=6)
    if status == 200 and body.get("key"):
        cfg["project"] = body.get("project") or cfg["project"]
        return body["key"]
    path = os.path.join(cfg.get("project") or "", "data", "agent_secret.txt")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def push(cfg, key, token):
    headers = {}
    if cfg.get("subscriber_token"):
        headers["X-Subscriber-Token"] = cfg["subscriber_token"]
    else:
        headers["X-Fahmy-Agent"] = key
    status, body = http("POST", SERVER_URL + "/api/accounts/auto",
                        body={"token": token}, headers=headers, timeout=120)
    return status, body


def panel_names(cfg, key):
    """Retrieves account names known to the dashboard."""
    headers = {}
    if cfg.get("subscriber_token"):
        headers["X-Subscriber-Token"] = cfg["subscriber_token"]
    else:
        headers["X-Fahmy-Agent"] = key
    status, body = http("GET", SERVER_URL + "/api/accounts", headers=headers)
    if status != 200:
        return None
    out = set()
    for rec in (body or {}).get("accounts") or []:
        out.update(v for v in (rec.get("name"), rec.get("display_name")) if v)
    return out


def deliver(cfg, key, state, token, jti="", exp=0.0, notify=None):
    """Sends token to dashboard and records state."""
    pushed = state.setdefault("pushed", {})
    status, body = push(cfg, key, token)
    if status == 400 or status == 403:
        state["last_error"] = body.get("detail") or str(status)
        log("Dashboard rejected token (%s): %s" % (status, state["last_error"]))
        return None
    if status == 200 and not (body.get("pulled") or {}).get("ok") and not body.get("created"):
        state["last_error"] = (body.get("pulled") or {}).get("error") or "gateway refused"
        log("Gateway rejected token (%s)" % state["last_error"])
        if jti:
            pushed[jti] = {"at": time.time(), "bad": True,
                           "account": account_name(body), "exp": exp}
        return None
    label, internal = account_label(body), account_name(body)
    if jti:
        pushed[jti] = {"at": time.time(), "account": internal, "exp": exp,
                       "created": bool(body.get("created"))}
    held = state.setdefault("held", {})
    held[internal] = token
    for stale in list(held)[:-12]:
        held.pop(stale, None)
    state["last_push"] = time.time()
    state["account"] = internal
    state["display"] = label
    state["exp"] = exp or float(state.get("exp") or 0)
    state["last_error"] = ""
    save_state(state)
    write_token_file(cfg, label, token)
    note = body.get("note") or ""
    if body.get("created"):
        message = "New account registered: %s" % label
    elif "refresh" in note:
        message = "Account token refreshed: %s" % label
    else:
        message = "Token unchanged: %s" % label
    left = (float(state.get("exp") or 0) - time.time()) / 3600
    log("%s%s" % (message, " (%.0f h)" % left if left > 0 else ""))
    if notify and (body.get("created") or "refresh" in note):
        notify(message)
    return message


def account_name(body):
    return ((body or {}).get("account") or {}).get("name") or "?"


def account_label(body):
    acc = (body or {}).get("account") or {}
    return acc.get("display_name") or acc.get("name") or "?"


def compute_token_expiry(token, saved_at=None):
    if saved_at is None:
        saved_at = time.time()
    token_exp = 0.0
    try:
        info = memtoken.inspect(token, strict=False)
        if info and info.get("exp"):
            token_exp = float(info["exp"])
    except Exception:
        pass
    if token_exp > 0:
        expires_at = min(token_exp, saved_at + 86400.0)
    else:
        expires_at = saved_at + 86400.0
    return saved_at, expires_at


def _can_write_dir(path):
    try:
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        test = os.path.join(d, ".perm_test.tmp")
        with open(test, "w") as fh:
            fh.write("1")
        os.remove(test)
        return True
    except (OSError, PermissionError):
        return False


def get_token_paths(cfg=None):
    target = (cfg.get("token_file") if cfg else None) or PRIMARY_TOKEN_JSON
    if not _can_write_dir(target):
        return FALLBACK_TOKEN_JSON, FALLBACK_TOKEN_TXT
    d = os.path.dirname(os.path.abspath(target)).upper()
    if d in ("C:\\", "C:"):
        return PRIMARY_TOKEN_JSON, PRIMARY_TOKEN_TXT
    base_dir = os.path.dirname(os.path.abspath(target))
    return os.path.join(base_dir, "tokens.json"), os.path.join(base_dir, "tokens.txt")


def load_token_data(json_path):
    if not os.path.isfile(json_path):
        return {"accounts": {}, "updated_at": 0}
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, dict):
                return {"accounts": {}, "updated_at": 0}
            if "accounts" not in data or not isinstance(data["accounts"], dict):
                data["accounts"] = {}
            return data
    except Exception:
        return {"accounts": {}, "updated_at": 0}


def save_token_data(data, json_path, txt_path):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        log("Failed to write token JSON %s: %s" % (json_path, exc))
        return False

    try:
        os.makedirs(os.path.dirname(os.path.abspath(txt_path)), exist_ok=True)
        lines = []
        for acc_name, info in (data.get("accounts") or {}).items():
            tok = info.get("token") or ""
            if tok:
                lines.append("%s\n%s" % (acc_name, tok))
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
    except Exception as exc:
        log("Failed to write token TXT %s: %s" % (txt_path, exc))
    return True


def clean_expired_tokens(cfg=None, json_path=None, txt_path=None):
    """Purges any token where now >= expires_at or now - saved_at >= 24h."""
    try:
        if not json_path or not txt_path:
            json_path, txt_path = get_token_paths(cfg)
        if not os.path.isfile(json_path):
            return 0
        data = load_token_data(json_path)
        accounts = data.get("accounts") or {}
        now = time.time()
        expired = []
        for name, info in list(accounts.items()):
            saved_at = float(info.get("saved_at") or 0)
            expires_at = float(info.get("expires_at") or 0)
            if saved_at <= 0 or expires_at <= 0 or now >= expires_at or (now - saved_at) >= 86400.0:
                expired.append(name)
        if expired:
            for name in expired:
                accounts.pop(name, None)
                log("Cleaned expired token for account: %s" % name)
            data["updated_at"] = now
            save_token_data(data, json_path, txt_path)
        return len(expired)
    except Exception as exc:
        log("Token cleanup error: %s" % exc)
        return 0


def write_token_file(cfg, name, token):
    if not name or name == "?" or not token:
        return False
    json_path, txt_path = get_token_paths(cfg)
    clean_expired_tokens(cfg, json_path=json_path, txt_path=txt_path)

    data = load_token_data(json_path)
    accounts = data.setdefault("accounts", {})
    now = time.time()
    saved_at, expires_at = compute_token_expiry(token, saved_at=now)

    existing = accounts.get(name)
    if existing and existing.get("token") == token:
        if float(existing.get("expires_at") or 0) > now:
            return True

    accounts[name] = {
        "account": name,
        "token": token,
        "saved_at": saved_at,
        "saved_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(saved_at)),
        "expires_at": expires_at,
        "expires_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at)),
    }
    data["updated_at"] = now
    ok = save_token_data(data, json_path, txt_path)
    if ok and not cfg.get("_token_file_warned"):
        cfg["_token_file_warned"] = True
        log("Token saved for %s to %s and %s" % (name, json_path, txt_path))
    return ok


def open_token_file(cfg=None, _icon=None, _item=None):
    try:
        json_path, txt_path = get_token_paths(cfg)
        target = txt_path if os.path.isfile(txt_path) else json_path
        if not os.path.exists(target):
            data = {"accounts": {}, "updated_at": time.time()}
            save_token_data(data, json_path, txt_path)
            target = txt_path if os.path.isfile(txt_path) else json_path
        os.startfile(target)
    except Exception as exc:
        log("Failed to open token file: %s" % exc)


def _parse_version(v_str):
    try:
        clean = re.sub(r"[^0-9\.]", "", str(v_str).strip())
        parts = [int(x) for x in clean.split(".") if x.isdigit()]
        return tuple(parts) if parts else (0, 0, 0)
    except Exception:
        return (0, 0, 0)


def check_for_updates(cfg, manual=False):
    """Background check against SERVER_URL/api/cmsync/version."""
    def worker():
        try:
            refresh_server_url(force=True)
            status, body = http("GET", SERVER_URL + "/api/cmsync/version", timeout=8)
            ui_queue.put(("update_check_result", manual, status, body))
        except Exception as exc:
            ui_queue.put(("update_check_result", manual, 0, {"error": str(exc)}))
    threading.Thread(target=worker, daemon=True).start()


def perform_update_download(dl_url, expected_sha):
    """Downloads installer to %TEMP% and runs it."""
    def worker():
        temp_dir = tempfile.gettempdir()
        installer_path = os.path.join(temp_dir, "CMSync_Setup_Update.exe")
        full_url = dl_url if dl_url.startswith("http") else (SERVER_URL + dl_url)
        log("Downloading update from %s to %s..." % (full_url, installer_path))
        try:
            req = urllib.request.Request(full_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            })
            with urllib.request.urlopen(req, timeout=60) as resp, open(installer_path, "wb") as out_f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_f.write(chunk)

            if expected_sha:
                h = hashlib.sha256()
                with open(installer_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                actual_sha = h.hexdigest().lower()
                if actual_sha != expected_sha.lower():
                    log("Update verification failed: SHA256 mismatch (%s != %s)" % (actual_sha, expected_sha))
                    ui_queue.put(("update_error", "Update verification failed (SHA256 mismatch). Please try again."))
                    return

            log("Update download verified. Launching installer: %s" % installer_path)
            subprocess.Popen([installer_path], shell=False)
            time.sleep(1)
            os._exit(0)
        except Exception as exc:
            log("Update download error: %s" % exc)
            ui_queue.put(("update_error", "Failed to download update: %s" % exc))

    threading.Thread(target=worker, daemon=True).start()


def repull(cfg, state, notify=None, now=False):
    """Re-sends saved token for the same account to pull inventory read-only."""
    every = float(cfg.get("pull_seconds") or PULL_SECONDS)
    if not now and time.time() - float(state.get("last_pull") or 0) < every:
        return None
    held = (state.get("held") or {}).get(state.get("account"))
    if not held:
        return None
    key = agent_key(cfg)
    if not key:
        return None
    state["last_pull"] = time.time()
    if not deliver(cfg, key, state, held, notify=notify):
        return None
    return "Auto-refreshed %s — %s" % (time.strftime("%H:%M"),
                                        state.get("display") or state.get("account"))


def scan_gap(cfg, state, launcher):
    if state.get("boot_poll"):
        return float(cfg.get("boot_gap") or BOOT_GAP)
    if not launcher:
        return float(cfg.get("rescan_seconds") or RESCAN_SECONDS)
    return float(cfg.get("launcher_scan_seconds") or LAUNCHER_SCAN_SECONDS)


def harvest(cfg, launcher, engine, broken):
    """Scans launcher or engine process memory for Pioneer JWT token."""
    for pid in launcher:
        try:
            got = memtoken.scan(pid, partial=broken,
                                max_bytes=LAUNCHER_BUDGET_MB * (1 << 20),
                                max_seconds=cfg.get("scan_seconds") or SCAN_BUDGET_SECONDS)
        except OSError as exc:
            log("Scan of launcher PID %s failed: %s" % (pid, exc))
            continue
        if got:
            return got, pid
    for pid in engine:
        try:
            got = memtoken.scan(pid, partial=broken)
        except OSError as exc:
            log("Scan of engine PID %s failed: %s" % (pid, exc))
            continue
        if got:
            return got, pid
    return [], 0


def sync_once(cfg, state, force=False, notify=None):
    """Single cycle: scans game/launcher memory and delivers token."""
    clean_expired_tokens(cfg)
    status, _ = site_status(cfg)
    if status != 200:
        log("sync_once: dashboard unreachable (HTTP %s) — skipping memory scan" % status)
        state["last_error"] = "Dashboard is unreachable"
        return "Dashboard is unreachable"
    log("sync_once: dashboard OK — starting memory scan")
    launcher, engine = memtoken.split_pids()
    pids = launcher + engine
    switched = "game" in state and bool(state.get("game")) != bool(pids)
    if not pids:
        state["game"] = False
        state["boot_poll"] = False
        if switched:
            out = repull(cfg, state, notify, now=True)
            if out:
                return out
        last = time.strftime("%H:%M", time.localtime(state.get("last_push") or 0))
        return "Game closed | last sync %s" % last if state.get("last_push") else "Game closed"
    if switched or not state.get("game") or not state.get("game_seen"):
        state["game_seen"] = time.time()
        state["has_token"] = False
    state["game"] = True
    state["boot_poll"] = (bool(launcher) and not state.get("has_token")
                          and time.time() - float(state.get("game_seen") or 0) < BOOT_WINDOW)
    key = agent_key(cfg)
    if not key:
        state["last_error"] = "No device key"
        return "No device key"
    exp = float(state.get("exp") or 0)
    gap = scan_gap(cfg, state, launcher)
    since_scan = time.time() - float(state.get("last_scan") or 0)
    held = (state.get("held") or {}).get(state.get("account"))
    rested = not force and not switched and since_scan < gap and state.get("pid") in pids
    if rested:
        if not (held and exp > time.time()):
            return "Waiting for token in memory — scanning in %d s" % int(max(1, gap - since_scan))
        known = panel_names(cfg, key)
        if known is None or state.get("account") in known:
            return repull(cfg, state, notify) or "Token active (%.0f h left)" % ((exp - time.time()) / 3600)
        log("Account %s missing from dashboard — re-registering" % state.get("account"))
        out = deliver(cfg, key, state, held, notify=notify)
        if out:
            return out
        state["last_scan"] = 0
    broken = []
    tokens, scanned = harvest(cfg, launcher, engine, broken)
    state["last_scan"] = time.time()
    state["pid"] = scanned or pids[0]
    if not tokens:
        state["last_error"] = ("Truncated token copies in memory (%d)" % len(broken)) if broken else "No token in memory"
        if broken:
            return "Found incomplete token copies — waiting for complete signature"
        return "Launcher detected — waiting for token (%d s)" % int(max(1, gap - since_scan))
    state["has_token"] = True
    state["boot_poll"] = False
    write_token_file(cfg, state.get("display") or state.get("account"), tokens[0]["token"])
    pushed = state.setdefault("pushed", {})
    known = panel_names(cfg, key)
    for cand in tokens[:3]:
        record = pushed.get(cand["jti"])
        if record and not force and (known is None or record.get("account") in known):
            write_token_file(cfg, state.get("display") or record.get("account") or state.get("account"),
                             cand["token"])
            continue
        out = deliver(cfg, key, state, cand["token"], cand["jti"], cand["exp"], notify)
        if out:
            return out
    return repull(cfg, state, notify, now=True) or "Tokens in memory are up to date"


WATCH_SECONDS = 3
LAUNCH_GRACE = 5
MANIFEST_SECONDS = 600


def refresh_manifest(cfg, state, force=False, notify=None):
    """Requests current game manifest number from dashboard."""
    now = time.time()
    if not force and now - float(state.get("manifest_at") or 0) < MANIFEST_SECONDS:
        return ""
    state["manifest_at"] = now
    key = agent_key(cfg)
    if not key:
        return ""
    headers = {"X-Subscriber-Token": cfg["subscriber_token"]} if cfg.get("subscriber_token") else {"X-Fahmy-Agent": key}
    status, body = http("POST", SERVER_URL + "/api/agent/manifest", body={},
                        headers=headers, timeout=90)
    if status != 200:
        log("Manifest check failed (%s): %s" % (status, str(body)[:140]))
        return ""
    if not body.get("changed"):
        return "Manifest %s" % body.get("manifest_id")
    log("Game patch: manifest updated to %s (was %s)" % (body.get("manifest_id"), body.get("old")))
    state["manifest_changed_at"] = now
    save_state(state)
    if notify:
        notify("Game patched — manifest updated automatically.")
    return "Manifest updated to %s" % body.get("manifest_id")


def exe_path():
    return sys.executable if getattr(sys, "frozen", False) else ""


def game_running():
    try:
        return bool(memtoken.find_pids())
    except OSError:
        return False


def _sleep(seconds, stop):
    waited = 0
    while waited < seconds and not stop.is_set():
        time.sleep(1)
        waited += 1


def wait_next_cycle(cfg, state, stop, interval):
    if interval:
        _sleep(interval, stop)
        return
    span = float(cfg.get("idle_seconds") or 30)
    if state.get("boot_poll"):
        span = min(span, float(cfg.get("boot_gap") or BOOT_GAP))
    deadline = time.time() + span
    was = game_running()
    while time.time() < deadline and not stop.is_set():
        _sleep(WATCH_SECONDS, stop)
        now = game_running()
        if now != was:
            if now:
                log("Game started — waiting %d seconds to scan" % LAUNCH_GRACE)
                _sleep(LAUNCH_GRACE, stop)
            else:
                log("Game exited — immediate sync")
            return


def loop(cfg, state, stop, notify=None, interval=None):
    was_game = bool(state.get("game"))
    last_cleanup = time.time()
    clean_expired_tokens(cfg)
    while not stop.is_set():
        try:
            if time.time() - last_cleanup >= 600.0:
                clean_expired_tokens(cfg)
                last_cleanup = time.time()
            text = sync_once(cfg, state, notify=notify)
            opened = bool(state.get("game")) and not was_game
            was_game = bool(state.get("game"))
            note = refresh_manifest(cfg, state, force=opened, notify=notify)
            if note and (opened or "updated" in note):
                text = "%s | %s" % (text, note)
        except Exception as exc:
            text = "Error: %s" % exc
            log(text)
        state["status"] = text
        state["report_at"] = time.time()
        save_state(state)
        wait_next_cycle(cfg, state, stop, interval)


def make_icon():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, 63, 63], radius=16, fill=(12, 12, 18, 255))
    d.rounded_rectangle([2, 2, 62, 62], radius=16, outline=(168, 85, 247, 255), width=3)
    d.rounded_rectangle([7, 7, 57, 57], radius=12, outline=(217, 70, 239, 130), width=1)
    font = None
    for path in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf"):
        try:
            font = ImageFont.truetype(path, 24)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    d.text((30, 33), "CM", font=font, fill=(255, 255, 255, 255), anchor="mm")
    d.ellipse([43, 10, 52, 19], fill=(224, 182, 74, 255))
    return img


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_startup(enable):
    if getattr(sys, "frozen", False):
        exe = '"%s"' % sys.executable
    else:
        exe = '"%s" "%s"' % (sys.executable, os.path.abspath(__file__))
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass
        winreg.CloseKey(key)
        return True
    except OSError as exc:
        log("Could not update Windows startup: %s" % exc)
        return False


def desktop_shortcut():
    if getattr(sys, "frozen", False):
        target, args, workdir = sys.executable, "", CONFIG_DIR
    else:
        here = os.path.abspath(__file__)
        target, args, workdir = "python.exe", '"%s"' % here, os.path.dirname(here)
    link = os.path.join(os.path.expanduser("~"), "Desktop", "%s.lnk" % APP_DISPLAY_NAME)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';"
          "$s.Arguments='%s';$s.WorkingDirectory='%s';$s.Save()"
          % tuple(str(x).replace("'", "''") for x in (link, target, args, workdir)))
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30)
        return os.path.exists(link)
    except Exception as exc:
        log("Desktop shortcut error: %s" % exc)
        return False


def single_instance():
    kernel32 = ctypes.WinDLL("kernel32")
    handle = kernel32.CreateMutexW(None, False, "Local\\CMSync.Tray")
    if not handle:
        return None
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        # Signal existing instance to restore its window
        try:
            hEvent = kernel32.OpenEventW(0x0002, False, SHOW_EVENT_NAME)
            if hEvent:
                kernel32.SetEvent(hEvent)
                kernel32.CloseHandle(hEvent)
        except Exception:
            pass
        return None
    return handle


def get_clipboard_text():
    try:
        r = tk._default_root
        if r:
            txt = r.clipboard_get()
            if txt:
                return str(txt)
    except Exception:
        pass
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        if u32.OpenClipboard(0):
            try:
                CF_UNICODETEXT = 13
                h = u32.GetClipboardData(CF_UNICODETEXT)
                if h:
                    ptr = k32.GlobalLock(h)
                    if ptr:
                        try:
                            val = ctypes.wstring_at(ptr)
                            if val:
                                return str(val)
                        finally:
                            k32.GlobalUnlock(h)
            finally:
                u32.CloseClipboard()
    except Exception:
        pass
    return ""


def find_app_icon():
    candidates = [
        getattr(sys, "_MEIPASS", ""),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent"),
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
        r"C:\Users\Administrator\Desktop\tt_8004\agent"
    ]
    for c in candidates:
        if c:
            p = os.path.join(c, "cmsync.ico")
            if os.path.isfile(p):
                return p
    return ""


def apply_dark_theme_to_window(window):
    try:
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark_flag = ctypes.c_int(1)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag)
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag)
            )
        DWMWA_CAPTION_COLOR = 35
        color = ctypes.c_int(0x00170F0D)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(color), ctypes.sizeof(color)
        )
    except Exception:
        pass


def apply_app_icon(window):
    ico_path = find_app_icon()
    if not ico_path:
        return
    try:
        window.iconbitmap(ico_path)
    except Exception:
        pass
    try:
        from PIL import Image, ImageTk
        img = Image.open(ico_path)
        photo = ImageTk.PhotoImage(img)
        window.iconphoto(True, photo)
        window._icon_photo_ref = photo
    except Exception:
        pass
    try:
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
        hIcon = ctypes.windll.user32.LoadImageW(None, ico_path, 1, 0, 0, 0x00000010)
        if hIcon:
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hIcon)
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hIcon)
            ctypes.windll.user32.SendMessageW(window.winfo_id(), 0x0080, 0, hIcon)
            ctypes.windll.user32.SendMessageW(window.winfo_id(), 0x0080, 1, hIcon)
    except Exception:
        pass


def build_gui(root, cfg, on_linked_callback=None):
    """Builds the 100% English, password-masked GUI inside the Tkinter root."""
    root.title(APP_DISPLAY_NAME)
    w, h = 500, 360
    root.geometry(f"{w}x{h}")
    root.minsize(w, h)
    root.maxsize(w, h)
    root.configure(bg="#0d0f17")

    # When X is pressed: NEVER exit process, only hide window to tray!
    def on_window_close():
        root.withdraw()

    root.protocol("WM_DELETE_WINDOW", on_window_close)

    def on_taskbar_map(event):
        if event.widget == root:
            root.deiconify()
            root.lift()

    root.bind("<Map>", on_taskbar_map)

    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() // 2) - (w // 2))
    y = max(0, (root.winfo_screenheight() // 2) - (h // 2))
    root.geometry(f"{w}x{h}+{x}+{y}")

    apply_dark_theme_to_window(root)
    apply_app_icon(root)

    header_card = tk.Frame(root, bg="#161824", highlightthickness=1, highlightbackground="#252a3d", padx=16, pady=12)
    header_card.pack(fill="x", padx=20, pady=(16, 12))

    head_top = tk.Frame(header_card, bg="#161824")
    head_top.pack(fill="x")

    badge_lbl = tk.Label(head_top, text=f"⚡ CMSYNC CLIENT v{APP_VERSION}", font=("Segoe UI", 8, "bold"),
                         fg="#c084fc", bg="#261b3d", padx=8, pady=2)
    badge_lbl.pack(side="left")

    title_lbl = tk.Label(header_card, text="Connect Game to Cloud Dashboard", font=("Segoe UI", 12, "bold"),
                         fg="#f8fafc", bg="#161824", anchor="w")
    title_lbl.pack(fill="x", pady=(6, 2))

    desc_lbl = tk.Label(header_card, text="Link your device for instant real-time synchronization.",
                        font=("Segoe UI", 9), fg="#94a3b8", bg="#161824", anchor="w")
    desc_lbl.pack(fill="x")

    container = tk.Frame(root, bg="#0d0f17")
    container.pack(padx=20, fill="both", expand=True)

    # Context holders for thread-safe UI updates
    active_widgets = {}

    def render_content():
        for widget in container.winfo_children():
            widget.destroy()

        sub_token = (cfg.get("subscriber_token") or "").strip()
        sub_name = (cfg.get("subscriber_name") or "").strip()

        if sub_token and sub_name:
            # Connected view
            connected_frame = tk.Frame(container, bg="#161824", highlightthickness=1,
                                       highlightbackground="#22c55e", padx=16, pady=14)
            connected_frame.pack(fill="x", pady=10)

            c_hdr = tk.Label(connected_frame, text=f"✔ Connected as: {sub_name}",
                             font=("Segoe UI", 11, "bold"), fg="#22c55e", bg="#161824")
            c_hdr.pack(anchor="w")

            c_sub = tk.Label(connected_frame, text="Status: Ready / Waiting for Game",
                             font=("Segoe UI", 9), fg="#94a3b8", bg="#161824")
            c_sub.pack(anchor="w", pady=(4, 8))

            def do_unlink():
                cfg["subscriber_token"] = ""
                cfg["subscriber_name"] = ""
                save_config(cfg)
                render_content()

            unlink_btn = tk.Button(connected_frame, text="Unlink / Change Token", font=("Segoe UI", 9),
                                   bg="#252a3d", fg="#f87171", activebackground="#7f1d1d", activeforeground="#ffffff",
                                   relief="flat", cursor="hand2", padx=12, pady=3, command=do_unlink)
            unlink_btn.pack(anchor="w")

            status_lbl = tk.Label(container, text="Agent is active and monitoring ARC Raiders.",
                                  font=("Segoe UI", 9), fg="#64748b", bg="#0d0f17")
            status_lbl.pack(pady=(12, 4))

            close_btn = tk.Button(container, text="Minimize to Tray", font=("Segoe UI", 10, "bold"),
                                  bg="#8b5cf6", fg="#ffffff", activebackground="#7c3aed", activeforeground="#ffffff",
                                  relief="flat", cursor="hand2", command=root.withdraw)
            close_btn.pack(pady=8, ipady=5, ipadx=20)

        else:
            # Token input view
            tok_lbl = tk.Label(container, text="Subscriber Token:", font=("Segoe UI", 9, "bold"),
                               fg="#e2e8f0", bg="#0d0f17", anchor="w")
            tok_lbl.pack(fill="x", pady=(4, 3))

            tok_row = tk.Frame(container, bg="#0d0f17")
            tok_row.pack(fill="x", pady=(0, 6))

            tok_var = tk.StringVar(value="")
            # Password masking by default (dots/bullets)
            tok_entry = tk.Entry(tok_row, textvariable=tok_var, font=("Consolas", 10), bg="#161824", fg="#f8fafc",
                                 show="•", insertbackground="#ffffff", relief="flat", highlightthickness=1,
                                 highlightbackground="#2b3147", highlightcolor="#a855f7",
                                 justify="left", state="normal", takefocus=True)
            tok_entry.pack(side="left", fill="x", expand=True, ipady=6)

            # Eye toggle button to show/hide masked password
            mask_state = [True]

            def toggle_mask():
                mask_state[0] = not mask_state[0]
                tok_entry.config(show="•" if mask_state[0] else "")
                eye_btn.config(text="👁" if mask_state[0] else "🙈")

            eye_btn = tk.Button(tok_row, text="👁", font=("Segoe UI", 10),
                                bg="#252a3d", fg="#cbd5e1", activebackground="#334155", activeforeground="#ffffff",
                                relief="flat", cursor="hand2", padx=8, command=toggle_mask)
            eye_btn.pack(side="right", padx=(4, 0), ipady=3)

            def do_paste_token():
                txt = get_clipboard_text().strip()
                if txt:
                    tok_var.set(txt)
                    status_lbl.config(text="✔ Token pasted from clipboard", fg="#22c55e")
                else:
                    status_lbl.config(text="⚠️ Clipboard is empty", fg="#f59e0b")

            paste_btn = tk.Button(tok_row, text="📋 Paste", font=("Segoe UI", 8, "bold"),
                                  bg="#252a3d", fg="#f8fafc", activebackground="#a855f7", activeforeground="#ffffff",
                                  relief="flat", cursor="hand2", padx=12, command=do_paste_token)
            paste_btn.pack(side="right", padx=(8, 0), ipady=4)

            # Context menu for right-click
            def attach_context_menu(entry, str_var):
                m = tk.Menu(root, tearoff=0, bg="#161824", fg="#ffffff", activebackground="#a855f7")

                def do_copy():
                    try:
                        txt = entry.selection_get() if entry.select_present() else entry.get()
                        if txt:
                            root.clipboard_clear()
                            root.clipboard_append(txt)
                            status_lbl.config(text="✔ Copied to clipboard", fg="#22c55e")
                    except Exception:
                        pass

                def do_paste():
                    txt = get_clipboard_text().strip()
                    if txt:
                        str_var.set(txt)
                        status_lbl.config(text="✔ Pasted from clipboard", fg="#22c55e")

                def do_select_all():
                    entry.select_range(0, tk.END)
                    entry.icursor(tk.END)

                m.add_command(label="📋 Paste", command=do_paste)
                m.add_command(label="📄 Copy", command=do_copy)
                m.add_command(label="🔘 Select All", command=do_select_all)

                def show_popup(e):
                    try:
                        entry.focus_set()
                        m.tk_popup(e.x_root, e.y_root)
                    except Exception:
                        pass
                    finally:
                        try:
                            m.grab_release()
                        except Exception:
                            pass
                    return "break"

                entry.bind("<Button-3>", show_popup)

            attach_context_menu(tok_entry, tok_var)

            # Auto paste candidate token if on clipboard
            clip = get_clipboard_text().strip()
            if len(clip) >= 20 and not clip.startswith("http"):
                tok_var.set(clip)

            status_lbl = tk.Label(container, text="", font=("Segoe UI", 9, "bold"), fg="#ef4444", bg="#0d0f17")
            status_lbl.pack(pady=(2, 6))

            def on_connect():
                tok = tok_var.get().strip()
                if not tok:
                    status_lbl.config(text="Please enter subscriber token", fg="#ef4444")
                    return

                status_lbl.config(text="Verifying subscriber token...", fg="#a855f7")
                btn.config(state="disabled")
                root.update_idletasks()

                def do_verify():
                    try:
                        refresh_server_url(force=False)
                        status, body = http("POST", SERVER_URL + "/api/subscriber/verify",
                                            body={"token": tok}, timeout=10)
                    except Exception as exc:
                        status, body = 0, {"error": str(exc)}
                    # Post result to thread-safe queue
                    ui_queue.put(("verify_result", status, body, tok))

                threading.Thread(target=do_verify, daemon=True).start()

            btn = tk.Button(container, text="Connect & Start", font=("Segoe UI", 10, "bold"),
                            bg="#8b5cf6", fg="#ffffff", activebackground="#7c3aed", activeforeground="#ffffff",
                            relief="flat", cursor="hand2", command=on_connect)
            btn.pack(ipady=7, ipadx=24, pady=(2, 6))

            tok_entry.bind("<Return>", lambda e: on_connect())
            tok_entry.focus_set()

            active_widgets["btn"] = btn
            active_widgets["status_lbl"] = status_lbl

    # Queue message processor running safely on main thread
    def process_ui_queue():
        try:
            while True:
                msg = ui_queue.get_nowait()
                if msg == "show_window":
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", True)
                    root.after(100, lambda: root.attributes("-topmost", False))
                    root.focus_force()
                elif isinstance(msg, tuple) and msg[0] == "verify_result":
                    _, status, body, tok = msg
                    btn = active_widgets.get("btn")
                    status_lbl = active_widgets.get("status_lbl")
                    if btn:
                        try:
                            btn.config(state="normal")
                        except Exception:
                            pass
                    if status == 200 and body.get("ok"):
                        sub_name = body.get("name") or "Subscriber"
                        cfg["subscriber_token"] = tok
                        cfg["subscriber_name"] = sub_name
                        cfg["server_url"] = SERVER_URL
                        cfg["base_url"] = SERVER_URL
                        save_config(cfg)
                        if status_lbl:
                            try:
                                status_lbl.config(text=f"✔ Connected successfully! Welcome {sub_name}", fg="#22c55e")
                            except Exception:
                                pass
                        if on_linked_callback:
                            on_linked_callback(sub_name)
                        render_content()
                        # Hide window after 1.2s to tray, keeping process running
                        root.after(1200, root.withdraw)
                    elif status == 401:
                        if status_lbl:
                            try:
                                status_lbl.config(text="❌ Invalid or expired subscriber token", fg="#ef4444")
                            except Exception:
                                pass
                    else:
                        err = body.get("detail") or body.get("error") or str(status)
                        if status_lbl:
                            try:
                                status_lbl.config(text=f"❌ Connection error: {err}", fg="#ef4444")
                            except Exception:
                                pass
                elif isinstance(msg, tuple) and msg[0] == "update_check_result":
                    _, manual, status, body = msg
                    if status == 200 and isinstance(body, dict):
                        srv_ver = body.get("version") or ""
                        dl_url = body.get("download_url") or "/download/CMSync_Setup.exe"
                        expected_sha = body.get("sha256") or ""
                        if _parse_version(srv_ver) > _parse_version(APP_VERSION):
                            ans = messagebox.askyesno(
                                "CMSync Update Available",
                                f"A new version v{srv_ver} of CMSync is available.\n"
                                f"Current installed version: v{APP_VERSION}\n\n"
                                f"Would you like to download and install the update now?",
                                parent=root
                            )
                            if ans:
                                perform_update_download(dl_url, expected_sha)
                        elif manual:
                            messagebox.showinfo(
                                "CMSync Up to Date",
                                f"Server link synced — CMSync v{APP_VERSION} is up to date.",
                                parent=root
                            )
                    elif manual:
                        err_text = (body.get("detail") or body.get("error") or str(status)) if isinstance(body, dict) else str(status)
                        messagebox.showwarning(
                            "Update Check",
                            f"Could not check for updates.\n{err_text}",
                            parent=root
                        )
                elif isinstance(msg, tuple) and msg[0] == "update_error":
                    _, err_msg = msg
                    messagebox.showerror("Update Error", err_msg, parent=root)
        except queue.Empty:
            pass
        root.after(80, process_ui_queue)

    render_content()
    root.after(80, process_ui_queue)
    return render_content


def run_gui_and_tray(cfg, state):
    import pystray

    root = tk.Tk()
    stop = threading.Event()

    def show_window():
        ui_queue.put("show_window")

    def on_exit(_icon=None, _item=None):
        stop.set()
        try:
            icon.stop()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
        os._exit(0)

    def tooltip():
        text = state.get("status") or "Starting..."
        hours = (float(state.get("exp") or 0) - time.time()) / 3600
        sub = (" | %s" % cfg["subscriber_name"]) if cfg.get("subscriber_name") else ""
        return "%s%s | %s%s" % (APP_NAME, sub, text, (" | token %.0f h" % hours) if hours > 0 else "")

    def on_notify(message, title=APP_NAME):
        try:
            icon.notify(message, title)
        except Exception:
            pass

    def open_dash(_icon=None, _item=None):
        def _open():
            refresh_server_url(force=True)
            webbrowser.open(SERVER_URL + "/login")
        threading.Thread(target=_open, daemon=True).start()

    def sync_now(_icon=None, _item=None):
        def work():
            refresh_server_url(force=False)
            sync_once(cfg, state, force=True, notify=on_notify)
            try:
                icon.tooltip = tooltip()
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def header_label(_item):
        if cfg.get("subscriber_name"):
            return "👤 %s" % cfg["subscriber_name"]
        return state.get("status") or "CMSync"

    def toggle_startup(item, _checked):
        set_startup(not startup_enabled())
        item.checked = startup_enabled()

    def show_log(_icon=None, _item=None):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        webbrowser.open(os.path.dirname(LOG_FILE))

    menu = pystray.Menu(
        pystray.MenuItem(header_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Show CMSync", lambda _i, _m: show_window(), default=True),
        pystray.MenuItem("Open Dashboard", open_dash),
        pystray.MenuItem("Sync Now", sync_now),
        pystray.MenuItem("Link Account", lambda _i, _m: show_window()),
        pystray.MenuItem("Token File (C:)", lambda _i, _m: open_token_file(cfg)),
        pystray.MenuItem("Check for Updates", lambda _i, _m: check_for_updates(cfg, manual=True)),
        pystray.MenuItem("Run with Windows", toggle_startup, checked=lambda item: startup_enabled()),
        pystray.MenuItem("Open Log Folder", show_log),
        pystray.MenuItem("Exit", on_exit),
    )
    icon = pystray.Icon(APP_NAME, make_icon(), tooltip(), menu)

    def on_linked(sub_name):
        try:
            icon.tooltip = tooltip()
        except Exception:
            pass

    build_gui(root, cfg, on_linked_callback=on_linked)

    # Check whether we have a valid token
    has_valid_token = False
    if cfg.get("subscriber_token"):
        try:
            status, body = http("POST", SERVER_URL + "/api/subscriber/verify",
                                body={"token": cfg["subscriber_token"]}, timeout=4)
            if status == 200 and body.get("ok"):
                has_valid_token = True
                cfg["subscriber_name"] = body.get("name") or cfg.get("subscriber_name") or ""
                save_config(cfg)
        except Exception:
            if cfg.get("subscriber_token"):
                has_valid_token = True

    if has_valid_token:
        # Hide window immediately to system tray
        root.withdraw()
    else:
        # Show window so user can enter subscriber token
        show_window()

    # IPC listener for other instances launching
    def ipc_show_listener():
        kernel32 = ctypes.WinDLL("kernel32")
        hEvent = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        if not hEvent:
            return
        while not stop.is_set():
            res = kernel32.WaitForSingleObject(hEvent, 500)
            if res == 0:
                ui_queue.put("show_window")
        kernel32.CloseHandle(hEvent)

    threading.Thread(target=ipc_show_listener, daemon=True).start()

    def reporter():
        while not stop.is_set():
            time.sleep(10)
            try:
                icon.tooltip = tooltip()
            except Exception:
                break

    def startup_worker():
        try:
            refresh_server_url(force=True)
        except Exception:
            pass
        clean_expired_tokens(cfg)
        time.sleep(6)
        if not stop.is_set():
            check_for_updates(cfg, manual=False)

    threading.Thread(target=lambda: loop(cfg, state, stop, notify=on_notify), daemon=True).start()
    threading.Thread(target=reporter, daemon=True).start()
    threading.Thread(target=startup_worker, daemon=True).start()
    threading.Thread(target=icon.run, daemon=True).start()

    root.mainloop()


def say(message):
    log(message)
    if sys.stdout is not None:
        print(message)
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x40)
    except Exception:
        pass


def install(cfg):
    cfg["python"] = cfg.get("python") or default_config()["python"]
    save_config(cfg)
    startup = set_startup(True)
    shortcut = desktop_shortcut()
    say("CMSync: config=%s | startup=%s | shortcut=%s"
        % (CONFIG_FILE, "OK" if startup else "FAIL", "OK" if shortcut else "FAIL"))
    return 0 if (startup and shortcut) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--once", action="store_true", help="one cycle and print result")
    ap.add_argument("--console", action="store_true", help="run without tray icon")
    ap.add_argument("--config", action="store_true", help="open subscriber setup dialog")
    ap.add_argument("--install", action="store_true", help="Windows startup + desktop shortcut")
    ap.add_argument("--uninstall", action="store_true", help="remove Windows startup")
    ap.add_argument("--project", default=None, help="dashboard folder")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.project:
        cfg["project"] = args.project
        save_config(cfg)
    state = load_state()

    if args.install:
        return install(cfg)
    if args.uninstall:
        set_startup(False)
        say("Windows startup removed.")
        return 0

    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(cfg)

    threading.Thread(target=lambda: refresh_server_url(force=True), daemon=True).start()
    log("boot: project=%s port=%s server=%s" % (cfg["project"], cfg["port"], SERVER_URL))
    clean_expired_tokens(cfg)

    if args.once:
        status = sync_once(cfg, state, force=True)
        note = refresh_manifest(cfg, state, force=True)
        print(json.dumps({"status": status, "manifest": note,
                          "account": state.get("account")}, ensure_ascii=False))
        save_state(state)
        return 0

    if args.console:
        loop(cfg, state, threading.Event(), notify=lambda m, **k: log("NOTIFY " + m))
        return 0

    mutex = single_instance()
    if not mutex:
        # Existing instance already running, signaled to show window
        return 0

    run_gui_and_tray(cfg, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
