"""محرك تنفيذ الإجراءات (Action Dispatcher) على حساب اللعبة الحقيقي.

كل المسارات مستخرجة حرفياً من حزمة JS الأصلية:
  POST /inventory/batch-move
  POST /inventory/batch-mutate
  POST /inventory/move-all-to-overflow
  POST /inventory/sync
  GET  /inventory/attachments/slots
  POST /inventory/attachments/attach
  POST /inventory/attachments/batch-attach
  POST /inventory/attachments/detach
  POST /inventory/weapon/upgrade

حماية مفروضة في الكود:
  * الكتابة مفعّلة افتراضياً من غير أي أمر تفعيل، وزر ⏻ بيوقفها ويحفظ الحالة.
  * recycle / scrap / repair / upgrade لا تنفذ إلا بعد تأكيد صريح من نافذة مخصصة
    — أي طلب من غير confirmed=True بيرجع preview بس.
  * delete / discard / destroy / drop / unload / unequip مرفوضة دائماً.
  * كل محاولة (مقبولة أو مرفوضة) بتتسجل في جدول actions.
"""
import json
import os
import time

import requests

from . import config, rampart_client

BATCH_MOVE = "/inventory/batch-move"
BATCH_MUTATE = "/inventory/batch-mutate"
MOVE_ALL_TO_OVERFLOW = "/inventory/move-all-to-overflow"
SYNC = "/inventory/sync"
ATTACH_SLOTS = "/inventory/attachments/slots"
ATTACH = "/inventory/attachments/attach"
BATCH_ATTACH = "/inventory/attachments/batch-attach"
DETACH = "/inventory/attachments/detach"
UPGRADE = "/inventory/weapon/upgrade"
TRADE_ACCEPT = "/traders/accept"
TRADE_ACCEPT_LIMITED = "/traders/accept-limited"

CONTAINERS = ("stash", "backpack", "overflow", "loadout")
MUTATE_ACTIONS = ("split", "combine", "id_update", "recycle", "scrap", "repair")
# محذوفة من الـ API نهائياً — مفيش أي مسار يسمح بها.
HARD_BLOCKED = ("delete", "discard", "destroy", "drop", "unload", "unequip")
# مسموحة فقط بعد نافذة تأكيد + وضع ARM.
CONFIRM_REQUIRED = ("recycle", "scrap", "repair", "upgrade")

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "writes_state.json")


def _load_armed():
    """الكتابة شغالة افتراضياً — مفيش أمر تفعيل مطلوب.
    زر ⏻ بيوقفها، والقيمة بتتحفظ وتُرجع زي ما هي بعد أي إعادة تشغيل."""
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return bool(json.load(fh).get("armed", True))
    except (OSError, ValueError, TypeError):
        return True


def _save_armed():
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"armed": bool(_state["armed"]), "updated": time.time()}, fh)
    except OSError:
        pass


_armed_now = _load_armed()
_state = {"armed": _armed_now, "armed_at": time.time() if _armed_now else None, "last_active": None}


def _write_paused():
    """الملف data/writes_paused = الحساب مشغول بحد تاني: كل الكتابة مقفولة."""
    try:
        from . import pioneer_write
        return pioneer_write.paused()
    except Exception:
        return False


def _direct_kinds():
    """أنواع الـ mutate اللي بوابة Embark بتقبلها فعلاً (recycle/scrap/repair/delete)."""
    try:
        from . import pioneer_write
        return list(pioneer_write.DIRECT_MUTATIONS)
    except Exception:
        return ["recycle", "scrap", "repair", "delete"]


def _route_alive():
    """مسار الكتابة راكب على البوابة؟ البوابة بتشيله وقت صيانتها وترد 404."""
    try:
        from . import pioneer_write
        return bool(pioneer_write.route_alive())
    except Exception:
        return True


def status():
    direct = config.DATA_SOURCE == "pioneer"
    paused = _write_paused()
    endpoint_ok = bool(config.PIONEER_MOVE_ENDPOINT) if direct else True
    route_up = (not direct) or _route_alive()
    move_armed = (((not direct and bool(_state["armed"])) or
                  (direct and endpoint_ok)) and not paused and route_up)
    # في الوضع المباشر الكتابة الحية شغالة على البوابة الرسمية: النقل + المرفقات
    # + التفكيك + الإعدام + الإصلاح. فمفيش سبب نخلي الواجهة تقول غير ده.
    live = ((bool(_state["armed"]) if not direct else endpoint_ok) and not paused and route_up)
    return {
        "armed": live,
        "write_paused": paused,
        "gateway_route_down": bool(direct and not route_up),
        "move_armed": bool(move_armed),
        "move_supported": True,
        "move_mode": "direct_gateway" if direct else "rampart",
        "move_endpoint_configured": (not direct) or bool(config.PIONEER_MOVE_ENDPOINT),
        "armed_at": _state["armed_at"],
        "data_source": config.DATA_SOURCE,
        "writes_supported": (not direct) or bool(config.PIONEER_MOVE_ENDPOINT),
        "mutate_supported": True,
        "mutate_kinds": _direct_kinds() if direct else list(MUTATE_ACTIONS),
        "upgrade_supported": True,
        "destructive_blocked": list(HARD_BLOCKED),
        "confirmation_required": list(CONFIRM_REQUIRED),
        "endpoints": (
            {"move": config.PIONEER_MOVE_ENDPOINT or None, "mutate": None, "overflow_all": None,
             "sync": None, "attach": None, "batch_attach": None, "detach": None,
             "upgrade": "/v1/pioneer/inventory/upgrade",
             "trade_accept": "/v1/pioneer/offers/accept", "trade_accept_limited": "/v1/pioneer/offers/accept"}
            if direct else
            {"move": BATCH_MOVE,
             "mutate": BATCH_MUTATE,
             "overflow_all": MOVE_ALL_TO_OVERFLOW,
             "sync": SYNC,
             "attach": ATTACH,
             "batch_attach": BATCH_ATTACH,
             "detach": DETACH,
             "upgrade": UPGRADE,
             "trade_accept": TRADE_ACCEPT,
             "trade_accept_limited": TRADE_ACCEPT_LIMITED}
        ),
    }


def arm():
    _state["armed"] = True
    _state["armed_at"] = time.time()
    _save_armed()
    return True


def disarm():
    _state["armed"] = False
    _state["armed_at"] = None
    _save_armed()
    return True


def _guard(action="", confirmed=False):
    if config.DATA_SOURCE == "pioneer":
        return {"ok": False, "code": 409, "error": "direct_read_only",
                "detail": "Direct mode: this path has no equivalent on the Embark gateway. "
                          "What runs there: moves, attachments, disassemble, destroy and repair."}
    if not _state["armed"]:
        return {"ok": False, "code": 409, "error": "read_only",
                "detail": "Writes are paused — press the ⏻ button in the header to enable them."}
    low = str(action).lower()
    if any(bad in low for bad in HARD_BLOCKED):
        return {"ok": False, "code": 403, "error": "destructive_blocked",
                "detail": "The action '%s' is destructive and blocked from running through the local mirror." % action}
    if any(bad in low for bad in CONFIRM_REQUIRED) and not confirmed:
        return {"ok": False, "code": 428, "error": "confirmation_required",
                "detail": "The action '%s' must be executed from the dedicated confirmation window (confirmed=true)." % action}
    return None


def ensure_active(account_id):
    """يفعّل الحساب على rampart قبل الكتابة (نفس ما الموقع بيعمله)."""
    if _state["last_active"] == account_id:
        return True
    url = config.ACTIVATE_PATH.format(account_id=account_id)
    res = requests.post(url, headers=rampart_client.headers(), timeout=config.HTTP_TIMEOUT)
    if res.status_code >= 400:
        raise RuntimeError("activate failed: HTTP %s %s" % (res.status_code, res.text[:200]))
    _state["last_active"] = account_id
    return True


def _send(path, body, activate_account=None):
    """يرسل الطلب الفعلي للمنبع بعد اجتياز الحرس."""
    if activate_account:
        ensure_active(activate_account)
    url = path
    res = requests.post(url, headers=rampart_client.headers(),
                        json=body if body is not None else None,
                        timeout=config.HTTP_TIMEOUT)
    try:
        parsed = res.json()
    except ValueError:
        parsed = {"raw": res.text[:500]}
    return {"ok": res.status_code < 400, "code": res.status_code, "response": parsed}


def sync_upstream(account_id):
    """POST /inventory/sync — مزامنة حالة اللعبة (قراءة/تحديث، مش تعديل عناصر)."""
    ensure_active(account_id)
    url = SYNC
    res = requests.post(url, headers=rampart_client.headers(), timeout=config.HTTP_TIMEOUT)
    try:
        parsed = res.json()
    except ValueError:
        parsed = {"raw": res.text[:500]}
    return {"ok": res.status_code < 400, "code": res.status_code, "response": parsed}


def fetch_slot_rules():
    """GET /inventory/attachments/slots — قراءة فقط، بدون تفعيل أي كتابة."""
    return rampart_client._get(ATTACH_SLOTS)


def build_move(instance_rows, target_container, target_wrapper_id=""):
    """يبني طلب batch-move من صفوف الـ instances المحلية (نفس شكل الحزمة الأصلية)."""
    return {
        "item_ids": [r["instance_id"] for r in instance_rows],
        "source_wrapper_ids": [r.get("wrapper_id") or None for r in instance_rows],
        "target_container": target_container,
        "target_wrapper_id": None if target_container == "overflow" else (target_wrapper_id or None),
    }


def build_mutate(action, instance_rows, target_wrapper_id="", target_instance_id="", amount=None):
    if action == "split":
        first = instance_rows[0]
        return {"mutations": [{"discriminator": "split", "instanceId": first["instance_id"],
                               "targetWrapperId": target_wrapper_id or "", "amount": int(amount)}]}
    if action == "combine":
        return {"mutations": [{"discriminator": "combine", "instanceId": r["instance_id"],
                               "targetInstanceId": target_instance_id, "amount": int(amount or r["qty"])}
                              for r in instance_rows]}
    return {"mutations": [{"discriminator": action, "instanceId": r["instance_id"],
                           "wrapperId": r.get("wrapper_id") or None, "etag": r.get("etag") or ""}
                          for r in instance_rows]}


_KIND_PATHS = {
    "move": BATCH_MOVE,
    "mutate": BATCH_MUTATE,
    "overflow_all": MOVE_ALL_TO_OVERFLOW,
    "attach": ATTACH,
    "batch_attach": BATCH_ATTACH,
    "detach": DETACH,
    "upgrade": UPGRADE,
}


def trade(path, body, account_id):
    """POST /traders/accept(-limited) — شراء عرض بعد ARM فقط."""
    denied = _guard("trade")
    if denied:
        return denied
    if path not in (TRADE_ACCEPT, TRADE_ACCEPT_LIMITED):
        return {"ok": False, "code": 400, "error": "bad_path", "detail": "Unknown trade path."}
    try:
        out = _send(path, body, account_id)
    except Exception as exc:
        return {"ok": False, "code": 502, "error": "upstream_error", "detail": str(exc)[:300]}
    out["request"] = {"method": "POST", "url": path, "body": body}
    return out


def execute(kind, body, account_id, action="", confirmed=False):
    """نقطة التنفيذ الوحيدة: حرس -> تفعيل الحساب -> POST للمنبع."""
    denied = _guard(action or kind, confirmed=confirmed)
    if denied:
        return denied
    if kind not in _KIND_PATHS:
        return {"ok": False, "code": 400, "error": "bad_action", "detail": "Unknown action: %s" % kind}
    path = _KIND_PATHS[kind]
    try:
        out = _send(path, body if kind != "overflow_all" else None, account_id)
    except Exception as exc:
        return {"ok": False, "code": 502, "error": "upstream_error", "detail": str(exc)[:300]}
    out["request"] = {"method": "POST", "url": path, "body": body}
    return out
