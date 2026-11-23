"""عميل Rampart — المسارات المسموحة هنا محسوبة حرفياً.

قراءة المخزن (نفس اللي auto_sync_v2.py بيعملهم):
  GET  /auth/embark                 -> قائمة الحسابات المرتبطة
  POST /auth/embark/{id}/activate   -> تبديل الحساب النشط (لا يمس المخزن: لا بيع/نقل/حذف)
  GET  /inventory/parsed            -> قراءة المخزن

قراءة/كتابة على *ملف المستخدم في Rampart نفسه* (لا تلمس أي عنصر في اللعبة أبداً،
وتُستدعى فقط من صفحة الحسابات بضغطة زر صريحة — مش من دورة المزامنة):
  GET    /auth/me                   -> بيانات الحساب/الخطة/الحد الأقصى
  POST   /auth/embark               -> ربط توكن حساب لعبة جديد بالبروفايل
  PATCH  /auth/embark/{id}          -> تعديل اللابل أو استبدال التوكن
  DELETE /auth/embark/{id}          -> فك ربط حساب من البروفايل

ممنوع أي endpoint تاني يغيّر حالة عنصر.
"""
import json
import os
import time

import requests

from . import config

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-EG,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
}


def read_token():
    for path in (config.TOKEN_FILE, config.LEGACY_TOKEN_FILE):
        try:
            if path and os.path.exists(path):
                with open(path, encoding="utf-8-sig") as f:
                    tok = f.read().strip()
                if tok:
                    if tok.lower().startswith("bearer "):
                        tok = tok[7:]
                    return tok.strip().strip('"')
        except OSError:
            continue
    return ""


def headers():
    h = dict(HEADERS)
    tok = read_token()
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def token_expiry(token):
    import base64
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or 0)
    except Exception:
        return 0


class UpstreamError(RuntimeError):
    pass


class RampartDisabled(UpstreamError):
    """كل طريق للخدمة الوسيطة بيعدي هنا — مقفول افتراضياً (FAHMY_RAMPART=off)."""

    def __init__(self, path=""):
        RuntimeError.__init__(
            self, "Upstream linking is stopped: the project runs directly on the official Embark gateway."
                  + (" (%s)" % path if path else ""))


def _guard(path=""):
    if not config.RAMPART_ENABLED:
        raise RampartDisabled(path)


def _get(path, retries=2):
    _guard(path)
    last = None
    for attempt in range(retries + 1):
        try:
            res = requests.get(path, headers=headers(), timeout=config.HTTP_TIMEOUT)
            if res.status_code == 200:
                return res.json()
            last = UpstreamError("GET %s -> HTTP %s %s" % (path, res.status_code, (res.text or "")[:200]))
            if res.status_code == 429:
                time.sleep((attempt + 1) * 3)
                continue
            break
        except Exception as e:
            last = UpstreamError("GET %s failed: %s" % (path, e))
            time.sleep(1.5 * (attempt + 1))
    raise last or UpstreamError("GET %s failed" % path)


def list_accounts():
    """GET /auth/embark كامل (بيانات البروفايل للعرض في صفحة الحسابات)."""
    if not config.RAMPART_ENABLED:
        return []
    data = _get(config.EMBARK_LIST_PATH)
    out = []
    for acc in data if isinstance(data, list) else []:
        if not acc.get("id"):
            continue
        out.append({
            "id": str(acc.get("id")), "label": acc.get("label"),
            "platform": acc.get("platform") or "steam",
            "is_active": bool(acc.get("is_active")), "is_expired": bool(acc.get("is_expired")),
            "is_restricted": bool(acc.get("is_restricted")),
            "display_name": acc.get("display_name"), "embark_id": acc.get("embark_id"),
            "email": acc.get("email"), "third_party_name": acc.get("third_party_name"),
            "third_party_user_id": acc.get("third_party_user_id"),
            "owner_username": acc.get("owner_username"), "token": acc.get("token") or "",
            "token_expiry": acc.get("token_expiry"), "added_at": acc.get("added_at"),
            "updated_at": acc.get("updated_at"),
        })
    return out


def fetch_inventory(account_id, activate=True):
    """يرجع payload المخزن الخام لحساب واحد (نفس شكل /inventory/parsed بالحرف)."""
    _guard(config.UPARSE_URL_PATH)
    if activate:
        res = requests.post(config.ACTIVATE_PATH.format(account_id=account_id),
                            headers=headers(), timeout=config.HTTP_TIMEOUT)
        if res.status_code not in (200, 201, 204):
            raise UpstreamError("activate %s -> HTTP %s %s" % (account_id[:8], res.status_code, (res.text or "")[:200]))
        time.sleep(1.0)
    return _get(config.UPARSE_URL_PATH)


# ------------------------------------------------- ملف المستخدم في Rampart (لا يمس المخزن)
def _send(method, path, body=None):
    _guard(path)
    res = requests.request(method, path, headers=headers(),
                           json=body if body is not None else None, timeout=config.HTTP_TIMEOUT)
    if res.status_code not in (200, 201, 204):
        raise UpstreamError("%s %s -> HTTP %s %s" % (method, path, res.status_code, (res.text or "")[:240]))
    if not res.content:
        return {}
    try:
        return res.json()
    except ValueError:
        return {}


def me():
    """GET /auth/me — بيانات البروفايل: username، الخطة، account_limit، current_account_count."""
    return _get("/auth/me")


def embark_add(token, label=""):
    return _send("POST", "/auth/embark",
                 {"token": token, "label": label or None, "platform": "manual"})


def embark_patch(account_id, token=None, label=None):
    body = {}
    if token:
        body["token"] = token
    if label is not None:
        body["label"] = label
    return _send("PATCH", "/auth/embark/%s" % account_id, body)


def embark_delete(account_id):
    return _send("DELETE", "/auth/embark/%s" % account_id)
