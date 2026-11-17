"""عميل بوابة Pioneer الرسمية.

الاتصال مباشر بـ api-gateway.europe.es-pio.net بالتوكن المحفوظ لكل حساب، بدون
Rampart ولا بوابة Pioneer. مسارات بيانات اللعبة محتاجة `x-embark-manifest-id`
(رقم بيتغير مع كل باتش) — بيتقرأ من data/pioneer_manifest.json وتحدّثه من
inspection/pioneer_manifest.py بعد كل تحديث للعبة.

القراءة GET. الطلبات POST محصورة في حاجتين: تجديد المانيفست، ومسار النقل
/v1/pioneer/inventory/v1/mutate (بيستخدمه pioneer_write بعد التحقق).
"""
import base64
import hashlib
import json
import os
import random
import sqlite3
import string
import threading
import time

import requests

from . import config

# اتصال keep-alive لكل ثريد: البوابة بتقبل إعادة استخدام الـ TLS، والقراءة
# التانية بتوفر حوالي 0.2 ثانية مقارنة باتصال جديد كل مرة.
_LOCAL = threading.local()


def _session():
    sess = getattr(_LOCAL, "session", None)
    if sess is None:
        sess = requests.Session()
        _LOCAL.session = sess
    return sess

BASE = os.environ.get("PIONEER_BASE", "https://api-gateway.europe.es-pio.net")
MANIFEST_FILE = os.path.join(config.DATA_DIR, "pioneer_manifest.json")
TELEMETRY_FILE = os.path.join(config.DATA_DIR, "pioneer_telemetry.json")
UA = os.environ.get(
    "PIONEER_UA",
    "PioneerGame/pioneer_2.02.x-CL1430164 (http-legacy) WinGDK/10.0.26200.1.256.64bit",
)
PLATFORM = "12"


class PioneerError(Exception):
    pass


class ManifestUnknown(PioneerError):
    pass


class ManifestExpired(PioneerError):
    pass


class TokenExpired(PioneerError):
    pass


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_manifest():
    data = _read_json(MANIFEST_FILE) or {}
    return str(data.get("manifest_id") or "").strip()


def save_manifest(manifest_id, build=""):
    payload = {"manifest_id": str(manifest_id).strip(),
               "build": build or UA.split("/")[1].split(" ")[0],
               "updated_at": int(time.time())}
    os.makedirs(os.path.dirname(MANIFEST_FILE), exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return payload


def refetch_manifest(token=None):
    """يسأل البوابة عن رقم المانيفست الحالي.

    build_id فاضي = أحدث باتش منشور، فالسيرفر بيرد برقم المانيفست الحي. build
    المحفوظ بيطلب المانيفست بتاع نفس الbuild — يعني لو اللعبة اتحدّثت بيرجع
    الرقم القديم نفسه (مقيس 2026-11-05: القديم 4444166003814106529، الجديد
    2961792159033244263 والكتابة بيه بتنفّذ).
    """
    token = token or account_token()
    saved = _read_json(MANIFEST_FILE) or {}
    body = {"build_id": "", "playtest_id": 0, "artifact_id": "",
            "store_deployment_target": "Production", "manifest_id": 0,
            "app_id": "2118292977-WinGDK"}
    resp = requests.post(BASE + "/v1/shared/manifest", headers=headers(token), json=body,
                         timeout=config.HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise PioneerError("refetch manifest -> HTTP %s: %s" % (resp.status_code, resp.text[:200]))
    try:
        manifest_id = str(resp.json().get("id") or "")
    except ValueError:
        manifest_id = ""
    if not manifest_id:
        raise PioneerError("The manifest refetch returned a response without an id.")
    save_manifest(manifest_id, build=str(saved.get("build") or ""))
    return manifest_id


def telemetry_uuid():
    data = _read_json(TELEMETRY_FILE) or {}
    if data.get("uuid"):
        return data["uuid"]
    uid = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(20))
    os.makedirs(os.path.dirname(TELEMETRY_FILE), exist_ok=True)
    with open(TELEMETRY_FILE, "w", encoding="utf-8") as fh:
        json.dump({"uuid": uid}, fh)
    return uid


def account_token(name=None):
    db = sqlite3.connect(config.DB_FILE)
    try:
        if name:
            row = db.execute("SELECT token FROM accounts WHERE name = ?", (name,)).fetchone()
        else:
            row = db.execute("SELECT token FROM accounts WHERE is_active = 1 LIMIT 1").fetchone()
            if not row:
                row = db.execute("SELECT token FROM accounts ORDER BY updated_at DESC LIMIT 1").fetchone()
    finally:
        db.close()
    return (row[0] if row else "") or ""


def token_expiry(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part))
        return int(claims.get("exp") or 0)
    except (IndexError, ValueError, KeyError):
        return 0


def headers(token, manifest_id=""):
    h = {
        "Host": BASE.split("//", 1)[-1],
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "x-embark-telemetry-uuid": telemetry_uuid(),
        "x-embark-telemetry-client-platform": PLATFORM,
        "Connection": "keep-alive",
    }
    if manifest_id:
        h["x-embark-manifest-id"] = str(manifest_id)
    return h


def request(path, token=None, manifest_id=None, timeout=config.HTTP_TIMEOUT, method="GET",
            _retry=True, body=None):
    token = token or account_token()
    if not token:
        raise TokenExpired("No saved token for the account — you must log into the game again.")
    exp = token_expiry(token)
    if exp and exp < time.time():
        raise TokenExpired("The account token is expired (%s) — refresh it from the game." %
                           time.strftime("%Y-%m-%d %H:%M", time.localtime(exp)))
    if manifest_id is None:
        manifest_id = load_manifest()
    url = path if str(path).startswith("http") else BASE + path
    resp = _session().request(method, url, headers=headers(token, manifest_id),
                              json=body if body is not None else None,
                              timeout=timeout, verify=True)
    text = resp.text[:400]
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError:
            return {}
    if resp.status_code == 401:
        raise TokenExpired("The gateway rejected the token (401).")
    # المانيفست القديم بيطهر في ثلاث ردود: 403/409 على القراءة، و412 FAILED_PRECONDITION
    # على الكتابة (القراءة بتمشي عليه عادي، فالكتابة هي اللي بتكشف الباتش).
    stale = (("MANIFEST_IS_FORBIDDEN" in text or "MANIFEST_EXPIRED" in text)
             if resp.status_code in (403, 409) else
             (resp.status_code == 412 and "FAILED_PRECONDITION" in text))
    if stale and _retry:
        try:
            fresh = refetch_manifest(token)
        except PioneerError:
            fresh = ""
        if fresh and fresh != manifest_id:
            return request(path, token, fresh, timeout, method, _retry=False, body=body)
    if resp.status_code == 403 and "MANIFEST_IS_FORBIDDEN" in text:
        raise ManifestUnknown("The manifest number is unknown to the server — it must be the current patch value.")
    if resp.status_code == 409 and "MANIFEST_EXPIRED" in text:
        raise ManifestExpired("The manifest number is outdated (409) — the server wants the current value.")
    raise PioneerError("%s %s -> %s: %s" % (method, path, resp.status_code, text))


def validate_manifest(manifest_id=None):
    """يرجّع (status, detail) — status واحد من ok/unknown/expired/error/none."""
    manifest_id = (manifest_id or load_manifest()).strip()
    if not manifest_id:
        return "none", "No manifest number is saved."
    try:
        data = request("/v1/pioneer/inventory", manifest_id=manifest_id)
    except ManifestUnknown as err:
        return "unknown", str(err)
    except ManifestExpired as err:
        return "expired", str(err)
    except TokenExpired as err:
        return "error", str(err)
    except (PioneerError, requests.RequestException) as err:
        return "error", "%s: %s" % (type(err).__name__, err)
    items = data.get("items") if isinstance(data, dict) else None
    return "ok", "The stash returned %s" % (("%d items" % len(items)) if isinstance(items, list) else "Valid JSON")


def post_json(path, body, token=None, manifest_id=None):
    """POST لمسار مثبت فقط (مش مستخدم في القراءة العادية)."""
    return request(path, token=token, manifest_id=manifest_id, method="POST", body=body)


def fetch_inventory():
    return request("/v1/pioneer/inventory")


def fetch_inventory_for(account_name):
    """مخزن حساب معيّن بتوكنه المحفوظ (المزامنة المباشرة بتستخدم الدالة دي)."""
    token = account_token(account_name)
    if not token:
        raise TokenExpired("No saved token for account %s — add it from the accounts page." % account_name)
    return request("/v1/pioneer/inventory", token=token)


def fetch_raiders():
    return request("/v1/pioneer/raiders")


_LIVE_OK = {}
LIVE_OK_SECONDS = 900


def validate_token_live(token):
    """اختبار قراءة فقط: البوابة بتقبل التوكن ده فعلًا؟ بيرجع (ok, رسالة).

    نسخة التوكن المبتورة من ذاكرة اللعبة بتفكّ الـ payload بتاعها صح وبتاخد 401 من
    البوابة — فالسجل المحلي لازم يستنى الضوء الأخضر ده قبل ما يعمل حساب جديد أو
    يمسح توكن شغال. أخطاء المانيفست/الشبكة ما بتعتبرش رفض للتوكن.

    عشان المسح كل 5 دقايق ما يضربش البوابة كل مرة: التوكن اللي اتقبل مرة بيتصادق عليه 15 دقيقة.
    """
    if not token:
        return False, "No token"
    key = hashlib.sha256(token.encode("utf-8", "ignore")).hexdigest()[:16]
    if _LIVE_OK.get(key, 0) > time.time():
        return True, "cached"
    try:
        request("/v1/pioneer/raiders", token=token, timeout=20)
    except TokenExpired as err:
        return False, str(err)
    except PioneerError as err:
        return True, "gateway answered (non-token error: %s)" % type(err).__name__
    except requests.RequestException as err:
        return True, "network error, token not judged (%s)" % type(err).__name__
    _LIVE_OK[key] = time.time() + LIVE_OK_SECONDS
    return True, "accepted"
