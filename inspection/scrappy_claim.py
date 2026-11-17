"""أداة استلام لوت Scrappy — على حساب الاختبار Kitsune52#0432 بس.

الأوامر:
    python -m inspection.scrappy_claim whoami
    python -m inspection.scrappy_claim scan          (transaction + snapshot)
    python -m inspection.scrappy_claim snapshot
    python -m inspection.scrappy_claim verify [عدد المتوقع]
    python -m inspection.scrappy_claim dry-run       (يطبع الطلب من غير ما تبعته)
    python -m inspection.scrappy_claim claim --apply (محاولة واحدة بس)
    python -m inspection.scrappy_claim room 6 [--apply] / restore   (مش محتاجهم دلوقتي)

القواعد اللي مكتوبة في الكود نفسه (مش في التعليق بس):
  • التوكن و X-Device-Id من ملف .env في جذع المشروع — مفيش أي توكن في الكود.
  • قبل أي طلب بنطبع اسم الحساب من /v1/shared/profile و /v1/pioneer/raiders،
    ولو مش حساب الاختبار بنوقف فورًا. لو التوكن المطابق لتوكن G22 في القاعدة
    اتستخدم بالغلط — بيقف كمان.
  • أي طبعة للتوكن أو الـ device id بتطلع ***.
  • محاولة القبض الحقيقية واحدة في الجلسة: عدادها في state.json، وأي زيادة
    بيترفض إلا بكلمة --force صريحة.
  • مفيش أسماء عمليات مخمّنة: القبض بيتم على offers/accept (نفس مسار
    التصنيع بتاع الـ Workshop) وبـ offerId مقروء من البوابة أو معطى حرفيًا.
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend import config, items_db, pioneer_client as pc, pioneer_tree, pioneer_write  # noqa: E402

ENV_FILE = os.path.join(ROOT, ".env")
STATE_FILE = os.path.join(ROOT, "state.json")
LOG_DIR = os.path.join(ROOT, "inspection", "pf")
ACCEPT_PATH = "/v1/pioneer/offers/accept"
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-\.]{10,}")
NAME_KEYS = re.compile(r"^(name|display_?name|raider_?name|handle|user_?name|public_?name)$", re.I)


# ---------------------------------------------------------------- credentials
def load_env():
    out = {}
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("FAHMY_TEST_ACCOUNT", "FAHMY_TEST_TOKEN", "FAHMY_TEST_DEVICE_ID"):
        out.setdefault(key, "")
        if not out[key]:
            out[key] = os.environ.get(key, "")
    return out


def redact(text):
    return JWT_RE.sub("***", str(text))


class Log:
    """كل السطر بيمر على redact قبل ما يطلع — التوكن مابيتطبعش أبدا."""

    def __init__(self, name):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.path = os.path.join(LOG_DIR, "%s_%s.log" % (name, time.strftime("%Y%m%d_%H%M%S")))
        self.fh = open(self.path, "w", encoding="utf-8")

    def say(self, *parts):
        line = " ".join(redact(p) for p in parts)
        print(line)
        self.fh.write(line + "\n")
        self.fh.flush()

    def close(self):
        try:
            self.fh.close()
        except OSError:
            pass


def headers(token, env):
    h = pc.headers(token, pc.load_manifest())
    if env.get("FAHMY_TEST_DEVICE_ID"):
        h["X-Device-Id"] = env["FAHMY_TEST_DEVICE_ID"]
    return h


# ---------------------------------------------------------------- identity
def names_in(payload, out=None):
    found = [] if out is None else out
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str) and NAME_KEYS.match(str(key)) and value.strip():
                found.append(value.strip())
            else:
                names_in(value, found)
    elif isinstance(payload, list):
        for value in payload:
            names_in(value, found)
    return found


def _db_accounts():
    """حسابات القاعدة: (name, display, embark_id) — للمقارنة بالحساب المسموح."""
    import sqlite3
    db = sqlite3.connect(config.DB_FILE)
    try:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT name, display_name, embark_id FROM accounts").fetchall()]
    finally:
        db.close()


def token_claims(token):
    """يفك claims التوكن من غير ما يطبعه. بيرجع None لو مش توكن pioneer صالح."""
    import base64
    parts = str(token).split(".")
    if len(parts) != 3:
        return None

    def pad(s):
        return s + "=" * (-len(s) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(pad(parts[1])).decode("utf-8", "ignore"))
    except Exception:
        return None
    ext = payload.get("ext") or {}
    return {"client_id": str(ext.get("client_id") or ""),
            "embark_id": str(ext.get("embark_user_id") or ""),
            "sub": str(payload.get("sub") or "")}


def guard_account(env, log):
    token = env.get("FAHMY_TEST_TOKEN") or ""
    if not token:
        log.say("⛔ .env مافيه FAHMY_TEST_TOKEN — ملي ملف .env الأول (مش هنا في الشات).")
        return None
    wanted = (env.get("FAHMY_TEST_ACCOUNT") or "Kitsune52#0432").strip()
    core = wanted.split("#")[0].strip().lower()
    claims = token_claims(token) or {}
    if claims.get("client_id") != "embark-pioneer":
        log.say("⛔ التوكن ده مش توكن بوابة اللعبة (client_id=%s) — وقفت." % (claims.get("client_id") or "؟"))
        return None
    # المقارنة بـ embark_user_id (أول 24 حرف في JWT هيدر مشترك بين كل الحسابات،
    # فمفيش مقارنة بادئة تنفع — كانت بتدي false positive على G21).
    log.say("· فحص الملكية: embark_id=%s sub=%s" % (claims.get("embark_id") or "؟", claims.get("sub") or "؟"))
    for row in _db_accounts():
        if row.get("embark_id") and row["embark_id"] == claims.get("embark_id"):
            label = row.get("display_name") or row.get("name")
            if core not in str(row.get("name")).lower() and core not in str(label).lower():
                log.say("⛔ الرادار: التوكن ده بتاع الحساب %s — ممنوع نشتغل بيه." % label)
                return None
            log.say("· التوكن مطابق لصف الحساب %s في القاعدة (الحساب المسموح)." % label)
    seen = []
    for path in ("/v1/shared/profile", "/v1/pioneer/raiders"):
        try:
            payload = pc.request(path, token=token)
        except Exception as exc:
            log.say("  · %-22s رجّعت خطأ قراءة: %s" % (path, str(exc)[:140]))
            continue
        got = names_in(payload)
        seen.extend(got)
        log.say("  · %-22s الأسماء اللي رجّعتها: %s" % (path, got or "—"))
    hit = [n for n in seen if core in n.lower() or n.lower().startswith(core)]
    if not hit:
        log.say("⛔ هوية الحساب مش %s — وقفت. اللي ظهر: %s" % (wanted, seen or "ولا اسم"))
        return None
    log.say("✔ الهوية مؤكدة: %s (من %s)" % (wanted, ", ".join(seen)))
    return token


# ---------------------------------------------------------------- state journal
def read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------- room
def stash_cells(tree, lay):
    """خانات الستاش الممتلئة: (cell_id, item_id, name, qty, value)."""
    rows = []
    for cell in lay["stash"]["slots"]:
        item = tree.first_child(cell)
        if not item:
            continue
        row = items_db.dossier(asset_id=str(tree.by_id[item].get("gameAssetId") or "")) or {}
        qty = int(tree.amount(item) or 0)
        unit = int(row.get("value") or 0)
        rows.append({"cell": cell, "item": item, "name": tree.label(item),
                     "type": row.get("type") or "", "is_weapon": bool(row.get("is_weapon")),
                     "qty": qty, "unit_value": unit, "stack_value": qty * unit,
                     "priced": bool(unit)})
    return rows


def room_plan(token, n, log):
    data = pc.request("/v1/pioneer/inventory", token=token)
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    lay = pioneer_tree.layout(tree)
    cells = list(lay["stash"]["slots"])
    filled = [c for c in cells if tree.first_child(c)]
    free = len(cells) - len(filled)
    log.say("الستاش: %d خانة، %d ممتلئة، %d فاضية" % (len(cells), len(filled), free))
    need = max(0, int(n) - free)
    if not need:
        log.say("مفيش حاجة لازم تتنقل — في %d خانة فاضية وأنت عايز %d." % (free, n))
        return [], free, need
    priced = stash_cells(tree, lay)
    # الأسلحة/Duffel والقطع اللي عليها مرفقات مش مرشّحة للتفريغ أبدًا.
    def protected(row):
        return row["is_weapon"] or "weapon" in row["type"].lower() or "armor" in row["type"].lower()
    pool = [r for r in priced if not protected(r)]
    pool.sort(key=lambda r: (not r["priced"], r["stack_value"], r["name"].lower()))
    picks = pool[:need]
    log.say("لازم نفضّي %d خانة — أرخص %d عنصر في الستاش:" % (need, len(picks)))
    for r in picks:
        log.say("  · %-34s ×%-4s قيمة %s %s" % (r["name"][:34], r["qty"],
                                                r["stack_value"] or "؟", "" if r["priced"] else "(سعرها مش معروف)"))
    bodies = []
    for r in picks:
        body, _dest, _moved, _lay = pioneer_tree.plan_move(tree, [r["item"]], "overflow", "", "")
        bodies.append({"record": r, "requests": body["requests"]})
    return bodies, free, need


def print_request(method, path, body, env, log, prefix="  →"):
    url = path if str(path).startswith("http") else pc.BASE + path
    shown = dict(pc.headers(env.get("FAHMY_TEST_TOKEN") or "", pc.load_manifest()))
    if env.get("FAHMY_TEST_DEVICE_ID"):
        shown["X-Device-Id"] = env.get("FAHMY_TEST_DEVICE_ID")
    shown = {k: ("***" if k.lower() in ("authorization", "x-device-id") else v)
             for k, v in shown.items()}
    log.say(prefix, method, url)
    log.say(prefix, "  headers:", json.dumps(shown, ensure_ascii=False))
    log.say(prefix, "  body:", json.dumps(body, ensure_ascii=False))


def make_room(token, env, n, apply_, log):
    bodies, free, need = room_plan(token, n, log)
    if not bodies:
        return {"moved": [], "need": need}
    state = read_state()
    journal = state.get("room") or []
    if apply_:
        # القيد ده مهم: بنسجّل قبل أول كتابة، فالسقوط في نص النقل مالوش أثر فقد.
        entry = {"account": env.get("FAHMY_TEST_ACCOUNT"), "made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "steps": [{"item": b["record"]["item"], "cell": b["record"]["cell"],
                            "name": b["record"]["name"], "qty": b["record"]["qty"],
                            "done": False} for b in bodies]}
        journal.append(entry)
        state["room"] = journal
        write_state(state)
        log.say("سجّلنا %d خطوة في state.json قبل أي كتابة." % len(entry["steps"]))
    for b in bodies:
        for req in b["requests"]:
            print_request("POST", pioneer_write.MUTATE_PATH, req, env, log, prefix="  →")
        if not apply_:
            continue
        for req in b["requests"]:
            try:
                pc.post_json(pioneer_write.MUTATE_PATH, req, token=token)
            except Exception as exc:
                log.say("  ⛔ النقل اتوقف عند %s: %s" % (b["record"]["name"], str(exc)[:200]))
                return {"moved": [], "need": need, "error": str(exc)[:200]}
        log.say("  ✔ اتنقل للأوفر فلو: %s ×%s من خانة %s" % (
            b["record"]["name"], b["record"]["qty"], b["record"]["cell"][:8]))
    if apply_:
        fresh = pioneer_tree.Tree((pc.request("/v1/pioneer/inventory", token=token) or {}).get("items") or [])
        moved = [b["record"] for b in bodies if not fresh.parent.get(b["record"]["item"])]
        state = read_state()
        if state.get("room"):
            for step in state["room"][-1]["steps"]:
                if any(m["item"] == step["item"] for m in moved):
                    step["done"] = True
            write_state(state)
        log.say("التحقق: %d من %d قطعة بقيت من غير أب (= في الأوفر فلو)." % (
            len(moved), len(bodies)))
        return {"moved": moved, "need": need}
    log.say("dry-run: ماتبعتش ولا طلب نقل.")
    return {"moved": [], "need": need}


def restore(token, env, apply_, log):
    state = read_state()
    journal = state.get("room") or []
    if not journal:
        log.say("مفيش حاجة مسجلة في state.json — مفيش حاجة نرجّعها.")
        return
    data = pc.request("/v1/pioneer/inventory", token=token)
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    todo = [s for entry in journal for s in entry.get("steps", []) if s.get("item") in tree.by_id]
    log.say("المسجّل: %d قطعة. هنبعت لكل واحدة update يخليها في خانتها الأصلية." % len(todo))
    for step in todo:
        try:
            body, _d, _m, _l = pioneer_tree.plan_move(tree, [step["item"]], "stash",
                                                      "", step["cell"])
        except pioneer_tree.TreeError as exc:
            log.say("  · %s: %s" % (step["name"], redact(exc.detail)[:160]))
            continue
        for req in body["requests"]:
            print_request("POST", pioneer_write.MUTATE_PATH, req, env, log, prefix="  →")
        if not apply_:
            continue
        for req in body["requests"]:
            try:
                pc.post_json(pioneer_write.MUTATE_PATH, req, token=token)
            except Exception as exc:
                log.say("  ⛔ الإرجاع اتوقف عند %s: %s" % (step["name"], str(exc)[:200]))
                return
        log.say("  ✔ رجعت: %s" % step["name"])
    if apply_:
        state["room"] = []
        write_state(state)
        log.say("state.json اتفرّغ بعد الإرجاع.")


# ---------------------------------------------------------------- claim
def transactions_in(payload, out=None):
    """أي كائن جوه رد البوابة فيه offerId/transactionId — بنأخده كما هو من غير فلترة."""
    found = [] if out is None else out
    if isinstance(payload, dict):
        keys = {str(k).lower(): v for k, v in payload.items()}
        if "offerid" in keys or "transactionid" in keys:
            found.append({"offer_id": keys.get("offerid"), "transaction_id": keys.get("transactionid"),
                          "owner_instance_id": keys.get("ownerinstanceid"),
                          "duration_seconds": keys.get("durationinseconds"),
                          "amount": keys.get("amount"), "start_time": keys.get("starttime"),
                          "raw": {k: v for k, v in payload.items() if not isinstance(v, (dict, list))}})
        for value in payload.values():
            transactions_in(value, found)
    elif isinstance(payload, list):
        for value in payload:
            transactions_in(value, found)
    return found


READ_ROUTES = ("/v1/pioneer/bonuses", "/v1/pioneer/quests", "/v1/pioneer/inventory",
               "/v1/pioneer/raiders", "/v1/shared/profile")


def read_routes(token, log):
    """يقرا المسارات الرسمية الليثبت إنها شغالة ويرجع {path: payload}."""
    out = {}
    for path in READ_ROUTES:
        try:
            out[path] = pc.request(path, token=token)
        except Exception as exc:
            out[path] = None
            log.say("  · %-24s رجّعت: %s" % (path, str(exc)[:120]))
    return out


def find_transaction(token, log, payloads=None):
    """بنقرا المسارات الموجودة فعلاً بحثًا عن transaction — من غير ما نخمّن اسم."""
    for path, payload in (payloads or read_routes(token, log)).items():
        if payload is None:
            continue
        found = transactions_in(payload)
        log.say("  · %-24s %d transaction" % (path, len(found)))
        for tx in found[:5]:
            log.say("      %s" % json.dumps(tx["raw"], ensure_ascii=False)[:300])
        if found:
            return found[0], path
    return None, ""


def snapshot(token, log, payloads=None):
    """سنابشوت الكميات قبل الاستلام — per instance و per asset."""
    data = payloads.get("/v1/pioneer/inventory") if payloads else \
        pc.request("/v1/pioneer/inventory", token=token)
    items = (data or {}).get("items") or []
    per_instance, per_asset = {}, {}
    for row in items:
        iid, asset = str(row.get("instanceId") or ""), str(row.get("gameAssetId") or "")
        if not iid:
            continue
        per_instance[iid] = int(row.get("amount") or 0)
        if asset:
            per_asset[asset] = per_asset.get(asset, 0) + int(row.get("amount") or 0)
    state = read_state()
    state["snapshot"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "nodes": len(per_instance), "instances": per_instance, "assets": per_asset}
    write_state(state)
    total = sum(per_asset.values())
    log.say("✔ سنابشوت: %d عقدة، %d صنف، مجموع وحدات %d — محفوظ في state.json" % (
        len(per_instance), len(per_asset), total))
    return per_instance, per_asset


def verify(token, log, expected=None, payloads=None):
    """يقارن الشجرة الحالية بالسنابشوت ويطبع الفرق لكل صنف بالاسم."""
    state = read_state()
    snap = state.get("snapshot") or {}
    if not snap.get("assets"):
        log.say("⛔ مفيش snapshot في state.json — اعمل snapshot الأول.")
        return None
    data = payloads.get("/v1/pioneer/inventory") if payloads else \
        pc.request("/v1/pioneer/inventory", token=token)
    items = (data or {}).get("items") or []
    now_asset, now_inst, names = {}, {}, {}
    for row in items:
        iid, asset = str(row.get("instanceId") or ""), str(row.get("gameAssetId") or "")
        if not iid:
            continue
        now_inst[iid] = int(row.get("amount") or 0)
        if asset:
            now_asset[asset] = now_asset.get(asset, 0) + int(row.get("amount") or 0)
            names[asset] = row.get("definitionId") or asset
    before = snap["assets"]
    rows = []
    for asset in set(before) | set(now_asset):
        delta = now_asset.get(asset, 0) - before.get(asset, 0)
        if delta:
            rows.append((delta, asset))
    rows.sort(reverse=True)
    log.say("قبل: %d عقدة / %d وحدة  —  بعد: %d عقدة / %d وحدة" % (
        snap.get("nodes", 0), sum(before.values()), len(now_inst), sum(now_asset.values())))
    log.say("عقد جديدة %d، اختفت %d" % (
        len([k for k in now_inst if k not in snap["instances"]]),
        len([k for k in snap["instances"] if k not in now_inst])))
    if not rows:
        log.say("⚠ مفيش ولا زيادة في ولا صنف.")
    for delta, asset in rows:
        row = items_db.dossier(asset_id=asset) or {}
        log.say("  · %-34s %+d" % ((row.get("name") or asset)[:34], delta))
    if expected is not None:
        got = sum(d for d, _ in rows if d > 0)
        log.say("المتوقع %d وحدة — اللي نزل %d (%s)" % (expected, got, "طابق" if got == expected else "مطابقش"))
    return rows


def claim(token, env, offer_id, apply_, log, amount_given=None, expect=None):
    """القبض: نفس شكل قبول التصنيع. offerId/amount من transaction البوابة أو من المستخدم حرفيًا."""
    state = read_state()
    used = int(state.get("claim_attempts") or 0)
    if used and "--force" not in sys.argv:
        log.say("⛔ اتبعت %d محاولة قبض في الجلسة دي — القاعدة: واحدة بس. (--force لو تعرف إن ده مطلوب)" % used)
        return
    payloads = read_routes(token, log)
    tx, route, src = None, "", ""
    if offer_id is None:
        tx, route = find_transaction(token, log, payloads)
        if not tx:
            log.say("⛔ ملقيتش ولا transaction بتاعة Scrappy في بيانات Kitsune52 الحقيقية. "
                    "لو الرقم جاي من رد API فعلي (مش تخمين) نبعت بيه: --offer-id N --amount M")
            return
        offer_id = tx.get("offer_id")
        src = "من transaction البوابة (%s)" % route
    else:
        src = "من المستخدم — رقم مقروء من رد API حقيقي (Rampart)"
    if offer_id is None:
        log.say("⛔ الـ transaction اللي لقينها مالهاش offerId: %s" % json.dumps(tx, ensure_ascii=False))
        return
    amount = tx.get("amount") if tx is not None else amount_given
    if amount is None and tx is not None:
        amount = amount_given
    if amount is None:
        log.say("⛔ مفيش amount: لا في الـ transaction ولا اتgiven بالمفتاح --amount.")
        return
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        log.say("⛔ الـ amount مش رقم: %r" % (amount,))
        return
    if amount <= 0:
        log.say("⛔ شرط إيقاف: الـ amount طالع %s (صفر أو سالب) — وقفت." % amount)
        return
    body = {"offerId": int(offer_id), "itemsToConsume": [], "amount": amount}
    log.say("مصدر الأرقام: %s" % src)
    log.say("الطلب اللي هيتبعت (نفس شكل قبول التصنيع بالظبط):")
    print_request("POST", ACCEPT_PATH, body, env, log)
    if not apply_:
        log.say("dry-run: ماتبعتش حاجة.")
        return
    snapshot(token, log, payloads)
    state = read_state()
    state["claim_attempts"] = used + 1
    state["last_claim"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "body": body,
                           "route": route, "source": src, "transaction": tx or {}}
    write_state(state)
    try:
        response = pc.post_json(ACCEPT_PATH, body, token=token)
    except Exception as exc:
        log.say("⛔ رد البوابة الحرفي: %s" % str(exc)[:600])
        log.say("· المحاولة دي اتصرفت (%d من 1) — مفيش إعادة تجريب ولا أسماء تانية." % (used + 1))
        return
    log.say("✔ رد البوابة الكامل:")
    log.say(json.dumps(response, ensure_ascii=False)[:4000])
    # المقارنة بعد الاستلام: بنقرا الشجرة من جديد (payloads القديمة دي سنابشوت ما قبل).
    verify(token, log, expected=expect)


def tree_diff(before, after):
    b, a = _amounts(before), _amounts(after)
    return {"created": len([k for k in a if k not in b]),
            "deleted": len([k for k in b if k not in a]),
            "grown": sum(1 for k in a if k in b and a[k] > b[k]),
            "gained": sum(a[k] - b[k] for k in a if k in b and a[k] > b[k]),
            "nodes_before": len(b), "nodes_after": len(a)}


def _amounts(payload):
    items = (payload.get("items") if isinstance(payload, dict) else payload) or []
    out = {}
    for row in items:
        iid = str(row.get("instanceId") or "")
        if iid:
            out[iid] = int(row.get("amount") or 0)
    return out


# ---------------------------------------------------------------- cli
def demo_dry_run(env, log):
    """بيطبع شكل الطلبات من غير توكن ومن غير أي طلب شبكي — للمراجعة قبل التشغيل."""
    cell, item, qty = "00000000-0000-4000-8000-000000000000", "11111111-1111-4111-8111-111111111111", 24
    log.say("الشكل الحقيقي اللي هيتبعت لكل قطعة (update بيمسح الخانة، والعنصر يبقى من غير أب):")
    print_request("POST", pioneer_write.MUTATE_PATH, {"mutations": [
        {"discriminator": "update", "instanceId": cell, "slots": [""], "amount": qty}],
        "requestId": ""}, env, log)
    log.say("والإرجاع (restore) بيحط نفس الـ instance في نفس الـ cell:")
    print_request("POST", pioneer_write.MUTATE_PATH, {"mutations": [
        {"discriminator": "update", "instanceId": cell, "slots": [item], "amount": qty}],
        "requestId": ""}, env, log)
    log.say("وقبض اللوت على نفس مسار قبول التصنيع بتاع الـ Workshop:")
    print_request("POST", ACCEPT_PATH, {"offerId": 0, "itemsToConsume": [], "amount": 1}, env, log)
    log.say("· offerId بيجي من transaction مقروءة من البوابة (claim --offer-id N لو معاك الرقم من بره).")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    cmd = args[0] if args else "whoami"
    apply_ = "--apply" in argv
    log = Log("scrappy_claim_" + cmd.replace("-", "_"))
    env = load_env()
    log.say("== أمر: %s | حساب الاختبار: %s | .env: %s ==" % (
        cmd, env.get("FAHMY_TEST_ACCOUNT") or "Kitsune52#0432",
        "موجود" if os.path.isfile(ENV_FILE) else "مش موجود"))
    if cmd == "dry-run" and not env.get("FAHMY_TEST_TOKEN"):
        log.say("⚠ مفيش توكن في .env — فبنطبع شكل الطلب فقط (بدون معرّفات حقيقية وبدون أي طلب).")
        demo_dry_run(env, log)
        log.say(" اللوج: %s" % log.path)
        log.close()
        return 0
    token = guard_account(env, log)
    if not token:
        log.close()
        return 2
    try:
        if cmd == "whoami":
            log.say("التوكن: *** (%d حرف) | صلاحيته لحد: %s" % (
                len(token), time.strftime("%Y-%m-%d %H:%M", time.localtime(pc.token_expiry(token)))))
        elif cmd == "scan":
            payloads = read_routes(token, log)
            find_transaction(token, log, payloads)
            snapshot(token, log, payloads)
        elif cmd == "snapshot":
            snapshot(token, log)
        elif cmd == "verify":
            verify(token, log, int(args[1]) if len(args) > 1 else None)
        elif cmd == "dry-run":
            claim(token, env, _offer_id(argv), False, log, _amount(argv), _flag(argv, "--expect"))
        elif cmd == "room":
            make_room(token, env, int(args[1]) if len(args) > 1 else 6, apply_, log)
        elif cmd == "restore":
            restore(token, env, apply_, log)
        elif cmd == "claim":
            claim(token, env, _offer_id(argv), apply_, log, _amount(argv), _flag(argv, "--expect"))
        else:
            log.say("أمر غير معروف: %s" % cmd)
    finally:
        log.say(" اللوج: %s" % log.path)
        log.close()
    return 0


def _offer_id(argv):
    return _flag(argv, "--offer-id")


def _amount(argv):
    return _flag(argv, "--amount")


def _flag(argv, name):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return int(argv[i + 1])
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv))
