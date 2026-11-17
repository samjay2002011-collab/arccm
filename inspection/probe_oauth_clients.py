"""جرد أسماء عملاء OAuth عند Embark الرسمي بمقياس "العميل عام ولا سري".

المنطق: `grant_type=refresh_token` بيرد 401 invalid_client لما العميل محتاج
سر (أو مش موجود)، و400 invalid_grant لما التحقق من العميل عدّى والرفض جه من
الـ grant نفسه — يعني العميل عام (public). بنجرّب قايمة أسماء متوقعة، وكل عام
بنسأله client_credentials عشان نشوف لو بيطّلع توكن تطبيق من غير مستخدم.
مافيش أي كتابة على أي حساب: بنرسل توكنات مضروضة بس.
"""
import urllib.error
import urllib.parse
import urllib.request

TOKEN = "https://auth.embark.net/oauth2/token"
CLIENTS = [
    "embark-launcher", "embark-pioneer", "embark-web", "embark-store", "embark-iap",
    "embark-account", "embark-accounts", "embark-arkadia", "embark-play",
    "launcher", "launcher-web", "pioneer-web", "pioneer", "arc-raiders",
    "arc-raiders-launcher", "arc-raiders-web", "arc-raiders-pioneer",
    "embark-arc-raiders-launcher", "embark-launcher-web", "embark-identity",
    "embark-oauth", "embark-auth", "embark-client", "embark", "embark-studios",
    "arcraiders", "arc-raiders-companion", "pioneer-companion", "embark-companion",
    "embark-traders", "embark-market", "arkadia", "arkadia-web", "play",
]
FAKE_RT = "00000000-0000-4000-8000-000000000000"


def post(data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(TOKEN, data=body, headers={
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(400)
    except urllib.error.HTTPError as e:
        return e.code, e.read(400)
    except Exception as e:
        return None, str(e)[:150].encode()


def short(b):
    try:
        j = __import__("json").loads(b)
        return "%s / %s" % (j.get("error"), (j.get("error_description") or "")[:60])
    except Exception:
        return b.decode("utf-8", "replace").replace("\n", " ")[:90]


def main():
    print("%-32s %-9s %s" % ("client", "refresh", "client_credentials"))
    for cid in CLIENTS:
        c1, b1 = post({"grant_type": "refresh_token", "client_id": cid, "refresh_token": FAKE_RT})
        pub = c1 == 400
        line = "%-32s %-9s" % (cid, "PUBLIC" if pub else ("secret" if c1 == 401 else c1))
        if pub:
            c2, b2 = post({"grant_type": "client_credentials", "client_id": cid, "scope": "pioneer"})
            line += " %s %s" % (c2, short(b2))
        print(line)


if __name__ == "__main__":
    main()
