"""Scrappy — ديك الورشة: مستواه، أرزاقه، وتحويل زراعته — كله من البوابة الرسمية.

المصدر: data/scrappy_catalog.json (38 عرض RoundCrafting من game-data الرسمي)
+ شجرة المخزون الحيّة من `GET /v1/pioneer/inventory`. مفيش أي سيرفر وسيط.

اللي اتقاس على البوابة (2026-11-01):
  • `POST /v1/pioneer/offers/accept` بيشتغل على عروض kind="food": البوابة بتصرف
    الخامة من الشجرة لوحدها وبترجّع transaction فيها offerId + startTime — نفس
    شكل التصنيع في backend/workshop.py.
  • عروض kind="rounds" (قبض الدقائق) كل أجسام القبول اترفضت 400 internal error على
    ثلاث حسابات بمستويات مختلفة، حتى مع `itemsToConsume` كامل من عقدة حقيقية
    (الـ decode كان بينجح، فالرفض من المعالج مش من الترميز). ومسارات
    claim/complete/cancel كلها 404 — offers/accept هو مسار العروض الوحيد.
    فالصفوف دي بتتعرض كأرزاق ومواعيد رسمية، مش كأزرار تنفيذ.
  • مكافأة العرض المؤجّل بتتحجز عند السيرفر: قياس قبول ليمون خصم الخامة
    فورًا وعمل transaction، لكن الشجرة ما زادش فيها أي حاجة بعد المدة. أي لوت
    ينزل فعليًا (مثلًا بعد تشغيل اللعبة) بيشوفه `collect()` كفارق عن آخر سنابشوت.
"""
import json
import os
import time

from . import config, items_db, pioneer_client as pc, pioneer_tree, pioneer_write, store, workshop

CATALOG_FILE = os.path.join(config.DATA_DIR, "scrappy_catalog.json")
ACCEPT_PATH = workshop.ACCEPT_PATH
TX_KEY = "scrappy_tx:%s"
GEN_TIER = {"1657228973": 1, "2041317243": 2, "1434069496": 3,
            "2080275953": 4, "1781867314": 5}
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
MAX_AMOUNT = 20
_TX_TTL = 86400

_cache = {"path": "", "stamp": 0, "data": {}}


def catalog():
    """كتالوج عروض الديك — بيتحمّل من جديد لو الملف اتبنى."""
    try:
        stamp = os.path.getmtime(CATALOG_FILE)
    except OSError:
        return {}
    if _cache["path"] != CATALOG_FILE or _cache["stamp"] != stamp:
        try:
            with open(CATALOG_FILE, encoding="utf-8") as fh:
                _cache["data"] = json.load(fh) or {}
        except Exception:
            _cache["data"] = {}
        _cache["path"], _cache["stamp"] = CATALOG_FILE, stamp
    return _cache["data"]


def live_tree(account):
    """شجرة الحساب الحيّة من البوابة (من غير كاش) — هي مصدر كل الأرقام."""
    data = pc.fetch_inventory_for(account) or {}
    return data, pioneer_tree.Tree(data.get("items") or [])


def _icon(asset_id):
    return items_db.icon_for(items_db.find(asset_id=asset_id))


def _name(asset_id):
    row = (pioneer_tree.asset_names() or {}).get(str(asset_id))
    if isinstance(row, dict):
        return row.get("display_name") or row.get("game_asset_name") or str(asset_id)
    return str(row or asset_id)


def _offer(offer_id):
    for row in catalog().get("offers") or []:
        if int(row.get("offer_id") or 0) == int(offer_id or 0):
            return row
    return {}


def generator(tree):
    """عقدة الديك: أعلى مستوى موجود في الشجرة الحيّة."""
    best = {"tier": 0, "asset_id": "", "instance_id": "", "label": "", "icon": ""}
    for iid, node in tree.by_id.items():
        tier = GEN_TIER.get(str(node.get("gameAssetId")))
        if not tier or tier <= best["tier"]:
            continue
        label = tree.label(iid) or ("Scrappy " + ROMAN.get(tier, ""))
        best = {"tier": int(tier), "asset_id": str(node.get("gameAssetId")),
                "instance_id": str(iid), "label": label,
                "icon": _icon(node.get("gameAssetId"))}
    return best


def totals(tree, asset_ids):
    """مجموع الكميات الحيّة لكل asset id مطلوب."""
    wanted = {str(a) for a in asset_ids if str(a or "")}
    acc = {a: 0 for a in wanted}
    for node in tree.by_id.values():
        aid = str(node.get("gameAssetId"))
        if aid in acc:
            acc[aid] += int(node.get("amount") or 0)
    return acc


def rounds_asset():
    return str(catalog().get("rounds_asset") or "-1869396984")


def rounds_of(tree):
    return int(totals(tree, [rounds_asset()]).get(rounds_asset(), 0))


def _lines(tree, cost, amount=1):
    """سطور التكلفة: محتاج قد إيه، وعندك قد إيه."""
    have = totals(tree, [c.get("asset_id") for c in cost or []])
    out, short = [], 0
    for row in cost or []:
        need = int(row.get("amount") or 0) * max(1, int(amount or 1))
        got = int(have.get(str(row.get("asset_id")), 0))
        missing = max(0, need - got)
        short += missing
        out.append({"asset_id": str(row.get("asset_id") or ""), "name": row.get("name") or "",
                    "image": row.get("image") or _icon(row.get("asset_id")),
                    "need": need, "have": got, "missing": missing, "ok": missing == 0})
    return out, short


def _label(row):
    """عنوان مقروء: الزراعي باسم الخضّة، والدفعة باسم الدقيقة (عناوين Embark مش مطبوعة)."""
    title = str(row.get("title") or "")
    if row.get("kind") == "food":
        crops = ", ".join(str(c.get("name") or "") for c in row.get("cost") or [])
        return (crops or title.replace("Scrappy", "")).strip()
    mins = title.split("Minute")[-1].strip() if "Minute" in title else ""
    return ("Minute %s" % mins) if mins else title


def _offer_rows(kind, tree, tier=0):
    """صفوف الكتالوج بنوعها + حالتها الحيّة. kind: food | rounds (عروض مستوى الحساب بس)."""
    out = []
    for row in catalog().get("offers") or []:
        if row.get("kind") != kind:
            continue
        if kind == "rounds" and int(row.get("tier") or 0) != int(tier or 0):
            continue
        lines, short = _lines(tree, row.get("cost"), 1)
        out.append({
            "offer_id": int(row.get("offer_id")), "tier": int(row.get("tier") or 0),
            "kind": kind, "title": row.get("title") or "", "label": _label(row),
            "duration_seconds": int(row.get("duration_seconds") or 0),
            "cost": lines, "reward": row.get("reward") or [],
            "reward_pool": (row.get("reward_pool") or [])[:6],
            "reward_total": int(row.get("reward_total") or 0),
            "affordable": bool(lines) and short == 0,
            "executable": kind == "food",
        })
    out.sort(key=lambda r: (r["tier"], r["duration_seconds"], r["title"]))
    return out


def upgrade_row(tier, tree):
    """ترقية الديك للمستوى اللي فوق: التكلفة الرسمية وحساب المتوفر (تنفيذها على مسار الأدوات مش العروض)."""
    for row in catalog().get("upgrades") or []:
        if int(row.get("tier") or 0) != int(tier or 0):
            continue
        cost = row.get("cost") or []
        lines, short = _lines(tree, cost, 1)
        return {"tier": int(tier or 0), "label": row.get("label") or "",
                "next_label": row.get("next_label") or "", "next_asset_id": row.get("next_asset_id") or "",
                "cost": lines, "shortfall": short,
                "ready": bool(cost) and short == 0, "max": not cost}
    return {"tier": int(tier or 0), "label": "", "next_label": "", "next_asset_id": "",
            "cost": [], "shortfall": 0, "ready": False, "max": True}


# ------------------------------------------------------------------ اللوت اللي وصل
def _stored_qty(conn, account):
    """instance_id -> qty من آخر سنابشوت محفوظ؛ النسخة اللي ملهاش صف = جديدة."""
    try:
        rows = conn.execute("SELECT instance_id, qty FROM instances WHERE account=?",
                            (account,)).fetchall()
    except Exception:
        return {}
    return {str(r["instance_id"]): int(r["qty"] or 0) for r in rows}


def landed_since_snapshot(conn, account, tree):
    """الزيادات في نفس نسخ السنابشوت — أثر القبض الحقيقي، مش نسخة اتفرّغت."""
    stored = _stored_qty(conn, account)
    groups = {}
    for iid, node in tree.by_id.items():
        before = stored.get(str(iid))
        if before is None:
            continue
        gained = int(tree.amount(iid) or 0) - before
        if gained <= 0:
            continue
        name = tree.label(iid)
        row = groups.setdefault(name, {"name": name, "gained": 0, "stacks": 0,
                                       "image": _icon(node.get("gameAssetId"))})
        row["gained"] += gained
        row["stacks"] += 1
    return sorted(groups.values(), key=lambda r: (-r["gained"], str(r["name"]).lower()))


# ------------------------------------------------------------------ المواعيد المفتوحة
def _tx_list(conn, account):
    return list((store.get_meta(conn, TX_KEY % account) or {}).get("items") or [])


def _tx_save(conn, account, rows):
    if rows:
        store.set_meta(conn, TX_KEY % account, {"items": rows[:40]})
    else:
        conn.execute("DELETE FROM meta WHERE key=?", (TX_KEY % account,))
        conn.commit()


def timers(conn, account, tree=None):
    """المواعيد اللي لسه شغّالة + أي واحد خلص يتقاس أثره على الشجرة ويُقفل."""
    rows = _tx_list(conn, account)
    if not rows:
        return [], []
    if tree is None:
        _, tree = live_tree(account)
    now = int(time.time())
    open_rows, settled = [], []
    for tx in rows:
        eta = int(tx.get("start_time") or 0) + int(tx.get("duration") or 0)
        if now < eta and tx.get("start_time"):
            open_rows.append(dict(tx, label=_label(_offer(tx.get("offer_id"))),
                                  remaining=max(0, eta - now), eta=eta))
            continue
        if int(tx.get("start_time") or 0) and now - int(tx["start_time"]) > _TX_TTL:
            continue
        after = totals(tree, [r.get("asset_id") for r in tx.get("reward") or []])
        before = tx.get("before_totals") or {}
        landed = [{"asset_id": aid, "name": _name(aid), "image": _icon(aid),
                   "gained": after.get(aid, 0) - int(before.get(aid, 0))}
                  for aid in after if after.get(aid, 0) > int(before.get(aid, 0))]
        settled.append({"offer_id": tx.get("offer_id"), "title": tx.get("title") or "",
                        "label": _label(_offer(tx.get("offer_id"))),
                        "ended_at": eta, "landed": landed,
                        "landed_total": sum(l["gained"] for l in landed)})
    _tx_save(conn, account, open_rows)
    return open_rows, settled


# ------------------------------------------------------------------ الواجهة
def view(conn, account):
    out = {"account": account, "found": False, "tier": 0, "tier_label": "", "icon": "",
           "rounds": 0, "feed": [], "claims": [], "upgrade": {}, "timers": [], "settled": [],
           "landed": [], "writes": pioneer_write.status(),
           "write_paused": pioneer_write.paused()}
    if not account or account == "ALL":
        out["error"] = "pick_account"
        return out
    try:
        _, tree = live_tree(account)
    except Exception as err:
        out["error"] = str(err)[:300]
        return out
    gen = generator(tree)
    out.update({"found": bool(gen["tier"]), "tier": gen["tier"], "tier_label": gen["label"],
                "icon": gen["icon"], "instance_id": gen["instance_id"],
                "rounds": rounds_of(tree)})
    out["feed"] = _offer_rows("food", tree)
    out["claims"] = _offer_rows("rounds", tree, tier=gen["tier"])
    out["upgrade"] = upgrade_row(gen["tier"], tree)
    out["timers"], out["settled"] = timers(conn, account, tree)
    try:
        out["landed"] = landed_since_snapshot(conn, account, tree)
    except Exception:
        out["landed"] = []
    return out


def preview(conn, account, offer_id, amount=1):
    """يكلفة العرض بالحالة الحيّة — من غير أي كتابة."""
    row = _offer(int(offer_id or 0))
    if not row:
        return {"ok": False, "error": "unknown_offer", "detail": "The offer is not in the official Scrappy catalog."}
    qty = max(1, min(MAX_AMOUNT, int(amount or 1)))
    try:
        _, tree = live_tree(account)
    except Exception as err:
        return {"ok": False, "error": "gateway_read", "detail": str(err)[:300]}
    lines, short = _lines(tree, row.get("cost"), qty)
    return {"ok": True, "account": account, "offer_id": int(row["offer_id"]),
            "title": row.get("title") or "", "label": _label(row), "kind": row.get("kind"),
            "amount": qty,
            "duration_seconds": int(row.get("duration_seconds") or 0),
            "cost": lines, "shortfall": short, "affordable": short == 0,
            "reward": row.get("reward") or [], "reward_total": int(row.get("reward_total") or 0) * qty,
            "reward_pool": (row.get("reward_pool") or [])[:6],
            "executable": row.get("kind") == "food",
            "note": "" if row.get("kind") == "food" else _not_executable()["detail"]}


def _not_executable():
    return {"ok": False, "error": "claim_not_executable", "code": 409,
            "detail": "Scrappy runs the crop conversions only. The minute claims are refused (400) by the "
                      "gateway in every body shape this token can send, so the button never fires them — "
                      "they belong to the game service."}


def claim(conn, account, offer_id, amount=1, confirmed=False):
    """ينفّذ تحويل زراعي على عرض RoundCrafting رسمي ويحفظ موعده للتحقق."""
    if not confirmed:
        return {"ok": False, "error": "confirmation_required", "code": 428,
                "detail": "Scrappy runs only from the dedicated confirmation window (confirmed=true)."}
    if not account or account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account first."}
    rec = store.get_account(conn, account)
    if not rec:
        return {"ok": False, "error": "unknown_account", "detail": "The account does not exist."}
    if config.DATA_SOURCE != "pioneer":
        return {"ok": False, "error": "legacy_only", "code": 409,
                "detail": "Scrappy runs only in official Pioneer gateway mode."}
    if not rec.get("token"):
        return {"ok": False, "error": "missing_token", "detail": "No stored token for this account."}
    if pioneer_write.paused():
        return {"ok": False, "error": "write_paused", "code": 423, "detail": pioneer_write.PAUSE_DETAIL}

    row = _offer(int(offer_id or 0))
    if not row:
        return {"ok": False, "error": "unknown_offer", "detail": "The offer is not in the official Scrappy catalog."}
    if row.get("kind") != "food":
        return _not_executable()
    try:
        qty = int(amount or 1)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_amount", "detail": "Invalid quantity."}
    if qty < 1 or qty > MAX_AMOUNT:
        return {"ok": False, "error": "bad_amount", "detail": "The quantity is between 1 and %d." % MAX_AMOUNT}

    try:
        _, tree = live_tree(account)
    except Exception as err:
        return {"ok": False, "error": "gateway_read", "detail": str(err)[:300]}
    lines, short = _lines(tree, row.get("cost"), qty)
    if short:
        return {"ok": False, "error": "not_enough", "code": 409, "cost": lines,
                "detail": "Not enough material: %s." % ", ".join(
                    "%s %d/%d" % (l["name"], l["have"], l["need"]) for l in lines if l["missing"])}
    wanted = [c.get("asset_id") for c in (row.get("cost") or [])]
    wanted += [r.get("asset_id") for r in (row.get("reward") or [])]
    before = totals(tree, wanted)

    token = rec["token"]
    body = {"offerId": int(row["offer_id"]), "itemsToConsume": [], "amount": qty}
    try:
        response = pc.post_json(ACCEPT_PATH, body, token=token)
    except Exception as err:
        out = workshop.craft_error(err)
        store.log_action(conn, account, "scrappy:feed", body, "failed", out.get("detail", ""), qty)
        return out
    rejected = workshop.gateway_rejection(response)
    if rejected:
        store.log_action(conn, account, "scrappy:feed", body, "rejected", rejected.get("detail", ""), qty)
        return rejected

    after_data, after_tree = live_tree(account)
    after = totals(after_tree, wanted)
    deltas = [{"asset_id": aid, "name": _name(aid), "image": _icon(aid),
               "delta": after.get(aid, 0) - before.get(aid, 0)}
              for aid in after if after.get(aid, 0) != before.get(aid, 0)]
    created = (((response or {}).get("changeset") or {}).get("offers") or {}).get("transactionsCreated") or []
    seconds = int(row.get("duration_seconds") or 0)
    starts = [int(tx.get("startTime") or 0) for tx in created if tx.get("startTime")]
    entry = {"offer_id": int(row["offer_id"]), "title": row.get("title") or "",
             "tx_id": (created[0].get("id") if created else "") or "",
             "start_time": min(starts) if starts else int(time.time()),
             "duration": seconds, "count": max(1, len(created)), "amount": qty,
             "reward": row.get("reward") or [],
             "before_totals": {str(k): int(v) for k, v in before.items()}}
    _tx_save(conn, account, [entry] + _tx_list(conn, account))
    pioneer_write._refresh_data(conn, account, after_data)
    store.log_action(conn, account, "scrappy:feed", body, "executed",
                     {"transactions": created, "deltas": deltas}, qty)
    spent = ", ".join("%+d %s" % (d["delta"], d["name"]) for d in deltas if d["delta"] < 0)
    return {"ok": True, "executed": True, "account": account, "mode": "offer",
            "offer_id": int(row["offer_id"]), "title": row.get("title") or "", "amount": qty,
            "transaction_id": entry["tx_id"], "eta": entry["start_time"] + seconds,
            "duration_seconds": seconds, "deltas": deltas, "cost": lines,
            "detail": ("Scrappy took %s and booked a %ds timer. The gateway spends the cost on accept; "
                       "the reward is paid by the game service, so the drop is verified on the tree, not promised here."
                       % (spent or "the cost", seconds))}


def collect(conn, account):
    """يقرأ الشجرة الحيّة ويسجّل أي لوت وصل فوق آخر سنابشوت — من غير ما يبعث طلب مقبوض."""
    try:
        data, tree = live_tree(account)
    except Exception as err:
        return {"executed": False, "error": "gateway_read", "detail": str(err)[:300]}
    gains = landed_since_snapshot(conn, account, tree)
    total = sum(g["gained"] for g in gains)
    timers(conn, account, tree)
    if not gains:
        return {"executed": False, "reason": "nothing_landed", "landed": [],
                "detail": "Nothing new in the official tree since the last read."}
    pioneer_write._refresh_data(conn, account, data)
    store.log_action(conn, account, "scrappy:landed", {"account": account, "items": gains},
                     "executed", "%d units landed across %d types." % (total, len(gains)), total)
    return {"executed": True, "reason": "landed", "landed": gains, "total": total,
            "detail": "Loot landed on the existing piles: %d units." % total}


def status(conn, account):
    return view(conn, account)
