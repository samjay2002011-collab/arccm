r"""المرحلة 1: فحص قرائي خالص (READ-ONLY) لموقع rampart.su.

القيود الصارمة المتفق عليها:
  - blocked على أي POST/PUT/PATCH/DELETE -> الطلبات دي بتُلغى قبل ما تخرج من المتصفح.
  - مفيش أي click/type/keyboard/scroll-to-activate: بس navigation + قراءة DOM + اعتراض responses.
  - مفيش أي استخدام لـ credentials من متصفح Brave الشخصي: بنستخدم .rampart_profile المخصص.

المخرجات بتتحفظ في C:\Users\Administrator\Desktop\rr\inspection\
"""
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

SRC = r"C:\Users\Administrator\Desktop\ll"
OUT = r"C:\Users\Administrator\Desktop\rr\inspection"
ASSETS = r"C:\Users\Administrator\Desktop\rr\assets"
PROFILE = os.path.join(SRC, ".rampart_profile")
TOKEN_FILE = os.path.join(SRC, "rampart_token.txt")

PAGES = [
    ("inventory", "https://rampart.su/inventory"),
    ("home", "https://rampart.su/"),
    ("traders", "https://rampart.su/traders"),
]
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ASSET_EXT = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".ico")
SAFE_HOSTS = {"rampart.su", "api.rampart.su", "cdn.rampart.su", "static.rampart.su"}

captured = {"requests": [], "responses": [], "payloads": {}, "websocket": []}
asset_urls = set()


def safe_host(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in SAFE_HOSTS)


def fname(url):
    p = urlparse(url)
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", (p.path or "/").strip("/")) or "root"
    return "%s%s.json" % (re.sub(r"[^A-Za-z0-9]+", "_", p.netloc).strip("_"), clean)


def block_mutating(route):
    req = route.request
    if req.method in MUTATING:
        captured["requests"].append({"method": req.method, "url": req.url, "outcome": "BLOCKED-READ-ONLY"})
        try:
            route.abort()
        except Exception:
            pass
        return
    try:
        route.continue_()
    except Exception:
        pass


def on_response(res):
    url = res.url
    if not safe_host(url):
        return
    ctype = (res.headers.get("content-type") or "").lower()
    rec = {"method": res.request.method, "url": url, "status": res.status, "ctype": ctype}
    captured["responses"].append(rec)
    if "json" in ctype and res.request.method == "GET":
        try:
            body = res.json()
            key = fname(url)
            captured["payloads"][key] = {"url": url, "status": res.status, "body": body}
            walk_assets(body, depth=0)
        except Exception:
            pass
    elif any(e in ctype for e in ("image", "font", "css")) or url.lower().endswith(ASSET_EXT):
        asset_urls.add(url)


def walk_assets(node, depth):
    if depth > 8:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and (v.lower().endswith(ASSET_EXT) or ("/item" in v and "/" in v)):
                if v.startswith("http") or v.startswith("/"):
                    asset_urls.add(urljoin("https://rampart.su", v))
            else:
                walk_assets(v, depth + 1)
    elif isinstance(node, list):
        for v in node[:400]:
            walk_assets(v, depth + 1)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(ASSETS, "items"), exist_ok=True)
    os.makedirs(os.path.join(ASSETS, "fonts"), exist_ok=True)
    os.makedirs(os.path.join(ASSETS, "css"), exist_ok=True)
    os.makedirs(os.path.join(ASSETS, "js"), exist_ok=True)
    for sub in ("html", "screenshots"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)

    token = ""
    try:
        with open(TOKEN_FILE, encoding="utf-8-sig") as f:
            token = f.read().strip()
    except OSError:
        print("[!] no rampart_token.txt -> continuing anonymously")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE, headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        if token:
            ctx.add_cookies([{"name": "token", "value": token, "domain": "rampart.su", "path": "/"}])
            ctx.set_extra_http_headers({"Authorization": "Bearer " + token})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.route("**/*", block_mutating)

        def on_ws(frame):
            captured["websocket"].append(str(frame)[:400])

        page.on("websocket", lambda ws: ws.on("framereceived", on_ws))
        page.on("response", on_response)

        for tag, url in PAGES:
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception as e:
                print("   [skip] %s -> %s" % (url, str(e)[:120]))
                continue
            html = page.content()
            with open(os.path.join(OUT, "html", "%s.html" % tag), "w", encoding="utf-8") as f:
                f.write(html)
            try:
                page.screenshot(path=os.path.join(OUT, "screenshots", "%s.png" % tag),
                                full_page=(tag != "inventory"))
            except Exception:
                pass
            print("   [saved] %s (%d bytes html)" % (tag, len(html)))

        # تصميم: الألوان/الخطوط/القواعد من أوراق الأنماط المحمّلة + أي CSS inline
        try:
            css_dump = page.evaluate(
                """() => Array.from(document.styleSheets).map(s => {
                        try { return {href: s.href, rules: Array.from(s.cssRules).map(r => r.cssText).join('\\n')}; }
                        catch (e) { return {href: s.href, rules: '<blocked>'}; }
                   })"""
            )
            with open(os.path.join(OUT, "stylesheets.json"), "w", encoding="utf-8") as f:
                json.dump(css_dump, f, ensure_ascii=False, indent=1)
            print("   [saved] stylesheets.json (%d sheets)" % len(css_dump))
        except Exception as e:
            print("   [!] css dump failed:", str(e)[:120])

        # كل روابط الأصول اللي الصفحة سحبها فعلاً
        try:
            for src in page.eval_on_selector_all(
                "img,link[href],source,script[src]",
                "els => els.map(e => e.src || e.href).filter(Boolean)"
            ):
                asset_urls.add(urljoin("https://rampart.su", src))
        except Exception:
            pass

        ctx.close()

    with open(os.path.join(OUT, "network_responses.json"), "w", encoding="utf-8") as f:
        json.dump(captured["responses"], f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "network_payloads.json"), "w", encoding="utf-8") as f:
        json.dump(captured["payloads"], f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "blocked_mutating.json"), "w", encoding="utf-8") as f:
        json.dump(captured["requests"], f, ensure_ascii=False, indent=1)

    print("[OK] GET responses captured: %d | json payload files: %d | asset urls: %d"
          % (len(captured["responses"]), len(captured["payloads"]), len(asset_urls)))
    with open(os.path.join(OUT, "asset_urls.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(asset_urls), f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
