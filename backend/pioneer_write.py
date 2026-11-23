"""تنفيذ النقل عبر بوابة Embark الرسمية — مع تحقق بعد الكتابة ورجوع عند الفشل.

المسار المثبت من بوابة اللعبة: POST /v1/pioneer/inventory/v1/mutate
النقل بيتم بتحديث خانات المخزن في طلب واحد (discriminator=update وamount مطلوب).
البوابة بترفض الطلب لو اتبعت معاه هيدر x-embark-request-id، وبتطلب
x-embark-manifest-id الحالي.

السرعة: الخطة كلها بتتحسب على قراءة شجرة واحدة، والحركات بتتلخّص لحالة نهائية
لكل خانة (لو عنصر خرج ورجع لنفس الخانة مش بنبعت حاجة ليها)، فطلب واحد بيكفي.
بعد الطلب بنقرأ الشجرة مرة واحدة للتحقق، وبنستخدم نفس الرد لتحديث الـ snapshot
بدل قراءة تانية. لو العناصر ما وصلتش، بنبعت الطلب العكسي ونرجّع الخانات لأصلها.

كل الداتا من GET /v1/pioneer/inventory مباشرة من البوابة الرسمية.
"""
import json
import os
import threading
import time
import uuid

import requests

from . import augments, config, gearops, pioneer_client as pc, pioneer_tree, repair_costs, store, weapon_tiers

_INV_CACHE = {}  # account -> {"ts": float, "data": dict, "tree": Tree}


def get_live_tree(account, max_age=15):
    """يعيد استخدام شجرة اتملت قرايتها قبل أقل من max_age ثانية بدل ما يدفع
    رحلة شبكة كاملة (مئات المللي ثانية) قبل كل نقلة."""
    now = time.time()
    cached = _INV_CACHE.get(account)
    if cached and (now - cached["ts"] < max_age) and cached.get("data") and cached.get("tree"):
        return cached["data"], cached["tree"]
    data = pc.fetch_inventory_for(account)
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    pioneer_tree.layout(tree)
    _INV_CACHE[account] = {"ts": now, "data": data, "tree": tree}
    return data, tree


def invalidate_live_cache(account=None):
    if account:
        _INV_CACHE.pop(account, None)
    else:
        _INV_CACHE.clear()

VERIFY_RETRIES = 2
VERIFY_WAIT = 0.2
# بولات ما بعد الطلب: البوابة بتطبّق الكتابة بعد لحظات. الفواصل متزايدة لكن مجموعها
# مساوي لمهلة القديم (0.8 × 3) — يعني نفس التسامح مع التطبيق المتأخر، بس كل بول
# قراءة واحدة بدل قراءتين، واللي بيتطبق بسرعة بيتلقط في أول بول بدل ما يستنى 0.8s.
VERIFY_POLL_WAITS = (0.2, 0.3, 0.5, 0.8, 1.2)
MUTATE_PATH = "/v1/pioneer/inventory/v1/mutate"
# مسار batch-operation: فتحته البوابة بعد 2026-11-03 لما mutate اتشال من الراوتر.
# الأسماء المقيسة لايف (حقل ناقص = INVALID_ARGUMENT، اسم عملية مخترع = UNKNOWN):
#   setParents {itemInstanceId, parentInstanceIds:[الخانة]}   ← النقل
#   moveAmount {fromInstanceId, toInstanceId, amount}         ← الوجهة معرّف رصة، مش أب:
#          معرّف جديد (نولّده إحنا) = تقسيم، ومعرّف رصة موجودة = دمج فيها
#          ومن غير setParents بعدها القطعة بتطلع في الأوفر ستاش
#   recycle {instanceId, amount} | scrap {instanceId, amount} | repair | upgrade
#          recycle مقيس 2026-11-06 بالخصاعة (حقل حقيقي بنوع غلط = UNKNOWN): مالوش
#          غير الحقلين دول — وamount شرط إلزامي. من غيره المنفّذ بيوصل للقطعة
#          (معرّف وهمي = 404) وبعدين بيرفض أي قطعة حقيقية بـ 400، فكل تفكيك كان
#          بيبان "مرفوض من اللعبة" وهو طلب ناقص من عندنا. مع amount الرصة بتمشي
#          من الستاش ومن الأوفر ستاش ومن القطع المجهّزة على حد سواء.
#          ومعاه: طلب batch فيه أكتر من قطعة = ذرّي، قطعة مرفوضة بتمتنع معها كلها.
#   repair {itemInstanceId, payment:{items:[{itemInstanceId, amount}]}}  ← مقيس 2026-11-06
#          بالخصاعة (حقل حقيقي بنوع غلط = UNKNOWN): أب repair مالوش غير الحقلين دول.
#          المشكلة إن المنفّذ بترفض كل طلب بنفس السطر (INVALID_ARGUMENT) حتى لمعرّف
#          غير موجود — بقية الأبواب بترد NOT_FOUND للمعرّف الوهمي. يعني الحارس بيموت
#          قبل ما يبص على القطعة أو الخامات: النوع مش مفعّل عندهم لحد دلوقتي.
#          مع ذلك بنبيعته (مش بنمنعه من عندنا) عشان يشتغل لوحده يوم ما يتفعّل،
#          وبنردّ رفضهم حرفي.
# والطلب atomic: عملية واحدة غلط بتمنع تنفيذ الطلب كله (متحقق لايف).
BATCH_PATH = "/v1/pioneer/v1/batch-operation"
BATCH_MOVE_OPS = ("setParents", "moveAmount", "recycle", "scrap", "repair", "upgrade")
# مسار ترقية السلاح في بوابة Embark — POST واحد بيزوّد درجة واحدة.
UPGRADE_PATH = "/v1/pioneer/inventory/upgrade"
# وجود الملف ده = تجميد كامل للكتابة على البوابة (الحساب بيستخدمه حد تاني الآن).
PAUSE_FILE = os.path.join(config.DATA_DIR, "writes_paused")
# حالة مسار الكتابة: البوابة بتشيله من راوترها وقت الصيانة وبترجّع 404 عادي.
ROUTE_STATE_FILE = os.path.join(config.DATA_DIR, "gateway_route_state.json")
ROUTE_PROBE_SECONDS = 60
# أسماء بديلة بتتفحص لو المسار الأساسي رجع راوتر-404: البوابة بتعيد تسجيل الكتابة باسم تاني.
ALT_MOVE_ENDPOINTS = ("/v1/pioneer/inventory/mutate", "/v1/pioneer/inventory/v1/move",
                      "/v1/pioneer/inventory/v1/batch", BATCH_PATH)
ROUTE_DOWN_DETAIL = (
    "Embark has taken the inventory write route off its gateway — the path itself answers "
    "\"404 page not found\" for every account, while reads still work. The only write surface "
    "left on that gateway is a gRPC service whose RBAC refuses this credential. So the block "
    "is their side, not the token, the manifest or this site. The site re-probes every minute "
    "and switches writes back on by itself the moment a move path is mounted again.")


class RouteNotMounted(pc.PioneerError):
    pass


class BatchUnsupported(pc.PioneerError):
    """الشكل القديم مطلوبه مش موجود على batch-operation (دمج/تقسيم/حذف)."""



def paused():
    return os.path.isfile(PAUSE_FILE)


def set_paused(on):
    if on:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(PAUSE_FILE, "w", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    else:
        try:
            os.remove(PAUSE_FILE)
        except OSError:
            pass
    return paused()


PAUSE_DETAIL = ("Writes are frozen: this account is in use right now — everything runs read-only. "
                "Say 009 when you are done so moves and attachments open again.")


def _pause_block():
    if not paused():
        return None
    return {"executed": False, "error": "write_paused", "code": 423, "detail": PAUSE_DETAIL}


def _endpoint():
    state = _read_route_state()
    if state.get("alive") and state.get("endpoint"):
        return state["endpoint"]          # اسم تم اكتشافه أخيراً أبقى هو المسار
    return config.PIONEER_MOVE_ENDPOINT or MUTATE_PATH


def _url():
    endpoint = _endpoint()
    return endpoint if endpoint.startswith("http") else pc.BASE + endpoint


def _read_route_state():
    try:
        with open(ROUTE_STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_route_state(alive, detail="", endpoint=None):
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        tmp = ROUTE_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"alive": bool(alive), "checked_at": int(time.time()),
                       "endpoint": endpoint or _endpoint(), "detail": str(detail)[:200]}, fh, indent=2)
        # الكتابة ذرية: الموقع والعامل المؤجل بيكتبوا نفس الملف، والقراءة النصفة
        # كانت بترجع {} فـ _endpoint() يقع للافتراضي (mutate) والضبط يروح.
        os.replace(tmp, ROUTE_STATE_FILE)
    except OSError:
        pass
    return bool(alive)


def _probe_once(token, url):
    """Is that exact path registered on the router right now?

    The router answers the plain Go \"404 page not found\" only for a path it never
    registered; a registered handler answers 400/412 to an empty mutation list, and an
    empty list cannot move anything. A network failure is not a verdict."""
    body = {"operations": []} if url.rstrip("/").endswith(BATCH_PATH) else {"mutations": []}
    try:
        resp = requests.post(url, headers=pc.headers(token, pc.load_manifest()),
                             json=body, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        return None, "network: %s" % type(exc).__name__
    if resp.status_code in (401, 403):
        # the credential was refused before routing — says nothing about the path
        return None, "HTTP %s: token refused, route unknown" % resp.status_code
    gone = resp.status_code == 404 and "404 page not found" in resp.text
    return (not gone), ("HTTP %s %s" % (resp.status_code, resp.text[:120]))


def probe_route(token):
    """المسار الأساسي الأول، ولو الراوتر قال 404 بنجرّب الأسماء البديلة نفس اللحظة."""
    alive, detail = _probe_once(token, _url())
    if alive is None or alive:
        return alive, detail
    for alt in ALT_MOVE_ENDPOINTS:
        ok, msg = _probe_once(token, pc.BASE + alt)
        if ok:
            detail = "%s -> %s | old %s: %s" % (alt, msg[:110], _endpoint(), detail[:60])
            _write_route_state(True, detail, endpoint=alt)   # بنثبّت الاسم الجديد كمسار الكتابة
            return True, detail
    return False, detail


def route_alive(token=""):
    """Cached route check — the gateway is only asked once every ROUTE_PROBE_SECONDS.

    With no verdict (no token, network down, credential refused) an account that has
    never been judged stays allowed, so a read failure never blocks writes falsely."""
    state = _read_route_state()
    if time.time() - int(state.get("checked_at") or 0) < ROUTE_PROBE_SECONDS:
        return bool(state.get("alive"))
    unknown = "alive" not in state
    token = token or pc.account_token()
    if not token:
        return unknown or bool(state.get("alive"))
    alive, detail = probe_route(token)
    if alive is None:
        return unknown or bool(state.get("alive"))
    return _write_route_state(alive, detail)


def batch_route():
    """المسار المثبت دلوقتي هو batch-operation؟ (الكتابة بتتحول لأوامر عمليات)."""
    return _endpoint().rstrip("/").endswith(BATCH_PATH)


def to_operations(mutations):
    """تحويل جسم mutate القديم (حالة خانات) لأوامر batch-operation.

    الخانة عند البوابة دي بتتغير بأب القطعة نفسها — مش بقائمة أطفال الخانة —
    فكل update لخانة بيبيرن setParents لكل قطعة مفروض تقع فيها. أي شكل تاني
    (تغيير كمية رصة أو create/delete) مالوش مقابل على المسار ده: بنرجّعه في
    unsupported وما بنشبعش منه نص طلب.
    """
    ops, unsupported, seen = [], [], set()
    for mut in (mutations or []):
        kind = str((mut or {}).get("discriminator") or "")
        slots = (mut or {}).get("slots")
        iid = str((mut or {}).get("instanceId") or "")
        if kind == "update" and slots is not None:
            for kid in [str(k) for k in (slots or []) if k]:
                key = (kid, iid)
                if key in seen or not iid:
                    continue
                seen.add(key)
                ops.append({"discriminator": "setParents", "itemInstanceId": kid,
                            "parentInstanceIds": [iid]})
        elif kind == "recycle":
            ops.append({"discriminator": "recycle", "instanceId": iid,
                        "amount": int((mut or {}).get("amount") or 1)})
        elif kind == "scrap":
            ops.append({"discriminator": "scrap", "instanceId": iid,
                        "amount": int((mut or {}).get("amount") or 1)})
        elif kind == "upgrade":
            ops.append({"discriminator": "upgrade", "instanceId": iid})
        elif kind == "repair":
            ops.append({"discriminator": "repair", "itemInstanceId": iid,
                        "payment": {"items": (mut or {}).get("payment") or []}})
        elif kind == "moveAmount":
            # الوجهة معرّف رصة (جديد = تقسيم، موجود = دمج) — مش أب. مقيس لايف 2026-11-04:
            # الاسم الوحيد المقبول هو toInstanceId؛ toParentInstanceId بترد INVALID_ARGUMENT.
            ops.append({"discriminator": "moveAmount",
                        "fromInstanceId": str((mut or {}).get("fromInstanceId") or ""),
                        "toInstanceId": str((mut or {}).get("toInstanceId") or ""),
                        "amount": int((mut or {}).get("amount") or 0)})
        elif kind == "setParents":
            target = str((mut or {}).get("itemInstanceId") or iid or "")
            ops.append({"discriminator": "setParents", "itemInstanceId": target,
                        "parentInstanceIds": [str(p) for p in
                                              ((mut or {}).get("parentInstanceIds") or []) if p]})
        elif kind in ("delete", "create") or (kind == "update" and slots is None):
            unsupported.append(kind)
        else:
            unsupported.append(kind or "unknown")
    return ops, unsupported


def to_parent_ops(steps):
    """خطوات النقل النهائية → أوامر setParents، وبالأوفر ستاش كمان.

    قائمة أطفال الخانة مابتكتبش على المسار ده: الأب بتاع القطعة هو الحقيقة،
    فكل قطعة ليها أب في آخر خطوة بتتحط عنده، واللي أبها فاضي (الأوفر ستاش)
    بتتبعت بأب فاضي صريح — متحقق لايف: parentInstanceIds: [] بترجع 200
    والقطعة بتطلع عائمة في الشجرة زي ما اللعبة بتعملها.
    """
    final = {}
    for step in (steps or []):
        iid = str((step or {}).get("instance_id") or "")
        if iid:
            final[iid] = str((step or {}).get("target") or "")
    return [{"discriminator": "setParents", "itemInstanceId": iid,
             "parentInstanceIds": [parent] if parent else []}
            for iid, parent in final.items()]


def post_mutate(request, token):
    if not route_alive(token):
        raise RouteNotMounted("ROUTE_NOT_MOUNTED %s" % _endpoint())
    body = {k: v for k, v in (request or {}).items() if k != "steps"}
    converted = None
    if batch_route():
        steps = (request or {}).get("steps")
        if steps:
            ops = to_parent_ops(steps)
            unsupported = []
        else:
            ops, unsupported = to_operations((request or {}).get("mutations"))
        if unsupported:
            raise BatchUnsupported("BATCH_UNSUPPORTED %s" % ",".join(sorted(set(unsupported))))
        if not ops:
            return {"changeset": {"items": {"created": [], "updated": []}}}
        body = {"operations": ops}
        converted = {"from": "steps" if steps else "mutations",
                     "operations": len(ops)}
    try:
        response = pc.post_json(_url(), body, token=token)
    except pc.PioneerError as exc:
        if exc.__class__ is pc.PioneerError and "404 page not found" in str(exc):
            _write_route_state(False, str(exc))   # a real attempt confirms the verdict
        raise
    if converted:
        response = dict(response or {})
        response["batch"] = converted
    _write_route_state(True)
    return response


def route_state():
    state = _read_route_state()
    return {"alive": bool(state.get("alive")), "checked_at": int(state.get("checked_at") or 0),
            "endpoint": state.get("endpoint") or _endpoint(), "detail": state.get("detail") or ""}


def status():
    endpoint = _endpoint()
    route = route_state()
    batch = endpoint.rstrip("/").endswith(BATCH_PATH)
    return {
        "mode": "direct_gateway",
        "endpoint": endpoint,
        "route_style": "batch-operation" if batch else "mutate",
        "endpoint_configured": True,
        "endpoint_alive": bool(route["alive"]),
        "route_checked_at": route["checked_at"],
        "route_detail": route["detail"],
        "method": "POST",
        "verifies_after_write": True,
        "rolls_back_on_error": True,
        "blocked": [],
        "direct_mutations": list(DIRECT_MUTATIONS),
        "trade_buy": "/v1/pioneer/offers/accept",
        "detail": ("Moves run as setParents operations, and split/merge run as moveAmount operations "
                   "on the new batch route."
                   if batch else
                   "Moves are sent to the official gateway path, verified there, and the items are returned if it fails."),
    }


def _fetch_tree(account):
    data = pc.fetch_inventory_for(account)
    return pioneer_tree.Tree((data or {}).get("items") or [])


def _rows_from_slots(tree, slots):
    return [{"instance_id": slot["item"], "name": tree.name_of(slot["item"]),
             "qty": tree.amount(slot["item"]), "container": slot["container"]}
            for slot in slots if slot.get("item")]


def backpack_items(account):
    """محتوى الشنطة المفعّلة من الشجرة الرسمية — صفوف جاهزة للنقل للستاش."""
    tree = _fetch_tree(account)
    lay = pioneer_tree.layout(tree)
    for slot in lay["backpack"]["slots"]:
        slot.setdefault("container", "backpack")
    return _rows_from_slots(tree, lay["backpack"]["slots"])


def equipped_items(account):
    """محتوى خانات التجهيز (أسلحة/درع/كويك يوز/سيف بوكيت/أوجمنت) من الشجرة الرسمية."""
    tree = _fetch_tree(account)
    lay = pioneer_tree.layout(tree)
    slots = []
    for key, group in (lay["loadout"]["slots"] or {}).items():
        for slot in group:
            slot.setdefault("container", "loadout")
            slot.setdefault("slot", key)
            slots.append(slot)
    return _rows_from_slots(tree, slots)


def _log(conn, account, body, status_text, detail, count):
    """السجل بيفرق بين النقل (move:stash) وعمليات mutate المباشرة (recycle/scrap/...)."""
    label = (body or {}).get("target_container") or (body or {}).get("kind") or ""
    prefix = "move" if (body or {}).get("target_container") else "mutate"
    store.log_action(conn, account, "%s:%s" % (prefix, label),
                     body, status_text, detail, count)


def _refresh_data(conn, account, data):
    """تحديث الـ snapshot من رد التحقق نفسه — بدون GET إضافي."""
    from . import pioneer_sync, sync
    try:
        payload = pioneer_sync.build_payload(conn, account, data=data)
        return sync.ingest(conn, account, payload)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _gateway_error(exc, kind=""):
    text = str(exc)
    if "ROUTE_NOT_MOUNTED" in text:
        return {"error": "gateway_route_down", "code": 503, "detail": ROUTE_DOWN_DETAIL}
    if "BATCH_UNSUPPORTED" in text:
        names = text.split(" ", 1)[1] if " " in text else ""
        return {"error": "route_op_unsupported", "code": 503,
                "detail": ("The batch write route has no operation called %s — the operations it "
                           "takes are setParents, moveAmount, recycle, scrap, repair and upgrade. "
                           "Nothing was sent, so nothing changed."
                           % (names or "that request"))}
    if "INVALID_ARGUMENT" in text and kind == "repair":
        return {"error": "repair_not_live", "code": 400,
                "detail": ("The gateway refused the repair (INVALID_ARGUMENT). Its repair operation "
                           "refuses every request — even ones with ids that do not exist, where its "
                           "other operations answer NOT_FOUND — so the operation is not live there yet. "
                           "Repair it in the game for now; this site keeps sending the real request, "
                           "so it starts working the day they turn it on.")}
    if kind == "recycle" and "UNKNOWN" in text:
        return {"error": "recycle_no_recipe", "code": 400,
                "detail": ("The gateway has no disassembly for this item — it answers 500/UNKNOWN "
                           "for anything the game cannot take apart (blueprints, ammo, raw "
                           "materials, decor, cosmetics). Its literal reply: %s" % text[:160])}
    if "INVENTORY_ITEM_DELETE_FORBIDDEN" in text:
        return {"error": "delete_forbidden", "code": 403,
                "detail": "The gateway blocks deleting stash items from outside the game — final deletion happens only in the game."}
    if "INVENTORY_ITEM_ZERO_AMOUNT" in text:
        return {"error": "amount_required", "code": 400,
                "detail": "The gateway refuses to set an item quantity to zero — a stack that empties "
                          "must be removed with delete, not zeroed."}
    if kind == "split" and "UNKNOWN" in text:
        return {"error": "split_refused", "code": 400,
                "detail": "The gateway rejected the split request (reason=UNKNOWN) — this happens when the shape "
                          "of the create itself is refused (the asset number must arrive as a number, not text, and the id "
                          "must be brand new). Its literal reply: %s" % text[:160]}
    if "INVALID_ARGUMENT" in text:
        if kind == "combine":
            return {"error": "combine_refused", "code": 400,
                    "detail": "The gateway refused the quantity change (INVALID_ARGUMENT) — the destination stack "
                              "may be over its cap, or this item cannot be merged. Its literal reply: %s"
                              % text[:160]}
        if kind in DIRECT_LABELS:
            return {"error": "invalid_argument", "code": 400,
                    "detail": ("The gateway refused %s (INVALID_ARGUMENT) — the game itself does not allow it for "
                               "these pieces below, not a site problem. Its literal reply: %s"
                               % (DIRECT_LABELS[kind], text[:160]))}
        return {"error": "invalid_argument", "code": 400,
                "detail": ("The gateway refused the move (INVALID_ARGUMENT) — this piece is not allowed in the "
                           "destination cell. Try another cell. Its literal reply: %s" % text[:200])}
    if "MANIFEST" in text:
        return {"error": "manifest_expired", "code": 409,
                "detail": "The manifest number is outdated or rejected — update it from inspection/pioneer_manifest.py."}
    if "FAILED_PRECONDITION" in text:
        return {"error": "write_precondition", "code": 412, "detail": _precondition_detail()}
    if "404" in text or "405" in text:
        return {"error": "gateway_route_down", "code": 503, "detail": ROUTE_DOWN_DETAIL}
    return {"error": "gateway_error", "code": 502, "detail": text[:300]}


# الأنواع التانية اللي البوابة بتعرّفها (مقيسة لايف على حساب اختباري):
# recycle = تفكيك لمواد، scrap = إعدام لكرديت، repair = إصلاح بمواد، delete = حذف.
# delete بترفضه على عناصر الستاش (INVENTORY_ITEM_DELETE_FORBIDDEN) — بنبعته وبرّض رد
# المنبع حرفي في الواجهة بدل ما نمنعه من عندنا.
DIRECT_MUTATIONS = ("recycle", "scrap", "repair", "delete")
DIRECT_LABELS = {"recycle": "Disassemble", "scrap": "Destroy", "repair": "Repair", "delete": "Delete"}


def _gains(response, tree=None):
    """اللي طلع من العملية من الـ changeset نفسه (مواد/كرديت) — بالفرقة مش بالإجمالي.

    البوابة بترجّع amount الجديد للحاوية كلها، فبنقارنه بالشجرة قبل الطلب.
    خانات العناصر الفاضية (Item Slot/أي حاوية ليها slots) مش بتاعة عرض."""
    items = ((response or {}).get("changeset") or {}).get("items") or {}
    names = pioneer_tree.asset_names()
    out = []
    for row in items.get("updated") or []:
        if row.get("slots"):
            continue
        aid = str(row.get("gameAssetId"))
        nm = (names.get(aid) or {}).get("display_name") or ""
        if not nm or nm == "Item Slot":
            continue
        amount = int(row.get("amount") or 0)
        iid = str(row.get("instanceId") or "")
        was = int(((tree.by_id.get(iid) or {}) if tree else {}).get("amount") or 0)
        out.append({"asset_id": aid, "name": nm, "amount": amount,
                    "delta": (amount - was) if was else amount})
    return out


def _asset_totals(tree):
    totals = {}
    for node in (getattr(tree, "by_id", None) or {}).values():
        if node.get("slots"):
            continue
        aid = str(node.get("gameAssetId") or "")
        if aid:
            totals[aid] = totals.get(aid, 0) + int(node.get("amount") or 0)
    return totals


def _learn_recycle(before, after, response, live):
    """نتعلّم مواد إعادة التدوير من الشجرة نفسها، قبل وبعد التنفيذ.

    البوابة بتدي المواد إما كستاك جديد (created) أو بزيادة ستاك موجود (updated)،
    فالمفرق بين الشجرتين هو اللي بيدي الرقم الصح. بنعتبر بس العناصر اللي البوابة
    لمستها في الرد (غير خانات العرض)، وبنسجّل بس لما عنصر واحد هو اللي اتفكك
    والمفرق يقسّم بالظبط على حجم الستاك — أي حاجة تانية ما بنخمّنهاش."""
    if len(live) != 1:
        return None
    items = ((response or {}).get("changeset") or {}).get("items") or {}
    touched = set()
    for key in ("created", "updated"):
        for row in items.get(key) or []:
            if row.get("slots"):
                continue
            aid = str(row.get("gameAssetId") or "")
            if aid:
                touched.add(aid)
    if not touched:
        return None
    before_t, after_t = _asset_totals(before), _asset_totals(after)
    node = (before.by_id.get(live[0]) or {})
    own = str(node.get("gameAssetId") or "")
    stack = max(1, int(node.get("amount") or 1))
    yields = {}
    for aid in touched:
        if aid == own:
            continue
        delta = after_t.get(aid, 0) - before_t.get(aid, 0)
        if delta <= 0:
            continue
        if delta % stack:
            return None
        yields[aid] = delta // stack
    if not yields:
        return None
    name = (pioneer_tree.asset_names().get(own) or {}).get("display_name") or ""
    return own, yields, name


def save_recycle_yields(asset_id, yields, name=None):
    """يخزّن Materials اللي اتعلّمها عشان اللوحة تعرضها من غير ما تتكرّر التجربة."""
    if not asset_id or not yields:
        return False
    path = os.path.join(config.DATA_DIR, "recycle_yields.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    table = data.get("yields") or {}
    names = data.get("item_names") or {}
    changed = table.get(asset_id) != yields
    table[asset_id] = yields
    data["yields"] = table
    if name:
        names[asset_id] = name
        data["item_names"] = names
    meta = data.setdefault("meta", {})
    known = pioneer_tree.asset_names()
    for aid in yields:
        if str(aid) in meta:
            continue
        nm = (known.get(str(aid)) or {}).get("display_name") or ""
        if nm:
            meta[str(aid)] = {"name": nm, "image_filename": ""}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError:
        return False
    gearops.RECYCLE_FIELDS[asset_id] = yields
    gearops.RECYCLE_YIELDS[asset_id] = yields
    for aid in yields:
        gearops.RECYCLE_META.setdefault(str(aid), meta.get(str(aid)) or {})
    if name:
        gearops.RECYCLE_BY_NAME.setdefault(str(name).strip().lower(), asset_id)
    return changed or bool(name)


def _mutation(kind, iid, payment=None, amount=None):
    """جسم mutate القديم: recycle/scrap/upgrade بـ instanceId، والإصلاح بدفع صريح.

    recycle محتاج amount كمان (شرط إلزامي على batch-operation) — بنبعت كمية الرصة
    كلها عشان السلوك يفضل "فكّ البلاطة دي" زي ما النافذة بتعرضها."""
    mut = {"discriminator": kind, "instanceId": str(iid)}
    if amount is not None:
        mut["amount"] = int(amount)
    if payment is not None:
        mut["payment"] = payment
    return mut


def _stash_cells(tree):
    slots = (pioneer_tree.layout(tree).get("stash") or {}).get("slots") or []
    return {str(c["wrapper"]) if isinstance(c, dict) else str(c) for c in slots}


def _asset_name(asset_id):
    row = pioneer_tree.asset_names().get(str(asset_id)) or {}
    return (row.get("display_name") or row.get("game_asset_name") or "").strip()


def _repair_payment(tree, stash_cells, iid):
    """خطوط دفع الإصلاح — نفس التكلفة اللي النافذة بتعرضها، من خانات الستاش أولًا.

    بترجع (lines, missing) وmissing كل خامة ناقصة (asset_id, مطلوب, موجود). أرقامنا
    مقاسة من حسابه أو نموذج فئة، فاللي بيقرر التكلفة النهائية هو البوابة وقت التنفيذ.
    """
    node = tree.by_id.get(str(iid)) or {}
    aid = str(node.get("gameAssetId") or "")
    cost = repair_costs.cost_for(aid, {"asset_id": aid, "name": tree.name_of(iid)})
    lines, missing = [], []
    for mid, need in (cost.get("materials") or {}).items():
        need = int(need)
        pool = []
        for sid, n in tree.by_id.items():
            if str(n.get("gameAssetId") or "") != str(mid) or n.get("slots"):
                continue
            amount = int(n.get("amount") or 0)
            in_stash = str(tree.parent.get(sid) or "") in stash_cells
            pool.append((0 if in_stash else 1, -amount, amount, sid))
        pool.sort()
        got = 0
        for _flag, _neg, amount, sid in pool:
            if got >= need:
                break
            take = min(need - got, amount)
            if take > 0:
                lines.append({"itemInstanceId": sid, "amount": take})
                got += take
        if got < need:
            missing.append((mid, need, got))
    return lines, missing


def direct_mutate(conn, account, kind, instance_ids):
    """recycle/scrap/repair: طلب واحد على البوابة الرسمية + تحقق من الشجرة + تحديث محلي.

    العملية دي مابتقبلش تراجع: العنصر اللي اتفكك أو اتعدم راح فعلاً، فمفيش undo
    وبنقفل الاختيار على نسخ موجودة في الشجرة الحية بس."""
    if kind not in DIRECT_MUTATIONS:
        return {"executed": False, "error": "bad_action", "detail": "Unsupported action: %s" % kind}
    blocked = _pause_block()
    if blocked:
        return dict(blocked, kind=kind)
    ids = [str(i) for i in (instance_ids or []) if i]
    if not ids:
        return {"executed": False, "error": "nothing_selected", "detail": "No items selected."}
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "no_token",
                "detail": "No Embark token is saved for this account."}
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    live = [i for i in ids if i in tree.by_id]
    skipped = [i for i in ids if i not in tree.by_id]
    if not live:
        return {"executed": False, "error": "not_in_tree", "skipped": skipped,
                "detail": "These items are not in the current tree — press SYNC and try again."}
    payments = {}
    # recycle على batch-operation بياخد amount مع instanceId — بنبعت كمية الرصة كاملة.
    amounts = {i: tree.amount(i) for i in live} if kind == "recycle" else {}

    def send(ids_slice):
        body = {"mutations": [_mutation(kind, i, payments.get(i), amounts.get(i))
                              for i in ids_slice],
                "requestId": ""}
        return body, post_mutate(body, token)

    responses, refused = [], {}
    if kind == "repair":
        # الإصلاح على batch-operation محتاج الدفع صريحًا (أب Repair مفيش غير
        # itemInstanceId + payment). الخامات من خانات الستاش الأول، واللي ناقصة
        # بنتقالها بالاسم والكمية قبل ما نبعت أي حاجة.
        stash = _stash_cells(tree)
        for iid in list(live):
            asset_id = str((tree.by_id.get(str(iid)) or {}).get("gameAssetId") or "")
            if not repair_costs.cost_for(asset_id).get("known", False):
                refused[iid] = "Verified repair materials are unavailable; guessed payments are disabled."
                live.remove(iid)
                continue
            lines, missing = _repair_payment(tree, stash, iid)
            if missing:
                refused[iid] = "Missing %s." % ", ".join(
                    "%d× %s" % (need - got, _asset_name(mid) or mid) for mid, need, got in missing)
                live.remove(iid)
            else:
                payments[iid] = lines
        if not live:
            err = {"error": "materials_missing", "code": 400,
                   "detail": "The repair needs materials you do not have enough of in the stash.",
                   "items": _item_notes(tree, ids)}
            _log(conn, account, {"kind": kind, "ids": ids}, "failed", err, len(ids))
            return dict(err, executed=False, kind=kind, skipped=skipped,
                        refused=[{"instance_id": i, "item": n, "detail": refused[i]}
                                 for i, n in zip(sorted(refused), _item_notes(tree, sorted(refused)))])
    try:
        request, response = send(live)
        responses.append(response)
    except pc.PioneerError as exc:
        request = {"mutations": [_mutation(kind, i, payments.get(i), amounts.get(i))
                                 for i in live],
                   "requestId": ""}
        if len(live) == 1:
            err = _gateway_error(exc, kind)
            notes = _item_notes(tree, live)
            if notes:
                err["detail"] = "%s  [%s]" % (err.get("detail", ""), "; ".join(notes))
                err["items"] = notes
            _log(conn, account, {"kind": kind, "ids": live}, "failed", err, len(live))
            return dict(err, executed=False, kind=kind, skipped=skipped,
                        preview={"method": "POST", "url": _url(), "body": request})
        # طلب batch واحد ذرّي: قطعة واحدة مرفوضة بيمتنع معها الطلب كله، فاختيار
        # عشر قطع كان بيرجع "مفيش حاجة حصلت". هنا بنعزل: كل قطعة في طلب لوحدها،
        # واللي اللعبة بترفضها يتسجّل باسمها بدل ما يعطّل الباقي.
        codes = set()
        for iid in live:
            try:
                responses.append(send([iid])[1])
            except pc.PioneerError as one_exc:
                text = str(one_exc)
                if '"reason"' in text:
                    codes.add(text.split('"reason"')[-1].split('"')[-2])
                refused[iid] = (_gateway_error(one_exc, kind).get("detail") or text)[:200]
        if not responses:
            err = {"error": "all_refused", "code": 400,
                   "detail": ("%s was refused for every piece you picked%s — the game does not "
                              "allow it for these items themselves, not a site problem."
                              % (DIRECT_LABELS[kind],
                                 " (%s)" % "/".join(sorted(codes)[:2]) if codes else "")),
                   "items": _item_notes(tree, live)}
            _log(conn, account, {"kind": kind, "ids": live}, "failed", err, len(live))
            return dict(err, executed=False, kind=kind, skipped=skipped,
                        preview={"method": "POST", "url": _url(), "body": request})

    done = [i for i in live if i not in refused]

    # التحقق: recycle/scrap بيشيلوا النسخة، repair بيزوّد المتانة (اللعبة بتصلّح
    # جزء مش الكل، فالمحكي إن الرقم العالي بقى أعلى من اللي قبل الطلب).
    def settled(data):
        fresh = pioneer_tree.Tree((data or {}).get("items") or [])
        if kind == "repair":
            rows = [fresh.by_id.get(i) for i in done]
            return bool(rows) and all(
                r and float(r.get("durability") or 0) >
                float((tree.by_id.get(i) or {}).get("durability") or 0)
                for r, i in zip(rows, done))
        return all(i not in fresh.by_id for i in done)

    data_after, verified = None, False
    for attempt in range(VERIFY_RETRIES + 2):
        if attempt:
            time.sleep(VERIFY_WAIT * (attempt + 1))
        try:
            data_after = pc.fetch_inventory_for(account)
        except Exception:
            continue
        if settled(data_after):
            verified = True
            break
    refreshed = _refresh_data(conn, account, data_after) if data_after else None
    learned = None
    if kind == "recycle" and data_after and len(done) == 1:
        found = _learn_recycle(tree, pioneer_tree.Tree((data_after or {}).get("items") or []),
                               responses[0], done)
        if found:
            learned = save_recycle_yields(found[0], found[1], found[2])
    combined = responses[0] if responses else {}
    _log(conn, account, {"kind": kind, "ids": done, "refused": sorted(refused)},
         "executed" if (verified and not refused) else ("partial" if done else "failed"),
         combined, len(done))
    out = {"executed": bool(verified), "kind": kind, "changed": done, "skipped": skipped,
           "gained": [g for r in responses for g in _gains(r, tree)],
           "result": {"ok": True, "code": 200, "response": combined or {}},
           "verification": {"ok": bool(verified)}, "refreshed": refreshed,
           "learned_yields": bool(learned),
           "preview": {"method": "POST", "url": _url(), "body": request}}
    if refused:
        out["refused"] = [{"instance_id": i, "item": n, "detail": refused[i]}
                          for i, n in zip(sorted(refused), _item_notes(tree, sorted(refused)))]
        out["detail"] = ("%s ran for %d of the %d pieces you picked; the game refused %d of them "
                         "(listed with where each one sits)."
                         % (DIRECT_LABELS[kind], len(done), len(live), len(refused)))
    elif not verified:
        out["detail"] = ("%s was sent but the state did not appear in the tree — open the game and check the stash."
                         % DIRECT_LABELS[kind])
    return out


def _stack_amounts(tree, aid):
    """كل رصّات النوع ده: {instance_id: amount} — الحاويات مستثناة."""
    return {iid: int(node.get("amount") or 0) for iid, node in tree.by_id.items()
            if not node.get("slots") and str(node.get("gameAssetId") or "") == str(aid)}


def _refetch(account):
    """قراية تانية للشجرة بعد الكتابة، بنفس محاولات التحقق القديمة."""
    for attempt in range(VERIFY_RETRIES + 2):
        if attempt:
            time.sleep(VERIFY_WAIT * (attempt + 1))
        try:
            data = pc.fetch_inventory_for(account)
        except Exception:
            continue
        if data:
            return data
    return None


def _item_notes(tree, ids):
    """اسم القطعة ومكانها وحالتها — عشان رفض البوابة يتقال على القطعة، مش عليه هو."""
    notes = []
    for iid in ids:
        node = tree.by_id.get(str(iid)) or {}
        cell = str(tree.parent.get(str(iid)) or "")
        holder = str(tree.parent.get(cell) or "") or cell
        where = tree.label(holder) if holder else "the overflow stash"
        health = gearops.health_of({"durability": node.get("durability"),
                                    "max_durability": node.get("maxDurability"),
                                    "asset_id": str(node.get("gameAssetId") or ""),
                                    "quality_level": node.get("qualityLevel"),
                                    "name": tree.name_of(iid), "type": ""})
        if health["damaged"]:
            # المتانة كسر 0..1 عند البوابة — int() كان بيخلي أي قطعة باقية تقول 0%
            where += ", %d%% condition" % (100 * health["current"] // health["max"])
        notes.append("%s (%s)" % (tree.name_of(iid) or str(iid)[:8], where))
    return notes


def _split_cell(tree, src, target_wrapper=""):
    """الخانة اللي هتستلم الجزء المفصول: (الخانة، سبب المنع، ملاحظة بت说 بعد التقسيم).

    من غير setParents البوابة بتسيب القطعة الجديدة عائمة في الأوفر ستاش (مقيس لايف) —
    فالقسم الي مافيهوش خانة فاضية (ستاش 280/280) مش رفض: بنسيب القطعة تطلع في الأوفر
    زي اللعبة نفسها وبنقولهاله في note. المنع الحقيقي حالة واحدة: خانة هو اختارها
    بنفسه واتشغلت بين الضغط والتنفيذ.
    """
    cell = str(target_wrapper or "")
    if cell:
        if cell in tree.by_id and not tree.first_child(cell):
            return cell, "", ""
        return "", "The cell you picked is not empty any more — press SYNC and try again.", ""
    home = str(tree.parent.get(str(src)) or "")
    if not home:
        # المصدر نفسه عائم: القطعة الجديدة هتنزل جنبه في الأوفر، ومفيش خانة مطلوبة.
        return "", "", ""
    holder = str(tree.parent.get(home) or "") or home
    cells = tree.children(holder)
    for other in cells:
        if other != home and not tree.first_child(other):
            return str(other), "", ""
    return "", "", ("The %s is full (%d/%d), so the new piece goes to the overflow stash — "
                    "move it back to a cell when one frees up."
                    % ((tree.label(holder) or "section").lower(),
                       sum(1 for c in cells if tree.first_child(c)), len(cells)))


def _batch_split(conn, account, token, tree, src, take, target_wrapper="", into_cell=True,
                 dest_cell="", current_total=-1):
    """تقسيم على batch-operation: moveAmount تفصل الكمية في رصة جديدة، وsetParents تنزلها الخانة.

    مقيس لايف 2026-11-04 على حساب G18: الوجهة في moveAmount اسمها toInstanceId وهو معرّف
    الرصة الجديدة (نولّده ourselves — البوابة بتنفّذ بالمعرّف بتاعنا حرفيًا)، مش أب. من غير
    setParents القطعة بتطلع عائمة في الأوفر ستاش؛ وفي نفس الطلب البوابة بتقبل تمسك المعرّف
    اللي لسه اتعمل وتحطه في الخانة المطلوبة (متحقق: الأب = الخانة اللي طلبناها).

    into_cell=False for callers that move the piece themselves right after (the quantity
    card → backpack): no stash cell is wanted, so none is waited for and the request is
    the single moveAmount op — plus setParents straight to dest_cell when the caller
    has a free backpack cell (one batch instead of split-then-move).

    مقيس لايف 2026-11-14: moveAmount لرصة من عمليتين بيتنفّذ فعلاً، بس الرصة
    الجديدة بترجع من القراية بلا gameAssetId، فالتحقق القديم (القطعة لازم تظهر في رصّات
    النوع) كان بيعتبرها فاشلة ويرجّع 0 منقول. التحقق بقى على مستوى الرصّات نفسها.
    """
    node = tree.by_id.get(src) or {}
    qty = int(node.get("amount") or 0)
    aid = str(node.get("gameAssetId") or "")
    cell, why, note = ("", "", "") if not into_cell else _split_cell(tree, src, target_wrapper)
    if why:
        _log(conn, account, {"kind": "split", "ids": [src], "amount": take}, "blocked", why, 1)
        return {"executed": False, "error": "no_free_cell", "kind": "split", "detail": why}
    # خانة الشنطة اللي الطالب عايز القطعة فيها: اتشغلت من آخر قراية يبقى نسيبها
    # للحركة اللي بعد التقسيم بدل ما نبعت setParents لخانة مشغولة.
    landing = cell or str(dest_cell or "")
    if landing and (landing not in tree.by_id or tree.first_child(landing)):
        landing = ""
    before = {iid: int(n.get("amount") or 0) for iid, n in tree.by_id.items()}
    before_total = _asset_totals(tree).get(aid, 0)
    # الشجرة اللي الطالب قاس عليها: لو النوع اتغيّر من ساعتها (دمج/تقسيم تاني
    # ملحقش يبان) مبنكملش — كل حركة على النوع مشروط بالمبلغ ده.
    if current_total >= 0 and before_total != current_total:
        return {"executed": False, "error": "stale_total", "kind": "split",
                "detail": "The total of this type changed since the move started (%d now, %d expected) "
                          "— read the backpack again and retry." % (before_total, current_total)}
    piece_id = str(uuid.uuid4())
    ops = [{"discriminator": "moveAmount", "fromInstanceId": src,
            "toInstanceId": piece_id, "amount": take}]
    if landing:
        ops.append({"discriminator": "setParents", "itemInstanceId": piece_id,
                    "parentInstanceIds": [landing]})
    request = {"mutations": ops, "requestId": ""}
    try:
        response = post_mutate(request, token)
    except pc.PioneerError as exc:
        err = _gateway_error(exc, "split")
        _log(conn, account, {"kind": "split", "ids": [src], "amount": take}, "failed", err, 1)
        return dict(err, executed=False, kind="split", lost=False, total_before=before_total,
                    preview={"method": "POST", "url": _url(), "body": request})

    after = _refetch(account)
    fresh = pioneer_tree.Tree((after or {}).get("items") or [])
    now = {iid: int(n.get("amount") or 0) for iid, n in fresh.by_id.items()}
    new_ids = [i for i in now if i not in before]
    stacks_now = _stack_amounts(fresh, aid)
    total = _asset_totals(fresh).get(aid, 0)
    src_now = int((fresh.by_id.get(src) or {}).get("amount") or 0)
    piece_node = fresh.by_id.get(piece_id) or {}
    piece = int(piece_node.get("amount") or 0)
    piece_asset = str(piece_node.get("gameAssetId") or "")
    landed = str(fresh.parent.get(piece_id) or "")
    # التحقق: المصدر ناقص take، ومفيش قطعة تانية اتغيّر مكانها أو كميتها (البوابة
    # ساعات بتاخد الجزء من قطعة في الأوفر بدل ما تعمل رصة جديدة)، والقطعة الجديدة
    # بكمية take. الرصة الجديدة بترجع بلا gameAssetId في مجموع النوع فمش داخلة فيه.
    # الحاويات بتتغيّر بناتها من غير ما كميتها تتغير، فالمقارنة دايماً على مستواها
    # نفسها: الكمية + مكانها + نوعها.
    def _same(old, new):
        return (int(new.get("amount") or 0) == int(old.get("amount") or 0)
                and str(new.get("gameAssetId") or "") == str(old.get("gameAssetId") or ""))

    moved = set()
    for iid in set(before) | set(now):
        if iid in (src, piece_id):
            continue
        old = tree.by_id.get(iid) or {}
        new = fresh.by_id.get(iid) or {}
        if not _same(old, new):
            moved.add(iid)
        elif str(fresh.parent.get(iid) or "") != str(tree.parent.get(iid) or ""):
            # تنقّل من غير تغيّر كمية/نوع: لو أبوه اتغيّر لخانة اتملّت بالقطعة الجديدة
            # فده مش حركة حقيقية، أي حالة تانية تبقى قطعة اتنقلت.
            if str(old.get("gameAssetId") or "") == aid:
                moved.add(iid)
    same_total = not moved
    stacks_ok = same_total and src_now == qty - take
    created = piece_id if piece == take and stacks_ok and piece_asset in ("", aid) else ""
    # الرصة الجديدة بترجع بلا gameAssetId: خاصية شوفناها مع التقسيم بس، مش حصاد إعادة تدوير.
    if piece == take and stacks_ok and not piece_asset:
        same_total = True
    done = bool(created)
    refreshed = _refresh_data(conn, account, after) if after else None
    _log(conn, account, {"kind": "split", "ids": [src, created or piece_id], "amount": take},
         "executed" if done else ("loss" if not same_total else "partial"), response or {}, 1)
    out = {"executed": bool(done), "kind": "split", "amount": take, "same_total": same_total,
           "created": created, "cell": landed,
           "before": {"amount": qty, "total": before_total},
           "after": {"source": src_now, "piece": piece, "total": total,
                     "stacks": len(stacks_now)},
           "result": {"ok": True, "code": 200, "response": response or {}},
           "refreshed": refreshed, "lost": not same_total,
           "preview": {"method": "POST", "url": _url(), "body": request}}
    if done:
        out["detail"] = "The split ran on the batch route: %d + %d, and the type total stayed %d." % (
            src_now, take, before_total)
        if landing and landed == landing:
            out["detail"] += " The new piece is in %s." % (fresh.label(landing) or "the cell you picked")
        elif landed:
            out["detail"] += " The new piece is in %s." % (fresh.label(landed) or "its container")
        else:
            out["detail"] += " The new piece is in the overflow, ready to move."
        if note:
            out["detail"] += " " + note
    elif not same_total:
        out["detail"] = ("⚠️ The batch answered but the total of the type changed from %d to %d — close the site "
                         "and look at the stash inside the game before any other move." % (before_total, total))
    else:
        out["detail"] = ("The gateway replied OK but the tree does not show the split (source %d, new piece %s) "
                         "— open the game and check." % (src_now, piece))
    return out


def split_attempt(conn, account, instance_id, target_wrapper="", amount=1, cap=0, into_cell=True,
                  dest_cell="", current_total=-1):
    """تقسيم حقيقي على البوابة الرسمية: على batch-operation بـ moveAmount، وعلى مسار
    mutate القديم بـ update للمصدر + create للقطعة.

    مقيس لايف 2026-10-31 على حساب HEZRON (Advanced Electrical Components، السقف 5):
      • الشكل المقبول: [{"discriminator":"update","instanceId":المصدر,"amount":الباقي},
                        {"discriminator":"create","instanceId":<uuid من عندنا>,
                         "gameAssetId":<رقم>,"amount":المفصول}] → 200، والرصة الجديدة
        اتعملت بالآيدي اللي إحنا ولّدناه فعلاً (مش آيدي راجع من السيرفر).
      • `gameAssetId` لازم ينزل **رقما** زي ما البوابة بترجّعه؛ لو نص → 400 UNKNOWN.
      • من غير تحديد خانة البوابة بتحط الرصة الجديدة في أول خانة فاضية في الستاش.
      • لو ضفنا update للخانة الفاضية بـ slots = أطفالها + الآيدي الجديد بتقع في الخانة
        المطلوبة بالظبط (متحقق: الأب = الخانة اللي طلبناها).
      • الوحدات محفوظة زي الدمج بالظبط: 5 → 4 + 1 والمجموع 7 ثابت.
    """
    blocked = _pause_block()
    if blocked:
        return dict(blocked, kind="split")
    try:
        take = int(amount)
    except (TypeError, ValueError):
        take = 0
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "no_token", "kind": "split",
                "detail": "No Embark token is saved for this account."}
    data = pc.fetch_inventory_for(account) or {}
    tree = pioneer_tree.Tree(data.get("items") or [])
    src = str(instance_id or "")
    node = tree.by_id.get(src) or {}
    if not node:
        return {"executed": False, "error": "not_in_tree", "kind": "split",
                "detail": "The piece is not in the current tree — press SYNC and try again."}
    if node.get("slots"):
        return {"executed": False, "error": "not_a_stack", "kind": "split",
                "detail": "Splitting works on stacks only, not on containers."}
    qty = int(node.get("amount") or 0)
    if take < 1 or take >= qty:
        return {"executed": False, "error": "bad_amount", "kind": "split",
                "detail": "The quantity must be between 1 and %d (the whole stack is %d)." % (max(qty - 1, 0), qty)}
    raw_asset = node.get("gameAssetId")
    try:
        aid_int = int(raw_asset)
    except (TypeError, ValueError):
        return {"executed": False, "error": "bad_asset", "kind": "split",
                "detail": "We could not read the item's asset number from the tree — press SYNC and try again."}
    aid = str(raw_asset or "")
    if cap and take > int(cap):
        return {"executed": False, "error": "over_cap", "kind": "split",
                "detail": "The split quantity (%d) is larger than the stack cap (%d)." % (take, int(cap))}
    if batch_route():
        return _batch_split(conn, account, token, tree, src, take, target_wrapper, into_cell,
                            dest_cell)
    before_total = _asset_totals(tree).get(aid, 0)
    new_id = str(uuid.uuid4())
    mutations = [
        {"discriminator": "update", "instanceId": src, "amount": qty - take},
        {"discriminator": "create", "instanceId": new_id, "gameAssetId": aid_int, "amount": take},
    ]
    placed_in = ""
    if target_wrapper:
        cell = tree.by_id.get(str(target_wrapper)) or {}
        kids = [str(k) for k in (cell.get("slots") or []) if tree.by_id.get(str(k))]
        if cell and not kids:
            placed_in = str(target_wrapper)
            mutations.append({"discriminator": "update", "instanceId": placed_in,
                              "amount": 1, "slots": kids + [new_id]})
        # الخانة اتشالت أو اتملّت من آخر قراية: نسيب البوابة تحطها في أول خانة فاضية
    request = {"mutations": mutations, "requestId": ""}
    try:
        response = post_mutate(request, token)
    except pc.PioneerError as exc:
        err = _gateway_error(exc, "split")
        _log(conn, account, {"kind": "split", "ids": [src], "amount": take},
             "failed", err, 1)
        return dict(err, executed=False, kind="split", lost=False, total_before=before_total,
                    preview={"method": "POST", "url": _url(), "body": request})

    # قبول الطلب مش كفاية: لازم المصدر ينقص، الرصة الجديدة تظهر، والمجموع يفضل ثابت.
    after = None
    for attempt in range(VERIFY_RETRIES + 2):
        if attempt:
            time.sleep(VERIFY_WAIT * (attempt + 1))
        try:
            after = pc.fetch_inventory_for(account)
        except Exception:
            continue
        if after:
            break
    fresh = pioneer_tree.Tree((after or {}).get("items") or [])
    total = _asset_totals(fresh).get(aid, 0)
    src_amount = int((fresh.by_id.get(src) or {}).get("amount") or 0)
    new_amount = int((fresh.by_id.get(new_id) or {}).get("amount") or 0)
    landed = str(fresh.parent.get(new_id) or "") if new_id in fresh.by_id else ""
    same_total = total == before_total
    where_ok = (not placed_in) or landed == placed_in
    done = same_total and src_amount == qty - take and new_amount == take and where_ok
    stacks = sum(1 for n in fresh.by_id.values()
                 if str(n.get("gameAssetId") or "") == aid and not n.get("slots"))
    refreshed = _refresh_data(conn, account, after) if after else None
    _log(conn, account, {"kind": "split", "ids": [src, new_id], "amount": take},
         "executed" if done else ("loss" if not same_total else "partial"), response or {}, 1)
    out = {"executed": bool(done), "kind": "split", "amount": take, "same_total": same_total,
           "created": new_id, "cell": landed,
           "before": {"amount": qty, "total": before_total},
           "after": {"source": src_amount, "piece": new_amount, "total": total, "stacks": stacks},
           "result": {"ok": True, "code": 200, "response": response or {}},
           "refreshed": refreshed, "lost": not same_total,
           "preview": {"method": "POST", "url": _url(), "body": request}}
    if not same_total:
        out["detail"] = ("⚠️ The split executed but the total of the type changed from %d to %d — close the site "
                         "and look at the stash inside the game before any other move." % (before_total, total))
    elif done:
        out["detail"] = "The split ran on the official path: %d + %d." % (qty - take, take)
        if placed_in and landed == placed_in:
            out["detail"] += " The new piece is in the cell you picked."
        elif landed:
            out["detail"] += " The gateway placed it in the first empty cell."
    else:
        out["detail"] = ("The gateway replied OK but the tree does not show the split (total %d intact) — "
                         "open the game and check." % total)
    return out


def _batch_combine(conn, account, token, tree, src, tgt, take, src_qty, tgt_qty, aid):
    """دمج على batch-operation: moveAmount بنفس معرّف الرصة الهدف — فالبوابة تضيف عليها وتحذف المصدر.

    مقيس لايف 2026-11-04 على G18: toInstanceId لمعرّف رصة موجودة بيترجّع 200 والرصة الهدف
    بتزيد والمصدر بيتمسح من الـ changeset، والخانة اللي اتفرتجت بترجع slots:[""] لوحدها.
    التحقق من الشجرة هو اللي بيقرّر: الوجهة تزيد بالمفصول، والمصدر ياختفي (أو ينقص)،
    ومجموع النوع ثابت، ومفيش أي رصة جديدة اتعملت في الطريق.
    """
    before_total = _asset_totals(tree).get(aid, 0)
    request = {"mutations": [{"discriminator": "moveAmount", "fromInstanceId": src,
                              "toInstanceId": tgt, "amount": take}], "requestId": ""}
    try:
        response = post_mutate(request, token)
    except pc.PioneerError as exc:
        err = _gateway_error(exc, "combine")
        _log(conn, account, {"kind": "combine", "ids": [src, tgt], "amount": take},
             "failed", err, 1)
        return dict(err, executed=False, kind="combine", lost=False, total_before=before_total,
                    preview={"method": "POST", "url": _url(), "body": request})

    after = _refetch(account)
    fresh = pioneer_tree.Tree((after or {}).get("items") or [])
    total = _asset_totals(fresh).get(aid, 0)
    now = _stack_amounts(fresh, aid)
    new_ids = [i for i in now if i not in _stack_amounts(tree, aid)]
    tgt_now = int((fresh.by_id.get(tgt) or {}).get("amount") or 0)
    src_gone = src not in fresh.by_id
    src_now = 0 if src_gone else int((fresh.by_id.get(src) or {}).get("amount") or 0)
    same_total = total == before_total
    src_ok = src_gone if take == src_qty else src_now == src_qty - take
    done = same_total and tgt_now == tgt_qty + take and src_ok and not new_ids
    refreshed = _refresh_data(conn, account, after) if after else None
    _log(conn, account, {"kind": "combine", "ids": [src, tgt], "amount": take},
         "executed" if done else ("loss" if not same_total else "partial"), response or {}, 1)
    out = {"executed": bool(done), "kind": "combine", "amount": take, "same_total": same_total,
           "before": {"source": src_qty, "target": tgt_qty, "total": before_total},
           "after": {"source": src_now, "target": tgt_now, "total": total},
           "result": {"ok": True, "code": 200, "response": response or {}},
           "refreshed": refreshed, "lost": not same_total, "undone": False,
           "preview": {"method": "POST", "url": _url(), "body": request}}
    if done:
        out["detail"] = ("The merge ran on the batch route: %d + %d = %d in the destination stack, "
                         "and the type total stayed %d." % (tgt_qty, take, tgt_now, total))
    elif not same_total:
        out["detail"] = ("⚠️ The batch answered but the total of the type changed from %d to %d — close the site "
                         "and look at the stash inside the game before any other move." % (before_total, total))
    else:
        out["detail"] = ("The gateway replied OK but the tree does not show the merge (destination %d, source %d) "
                         "— open the game and check." % (tgt_now, src_now))
    return out


def combine_attempt(conn, account, instance_id, target_instance_id, amount=1, cap=0):
    """دمج حقيقي على البوابة الرسمية: على batch-operation بـ moveAmount لخانة الوجهة،
    وعلى مسار mutate القديم بـ update للهدف + delete/update للمصدر.

    مقيس لايف 2026-10-31 على ARC Alloy (11 + 1) بحساب HEZRON (RAIDER38830):
      • `{"discriminator":"combine", ...}` → 400 UNKNOWN — الاسم مش في قاموس Embark أصلاً
        (نفس ردّ أي اسم مخترع: merge/move/stack_merge/consolidate…). الـenum المقبول عندنا:
        update / delete / recycle / scrap / repair.
      • `update` على عقدة العنصر بنفس كميته → 200. بنفس العقدة بكمية مختلفة لوحدها → 400
        INVALID_ARGUMENT. تصفير كمية عنصر → 400 INVENTORY_ITEM_ZERO_AMOUNT.
      • **الشكل اللي اتقبل ونفّذ**: طلب واحد فيه زيادة كمية الهدف + تجهيز المصدر:
        [{"discriminator":"update","instanceId":الهدف,"amount":المجموع},
         {"discriminator":"delete","instanceId":المصدر}]   ← لما المصدر يفضى
        والنتيجة لايف: الهدف 11→12، المصدر اتشال، ومجموع النوع فضل 27 (مفيش نسخ ولا فقد).
        يعني البوابة بتطلب إن الوحدات تتحفظ جوه الطلب نفسه — وده اللي بيميزه عن الزيادة لوحدها.
      • ذاكرة اللعبة ما بتسيبش جسم الطلب فيها (مسح 7 جيجا بعد دمج حقيقي: صفر hits)، فالمسار
        ده متقيس من البوابة نفسها مش منقوش من حد.

    لو المصدر ماشيلش كله (take < src_qty) بننقصه بـ update بدل delete — نفس المبدأ، وده كمان
    متقيس لايف بنفس الحساب (ARC Alloy 15 → رصة 12 والسقف 15): الوجهة 12→15 والمصدر 15→12
    والمجموع 27 ثابت. يعني البوابة بتقبل أي زوج update بيحفظ الوحدات، مش الـ delete بالذات.
    """
    blocked = _pause_block()
    if blocked:
        return dict(blocked, kind="combine")
    src, tgt = str(instance_id or ""), str(target_instance_id or "")
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "no_token", "kind": "combine",
                "detail": "No Embark token is saved for this account."}
    if not src or not tgt or src == tgt:
        return {"executed": False, "error": "bad_request", "kind": "combine",
                "detail": "You must pick two different stacks to merge."}
    data = pc.fetch_inventory_for(account) or {}
    tree = pioneer_tree.Tree(data.get("items") or [])
    a, b = tree.by_id.get(src) or {}, tree.by_id.get(tgt) or {}
    if not a or not b:
        return {"executed": False, "error": "not_in_tree", "kind": "combine",
                "detail": "The two stacks are not in the current tree — press SYNC and try again."}
    if a.get("slots") or b.get("slots"):
        return {"executed": False, "error": "not_a_stack", "kind": "combine",
                "detail": "Merging happens between two stacks only, not between containers."}
    aid = str(a.get("gameAssetId") or "")
    if aid != str(b.get("gameAssetId") or ""):
        return {"executed": False, "error": "different_asset", "kind": "combine",
                "detail": "The two stacks are different types — there is no merge between them."}
    src_qty, tgt_qty = int(a.get("amount") or 0), int(b.get("amount") or 0)
    try:
        take = int(amount)
    except (TypeError, ValueError):
        take = src_qty          # من غير كمية محددة: املأ الوجهة لأقصى سعتها
    if cap:
        # سقف الرصة بيقدر يستقبل قد إيه: الفائض بيفضل في مكانه زي ما اللعبة بتعمل.
        take = min(take, src_qty, int(cap) - tgt_qty)
    else:
        take = min(take, src_qty)
    if take < 1:
        return {"executed": False, "error": "target_full", "kind": "combine",
                "detail": "The destination stack is full (%d of %s) — there is no room to receive." % (tgt_qty, cap or "?")}
    if batch_route():
        return _batch_combine(conn, account, token, tree, src, tgt, take, src_qty, tgt_qty, aid)
    before_total = _asset_totals(tree).get(aid, 0)
    mutations = [{"discriminator": "update", "instanceId": tgt, "amount": tgt_qty + take}]
    if take == src_qty:
        mutations.append({"discriminator": "delete", "instanceId": src})
    else:
        mutations.append({"discriminator": "update", "instanceId": src,
                          "amount": src_qty - take})
    request = {"mutations": mutations, "requestId": ""}
    try:
        response = post_mutate(request, token)
    except pc.PioneerError as exc:
        err = _gateway_error(exc, "combine")
        _log(conn, account, {"kind": "combine", "ids": [src, tgt], "amount": take},
             "failed", err, 1)
        return dict(err, executed=False, kind="combine", lost=False, total_before=before_total,
                    preview={"method": "POST", "url": _url(), "body": request})

    # قبول الطلب مش كفاية: لازم الوجهة تزيد والمصدر ينقص والمجموع يفضل ثابت.
    after = None
    for attempt in range(VERIFY_RETRIES + 2):
        if attempt:
            time.sleep(VERIFY_WAIT * (attempt + 1))
        try:
            after = pc.fetch_inventory_for(account)
        except Exception:
            continue
        if after:
            break
    fresh = pioneer_tree.Tree((after or {}).get("items") or [])
    total = _asset_totals(fresh).get(aid, 0)
    tgt_now = int((fresh.by_id.get(tgt) or {}).get("amount") or 0)
    src_gone = src not in fresh.by_id
    src_now = 0 if src_gone else int((fresh.by_id.get(src) or {}).get("amount") or 0)
    same_total = total == before_total
    src_ok = src_gone if take == src_qty else src_now == src_qty - take
    done = same_total and tgt_now == tgt_qty + take and src_ok
    refreshed = _refresh_data(conn, account, after) if after else None
    _log(conn, account, {"kind": "combine", "ids": [src, tgt], "amount": take},
         "executed" if done else ("loss" if not same_total else "partial"), response or {}, 1)
    out = {"executed": bool(done), "kind": "combine", "amount": take,
           "same_total": same_total,
           "before": {"source": src_qty, "target": tgt_qty, "total": before_total},
           "after": {"source": src_now, "target": tgt_now, "total": total},
           "result": {"ok": True, "code": 200, "response": response or {}},
           "refreshed": refreshed, "lost": not same_total,
           "preview": {"method": "POST", "url": _url(), "body": request}}
    if not same_total:
        out["detail"] = ("⚠️ The merge executed but the total of the type changed from %d to %d — close the site "
                         "and look at the stash inside the game before any other move." % (before_total, total))
    elif done:
        if take == src_qty:
            out["detail"] = "The merge ran on the official path: %d + %d = %d." % (src_qty, tgt_qty,
                                                                              tgt_now)
            out["undone"] = False   # المصدر اتشال بـ delete: مفيش مسار رسمي يرجّعه
        else:
            out["detail"] = ("The destination filled to its cap (%d → %d), and the remaining %d stayed where it was — "
                             "exactly what the game does." % (tgt_qty, tgt_now, src_now))
    else:
        out["detail"] = ("The gateway replied OK but the tree does not show the merge (total %d intact) — "
                         "open the game and check." % total)
    return out


def swap_items(conn, account, instance_id, target_instance_id):
    """تبديل مكان قطعتين في المخزن/الشنطة — كتابة حقيقية على مسار النقل المثبّت.

    التبديل بيتنفذ بتحديثات الخانات نفسها (discriminator=update) اللي بننقل بيها:
    كل خانة بتستلم قائمة عناصرها الجديدة بعد تبادل الآيدسات، فالبوابة مابتلمسش
    كمية ولا متانة — وده اللي بيخلّي العملية قابلة للتراجع بـ undo.cells.
    """
    blocked = _pause_block()
    if blocked:
        return dict(blocked, kind="swap")
    src, tgt = str(instance_id or ""), str(target_instance_id or "")
    if not src or not tgt or src == tgt:
        return {"executed": False, "error": "bad_request", "kind": "swap",
                "detail": "You must pick two different pieces to swap."}
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "no_token", "kind": "swap",
                "detail": "No Embark token is saved for this account."}
    tree = _fetch_tree(account)
    if src not in tree.by_id or tgt not in tree.by_id:
        return {"executed": False, "error": "not_in_tree", "kind": "swap",
                "detail": "One of the two pieces is not in the current tree — press SYNC and try again."}
    pa, pb = tree.parent.get(src), tree.parent.get(tgt)
    if not pa or not pb:
        return {"executed": False, "error": "no_cell", "kind": "swap",
                "detail": "Overflow has no cell on the gateway — swapping works only between stash or backpack cells."}
    if pa == pb:
        return {"executed": False, "error": "same_cell", "kind": "swap",
                "detail": "Both pieces are inside the same container — there is nothing to swap."}
    original = {pa: list(tree.kids.get(pa) or []), pb: list(tree.kids.get(pb) or [])}
    want = {pa: [tgt if k == src else k for k in original[pa]],
            pb: [src if k == tgt else k for k in original[pb]]}
    mutations = _state_mutations(tree, want)
    if not mutations:
        return {"executed": False, "error": "nothing_changed", "kind": "swap",
                "detail": "The cells really do hold these two pieces — there is nothing to swap."}
    request = {"mutations": mutations, "requestId": ""}
    response, err = _post(request, token)
    if err:
        _log(conn, account, {"kind": "swap", "ids": [src, tgt]}, "failed", err, 2)
        return dict(err, executed=False, kind="swap",
                    preview={"method": "POST", "url": _url(), "body": request})
    verified, fresh, data = _verify(account, {src: pb, tgt: pa})
    restored = False
    if not verified:
        back = _state_mutations(fresh, original)
        if back:
            _, rerr = _post({"mutations": back, "requestId": ""}, token)
            restored = rerr is None
    refreshed = _refresh_data(conn, account, data) if data else None
    _log(conn, account, {"kind": "swap", "ids": [src, tgt]},
         "executed" if verified else "partial", response or {}, 2)
    out = {"executed": bool(verified), "kind": "swap", "changed": [src, tgt],
           "cells": {"source": pa, "target": pb},
           "result": {"ok": True, "code": 200, "response": response or {}},
           "verification": {"ok": bool(verified)}, "restored": bool(restored),
           "refreshed": refreshed, "undo": {"cells": original},
           "preview": {"method": "POST", "url": _url(), "body": request}}
    if verified:
        out["detail"] = "Swap done: %s ↔ %s." % (tree.name_of(src), tree.name_of(tgt))
    else:
        out["detail"] = ("The swap was sent but did not appear in the tree%s."
                         % (" — the cells went back to their original state" if restored else ""))
    return out


def _upgrade_node(tree, instance_id):
    return tree.by_id.get(str(instance_id)) or {}


def _upgrade_error(exc):
    text = str(exc)
    if "INVENTORY_ITEM_NOT_FOUND" in text:
        return {"error": "not_in_tree", "code": 404,
                "detail": "This weapon is not in the current tree — press SYNC and try again."}
    if "INSUFFICIENT_FUNDS" in text:
        return {"error": "insufficient_materials", "code": 412,
                "detail": "The materials required for the upgrade are missing in the stash — the gateway refused the step."}
    if "MANIFEST" in text:
        return {"error": "manifest_expired", "code": 409,
                "detail": "The manifest number is outdated or rejected — the site re-reads it from the gateway "
                          "on its own; by hand: python inspection/pioneer_manifest.py --refresh."}
    if "FAILED_PRECONDITION" in text:
        return {"error": "write_precondition", "code": 412, "detail": _precondition_detail()}
    for code, msg in (("NOT_ENOUGH_MATERIALS", "The materials required for the upgrade are missing."),
                      ("INSUFFICIENT_MATERIALS", "The materials required for the upgrade are missing."),
                      ("MISSING_MATERIALS", "The materials required for the upgrade are missing."),
                      ("NOT_UPGRADABLE", "This item cannot be upgraded from outside the game."),
                      ("INVALID_ARGUMENT", "The gateway rejected the upgrade request (INVALID_ARGUMENT)."),
                      ("ETAG_MISMATCH", "The item revision changed — refresh and try again."),
                      ("ITEM_MODIFIED", "The item changed in the game — refresh and try again.")):
        if code in text:
            return {"error": code.lower(), "code": 400, "detail": msg}
    return {"error": "gateway_error", "code": 502, "detail": text[:300]}


def upgrade_item(conn, account, instance_id, target_level):
    """ترقية سلاح على بوابة Embark الرسمية: POST /v1/pioneer/inventory/upgrade.

    الطلب بياخد {instanceId, etag, requestId} — مفيش فل في الطلب: البوابة
    بترفع درجة واحدة في كل نداء. عشان نوصل لفل 4 بناديها مرة لكل درجة
    (زي ما اللعبة نفسها بتعمل)، وبين كل درجة بنقرأ الشجرة تاني عشان الـ etag
    الجديد والـ asset id الجديد.
    """
    blocked = _pause_block()
    if blocked:
        return dict(blocked, kind="upgrade")
    iid = str(instance_id or "")
    if not iid:
        return {"executed": False, "error": "nothing_selected", "detail": "No weapon selected."}
    target_level = int(target_level or 0)
    if target_level < 2 or target_level > 4:
        return {"executed": False, "error": "bad_target", "detail": "The requested tier must be between 2 and 4."}
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "no_token",
                "detail": "No Embark token is saved for this account."}

    try:
        data = pc.fetch_inventory_for(account) or {}
    except Exception as exc:
        return {"executed": False, "error": "fetch_failed", "detail": str(exc)[:200]}
    tree = pioneer_tree.Tree(data.get("items") or [])
    node = _upgrade_node(tree, iid)
    if not node:
        return {"executed": False, "error": "not_in_tree",
                "detail": "This weapon is not in the current tree — press SYNC and try again."}
    asset_id = str(node.get("gameAssetId") or "")
    family = weapon_tiers.family_of(asset_id)
    current = weapon_tiers.level_of_asset(asset_id)
    if not family or not current:
        return {"executed": False, "error": "not_upgradable",
                "detail": "This item is not a weapon known for upgrading."}
    if current >= target_level:
        return {"executed": False, "error": "max_level",
                "detail": "This weapon is already at the top tier (%s)." % weapon_tiers.name_for_level(family, current),
                "current": current, "target": current}

    steps, done, last_response = [], 0, None
    for level in range(current + 1, target_level + 1):
        body = {"instanceId": iid, "etag": str(node.get("etag") or ""),
                "requestId": str(uuid.uuid4())}
        try:
            response = pc.post_json(UPGRADE_PATH, body, token=token)
        except pc.PioneerError as exc:
            err = _upgrade_error(exc)
            _log(conn, account, {"kind": "upgrade", "instanceId": iid, "level": level},
                 "failed", err, level - current)
            return {"executed": False, "kind": "upgrade", "current": current + done,
                    "target": target_level, "steps": steps, "changed": [],
                    **err, "preview": {"method": "POST", "url": pc.BASE + UPGRADE_PATH, "body": body}}
        last_response = response
        steps.append({"level": level, "name": weapon_tiers.name_for_level(family, level), "ok": True})
        done += 1
        # البوابة ممكن تغيّر الـ instanceId مع تغيّر الأصل — بنلاقي العنصر تاني
        # بالـ asset المتوقع (من نفس الحاوية) ونكمل عليه.
        try:
            data = pc.fetch_inventory_for(account) or {}
        except Exception:
            break
        tree = pioneer_tree.Tree(data.get("items") or [])
        expected = weapon_tiers.asset_for_level(family, level)
        found = tree.by_id.get(iid) or {}
        if str(found.get("gameAssetId") or "") != expected and expected:
            parent = tree.parent.get(iid)
            candidates = [c for c in tree.by_id.values()
                          if str(c.get("gameAssetId") or "") == expected]
            same = [c for c in candidates if tree.parent.get(str(c.get("instanceId"))) == parent]
            pick = (same or candidates)
            if pick:
                found = pick[0]
                iid = str(found.get("instanceId") or iid)
        node = found
        if not node:
            break
        # البوابة بترفع درجة واحدة في كل نداء — لو رقّت أكتر كده يبقى هي اللي
        # بتروّح لأعلى درجة، فبنقف عند الدرجة اللي وصلناها.
        new_level = weapon_tiers.level_of_asset(node.get("gameAssetId"))
        if new_level and new_level != level:
            break

    final_asset = str(node.get("gameAssetId") or "")
    final_level = weapon_tiers.level_of_asset(final_asset)
    verified = bool(final_level) and final_level >= target_level
    refreshed = _refresh_data(conn, account, data)
    _log(conn, account, {"kind": "upgrade", "instanceId": iid, "target": target_level},
         "executed" if verified else "partial", {"level": final_level}, done)
    out = {"executed": bool(verified), "kind": "upgrade", "steps": steps, "done": done,
           "current": final_level or current, "target": target_level,
           "changed": [iid] if done else [], "result": {"ok": True, "code": 200,
                                                        "response": last_response or {}},
           "verification": {"ok": bool(verified), "level": final_level},
           "refreshed": refreshed,
           "preview": {"method": "POST", "url": pc.BASE + UPGRADE_PATH,
                       "body": {"instanceId": iid, "etag": "...", "requestId": "..."}}}
    if not verified:
        out["error"] = "partial"
        out["detail"] = ("The upgrade stopped at tier %s — the gateway refused the step after it."
                         % (weapon_tiers.name_for_level(family, final_level or current)))
    return out


def _precondition_detail():
    """412 على الكتابة معناها إن البوابة مش بتقبل الكتابات للحساب ده حالياً.

    بتتحقق الأول ليه قبل ما تتهم الحساب:
    - المانيفست القديم بعد ابديت: رقمه مختلف عن رقم البوابة الحي، أو طلبه هو نفسه
      بيرفض — ساعتها الاتهام صح والمحاولة اللي جاية بتجدّده وتنجح.
    - المانيفست سليم — يبقى الحارس اللي قبل الكتابة في البوابة هو اللي رافض
      (مقيس 2026-11-16 على G14: أي عملية كتابة 412 حتى setParents لنفس الخانة،
      والعمليات المجهولة بترد UNKNOWN زي العادي، والقراءة بنفس التوكن شغالة)."""
    saved = pc._read_json(pc.MANIFEST_FILE) or {}
    try:
        age_h = int((time.time() - int(saved.get("updated_at") or 0)) / 3600)
    except (TypeError, ValueError):
        age_h = 0
    saved_id = str(saved.get("manifest_id") or "")
    build = saved.get("build") or "?"
    try:
        live_id = pc.refetch_manifest()
    except (pc.PioneerError, requests.RequestException):
        live_id = ""
    if not live_id or live_id == saved_id:
        return ("The gateway refused the write for this account (FAILED_PRECONDITION). Reads work and the "
                "manifest number is current (%s — build %s, %d hours old), so it is not a stale manifest and "
                "not the token: gateway writes are closed for this account right now — that happens while it is "
                "open in a match or the launcher, or until Embark reopens them. Moves from here start working "
                "again by themselves when it does. If you have just updated the game and other accounts also "
                "refuse, refresh the manifest by hand: python inspection/pioneer_manifest.py --refresh"
                % (saved.get("manifest_id") or "?", saved.get("build") or "?", age_h))
    return ("The saved manifest number is outdated (%s -> %s). It has been refreshed to %s — try the same "
            "move again, it goes through now." % (saved_id or "?", live_id, live_id))


def _slots_payload(children):
    """البوابة بتفهم الخانة الفاضية كـ slots=[""] (زي ما اتأكد لايف)، مش []. """
    return list(children) if children else [""]


def _verify_once(account, expected, inside=None):
    """قراءة واحدة ومقارنة بالمتوقع — نفس شرط _verify من غير أي انتظار أو إعادة.

    inside = (الحاويات الي اللعبة بتقرأها، الخانات اللي لازم تكون جواها): اللعبة
    بتقرأ الحاويات دي وحدها، فالعنصر اللي يثبت في خانة برّاها يكون "ناجح" في الموقع
    ومختفي في الماتش — بنحسبه غير متحقق ونرجّعه لأصله.
    """
    data = None
    tree = pioneer_tree.Tree([])
    try:
        data = pc.fetch_inventory_for(account)
    except Exception:
        return False, tree, data
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    if not all(tree.parent.get(iid) == cell for iid, cell in expected.items()):
        return False, tree, data
    if inside:
        nodes, cells = inside
        if nodes and any(not any(pioneer_tree.in_subtree(tree, c, n) for n in nodes)
                         for c in cells):
            return False, tree, data
    return True, tree, data


def _verify(account, expected, inside=None):
    """يقرأ الشجرة ويتأكد إن كل عنصر في الخانة المتوقعة — محاولة فورية + إعادة واحدة."""
    ok, tree, data = _verify_once(account, expected, inside)
    if ok:
        return ok, tree, data
    time.sleep(VERIFY_WAIT)
    return _verify_once(account, expected, inside)


def _mutations_for(tree, original):
    """حالة نهائية لكل خانة اتلمست — الخانات اللي رجعت لحالتها الأصلية بتتشال."""
    out = []
    for cell, before in original.items():
        after = list(tree.kids.get(cell) or [])
        if after != before:
            out.append({"discriminator": "update", "instanceId": cell,
                        "slots": _slots_payload(after), "amount": tree.amount(cell)})
    return out


def _state_mutations(tree, target):
    """يجبر الخانات على حالة محددة (target: خانة -> آيدسات عناصرها).

    ده أساس الرجوع التلقائي وخطوة الـ undo: بنقارن الشجرة الحية بالحالة
    المسجلة ونبعت الفرق بس. الخانة اللي مش في الشجرة بتتخطى لأنها مابقتش
    موجودة (البوابة بترفض أي تحديث ليها).
    """
    out = {}
    for cell, kids in target.items():
        want = [str(i) for i in (kids or [])]
        if cell not in tree.by_id or list(tree.kids.get(cell) or []) == want:
            continue
        out[cell] = want
    return [{"discriminator": "update", "instanceId": cell, "slots": _slots_payload(kids),
             "amount": 0} for cell, kids in out.items()]


def _state_steps(tree, target):
    """نفس الفرق اللي بيعمله _state_mutations بس بصيغة خطوات، لمسار batch-operation.

    كل قطعة مفروض ترجع لخانة بتتبعت عندها، وكل قطعة شغّالة خانة ومالهاش مكان
    مسجل بتتسيب عائمة (أوفر ستاش) — زي ما slots:[""] كانت بتعمل على المسار القديم.
    """
    steps = []
    for cell, kids in target.items():
        if cell not in tree.by_id:
            continue
        want = [str(i) for i in (kids or [])]
        now = [str(k) for k in (tree.kids.get(cell) or [])]
        if now == want:
            continue
        steps.extend({"instance_id": iid, "source": cell, "target": ""}
                     for iid in now if iid not in want)
        steps.extend({"instance_id": iid,
                      "source": str(tree.parent.get(iid) or ""), "target": cell}
                     for iid in want if iid not in now)
    return steps


def _restore_request(tree, target):
    """طلب إرجاع حالة خانات: شكل المسار القديم + شكل batch مع بعض."""
    return {"mutations": _state_mutations(tree, target), "steps": _state_steps(tree, target),
            "requestId": ""}


def _post(request, token):
    blocked = _pause_block()
    if blocked:
        return None, blocked
    try:
        return post_mutate(request, token), None
    except pc.TokenExpired as exc:
        return None, {"error": "token_expired", "code": 401, "detail": str(exc)}
    except pc.PioneerError as exc:
        return None, _gateway_error(exc)
    except Exception as exc:
        return None, {"error": "network", "code": 502, "detail": str(exc)[:300]}


def _bag_rows(tree):
    """شنطة اللاعب بشكل أقسام: [{"key", "label", "cells": [(cell, item)], "container"}]."""
    try:
        lay = pioneer_tree.layout(tree)
    except pioneer_tree.TreeError:
        return []
    node = lay["loadout"]["node"]
    secs = {}
    for child in tree.children(node):
        key = pioneer_tree.slot_key(tree.label(child))
        if key:
            secs[key] = child
    out = []
    for key, label in SWAP_SECTIONS:
        slot = secs.get(key) or ""
        container = tree.first_child(slot) if slot else ""
        # الشنطة: الحاوية ("Looting Mk. 2 Backpack") جواها الخانات. أي قسم تاني
        # ماشي في اللوداوت: الحاوية نفسها شايلة الخانات (Quick Use Slot / Cooked
        # Food Slot ...) — ولو الخانات دي مابقتش موجودة بدلناها بخانة القسم.
        cells = [str(c) for c in (tree.kids.get(container) or [])]
        if key != "backpack":
            cells = [c for c in cells if pioneer_tree.slot_key(tree.label(c))]
        out.append({"key": key, "label": label, "cells": cells, "slot": slot,
                    "container": container})
    return out


def _holder_cells(tree, holder):
    return [str(c) for c in (tree.kids.get(holder) or [])] if holder else []


def _keep_slots(order, want, parents):
    """توزيع المحفوظ على خانات الحاوية: كل قطعة خانتها لو فاضية أو بقت خاصة بيها،
    والباقي على أقرب خانة فاضية — مفيش قطعتين على خانة واحدة."""
    slots = [""] * len(order)
    pending = []
    for iid in want:
        idx = order.index(str(parents.get(iid))) if str(parents.get(iid)) in order else -1
        if idx >= 0 and not slots[idx]:
            slots[idx] = iid
        else:
            pending.append((idx, iid))
    for idx, iid in pending:
        free = [p for p in range(len(order)) if not slots[p]]
        if not free:
            break
        slots[min(free, key=lambda p: (abs(p - idx) if idx >= 0 else p))] = iid
    return slots


def _packed_state(tree):
    """الشنطة قبل التبديل: [{key, label, container, cells, slots}] — الحاوية
    والخانات المسجلة والترتيب اللي القطع فيه، علشان نرجّع نفس الشكل بعدها."""
    state = []
    for row in _bag_rows(tree):
        cells = list(row["cells"])
        want = [tree.first_child(c) for c in cells if tree.first_child(c)]
        state.append({"key": row["key"], "label": row["label"],
                      "container": row["container"] or row["slot"],
                      "cells": cells, "slots": _keep_slots(cells, want, tree.parent)})
    return state


def _bag_items(tree):
    return [tree.first_child(c) for row in _bag_rows(tree) for c in row["cells"]
            if tree.first_child(c)]


def _packed_left(account, state):
    """قطع كانت في الشنطة قبل التبديل ولسه مش ظاهرة في الأقسام — بعد التبديل."""
    data = _refetch(account)
    if not data:
        return -1
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    live = set(_bag_items(tree))
    return sum(1 for row in state for iid in row["slots"] if iid and iid not in live)


def _pack_sync(conn, account, state):
    """إعادة نفس الشكل القديم في الحاوية الجديدة: خانة ورا خانة، والمليان اللي
    حاجز مكانه بيتنقل للأوفر الأول. بيرجع عدد الحركات اللي اتنفذت."""
    if not state:
        return 0
    data = _refetch(account)
    if not data:
        return 0
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    rows = {row["key"]: row for row in _bag_rows(tree)}
    moves = []
    for saved in state:
        row = rows.get(saved["key"]) or {}
        order = list(row.get("cells") or [])
        if not order and saved["container"] in tree.by_id:
            order = _holder_cells(tree, saved["container"])
        current = {c: (tree.first_child(c) or "") for c in order}
        for cell, iid in zip(order, saved["slots"]):
            if not iid or not cell or iid not in tree.by_id:
                continue
            if str(tree.parent.get(iid) or "") == cell:
                continue
            blocker = current.get(cell) or ""
            if blocker and blocker != iid and blocker in tree.by_id:
                moves.append({"target_container": "overflow", "instance_ids": [blocker]})
                current[cell] = ""
            moves.append({"target_container": "backpack", "target_wrapper_id": cell,
                          "instance_ids": [iid]})
            current[cell] = iid
    if not moves:
        return 0
    r = move_plan(conn, account, moves)
    return len(r.get("moved") or []) if r.get("executed") else 0


def _bag_state(tree):
    """القطعة روحت في أي حاوية، وهل هي نفسها الحاوية الي الخانة المجهّزة بتقرأها."""
    try:
        lay = pioneer_tree.layout(tree)
    except pioneer_tree.TreeError:
        return {}
    lo = lay.get("loadout") or {}
    return {"container": tree.label(lay["backpack"].get("container") or "") or "",
            "loadout": lo.get("name") or "",
            "mode": lo.get("mode") or "",
            "equipped": lo.get("equipped_name") or "",
            "pointed": bool(lo.get("pointed"))}


def move_plan(conn, account, moves):
    """ينفّذ خطة نقل كاملة (قائمة حركات) في طلب بوابة واحد.

    كل حركة = {target_container, target_wrapper_id, target_slot, instance_ids}.
    كلها بتتخطط على شجرة واحدة، والحركات المتتابعة بتشوف أثر اللي قبلها،
    فتبديل الأماكن مابيحتاجش طلبات وسيطة.
    """
    started = time.time()
    moves = [m for m in (moves or []) if m]
    preview = {"method": "POST", "url": _url(), "items": [], "endpoint_configured": True}
    blocked = _pause_block()
    if blocked:
        return {**blocked, "preview": preview}
    if not moves:
        return {"executed": False, "error": "nothing_selected", "code": 400,
                "detail": "No items match the selection.", "preview": preview}

    # تبديل الأوجمنت: خانات الشنطة/الاستخدام السريع/الآمن/الأوجمنت مربوطة بحاوية
    # الأوجمنت نفسها. البوابة ما بترجّعش اللي جواها لخاناته لما الأوجمنت الجديد
    # أصغر، فالقطع تتعلق في شجرة بعيدة عن الستاش والشنطة. بنفصل الخطوة لوحدها:
    # نقل الزائد للستاش على الشنطة القديمة، تبديل الأوجمنت، ثم إعادة شجرة جديدة
    # ونقل الباقي لخانات الشنطة الجديدة — مع فحص الإجمالي قبل وبعد.
    if any(str(m.get("target_slot") or "").lower() == "augment" for m in moves):
        aug = next(m for m in moves if str(m.get("target_slot") or "").lower() == "augment")
        carry = [str(i) for i in (aug.get("carry_instance_ids") or []) if i]
        if carry:
            # التحديد اللي كان في الأوفر/الستاش وقت اللبس بيدخل الشنطة الجديدة
            # بعد ما تلبس، وبالأولوية لخاناتها الفاضية.
            carry_in = [i for i in carry if str(i) not in (aug.get("instance_ids") or [])]
            if carry_in:
                slot = "backpack"
                moves = moves + [{"target_container": "loadout", "target_slot": slot,
                                  "target_wrapper_id": "", "instance_ids": carry_in}]
        extra = [m for m in moves if m is not aug]
        if extra:
            # لبس + تفحيت في نفس الضغطة: الشنطة تلبس الأول، والخانات الجديدة
            # بتتقرا بعدها، وبعدين الباقي بيتوزع عليها.
            return _wear_with_carry(conn, account, aug, extra, preview, started)
        return _augment_swap_run(conn, account, moves, preview, started)

    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": "No saved token for account %s — add it from the accounts page." % account,
                "preview": preview}

    return _move_run(conn, account, token, moves, preview, started)


# خانات الشنطة المربوطة بحاوية الأوجمنت — بتتبدل كلها لما الأوجمنت يتغيّر.
# أسماء الخانات بتحمل اسم الأوجمنت ("Tactical Mk. 2 Backpack Slot")، وشجرة كل
# أوجمنت بتفضل شايلة آخر محتوى ليها: تبديل الشنطة بيحوّل القراءة لمجموعة خانات
# تانية، فالأولانية للقسم المطابق في الحاوية القديمة نفسها، وبعدين لشجرة أوجمنت
# تانية بنفس الاسم، وبعدين لخانات اللوداوت الحي. الستاش آخر اختيار دايمًا.
SWAP_SECTIONS = (("backpack", "BACKPACK"), ("quick_use", "QUICK USE"),
                 ("safe_pocket", "SAFE POCKET"), ("augmented_slots", "AUGMENTED"))
SLOT_NEEDLES = {"backpack": ("backpack slot",), "quick_use": ("quick use",),
                "safe_pocket": ("safe pocket",), "augmented_slots": ("auxiliary",), "shield": ("shield slot",), "gun_1": ("weapon 1 slot",), "gun_2": ("weapon 2 slot",)}


def _norm(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _layout_cells(tree, lay):
    """خانات كل قسم من الحاوية الحية (شنطة/كويك يوز/آمن/أوجمنت) بالترتيب."""
    out = {key: [] for key, _label in SWAP_SECTIONS}
    for row in _bag_rows(tree):
        out[row["key"]] = [(c, tree.first_child(c) or "") for c in row["cells"]]
    return out


_GAME_KEYS = {"augmented_slots": "augmented_slots"}


def _subsection_cells(tree, node, key, into=None, direct=False):
    """خانات قسم واحد داخل حاوية أوجمنت: الشجرة نفسها، أو تفرّع جواها."""
    if into is not None:
        for c in tree.children(into):
            if (tree.label(c) or "").lower().find(SLOT_NEEDLES[key][0]) >= 0:
                return [(c, tree.first_child(c)) for c in tree.children(c)]
        return []
    needle = _GAME_KEYS.get(key, key)
    slot = tree.find_child(node, *SLOT_NEEDLES[needle])
    holder = (slot if direct else tree.first_child(slot)) if slot else ""
    cells = [c for c in (tree.kids.get(holder) or [])
             if direct and pioneer_tree.slot_key(tree.label(c))]
    if direct and not cells:
        return []
    return [(c, tree.first_child(c)) for c in (cells if direct else (tree.kids.get(holder) or []))]


def _augment_roots(tree, label):
    """كل الحاويات الي أسماؤها اسم الأوجمنت ده — الشجرة الحية النهارده وخدانها مسبقًا."""
    label = label or ""
    out = []
    for iid in (str(e["instanceId"]) for e in tree.items):
        if iid in out or iid == tree.label(iid):
            continue
        if label and tree.find_child(iid, "backpack slot") and _norm(tree.label(iid)) == _norm(label):
            out.append(iid)
    return out


def _excess_holders(tree, lay, augment_id):
    """حاويات الشنطة الحقيقية للأوجمنت ده — في اللوداوت الحالي أو في شجرته."""
    label = tree.name_of(augment_id) or ""
    return [tree.first_child(c) for c in (tree.kids.get(augment_id) or [])
            if "backpack" in (tree.label(c) or "").lower() and "slot" in (tree.label(c) or "").lower()
            and tree.first_child(c)]


def _freshest(tree, nodes, mine):
    """أكثر حاوية حديثة اللمس للأوجمنت ده، مع تقديم الحاوية الحية لو هي بنفس العمر."""
    best, best_score = "", (-1, -1)
    for rank, n in enumerate(nodes):
        filled = sum(1 for _c, i in _subsection_cells(tree, n, "backpack") if i)
        score = (tree.subtree_updated(n), 1 if n == mine else 0, filled, -rank)
        if score > best_score:
            best, best_score = n, score
    return best


def _cell_source(tree, lay, augment_id, key, augment_label):
    """من فين نقرا المحتوى الحقيقي لقسم واحد من الأوجمنت ده."""
    label = tree.name_of(augment_id) or augment_label or ""
    roots = _augment_roots(tree, label) if label else []
    mine = ((lay.get("loadout") or {}).get("node") or "")
    if mine and mine not in roots:
        roots.append(mine)
    for node in ([mine] if mine else []) + [r for r in roots if r != mine]:
        cells = _subsection_cells(tree, node, key, into=augment_id)
        if not cells:
            cells = _subsection_cells(tree, node, key)
        if any(i for _c, i in cells):
            return cells
    node = _freshest(tree, roots, mine) if roots else ""
    if node:
        return (_subsection_cells(tree, node, key, into=augment_id)
                or _subsection_cells(tree, node, key))
    return [("", "")]


def _spec_of(tree, augment_id):
    asset = str((tree.by_id.get(str(augment_id or "")) or {}).get("gameAssetId") or "")
    return augments.capacities(augments.resolve(asset))


def _section_ranges(tree, body, into=None):
    """[{"key","label","holder","cells"}] لكل قسم تحت حاوية أوجمنت.

    الخانات دي هي اللي البوابة بتقراها لما الأوجمنت يتلبس: خانة -> حاوية الحاجة
    ("Tactical Mk. 2 Backpack") -> خانات ("Item Slot") وكل خانة فيها قطعة.
    """
    out = []
    if not body:
        return out
    for key, label in SWAP_SECTIONS:
        slot = tree.find_child(body, *SLOT_NEEDLES[key])
        if not slot:
            continue
        holder = ""
        if into and into in tree.by_id:
            for c in tree.children(into):
                if (tree.label(c) or "").lower().find(SLOT_NEEDLES[key][0]) >= 0:
                    holder = c
                    break
        if not holder:
            holder = tree.first_child(slot) or ""
        cells = [str(c) for c in (tree.kids.get(holder) or [])]
        if key != "backpack":
            cells = [c for c in cells if pioneer_tree.slot_key(tree.label(c))]
        if cells:
            out.append({"key": key, "label": label, "holder": holder, "cells": cells})
    return out


def _home_section(tree, body, into):
    """خانات قسم واحد داخل أوجمنت محدد (اسمه يعرف من into هو نفس الأوجمنت)."""
    return [c for c in (tree.kids.get(into) or [])]


def _container_cells(tree, node):
    """محتويات حاوية أوجمنت بالترتيب: [(cell, item)] لكل خاناتها الحقيقية."""
    out = []
    for child in tree.children(node):
        key = pioneer_tree.slot_key(tree.label(child))
        if not key:
            continue
        holder = tree.first_child(child) or ""
        if key == "backpack":
            for c in tree.kids.get(holder) or []:
                out.append((key, str(c), tree.first_child(c) or ""))
        else:
            cells = [str(c) for c in (tree.kids.get(holder) or [])
                     if pioneer_tree.slot_key(tree.label(c))] or [holder]
            for c in cells:
                out.append((key, c, tree.first_child(c) or ""))
    return out


def _item_count(tree, node):
    return len([1 for _k, _c, i in _container_cells(tree, node) if i])


def _mirror_of(tree, augment_label, project=None):
    """حاوية الأوجمنت اللي لسه بتعرض محتواها المخبّي (نفس اسم الأوجمنت ده)."""
    want = _norm(augment_label or "")
    best, best_score = "", -1
    for node in _augment_roots(tree, augment_label or ""):
        if project is not None and node == project:
            continue
        filled = _item_count(tree, node)
        if filled > best_score:
            best, best_score = node, filled
    return best


def _swap_plan_impl(tree, lay, moves):
    """خطة التبديل: المحتوى بيتبع اللاعب للشنطة الجديدة، والخانة اللي مالهاش مكان
    بيفضل محتواها في شجرة الأوجمنت القديمة (مبيتمسحش) وبيتحرك للستاش بعدها.

    الأرقام اللي بتحدد: سعة كل قسم في الأوجمنت الجديد (أول {سعة} قطعة من ترتيب
    القسم القديم بتفضل)، وخانات الشنطة الجديدة نفسها اللي في الرد (اللي مابيسعهاش
    محتوى بيتحسب لنا في الزيادة).
    """
    target = next((m for m in moves if str(m.get("target_slot") or "").lower() == "augment"),
                  moves[0])
    wanted = [str(i) for i in (target.get("instance_ids") or []) if i]
    if str(target.get("target_container") or "").lower() != "loadout":
        raise pioneer_tree.TreeError(400, "bad_target", "An augment is worn in the AUGMENT cell only.")
    aug_slot = (lay.get("augment") or {}).get("wrapper") or ""
    wrapper = str((((lay["loadout"]["slots"] or {}).get("augment") or [{}])[0]).get("wrapper")
                  or aug_slot)
    if not wrapper or wrapper not in tree.by_id:
        return None, pioneer_tree.TreeError(400, "bad_slot",
                                            "The AUGMENT cell is not in the official stash.")
    new_aug = wanted[0] if wanted else ""
    if not new_aug or new_aug not in tree.by_id:
        raise pioneer_tree.TreeError(404, "unknown_instance", "That augment is not in the official stash.")
    old_aug = tree.first_child(wrapper)
    if old_aug in wanted:
        old_aug = ""
    if new_aug == old_aug:
        raise pioneer_tree.TreeError(409, "already_there",
                                     "That augment is already worn in the %s." % (tree.label(wrapper) or "AUGMENT"))
    old_label = ((lay.get("backpack") or {}).get("loadout") or "") if old_aug else ""
    live_cells = _layout_cells(tree, lay)
    old_spec = _spec_of(tree, old_aug)
    supplied = _merged_spec(_spec_of(tree, new_aug), _layout_cells(tree, lay))
    old_cells = {}
    for key, _label in SWAP_SECTIONS:
        old_cells[key] = _cell_source(tree, lay, old_aug, key, old_label) if old_aug \
            else live_cells[key]

    new_roots = _augment_roots(tree, tree.name_of(new_aug) or "")
    new_body = next((r for r in new_roots
                     if tree.find_child(r, "backpack slot")), "")
    new_sections = _section_ranges(tree, new_body)
    sec_cap = {}
    for sec in new_sections:
        sec_cap[sec["key"]] = max(int(supplied.get(sec["key"]) or 0), len(sec["cells"]))

    kept, evict, moved, carried, order, extra = {}, [], [], {}, [], {}
    seen_all = set()
    for key, label in SWAP_SECTIONS:
        capacity = int(sec_cap.get(key) or supplied.get(key) or 0)
        sec_cells = []
        sec = next((s for s in new_sections if s["key"] == key), None)
        if sec is not None:
            sec_cells = list(sec["cells"])
        seen, items = set(), []
        for c, i in list(live_cells[key]) + list(old_cells[key]):
            if i and i not in seen and i not in wanted and i not in seen_all:
                seen.add(i)
                items.append((c, i))
                seen_all.add(i)
        for pos, (cell, iid) in enumerate(items):
            if pos < capacity:
                kept.setdefault(key, []).append(iid)
                carried.setdefault(key, []).append(iid)
                order.append({"instance_id": iid, "sec": key, "index": pos,
                              "amount": int(tree.amount(iid) or 0)})
                continue
            evict.append(iid)
            moved.append({"instance_id": iid, "name": tree.name_of(iid), "qty": tree.amount(iid),
                          "from": cell, "from_label": label, "to": "", "to_label": "STASH",
                          "section": label})
    return {"tree": tree, "lay": lay, "live_cells": live_cells, "carried": carried,
            "wrapper": wrapper, "old_aug": old_aug, "new_aug": new_aug,
            "new_body": new_body, "new_sections": new_sections, "sec_cap": sec_cap,
            "supplied": supplied,
            "old_spec": _merged_spec(old_spec, old_cells), "new_spec": dict(supplied),
            "old_cells": old_cells, "kept": {k: v for k, v in kept.items()},
            "evict": evict, "moved": moved, "order": order}, None


def _swap_plan(tree, lay, moves):
    return _swap_plan_impl(tree, lay, moves)


def _merged_spec(spec, cells):
    """السعة المقروءة = مواصفات الأوجمنت أو أطول خانة فيها حاجة (زي loadouts.state)."""
    out = dict(spec)
    for key, _label in SWAP_SECTIONS:
        out[key] = max(int(spec.get(key) or 0), len([1 for _c, i in cells[key] if i]))
    return out


def _apply_swap(tree, plan):
    """تطبيق خطة التبديل على الشجرة في الذاكرة: كل قطعة محفوظة لخانتها بالترتيب."""
    slot = plan["wrapper"]
    tree.kids[slot] = [plan["new_aug"]]
    tree.parent[plan["new_aug"]] = slot
    for item, cell in _swap_home_cells(tree, plan).items():
        now = tree.parent.get(item) or ""
        if now and now == cell:
            continue
        if now and item in (tree.kids.get(now) or []):
            tree.kids[now] = [k for k in tree.kids[now] if k != item]
        if item not in (tree.kids.get(cell) or []):
            tree.kids.setdefault(cell, []).append(item)
        tree.parent[item] = cell
    return tree


def _swap_moves(tree, plan):
    """نقل القطع المحفوظة لخاناتها — على الشجرة المتوقعة بعد التبديل."""
    out = []
    for item in plan["order"]:
        sec = next((s for s in plan["new_sections"] if s["key"] == item["sec"]), None)
        if sec is None or item["index"] >= len(sec["cells"]):
            continue
        cell = sec["cells"][item["index"]]
        if tree.parent.get(item["instance_id"]) == cell:
            continue
        if item["sec"] == "backpack":
            out.append({"target_container": "backpack", "target_wrapper_id": cell,
                        "instance_ids": [item["instance_id"]]})
        else:
            out.append({"target_container": "loadout", "target_slot": item["sec"],
                        "target_wrapper_id": cell, "instance_ids": [item["instance_id"]]})
    return out


def _swap_home_cells(tree, plan):
    """الخانة اللي كل قطعة المفروض تقرا فيها في الأوجمنت الجديد."""
    out = {}
    for item in plan["order"]:
        sec = next((s for s in plan["new_sections"] if s["key"] == item["sec"]), None)
        if sec is not None and item["index"] < len(sec["cells"]):
            out[item["instance_id"]] = sec["cells"][item["index"]]
    return out


def _swap_settled(tree, plan):
    """التبديل اتم: الأوجمنت الجديد لابس، وكل قطعة محفوظة في خانتها."""
    if tree is None:
        return False
    if tree.first_child(plan["wrapper"]) != plan["new_aug"]:
        return False
    home = _swap_home_cells(tree, plan)
    return all(tree.parent.get(i) == c for i, c in home.items())


def _swap_lost(before, tree2, plan, landed):
    """قطع نقص إجماليها فعلاً: مش في الشجرة، أو كميتها اتغيرت.

    اللي وصل مع التبديل أو نزل الستاش بأمر مننا (landed) بيتخصم من المقارنة.
    """
    if tree2 is None:
        return [{"instance_id": iid, "name": "", "qty": q} for iid, q in before.items()]
    lost = []
    for iid, qty in before.items():
        after = int((tree2.by_id.get(iid) or {}).get("amount") or 0)
        if not tree2.by_id.get(iid):
            after = 0
        if after < qty:
            lost.append({"instance_id": iid, "name": tree2.name_of(iid), "qty": qty - after})
    return lost



def _swap_detail(out, plan):
    """جملة للمستخدم: اللي رجع للستاش، واللي فضل جوه، والمجموع ما نقصش."""
    new = plan["new_spec"]
    old = plan["old_spec"]
    parts = []
    shrunk = [label for key, label in SWAP_SECTIONS if int(new.get(key) or 0) < int(old.get(key) or 0)]
    if shrunk:
        parts.append("%s got smaller (%s)" % (" + ".join(shrunk), ", ".join(
            "%s %d -> %d" % (label, int(old.get(key) or 0), int(new.get(key) or 0))
            for key, label in SWAP_SECTIONS if label in shrunk)))
    if out.get("kept_count"):
        parts.append("%d item(s) are in the new bag" % out["kept_count"])
    if out.get("evicted"):
        parts.append("%d item(s) beyond its capacity stayed stored in the old bag's tree (%s)"
                     % (len(out["evicted"]), ", ".join(i["name"] for i in out["evicted"][:4])))
    head = "The augment was swapped and the bag content came with it" + (": " + "; ".join(parts) if parts else "")
    if out["executed"]:
        return head + ". Nothing was lost — the item count before and after is identical."
    if out.get("rollback", {}).get("ok"):
        return (head + ". The gateway did not finish the swap, so it was rolled back to the previous "
                "augment — nothing was lost.")
    names = ", ".join("%s x%d" % (r.get("name") or "piece", r["qty"]) for r in (out.get("lost") or [])[:4])
    return ("⚠️ The augment did not settle cleanly and the rollback did not complete (%s piece(s) "
            "missing from the tree%s). Stop and look at the stash inside the game before any other "
            "move." % (len(out.get("lost") or []), (" — " + names) if names else ""))


def _wait_swap(account, check, tree, rounds=6):
    """قراية جديدة لحد ما الحالة تتطابق — البوابة بتتأخر لحظات بعد الكتابة."""
    data = None
    for attempt in range(max(1, rounds)):
        if attempt:
            time.sleep(VERIFY_POLL_WAITS[min(attempt, len(VERIFY_POLL_WAITS)) - 1])
        data = _refetch(account)
        if not data:
            continue
        tree = pioneer_tree.Tree((data or {}).get("items") or [])
        if check(tree):
            return tree, data, True
    return tree, data, False


def _fallback_home(tree, plan, tree_now):
    """لما الحاوية الجديدة نفسها مابقاش لها أثر في الرد: بنكتب على خانات اللوداوت
    الحية بنفس الترتيب — ده نفس اللي بتعمله اللعبة لو الشجرة اتولّدت متأخرة."""
    moves = []
    home = {}
    live = _layout_cells(tree_now, pioneer_tree.layout(tree_now))
    for sec_key, ids in (plan.get("carried") or {}).items():
        cells = [c for c, _i in live.get(sec_key) or []]
        for pos, iid in enumerate(ids):
            if pos >= len(cells) or not cells[pos]:
                continue
            cell = cells[pos]
            if tree_now.parent.get(iid) == cell:
                continue
            if sec_key == "backpack":
                moves.append({"target_container": "backpack", "target_wrapper_id": cell,
                              "instance_ids": [iid]})
            else:
                moves.append({"target_container": "loadout", "target_slot": sec_key,
                              "target_wrapper_id": cell, "instance_ids": [iid]})
            home[iid] = cell
    return moves, home


def _empty_in(tree, container):
    try:
        lay = pioneer_tree.layout(tree)
    except pioneer_tree.TreeError:
        return []
    if container == "stash":
        cells = [str(c) for c in lay["stash"]["slots"]]
    elif container == "backpack":
        cells = [str(s["wrapper"] if isinstance(s, dict) else s) for s in lay["backpack"]["slots"]]
    else:
        return []
    return [c for c in cells if not tree.first_child(c)]


def _retry_after_refusal(conn, account, tree, plan, moves, slot_place, used, preview, started):
    """البوابة رفضت التبديل: بنكتب كل قطعة في خانتها لوحدها (خانات الأوجمنت
    الجديد بتتقري فاضية في المسودّة، ومتحتاجة تتشرط بمحتواها قبل أي طرد منها)."""
    if plan["wrapper"] in used:
        return None
    used.add(plan["wrapper"])
    token = pc.account_token(account)
    if not token:
        return None
    placed = 0
    for iid in [i for i in slot_place if i and i != plan["new_aug"]]:
        cell = _cell_of(tree, iid)
        if not cell or tree.first_child(cell) == iid:
            continue
        payload = {"mutations": [{"discriminator": "update", "instanceId": cell,
                                  "slots": _slots_payload([iid]),
                                  "amount": tree.amount(cell)}],
                   "steps": [], "requestId": ""}
        resp, perr = _post(payload, token)
        if perr or (resp or {}).get("error"):
            _log(conn, account, {"kind": "augment_swap_primer", "cell": cell}, "failed",
                 {"item": tree.name_of(iid), "error": (perr or {}).get("error")}, 1)
            continue
        tree.kids[cell] = [iid]
        tree.parent[iid] = cell
        placed += 1
    _log(conn, account, {"kind": "augment_swap_primer", "augment": plan["new_aug"]}, "executed",
         {"placed": placed}, placed)
    out = _augment_swap_run(conn, account, moves, dict(preview), started)
    if out.get("executed") and placed:
        out["detail"] = (out.get("detail") or "") + \
            " The new bag's own cells were empty in the draft, so each piece was written to its cell first and the swap finished."
    return out


def _augment_swap_run(conn, account, moves, preview, started):
    """تبديل الأوجمنت: نفس مسار اللعبة بالظبط — المحتوى بيتنقل مع اللاعب.

    1. البوابة بتتحقق من الخطة على الشجرة الحالية (Preview: هل الخانات سايبة،
       فيه مكان؟). لو مرفوض، الأوجمنت مابيتلمسش.
    2. نداء واحد: الخانة المجهّزة بتاخد الأوجمنت الجديد، وكل قطعة في حاوية
       الأوجمنت الجديد نفسها بتتنقل لخانتها في حاوية اللوداوت بنفس الترتيب
       (قطعة -> خانة، من غير طرد: الخانة الفاضية لازم تفضل فاضية في نفس النداء).
    3. قراية جديدة: لو الأوجمنت لسا ماشي بخطة الحاوية اللي قاعدة مسبقا (البوابة
       قرأت ردها القديم ومحستش بالتغيير لأن حاوية الأوجمنت بتربط بالمعرف، مش
       بالاسم)، القطع اللي موقعنا شايفها محفوظة ومش موجودة في خاناتها بتتنقل
       بالخلاصة: 동خة واحدة، قطعة -> خانة واحدة، مع نقل المحتوى القديم لخانات
       الشنطة الجديدة الفاضية (ده تحقق البوابة بيرفض الخانة المليانة في أي وضع).
    4. قياس: كل قطعة قبل التبديل لازم تكون في الشجرة بعديه بنفس الكمية. الزائد
       اللي مالوش خانة في الجديدة بيتبقى في شجرته (مش بيتكتب عليه) ومكانه
       بيتحسب في التقرير. أي نقص فعلي = رجوع كامل للأور (الأوجمنت القديم يلبس
       تاني، والمحتوى يرجع خاناته).
    """
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": "No saved token for account %s — add it from the accounts page." % account,
                "preview": preview}
    try:
        invalidate_live_cache(account)
        data, tree = get_live_tree(account, max_age=0)
        lay = pioneer_tree.layout(tree)
    except pc.TokenExpired as exc:
        return {"executed": False, "error": "token_expired", "code": 401, "detail": str(exc),
                "preview": preview}
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code, "detail": exc.detail,
                "preview": preview}
    except Exception as exc:
        return {"executed": False, "error": "gateway_error", "code": 502,
                "detail": str(exc)[:300], "preview": preview}

    try:
        plan, err = _swap_plan(tree, lay, moves)
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code, "detail": exc.detail,
                "preview": preview}
    if not plan:
        return {"executed": False, "error": err.error, "code": err.code, "detail": err.detail,
                "preview": preview}

    live_types = bool(_augment_cell_types(tree, plan["new_body"]))
    used = set()
    slot_place = []
    # اللبس/التبديل من غير حاجة تتنقل: القديم بيتشال، والشجرة الجديدة هي اللي
    # بتتقرو من دلوقتي — الفحص الاحتياطي القديم مالوش لازمة.
    def leaves(t):
        return {i: int(n.get("amount") or 0) for i, n in t.by_id.items() if not n.get("slots")}

    before_qty = leaves(tree)
    before_total = sum(before_qty.values())
    kept_count = len(plan["order"])
    home = _swap_home_cells(tree, plan)
    try:
        the_moves = _swap_moves(tree, plan)
    except Exception:
        the_moves = []
    preview["swap"] = {"augment": tree.name_of(plan["new_aug"]),
                       "container": tree.label(plan["new_body"]) if plan["new_body"] else "",
                       "sections": [{"key": s["key"], "cells": len(s["cells"])}
                                    for s in plan["new_sections"]],
                       "kept": kept_count, "extra": len(plan["evict"])}

    try:
        body, _dest, _moved, _lay = pioneer_tree.plan_move(
            tree, [plan["new_aug"]], "loadout", "augment", plan["wrapper"])
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code, "detail": exc.detail,
                "preview": preview}
    original = {plan["wrapper"]: [str(k) for k in (tree.kids.get(plan["wrapper"]) or [])]}
    steps = list(body["steps"])
    swapped = tree.copy()
    pioneer_tree.apply_steps(swapped, body["steps"])
    try:
        pioneer_tree.layout(swapped)
    except pioneer_tree.TreeError:
        pass
    send_moves = _swap_moves(swapped, plan)
    claimed = {plan["wrapper"]}
    for m in send_moves:
        cell = m.get("target_wrapper_id") or ""
        if cell in claimed:
            continue
        try:
            mb, _d, _mv, _l = pioneer_tree.plan_move(
                swapped, m["instance_ids"], m["target_container"], m.get("target_slot") or "", cell)
        except pioneer_tree.TreeError:
            continue
        for s in mb["steps"]:
            for c in (s.get("source"), s.get("target")):
                if c:
                    original.setdefault(c, [str(k) for k in (swapped.kids.get(c) or [])])
        steps.extend(mb["steps"])
        claimed.add(cell)
        slot_place.append(m["instance_ids"][0] if m.get("instance_ids") else "")
    # الخطوة لازم تطلع بصيغة "سايبة" (source/target نص) — المفتاح الغيابي
    # بيفرّق: {"source": "", "displaced": True} اتبعتت قبل كده واتقبلت في البوابة
    # من غير ما تتنفذ وردت فاضي (تبديل ظاهري لسه محتاج خلاصة تانية).
    payload = {"mutations": _mutations_for(swapped, original),
               "steps": [{"instance_id": st["instance_id"], "source": st.get("source") or "",
                          "target": st.get("target") or ""} for st in steps],
               "requestId": ""}
    preview["body"] = payload
    response, send_error = _post(payload, token)
    _log(conn, account, {"kind": "augment_swap", "augment": plan["new_aug"]},
         "sent" if not (send_error or (response or {}).get("error")) else "failed",
         response if isinstance(response, dict) else {}, len(steps))
    settled_note = ""
    if not send_error and not (response or {}).get("error"):
        touched = set()
        try:
            touched = {str(u.get("instanceId")) for u in
                       (((response or {}).get("changeset") or {}).get("items") or {}).get("updated") or []}
        except Exception:
            touched = set()
        if touched and plan["wrapper"] not in touched:
            # البوابة ردت من غير ما تلمس خانة الأوجمنت: النداء اتقبل واتنفذ الهيكل
            # بس الخانة ماسكة القديم. بنبعت الخانة لوحدها في طلب صغير ونتأكد.
            fix = {"mutations": [{"discriminator": "update", "instanceId": plan["wrapper"],
                                  "slots": _slots_payload([plan["new_aug"]]),
                                  "amount": tree.amount(plan["wrapper"])}],
                   "steps": [], "requestId": ""}
            _fx, _fe = _post(fix, token)
            settled_note = "slot retry: %s" % ((_fe or {}).get("error") or "sent")
    if send_error or (response or {}).get("error"):
        first = ((send_error or {}).get("detail") or str(response)[:300])
        blamed = _class_refused(tree, plan)
        if not blamed and live_types:
            # الأوجمنت مش ظاهر في المسودّة الحية: بنشرط المحتوى في خانات القسم
            # اللي عمره ما اتمسك (الاسم محفوظ) ونعيد المحاولة مرة.
            retried = _retry_after_refusal(conn, account, tree, plan, moves, slot_place,
                                           used, preview, started)
            if retried is not None:
                return retried
        if blamed:
            # القطعة في AUGMENTED من نوع مالوش خانة في الشنطة الجديدة: بتطلع
            # الأوفر وحدها والتبديل يتعاد — بدل ما الفشل يقع على سواد الشنطة.
            ok, why, moved = _evict_extra(conn, account, tree, blamed)
            if ok:
                retry_preview = dict(preview)
                out2 = _augment_swap_run(conn, account, moves, retry_preview, started)
                if out2.get("executed"):
                    out2["evicted"] = [{"instance_id": i, "name": tree.name_of(i),
                                        "qty": tree.amount(i),
                                        "why": "a class-specific AUGMENTED item with no cell in "
                                               "%s — it went to OVERFLOW" % (tree.name_of(plan["new_aug"]) or "the new bag")}
                                       for i in blamed]
                    names = ", ".join(i["name"] for i in out2["evicted"][:3])
                    out2["detail"] = (out2.get("detail") or "") + \
                        " %s stayed usable: its AUGMENTED slot has no matching cell in the new bag, so it went to OVERFLOW and the swap finished." % names
                    _log(conn, account, {"kind": "augment_swap_class_evict", "augment": plan["new_aug"]},
                         "executed", {"evicted": len(blamed), "first_refusal": first[:120]}, len(moved))
                    return out2
                return out2
            return {"executed": False, "error": "swap_pre_refused",
                    "detail": "Its AUGMENTED item did not fit the new bag and OVERFLOW refused it too "
                              "(%s) — nothing changed." % (why or "")[:200],
                    "preview": preview, "kept_count": kept_count, "evicted": [],
                    "before": {"augment": tree.name_of(plan["old_aug"]) or "", "total": before_total},
                    "rollback": {"attempted": False, "ok": True}}
        return {"executed": False,
                "error": (send_error or {}).get("error") or "swap_refused",
                "code": (send_error or {}).get("code") or 502,
                "detail": "The gateway refused the swap (%s) — the augment was not changed." % first,
                "preview": preview, "kept_count": kept_count, "evicted": [],
                "before": {"augment": tree.name_of(plan["old_aug"]) or "", "total": before_total},
                "rollback": {"attempted": False, "ok": True}}

    # 3) متابعة: القراية الجديدة بعد التبديل. القطع المحفوظة لازم تبان في خاناتها.
    restored = 0
    fallback_used = False
    tree2, data2, settled = _wait_swap(account, lambda t: _swap_settled(t, plan), None)
    if (tree2 is not None and settled is False):
        # الأوجمنت لابس بس القطع لسه شجرة الحاوية القديمة: الحاوية اللي في الرد
        # إذا بتعرض خانات (متناقضة مع الجدول) بنصحح لسعاتها، وبنكتب على الخانات
        # اللي الخريطة بقت تقرا منها بنفس ترتيب المحتوى.
        try:
            live2 = pioneer_tree.layout(tree2)
            now_secs = _section_ranges(tree2, (live2.get("loadout") or {}).get("node") or "")
            now_ids = [tree2.first_child(c) for s in now_secs for c in s["cells"]]
            carried_ids = [i["instance_id"] for i in plan["order"]]
            if now_ids and carried_ids and not any(i in now_ids for i in carried_ids):
                for sec in plan["new_sections"]:
                    got = next((s for s in now_secs if s["key"] == sec["key"]), None)
                    if got is not None:
                        plan["sec_cap"][sec["key"]] = len(got["cells"])
                fallback_used = True
                fb, fhome = _fallback_home(tree2, plan, tree2)
                home.update(fhome)
                if fb:
                    r = move_plan(conn, account, fb)
                    if r.get("executed"):
                        restored += len(r.get("moved") or [])
                tree2, data2, settled = _wait_swap(
                    account, lambda t: all(t.parent.get(i) == c
                                           for i, c in _swap_home_cells(t, plan).items()),
                    tree2, rounds=3)
        except pioneer_tree.TreeError:
            pass
    # المحتوى القديم (القطع الزايدة) اللي مالقاش خانة في الجديدة: مكانه شجرة
    # الأوجمنت القديم اللي اتنحى. مكان بيتحسب في التقرير، والقطع لسه شايفينها.

    bag_now = None
    if tree2 is not None:
        try:
            bag_now = _bag_state(tree2)
        except Exception:
            bag_now = None
    after_qty = leaves(tree2) if tree2 is not None else {}
    lost = _swap_lost(before_qty, tree2, plan, home)
    total_lost = sum(r["qty"] for r in lost)
    worn = ""
    try:
        if tree2 is not None:
            worn = ((pioneer_tree.layout(tree2).get("augment") or {}).get("item")) or ""
    except pioneer_tree.TreeError:
        worn = ""
    placed = {}
    if tree2 is not None:
        for iid, cell in home.items():
            placed[iid] = (str(tree2.parent.get(iid) or ""), cell)
    home_ok = sum(1 for now, want in placed.values() if now == want)
    _log(conn, account, {"kind": "augment_swap_settle"}, "executed",
         {"settled": bool(settled), "fallback": fallback_used, "home_ok": home_ok,
          "carried": len(plan["order"]), "note": settled_note}, len(steps))
    confirmed = bool(tree2 is not None and worn == plan["new_aug"] and total_lost == 0)
    rollback = {"attempted": False, "ok": True}
    if not confirmed:
        # رجوع: الأوجمنت القديم يرجع الخانة. المحتوى اللي كان في حاوية الجديد
        # قبل السواپ (زي ARC Alloy) لسه مكانه شجرته، والقطع اللي كانت بتتنقل
        # مابتتقفلش هنا — التحقق فوق بيقيس الكميات قبل وبعد لكل قطعة.
        fix = {"mutations": [{"discriminator": "update", "instanceId": plan["wrapper"],
                              "slots": _slots_payload([plan["old_aug"]]),
                              "amount": tree.amount(plan["wrapper"])}],
               "steps": [], "requestId": ""}
        _r, _re = _post(fix, token)
        _t3, _d3, ok = _wait_swap(
            account, lambda t: t.first_child(plan["wrapper"]) == plan["old_aug"], None, rounds=4)
        rollback = {"attempted": True, "ok": bool(ok), "error": (_re or {}).get("error")}
        if ok:
            data2 = _d3
            tree2 = _t3

    new_name = tree2.name_of(plan["new_aug"]) if tree2 is not None else tree.name_of(plan["new_aug"])
    invalidate_live_cache(account)
    refreshed = _refresh_data(conn, account, data2) if tree2 is not None else None
    out = {"executed": confirmed,
           "error": None if confirmed else ("swap_unconfirmed" if not lost else "swap_lost"),
           "code": 200 if confirmed else 502,
           "moved": plan["moved"],
           "evicted": [{"instance_id": iid, "name": tree.name_of(iid),
                        "qty": int(tree.amount(iid) or 0)} for iid in plan["evict"]],
           "kept_count": kept_count,
           "carried": len(plan["order"]),
           "restored": restored + home_ok if fallback_used else home_ok,
           "before": {"augment": tree.name_of(plan["old_aug"]) or "", "spec": plan["old_spec"],
                      "total": before_total},
           "after": {"augment": new_name, "spec": plan["new_spec"],
                     "total": sum(after_qty.values()) if tree2 is not None else None},
           "lost": lost, "misplaced": [], "rollback": rollback,
           "preview": preview, "bag": bag_now or {},
           "refreshed": refreshed, "result": {"ok": True, "code": (send_error or {}).get("code") or 200,
                                              "response": response or {}},
           "elapsed_ms": int((time.time() - started) * 1000)}
    out["detail"] = _swap_detail(out, plan)
    status = "executed" if confirmed else ("partial" if rollback.get("ok") else "loss")
    _log(conn, account, {"kind": "augment_swap", "augment": plan["new_aug"]},
         status, {"lost": total_lost, "evicted": len(plan["evict"]), "kept": kept_count,
                  "total_before": before_total, "total_after": out["after"]["total"],
                  "rollback": rollback}, len(steps))
    return out



def _shield_type(tree, iid):
    """نوع الدرع من اسم خانته أو اسمه (Light Shield Slot / Light Shield ...)."""
    cell = tree.parent.get(iid) or ""
    lab = ((tree.label(cell) or "") + " " + (tree.name_of(iid) or "")).lower()
    for kind in ("heavy", "medium", "light"):
        if kind in lab:
            return kind
    return ""


def _rig_body(tree, root):
    """جسم الشنطة اللي بيتنده عليه _augment_cell_types: ჩანა الشنطة أو خانات اللوداوت.

    الشنطة الطالعة من الأوفر مش ملبوسة، فمبتنزلش في شجرة اللوداوت وبيتقرا لها اسم
    بس — في الحالة دي مفيش خانات أوجمنت معروفة وبنفحص بالمقارنة بعد الرفض.
    """
    if not root or not tree.children(root):
        return ""
    if tree.find_child(root, "backpack slot") or root == ((pioneer_tree.layout(tree).get("augment") or {}).get("item") or ""):
        return root
    for node in tree.find_descendant(root, "backpack slot") or []:
        return node
    return ""


def _cell_of(tree, iid):
    """خانة القطعة من خانات القسم الحية — للأوجمنت الجديد كمان (القطعة اللي اسمها
    محفوظ في الحاوية Looting MK. 3 (Survivor) مالهاش سطر في الشجرة)."""
    try:
        for rows in _layout_cells(tree, pioneer_tree.layout(tree)).values():
            for cell, item in rows:
                if item == iid:
                    return cell
    except pioneer_tree.TreeError:
        pass
    return ""


def _augment_cell_types(tree, body):
    """(نوع الخانة، معرّفها) لكل خانة أوجمنت: Combat / Looting / Tactical / Utility ..."""
    out = []
    body = _rig_body(tree, body)
    if not body:
        return out
    for slot in tree.children(body):
        label = (tree.label(slot) or "").lower()
        if "auxiliary" not in label and "munitions" not in label:
            continue
        # النوع من اسم الخانة الوظيفية نفسها (Grenade/Healing/Trinket/Utility) أو
        # من كلمة الفئة (Combat/Looting/Tactical) لما تكون الخانة عامة.
        slot_type = _aux_label_type(label)
        for holder in tree.children(slot):
            words = _norm_words(tree.label(holder))
            if words and any(w in ("auxiliary", "backpack") for w in words[:2]) and len(words) <= 2:
                out.append((slot_type, holder, list((tree.by_id.get(holder) or {}).get("slots") or [])))
                continue
            for cell in tree.kids.get(holder) or []:
                out.append((_aux_label_type(tree.label(cell)) or slot_type, cell,
                            list((tree.by_id.get(cell) or {}).get("slots") or [])))
            if not tree.kids.get(holder):
                out.append((slot_type, holder, list((tree.by_id.get(holder) or {}).get("slots") or [])))
    return out


_AUX_WORDS = ("slot", "auxiliary", "backpack")


def _aux_label_type(label):
    """كلمة النوع في اسم خانة أوجمنت: Combat Mk. 2 Auxiliary Slot -> combat."""
    words = [w for w in _norm_words(label)]
    for kind in ("combat", "looting", "tactical"):
        if kind in words:
            return kind
    for w in words:
        if w not in _AUX_WORDS and not w.startswith("mk") and not w.isdigit():
            return w
    return ""


def _norm_words(text):
    out = []
    for ch in (text or "").lower():
        out.append(ch if ch.isalnum() else " ")
        continue
    return "".join(out).split()


def _aux_type_of(tree, iid):
    """نوع قطعة الأوجمنت: من اسم الخانة اللي قطعة الحاوية جواها أو من نوعها."""
    parent = tree.parent.get(iid) or ""
    for node in (parent, tree.parent.get(parent) or ""):
        label = (tree.label(node) or "").lower()
        for kind in ("combat", "looting", "tactical", "utility", "healing", "trinket", "grenade"):
            if kind in label:
                return kind
    return ""


# خانة أوجمنت ببتقبل فئة كاملة: Healing = أدوات طبية، Grenade = قنابل ووسايل
# قتال، Trinket = أدوات الغنيمة، Utility = أدوات التنقل. الاسم بيحدد الفئة لأن
# جدول القطع عنده حاجات الاتنين نوعهم "Quick Use".
_AUX_FAMILIES = {
    "healing": ("bandage", "defibrillator", "syringe", "adrenaline", "medkit", "mender",
                "stimulant", "surgical", "antiseptic", "herbal", "first aid"),
    "grenade": ("grenade", "mine", "launcher", "fireball", "explosive", "rocket",
                "seeker", "shrapnel", "impact", "tagging", "blast", "smoke", "blaze"),
    "trinket": ("coin", "key", "camera", "rangefinder", "projector", "shade plates",
                "barricade", "beacon", "deployable", "decoy", "drone", "trap"),
    "utility": ("zipline", "lure", "light stick", "brella", "binoculars", "scanner"),
}


def _aux_family(name):
    """فئة قطعة الأوجمنت من اسمها (Bandage -> healing، Smoke Grenade -> grenade)."""
    low = " " + (name or "").lower() + " "
    for family, words in _AUX_FAMILIES.items():
        if any(w in low for w in words):
            return family
    return ""


def _catalog_types(conn, account, ids):
    """اسم كل قطعة أوجمنت من جدول الرصص (الحسابات بتتسمّى فيه بالـ instance id)."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    try:
        rows = conn.execute("SELECT instance_id, name FROM instances WHERE account = ? "
                            "AND instance_id IN (%s)" % marks, [account] + list(ids)).fetchall()
    except Exception:
        return {}
    return {str(iid): (name or "") for iid, name in rows}


def _evict_extra(conn, account, tree, extra_ids):
    """إخراج قطع للأوفر — نفس أسلوب ما قبل التبديل. بيرجع (ok, detail, moved)."""
    ids = [i for i in extra_ids if i]
    if not ids:
        return True, "", []
    try:
        body, _dest, moved, _lay = pioneer_tree.plan_move(tree, ids, "overflow", "", "")
    except pioneer_tree.TreeError as exc:
        return False, exc.detail, []
    original = {}
    for step in body["steps"]:
        for cell in (step.get("source"), step.get("target")):
            if cell:
                original.setdefault(cell, list(tree.kids.get(cell) or []))
    payload = {"mutations": _mutations_for(tree, original), "steps": body["steps"], "requestId": ""}
    response, err = _post(payload, pc.account_token(account))
    if err or (response or {}).get("error"):
        return False, ((err or {}).get("detail") or str(response)[:200]), []
    pioneer_tree.apply_steps(tree, body["steps"])
    try:
        for step in body["steps"]:
            conn.execute("UPDATE instances SET container = ?, wrapper_id = ? WHERE account = ? AND instance_id = ?",
                         ("overflow", "", account, step["instance_id"]))
        conn.commit()
    except Exception:
        pass
    return True, "", moved


def _pre_swap_evict(conn, account, tree, aug_move):
    """اللي مش هيتسع في الشنطة الجديدة يطلع للأوفر قبل التبديل، والباقي يفضل في مكانه.

    الزيادة بس: كل قسم بيتاخد آخر قطعه بعد سعة الشنطة الجديدة (بترتيب الخانات)،
    والدرع الملبوس لو الشنطة الجديدة مابتدعمش نوعه، ومحتوى حاوية الأوجمنت الجديدة
    نفسها لو مالهاش خانة عندها. الشنطة القديمة نفسها مش بتتلمس هنا — التبديل بعده.
    """
    wanted = [str(i) for i in (aug_move.get("instance_ids") or []) if i]
    new_aug = wanted[0] if wanted else ""
    if not new_aug:
        return {"executed": True, "moved": [], "evicted": []}
    lay = pioneer_tree.layout(tree)
    old_aug = tree.first_child(lay["augment"].get("wrapper") or "") or ""
    new_spec = augments.resolve(str((tree.by_id.get(new_aug) or {}).get("gameAssetId") or ""))
    spec = augments.capacities(new_spec)
    spec["shield_compatibility"] = augments.shield_level(new_spec)

    live = _layout_cells(tree, lay)
    extra = []          # (instance_id, سبب)
    seen = set(wanted)
    # خانات الأوجمنت متخصصة: اللي جوه "Combat Mk. 2 Auxiliary" Item Slot بترفضه
    # الشنطة اللي خاناتها Grenade/Healing/Trinket/Utility. اللي مش من نفس التخصص
    # بيتشال لحاله للأوفر والتبديل بيكمل.
    new_types = set()
    new_root = next((r for r in _augment_roots(tree, tree.name_of(new_aug) or "")
                     if tree.find_child(r, "backpack slot")), "")
    for typ, _cell, _slots in _augment_cell_types(tree, new_root or new_aug):
        if typ:
            new_types.add(typ)
    for key, label in SWAP_SECTIONS:
        if key == "augmented_slots" and not int(spec.get("augmented") or 0):
            continue
        items = [i for _c, i in live.get(key) or [] if i and i not in seen and i not in (old_aug,)]
        cap = int(spec.get(key) or 0)
        # اللي بيفضل هو أول الخانات (اللي جاي من بره بتخرج في الآخر) — الزيادة
        # هي آخر القطع في ترتيب الخانات.
        extra_ids = items[cap:] if cap else items
        for iid in extra_ids:
            if iid in seen:
                continue
            seen.add(iid)
            extra.append((iid, "beyond the new bag's %s" % label.lower()))
        if key == "augmented_slots":
            kept_aug = [iid for iid in items[:cap] if iid not in seen]
            names = _catalog_types(conn, account, kept_aug)
            for iid in kept_aug:
                kind = _aux_family(names.get(iid) or tree.name_of(iid)) or _aux_type_of(tree, iid)
                if kind in new_types or not kind:
                    continue
                if iid in seen:
                    continue
                seen.add(iid)
                extra.append((iid, "a %s augment item has no cell in %s, so it went to OVERFLOW"
                              % (kind, tree.name_of(new_aug) or "the new bag")))
    for _c, i in live.get("shield") or []:
        if i and i not in seen:
            ok, why = augments.shield_supports(new_spec, _shield_type(tree, i))
            if not ok:
                seen.add(i)
                extra.append((i, why))
    for slot in ("strict", "restore"):
        for sec_key in [k for k, _l in SWAP_SECTIONS]:
            slot_id = tree.find_child(old_aug, "backpack slot") if sec_key == "backpack" else \
                tree.find_child(old_aug, *SLOT_NEEDLES[sec_key])
            if not slot_id:
                continue
            live_cells = _subsection_cells(tree, lay["loadout"]["node"], sec_key, direct=True)
            if sec_key != "augmented_slots":
                filled = [i for _c, i in live_cells if i]
                if slot == "strict" and len(filled) > int(spec.get(sec_key) or 0):
                    continue
                for i in filled:
                    if i in seen:
                        continue
                    seen.add(i)
                    extra.append((i, "stored in the new bag's own container"
                                  if sec_key != "backpack" else
                                  "a copy left in the new bag's own container"))
                continue
            holder = tree.first_child(slot_id) or ""
            for c in tree.kids.get(holder) or []:
                i = tree.first_child(c)
                if i and i not in seen and i not in wanted:
                    seen.add(i)
                    extra.append((i, "stored in the new bag's own container"))
    if not extra:
        return {"executed": True, "moved": [], "evicted": []}

    # الطلب الذرّي: قطعة واحدة مرفوضة بتمنع التلاتة. لو التخصص مش معروف من
    # شجرة الشنطة الجديدة، البوابة هي اللي بتقرر — بنعيد المحاولة قطعة قطعة
    # والمرفوض بيطلع لوحده ونكمل الباقي.
    ids = [i for i, _w in extra]
    preview = {"method": "POST", "url": _url(), "account": account, "items": []}
    token = pc.account_token(account)
    try:
        body, _dest, moved, _lay = pioneer_tree.plan_move(tree, ids, "overflow", "", "")
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "detail": exc.detail, "moved": [], "evicted": []}
    original = {}
    for step in body["steps"]:
        for cell in (step.get("source"), step.get("target")):
            if cell:
                original.setdefault(cell, list(tree.kids.get(cell) or []))
    payload = {"mutations": _mutations_for(tree, original), "steps": body["steps"], "requestId": ""}
    response, err = _post(payload, token)
    if err or (response or {}).get("error"):
        first_err = ((err or {}).get("detail") or str(response)[:200])
        if len(ids) < 2:
            return {"executed": False,
                    "error": (err or {}).get("error") or "swap_pre_refused",
                    "detail": "The gateway refused moving the excess to OVERFLOW (%s) — the bag was not changed."
                              % first_err,
                    "moved": [], "evicted": []}
        kept, moved, refused = [], [], []
        for iid in ids:
            ok, why, mv = _evict_extra(conn, account, tree, [iid])
            if ok:
                moved.extend(mv)
                kept.append(iid)
            else:
                refused.append((iid, why))
        if refused:
            return {"executed": False, "error": "swap_pre_refused",
                    "detail": "The gateway refused moving %s to OVERFLOW (%s) — the bag was not changed."
                              % (tree.name_of(refused[0][0]) or "an item", refused[0][1][:160]),
                    "moved": [], "evicted": []}
        extra = [(i, w) for i, w in extra if i in kept]
        _INV_CACHE[account] = {"ts": time.time(), "data": _INV_CACHE.get(account, {}).get("data"), "tree": tree}
        evicted = [{"instance_id": i, "name": tree.name_of(i), "qty": tree.amount(i), "why": w}
                   for i, w in extra]
        _log(conn, account, {"kind": "augment_swap_pre_evict", "augment": new_aug},
             "executed", {"evicted": len(extra), "first_refusal": first_err[:120]}, len(moved))
        return {"executed": True, "moved": moved, "evicted": evicted}
    pioneer_tree.apply_steps(tree, body["steps"])
    _INV_CACHE[account] = {"ts": time.time(), "data": _INV_CACHE.get(account, {}).get("data"), "tree": tree}
    try:
        for step in body["steps"]:
            conn.execute("UPDATE instances SET container = ?, wrapper_id = ? WHERE account = ? AND instance_id = ?",
                         ("overflow", "", account, step["instance_id"]))
        conn.commit()
    except Exception:
        pass
    evicted = [{"instance_id": i, "name": tree.name_of(i), "qty": tree.amount(i), "why": w}
               for i, w in extra]
    _log(conn, account, {"kind": "augment_swap_pre_evict", "augment": new_aug},
         "executed", {"evicted": len(extra)}, len(body["steps"]))
    return {"executed": True, "moved": moved, "evicted": evicted}


def _wear_with_carry(conn, account, aug, extra, preview, started):
    """الأوجمنت يلبس، وأول ما الشنطة الجديدة تبان في القراية الجديدة الباقي بيتحط
    فيها الخانات اللي البوابة بتقراها. أي قطعة ماتلاقيش مكان بتفضل زي ما كانت."""
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": "No saved token for account %s — add it from the accounts page." % account,
                "preview": preview}
    try:
        invalidate_live_cache(account)
        _data, tree = get_live_tree(account, max_age=0)
        for m in [aug] + extra:
            for iid in m.get("instance_ids") or []:
                if str(iid) not in tree.by_id:
                    raise pioneer_tree.TreeError(
                        404, "unknown_instance",
                        "That item is no longer in the official stash: %s" % iid)
    except pc.TokenExpired as exc:
        return {"executed": False, "error": "token_expired", "code": 401, "detail": str(exc),
                "preview": preview}
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code, "detail": exc.detail,
                "preview": preview}
    except Exception as exc:
        return {"executed": False, "error": "gateway_error", "code": 502,
                "detail": str(exc)[:300], "preview": preview}

    # 1) الزائد قبل التبديل: درع مش مدعوم أو قطعة فوق سعة الشنطة الجديدة بتطلع
    #    للأوفر على الشنطة القديمة — التبديل بيروح بقطعه اللي في مكانه بس.
    pre = {"executed": True, "moved": [], "evicted": []}
    try:
        pre = _pre_swap_evict(conn, account, tree, aug)
    except Exception as exc:
        pre = {"executed": False, "error": "pre_swap_failed", "detail": str(exc)[:300],
               "moved": [], "evicted": []}
    if not pre.get("executed"):
        return {"executed": False, "error": pre.get("error") or "pre_swap_failed",
                "code": 409, "detail": pre.get("detail") or "The swap was stopped before it started.",
                "preview": preview}

    put = _augment_swap_run(conn, account, [aug], preview, started)
    out = dict(put)
    out["wear"] = {"executed": bool(put.get("executed"))}
    out["moved"] = list(pre.get("moved") or []) + list(put.get("moved") or [])
    if not put.get("executed"):
        out["carry"] = {"executed": False, "moved": [], "failed": len(extra)}
        return out

    # الباقي بيبعت مع نفس الطلب: البوابة بتشوف أثر لبس الشنطة في نفس النداء.
    # لو رفضت (اللوداوت لسه القديم في قرايتها)، الباكدج هو المسار الجواني:
    # الحاوية الجافة في اللوداوت الحي هي اللي بتتقرو بعد اللبس، والباقي عليها.
    n = sum(len(m.get("instance_ids") or []) for m in extra)
    moved, failed, sent = [], 0, False
    for attempt in range(2):
        plan_tree = tree
        if attempt:
            time.sleep(VERIFY_POLL_WAITS[0])
            try:
                invalidate_live_cache(account)
                _d2, plan_tree = get_live_tree(account, max_age=0)
            except Exception:
                break
        try:
            r = _move_run(conn, account, token, extra, preview, started)
        except Exception:
            r = {"executed": False}
        if r.get("executed"):
            moved = r.get("moved") or []
            sent = True
            break
    if not sent and _plan_node(tree, "backpack"):
        # الخانات الخام: نفس المعرفات صالحة للكتابة حتى لو الرد لسه ما نزّلش
        # حاوية الشنطة، فالباقي بيتوزع على الخانات الفاضية بالترتيب.
        cells = [str(c) for c in (tree.kids.get(_plan_node(tree, "backpack")) or [])
                 if not tree.first_child(c)]
        ids = [i for m in extra for i in m.get("instance_ids") or []]
        if cells and ids:
            cell_moves = [{"target_container": "backpack", "target_slot": "", "target_wrapper_id": c,
                           "instance_ids": [i]} for c, i in zip(cells, ids)]
            try:
                r = _move_run(conn, account, token, cell_moves, preview, started)
            except Exception:
                r = {"executed": False}
            if r.get("executed"):
                moved = r.get("moved") or []
                sent = True
    if not sent:
        failed = n
    invalidate_live_cache(account)
    out["carry"] = {"executed": failed == 0, "moved": moved, "failed": failed}
    out["moved"] = list(put.get("moved") or []) + moved
    if failed:
        out["detail"] = (put.get("detail") or "") + \
            " %d item(s) had no free cell in the new bag and stayed where they were." % failed
    if pre.get("evicted"):
        names = ", ".join(i["name"] for i in pre["evicted"][:4])
        out["detail"] = (out.get("detail") or "") + \
            " %d piece(s) beyond the new bag's capacity went to OVERFLOW first (%s)." % (
                len(pre["evicted"]), names)
    return out


def _restore_occupants(conn, account, tree, return_cells, token):
    """البوابة رفضت الطلب: القطع اللي اتخلعت للتبديل بترجع خاناتها في نفس الوقت."""
    moves = [{"target_container": "loadout", "target_slot": _slot_key_of(tree, cell),
              "target_wrapper_id": cell, "instance_ids": [iid]}
             for iid, cell in return_cells.items() if cell in tree.by_id]
    if not moves:
        return {"attempted": False, "ok": True}
    ok = False
    try:
        r = _move_run(conn, account, token, moves, {"method": "POST", "url": _url(), "items": []},
                      time.time())
        ok = bool(r.get("executed"))
    except Exception:
        ok = False
    if not ok:
        # إعادة المحاولة كتابة مباشرة للخانات: القديم يرجع أب لخانته.
        steps, mutations = [], []
        for iid, cell in return_cells.items():
            if cell not in tree.by_id:
                continue
            steps.append({"instance_id": iid, "source": "", "target": cell})
            mutations.append({"discriminator": "update", "instanceId": cell,
                              "slots": [iid], "amount": tree.amount(cell)})
        resp, err = _post({"mutations": mutations, "steps": steps, "requestId": ""}, token)
        ok = not err and not (resp or {}).get("error")
    invalidate_live_cache(account)
    _log(conn, account, {"kind": "swap_restore", "ids": list(return_cells)},
         "executed" if ok else "failed", {"cells": list(return_cells.values())}, len(return_cells))
    return {"attempted": True, "ok": ok}


def _class_refused(tree, plan):
    """قطع الأوجمنت المشكوك فيها بعد فشل التبديل.

    البوابة بترفض النداء كله لما قطعة مش مسموح لها في خانتها، ومش بتقول
    أنهي قطعة. القطعة الوحيدة اللي بيفضل مكانها الأول في الشنطة الجديدة (من غير
    إخراج) في القسم المتخصص هي المرشحة — بتطلع الأوفر والتبديل يتعاد.
    """
    target = next((s for s in plan.get("new_sections") or [] if s["key"] == "augmented_slots"), None)
    if target is None or not plan.get("order"):
        return []
    evicted = {i for i in plan.get("evict") or []}
    out = []
    for item in plan["order"]:
        if item["sec"] != "augmented_slots" or item["instance_id"] in evicted:
            continue
        if item["index"] < len(target["cells"]):
            out.append(item["instance_id"])
    return out


def _slot_key_of(tree, cell):
    """قسم الخانة من اسم حاويتها (Looting Mk. 2 Weapon 1 ...) — أسماء الخانات
    نفسها عامة (Firearm Slot / Item Slot)."""
    lab = (tree.label(tree.parent.get(cell) or "") or "").lower()
    if not lab:
        lab = (tree.label(cell) or "").lower()
    if "weapon 1" in lab:
        return "gun_1"
    if "weapon 2" in lab:
        return "gun_2"
    if "shield" in lab:
        return "shield"
    if "quick use" in lab:
        return "quick_use"
    if "safe pocket" in lab:
        return "safe_pocket"
    if "auxiliary" in lab or "trinket" in lab:
        return "augmented_slots"
    if "backpack" in lab or "item slot" in lab:
        return "backpack"
    return "augmented_slots"


def _move_run(conn, account, token, moves, preview, started):
    """جوهر move_plan بعد التحقق من التوكن: تخطيط على الشجرة، طلب واحد، إرجاع."""

    try:
        # كاش 15 ثانية كويس لو حد بينقل ورا حد، لكن مش لو حد بينتظر تبديل: اللوحة
        # وسيطة ممكن تبقى مختلفة عن الشجرة القديمة والقطعة تتحط على خانة خانة
        # غير اللي المستخدم شايفها. النقل بيتخطّط على قراءة طازة دايمًا.
        invalidate_live_cache(account)
        data, tree = get_live_tree(account, max_age=15)
        # الخطة الكبيرة بتقعد ثواني على البوابة، والخيط الخلفي بيتحدّث بعدها بشجرة
        # جديدة: لو كل حركة أخذتها من الكاش كان الطرد والنقل اتخطّطوا على شجرتين
        # والفرق بينهم ضاع. الشجرة اللي الحلقة تعدّلها هي مصدر الحقيقة هنا، ومفيش
        # حد تاني بيلمسها غير الخيط ده، فيتسجل مكانها في الكاش على طول.
        _INV_CACHE[account] = {"ts": time.time(), "data": data, "tree": tree}
        # الشنطة الملبوسة بتحدد نوع الدرع المسموح — نقف قبل أي كتابة لو مش مدعوم.
        for move in moves:
            if str(move.get("target_container") or "").lower() != "loadout"                     or str(move.get("target_slot") or "").lower() != "shield":
                continue
            spec = augments.resolve(str((tree.by_id.get(
                str((((pioneer_tree.layout(tree).get("augment") or {}).get("item")) or ""))) or {}
            ).get("gameAssetId") or ""))
            for iid in move.get("instance_ids") or []:
                ok, why = augments.shield_supports(spec, _shield_type(tree, str(iid)))
                if not ok:
                    return {"executed": False, "error": "shield_not_supported", "code": 409,
                            "detail": why, "preview": preview}
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code,
                "detail": exc.detail, "preview": preview}
    except pc.TokenExpired as exc:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": str(exc), "preview": preview}
    except (pc.PioneerError, Exception) as exc:
        return {"executed": False, "error": "gateway_error", "code": 502,
                "detail": str(exc)[:300], "preview": preview}

    # اللعبة نفسها: الخانة لو مليانة مش بترفض — الموجود فيها بيروح لأقرب خانة فاضية
    # في نفس الحاوية. البوابة بترفض الطلب اللي بيحط عنصرين في خانة واحدة، فالتبديل
    # الحقيقي (اللي المفروض يحصل من الأوفر ستاش) بيخرج من خانته الأول في خطوة
    # تلقائية، وبعدين نقلت المستخدم بتتنفذ على الشجرة المحدّثة.
    original_steps = []
    evictions = {}
    return_cells = {}
    for move in moves:
        wrapper = str(move.get("target_wrapper_id") or "")
        container = str(move.get("target_container") or "").lower()
        if not wrapper or container not in ("backpack", "loadout"):
            continue
        occupant = tree.first_child(wrapper)
        if not occupant or occupant in evictions:
            continue
        # تبديل خانة (SHIELD / WEAPON / QUICK USE / SAFE POCKET / AUGMENTED):
        # القديم للأوفر في نفس الطلب، وخانته محفوظة عشان ترجع عليها لو البوابة
        # رفضت الجديد — القطعة الملبوسة مابتضيعش.
        ids = [str(i) for i in (move.get("instance_ids") or []) if i]
        swapping = bool(move.get("swap")) or (container == "loadout" and bool(ids))
        try:
            body, _dest, _moved, _lay = pioneer_tree.plan_move(
                tree, [occupant], "overflow", "", "",
                source_steps=([(occupant, wrapper)] if swapping and container == "loadout" else None))
        except pioneer_tree.TreeError as exc:
            return {"executed": False, "error": exc.error, "code": exc.code,
                    "detail": exc.detail, "preview": preview}
        pioneer_tree.apply_steps(tree, body["steps"])
        evictions[occupant] = body["steps"]
        original_steps.append((body["steps"], "displaced"))
        if swapping:
            return_cells[occupant] = wrapper

    original, original_parent = {}, {}
    steps_all, moved_all, plans = [], [], []
    for exp_steps in evictions.values():
        for step in exp_steps:
            for cell in (step["source"], step["target"]):
                if cell:
                    original.setdefault(cell, list(tree.kids.get(cell) or []))
        steps_all.extend(exp_steps)
    # الخانة نفسها مبتتلمسش مرتين في طلب واحد: طرد المحتوى ونقل قطعة عليه في
    # نفس الطلب كان بيتلخّص لسطر واحد للخانة، ولو الحالة النهائية بتساوي الحالية
    # (القطعة أصلاً في الأوفر مالهاش سطر خروج) الطلب بيطلع فاضي. الحركة الأولى
    # في الخطة هي اللي بتاخد الخانة، وطردها اللي اتطبّق فوق بيتشال من الخطوات.
    claimed_cells = set()
    to_overflow = False
    for move in moves:
        ids = [str(i) for i in (move.get("instance_ids") or []) if i]
        # الخانة اللي اتاخدت مابقاش ليها محتوى قديم: فيه قطعة بتحرّكها، وطردها
        # اللي اتطبّق فوق مش محتاج خطوة خروج تاني.
        for cell in [str(move.get("target_wrapper_id") or "").lower()]:
            if cell in claimed_cells:
                evictions.pop(cell, None)
        try:
            body, dest, moved, lay = pioneer_tree.plan_move(
                tree, ids, move.get("target_container"), move.get("target_slot") or "",
                move.get("target_wrapper_id") or "",
                fallback_if_full=bool(move.get("fallback_if_full")))
        except pioneer_tree.TreeError as exc:
            # الستاش مليان: زي اللعبة بالظبط — الحاجة بتروح الأوفر ستاش
            # (العنصر بيتكتب عائم من غير خانة أب على البوابة).
            if (exc.error == "no_empty_target"
                    and str(move.get("target_container") or "").lower() == "stash"
                    and not (move.get("target_wrapper_id") or "")):
                try:
                    body, dest, moved, lay = pioneer_tree.plan_move(tree, ids, "overflow", "", "")
                    to_overflow = True
                except pioneer_tree.TreeError as exc2:
                    return {"executed": False, "error": exc2.error, "code": exc2.code,
                            "detail": exc2.detail, "preview": preview,
                            "executed_steps": len(steps_all)}
            else:
                return {"executed": False, "error": exc.error, "code": exc.code,
                        "detail": exc.detail, "preview": preview,
                        "executed_steps": len(steps_all)}
        for step in body["steps"]:
            iid = step["instance_id"]
            original_parent.setdefault(iid, tree.parent.get(iid))
            for cell in (step["source"], step["target"]):
                if cell:
                    original.setdefault(cell, list(tree.kids.get(cell) or []))
        pioneer_tree.apply_steps(tree, body["steps"])
        for step in body["steps"]:
            if step.get("target"):
                claimed_cells.add(str(step["target"]).lower())
        steps_all.extend(body["steps"])
        moved_all.extend(moved)
        plans.append({"body": body, "dest": dest, "moved": moved})
        preview["items"].extend({"name": m.get("name"), "from": m.get("from_label"),
                                 "qty": tree.amount(m.get("instance_id"))} for m in moved)

    mutations = _mutations_for(tree, original)
    if not mutations:
        return {"executed": False, "error": "already_there", "code": 409,
                "detail": "The items are already in the requested destination.", "preview": preview}
    request = {"mutations": mutations, "steps": steps_all, "requestId": ""}
    preview["body"] = request
    preview["destination"] = plans[-1]["dest"] if plans else None

    response, send_error = _post(request, token)
    elapsed = int((time.time() - started) * 1000)
    restore = {"attempted": False, "ok": True}
    if (send_error or (response or {}).get("error")) and return_cells:
        restore = _restore_occupants(conn, account, tree, return_cells, token)

    # المسار السريع: البوابة قبلت الطلب (200 ومن غير error) — بنحدّث جدول الصفوف
    # فورًا (أقل من 1ms) ونرجّع النتيجة من غير قراءة تانية كاملة للمخزن كانت
    # بتخلّي كل نقلة تستنى عدة ثواني. التحقق الكامل بيحصل في الخلفية.
    if not send_error and response and not response.get("error"):
        dest_c = plans[-1]["dest"].get("container") or ("overflow" if to_overflow else moves[-1].get("target_container") or "stash")
        final_cell = {}
        try:
            for plan in plans:
                for s in plan["body"]["steps"]:
                    final_cell[s["instance_id"]] = s.get("target") or ""
                    conn.execute(
                        "UPDATE instances SET container = ?, wrapper_id = ? WHERE account = ? AND instance_id = ?",
                        (dest_c, s.get("target") or "", account, s["instance_id"]))
            conn.commit()
        except Exception as exc:
            print("[pioneer_write] fast instance update: %s" % exc)

        for iid, cell in final_cell.items():
            if cell:
                tree.parent[iid] = cell
        for cell, kids in original.items():
            kids_now = [i for i in (list(tree.kids.get(cell) or []) + list(final_cell))
                        if final_cell.get(i, i) == cell]
            tree.kids[cell] = kids_now
        if account in _INV_CACHE:
            _INV_CACHE[account]["ts"] = time.time()
            _INV_CACHE[account]["tree"] = tree

        def _bg_sync():
            try:
                time.sleep(0.4)
                d_after = pc.fetch_inventory_for(account)
                if d_after:
                    bg_tree = pioneer_tree.Tree((d_after or {}).get("items") or [])
                    # من غير layout الشجرة بتفضل من غير أبوين: كل قطعة تبان أوفر
                    # ستاش، وحركة المستخدم اللي بعدها بتترمي كـ already_there.
                    pioneer_tree.layout(bg_tree)
                    _INV_CACHE[account] = {"ts": time.time(), "data": d_after, "tree": bg_tree}
                    c = store.db()
                    try:
                        _refresh_data(c, account, d_after)
                    finally:
                        c.close()
            except Exception:
                pass
        threading.Thread(target=_bg_sync, daemon=True).start()

        _log(conn, account, {"target_container": "overflow" if to_overflow else moves[-1].get("target_container"),
                             "moves": len(moves), "mutations": len(mutations)},
             "executed", response or {}, len(steps_all))
        return {"executed": True, "preview": preview, "moved": moved_all,
                "result": {"ok": True, "code": 200, "response": response or {}},
                "verification": {"ok": True, "deferred": True}, "refreshed": {"ok": True, "deferred": True},
                "to_overflow": to_overflow, "bag": _bag_state(tree),
                "displaced": [{"instance_id": iid, "name": tree.name_of(iid)}
                              for iid in evictions],
                "undo": {"cells": {cell: list(kids) for cell, kids in original.items()}},
                "items": len(steps_all), "requests": 1, "elapsed_ms": elapsed}

    expected = {iid: tree.parent.get(iid) for iid in original_parent}
    # خانات الشنطة/التجهيز الي اتكتبت: لازم تضل جوا الحاوية المجهّزة — دي الوحيدة
    # الي اللعبة بتقرأها. الخانة برّاها معناها القطعة اتحطت في لوداوت تاني مخفي.
    bag_cells = {s["target"] for plan in plans for s in plan["body"]["steps"]
                 if s.get("target") and str(plan["dest"].get("label") or "").upper()
                 in ("BACKPACK", "LOADOUT")}
    # الحاويات المسموح بيها بتتقاس من الشجرة الي اتطبّقت عليها الكتابة، وكل بول
    # إعادة بترتقي لشجرة السيرفر الجديدة (لو المؤشر اتقلب في النص ما نرفضش كتابة صح).
    tree_after = tree
    inside = (pioneer_tree.active_containers(tree_after), bag_cells) if bag_cells else None
    verified, tree_after, data_after = _verify(account, expected, inside)
    # البوابة بتطبّق الكتابة بعد لحظات — بولات متزايدة عشان نلحق العناصر السايبة
    # (العنصر السايب مالهوش أب، فـ parent.get بيرجع None مش "").
    if not verified:
        for wait in VERIFY_POLL_WAITS:
            time.sleep(wait)
            verified, tree_after, data_after = _verify_once(account, expected, inside)
            if verified:
                break
            if bag_cells:
                inside = (pioneer_tree.active_containers(tree_after), bag_cells)
    elapsed = int((time.time() - started) * 1000)

    if verified:
        refreshed = _refresh_data(conn, account, data_after)
        _log(conn, account, {"target_container": "overflow" if to_overflow else moves[-1].get("target_container"),
                             "moves": len(moves), "mutations": len(mutations)},
             "executed", response or {}, len(steps_all))
        out = {"executed": True, "preview": preview, "moved": moved_all,
               "result": {"ok": True, "code": 200, "response": response or {}},
               "verification": {"ok": True}, "refreshed": refreshed,
               "to_overflow": to_overflow, "bag": _bag_state(tree_after),
               "displaced": [{"instance_id": iid, "name": tree_after.name_of(iid)}
                             for iid in evictions],
               "undo": {"cells": {cell: list(kids) for cell, kids in original.items()}},
               "items": len(steps_all), "requests": 1, "elapsed_ms": elapsed}
        if send_error:
            out["note"] = "The gateway returned an error for the request but the state was confirmed from the official stash — the move is done."
        return out

    changed = [(iid, original_parent[iid], expected[iid]) for iid in expected
               if tree_after.parent.get(iid) == expected[iid]
               and tree_after.parent.get(iid) != original_parent[iid]]
    # لو التحقق نفسه ما قدرش يقرأ الشجرة، بنرجّع الخانات لأصلها وإحنا مش شايفين
    # (الطلبات بتحدد حالة نهائية فإعادة الإرسال آمنة حتى لو النقل ما اتنفذش).
    unknown = data_after is None
    rollback = {"attempted": False, "ok": True, "items": 0, "steps": []}
    if changed or unknown:
        undo = _restore_request(tree_after, original)
        if undo["mutations"] or undo["steps"]:
            rollback["attempted"] = True
            rollback["items"] = len(changed)
            _, undo_error = _post(undo, token)
            restored, _, _ = _verify(account, original_parent)
            rollback["ok"] = restored
            rollback["steps"] = [{"ok": restored, "items": len(changed)}]
            if undo_error:
                rollback["error"] = undo_error
    error = (send_error or {}).get("error") or ("verify_unreachable" if unknown else "verification_failed")
    # العناصر في الخانات الي طلبناها بس الخانات دي برّه الحاوية المجهّزة — يعني
    # الكتابة راحت للوداوت غلط واللعبة مش هتشوف حاجة.
    misplaced = bool(inside) and not unknown and bool(changed) and all(
        tree_after.parent.get(iid) == cell for iid, cell in expected.items())
    if misplaced:
        error = "outside_equipped_loadout"
    if rollback.get("ok"):
        detail = ("We returned the items to their places: the cell the gateway put them in is outside the "
                  "equipped container, and the game only reads the equipped container — enter the match and change "
                  "the loadout inside the game, then sync the site again."
                  if misplaced else
                  ("The move was not confirmed — we returned the cells to their original state, nothing changed."
                   if (changed or unknown) else "The move did not complete and no item moved."))
    else:
        detail = ("The items did not settle in the destination, and the rollback did not complete — "
                  "check the stash before any other attempt.")
    if send_error and send_error.get("detail"):
        detail = "%s (%s)" % (detail, send_error["detail"])
    partial = (bool(changed) or unknown) and not rollback.get("ok", False)
    _log(conn, account, {"target_container": "overflow" if to_overflow else moves[-1].get("target_container"),
                         "moves": len(moves), "mutations": len(mutations)},
         "partial" if partial else "failed",
         {"error": error, "detail": detail, "rollback": rollback}, len(steps_all))
    return {"executed": False, "error": error,
            "code": (send_error or {}).get("code") or 502, "detail": detail,
            "preview": preview, "moved": moved_all, "partial": partial,
            "rollback": rollback,
            "restored": bool(rollback.get("attempted")) and bool(rollback.get("ok")),
            "items": len(steps_all), "elapsed_ms": int((time.time() - started) * 1000),
            "result": send_error or {"ok": False, "code": 502, "error": error}}


def touch_loadout(conn, account, instance_ids=None):
    """زرار ↑ UPDATE: بيلمس خانات التجهيز على سيرفر Embark من غير ما يحرّك حاجة.

    اللمسة = update بنفس الـ slots ونفس الـ amount بالظبط. مقيس لايف 2026-10-29
    (inspection/probe_touch.py): البوابة بترجع 200 وبتحدّث updatedAt للخانة،
    ومفيش ولا عنصر بيغيّر مكانه أو كميته — يعني كتابة محايدة تماماً.
    اللي بنختبره بيه: الكلاينت بيمسك نسخة من الشنطة وقت اللوبي ومبيحدّثهاش
    بعد الكتابة من بره، فالقطعة اللي تتحط في الشنطة بتظهر جوه الماتش متأخر.
    لو سجل أحدث على السيرفر خلّى الكلاينت يسحب الشنطة من جديد، المشكلة دي تختفي.

    instance_ids اختيارية: يلمّس خانات العناصر المحددة بس (من أي مكان)، وإلا
    يلمّس كل خانة فيها حاجة في اللوداوت المجهز + الشنطة.
    """
    started = time.time()
    blocked = _pause_block()
    if blocked:
        return blocked
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": "No saved token for account %s — add it from the accounts page." % account}
    try:
        tree = _fetch_tree(account)
        lay = pioneer_tree.layout(tree)
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code, "detail": exc.detail}
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "code": 502, "detail": str(exc)[:300]}

    wrappers = []
    picked = {str(i) for i in (instance_ids or []) if i}
    if picked:
        for iid in picked:
            cell = str(tree.parent.get(iid) or "")
            if cell and cell not in wrappers:
                wrappers.append(cell)
    else:
        for slot in (lay["backpack"].get("slots") or []):
            wrappers.append(str(slot.get("wrapper") if isinstance(slot, dict) else slot))
        for entries in (lay["loadout"].get("slots") or {}).values():
            for slot in entries or []:
                wrappers.append(str(slot.get("wrapper") if isinstance(slot, dict) else slot))
    mutations = []
    for cell in wrappers:
        kids = [str(k) for k in (tree.kids.get(cell) or [])]
        if not kids:
            continue                       # الخانة الفاضية مالهاش حاجة تتلمّس
        mutations.append({"discriminator": "update", "instanceId": cell,
                          "slots": _slots_payload(kids), "amount": tree.amount(cell)})
    if not mutations:
        return {"executed": False, "error": "nothing_to_touch", "code": 400,
                "detail": "Nothing is equipped in the backpack/loadout — place a piece first."}

    before = {iid: (str(tree.parent.get(iid) or ""), int(tree.amount(iid) or 1))
              for iid in tree.by_id}
    stamps = {c: int(tree.by_id[c].get("updatedAt") or 0) for c in wrappers if c in tree.by_id}
    response, send_error = _post({"mutations": mutations, "requestId": ""}, token)
    if send_error:
        _log(conn, account, {"kind": "touch", "cells": len(mutations)}, "failed",
             send_error, len(mutations))
        return {"executed": False, **send_error, "touched": 0}

    try:
        after_tree = _fetch_tree(account)
    except pc.PioneerError as exc:
        return {"executed": True, "verified": False,
                "detail": "The touch succeeded but we could not read the tree again: %s" % str(exc)[:160]}
    after = {iid: (str(after_tree.parent.get(iid) or ""), int(after_tree.amount(iid) or 1))
             for iid in after_tree.by_id}
    moved = [i for i in set(before) | set(after) if before.get(i) != after.get(i)]
    bumped = [c for c, s in stamps.items()
              if int((after_tree.by_id.get(c) or {}).get("updatedAt") or 0) > s]
    refreshed = _refresh_data(conn, account, (pc.fetch_inventory_for(account) or {}))
    _log(conn, account, {"kind": "touch", "cells": len(mutations)},
         "executed" if not moved else "partial",
         {"moved": len(moved), "bumped": len(bumped)}, len(mutations))
    out = {"executed": True, "touched": len(mutations), "bumped": len(bumped),
           "moved": len(moved), "verified": not moved, "preview": {"mutations": mutations},
           "result": {"ok": True, "code": 200, "response": response or {}},
           "refreshed": refreshed, "undo": {"cells": {}},
           "elapsed_ms": int((time.time() - started) * 1000),
           "detail": ("We touched %s cells on the Embark server — not one item moved and no quantity "
                      "changed, and the update log advanced by %s cells." % (len(mutations), len(bumped)))}
    if moved:
        out["detail"] = ("The touch moved %s items — that should not happen; open the stash "
                         "and verify before you continue." % len(moved))
    return out


def undo_cells(conn, account, cells):
    """يرجّع الخانات المسجّلة لحالتها الأصلية — خطوة undo واحدة من سجل الواجهة.

    cells = {خانة: [آيدسات عناصرها الأصلية]} زي ما رجّعها move_plan في out["undo"].
    بنقارن بالشجرة الحية فبنبعت الفرق بس (الكتابة idempotent)، وبنحقق بعد الطلب
    بنفس طريقة النقل. بنرجّع undo تاني للوضع اللي قبل التراجع لو عايز ترجعها.
    """
    started = time.time()
    target = {str(c): [str(i) for i in (v or [])] for c, v in (cells or {}).items() if c}
    blocked = _pause_block()
    if blocked:
        return blocked
    if not target:
        return {"executed": False, "error": "nothing_to_undo", "code": 400,
                "detail": "There is no recorded step to undo."}
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": "No saved token for account %s — add it from the accounts page." % account}
    try:
        tree = _fetch_tree(account)
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "code": 502, "detail": str(exc)[:300]}

    request = _restore_request(tree, target)
    mutations = request["mutations"]
    if not (mutations or request["steps"]):
        return {"executed": False, "error": "already_there", "code": 409,
                "detail": "The cells are already in this state — there is nothing to undo."}

    def _read_tree():
        data = pc.fetch_inventory_for(account)
        return pioneer_tree.Tree((data or {}).get("items") or []), data

    def _matches(t):
        return all(list(t.kids.get(c) or []) == k for c, k in target.items() if c in t.by_id)

    response, send_error = _post(request, token)
    if send_error:
        return {**send_error, "executed": False, "detail": send_error.get("detail") or "The gateway refused the undo."}
    data_after = None
    for attempt in range(5):
        if attempt:
            time.sleep(VERIFY_WAIT * 2)
            _post(request, token)  # إعادة إرسال نفس الحالة النهائية — آمنة
        try:
            tree_after, data = _read_tree()
        except Exception:
            continue
        if _matches(tree_after):
            data_after = data
            break
    elapsed = int((time.time() - started) * 1000)
    if data_after is None:
        store.log_action(conn, account, "undo", {"cells": len(target)}, "failed",
                         {"error": "verification_failed"}, len(mutations))
        return {"executed": False, "error": "verification_failed", "code": 502,
                "detail": "The undo was not confirmed — refresh the state with SYNC before any other step.",
                "items": len(mutations), "elapsed_ms": elapsed}
    refreshed = _refresh_data(conn, account, data_after)
    store.log_action(conn, account, "undo", {"cells": len(target), "mutations": len(mutations)},
                     "executed", response or {}, len(mutations))
    return {"executed": True, "items": len(mutations), "elapsed_ms": elapsed,
            "refreshed": refreshed, "result": {"ok": True, "code": 200, "response": response or {}},
            "detail": "We returned %d cells to the state they had before the move." % len(mutations)}


def move(conn, account, target_container, rows, target_wrapper_id="", target_slot="",
         fallback_if_full=False, carry_instance_ids=None, swap=None):
    rows = [r for r in (rows or []) if r.get("instance_id")]
    carry = [str(i) for i in (carry_instance_ids or []) if i]
    moves = [{
        "target_container": target_container,
        "target_wrapper_id": target_wrapper_id,
        "target_slot": target_slot,
        "fallback_if_full": bool(fallback_if_full),
        "swap": bool(swap) if swap is not None else (
            target_container == "loadout" and bool(target_wrapper_id)
            and str(target_slot or "").lower() != "augment"),
        "instance_ids": [str(r["instance_id"]) for r in rows],
    }]
    if carry and str(target_slot or "").lower() == "augment":
        # اللي بيتحط في الشنطة الجديدة: الباكدج لو اتحدد، والكارت/القطيع الصغير
        # على الخانات الأصغر — كل ده الباكند بيوزعه بعد ما يقرا الشنطة الفعلية.
        moves.append({"target_container": "backpack", "target_wrapper_id": "",
                      "target_slot": "", "instance_ids": carry})
    return move_plan(conn, account, moves)
def _move_run(conn, account, token, moves, preview, started):
    """جوهر move_plan بعد التحقق من التوكن: تخطيط على الشجرة، طلب واحد، إرجاع."""

    try:
        # كاش 15 ثانية كويس لو حد بينقل ورا حد، لكن مش لو حد بينتظر تبديل: اللوحة
        # وسيطة ممكن تبقى مختلفة عن الشجرة القديمة والقطعة تتحط على خانة خانة
        # غير اللي المستخدم شايفها. النقل بيتخطّط على قراءة طازة دايمًا.
        invalidate_live_cache(account)
        data, tree = get_live_tree(account, max_age=15)
        # الخطة الكبيرة بتقعد ثواني على البوابة، والخيط الخلفي بيتحدّث بعدها بشجرة
        # جديدة: لو كل حركة أخذتها من الكاش كان الطرد والنقل اتخطّطوا على شجرتين
        # والفرق بينهم ضاع. الشجرة اللي الحلقة تعدّلها هي مصدر الحقيقة هنا، ومفيش
        # حد تاني بيلمسها غير الخيط ده، فيتسجل مكانها في الكاش على طول.
        _INV_CACHE[account] = {"ts": time.time(), "data": data, "tree": tree}
        # الشنطة الملبوسة بتحدد نوع الدرع المسموح — نقف قبل أي كتابة لو مش مدعوم.
        for move in moves:
            if str(move.get("target_container") or "").lower() != "loadout"                     or str(move.get("target_slot") or "").lower() != "shield":
                continue
            spec = augments.resolve(str((tree.by_id.get(
                str((((pioneer_tree.layout(tree).get("augment") or {}).get("item")) or ""))) or {}
            ).get("gameAssetId") or ""))
            for iid in move.get("instance_ids") or []:
                ok, why = augments.shield_supports(spec, _shield_type(tree, str(iid)))
                if not ok:
                    return {"executed": False, "error": "shield_not_supported", "code": 409,
                            "detail": why, "preview": preview}
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code,
                "detail": exc.detail, "preview": preview}
    except pc.TokenExpired as exc:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": str(exc), "preview": preview}
    except (pc.PioneerError, Exception) as exc:
        return {"executed": False, "error": "gateway_error", "code": 502,
                "detail": str(exc)[:300], "preview": preview}

    # اللعبة نفسها: الخانة لو مليانة مش بترفض — الموجود فيها بيروح لأقرب خانة فاضية
    # في نفس الحاوية. البوابة بترفض الطلب اللي بيحط عنصرين في خانة واحدة، فالتبديل
    # الحقيقي (اللي المفروض يحصل من الأوفر ستاش) بيخرج من خانته الأول في خطوة
    # تلقائية، وبعدين نقلت المستخدم بتتنفذ على الشجرة المحدّثة.
    original_steps = []
    evictions = {}
    return_cells = {}
    for move in moves:
        wrapper = str(move.get("target_wrapper_id") or "")
        container = str(move.get("target_container") or "").lower()
        if not wrapper or container not in ("backpack", "loadout"):
            continue
        occupant = tree.first_child(wrapper)
        if not occupant or occupant in evictions:
            continue
        # تبديل خانة (SHIELD / WEAPON / QUICK USE / SAFE POCKET / AUGMENTED):
        # القديم للأوفر في نفس الطلب، وخانته محفوظة عشان ترجع عليها لو البوابة
        # رفضت الجديد — القطعة الملبوسة مابتضيعش.
        ids = [str(i) for i in (move.get("instance_ids") or []) if i]
        swapping = bool(move.get("swap")) or (container == "loadout" and bool(ids))
        try:
            body, _dest, _moved, _lay = pioneer_tree.plan_move(
                tree, [occupant], "overflow", "", "",
                source_steps=([(occupant, wrapper)] if swapping and container == "loadout" else None))
        except pioneer_tree.TreeError as exc:
            return {"executed": False, "error": exc.error, "code": exc.code,
                    "detail": exc.detail, "preview": preview}
        pioneer_tree.apply_steps(tree, body["steps"])
        evictions[occupant] = body["steps"]
        original_steps.append((body["steps"], "displaced"))
        if swapping:
            return_cells[occupant] = wrapper

    original, original_parent = {}, {}
    steps_all, moved_all, plans = [], [], []
    for exp_steps in evictions.values():
        for step in exp_steps:
            for cell in (step["source"], step["target"]):
                if cell:
                    original.setdefault(cell, list(tree.kids.get(cell) or []))
        steps_all.extend(exp_steps)
    # الخانة نفسها مبتتلمسش مرتين في طلب واحد: طرد المحتوى ونقل قطعة عليه في
    # نفس الطلب كان بيتلخّص لسطر واحد للخانة، ولو الحالة النهائية بتساوي الحالية
    # (القطعة أصلاً في الأوفر مالهاش سطر خروج) الطلب بيطلع فاضي. الحركة الأولى
    # في الخطة هي اللي بتاخد الخانة، وطردها اللي اتطبّق فوق بيتشال من الخطوات.
    claimed_cells = set()
    to_overflow = False
    for move in moves:
        ids = [str(i) for i in (move.get("instance_ids") or []) if i]
        # الخانة اللي اتاخدت مابقاش ليها محتوى قديم: فيه قطعة بتحرّكها، وطردها
        # اللي اتطبّق فوق مش محتاج خطوة خروج تاني.
        for cell in [str(move.get("target_wrapper_id") or "").lower()]:
            if cell in claimed_cells:
                evictions.pop(cell, None)
        try:
            body, dest, moved, lay = pioneer_tree.plan_move(
                tree, ids, move.get("target_container"), move.get("target_slot") or "",
                move.get("target_wrapper_id") or "",
                fallback_if_full=bool(move.get("fallback_if_full")))
        except pioneer_tree.TreeError as exc:
            # الستاش مليان: زي اللعبة بالظبط — الحاجة بتروح الأوفر ستاش
            # (العنصر بيتكتب عائم من غير خانة أب على البوابة).
            if (exc.error == "no_empty_target"
                    and str(move.get("target_container") or "").lower() == "stash"
                    and not (move.get("target_wrapper_id") or "")):
                try:
                    body, dest, moved, lay = pioneer_tree.plan_move(tree, ids, "overflow", "", "")
                    to_overflow = True
                except pioneer_tree.TreeError as exc2:
                    return {"executed": False, "error": exc2.error, "code": exc2.code,
                            "detail": exc2.detail, "preview": preview,
                            "executed_steps": len(steps_all)}
            else:
                return {"executed": False, "error": exc.error, "code": exc.code,
                        "detail": exc.detail, "preview": preview,
                        "executed_steps": len(steps_all)}
        for step in body["steps"]:
            iid = step["instance_id"]
            original_parent.setdefault(iid, tree.parent.get(iid))
            for cell in (step["source"], step["target"]):
                if cell:
                    original.setdefault(cell, list(tree.kids.get(cell) or []))
        pioneer_tree.apply_steps(tree, body["steps"])
        for step in body["steps"]:
            if step.get("target"):
                claimed_cells.add(str(step["target"]).lower())
        steps_all.extend(body["steps"])
        moved_all.extend(moved)
        plans.append({"body": body, "dest": dest, "moved": moved})
        preview["items"].extend({"name": m.get("name"), "from": m.get("from_label"),
                                 "qty": tree.amount(m.get("instance_id"))} for m in moved)

    mutations = _mutations_for(tree, original)
    if not mutations:
        return {"executed": False, "error": "already_there", "code": 409,
                "detail": "The items are already in the requested destination.", "preview": preview}
    request = {"mutations": mutations, "steps": steps_all, "requestId": ""}
    preview["body"] = request
    preview["destination"] = plans[-1]["dest"] if plans else None

    response, send_error = _post(request, token)
    elapsed = int((time.time() - started) * 1000)
    restore = {"attempted": False, "ok": True}
    if (send_error or (response or {}).get("error")) and return_cells:
        restore = _restore_occupants(conn, account, tree, return_cells, token)

    # المسار السريع: البوابة قبلت الطلب (200 ومن غير error) — بنحدّث جدول الصفوف
    # فورًا (أقل من 1ms) ونرجّع النتيجة من غير قراءة تانية كاملة للمخزن كانت
    # بتخلّي كل نقلة تستنى عدة ثواني. التحقق الكامل بيحصل في الخلفية.
    if not send_error and response and not response.get("error"):
        dest_c = plans[-1]["dest"].get("container") or ("overflow" if to_overflow else moves[-1].get("target_container") or "stash")
        final_cell = {}
        try:
            for plan in plans:
                for s in plan["body"]["steps"]:
                    final_cell[s["instance_id"]] = s.get("target") or ""
                    conn.execute(
                        "UPDATE instances SET container = ?, wrapper_id = ? WHERE account = ? AND instance_id = ?",
                        (dest_c, s.get("target") or "", account, s["instance_id"]))
            conn.commit()
        except Exception as exc:
            print("[pioneer_write] fast instance update: %s" % exc)

        for iid, cell in final_cell.items():
            if cell:
                tree.parent[iid] = cell
        for cell, kids in original.items():
            kids_now = [i for i in (list(tree.kids.get(cell) or []) + list(final_cell))
                        if final_cell.get(i, i) == cell]
            tree.kids[cell] = kids_now
        if account in _INV_CACHE:
            _INV_CACHE[account]["ts"] = time.time()
            _INV_CACHE[account]["tree"] = tree

        def _bg_sync():
            try:
                time.sleep(0.4)
                d_after = pc.fetch_inventory_for(account)
                if d_after:
                    bg_tree = pioneer_tree.Tree((d_after or {}).get("items") or [])
                    # من غير layout الشجرة بتفضل من غير أبوين: كل قطعة تبان أوفر
                    # ستاش، وحركة المستخدم اللي بعدها بتترمي كـ already_there.
                    pioneer_tree.layout(bg_tree)
                    _INV_CACHE[account] = {"ts": time.time(), "data": d_after, "tree": bg_tree}
                    c = store.db()
                    try:
                        _refresh_data(c, account, d_after)
                    finally:
                        c.close()
            except Exception:
                pass
        threading.Thread(target=_bg_sync, daemon=True).start()

        _log(conn, account, {"target_container": "overflow" if to_overflow else moves[-1].get("target_container"),
                             "moves": len(moves), "mutations": len(mutations)},
             "executed", response or {}, len(steps_all))
        return {"executed": True, "preview": preview, "moved": moved_all,
                "result": {"ok": True, "code": 200, "response": response or {}},
                "verification": {"ok": True, "deferred": True}, "refreshed": {"ok": True, "deferred": True},
                "to_overflow": to_overflow, "bag": _bag_state(tree),
                "displaced": [{"instance_id": iid, "name": tree.name_of(iid)}
                              for iid in evictions],
                "undo": {"cells": {cell: list(kids) for cell, kids in original.items()}},
                "items": len(steps_all), "requests": 1, "elapsed_ms": elapsed}

    expected = {iid: tree.parent.get(iid) for iid in original_parent}
    # خانات الشنطة/التجهيز الي اتكتبت: لازم تضل جوا الحاوية المجهّزة — دي الوحيدة
    # الي اللعبة بتقرأها. الخانة برّاها معناها القطعة اتحطت في لوداوت تاني مخفي.
    bag_cells = {s["target"] for plan in plans for s in plan["body"]["steps"]
                 if s.get("target") and str(plan["dest"].get("label") or "").upper()
                 in ("BACKPACK", "LOADOUT")}
    # الحاويات المسموح بيها بتتقاس من الشجرة الي اتطبّقت عليها الكتابة، وكل بول
    # إعادة بترتقي لشجرة السيرفر الجديدة (لو المؤشر اتقلب في النص ما نرفضش كتابة صح).
    tree_after = tree
    inside = (pioneer_tree.active_containers(tree_after), bag_cells) if bag_cells else None
    verified, tree_after, data_after = _verify(account, expected, inside)
    # البوابة بتطبّق الكتابة بعد لحظات — بولات متزايدة عشان نلحق العناصر السايبة
    # (العنصر السايب مالهوش أب، فـ parent.get بيرجع None مش "").
    if not verified:
        for wait in VERIFY_POLL_WAITS:
            time.sleep(wait)
            verified, tree_after, data_after = _verify_once(account, expected, inside)
            if verified:
                break
            if bag_cells:
                inside = (pioneer_tree.active_containers(tree_after), bag_cells)
    elapsed = int((time.time() - started) * 1000)

    if verified:
        refreshed = _refresh_data(conn, account, data_after)
        _log(conn, account, {"target_container": "overflow" if to_overflow else moves[-1].get("target_container"),
                             "moves": len(moves), "mutations": len(mutations)},
             "executed", response or {}, len(steps_all))
        out = {"executed": True, "preview": preview, "moved": moved_all,
               "result": {"ok": True, "code": 200, "response": response or {}},
               "verification": {"ok": True}, "refreshed": refreshed,
               "to_overflow": to_overflow, "bag": _bag_state(tree_after),
               "displaced": [{"instance_id": iid, "name": tree_after.name_of(iid)}
                             for iid in evictions],
               "undo": {"cells": {cell: list(kids) for cell, kids in original.items()}},
               "items": len(steps_all), "requests": 1, "elapsed_ms": elapsed}
        if send_error:
            out["note"] = "The gateway returned an error for the request but the state was confirmed from the official stash — the move is done."
        return out

    changed = [(iid, original_parent[iid], expected[iid]) for iid in expected
               if tree_after.parent.get(iid) == expected[iid]
               and tree_after.parent.get(iid) != original_parent[iid]]
    # لو التحقق نفسه ما قدرش يقرأ الشجرة، بنرجّع الخانات لأصلها وإحنا مش شايفين
    # (الطلبات بتحدد حالة نهائية فإعادة الإرسال آمنة حتى لو النقل ما اتنفذش).
    unknown = data_after is None
    rollback = {"attempted": False, "ok": True, "items": 0, "steps": []}
    if changed or unknown:
        undo = _restore_request(tree_after, original)
        if undo["mutations"] or undo["steps"]:
            rollback["attempted"] = True
            rollback["items"] = len(changed)
            _, undo_error = _post(undo, token)
            restored, _, _ = _verify(account, original_parent)
            rollback["ok"] = restored
            rollback["steps"] = [{"ok": restored, "items": len(changed)}]
            if undo_error:
                rollback["error"] = undo_error
    error = (send_error or {}).get("error") or ("verify_unreachable" if unknown else "verification_failed")
    # العناصر في الخانات الي طلبناها بس الخانات دي برّه الحاوية المجهّزة — يعني
    # الكتابة راحت للوداوت غلط واللعبة مش هتشوف حاجة.
    misplaced = bool(inside) and not unknown and bool(changed) and all(
        tree_after.parent.get(iid) == cell for iid, cell in expected.items())
    if misplaced:
        error = "outside_equipped_loadout"
    if rollback.get("ok"):
        detail = ("We returned the items to their places: the cell the gateway put them in is outside the "
                  "equipped container, and the game only reads the equipped container — enter the match and change "
                  "the loadout inside the game, then sync the site again."
                  if misplaced else
                  ("The move was not confirmed — we returned the cells to their original state, nothing changed."
                   if (changed or unknown) else "The move did not complete and no item moved."))
    else:
        detail = ("The items did not settle in the destination, and the rollback did not complete — "
                  "check the stash before any other attempt.")
    if send_error and send_error.get("detail"):
        detail = "%s (%s)" % (detail, send_error["detail"])
    partial = (bool(changed) or unknown) and not rollback.get("ok", False)
    _log(conn, account, {"target_container": "overflow" if to_overflow else moves[-1].get("target_container"),
                         "moves": len(moves), "mutations": len(mutations)},
         "partial" if partial else "failed",
         {"error": error, "detail": detail, "rollback": rollback}, len(steps_all))
    return {"executed": False, "error": error,
            "code": (send_error or {}).get("code") or 502, "detail": detail,
            "preview": preview, "moved": moved_all, "partial": partial,
            "rollback": rollback,
            "restored": bool(rollback.get("attempted")) and bool(rollback.get("ok")),
            "items": len(steps_all), "elapsed_ms": int((time.time() - started) * 1000),
            "result": send_error or {"ok": False, "code": 502, "error": error}}


def touch_loadout(conn, account, instance_ids=None):
    """زرار ↑ UPDATE: بيلمس خانات التجهيز على سيرفر Embark من غير ما يحرّك حاجة.

    اللمسة = update بنفس الـ slots ونفس الـ amount بالظبط. مقيس لايف 2026-10-29
    (inspection/probe_touch.py): البوابة بترجع 200 وبتحدّث updatedAt للخانة،
    ومفيش ولا عنصر بيغيّر مكانه أو كميته — يعني كتابة محايدة تماماً.
    اللي بنختبره بيه: الكلاينت بيمسك نسخة من الشنطة وقت اللوبي ومبيحدّثهاش
    بعد الكتابة من بره، فالقطعة اللي تتحط في الشنطة بتظهر جوه الماتش متأخر.
    لو سجل أحدث على السيرفر خلّى الكلاينت يسحب الشنطة من جديد، المشكلة دي تختفي.

    instance_ids اختيارية: يلمّس خانات العناصر المحددة بس (من أي مكان)، وإلا
    يلمّس كل خانة فيها حاجة في اللوداوت المجهز + الشنطة.
    """
    started = time.time()
    blocked = _pause_block()
    if blocked:
        return blocked
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": "No saved token for account %s — add it from the accounts page." % account}
    try:
        tree = _fetch_tree(account)
        lay = pioneer_tree.layout(tree)
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "code": exc.code, "detail": exc.detail}
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "code": 502, "detail": str(exc)[:300]}

    wrappers = []
    picked = {str(i) for i in (instance_ids or []) if i}
    if picked:
        for iid in picked:
            cell = str(tree.parent.get(iid) or "")
            if cell and cell not in wrappers:
                wrappers.append(cell)
    else:
        for slot in (lay["backpack"].get("slots") or []):
            wrappers.append(str(slot.get("wrapper") if isinstance(slot, dict) else slot))
        for entries in (lay["loadout"].get("slots") or {}).values():
            for slot in entries or []:
                wrappers.append(str(slot.get("wrapper") if isinstance(slot, dict) else slot))
    mutations = []
    for cell in wrappers:
        kids = [str(k) for k in (tree.kids.get(cell) or [])]
        if not kids:
            continue                       # الخانة الفاضية مالهاش حاجة تتلمّس
        mutations.append({"discriminator": "update", "instanceId": cell,
                          "slots": _slots_payload(kids), "amount": tree.amount(cell)})
    if not mutations:
        return {"executed": False, "error": "nothing_to_touch", "code": 400,
                "detail": "Nothing is equipped in the backpack/loadout — place a piece first."}

    before = {iid: (str(tree.parent.get(iid) or ""), int(tree.amount(iid) or 1))
              for iid in tree.by_id}
    stamps = {c: int(tree.by_id[c].get("updatedAt") or 0) for c in wrappers if c in tree.by_id}
    response, send_error = _post({"mutations": mutations, "requestId": ""}, token)
    if send_error:
        _log(conn, account, {"kind": "touch", "cells": len(mutations)}, "failed",
             send_error, len(mutations))
        return {"executed": False, **send_error, "touched": 0}

    try:
        after_tree = _fetch_tree(account)
    except pc.PioneerError as exc:
        return {"executed": True, "verified": False,
                "detail": "The touch succeeded but we could not read the tree again: %s" % str(exc)[:160]}
    after = {iid: (str(after_tree.parent.get(iid) or ""), int(after_tree.amount(iid) or 1))
             for iid in after_tree.by_id}
    moved = [i for i in set(before) | set(after) if before.get(i) != after.get(i)]
    bumped = [c for c, s in stamps.items()
              if int((after_tree.by_id.get(c) or {}).get("updatedAt") or 0) > s]
    refreshed = _refresh_data(conn, account, (pc.fetch_inventory_for(account) or {}))
    _log(conn, account, {"kind": "touch", "cells": len(mutations)},
         "executed" if not moved else "partial",
         {"moved": len(moved), "bumped": len(bumped)}, len(mutations))
    out = {"executed": True, "touched": len(mutations), "bumped": len(bumped),
           "moved": len(moved), "verified": not moved, "preview": {"mutations": mutations},
           "result": {"ok": True, "code": 200, "response": response or {}},
           "refreshed": refreshed, "undo": {"cells": {}},
           "elapsed_ms": int((time.time() - started) * 1000),
           "detail": ("We touched %s cells on the Embark server — not one item moved and no quantity "
                      "changed, and the update log advanced by %s cells." % (len(mutations), len(bumped)))}
    if moved:
        out["detail"] = ("The touch moved %s items — that should not happen; open the stash "
                         "and verify before you continue." % len(moved))
    return out


def undo_cells(conn, account, cells):
    """يرجّع الخانات المسجّلة لحالتها الأصلية — خطوة undo واحدة من سجل الواجهة.

    cells = {خانة: [آيدسات عناصرها الأصلية]} زي ما رجّعها move_plan في out["undo"].
    بنقارن بالشجرة الحية فبنبعت الفرق بس (الكتابة idempotent)، وبنحقق بعد الطلب
    بنفس طريقة النقل. بنرجّع undo تاني للوضع اللي قبل التراجع لو عايز ترجعها.
    """
    started = time.time()
    target = {str(c): [str(i) for i in (v or [])] for c, v in (cells or {}).items() if c}
    blocked = _pause_block()
    if blocked:
        return blocked
    if not target:
        return {"executed": False, "error": "nothing_to_undo", "code": 400,
                "detail": "There is no recorded step to undo."}
    token = pc.account_token(account)
    if not token:
        return {"executed": False, "error": "token_expired", "code": 401,
                "detail": "No saved token for account %s — add it from the accounts page." % account}
    try:
        tree = _fetch_tree(account)
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "code": 502, "detail": str(exc)[:300]}

    request = _restore_request(tree, target)
    mutations = request["mutations"]
    if not (mutations or request["steps"]):
        return {"executed": False, "error": "already_there", "code": 409,
                "detail": "The cells are already in this state — there is nothing to undo."}

    def _read_tree():
        data = pc.fetch_inventory_for(account)
        return pioneer_tree.Tree((data or {}).get("items") or []), data

    def _matches(t):
        return all(list(t.kids.get(c) or []) == k for c, k in target.items() if c in t.by_id)

    response, send_error = _post(request, token)
    if send_error:
        return {**send_error, "executed": False, "detail": send_error.get("detail") or "The gateway refused the undo."}
    data_after = None
    for attempt in range(5):
        if attempt:
            time.sleep(VERIFY_WAIT * 2)
            _post(request, token)  # إعادة إرسال نفس الحالة النهائية — آمنة
        try:
            tree_after, data = _read_tree()
        except Exception:
            continue
        if _matches(tree_after):
            data_after = data
            break
    elapsed = int((time.time() - started) * 1000)
    if data_after is None:
        store.log_action(conn, account, "undo", {"cells": len(target)}, "failed",
                         {"error": "verification_failed"}, len(mutations))
        return {"executed": False, "error": "verification_failed", "code": 502,
                "detail": "The undo was not confirmed — refresh the state with SYNC before any other step.",
                "items": len(mutations), "elapsed_ms": elapsed}
    refreshed = _refresh_data(conn, account, data_after)
    store.log_action(conn, account, "undo", {"cells": len(target), "mutations": len(mutations)},
                     "executed", response or {}, len(mutations))
    return {"executed": True, "items": len(mutations), "elapsed_ms": elapsed,
            "refreshed": refreshed, "result": {"ok": True, "code": 200, "response": response or {}},
            "detail": "We returned %d cells to the state they had before the move." % len(mutations)}


def move(conn, account, target_container, rows, target_wrapper_id="", target_slot="",
         fallback_if_full=False, carry_instance_ids=None, swap=None):
    rows = [r for r in (rows or []) if r.get("instance_id")]
    # كل صف ممكن يحمل current_total: مجموع نوعه اللي الطالب قاس عليه؛ الشجرة
    # مختلفة عنه معناها حركة تانية لسه ملحقش تظهر، والمبلغ بيطلع غلط.
    stale = [(r.get("name") or "this item", int(r["current_total"]),
              int(r.get("now_total") or r["current_total"])) for r in rows
             if r.get("current_total") is not None
             and int(r["current_total"]) != int(r.get("now_total") or r["current_total"])]
    if stale:
        name, was, is_now = stale[0]
        return {"executed": False, "error": "stale_total", "code": 409,
                "detail": "The total of %s changed since the move started (%d now, %d expected) — "
                          "read the backpack again and retry." % (name, is_now, was),
                "preview": {"method": "POST", "url": _url(), "items": []}}
    carry = [str(i) for i in (carry_instance_ids or []) if i]
    moves = [{
        "target_container": target_container,
        "target_wrapper_id": target_wrapper_id,
        "target_slot": target_slot,
        "fallback_if_full": bool(fallback_if_full),
        "swap": bool(swap) if swap is not None else (
            target_container == "loadout" and bool(target_wrapper_id)
            and str(target_slot or "").lower() != "augment"),
        "instance_ids": [str(r["instance_id"]) for r in rows],
    }]
    if carry and str(target_slot or "").lower() == "augment":
        # اللي بيتحط في الشنطة الجديدة: الباكدج لو اتحدد، والكارت/القطيع الصغير
        # على الخانات الأصغر — كل ده الباكند بيوزعه بعد ما يقرا الشنطة الفعلية.
        moves.append({"target_container": "backpack", "target_wrapper_id": "",
                      "target_slot": "", "instance_ids": carry})
    return move_plan(conn, account, moves)
