"""يقفل السيرفر، يستنى الحارس يرجّعه، ويفاشر ترويسات الكاش والصور الجديدة.

    python inspection/verify_cache.py

بيراجع المسار المحلي بكوكي /login صالح (الباب مقفول لول)، ويطبع Cache-Control
والنوع والحجم لكل مسار — بدون أي طلب تعديل للمنبع.
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inspection import site_restart  # noqa: E402

ROOT = "http://127.0.0.1:8000"
CHECKS = ["/", "/index.html", "/app.js?v=191", "/styles.css?v=60", "/icons/bag.webp",
          "/icons/gear.webp", "/icons/scrappy.webp", "/assets/hideout/base_scrappy.webp",
          "/api/status", "/api/inventory", "/api/sections", "/icons/bag.png"]


def opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(op, path):
    req = urllib.request.Request(ROOT + path, headers={"Accept": "text/html,*/*"})
    try:
        with op.open(req, timeout=60) as resp:
            body = resp.read()
            return resp.status, dict(resp.headers), len(body)
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers or {}), len(err.read())


def main():
    killed = site_restart.listeners()
    if killed:
        for pid in killed:
            os.system('taskkill /PID %s /f >nul 2>&1' % pid)
        print("killed", killed)
    op = opener()
    up = 0
    for _ in range(90):
        try:
            up, _, _ = call(op, "/api/status")
            if up == 200:
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5)
    if up != 200:
        print("SITE DOWN after 90s — check FahmySync")
        return 1
    pw = json.load(open(os.path.join("data", "access.json"), encoding="utf-8")).get("password") or ""
    req = urllib.request.Request(ROOT + "/login",
                                data=("password=" + pw).encode(),
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with op.open(req, timeout=30) as resp:
            print("login ->", resp.status, resp.headers.get("Location"))
    except urllib.error.HTTPError as err:
        print("login FAILED ->", err.code, err.read()[:120])
        return 1
    for path in CHECKS:
        code, head, size = call(op, path)
        print("%-34s %s  cc=%-42s ct=%-24s %s KB" % (
            path, code, head.get("Cache-Control"), (head.get("Content-Type") or "")[:24],
            round(size / 1024, 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
