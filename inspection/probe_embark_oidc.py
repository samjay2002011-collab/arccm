"""مسح تعريفي لمزوّد هوية Embark الرسمي (auth.embark.net) — بدون أي كتابة على الحساب.

بنسأل تلات حاجات:
1) token endpoint بـ client_credentials لأسماء عملاء متوقعة: الرد بيورينا
   العميل الموجود فعلاً وبيطلب سر ولا لا.
2) authorize endpoint بقيم redirect_uri مختلفة: خطأ open-redirect بيفصح
   عن قائمة العناوين المسجّلة (يعني نعرف الـ app المسجّل رسمي).
3) scopes بديلة (pioneer / launcher / play / arkadia) على نفس الطلبات.
"""
import json
import sys
import urllib.parse
import urllib.request
import urllib.error

AUTH = "https://auth.embark.net"
TOKEN = AUTH + "/oauth2/token"
Authorize = AUTH + "/oauth2/authorize"

CLIENTS = [
    "embark-pioneer", "embark-launcher", "embark-web", "pioneer", "arc-raiders",
    "arcraiders", "embark-arc-raiders", "embark-companion", "embark-store",
    "embark-iap", "launcher", "web",
]
SCOPES = ["pioneer", "pioneer offline_access", "launcher pioneer",
          "play pioneer", "arkadia pioneer", "openid pioneer", ""]
CB_URIS = ["https://pioneerfree.arc-traders.net/signin-oidc",
           "https://rampart.su/auth/callback",
           "https://auth.embark.net/callback",
           "http://localhost:8000/callback",
           "https://arc-traders.net/callback",
           "com.embark.pioneer://callback"]


def post(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    h = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
         "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(400)
    except urllib.error.HTTPError as e:
        return e.code, e.read(400)
    except Exception as e:
        return None, str(e)[:150].encode()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.geturl(), dict(r.headers), r.read(500)
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read(500)
    except Exception as e:
        return None, url, {}, str(e)[:150].encode()


def main():
    print("######## client_credentials")
    for cid in CLIENTS:
        code, body = post(TOKEN, {"grant_type": "client_credentials", "client_id": cid,
                                  "scope": "pioneer"})
        print("%-22s %-5s %s" % (cid, code, body.decode("utf-8", "replace").replace("\n", " ")[:150]))

    print("\n######## scopes (client_id=embark-pioneer)")
    for sc in SCOPES:
        code, body = post(TOKEN, {"grant_type": "client_credentials",
                                  "client_id": "embark-pioneer", "scope": sc})
        print("%-26s %-5s %s" % (sc or "(none)", code,
                                 body.decode("utf-8", "replace").replace("\n", " ")[:140]))

    print("\n######## authorize redirect_uri registration")
    for cb in CB_URIS:
        q = urllib.parse.urlencode({"client_id": "embark-pioneer", "response_type": "code",
                                    "scope": "openid pioneer offline_access",
                                    "redirect_uri": cb, "state": "probe"})
        code, final, hdr, body = get(Authorize + "?" + q)
        loc = hdr.get("Location") or hdr.get("location") or ""
        txt = body.decode("utf-8", "replace").replace("\n", " ")
        clean = " ".join(txt.split())[:130]
        print("%-48s %-5s loc=%-30s %s" % (cb[:48], code, loc[:30], clean))


if __name__ == "__main__":
    main()
