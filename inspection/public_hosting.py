"""اللوحة على 0.0.0.0 + نفق cloudflared — في أمر واحد، ومن غير أي سطر مركّب.

    python inspection/public_hosting.py start    # يشغّل اللوحة والنفق ويطبع الرابط
    python inspection/public_hosting.py url      # يطبع الرابط اللي شغال دلوقتي
    python inspection/public_hosting.py stop     # يقفل النفق واللوحة اللي فتحها هنا

اللوحة بتشتغل على كل الواجهات (0.0.0.0) عشان النفق يقدر يوصّلها، وكل حاجة وراها
كلمة المرور بتاعة backend/auth.py. الرابط المؤقت بيروح في data/tunnel.log.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import config  # noqa: E402

PYTHON = sys.executable
LOG_DIR = os.path.join(config.DATA_DIR, "launch")
SITE_LOG = os.path.join(LOG_DIR, "site_public.log")
TUNNEL_LOG = os.path.join(LOG_DIR, "tunnel.log")
STATE_FILE = os.path.join(config.DATA_DIR, "hosting.json")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

# win32: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
FLAGS = 0x00000008 | 0x00000200 if os.name == "nt" else 0


def _log(name):
    os.makedirs(LOG_DIR, exist_ok=True)
    return open(name, "ab", buffering=0)


def _state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _save_state(row):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(row, fh, indent=1)


def listening(port=None):
    """كل (pid, العنوان المحلي) اللي بيسمع على البورت ده."""
    port = port or config.PORT
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or "LISTENING" not in line.upper():
            continue
        if parts[1].endswith(":%d" % port):
            pid = int(parts[-1])
            if (pid, parts[1]) not in rows:
                rows.append((pid, parts[1]))
    return rows


def public_listener(port=None):
    """PID بيسمع على كل الواجهات — لو مفيش فاللوحة محلية بس ولازم تتعاد تشغيلها."""
    for pid, local in listening(port):
        if local.startswith("0.0.0.0:") or local.startswith("[::]:"):
            return pid
    return 0


def status_code(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return res.status
    except urllib.error.HTTPError as err:
        return err.code
    except Exception:
        return 0


def gate_up(port=None):
    """True لو اللوحة شغّلة بالكود الجديد: /api/accounts بيرفض من غير كوكي."""
    return status_code("http://127.0.0.1:%d/api/accounts" % (port or config.PORT)) == 401


def start_site(host=None, port=None, force=False):
    """يشغّل uvicorn على كل الواجهات. بيخلي العملية القائمة لو هي عامة وفيها الباب."""
    host = host or config.HOST
    port = port or config.PORT
    already = listening(port)
    pid = public_listener(port)
    if pid and not force and gate_up(port):
        print("the site is already public on %d (pid %d) and the gate is answering." % (port, pid))
        return pid
    for cur, local in already:
        subprocess.run(["taskkill", "/PID", str(cur), "/f"], capture_output=True)
        print("closed the old listener on %s (pid %d)." % (local, cur))
    if already:
        time.sleep(1.0)
    cmd = [PYTHON, "-X", "utf8", "-m", "uvicorn", "backend.main:app",
           "--host", host, "--port", str(port), "--log-level", "warning"]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=_log(SITE_LOG), stderr=_log(SITE_LOG),
                            creationflags=FLAGS, close_fds=True)
    print("starting the site on %s:%d (pid %d)…" % (host, port, proc.pid))
    for _ in range(60):
        time.sleep(1.5)
        if proc.poll() is not None:
            break
        if public_listener(port) and gate_up(port):
            print("the site is up and locked.")
            return proc.pid
    print("the site did not come up with the gate. last lines of %s:" % SITE_LOG)
    print(_tail(SITE_LOG, 12))
    return 0


def cloudflared_path():
    found = subprocess.run("where cloudflared", shell=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace").stdout.split()
    for cand in found:
        if os.path.isfile(cand):
            return cand
    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"),
             os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "cloudflared"),
             os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "cloudflared"),
             os.path.join(ROOT, "tools")]
    for base in roots:
        if not base or not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            if "cloudflared.exe" in files:
                return os.path.join(dirpath, "cloudflared.exe")
    return ""


def start_tunnel(port=None, exe=None):
    port = port or config.PORT
    exe = exe or cloudflared_path()
    if not exe:
        print("cloudflared was not found — install it with:  winget install --id Cloudflare.cloudflared -e")
        return ""
    row = _state()
    if row.get("tunnel_pid") and _alive(row["tunnel_pid"]) and tunnel_url():
        print("the tunnel is already up.")
        return tunnel_url()
    # نقتل نفق uu القديم فقط عشان ما نقفلش نفق الموقع الأساسي اللي على بورت 8000
    old_tunnel = row.get("tunnel_pid")
    if old_tunnel and _alive(old_tunnel):
        _kill(old_tunnel)
    # اللوج بيتكتب من الصفر: الرابط القديم الميت ما يطلعش كإنه هو الشغال
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(TUNNEL_LOG, "wb"):
        pass
    cmd = [exe, "tunnel", "--no-autoupdate", "--url", "http://localhost:%d" % port]
    proc = subprocess.Popen(cmd, stdout=_log(TUNNEL_LOG), stderr=_log(TUNNEL_LOG),
                            creationflags=FLAGS, close_fds=True)
    print("opening the tunnel (pid %d)…" % proc.pid)
    for _ in range(25):
        time.sleep(1.2)
        url = tunnel_url()
        if url:
            row.update({"tunnel_pid": proc.pid, "url": url, "at": int(time.time()),
                        "target": "http://localhost:%d" % port})
            _save_state(row)
            return url
        if proc.poll() is not None:
            break
    print("no URL in the log yet. last lines of %s:" % TUNNEL_LOG)
    print(_tail(TUNNEL_LOG, 15))
    return ""


def tunnel_url():
    """آخر رابط trycloudflare طلع في اللوج — وبيتحقّق إنه لسه بيرد."""
    try:
        with open(TUNNEL_LOG, encoding="utf-8", errors="replace") as fh:
            found = URL_RE.findall(fh.read())
    except OSError:
        return ""
    for url in reversed(found):
        if status_code(url + "/login", timeout=8) in (200, 302, 303):
            return url
    return found[-1] if found else ""


def _tail(path, lines):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return "\n".join(fh.read().splitlines()[-lines:])
    except OSError:
        return "(no log yet)"


def _alive(pid):
    return bool(pid) and _running(pid)


def _running(pid):
    out = subprocess.run("tasklist /FI \"PID eq %d\" /NH" % int(pid), shell=True,
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return str(pid) in out


def _kill(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/f"], capture_output=True)
    else:
        os.kill(int(pid), signal.SIGTERM)


def stop():
    row = _state()
    # نقتل نفق uu فقط
    tunnel_pid = row.get("tunnel_pid")
    if tunnel_pid and _alive(tunnel_pid):
        _kill(tunnel_pid)
        print("closed uu tunnel (pid %d)" % tunnel_pid)
    port = row.get("port") or config.PORT
    mine = row.get("site_pid")
    for pid, local in listening(port):
        if mine and pid == mine:
            _kill(pid)
            print("closed the site (pid %d)" % pid)
    row.update({"tunnel_pid": 0, "url": ""})
    _save_state(row)
    return 0


def main(argv):
    action = (argv[1] if len(argv) > 1 else "start").strip().lower()
    row = _state()
    if action == "url":
        url = tunnel_url()
        print(url or "no live tunnel right now — run:  python inspection/public_hosting.py start")
        return 0 if url else 1
    if action == "stop":
        return stop()
    if action not in ("start", "up", "run"):
        print(__doc__)
        return 1
    pid = start_site()
    if not pid:
        return 1
    row.update({"site_pid": pid, "port": config.PORT, "host": config.HOST})
    _save_state(row)
    url = start_tunnel(config.PORT)
    if not url:
        return 1
    print("")
    print("=" * 68)
    print("  🌐 PUBLIC SHARE LINK: %s" % url)
    print("  🔐 ADMIN PANEL:       %s/admin" % url)
    print("  🔑 ADMIN PASSWORD:    Lord@1234")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
