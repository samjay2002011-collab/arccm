"""لمس مستندات الـ OpenAPI/Swagger على بوابة Pioneer بمختلف أنماط الاعتماد.

كل الطلبات GET ولا تغيّر حاجة. الفكرة نعرف الـ scheme المطلوب في 401
(الرسمة قالت "IAP credentials") ونحاول مسارات بديلة للمستند.
"""
import sys
import urllib.request
import urllib.error

sys.path.insert(0, ".")
from backend import config, pioneer_client

BASE = pioneer_client.BASE
PATHS = [
    "/v1/pioneer/openapi.json",
    "/v1/shared/openapi.json",
    "/openapi.json",
    "/v1/openapi.json",
    "/v1/pioneer/openapi.yaml",
    "/v1/pioneer/swagger.json",
    "/v1/pioneer/docs",
    "/v1/pioneer/swagger/index.html",
    "/v1/pioneer/inventory/openapi.json",
    "/v1/pioneer/iap/openapi.json",
]
TOKENS = {
    "companion": None,          # توكن اللعبة المحفوظ عندنا
    "anonymous": "",
}


def get(path, token, extra=None):
    url = BASE + path
    h = {"User-Agent": pioneer_client.UA, "Accept": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(600)
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(600)
    except Exception as e:
        return None, {"err": str(e)[:160]}, b""


def main():
    tok = pioneer_client.account_token()
    for scheme, use in (("companion", tok), ("anonymous", "")):
        print("\n######## auth=%s" % scheme)
        for path in PATHS:
            code, hdr, body = get(path, use)
            want = hdr.get("WWW-Authenticate") or hdr.get("www-authenticate") or "-"
            txt = body.decode("utf-8", "replace").replace("\n", " ")[:170]
            print("%-38s %-5s www-auth=%-38s %s" % (path, code, want[:38], txt))


if __name__ == "__main__":
    main()
