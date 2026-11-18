"""CMSync — أجن محلي بيوصّل جهازك باللوحة من غير أي لصق توكن.

بيعمل ثلاث حاجات في الخلفية:
  1) لو اللوحة مقفولة بيشغّلها (uvicorn على 127.0.0.1 بس).
  2) بيستنى ARC Raiders يفتح، بيقرا توكن Pioneer من ذاكرة اللعبة (قراءة فقط).
  3) بيبعته للوحة على /api/accounts/auto: نفس الحساب يتحدّث، وحساب جديد يتسجّل —
     ثم اللوحة تسحب المخزن قراءةً فورًا. مفيش أي كتابة على حساب اللعبة هنا نهائيًا.
  4) التحديث تلقائي بالكامل: كل PULL_SECONDS بنعيد إرسال التوكن المحفوظ فاللوحة
     تسحب المخزن قراءةً — من غير ما حد يدوس "حدّث دلوقتي" (الزرار فضل للطلب الفوري).
  5) بيراقب عملية اللعبة كل WATCH_SECONDS: أول ما تدوس على ملف التشغيل وتستنى
     LAUNCH_GRACE ثواني بيعمل مسح فوري للتوكن، ولحظة القفل بيسحب آخر حالة فورًا.
  6) بيلمع اللانشر قبل المحرك: "Embark Game Launcher" بيكتب التوكن في ذاكرته وهو لسه
     على شاشته (قبل ما نافذة اللعبوة تفتح)، فبنلمع هناك الأول وبنشيل اللانشر الصغير
     بدل لمعة رام المحرك الجيجابايتي اللي بتجمّد اللعبوة. أول ما اللانشر يبان بنلمع
     كل BOOT_GAP ثانية لحد ما التوكن يطلع، وبعدها للوتيرة الطويلة.
  7) مسؤول عن رقم المانيفست (مفتاح الكتابة على بوابة بايونير): لحظة فتح اللعبة وكل
     MANIFEST_SECONDS بيقول للوحة تسأل البوابة نفسها على الرقم الحي وتحفظه — فالباتش
     ما بيلقاش الموقع برقم قديم والنقل ما بيرفضش. من غير أي قراءة لذاكرة اللعبة.
  8) يحدّث نفسه: كل UPDATE_CHECK_SECONDS بيقارن بصمته ببصمة CMSync.exe اللي عند
     اللوحة، ولو اختلفوا بيبلّغ، وزرار Update في الثى بينزّلها ويسأله قبل إعادة
     التشغيل — فالنسخة الجديدة بتوصل بالظبط من غير ما حد يحمل البرنامج من الأول.

  python agent/fahmy_agent.py              # شغل في الثى
  python agent/fahmy_agent.py --once       # دورة واحدة واطبع النتيجة (للتجربة)
  python agent/fahmy_agent.py --console    # نفس الشغل من غير أيقونة
  python agent/fahmy_agent.py --install    # shortcut + تشغيل مع ويندوز
  python agent/fahmy_agent.py --update-check  # قارن نسختك بنسخة اللوحة واسكت
"""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import winreg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memtoken  # noqa: E402

# ضبط معرف التطبيق في ويندوز فور تشغيل الموديول لربط أيقونة شريط المهام بالبرنامج وليس ببايثون
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CM.CMSync.Agent.1.0")
except Exception:
    pass

SHOW_EVENT_NAME = "Local\\CMSync.ShowWindowEvent"

APP_NAME = "CMSync"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")
LOG_FILE = os.path.join(CONFIG_DIR, "agent.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_PROJECT = r"C:\Users\Administrator\Desktop\rr"
DEFAULT_PORT = 8000
RESCAN_SECONDS = 300       # اللعبة شغالة والتوكن اتلمّ → نلمع الذاكرة كل 5 دقايق
PULL_SECONDS = 120         # والتوكن المحفوظ بيتبعت كل دقيقتين عشان اللوحة تسحب المخزن قراءةً لوحدها
LAUNCHER_SCAN_SECONDS = 60  # اللانشر لوحده (اللعبة لسه ما فتحت) → لمعة كل دقيقة: رخيصة وما تلمسش اللعبوة
BOOT_GAP = 15              # شاشة اللانشر ومستنيين أول توكن → لمعة خفيفة كل 15 ثانية
BOOT_WINDOW = 300          # والمهلة دي 5 دقايق من ظهور اللانشر، بعدها نرجع للوتيرة العادية
LAUNCHER_BUDGET_MB = 768   # سقف لمعة اللانشر (الprocess بضلمةينات الميجا) — المحرك بسقفه المعتاد
SCAN_BUDGET_SECONDS = 25   # والوقت الأقصى لللمعة الخفيفة دي
LOG_KEEP = 400
DEFAULT_TOKEN_FILE = r"C:\CMSyncToken.txt"
DEFAULT_SERVER_URL = "https://arccm.pages.dev"


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


def default_config():
    python = sys.executable
    if getattr(sys, "frozen", False):
        # الثابت exe ما بيرث بايثون معاه: بنجيب بايثون الجهاز.
        python = os.environ.get("FAHMY_PYTHON") or _find_python() or python
    return {"project": DEFAULT_PROJECT, "port": DEFAULT_PORT, "python": python,
            "ensure_site": True, "idle_seconds": 30, "open_browser": False,
            "token_file": DEFAULT_TOKEN_FILE, "server_url": DEFAULT_SERVER_URL,
            "subscriber_token": "", "subscriber_name": ""}


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
    url = (cfg.get("server_url") or "").strip().rstrip("/")
    if cfg.get("subscriber_token") or (url and not url.startswith("http://127.0.0.1")):
        cfg["base_url"] = url or DEFAULT_SERVER_URL
    else:
        cfg["base_url"] = "http://127.0.0.1:%d" % int(cfg.get("port") or DEFAULT_PORT)
    return cfg


def save_config(cfg):
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
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
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


# ---------------------------------------------------------------- اللوحة
def site_status(cfg):
    return http("GET", cfg["base_url"] + "/api/status", timeout=4)


def agent_key(cfg):
    """مفتاح الجهاز: لو المشترك معاه subscriber_token بنستخدمه، غير كده المفتاح المشترك."""
    if cfg.get("subscriber_token"):
        return cfg["subscriber_token"]
    status, body = http("GET", cfg["base_url"] + "/api/agent/handshake", timeout=6)
    if status == 200 and body.get("key"):
        cfg["project"] = body.get("project") or cfg["project"]
        return body["key"]
    path = os.path.join(cfg.get("project") or "", "data", "agent_secret.txt")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def start_site(cfg):
    """تشغيل اللوحة منفصلة عن الثى — نفس أمر uvicorn بتاع السكربتات."""
    project = cfg.get("project") or ""
    python = cfg.get("python") or ""
    if not (os.path.isdir(project) and python and os.path.exists(python)):
        log("Project or python not found (%s / %s)" % (project, python))
        return False
    creation = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    env = dict(os.environ, PYTHONPATH=project)
    out = open(os.path.join(CONFIG_DIR, "site.log"), "a", encoding="utf-8")
    subprocess.Popen([python, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
                      "--port", str(cfg["port"]), "--log-level", "warning"],
                     cwd=project, stdout=out, stderr=out, env=env, creationflags=creation)
    log("Starting the dashboard…")
    deadline = time.time() + 180
    while time.time() < deadline:
        status, _ = site_status(cfg)
        if status == 200:
            log("Dashboard is up.")
            return True
        time.sleep(3)
    log("The dashboard did not come up after 180 seconds.")
    return False


def ensure_site(cfg):
    # لو وضع المشترك (عبر السيرفر الخارجي أو معاه توكن)، مش بنشغل uvicorn محلي
    if cfg.get("subscriber_token") or not cfg.get("base_url", "").startswith("http://127.0.0.1"):
        status, _ = site_status(cfg)
        return status == 200
    status, _ = site_status(cfg)
    if status == 200:
        return True
    if not cfg.get("ensure_site", True):
        return False
    return start_site(cfg)


def push(cfg, key, token):
    headers = {}
    if cfg.get("subscriber_token"):
        headers["X-Subscriber-Token"] = cfg["subscriber_token"]
    else:
        headers["X-Fahmy-Agent"] = key
    status, body = http("POST", cfg["base_url"] + "/api/accounts/auto",
                        body={"token": token}, headers=headers, timeout=120)
    return status, body


def panel_names(cfg, key):
    """أسماء الحسابات اللي اللوحة تعرفها دلوقتي (المفتاح الداخلي + الاسم الظاهر)."""
    headers = {}
    if cfg.get("subscriber_token"):
        headers["X-Subscriber-Token"] = cfg["subscriber_token"]
    else:
        headers["X-Fahmy-Agent"] = key
    status, body = http("GET", cfg["base_url"] + "/api/accounts", headers=headers)
    if status != 200:
        return None
    out = set()
    for rec in (body or {}).get("accounts") or []:
        out.update(v for v in (rec.get("name"), rec.get("display_name")) if v)
    return out


# ---------------------------------------------------------------- الدورة
def deliver(cfg, key, state, token, jti="", exp=0.0, notify=None):
    """يبعت توكن للوحة ويسجّل النتيجة في الحالة. بيرجع رسالة، أو None لو اترفض."""
    pushed = state.setdefault("pushed", {})
    status, body = push(cfg, key, token)
    if status == 400 or status == 403:
        state["last_error"] = body.get("detail") or str(status)
        log("The dashboard rejected it (%s): %s" % (status, state["last_error"]))
        return None
    if status == 200 and not (body.get("pulled") or {}).get("ok") and not body.get("created"):
        state["last_error"] = (body.get("pulled") or {}).get("error") or "gateway refused"
        log("The gateway rejected the token (%s)" % state["last_error"])
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
    """الاسم الظاهر في اللعبة — هو اللي بيتكتب في ملف التوكن، مش المفتاح الداخلي."""
    acc = (body or {}).get("account") or {}
    return acc.get("display_name") or acc.get("name") or "?"


def write_token_file(cfg, name, token):
    """السطر الأول اسم الحساب والسطر التاني التوكن — بيتكتب من جديد كل مرة."""
    path = cfg.get("token_file") or DEFAULT_TOKEN_FILE
    if not name or name == "?" or not token:
        return False
    want = "%s\n%s\n" % (name, token)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            if fh.read() == want:
                return True
    except OSError:
        pass
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(want)
    except OSError as exc:
        log("Token file %s is locked: %s" % (path, str(exc)[:90]))
        return False
    if not cfg.get("_token_file_warned"):
        cfg["_token_file_warned"] = True
        log("The token is being written to %s" % path)
    return True


def open_token_file(cfg):
    path = cfg.get("token_file") or DEFAULT_TOKEN_FILE
    if os.path.exists(path):
        os.startfile(path)
    else:
        webbrowser.open(os.path.splitdrive(path)[0] + os.sep)


def repull(cfg, state, notify=None, now=False):
    """يعيد إرسال التوكن المحفوظ لنفس الحساب — واللوحة تسحب المخزن قراءةً مع كل استلام.

    ده اللي بيخلي التحديث تلقائي من غير زرار "حدّث دلوقتي": قراءة فقط، مفيش كتابة.
    بيرجّع None لو لسه بدري على الدورة أو مفيش توكن محفوظ نتبعت بيه.
    """
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
    """وتيرة لمعة الذاكرة: لمعة اللانشر رخيصة فلنكررها، ولمعة المحرك غالية فلنقلّها.

    شاشة اللانشر لسه ما كتبتش توكن = كل كام ثانية، اللانشر بس = دقيقة، والمحرك شغال
    والتوكن اتلمّ = 5 دقايق — عشان المسح جوا اللعبوة هو اللي بيجمّدها.
    """
    if state.get("boot_poll"):
        return float(cfg.get("boot_gap") or BOOT_GAP)
    if not launcher:
        return float(cfg.get("rescan_seconds") or RESCAN_SECONDS)
    return float(cfg.get("launcher_scan_seconds") or LAUNCHER_SCAN_SECONDS)


def harvest(cfg, launcher, engine, broken):
    """أول عملية تطلّع توكن كامل تكفي — واللانشر بيمشي الأول.

    اللانشر بيكتب التوكن وهو لسه على شاشته، فبنلمعه بميزانية صغيرة (process بضلمةينات
    الميجا) وبنخلص قبل ما اللعبوة تفتح. المحرك ما بنلمعوش إلا لو اللانشر ساكت، وبالسقف
    الكامل المعتاد — التقطير اللي قبل كده كان بيقطع الدورة على توكن موجود فعلاً.
    """
    for pid in launcher:
        try:
            got = memtoken.scan(pid, partial=broken,
                                max_bytes=LAUNCHER_BUDGET_MB * (1 << 20),
                                max_seconds=cfg.get("scan_seconds") or SCAN_BUDGET_SECONDS)
        except OSError as exc:
            log("Scan of pid %s failed: %s" % (pid, exc))
            continue
        if got:
            return got, pid
    for pid in engine:
        try:
            got = memtoken.scan(pid, partial=broken)
        except OSError as exc:
            log("Scan of pid %s failed: %s" % (pid, exc))
            continue
        if got:
            return got, pid
    return [], 0


def sync_once(cfg, state, force=False, notify=None):
    """دورة واحدة: لو اللانشر أو اللعبة مفتوحة اقرأ الذاكرة وابعث التوكن الجديد."""
    status, site = site_status(cfg)
    if status != 200:
        state["last_error"] = "Dashboard is down"
        return "Dashboard is down"
    launcher, engine = memtoken.split_pids()
    pids = launcher + engine
    switched = "game" in state and bool(state.get("game")) != bool(pids)
    if not pids:
        state["game"] = False
        state["boot_poll"] = False
        if switched:
            # اللعبة قفلت دلوقتي: آخر سحب بعد الرايد بالتوكن المحفوظ من غير انتظار الدورة
            out = repull(cfg, state, notify, now=True)
            if out:
                return out
        last = time.strftime("%H:%M", time.localtime(state.get("last_push") or 0))
        return "Game closed | last update %s" % last if state.get("last_push") else "Game closed"
    if switched or not state.get("game") or not state.get("game_seen"):
        # اللانشر بان دلوقتي (أو الأجنقل نفسه وهو شغال): التوكن اللي قبل كده ملك جلسة تانية
        state["game_seen"] = time.time()
        state["has_token"] = False
    state["game"] = True
    # الاستعجال بس وهو واقف قدام اللانشر: لمعة المحرك الغالية ما تتكررش كل كام ثانية
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
        # لسه بدري على لمعة تانية: نعيش على التوكن المحفوظ بدل ما نلمع نفس الجيجابايت
        if not (held and exp > time.time()):
            return "No Pioneer token in memory yet — scanning again in %d s" \
                % int(max(1, gap - since_scan))
        known = panel_names(cfg, key)
        if known is None or state.get("account") in known:
            return repull(cfg, state, notify) or "Token is fine (%.0f h)" % ((exp - time.time()) / 3600)
        # الحساب اتمسح من اللوحة: نرجّعه من النسخة المحفوظة من غير ما نلمع الذاكرة تاني
        log("Account %s is not in the dashboard — re-registering it from the saved copy" % state.get("account"))
        out = deliver(cfg, key, state, held, notify=notify)
        if out:
            return out
        state["last_scan"] = 0
    broken = []
    tokens, scanned = harvest(cfg, launcher, engine, broken)
    state["last_scan"] = time.time()
    state["pid"] = scanned or pids[0]
    if not tokens:
        state["last_error"] = ("Truncated-signature token copies in memory (%d)" % len(broken)) if broken \
            else "No token in memory"
        if broken:
            return "Found incomplete token copies in memory — waiting for a full one"
        return "The launcher is running — waiting for the token to appear (%d s)" % int(max(1, gap - since_scan))
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
    return repull(cfg, state, notify, now=True) or "All tokens in memory were already sent"


WATCH_SECONDS = 3       # استطلاع خفيف على أسماء العمليات — ثواني معدودة لكل لقطة
LAUNCH_GRACE = 5        # مهلة بعد ظهور عملية اللعبة عشان تكتب التوكن في الرام
MANIFEST_SECONDS = 600  # ورقم المانيفست بيتسأل عليه كل 10 دقايق (الباتش ينزل واللعبة مقفولة)


def refresh_manifest(cfg, state, force=False, notify=None):
    """يخلّي اللوحة تسأل البوابة على رقم المانيفست الحي وتحفظه — صفر قراءة ذاكرة.

    الرقم ده هو مفتاح الكتابة: أول ما اللعبة تعمل ابديت بيقى قديم فالنقل يرفض 412
    والقراءة تفضل شغالة. بنسأله لحظة فتح اللعبة (force) وعشان الباتش ممكن ينزل
    والحساب مقفول بنسأله دورياً كمان. اللوحة بتحفظ في data/pioneer_manifest.json
    وبتقراه لكل طلب، فمفيش إعادة تشغيل ولا حاجة تدوس عليها.
    """
    now = time.time()
    if not force and now - float(state.get("manifest_at") or 0) < MANIFEST_SECONDS:
        return ""
    state["manifest_at"] = now
    key = agent_key(cfg)
    if not key:
        return ""
    headers = {"X-Subscriber-Token": cfg["subscriber_token"]} if cfg.get("subscriber_token") else {"X-Fahmy-Agent": key}
    status, body = http("POST", cfg["base_url"] + "/api/agent/manifest", body={},
                        headers=headers, timeout=90)
    if status != 200:
        log("Manifest check failed (%s): %s" % (status, str(body)[:140]))
        return ""
    if not body.get("changed"):
        return "Manifest %s" % body.get("manifest_id")
    log("Game patch: the gateway moved to manifest %s (was %s) — the site saved it"
        % (body.get("manifest_id"), body.get("old")))
    state["manifest_changed_at"] = now
    save_state(state)
    if notify:
        notify("The game patched — writes re-opened by themselves.")
    return "Manifest updated to %s" % body.get("manifest_id")


UPDATE_CHECK_SECONDS = 900   # ونسخة الأجن نفسها بتتفحص كل 15 دقيقة
UPDATE_DIR = os.path.join(CONFIG_DIR, "update")
DETACHED = 0x00000008 | 0x00000200
STILL_ACTIVE = 259


def exe_path():
    """ملف الـ exe الجاري دلوقتي — فاضي لو الأجن اتشغل من بايثون (مفيش ملف يتبدّل)."""
    return sys.executable if getattr(sys, "frozen", False) else ""


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def file_release(path):
    """وصف ملف على القرص، والبصمة متخزنة بحجمه وتعديله — مجاش غيرهم اتحسبت من جديد."""
    st = os.stat(path)
    key = (path, st.st_size, int(st.st_mtime))
    digest = _sha_cache.get(key) or sha256_of(path)
    _sha_cache.clear()
    _sha_cache[key] = digest
    return {"size": st.st_size, "built_at": int(st.st_mtime), "sha256": digest}


_sha_cache = {}


def release_info(cfg):
    """النسخة المتاحة على السيرفر — نفس الملف اللي في صفحة الإعدادات بيتحمّل."""
    key = agent_key(cfg)
    if not key:
        return {}
    headers = {"X-Subscriber-Token": cfg["subscriber_token"]} if cfg.get("subscriber_token") else {"X-Fahmy-Agent": key}
    status, body = http("GET", cfg["base_url"] + "/api/agent/release",
                        headers=headers, timeout=60)
    return body if status == 200 and body.get("present") else {}


def check_update(cfg, state, force=False, notify=None):
    """يقارن بصمته ببصمة نسخة السيرفر: مختلفة = في ابديت، والنفسية = مفيش.

    بنعتمد على البصمة مش على رقم إصدار لأن مفيش رقم يتكتب ويتنسى عند كل بيلد —
    وأي ملف مختلف فعلاً على السيرفر بيتكشف. البلّغ مرة واحدة لكل نسخة جديدة.
    """
    mine = exe_path()
    if not mine:
        return ""
    now = time.time()
    if not force and now - float(state.get("update_checked_at") or 0) < UPDATE_CHECK_SECONDS:
        return ""
    state["update_checked_at"] = now
    remote = release_info(cfg)
    if not remote:
        return ""
    try:
        local = file_release(mine)
    except OSError as exc:
        log("Update check could not read itself: %s" % exc)
        return ""
    if local["sha256"] == remote.get("sha256"):
        state["update_available"] = False
        return "Up to date"
    state["update_available"] = True
    state["update_remote"] = {"built_at": remote.get("built_at_text"),
                              "size": remote.get("size"), "sha256": remote.get("sha256")}
    if state.get("update_notified_sha") != remote.get("sha256"):
        state["update_notified_sha"] = remote.get("sha256")
        save_state(state)
        if notify:
            notify("A new CMSync build is ready — right-click the icon and press Update.")
        log("New build on the server: %s (%s MB) — this one is %s"
            % (remote.get("built_at_text"), round((remote.get("size") or 0) / 1048576, 1),
               local["sha256"][:8]))
        return "New build %s available" % remote.get("built_at_text")
    return "New build %s waiting" % remote.get("built_at_text")


def download_update(cfg, state, notify=None):
    """ينزّل نسخة السيرفر لملف مؤقت ويتأكد إنها هي المطلوبة قبل ما يسلّمها."""
    remote = release_info(cfg)
    if not remote:
        return "", "The dashboard has no CMSync build to offer."
    target = os.path.join(UPDATE_DIR, "CMSync.new.exe")
    try:
        if os.path.exists(target) and file_release(target)["sha256"] == remote["sha256"]:
            return target, "Already downloaded."
        key = agent_key(cfg)
        if not key:
            return "", "The dashboard did not give an agent key."
        if notify:
            notify("Downloading the new CMSync build…")
        os.makedirs(UPDATE_DIR, exist_ok=True)
        part = target + ".part"
        headers = {"X-Subscriber-Token": cfg["subscriber_token"]} if cfg.get("subscriber_token") else {"X-Fahmy-Agent": key}
        req = urllib.request.Request(cfg["base_url"] + "/api/agent/release/file",
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=900) as resp, open(part, "wb") as fh:
            shutil.copyfileobj(resp, fh, 1 << 20)
        if file_release(part)["sha256"] != remote["sha256"]:
            os.remove(part)
            return "", "The download came out corrupted — press Update again."
        os.replace(part, target)
    except Exception as exc:  # noqa: BLE001 — الزرار ما يقفلش الأيقونة
        log("Update download failed: %s" % exc)
        return "", "Download failed: %s" % str(exc)[:120]
    state["update_downloaded_sha"] = remote["sha256"]
    save_state(state)
    size = round((remote.get("size") or 0) / 1048576, 1)
    log("Downloaded build %s (%s MB) — ready to swap" % (remote.get("built_at_text"), size))
    return target, "Downloaded %s MB." % size


def process_alive(pid):
    try:
        kernel32 = ctypes.WinDLL("kernel32")
    except OSError:
        return False
    handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def apply_update(wait_pid, source, target, launch=True):
    """تبدّل نفسها: النسخة الجديدة بتشتغل من ملف مؤقت، تستنى القديمة تقفل، تنسخ فوقها، وتشغلها.

    الـ exe مش بيتكتب وهو شغال على ويندوز، فبنستنى الـ PID يطلع، وبعدها بنعيد المحاولة
    شوية ثواني لأن الملف بيقفل بعد لحظات من خروج العملية — مش بنفشل من أول مرة.
    """
    deadline = time.time() + 120
    while wait_pid and process_alive(wait_pid) and time.time() < deadline:
        time.sleep(0.5)
    staged = target + ".newbuild"
    for _ in range(60):
        try:
            shutil.copyfile(source, staged)
            os.replace(staged, target)  # الذرة بتتحول نسخة كاملة مرة واحدة، بنصف ملف ما بيسيبش حد
            break
        except OSError:
            time.sleep(0.5)
    else:
        try:
            os.remove(staged)
        except OSError:
            pass
        log("Update failed: %s is still locked — close CMSync and copy it by hand" % target)
        return 3
    log("Update applied: %s is now the running build" % target)
    if launch:
        subprocess.Popen([target], cwd=CONFIG_DIR, creationflags=DETACHED)
    return 0


def ask_yes_no(message):
    """الـ exe بيتبني من غير نافذة — فالسؤال يظهر كصندوق رسالة."""
    if sys.stdout is not None:
        try:
            return input(message + " [y/N] ").strip().lower() in ("y", "yes")
        except (EOFError, OSError):
            return False
    try:
        return ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x4 | 0x20) == 6
    except Exception:
        return False


def run_update(cfg, state, notify=None, restart=None):
    """الزرار: نزّل، اسأل، وبعدين سلّم للنسخة الجديدة تبدّل نفسها وتقفل دي."""
    if not exe_path():
        say("This CMSync is running from python — there is no exe file to replace.")
        return ""
    source, message = download_update(cfg, state, notify)
    if not source:
        say("Update: " + message)
        return message
    remote = state.get("update_remote") or {}
    note = "%s (%s MB)" % (remote.get("built_at") or "new build",
                           round((remote.get("size") or 0) / 1048576, 1))
    if not ask_yes_no("CMSync %s is downloaded.\n\n"
                      "Restart it now to finish the update? The dashboard keeps running." % note):
        if notify:
            notify("Downloaded — press Update again whenever you want to restart.")
        return "Downloaded, restart pending."
    spawn_apply(cfg, source)
    if restart:
        restart()
    return "Restarting with the new build."


def spawn_apply(cfg, source):
    """يشغّل النسخة الجديدة بوضع التبديل — فلو النسخة القديمة هي اللي ما تعرفش تتحدّث،
    الجديدة بتعرف: هي اللي بتنسخ على نفسها."""
    subprocess.Popen([source, "--apply-update", str(os.getpid()), exe_path(), source],
                     cwd=CONFIG_DIR, creationflags=DETACHED)


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
    """استراحة الدورة العادية، بتتقطع فورًا لحظة تغيّر حالة اللعبة (فتحت/قفلت).

    وشاشة اللانشر مستنية التوكن = استراحة قصيرة عشان نحاول تاني بسرعة من غير انتظار دورة.
    """
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
                log("The game opened — wait %d seconds and scan" % LAUNCH_GRACE)
                _sleep(LAUNCH_GRACE, stop)
            else:
                log("The game closed — refresh immediately")
            return


def loop(cfg, state, stop, notify=None, interval=None):
    was_game = bool(state.get("game"))
    first_cycle = True
    while not stop.is_set():
        try:
            ensure_site(cfg)
            text = sync_once(cfg, state, notify=notify)
            # أول ما اللعبة تفتح نسأل على رقم المانيفست فورًا: الباتش بيكون نزل
            # خلاص، وإلا أول نقل بعد الدخول بيرفض 412 لحد ما الدورة العادية تجي.
            opened = bool(state.get("game")) and not was_game
            was_game = bool(state.get("game"))
            note = refresh_manifest(cfg, state, force=opened, notify=notify)
            if note and (opened or "updated" in note):
                text = "%s | %s" % (text, note)
            # وأول دورة بعد التشغيل نفحص نسختنا على طول: اللوحة ممكن تكون اتحدّثت وهو مقفول
            up = check_update(cfg, state, force=first_cycle, notify=notify)
            if up and "available" in up:
                text = "%s | %s" % (text, up)
            first_cycle = False
        except Exception as exc:  # الأيقونة ما تموتش بسبب استثناء
            text = "Error: %s" % exc
            log(text)
        state["status"] = text
        state["report_at"] = time.time()
        save_state(state)
        wait_next_cycle(cfg, state, stop, interval)


# ---------------------------------------------------------------- ثى + تثبيت
def make_icon():
    """علامة CM: مربّع أوبسيدي بحلّة بنفسجى/فوشيا و"CM" أبيض في النص، ونقطة كهرمانية جوّه."""
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
    exe = getattr(sys, "frozen", False) and sys.executable or '"%s" "%s"' % (
        sys.executable, os.path.abspath(__file__))
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
        log("Could not edit Windows startup: %s" % exc)
        return False


def desktop_shortcut():
    """اختصار على سطح المكتب عن طريق PowerShell — من غير أي مكتبة خارجية."""
    if getattr(sys, "frozen", False):
        target, args, workdir = sys.executable, "", CONFIG_DIR
    else:
        here = os.path.abspath(__file__)
        target, args, workdir = "python.exe", '"%s"' % here, os.path.dirname(here)
    link = os.path.join(os.path.expanduser("~"), "Desktop", "%s.lnk" % APP_NAME)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';"
          "$s.Arguments='%s';$s.WorkingDirectory='%s';$s.Save()"
          % tuple(str(x).replace("'", "''") for x in (link, target, args, workdir)))
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30)
        return os.path.exists(link)
    except Exception as exc:
        log("The shortcut failed: %s" % exc)
        return False


def single_instance():
    """مفيش نسخة تانية من البرنامج — وإذا كانت نسخة سابقة مفتوحة يتم إظهار نافذتها فوراً للمستخدم."""
    kernel32 = ctypes.WinDLL("kernel32")
    handle = kernel32.CreateMutexW(None, False, "Local\\CMSync.Tray")
    if not handle:
        return None
    # ERROR_ALREADY_EXISTS = 183: في نسخة تانية ماسكة القفل خلاص
    if kernel32.GetLastError() == 183:
        try:
            hEvent = kernel32.OpenEventW(0x0002, False, SHOW_EVENT_NAME)
            if hEvent:
                kernel32.SetEvent(hEvent)
                kernel32.CloseHandle(hEvent)
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "CMSync — ربط الحساب بالسيرفر")
            if hwnd:
                SW_RESTORE = 9
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return None
    return handle


def get_clipboard_text():
    """قراءة نص الحافظة مباشرة عبر ويندوز لضمان اللصق حتى مع الكيبورد العربي."""
    try:
        import ctypes
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        if not u32.OpenClipboard(0):
            return ""
        try:
            CF_UNICODETEXT = 13
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ""
            ptr = k32.GlobalLock(h)
            if not ptr:
                return ""
            try:
                return ctypes.c_wchar_p(ptr).value or ""
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        return ""


def find_app_icon():
    """البحث عن ملف الأيقونة في موارد الحزمة أو المسار المحلي."""
    candidates = [
        getattr(sys, "_MEIPASS", ""),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent"),
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
        r"C:\Users\Administrator\Desktop\uu\agent"
    ]
    for c in candidates:
        if c:
            p = os.path.join(c, "cmsync.ico")
            if os.path.isfile(p):
                return p
    return ""


def apply_dark_theme_to_window(window):
    """تفعيل الثيم الداكن لشريط العنوان في ويندوز (Windows Dark Mode Title Bar)."""
    try:
        window.update_idletasks()
        import ctypes
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
        color = ctypes.c_int(0x00170F0D)  # #0d0f17 in BGR
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(color), ctypes.sizeof(color)
        )
    except Exception:
        pass


def apply_app_icon(window):
    """تطبيق أيقونة التطبيق على النافذة وشريط المهام عبر Win32 و Tkinter لمنع ظهور ريشة بايثون."""
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
        import ctypes
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
        hIcon = ctypes.windll.user32.LoadImageW(None, ico_path, 1, 0, 0, 0x00000010)
        if hIcon:
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hIcon)  # WM_SETICON, ICON_SMALL
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hIcon)  # WM_SETICON, ICON_BIG
            ctypes.windll.user32.SendMessageW(window.winfo_id(), 0x0080, 0, hIcon)
            ctypes.windll.user32.SendMessageW(window.winfo_id(), 0x0080, 1, hIcon)
    except Exception:
        pass


def prompt_subscriber_config(cfg, force=False):
    """نافذة إعداد المشترك: إدخال التوكن ورابط السيرفر بتصميم داكن عصري وأيقونة مخصصة."""
    if not force and cfg.get("subscriber_token"):
        url = (cfg.get("server_url") or DEFAULT_SERVER_URL).rstrip("/")
        status, body = http("POST", url + "/api/subscriber/verify",
                            body={"token": cfg["subscriber_token"]}, timeout=8)
        if status == 200 and body.get("ok"):
            cfg["subscriber_name"] = body.get("name") or cfg.get("subscriber_name") or ""
            save_config(cfg)
            return True
        elif status == 401:
            log("Stored subscriber token is invalid or expired. Prompting for new token...")
        else:
            return True

    # ضبط معرف التطبيق في ويندوز لربط أيقونة شريط المهام بالبرنامج وليس ببايثون
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CM.CMSync.Agent.1.0")
    except Exception:
        pass

    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except ImportError:
        log("Tkinter / PIL not available")
        return False

    root = tk.Tk()
    root.title("CMSync — ربط الحساب بالسيرفر")
    w, h = 530, 440
    root.geometry(f"{w}x{h}")
    root.minsize(w, h)
    root.maxsize(w, h)
    root.configure(bg="#0d0f17")

    # إغلاق النافذة والنزول لشريط المهام (Tray Icon) بدلاً من إنهاء البرنامج
    def on_window_close():
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_window_close)

    # معالجة استعادة النافذة عند الضغط عليها في شريط المهام
    def on_taskbar_map(event):
        if event.widget == root:
            root.deiconify()
            root.lift()

    root.bind("<Map>", on_taskbar_map)

    # توسيط النافذة في منتصف الشاشة
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() // 2) - (w // 2))
    y = max(0, (root.winfo_screenheight() // 2) - (h // 2))
    root.geometry(f"{w}x{h}+{x}+{y}")

    # تفعيل شريط العنوان الداكن العصري وتعيين الأيقونة المخصصة
    apply_dark_theme_to_window(root)
    apply_app_icon(root)

    # كارت الهيدر العصري
    header_card = tk.Frame(root, bg="#161824", highlightthickness=1, highlightbackground="#252a3d", padx=16, pady=12)
    header_card.pack(fill="x", padx=20, pady=(16, 12))

    head_top = tk.Frame(header_card, bg="#161824")
    head_top.pack(fill="x")

    badge_lbl = tk.Label(head_top, text="⚡ CMSYNC CLIENT", font=("Segoe UI", 8, "bold"),
                         fg="#c084fc", bg="#261b3d", padx=8, pady=2)
    badge_lbl.pack(side="left")

    title_lbl = tk.Label(header_card, text="ربط حساب اللعبة بسيرفر المخزن", font=("Segoe UI", 13, "bold"),
                         fg="#f8fafc", bg="#161824", anchor="w")
    title_lbl.pack(fill="x", pady=(6, 2))

    desc_lbl = tk.Label(header_card, text="اربط جهازك باللوحة السحابية للمزامنة التلقائية الفورية لمخزنك وعتادك.",
                        font=("Segoe UI", 9), fg="#94a3b8", bg="#161824", justify="right", anchor="w")
    desc_lbl.pack(fill="x")

    # الفورم الداخلي
    form_frame = tk.Frame(root, bg="#0d0f17")
    form_frame.pack(padx=24, fill="x")

    # 1. رابط السيرفر
    url_hdr_row = tk.Frame(form_frame, bg="#0d0f17")
    url_hdr_row.pack(fill="x", pady=(4, 3))
    url_lbl = tk.Label(url_hdr_row, text="🌐 رابط السيرفر (Server URL):", font=("Segoe UI", 9, "bold"),
                       fg="#e2e8f0", bg="#0d0f17")
    url_lbl.pack(side="left")

    url_var = tk.StringVar(value=cfg.get("server_url") or DEFAULT_SERVER_URL)
    url_entry = tk.Entry(form_frame, textvariable=url_var, font=("Consolas", 9), bg="#161824", fg="#f8fafc",
                         insertbackground="#ffffff", relief="flat", highlightthickness=1,
                         highlightbackground="#2b3147", highlightcolor="#a855f7")
    url_entry.pack(fill="x", ipady=6, pady=(0, 2))

    # الرابط التفاعلي لفتح الموقع في المتصفح بنقرة واحدة
    def open_server_in_browser(e=None):
        srv_url = url_var.get().strip()
        if srv_url:
            import webbrowser
            webbrowser.open(srv_url)

    link_row = tk.Frame(form_frame, bg="#0d0f17")
    link_row.pack(fill="x", pady=(2, 10))
    link_lbl = tk.Label(link_row, text="🔗 اضغط هنا لفتح رابط الموقع في المتصفح تلقائياً ↗",
                        font=("Segoe UI", 8, "underline"), fg="#38bdf8", bg="#0d0f17", cursor="hand2")
    link_lbl.pack(side="left")
    link_lbl.bind("<Button-1>", open_server_in_browser)
    link_lbl.bind("<Enter>", lambda e: link_lbl.config(fg="#7dd3fc"))
    link_lbl.bind("<Leave>", lambda e: link_lbl.config(fg="#38bdf8"))

    # 2. توكن المشترك
    tok_lbl = tk.Label(form_frame, text="🔑 توكن المشترك (Subscriber Token):", font=("Segoe UI", 9, "bold"),
                       fg="#e2e8f0", bg="#0d0f17", anchor="w")
    tok_lbl.pack(fill="x", pady=(2, 3))

    tok_row = tk.Frame(form_frame, bg="#0d0f17")
    tok_row.pack(fill="x", pady=(0, 8))

    tok_var = tk.StringVar(value=cfg.get("subscriber_token") or "")
    tok_entry = tk.Entry(tok_row, textvariable=tok_var, font=("Consolas", 9), bg="#161824", fg="#f8fafc",
                         insertbackground="#ffffff", relief="flat", highlightthickness=1,
                         highlightbackground="#2b3147", highlightcolor="#a855f7")
    tok_entry.pack(side="left", fill="x", expand=True, ipady=6)

    def do_paste_token():
        txt = get_clipboard_text().strip()
        if txt:
            tok_var.set(txt)
            status_lbl.config(text="✔ تم لصق التوكن بنجاح", fg="#22c55e")
        else:
            status_lbl.config(text="⚠️ الحافظة فارغة — انسخ التوكن أولاً ثم اضغط لصق", fg="#f59e0b")

    paste_btn = tk.Button(tok_row, text="📋 لصق (Paste)", font=("Segoe UI", 8, "bold"),
                          bg="#252a3d", fg="#f8fafc", activebackground="#a855f7", activeforeground="#ffffff",
                          relief="flat", cursor="hand2", padx=12, command=do_paste_token)
    paste_btn.pack(side="right", padx=(8, 0), ipady=4)

    def attach_context_menu(entry, str_var=None):
        m = tk.Menu(root, tearoff=0, bg="#161824", fg="#ffffff", activebackground="#a855f7")
        def paste():
            txt = get_clipboard_text().strip()
            if txt:
                if str_var is not None:
                    str_var.set(txt)
                else:
                    entry.delete(0, tk.END)
                    entry.insert(0, txt)
                status_lbl.config(text="✔ تم اللصق", fg="#22c55e")
        m.add_command(label="📋 لصق (Paste)", command=paste)
        m.add_command(label="📄 نسخ (Copy)", command=lambda: root.clipboard_append(entry.get()))
        m.add_command(label="🔘 تحديد الكل (Select All)", command=lambda: entry.select_range(0, tk.END))
        def show_popup(e):
            entry.focus_set()
            m.tk_popup(e.x_root, e.y_root)
        entry.bind("<Button-3>", show_popup)

        def on_key_paste(e):
            paste()
            return "break"
        entry.bind("<Control-v>", on_key_paste)
        entry.bind("<Control-V>", on_key_paste)
        entry.bind("<Shift-Insert>", on_key_paste)

    attach_context_menu(url_entry, url_var)
    attach_context_menu(tok_entry, tok_var)

    # لو الحافظة فيها التوكن مسبقاً، ضعه تلقائياً
    clip = get_clipboard_text().strip()
    if not tok_var.get() and len(clip) >= 20 and not clip.startswith("http"):
        tok_var.set(clip)

    status_lbl = tk.Label(root, text="", font=("Segoe UI", 9, "bold"), fg="#ef4444", bg="#0d0f17")
    status_lbl.pack(pady=(2, 8))

    success = [False]

    def on_connect():
        srv = url_var.get().strip().rstrip("/")
        tok = tok_var.get().strip()
        if not srv:
            status_lbl.config(text="يرجى إدخال رابط السيرفر", fg="#ef4444")
            return
        if not tok:
            status_lbl.config(text="يرجى إدخال توكن المشترك", fg="#ef4444")
            return

        status_lbl.config(text="جاري التحقق من التوكن...", fg="#a855f7")
        root.update()

        status, body = http("POST", srv + "/api/subscriber/verify", body={"token": tok}, timeout=10)
        if status == 200 and body.get("ok"):
            sub_name = body.get("name") or "المشترك"
            status_lbl.config(text=f"✔ تم الربط بنجاح! مرحباً بك {sub_name}", fg="#22c55e")
            cfg["server_url"] = srv
            cfg["subscriber_token"] = tok
            cfg["subscriber_name"] = sub_name
            cfg["base_url"] = srv
            save_config(cfg)
            success[0] = True
            root.after(1000, root.destroy)
        elif status == 401:
            status_lbl.config(text="❌ التوكن غير صحيح أو منتهي الصلاحية", fg="#ef4444")
        else:
            err = body.get("error") or str(status)
            status_lbl.config(text=f"❌ تعذر الاتصال بالسيرفر ({err})", fg="#ef4444")

    btn = tk.Button(root, text="🚀 حفظ وربط الحساب الآن (Connect & Start)", font=("Segoe UI", 10, "bold"),
                    bg="#8b5cf6", fg="#ffffff", activebackground="#7c3aed", activeforeground="#ffffff",
                    relief="flat", cursor="hand2", command=on_connect)
    btn.pack(ipady=7, ipadx=24)

    tok_entry.bind("<Return>", lambda e: on_connect())
    url_entry.bind("<Return>", lambda e: on_connect())

    # إعطاء الفوكس التام للنافذة وحقل التوكن
    root.lift()
    root.attributes('-topmost', True)
    root.after(150, lambda: root.attributes('-topmost', False))
    root.focus_force()
    tok_entry.focus_set()

    root.mainloop()
    return success[0]


def run_tray(cfg, state, show_ui_on_start=False):
    import pystray
    stop = threading.Event()

    def tooltip():
        text = state.get("status") or "Starting…"
        hours = (float(state.get("exp") or 0) - time.time()) / 3600
        sub = (" | %s" % cfg["subscriber_name"]) if cfg.get("subscriber_name") else ""
        return "%s%s | %s%s" % (APP_NAME, sub, text, ("  | token %.0f h" % hours) if hours > 0 else "")

    def on_notify(message, title=APP_NAME):
        try:
            icon.notify(message, title)
        except Exception:
            pass

    def open_dash(_icon=None, _item=None):
        webbrowser.open(cfg["base_url"])

    def sync_now(_icon=None, _item=None):
        def work():
            sync_once(cfg, state, force=True, notify=on_notify)
            try:
                icon.tooltip = tooltip()
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def change_config(_icon=None, _item=None):
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "CMSync — ربط الحساب بالسيرفر")
            if hwnd:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
                return
        except Exception:
            pass
        threading.Thread(target=lambda: prompt_subscriber_config(cfg, force=True), daemon=True).start()

    def ipc_show_listener():
        kernel32 = ctypes.WinDLL("kernel32")
        hEvent = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        if not hEvent:
            return
        while not stop.is_set():
            res = kernel32.WaitForSingleObject(hEvent, 500)
            if res == 0:
                change_config()
        kernel32.CloseHandle(hEvent)

    threading.Thread(target=ipc_show_listener, daemon=True).start()

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

    def restart():
        stop.set()
        try:
            icon.stop()
        except Exception:
            pass
        os._exit(0)

    def update_now(_icon=None, _item=None):
        def work():
            text = run_update(cfg, state, on_notify, restart)
            if text:
                log("Update: " + text)
                try:
                    icon.tooltip = tooltip()
                except Exception:
                    pass
        threading.Thread(target=work, daemon=True).start()

    def update_label(_item):
        if not exe_path():
            return "Update CMSync (running from python)"
        return "Update CMSync — NEW BUILD" if state.get("update_available") else "Update CMSync"

    menu = pystray.Menu(
        pystray.MenuItem(header_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("⚙️ إظهار نافذة البرنامج / Show CMSync", change_config, default=True),
        pystray.MenuItem("🌐 Open Dashboard / فتح الموقع", open_dash),
        pystray.MenuItem("🔄 Sync Now / تحديث الآن", sync_now),
        pystray.MenuItem("🔑 Link Account / ربط الحساب", change_config),
        pystray.MenuItem(update_label, update_now),
        pystray.MenuItem("🚀 Run with Windows / تشغيل مع ويندوز", toggle_startup, checked=lambda item: startup_enabled()),
        pystray.MenuItem("📁 Open the log folder", show_log),
        pystray.MenuItem("📄 Token file (C:)", lambda _i=None, _x=None: open_token_file(cfg)),
        pystray.MenuItem("❌ Exit / خروج", lambda: (stop.set(), icon.stop(), os._exit(0))),
    )
    icon = pystray.Icon(APP_NAME, make_icon(), tooltip(), menu)

    def reporter():
        while not stop.is_set():
            time.sleep(10)
            try:
                icon.tooltip = tooltip()
            except Exception:
                break

    threading.Thread(target=lambda: loop(cfg, state, stop, notify=on_notify), daemon=True).start()
    threading.Thread(target=reporter, daemon=True).start()
    if show_ui_on_start:
        threading.Thread(target=change_config, daemon=True).start()
    icon.run()


def say(message):
    """الـ exe بيتبني من غير نافذة كونسول — فالرسايل تظهر أو تتسجل بس."""
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
    ap.add_argument("--once", action="store_true", help="one cycle and print the result")
    ap.add_argument("--console", action="store_true", help="run without the tray icon")
    ap.add_argument("--config", action="store_true", help="open subscriber setup dialog")
    ap.add_argument("--install", action="store_true", help="Windows startup + shortcut")
    ap.add_argument("--uninstall", action="store_true", help="remove Windows startup")
    ap.add_argument("--update-check", action="store_true",
                    help="compare this build with the dashboard's and stop")
    ap.add_argument("--apply-update", nargs=3, metavar=("PID", "TARGET", "SOURCE"),
                    help=argparse.SUPPRESS)  # داخلية: النسخة الجديدة بتبدّل القديمة
    ap.add_argument("--project", default=None, help="dashboard folder")
    args = ap.parse_args(argv)
    if args.apply_update:
        pid, target, source = args.apply_update
        return apply_update(int(pid), source, target)
    cfg = load_config()
    if args.project:
        cfg["project"] = args.project
        save_config(cfg)
    state = load_state()
    if args.config:
        prompt_subscriber_config(cfg, force=True)
        mutex = single_instance()
        if not mutex:
            return 0
        run_tray(cfg, state)
        return 0
    if args.install:
        return install(cfg)
    if args.uninstall:
        set_startup(False)
        say("Windows startup removed.")
        return 0
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(cfg)  # أول تشغيل: يسيب ملف قابل للتعديل بدل القيم الافتراضية الصامتة
    log("boot: project=%s port=%s python=%s" % (cfg["project"], cfg["port"], cfg["python"]))
    if args.update_check:
        ensure_site(cfg)
        mine, remote = exe_path(), release_info(cfg)
        local = file_release(mine) if mine else None
        say("Update check: %s" % json.dumps({
            "running": mine or "python (no exe to replace)",
            "local_build": local and time.strftime("%Y-%m-%d %H:%M", time.localtime(local["built_at"])),
            "server_build": remote and remote.get("built_at_text"),
            "server_size_mb": remote and round((remote.get("size") or 0) / 1048576, 1),
            "update_available": bool(local and remote and local["sha256"] != remote["sha256"]),
        }, ensure_ascii=False))
        return 0
    if args.once:
        ensure_site(cfg)
        status = sync_once(cfg, state, force=True)
        note = refresh_manifest(cfg, state, force=True)
        print(json.dumps({"status": status, "manifest": note,
                          "update": check_update(cfg, state, force=True),
                          "account": state.get("account")}, ensure_ascii=False))
        save_state(state)
        return 0
    if args.console:
        loop(cfg, state, threading.Event(), notify=lambda m, **k: log("NOTIFY " + m))
        return 0
    mutex = single_instance()
    if not mutex:
        return 0
    show_ui = not args.console and not args.once and not args.install
    run_tray(cfg, state, show_ui_on_start=show_ui)
    return 0


if __name__ == "__main__":
    sys.exit(main())
