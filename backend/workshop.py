"""ورك شوب فحمي: وصفات الصناعة اللي الحساب مسموح بيها فعلًا، وتنفيذها على البوابة.

الوصفات (المكونات + المحطة + مستوى المحطة + المخطوطة) بتقرا من data/items_db.json
— بيانات arctracker.io الرسمية اللي نزلت أوفلاين — والكميات من شجرة المخزن
الرسمية، وحالة التفعيل ومستويات المحطات من backend/knowledge.py.

التصنيع عرض زي عروض التجار: نفس نقطة القبول `POST /v1/pioneer/offers/accept`
برقم العرض المحفوظ في data/craft_catalog.json، والسيرفر بيصرف الخامات من الشجرة
وحده. بنقرأ الشجرة قبل وبعد كل تنفيذ، فخصم الخامات هو التحقق — بدون أي سيرفر وسيط.
"""
import json
import os

from . import config, hideout, items_db, knowledge, pioneer_client as pc, pioneer_tree, store

PLAN_KEY = "workshop_plan:%s"
# سقف الكمية لبند واحد في قائمة التصنيع — عشان زرار MAX ما يطلّعش رقم بلا نهاية.
PLAN_MAX = 99
CATALOG_FILE = os.path.join(config.DATA_DIR, "craft_catalog.json")
ACCEPT_PATH = "/v1/pioneer/offers/accept"

# ترتيب الأعمدة في المصنع — نفس ترتيب شاشات المحطات جوه اللعبة.
STATIONS = (
    ("workbench", "WORKBENCH"),
    ("equipment_bench", "EQUIPMENT BENCH"),
    ("weapon_bench", "WEAPON BENCH"),
    ("med_station", "MEDICAL STATION"),
    ("utility_bench", "UTILITY BENCH"),
    ("explosives_bench", "EXPLOSIVES BENCH"),
    ("refiner", "REFINER"),
    ("in_raid", "FIELD BENCH"),
)
STATION_LABELS = dict(STATIONS)


def station_label(key):
    """اسم المحطة زي ما بيظهر جوه اللعبة، وبديل محلي لمحاولة الميدان."""
    if key == "in_raid":
        return STATION_LABELS["in_raid"]
    return (hideout.label(key) or STATION_LABELS.get(key, key)).upper()


def _station(stations):
    """المحطة الأساسية: أي محطة ثابتة؛ ولو in_raid بس، تبقى محطة الميدان."""
    for key in stations or []:
        if key != "in_raid":
            return key
    return "in_raid"


def owned_by_asset(conn, account):
    """كمية كل asset_id في مخزن الحساب (الستاش + الشنطة + اللوداوت + الأوفر فلو)."""
    if not account or account == "ALL":
        return {}
    rows = conn.execute("SELECT asset_id, SUM(qty) q FROM instances "
                        "WHERE account=? AND asset_id IS NOT NULL AND asset_id <> '' GROUP BY asset_id",
                        (account,)).fetchall()
    return {str(r["asset_id"]): int(r["q"] or 0) for r in rows}


def owned_by_name(conn, account):
    """احتياطي للأغراض اللي ملهاش asset_id في القاعدة (بعض الـ blueprints)."""
    if not account or account == "ALL":
        return {}
    rows = conn.execute("SELECT name, SUM(qty) q FROM instances WHERE account=? GROUP BY name",
                        (account,)).fetchall()
    return {items_db.norm(r["name"]): int(r["q"] or 0) for r in rows}


ALIAS = {"stamp": None, "map": {}, "ids": {}}


def _file_stamp(path):
    try:
        return round(os.path.getmtime(path), 4)
    except OSError:
        return -1.0


def _instances_stamp(conn):
    """علامة رخيصة تتغيّر مع أي سنك جديد — عشان القاموس ما يقعدش على بيانات عتيقة.

    MAX(rowid) بس: أي سنك بيكتب صفوف جديدة فيرقم آخر صف بيزيد، والاستعلام ده بياخد
    ورقة شجرة واحدة (العدّ الكامل كان بيتكرّر مع كل خامة في كل وصفة).
    """
    row = conn.execute("SELECT IFNULL(MAX(rowid), 0) m FROM instances").fetchone()
    return int(row["m"] or 0)


def asset_alias_map(conn):
    """قاموس البدائل: norm(اسم العنصر) -> {كل asset_id مقاس بيمثّله}.

    arctracker ما نشربلش أرقام لبعض الخامات (Hand Drill و8 غيرها)، فالعد بالـ id
    الصارم كان بيرجّع صفر على قطع موجودة فعلاً في المخزن. الأرقام هنا من مصادر
    مقاسة بس: شجرة البوابة الرسمية نفسها (جدول instances)، وفهرس الأصول المحلي،
    وأرقام خامات عروض التصنيع الحقيقية — مفيش ولا رقم مكتوب بإيدنا.
    """
    stamp = (_instances_stamp(conn), _file_stamp(CATALOG_FILE),
             _file_stamp(pioneer_tree.ASSET_INDEX_FILE), _file_stamp(pioneer_tree.ASSET_LOCAL_FILE))
    if ALIAS["stamp"] == stamp:
        return ALIAS["map"]

    def add(label, asset_id):
        key = items_db.norm(label)
        asset_id = str(asset_id or "")
        if key and asset_id:
            out.setdefault(key, set()).add(asset_id)

    out = {}
    for asset_id, row in pioneer_tree.asset_names().items():
        add(row.get("display_name") or row.get("game_asset_name"), asset_id)
    for r in conn.execute("SELECT DISTINCT asset_id, name FROM instances "
                          "WHERE asset_id IS NOT NULL AND asset_id <> '' AND name IS NOT NULL"):
        add(r["name"], r["asset_id"])
    for rec in catalog().values():
        for cost in rec.get("cost") or []:
            add(cost.get("name"), cost.get("asset_id"))
    ALIAS.update(stamp=stamp, map=out, ids={})
    return out


def asset_ids_for(conn, slug="", name="", extra=()):
    """كل أرقام الأصول اللي بتمثّل العنصر ده: الأساسية + البدائل المقاسة.

    بديل مرفوض لو القاعدة نفسها بتقول إن الرقم ده لعنصر تاني — دمج كده كان هيعدّ
    خامات غلط لصالح وصفة تانية.
    """
    memo = ALIAS["ids"]
    cache_key = "%s\x1f%s\x1f%s" % (slug, name, ",".join(sorted(str(a) for a in extra)))
    if cache_key in memo:
        return memo[cache_key]
    row = items_db.by_slug(slug) or {}
    ids = {str(a) for a in (row.get("asset_ids") or []) if str(a or "")}
    ids |= {str(a) for a in extra if str(a or "")}
    key = items_db.norm(name or row.get("name") or "")
    for asset_id in (asset_alias_map(conn).get(key) or ()):
        other = str((items_db.find(asset_id=asset_id) or {}).get("slug") or "")
        if other and slug and other != slug:
            continue
        ids.add(asset_id)
    out = sorted(ids)
    memo[cache_key] = out
    return out


def material_ids(conn, mat):
    """أرقام خامة من وصفة: أرقامها + أرقام عنصرها + أي بديل مقاس بنفس الاسم."""
    return asset_ids_for(conn, str(mat.get("slug") or ""), str(mat.get("name") or ""),
                         mat.get("asset_ids") or [])


def material_key(slug, name):
    """مفتاح موحّد للخامة: slug عنصرها لو معروف، ولو لأ فاسمها المطبّع.

    بيخلي الحجز والمقارنة مع أرقام العروض الرسمية يتكلموا نفس اللغة حتى لما
    arctracker يكون سايب الخامة من غير id.
    """
    row = items_db.by_slug(slug) or items_db.find(name=name) or {}
    return str(row.get("slug") or "") or items_db.norm(name)


def needs(conn, slug, amount=1):
    """{مفتاح الخامة: qty} لخامات وصفة بكمية معينة — للحجز، فالمفتاح مفتاح الخامة.

    المفتاح مش asset_id: الخامة الواحدة ليها أكتر من رقم عند أكتر من مصدر، والحجز
    باسم الخامة بيمنع إن نفس الكميات تتعد مرتين.
    """
    out = {}
    for mat in (items_db.by_slug(slug) or {}).get("recipe") or []:
        key = material_key(mat.get("slug"), mat.get("name"))
        if key:
            out[key] = out.get(key, 0) + int(mat.get("qty") or 1) * int(amount or 1)
    return out


def _stored(conn, account):
    """{slug: qty} زي ما هي محفوظة في قائمة تصنيع الحساب."""
    out = {}
    for entry in (store.get_meta(conn, PLAN_KEY % account) or {}).get("items") or []:
        slug = str(entry.get("slug") or "")
        if slug and items_db.by_slug(slug):
            out[slug] = max(1, int(entry.get("amount") or 1))
    return out


def _reserved(conn, account, skip=None):
    """{مفتاح الخامة: qty} المحجوزة لخطة التصنيع كلها — وskip يستثني بند واحد."""
    total = {}
    for slug, amount in _stored(conn, account).items():
        if slug == skip:
            continue
        for key, qty in needs(conn, slug, amount).items():
            total[key] = total.get(key, 0) + qty
    return total


def _gate(row, states, levels, access):
    """هل الحساب مسموحله يصنع الوصفة دي؟ ومين مانع لو لأ.

    الشرط صارم ومفيش فيه تخمين: `access[slug]` صح = الوصفة في `default_recipes()`
    (ملهاش مخطوطة عند arctracker فمفتوحة مع أي حساب) أو الحساب فيه عقدة تفعيلها في
    الشجرة (أو علّمها ✓).
    غير كده الوصفة مش مقفولة — هي أصلاً مش عندك، فبتختفي من المصنع. الحاجز الوحيد
    اللي يفضل ظاهر هو مستوى المحطة (وده يدوي لأن مفيش مصدر رسمي لمستوى المحطة).
    """
    slug = str(row.get("slug") or "")
    station = _station(row.get("stations") or row.get("craft_bench"))
    required = int(row.get("station_level") or 0)
    current = int(levels.get(station) or 0)
    level_ok = not required or not current or current >= required
    unlock_ok = bool(access.get(slug))
    lock = "" if unlock_ok else "not_unlocked"
    if unlock_ok and not level_ok:
        lock = "level"
    return {"station": station, "blueprint_state": states.get(slug) if row.get("blueprint_locked") else None,
            "level_required": required, "level_current": current, "level_known": bool(current),
            "unlocked": unlock_ok, "allowed": unlock_ok and level_ok, "lock": lock}


def _craft_gate(conn, account):
    """حالتين بس للتفعيل + أدلة الحساب من الشجرة، لكل الوصفات مرة واحدة."""
    owned = owned_by_asset(conn, account)
    owned_names = owned_by_name(conn, account)
    return {
        "owned": owned, "owned_names": owned_names,
        "states": knowledge.blueprint_state(conn, account, owned, owned_names),
        "levels": knowledge.station_levels(conn, account),
        "access": knowledge.craft_access(conn, account, owned, owned_names),
    }


CATALOG_CACHE = {"path": None, "stamp": None, "recipes": {}}


def catalog():
    """data/craft_catalog.json: slug -> رقم العرض الرسمي على البوابة + خاماته."""
    try:
        stamp = os.stat(CATALOG_FILE).st_mtime_ns
    except OSError:
        return {}
    if CATALOG_CACHE["stamp"] != stamp:
        try:
            with open(CATALOG_FILE, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            payload = {}
        CATALOG_CACHE.update(stamp=stamp, recipes=payload.get("recipes") or {})
    return CATALOG_CACHE["recipes"]


def offer_for(conn, slug):
    """رقم العرض الرسمي + تأكيد حيّ إن خاماته دي خامات وصفتنا.

    المطابقة بتتم على مفتاح الخامة (slug العنصر) بعد حل رقم العرض من القاعدة
    المحلية، مش على رقم خام مكتوب في ملف الكتالوج: لو arctracker ما قالش رقم
    الخامة، المقارنة القديمة كانت تفشل عند كل وصفة فيها خامة مجهولة الرقم — وده
    كان بيحرم الوصفة من رقم العرض حتى وهي صح بالظبط.
    """
    offer = dict(catalog().get(str(slug or "")) or {})
    if not offer:
        return {}
    local, gateway = {}, {}
    for mat in (items_db.by_slug(slug) or {}).get("recipe") or []:
        key = material_key(mat.get("slug"), mat.get("name"))
        local[key] = local.get(key, 0) + int(mat.get("qty") or 0)
    for cost in offer.get("cost") or []:
        key = material_key((items_db.find(asset_id=cost.get("asset_id")) or {}).get("slug"),
                           cost.get("name"))
        gateway[key] = gateway.get(key, 0) + int(cost.get("amount") or 0)
    offer["cost_match"] = bool(gateway) and local == gateway
    return offer


def recipes(conn, account):
    """الوصفات المسموح للحساب بصنعها + حالة خاماته، صافي ما هو محجوز في قائمة التصنيع.

    اللي ملهاش دليل تفعيل ولسه مش في القائمة الأساسية بتاعت اللعبة **ما بتظهرش خالص**
    — مش بتتحول لصف مقفول. كل وصفة بتشوف حجز البنود التانية بس (متستثني نفسها)، عشان
    الزيادة الناقصة في نفس البند ما تتحسبش عليها مرتين.
    """
    gate_data = _craft_gate(conn, account)
    owned, states, levels, access = (gate_data["owned"], gate_data["states"],
                                     gate_data["levels"], gate_data["access"])
    owned_names = gate_data["owned_names"]
    reserved = _reserved(conn, account)
    stored = _stored(conn, account)
    out = []
    for row in items_db.craftable_rows():
        slug = str(row.get("slug") or "")
        if not access.get(slug):
            continue
        own_planned = stored.get(slug, 0)
        mats, max_now = [], None
        for mat in row.get("materials") or []:
            need = int(mat.get("qty") or 1)
            ids = material_ids(conn, mat)
            total = sum(int(owned.get(a, 0) or 0) for a in ids)
            key = material_key(mat.get("slug"), mat.get("name"))
            have = max(0, total - reserved.get(key, 0) + need * own_planned)
            mats.append({**mat, "asset_ids": ids, "asset_id": ids[0] if ids else "",
                         "key": key, "need": need, "have": have,
                         "owned": total, "short": max(0, need - have)})
            if ids:
                fits = have // need if need else PLAN_MAX
                max_now = fits if max_now is None else min(max_now, fits)
        gate = _gate(row, states, levels, access)
        enough = all(not m["short"] for m in mats)
        station = gate["station"]
        offer = offer_for(conn, slug)
        # رقم العرض يُستخدم للتنفيذ فقط لو خاماته مطابقة لبياناتنا — الاختلاف يعني منتج تاني.
        offer_id = offer.get("offer_id") if offer.get("cost_match") else None
        out.append({
            "slug": slug, "name": row.get("name"), "image": row.get("image_filename"),
            "rarity": row.get("rarity"), "type": row.get("type"), "group": row.get("group"),
            "quantity": int(row.get("quantity") or 1), "value": row.get("value"),
            "asset_ids": row.get("asset_ids") or [],
            "offer_id": offer_id,
            "station": station, "stations": row.get("stations") or [],
            "station_label": station_label(station),
            "station_level": row.get("station_level"),
            "skills": sorted({code for group in (row.get("craft_skills") or {}).values() for code in group}),
            "materials": mats, "blueprint": gate["blueprint_state"] or "",
            "lock": gate["lock"], "allowed": gate["allowed"],
            "level_required": gate["level_required"], "level_current": gate["level_current"],
            "have_all": enough, "max_now": PLAN_MAX if max_now is None else max_now,
            "can_craft": gate["allowed"] and enough,
            "planned": 0,
        })
    return out


def plan(conn, account, stored=None):
    """قائمة التصنيع المحفوظة: كل بند بمكوناته + إجمالي الخامات المصروفة لكل خامة.

    `stored` اختياري ليشيل بند قبل ما يتحفظ — عشان edit_plan يوازن على نفس الأرقام
    اللي هتتنزل، مش على الخطة القديمة.
    """
    owned = owned_by_asset(conn, account)
    items = []
    totals = {}
    for slug, amount in (_stored(conn, account) if stored is None else stored).items():
        row = items_db.by_slug(slug) or {}
        rec = items_db.recipe_by_slug(slug) or {}
        mats = []
        for mat in rec.get("materials") or []:
            ids = material_ids(conn, mat)
            key = material_key(mat.get("slug"), mat.get("name"))
            need = int(mat.get("qty") or 1) * amount
            mats.append({"asset_id": ids[0] if ids else "", "asset_ids": ids, "key": key,
                         "name": mat.get("name"), "image": mat.get("image_filename"),
                         "need": need, "owned": sum(int(owned.get(a, 0) or 0) for a in ids)})
            bucket = totals.setdefault(key, {"asset_id": mats[-1]["asset_id"],
                                             "asset_ids": ids, "key": key,
                                             "name": mat.get("name"),
                                             "image": mat.get("image_filename"), "amount": 0})
            bucket["amount"] += need
        items.append({"slug": slug, "name": row.get("name"), "image": items_db.icon_for(row),
                      "rarity": row.get("rarity"), "quantity": int(row.get("craft_quantity") or 1),
                      "station_label": station_label(_station(row.get("craft_bench"))),
                      "qty": amount, "produces": int(row.get("craft_quantity") or 1) * amount,
                      "materials": mats})
    missing = set()
    for key, row in totals.items():
        row["balance"] = sum(int(owned.get(a, 0) or 0) for a in row["asset_ids"])
        row["shortfall"] = max(0, row["amount"] - row["balance"])
        if row["shortfall"]:
            missing.add(key)
    for item in items:
        item["short"] = any(m["key"] in missing for m in item["materials"])
    return {"items": items, "totals": [t for t in totals.values() if t["amount"]]}


def station_board(conn, account, rows=None):
    """شريط المحطات: رسم المحطة بمستواها الحالي، ومستواها، وخامات المستوى الجاي."""
    rows = rows if rows is not None else recipes(conn, account)
    owned = owned_by_asset(conn, account)
    levels = knowledge.station_levels(conn, account)
    sources = knowledge.station_level_sources(conn, account)
    bench_at = knowledge.bench_measured_at(conn, account)
    out = []
    for key, _label in STATIONS:
        group = [r for r in rows if r["station"] == key]
        if not group:
            continue
        level = int(levels.get(key) or 0)
        board = hideout.station(key, level) if key != "in_raid" else {
            "label": station_label(key), "max_level": 0, "next": None,
            "icon": ""}
        nxt = board.get("next")
        cost = []
        if nxt:
            for item in nxt.get("cost") or []:
                asset_ids = asset_ids_for(conn, str(item.get("slug") or ""))
                have = sum(int(owned.get(a, 0) or 0) for a in asset_ids)
                cost.append(dict(item, asset_ids=asset_ids, have=have,
                                 short=max(0, item["qty"] - have)))
        out.append({
            "key": key, "label": station_label(key), "icon": board.get("icon") or "",
            "level": level, "max_level": board.get("max_level") or 0,
            "level_source": sources.get(key) or "", "level_read_at": bench_at,
            "count": len(group),
            "allowed": sum(1 for r in group if r["allowed"]),
            "ready": sum(1 for r in group if r["can_craft"]),
            "next": {"level": nxt["level"], "cost": cost, "image": nxt.get("image")} if nxt else None,
            "unlocks_next": sum(1 for r in group
                                if r["lock"] == "level" and nxt and r["level_required"] == nxt["level"]),
        })
    return out


def _craft_state(conn):
    """بيانات الواجهة: التصنيع بيتنفذ على البوابة؟ والكتابة مجمّدة ولا لأ."""
    from . import pioneer_write
    direct = config.DATA_SOURCE == "pioneer"
    paused = bool(pioneer_write.paused())
    mapped = sum(1 for slug in catalog() if offer_for(conn, slug).get("cost_match"))
    if direct:
        note = ("Crafting executes directly on the official Embark gateway after confirmation, like trader purchases, "
                "and the server spends the materials from the tree.") if not paused else (
                    "The official craft path is ready, but writes are frozen now — counting and preparing work, "
                    "and execution waits for 009.")
    else:
        note = "The legacy mode only computes the materials and adds the request to the craft list."
    return {
        "craftable": direct,
        "write_paused": paused,
        "craft_endpoint": ACCEPT_PATH if direct else None,
        "craft_recipes": mapped,
        "craft_note": note,
    }


def view(conn, account):
    """شكل /api/workshop: الوصفات المسموح بيها + حالة الخامات + قائمة التصنيع للحساب."""
    planned = _stored(conn, account)
    rows = recipes(conn, account)
    for row in rows:
        row["planned"] = planned.get(row["slug"], 0)
    access = _craft_gate(conn, account)["access"]
    hidden = sum(1 for slug in access if not access[slug])
    return {
        "account": account,
        "pick_account": not account or account == "ALL",
        **_craft_state(conn),
        "totals": {
            "recipes": len(rows),
            "allowed": sum(1 for r in rows if r["allowed"]),
            "ready": sum(1 for r in rows if r["can_craft"]),
            "live": sum(1 for r in rows if r["offer_id"]),
            "hidden_not_unlocked": hidden,
            "locked_level": sum(1 for r in rows if r["lock"] == "level"),
        },
        "knowledge": knowledge.summary(conn, account, owned_by_asset(conn, account),
                                       owned_by_name(conn, account)),
        "stations": station_board(conn, account, rows),
        "plan": plan(conn, account),
        "recipes": rows,
        "source": items_db.meta().get("built_at"),
    }


def blueprint_board(conn, account):
    """شاشة المخطوطات الـ 91: حالة كل واحدة عند الحساب ده."""
    owned = owned_by_asset(conn, account)
    cards = knowledge.cards(conn, account, owned, owned_by_name(conn, account))
    for card in cards:
        card["station_label"] = station_label(_station(card.get("stations")))
    return {"account": account, "blueprints": cards,
            "totals": knowledge.summary(conn, account, owned, owned_by_name(conn, account)),
            "stations": [{"key": s["key"], "label": s["label"], "icon": s["icon"],
                          "level": s["level"], "max_level": s["max_level"], "next": s["next"]}
                         for s in station_board(conn, account)]}


def edit_plan(conn, account, slug=None, amount=1, action="add"):
    """يضيف/يعدّل/يشيل/يمسح بند في قائمة تصنيع الحساب — بميزان الخامات الحقيقية."""
    if not account or account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account first."}
    if not store.get_account(conn, account):
        return {"ok": False, "error": "unknown_account", "detail": "The account does not exist."}
    stored = _stored(conn, account)
    if action == "clear":
        stored = {}
    else:
        row = items_db.by_slug(slug)
        if not row or not row.get("recipe"):
            return {"ok": False, "error": "unknown_recipe", "detail": "The recipe is not in the database."}
        key = str(row.get("slug"))
        if action == "remove":
            stored.pop(key, None)
        else:
            try:
                qty = int(amount)
            except (TypeError, ValueError):
                return {"ok": False, "error": "bad_amount", "detail": "Invalid quantity."}
            if qty < 1:
                return {"ok": False, "error": "bad_amount", "detail": "The quantity must be at least 1."}
            states = knowledge.blueprint_state(conn, account, owned_by_asset(conn, account),
                                               owned_by_name(conn, account))
            gate = _gate(row, states, knowledge.station_levels(conn, account),
                         knowledge.craft_access(conn, account))
            if gate["lock"] == "not_unlocked":
                return {"ok": False, "error": "blueprint_not_learned",
                        "detail": "You have no activated blueprint for this item — it cannot be planned."}
            if gate["lock"] == "level":
                return {"ok": False, "error": "station_level",
                        "detail": "This station requires level %s and you have %s."
                                  % (gate["level_required"], gate["level_current"])}
            current = next((r for r in recipes(conn, account) if r["slug"] == key), None)
            if current is None:
                return {"ok": False, "error": "unknown_recipe", "detail": "The recipe is not in the database."}
            if current["max_now"] < 1:
                return {"ok": False, "error": "missing_materials",
                        "detail": "Materials are not enough for one piece: " + ", ".join(
                            "%s (%s of %s)" % (m["name"], m["have"], m["need"])
                            for m in current["materials"] if m["short"])}
            picked = (stored.get(key, 0) + qty) if action == "add" else qty
            stored[key] = min(picked, PLAN_MAX, current["max_now"])

    short = next((row for row in plan(conn, account, stored=stored)["totals"] if row["shortfall"]), None)
    if short:
        return {"ok": False, "error": "insufficient_materials",
                "detail": "The craft list needs %s %s and the stash has %s."
                          % (short["amount"], short["name"], short["balance"]),
                "asset_id": short["asset_id"], "balance": short["balance"], "total": short["amount"]}
    items = [{"slug": s, "amount": q} for s, q in stored.items() if q > 0]
    if items:
        store.set_meta(conn, PLAN_KEY % account, {"items": items})
    else:
        conn.execute("DELETE FROM meta WHERE key=?", (PLAN_KEY % account,))
        conn.commit()
    return {"ok": True, "account": account, "plan": plan(conn, account)}


def _asset_totals(data, asset_ids):
    """مجموع الكميات الرسمية لكل gameAssetId من شجرة المخزون."""
    wanted = {str(a) for a in asset_ids if str(a or "")}
    totals = {a: 0 for a in wanted}
    for node in (data or {}).get("items") or []:
        asset_id = str(node.get("gameAssetId") or "")
        if asset_id in totals:
            totals[asset_id] += int(node.get("amount") or 0)
    return totals


def craft_error(exc):
    text = str(exc)
    if "FAILED_PRECONDITION" in text:
        return {"ok": False, "error": "craft_precondition", "code": 412,
                "detail": "The gateway refused the craft: the station is not built, or the account state does not allow executing now."}
    if "INVALID_ARGUMENT" in text:
        return {"ok": False, "error": "craft_invalid", "code": 400,
                "detail": "The gateway rejected the offer number: the recipe changed after the last catalog — run a sync."}
    if "OUT_OF_RANGE" in text:
        return {"ok": False, "error": "craft_unavailable", "code": 400,
                "detail": "The gateway refused the craft: not available on this account right now."}
    if "MANIFEST" in text:
        return {"ok": False, "error": "manifest_expired", "code": 409,
                "detail": "The manifest number is outdated or rejected — update it from inspection/pioneer_manifest.py."}
    if "401" in text:
        return {"ok": False, "error": "token_expired", "code": 401,
                "detail": "The account token was locked by the gateway — a new login is required."}
    return {"ok": False, "error": "gateway_error", "code": 502, "detail": text[:300]}


def gateway_rejection(response):
    """البوابة بترجّع 200 وفيها خطأ داخل الـ payload — نعتبره رفضاً قبل ما نقول تم."""
    if not isinstance(response, dict):
        return None
    err = response.get("error")
    if not err:
        return None
    text = err if isinstance(err, str) else json.dumps(err, ensure_ascii=False)
    return {"ok": False, "error": "craft_rejected", "code": 400,
            "detail": "The gateway refused to execute the craft: %s" % text[:280]}


def _consume_plan_slug(conn, account, slug, qty):
    """يشيل الكمية المنفّذة فعلًا من قائمة تصنيع الحساب."""
    key = PLAN_KEY % account
    stored = (store.get_meta(conn, key) or {}).get("items") or []
    out, left, changed = [], int(qty), False
    for entry in stored:
        if str(entry.get("slug")) == str(slug) and left > 0:
            take = min(left, max(0, int(entry.get("amount") or 0)))
            remaining = max(0, int(entry.get("amount") or 0) - take)
            left -= take
            changed = True
            if remaining:
                out.append({"slug": entry.get("slug"), "amount": remaining})
        else:
            out.append(entry)
    if changed:
        if out:
            store.set_meta(conn, key, {"items": out})
        else:
            conn.execute("DELETE FROM meta WHERE key=?", (key,))
            conn.commit()
    return changed


def craft(conn, account, slug, amount, confirmed=False):
    """ينفّذ تصنيع وصفة على بوابة Embark الرسمية (عرض قبول) ثم يتحقق من الشجرة ويحدّث السنابشوت."""
    from . import pioneer_write

    if not confirmed:
        return {"ok": False, "error": "confirmation_required", "code": 428,
                "detail": "The craft must be executed from the dedicated confirmation window (confirmed=true)."}
    if not account or account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account first."}
    rec = store.get_account(conn, account)
    if not rec:
        return {"ok": False, "error": "unknown_account", "detail": "The account does not exist."}
    if config.DATA_SOURCE != "pioneer":
        return {"ok": False, "error": "legacy_plan_only", "code": 409,
                "detail": "Direct crafting is available only in official Pioneer gateway mode."}
    if not rec.get("token"):
        return {"ok": False, "error": "missing_token", "detail": "No stored token for this account."}
    if pioneer_write.paused():
        return {"ok": False, "error": "write_paused", "code": 423, "detail": pioneer_write.PAUSE_DETAIL}

    row = items_db.by_slug(slug)
    if not row or not row.get("recipe"):
        return {"ok": False, "error": "unknown_recipe", "detail": "The recipe is not in the database."}
    offer = offer_for(conn, slug)
    if not offer.get("cost_match") or not offer.get("offer_id"):
        return {"ok": False, "error": "no_offer_id", "code": 409,
                "detail": "This recipe has no matching official offer number — it can only be planned, and crafted inside the game."}

    states = knowledge.blueprint_state(conn, account, owned_by_asset(conn, account),
                                      owned_by_name(conn, account))
    gate = _gate(row, states, knowledge.station_levels(conn, account),
                 knowledge.craft_access(conn, account))
    if gate["lock"] == "not_unlocked":
        return {"ok": False, "error": "blueprint_not_learned", "code": 403,
                "detail": "The official node that activates this blueprint is not in your account tree — "
                          "it has to be activated inside the game first."}
    if gate["lock"] == "level":
        return {"ok": False, "error": "station_level",
                "detail": "This station requires level %s and you have %s." % (gate["level_required"], gate["level_current"])}

    try:
        offer_id = int(offer["offer_id"])
        qty = int(amount)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_amount", "detail": "Invalid offer number or quantity."}
    if qty < 1:
        return {"ok": False, "error": "bad_amount", "detail": "The quantity must be at least 1."}
    limit = int(offer.get("limit") or 0)
    if limit > 0 and qty > limit:
        return {"ok": False, "error": "above_limit", "detail": "The quantity is above the offer limit (%s)." % limit}

    costs = [{"asset_id": str(c.get("asset_id")), "name": c.get("name") or "",
              "need": int(c.get("amount") or 0) * qty} for c in offer.get("cost") or []]
    reward_asset = str(offer.get("reward_asset_id") or "")
    reward_amount = int(offer.get("reward_amount") or 1) * qty
    wanted = [c["asset_id"] for c in costs] + [reward_asset]

    try:
        before = pc.fetch_inventory_for(account)
    except Exception as exc:
        return dict(craft_error(exc), stage="pre_inventory")

    actual = _asset_totals(before, wanted)
    short = [c for c in costs if actual.get(c["asset_id"], 0) < c["need"]]
    if short:
        return {"ok": False, "error": "missing_materials", "code": 402,
                "detail": "The official materials are not enough: " + ", ".join(
                    "%s (%s of %s)" % (c["name"] or c["asset_id"], actual.get(c["asset_id"], 0), c["need"])
                    for c in short)}

    request = {"offerId": offer_id, "itemsToConsume": [], "amount": qty}
    try:
        response = pc.post_json(ACCEPT_PATH, request, token=rec["token"])
    except Exception as exc:
        store.log_action(conn, account, "craft:accept", request, "failed", str(exc)[:300], qty)
        return dict(craft_error(exc), stage="accept")
    rejected = gateway_rejection(response)
    if rejected:
        store.log_action(conn, account, "craft:accept", request, "rejected", rejected["detail"], qty)
        return dict(rejected, stage="accept")

    try:
        after = pc.fetch_inventory_for(account)
    except Exception as exc:
        store.log_action(conn, account, "craft:accept", request, "accepted_unverified", str(exc)[:300], qty)
        return {"ok": True, "executed": True, "verified": False, "account": account,
                "offer_id": offer_id, "qty": qty, "detail":
                    "The gateway accepted the craft, but the verification read failed — press SYNC before any other operation.",
                "error": str(exc)[:300]}

    post_totals = _asset_totals(after, wanted)
    deltas = {c["asset_id"]: post_totals.get(c["asset_id"], 0) - actual.get(c["asset_id"], 0) for c in costs}
    consumed = all(deltas[c["asset_id"]] == -c["need"] for c in costs)
    reward_delta = post_totals.get(reward_asset, 0) - actual.get(reward_asset, 0)
    refreshed = pioneer_write._refresh_data(conn, account, after)
    _consume_plan_slug(conn, account, str(row.get("slug")), qty)
    summary = {
        "recipe": row.get("name"), "bench": offer.get("bench_name"),
        "costs": [{"name": c["name"] or c["asset_id"], "expected": -c["need"],
                   "delta": deltas[c["asset_id"]]} for c in costs],
        "reward": reward_asset, "expected_reward": reward_amount, "reward_delta": reward_delta,
    }
    store.log_action(conn, account, "craft:accept", request,
                     "executed" if consumed else "accepted_unverified", summary, qty)

    detail = "Crafted %s × %s." % (qty, row.get("name"))
    if not consumed:
        detail += " the gateway accepted the request but the material spend did not match — press SYNC and check the stash."
    elif reward_delta < reward_amount:
        detail += " the piece may have landed somewhere else in the stash — press SYNC."
    return {"ok": True, "executed": True, "verified": consumed, "account": account,
            "offer_id": offer_id, "qty": qty, "slug": str(row.get("slug")),
            "detail": detail, "summary": summary,
            "deltas": dict(deltas, **{reward_asset: reward_delta}), "refreshed": refreshed}
