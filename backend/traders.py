"""كتالوج التجار المحلي + الشراء من بوابة Pioneer الرسمية.

الكتالوج (التاجر، عرضه، سعره والحد اليومي) بيُخزّن في data/traders_catalog.json
عشان الصفحة تشتغل أوفلاين. الأرصدة بتتقرا من بوابة Embark الرسمية: الـ Coins من
stats الحساب، والـ SEEDS من شجرة المخزن (بند حقيقي جوه الستاش/الأوفر فلو).

بوابة Embark بتنفّذ قبو العروض عبر POST /v1/pioneer/offers/accept. الشراء بيتعمل
بعد تأكيد صريح، بيحترم قفل الكتابة الحالي، وبيتحقق من المخزون الرسمي بعد التنفيذ.

العروض اللي ليها `requiredItems` (مفاتيح فتح مستويات التجار) بترفض 400 لو القبول
راحت بدونها: البوابة بتطلب الأصناف دي صراحة في `itemsToConsume` بالرصة الحية
و etag بتاعها — بنقرأها من رد اللعبة الرسمي لأن العروض نفسها مش بتتشارك على البوابة.
"""
import json
import os
import time

from . import accounts, catalog, config, items_db, pioneer_client as pc, pioneer_tree, store, sync

CATALOG_FILE = os.path.join(config.DATA_DIR, "traders_catalog.json")
GAME_DATA_FILE = os.path.join(config.DATA_DIR, "pioneer_game_data.json")
CATALOG_VERSION = 1
PLAN_KEY = "trader_plan:%s"
OFFER_ACCEPT_PATH = "/v1/pioneer/offers/accept"
# سقف الكمية لعرض ملهوش حد يومي — عشان زرار MAX ما يطلّعش رقم بلا نهاية.
PLAN_MAX = 99

# ترتيب ثابت للتجار؛ أي تاجر بره القائمة دي بيترتب بعداهم بعدّ عروضه.
TRADER_ORDER = ("Tian Wen", "Celeste", "Lance", "Apollo", "Shani")

CURRENCIES = {
    "-898439395": {"name": "Coins", "image": "metaforge/coins.webp", "wallet": "coins"},
    "1051518749": {"name": "Assorted Seeds", "image": "metaforge/assorted-seeds.png", "wallet": None},
    "1369416424": {"name": "Free Loadout Augment", "image": "metaforge/free-loadout-augment.png", "wallet": None},
}


def _icon(name, fallback=""):
    item = catalog.arctracker_lookup(name)
    return catalog.icon_of(item) or fallback


def _currency(meta):
    asset_id = str(meta.get("asset_id") or "")
    known = CURRENCIES.get(asset_id) or {}
    name = meta.get("display_name") or known.get("name") or "Currency"
    return {
        "asset_id": asset_id,
        "name": name,
        "image": known.get("image") or _icon(name, meta.get("image_filename") or ""),
        "wallet": known.get("wallet"),
    }


def normalize_offer(raw):
    reward_meta = raw.get("reward_meta") or ((raw.get("reward") or {}).get("meta")) or {}
    cost = raw.get("cost") or {}
    cost_meta = raw.get("cost_meta") or cost.get("meta") or {}
    reward = raw.get("reward") or {}
    return {
        "offer_id": raw.get("offer_id"),
        "order_index": raw.get("order_index") or 0,
        "title": raw.get("title"),
        "reward": {
            "asset_id": str(reward.get("asset_id") or ""),
            "name": reward_meta.get("display_name") or "",
            "amount": int(reward.get("amount") or 0),
            "image": _icon(reward_meta.get("display_name"), reward_meta.get("image_filename") or ""),
            "rarity": reward_meta.get("rarity") or "",
            "type": reward_meta.get("type") or "",
        },
        "cost": {
            **_currency({**cost_meta, "asset_id": cost.get("asset_id") or cost_meta.get("asset_id")}),
            "amount": int(cost.get("amount") or 0),
        },
        "limit": int(raw.get("limit") or 0),
        "remaining": raw.get("remaining"),
        "amount_bought": int(raw.get("amount_bought") or 0),
        "required": raw.get("required"),
    }


def build_catalog(conn):
    """يبني data/traders_catalog.json من آخر snapshot لكل حساب (بدون أي طلب شبكة)."""
    traders = {}
    instances = {}
    generated = time.time()
    for account in (sync.account_pairs(conn) or []):
        name = account[0]
        payload = store.get_meta(conn, "traders:%s" % name) or {}
        if not isinstance(payload, dict):
            continue
        instances[name] = {}
        for owner_asset_id, offers in payload.items():
            if not offers:
                continue
            owner = offers[0].get("owner_meta") or {}
            key = str(owner_asset_id)
            trader = traders.setdefault(key, {
                "asset_id": str(owner_asset_id),
                "name": owner.get("display_name") or key,
                "type": owner.get("type") or "npc",
                "image": owner.get("image_filename") or "",
                "offers": {},
            })
            for raw in offers:
                offer = trader["offers"].get(str(raw.get("offer_id"))) or normalize_offer(raw)
                if raw.get("owner_instance_id"):
                    offer.setdefault("instances", {})[name] = raw["owner_instance_id"]
                    instances[name][str(offer["offer_id"])] = raw["owner_instance_id"]
                trader["offers"][str(raw.get("offer_id"))] = offer
    rank = {name: idx for idx, name in enumerate(TRADER_ORDER)}
    out_traders = []
    for trader in traders.values():
        offers = sorted(trader["offers"].values(),
                        key=lambda o: (o.get("order_index") or 0, o["reward"]["name"]))
        out_traders.append({
            "asset_id": trader["asset_id"],
            "name": trader["name"],
            "type": trader["type"],
            "image": trader["image"],
            "trades": len(offers),
            "offers": offers,
        })
    out_traders.sort(key=lambda t: (rank.get(t["name"], 99), -t["trades"]))
    if not out_traders:
        # البوابة الرسمية ما بتنشرش عروض التجار — يبقى مفيش快照 جديدة تتبنى منها.
        # ما نستبدلش الكتالوج الموجود بملف فاضي.
        return _read_catalog_file() or {"version": CATALOG_VERSION, "generated_at": generated,
                                       "accounts": sorted(instances), "instances": instances,
                                       "traders": []}
    data = {
        "version": CATALOG_VERSION,
        "generated_at": generated,
        "source": "local_snapshots",
        "accounts": sorted(instances),
        "instances": instances,
        "traders": out_traders,
    }
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = CATALOG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CATALOG_FILE)
    return data


def _read_catalog_file():
    try:
        with open(CATALOG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == CATALOG_VERSION and data.get("traders"):
            return data
    except (OSError, ValueError):
        pass
    return None


def load_catalog(conn):
    return _read_catalog_file() or build_catalog(conn)


def _live_map(conn, account):
    payload = store.get_meta(conn, "traders:%s" % account) or {}
    out = {}
    for offers in (payload.values() if isinstance(payload, dict) else []):
        for raw in offers or []:
            if raw.get("offer_id") is not None:
                out[str(raw["offer_id"])] = raw
    return out


def _offer_for(account_catalog_offer, live_raw, account):
    offer = json.loads(json.dumps(account_catalog_offer))
    if live_raw:
        offer["limit"] = int(live_raw.get("limit") or 0)
        offer["remaining"] = live_raw.get("remaining")
        offer["amount_bought"] = int(live_raw.get("amount_bought") or 0)
        if live_raw.get("owner_instance_id"):
            offer.setdefault("instances", {})[account] = live_raw["owner_instance_id"]
    offer["owner_instance_id"] = (offer.get("instances") or {}).get(account) or ""
    offer["stock_left"] = (offer.get("remaining") if offer.get("limit")
                           else None)
    return offer


def balance_of(conn, account, currency):
    wallet_key = (currency or {}).get("wallet")
    if wallet_key:
        stats = accounts.wallet(conn, account)["stats"]
        return int((stats.get(wallet_key) or {}).get("value") or 0)
    row = conn.execute("SELECT COALESCE(SUM(qty),0) q FROM instances WHERE account=? AND asset_id=?",
                       (account, str((currency or {}).get("asset_id") or ""))).fetchone()
    return int(row["q"] or 0)


def balances(conn, account):
    out = {}
    for asset_id, meta in CURRENCIES.items():
        out[asset_id] = {
            "asset_id": asset_id, "name": meta["name"], "image": meta["image"],
            "amount": balance_of(conn, account, {"asset_id": asset_id, "wallet": meta["wallet"]}),
        }
    return out


def _purchase_state():
    """بيانات الواجهة: المسار الرسمي شغال؟ والكتابة الحالية مجمّدة ولا لأ."""
    from . import pioneer_write
    direct = config.DATA_SOURCE == "pioneer"
    paused = bool(pioneer_write.paused())
    if direct:
        note = ("Purchases execute directly on the official Embark gateway after confirmation, and are deducted "
                "from the account balance.") if not paused else (
                    "The official purchase path is ready, but writes are frozen now — choosing and preparing "
                    "work, and execution waits for 009.")
    else:
        note = "The legacy mode only computes the cost and adds the request to the buy list."
    return {
        "buyable": direct,
        "write_paused": paused,
        "buy_endpoint": OFFER_ACCEPT_PATH if direct else None,
        "buy_note": note,
    }


def view(conn, account):
    """شكل /api/traders: كتالوج ثابت + remaining الحي + أرصدة الحساب + قائمة الشراء."""
    data = load_catalog(conn)
    live = _live_map(conn, account)
    traders = []
    for trader in data.get("traders") or []:
        offers = [_offer_for(o, live.get(str(o.get("offer_id"))), account) for o in trader.get("offers") or []]
        offers = [o for o in offers if str(o.get("offer_id")) in live or not live]
        traders.append({
            "asset_id": trader["asset_id"], "name": trader["name"], "type": trader["type"],
            "image": trader["image"], "trades": len(offers), "offers": offers,
        })
    return {
        "account": account,
        **_purchase_state(),
        "generated_at": data.get("generated_at"),
        "currency_order": list(CURRENCIES),
        "balances": balances(conn, account),
        "plan": plan(conn, account),
        "traders": traders,
    }


def _offer_index(conn, account):
    """offer_id -> (trader, offer) بعد دمج الكتالوج في البيانات الحية للحساب."""
    data = load_catalog(conn)
    live = _live_map(conn, account)
    out = {}
    for trader in data.get("traders") or []:
        for offer in trader.get("offers") or []:
            out[str(offer.get("offer_id"))] = (trader, _offer_for(offer, live.get(str(offer.get("offer_id"))), account))
    return out


# البوابة ما بتنشرش وصف العروض (الشراء من التجار مش في /v1/pioneer/offers)، فالحقل
# الوحيد اللي بيرجع من رد اللعبة الرسمي هو requiredItems — وهو اللي بيفصل عرض
# بيقبل 200 عن عرض بيرفض 400 internal error.
_requirements_cache = {"key": None, "rows": {}}


def offer_requirements():
    """offer_id -> قائمة requiredItems من data/pioneer_game_data.json (كاش بالميل تايم)."""
    try:
        key = (os.path.getmtime(GAME_DATA_FILE), os.path.getsize(GAME_DATA_FILE))
    except OSError:
        return {}
    if _requirements_cache["key"] != key:
        try:
            with open(GAME_DATA_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        rows = {}
        for offer in ((data.get("offer-descriptions") or {}).get("offerDescriptions") or []):
            if offer.get("requiredItems"):
                rows[str(offer.get("offerId"))] = [
                    {"itemGameAssetId": int(r.get("itemGameAssetId")),
                     "amount": int(r.get("amount") or 1)}
                    for r in offer["requiredItems"] if r.get("itemGameAssetId") is not None]
        _requirements_cache.update({"key": key, "rows": rows})
    return _requirements_cache["rows"]


def required_of(offer):
    """الأصناف اللي العرض بيطلبها صراحةً: من الكتالوج، ولو مفقود من رد اللعبة الرسمي."""
    rows = (offer or {}).get("required")
    if rows:
        return rows
    return offer_requirements().get(str((offer or {}).get("offer_id"))) or []


# أصغر شكل معروف لـ openapi.InventoryItem: الرصة الحية + الكمية + نسخة_etag_اللي
# البوابة بتقارنه قبل الصرف. حقول بره القائمة دي بترفع رسالة فك الترميز.
ITEM_FIELDS = ("gameAssetId", "etag")


def consume_required(tree, offer, qty=1):
    """يبني itemsToConsume من الشجرة الحية: (خطوط، الناقص).

    بنبدأ بالرصات اللي حجمها = المطلوب بالظبط (مفيش تقسيم)، وبعدين الأكبر. الناقص
    بيتقارن قبل الإرسال، والقرار النهائي للصرف بيفضل للبوابة.
    """
    lines, missing = [], []
    for row in required_of(offer):
        try:
            aid = int(row.get("itemGameAssetId"))
        except (TypeError, ValueError):
            continue
        need = int(row.get("amount") or 1) * max(1, int(qty or 1))
        pool = []
        for iid, node in (tree.by_id.items() if tree else []):
            if str(node.get("gameAssetId")) != str(aid):
                continue
            have = int(node.get("amount") or 1)
            pool.append((0 if have == need else 1, -have, iid, node))
        pool.sort(key=lambda r: (r[0], r[1], r[2]))
        got = 0
        for _bucket, _neg, iid, node in pool:
            if got >= need:
                break
            take = min(need - got, int(node.get("amount") or 1))
            if take <= 0:
                continue
            line = {"instanceId": str(iid), "amount": take}
            line.update({k: node[k] for k in ITEM_FIELDS if k in node})
            lines.append(line)
            got += take
        if got < need:
            missing.append((aid, need, got))
    return lines, missing


def _missing_detail(missing):
    names = pioneer_tree.asset_names()
    parts = []
    for aid, need, got in missing:
        row = names.get(str(aid)) or {}
        parts.append("%d× %s" % (need - got,
                                 row.get("display_name") or row.get("game_asset_name")
                                 or "unlock item %s" % aid))
    return ", ".join(parts)


def _asset_totals(data, asset_ids):
    """مجموع الكميات الرسمية لكل gameAssetId مطلوب من شجرة المخزون."""
    wanted = {str(a) for a in asset_ids if str(a or "")}
    totals = {a: 0 for a in wanted}
    for node in (data or {}).get("items") or []:
        asset_id = str(node.get("gameAssetId") or "")
        if asset_id in totals:
            totals[asset_id] += int(node.get("amount") or 0)
    return totals


def _reward_cap(conn, account, asset_id):
    """سقف كومة النوع من المصادر المحلية (نفس مصدر باقي الحركات) — وافتراضياً 1."""
    from . import actions as gear_actions
    return max(1, int(gear_actions._stack_cap(conn, account, asset_id) or 1))


def _space_need(conn, account, data, asset_id, amount):
    """كام خانة فاضية محتاج التسليم: الكومة اللي ليها مكان بتاخد بدل النوع ناقص
    وتقسيمها على السقف، والباقي خانة كاملة لكل كومة."""
    cap = _reward_cap(conn, account, asset_id)
    room = 0
    for node in (data or {}).get("items") or []:
        if str(node.get("gameAssetId")) != str(asset_id):
            continue
        try:
            held = int(node.get("amount") or 0)
            limit = int(node.get("maxAmount") or 0) or cap
        except (TypeError, ValueError):
            continue
        room += max(0, limit - held)
    return max(0, -(-max(0, int(amount) - room) // cap))


def _free_stash(data):
    """(فاضي, إجمالي) خانات الستاش الرسمية — نفس التخطيط اللي الموقع بيرسمه."""
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    cells = [str(c) for c in (pioneer_tree.layout(tree).get("stash") or {}).get("slots") or []]
    return sum(1 for c in cells if not tree.first_child(c)), len(cells)


_RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "amplified": 5}


ALLOWED_ASSET_IDS = {"-898439395", "1979925731", "941631263", "1051518749", "1369416424"}


def _eviction_candidates(conn, account, data):
    """أي قطعة في الستاش ينفع تتشال مؤقتاً عشان خانتها تتفضّي للشراء.

    البوابة بتقبل شكل كتابة واحد بس بيحرّك حاجة: القطعة → خانة فاضية. فمفيش
    «إخراج من الستاش» ولا دمج في كوم تاني — التفريغ بيحصل بنقل القطعة لخانة
    فاضية في شنطة الـ loadout (نفس الشكل اللي زر النقل في الموقع بيستخدمه).

    الفلتر مفتوح بالكامل: أي قطعة مسطّحة في خانة (من غير ملحقات) مؤهلة — حتى
    سلاح أو درع أو أوجمنت متكرر — بشرط إنها مش مجهّزة في اللوداوت ومش ممنوعة
    في ALLOWED_ASSET_IDS. الأرخص والعملي بيروح الأول، والقطع الخاصة آخر الترتيب.

    مفيش شنطة فيها خانة فاضية؟ ساعتها مفيش مسار نقل أصلًا — بنرجّع مرشحين
    بعلامة mode="stash" عشان رسالة الرفض تشرح الحالة بدل ما تقول مفيش مرشحين."""
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    lay = pioneer_tree.layout(tree)
    if not tree.items:
        return tree, []
    cells = [str(c) for c in lay["stash"]["slots"]]
    protected = set()
    try:
        from . import loadouts
        state = loadouts.state(conn, account)
        for slots in (state.get("slots") or {}).values():
            for slot in slots or []:
                iid = ((slot or {}).get("item") or {}).get("instance_id")
                if iid:
                    protected.add(str(iid))
    except Exception:
        pass
    container = (lay.get("backpack") or {}).get("container") or ""
    bag_free = [str(s["wrapper"]) for s in lay["backpack"]["slots"]
                if not tree.first_child(s["wrapper"])]
    out = []
    for cell in cells:
        leaf = tree.first_child(cell)
        if not leaf or leaf in protected:
            continue
        if tree.children(leaf):
            continue
        row = tree.by_id.get(leaf) or {}
        asset_id = str(row.get("gameAssetId") or "")
        if asset_id in ALLOWED_ASSET_IDS:
            continue
        try:
            amount = int(row.get("amount") or 1)
        except (TypeError, ValueError):
            amount = 1
        dossier = items_db.dossier(asset_id=asset_id) or {}
        text = " ".join(str(dossier.get(k) or "") for k in ("type", "group", "name")).lower()
        rarity = str(dossier.get("rarity") or "").lower()
        cap = _reward_cap(conn, account, asset_id)
        out.append({
            "cell": str(cell), "leaf": leaf, "asset_id": asset_id,
            "name": tree.name_of(leaf) or "item", "amount": amount, "cap": cap,
            "value": int(dossier.get("value") or 0) or 10 ** 9,
            "rarity": _RARITY_ORDER.get(rarity, 0),
            "special": bool(dossier.get("is_weapon") or dossier.get("is_blueprint")
                            or dossier.get("quest_item") or "blueprint" in text or "key" in text
                            or rarity in ("epic", "legendary", "amplified")),
            "single": amount <= 1 or cap <= 1,
            "mode": "backpack" if bag_free else "none",
            "bag_container": container, "bag_slot": bag_free[0] if bag_free else "",
            "host_cell": "", "host_leaf": "", "gap": 0,
        })
    out.sort(key=lambda c: (c["special"], c["single"], c["value"], c["rarity"],
                            c["gap"], -c["amount"], c["name"]))
    return tree, out


def _slot_children(tree, cell):
    """كل آيدسات جوه خانة (عنصر + لو معاه ملحقات زي كارت المفتاح) — لتطابق الأمر
    الواحد بالحالة اللي البوابة سايباها في الخانة."""
    out = []
    for kid in tree.children(cell):
        out.append(kid)
        out.extend(tree.children(kid))
    return out


def _auto_make_room(conn, account, need, data):
    """يفضّي خانات الستاش المطلوبة قبل التسليم.

    مسار التفريغ: القطعة المرشحة بتروح مؤقتاً لخانة فاضية في شنطة الـ loadout،
    وبعدها بنقرا الشجرة الجديدة ونتأكد إن عدد الخانات المشغولة في الستاش نقص
    فعلًا قبل ما أي شراء يتبعت (القراءة هي الحكم — رد البوابة على النقل مش
    دليل، لأنها ساعات بترجع الخانة القديمة زي ما هي مع updatedAt جديد).

    لو البوابة رفضت النقل أو الخانة ما فضتش: بنرجّع ok=False ورسالة صريحة —
    الشراء ميتّبعتش والفلوس متتخصمش."""
    from . import pioneer_write
    free, total = _free_stash(data)
    short = need - free
    if short <= 0:
        return {"ok": True, "moved": [], "free": free, "total": total, "before": free, "data": data}
    tree, candidates = _eviction_candidates(conn, account, data)
    if not candidates:
        return {"ok": False, "error": "stash_full", "moved": [], "free": free, "total": total,
                "detail": ("The stash is full (%d / %d cells) and there is nothing in it that can be moved "
                           "out: every cell is either empty of a movable item or part of the equipped loadout. "
                           "Free one cell in the game, then buy again. Nothing was purchased and nothing was charged."
                           % (total - free, total))}
    if candidates[0]["mode"] != "backpack":
        return {"ok": False, "error": "no_parking_cell", "moved": [], "free": free, "total": total,
                "detail": ("The stash is full (%d / %d cells) and the loadout backpack has no free cell to "
                           "park an item in while the purchase is delivered. Free a bag cell in the game, then "
                           "buy again. Nothing was purchased and nothing was charged."
                           % (total - free, total))}
    picks = candidates[:short]
    for p in picks:
        if p["mode"] != "backpack":
            p["bag_slot"] = ""
    picks = [p for p in picks if p["bag_slot"]]
    if not picks:
        return {"ok": False, "error": "no_parking_cell", "moved": [], "free": free, "total": total,
                "detail": "The loadout backpack has no free cell to park an item in."}
    moves = [{"target_container": "backpack", "target_wrapper_id": p["bag_slot"],
              "instance_ids": [p["leaf"]]} for p in picks]
    result = pioneer_write.move_plan(conn, account, moves)
    if not result.get("executed"):
        return {"ok": False, "error": result.get("error") or "make_room_failed",
                "moved": [], "free": free, "total": total,
                "detail": ("The stash is full (%d / %d cells) and moving an item into the loadout backpack "
                           "did not go through: %s Nothing was purchased and nothing was charged."
                           % (total - free, total, result.get("detail") or result.get("error") or "unknown error"))}
    try:
        after = pc.fetch_inventory_for(account)
    except Exception:
        after = None
    free_after = _free_stash(after)[0] if after else free
    if after is None or free_after <= free:
        return {"ok": False, "error": "make_room_failed", "moved": [], "free": free, "total": total,
                "detail": ("The stash is full (%d / %d cells) and I could not free a cell: the gateway took the "
                           "move into the backpack but the stash cell did not come free (%d / %d free) — the item "
                           "either stayed where it was or its old cell was refilled straight away. Nothing was "
                           "purchased and nothing was charged. Free one cell in the game, then buy again."
                           % (total - free, total, free_after, total))}
    moved = [{"name": p["name"], "amount": p["amount"], "cell": p["cell"], "leaf": p["leaf"],
              "bag_slot": p["bag_slot"], "asset_id": p["asset_id"]} for p in picks]
    return {"ok": True, "moved": moved, "free": free_after, "total": total, "before": free,
            "mode": "backpack", "data": after}


def _put_items_back(conn, account, room, data):
    """بعد الشراء: القطع اللي اتنقلت للشنطة ترجع لخاناتها القديمة — الخانة اللي
    المشترى نزل فيها هي اللي بتفضى، والوضع يرجع زي ما كان."""
    from . import pioneer_write
    moved = (room or {}).get("moved") or []
    if not moved:
        return None
    tree = pioneer_tree.Tree(((data or {}).get("items")) or [])
    lay = pioneer_tree.layout(tree)
    free_cells = [str(c) for c in lay["stash"]["slots"] if not tree.first_child(c)]
    plans, back = [], []
    for m in moved:
        bag_slot, target = m.get("bag_slot"), m.get("cell")
        parked = tree.first_child(bag_slot) if bag_slot else ""
        if not parked or str((tree.by_id.get(parked) or {}).get("gameAssetId")) != str(m.get("asset_id")):
            continue
        if not target or tree.first_child(target):
            if not free_cells:
                continue
            target = free_cells.pop(0)
        plans.append({"target_container": "stash", "target_wrapper_id": target,
                      "instance_ids": [parked]})
        back.append({"name": m.get("name"), "amount": m.get("amount"), "cell": target,
                     "from": bag_slot})
        tree.parent[parked] = target
    if not plans:
        return None
    result = pioneer_write.move_plan(conn, account, plans)
    if not result.get("executed"):
        return None
    return back


def _log_make_room(conn, account, room):
    moved = room.get("moved") or []
    if not moved:
        return
    summary = {"to": "backpack", "before": room.get("before"), "free": room.get("free"),
               "total": room.get("total"),
               "items": [{"name": m.get("name"), "amount": m.get("amount"),
                          "cell": m.get("cell"), "bag_slot": m.get("bag_slot")} for m in moved]}
    store.log_action(conn, account, "trade:make_room",
                     {"target_container": room.get("mode") or "backpack"}, "executed",
                     summary, len(moved))


def _moved_note(moved, free, total):
    if not moved:
        return ""
    count = len(moved)
    extra = (" %s" % ", ".join("%s ×%s" % (m.get("name") or "item", m.get("amount") or 1)
                               for m in moved[:4])) if count <= 4 else ""
    return (" The stash was full, so %d item%s were parked in the backpack to clear room%s "
            "— now %d / %d cells free." % (count, "" if count == 1 else "s", extra, free, total))


def _restored_note(restored):
    if not restored:
        return ""
    return (" The parked item%s went back to the stash: %s."
            % ("" if len(restored) == 1 else "s",
               ", ".join("%s ×%d" % (m.get("name") or "item", m.get("amount") or 0)
                         for m in restored[:4])))


def _stash_full(conn, account, before, reward_asset, amount, expected_reward):
    """التسليم مش لاقي مكانه في الستاش؟ ⇐ كل المساحة المتاحة محودة."""
    free, total = _free_stash(before)
    need = _space_need(conn, account, before, reward_asset, expected_reward)
    if need <= free:
        return None
    short = max(1, need - free)
    return {"ok": False, "error": "stash_full", "code": 409, "stage": "space_check",
            "detail": ("The stash is full (%d / %d cells), so %s cannot be delivered. "
                       "Free at least %d cell%s — sell, recycle or move stacks to the pack in the game — "
                       "then buy again. Nothing was sent to the gateway and nothing was charged."
                       % (total - free, total, "the purchase" if amount == 1 else "the purchases",
                          short, "" if short == 1 else "s")),
            "free_cells": free, "total_cells": total, "need_cells": need}


def _not_enough_space(exc):
    """رد البوابة اللي معناه: الاستلام مش لاقي خانة (بعد ما القراءة حيّزت المبلغ)."""
    return "400" in str(exc) and "internal error" in str(exc)



def _purchase_error(exc):
    text = str(exc)
    if "FAILED_PRECONDITION" in text:
        return {"error": "offer_precondition", "code": 412,
                "detail": "The gateway rejected the offer because the account or game state does not allow executing right now."}
    if "INVALID_ARGUMENT" in text:
        return {"error": "offer_invalid", "code": 400,
                "detail": "The gateway rejected the offerId: the offer expired or changed after the last catalog. SYNC the offers."}
    if "OUT_OF_RANGE" in text:
        return {"error": "offer_unavailable", "code": 400,
                "detail": "The gateway rejected the offer: not available on this account right now."}
    if "MANIFEST" in text:
        return {"error": "manifest_expired", "code": 409,
                "detail": "The manifest number is outdated or rejected — update it from inspection/pioneer_manifest.py."}
    if "401" in text:
        return {"error": "token_expired", "code": 401,
                "detail": "The account token was locked by the gateway — a new login is required."}
    return {"error": "gateway_error", "code": 502, "detail": text[:300]}


def _gateway_rejection(response):
    """البوابة بترجّع 200 وفيها خطأ داخل الـ payload — نعتبره رفضاً قبل ما نقول تم."""
    if not isinstance(response, dict):
        return None
    err = response.get("error")
    if not err:
        return None
    text = err if isinstance(err, str) else json.dumps(err, ensure_ascii=False)
    return {"ok": False, "error": "offer_rejected", "code": 400,
            "detail": "The gateway refused to execute the offer: %s" % text[:280]}


def _consume_plan(conn, account, offer_id, qty):
    """يشيل الكمية المنفّذة فعلًا من قائمة الشراء المحجوزة للحساب."""
    key = PLAN_KEY % account
    stored = (store.get_meta(conn, key) or {}).get("items") or []
    target = str(offer_id)
    out = []
    left = int(qty)
    changed = False
    for entry in stored:
        if str(entry.get("offer_id")) == target and left > 0:
            take = min(left, max(0, int(entry.get("amount") or 0)))
            remaining = max(0, int(entry.get("amount") or 0) - take)
            left -= take
            changed = True
            if remaining:
                out.append({"offer_id": entry.get("offer_id"), "amount": remaining})
        else:
            out.append(entry)
    if changed:
        store.set_meta(conn, key, {"items": out})
    return changed


def plan(conn, account):
    """قائمة الشراء المحفوظة للحساب: كل بند بكميته وتكلفته + إجمالي كل عملة."""
    idx = _offer_index(conn, account)
    items = []
    totals = {}
    for entry in (store.get_meta(conn, PLAN_KEY % account) or {}).get("items") or []:
        hit = idx.get(str(entry.get("offer_id")))
        if not hit:
            continue
        trader, offer = hit
        qty = max(1, int(entry.get("amount") or 1))
        cost = offer.get("cost") or {}
        total = int(cost.get("amount") or 0) * qty
        asset_id = str(cost.get("asset_id") or "")
        have = balance_of(conn, account, cost) if account and account != "ALL" else 0
        items.append({
            "offer_id": offer.get("offer_id"), "trader": trader.get("name"), "qty": qty,
            "reward": offer.get("reward"), "cost": cost, "total": total,
            "reward_total": int((offer.get("reward") or {}).get("amount") or 1) * qty,
            "balance": have, "shortfall": max(0, total - have),
        })
        row = totals.setdefault(asset_id, {
            "asset_id": asset_id, "name": cost.get("name") or "Currency",
            "image": cost.get("image") or "", "amount": 0, "balance": have})
        row["amount"] += total
    for row in totals.values():
        row["shortfall"] = max(0, row["amount"] - row["balance"])
    return {"items": items, "totals": list(totals.values())}


def edit_plan(conn, account, offer_id=None, amount=1, action="add"):
    """يضيف/يعدّل/يشيل/يمسح بند في قائمة شراء الحساب — بنفس منطق الشراء: حد العرض والرصيد."""
    if not account or account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account first."}
    if not store.get_account(conn, account):
        return {"ok": False, "error": "unknown_account", "detail": "The account does not exist."}
    idx = _offer_index(conn, account)
    stored = {str(e.get("offer_id")): int(e.get("amount") or 1)
              for e in (store.get_meta(conn, PLAN_KEY % account) or {}).get("items") or []
              if str(e.get("offer_id")) in idx}
    if action == "clear":
        stored = {}
    else:
        hit = idx.get(str(offer_id))
        if not hit:
            return {"ok": False, "error": "unknown_offer", "detail": "The offer is not in the catalog."}
        offer = hit[1]
        oid = str(offer.get("offer_id"))
        if action == "remove":
            stored.pop(oid, None)
        else:
            try:
                qty = int(amount)
            except (TypeError, ValueError):
                return {"ok": False, "error": "bad_amount", "detail": "Invalid quantity."}
            if qty < 1:
                return {"ok": False, "error": "bad_amount", "detail": "The quantity must be at least 1."}
            limit = int(offer.get("limit") or 0)
            picked = (stored.get(oid, 0) + qty) if action == "add" else qty
            stored[oid] = min(picked, limit or PLAN_MAX)
    wanted = {}
    for oid, qty in stored.items():
        if qty <= 0:
            continue
        cost = (idx[oid][1].get("cost") or {})
        row = wanted.setdefault(str(cost.get("asset_id") or ""), [cost, 0])
        row[1] += int(cost.get("amount") or 0) * qty
    for cost, total in wanted.values():
        have = balance_of(conn, account, cost)
        if total > have:
            return {"ok": False, "error": "insufficient_funds",
                    "detail": "Balance is not enough: the buy list needs %s %s and the available balance is %s." % (total, cost.get("name"), have),
                    "balance": have, "total": total}
    store.set_meta(conn, PLAN_KEY % account,
                   {"items": [{"offer_id": oid, "amount": qty} for oid, qty in stored.items() if qty > 0]})
    conn.commit()
    return {"ok": True, "account": account, "plan": plan(conn, account)}


def buy(conn, account, offer_id, amount, confirmed=False):
    """ينفّذ عرض تاجر على بوابة Embark الرسمية، ثم يتحقق من المخزون ويحدّث السنابشوت."""
    from . import pioneer_write

    if not confirmed:
        return {"ok": False, "error": "confirmation_required", "code": 428,
                "detail": "The purchase must be executed from the dedicated confirmation window (confirmed=true)."}
    if not account or account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account first."}
    rec = store.get_account(conn, account)
    if not rec:
        return {"ok": False, "error": "unknown_account", "detail": "The account does not exist."}
    if config.DATA_SOURCE != "pioneer":
        return {"ok": False, "error": "legacy_plan_only", "code": 409,
                "detail": "Direct purchase is available only in official Pioneer gateway mode."}
    if not rec.get("token"):
        return {"ok": False, "error": "missing_token", "detail": "No stored token for this account."}
    if pioneer_write.paused():
        return {"ok": False, "error": "write_paused", "code": 423, "detail": pioneer_write.PAUSE_DETAIL}

    hit = _offer_index(conn, account).get(str(offer_id))
    if not hit:
        return {"ok": False, "error": "unknown_offer", "detail": "The offer is not in the catalog."}
    trader, offer = hit
    reward = offer.get("reward") or {}
    cost = offer.get("cost") or {}
    try:
        gateway_offer_id = int(offer.get("offer_id"))
        qty = int(amount)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_amount", "detail": "Invalid offer number or quantity."}
    if qty < 1:
        return {"ok": False, "error": "bad_amount", "detail": "The quantity must be at least 1."}
    limit = int(offer.get("limit") or 0)
    max_qty = limit if limit > 0 else PLAN_MAX
    if qty > max_qty:
        return {"ok": False, "error": "above_limit", "detail": "The quantity is above the offer limit (%s)." % max_qty}
    remaining = offer.get("remaining")
    if limit > 0 and remaining is not None and qty > max(0, int(remaining)):
        return {"ok": False, "error": "daily_limit", "detail": "only %s left on this offer." % max(0, int(remaining))}

    cost_asset = str(cost.get("asset_id") or "")
    reward_asset = str(reward.get("asset_id") or "")
    unit_cost = int(cost.get("amount") or 0)
    total_cost = unit_cost * qty
    expected_reward = int(reward.get("amount") or 1) * qty

    try:
        before = pc.fetch_inventory_for(account)
    except Exception as exc:
        return dict(_purchase_error(exc), stage="pre_inventory")

    actual = _asset_totals(before, [cost_asset, reward_asset])
    if total_cost > actual.get(cost_asset, 0):
        return {"ok": False, "error": "insufficient_funds", "code": 402,
                "detail": "The official balance is not enough: %s %s required, and the available balance is %s." %
                          (total_cost, cost.get("name") or cost_asset, actual.get(cost_asset, 0)),
                "balance": actual.get(cost_asset, 0), "total": total_cost}

    # عروض فتح المستويات بتخصم أصناف من المخزن قبل التسليم: لو مش موجودة البوابة
    # بترد 400 internal error من غير ما تشرح، فبنمنعها هنا وبنقول الناقص بالاسم.
    tree = pioneer_tree.Tree((before or {}).get("items") or [])
    consume, lacking = consume_required(tree, offer, qty)
    if lacking:
        detail = ("This offer also takes %s from your stash, and %s missing. "
                  "Nothing was sent to the gateway and nothing was charged." %
                  (_missing_detail(lacking), "it is" if len(lacking) == 1 else "they are"))
        store.log_action(conn, account, "trade:buy",
                         {"offerId": gateway_offer_id, "itemsToConsume": consume, "amount": qty},
                         "blocked", detail, 0)
        return {"ok": False, "error": "missing_required", "code": 409, "stage": "requirements",
                "detail": detail,
                "required": [{"asset_id": aid, "need": need, "have": got} for aid, need, got in lacking]}

    # الستاش مليان = البوابة بتخصم الثمن وبعدين ترفض التسليم بـ 400 عام. بننقل
    # قطعة مؤقتاً لشنطة اللوداوت، ونعيد القراءة — الشراء ميتّبعتش غير وخانة فضت.
    request = {"offerId": gateway_offer_id, "itemsToConsume": consume, "amount": qty}
    room = {"moved": [], "free": 0, "total": 0}
    for _attempt in range(3):
        full = _stash_full(conn, account, before, reward_asset, qty, expected_reward)
        if not full:
            break
        need = _space_need(conn, account, before, reward_asset, expected_reward)
        step = _auto_make_room(conn, account, need, before)
        if not step.get("ok"):
            store.log_action(conn, account, "trade:buy", request, "blocked", step["detail"], 0)
            return {"ok": False, "error": step.get("error") or "stash_full", "code": 409,
                    "stage": "space_check", "detail": step["detail"],
                    "free_cells": step.get("free"), "total_cells": step.get("total"), "need_cells": need}
        room["moved"].extend(step.get("moved") or [])
        room.update({k: step.get(k) for k in ("free", "total", "before", "mode")})
        if step.get("data"):
            before = step["data"]
            actual = _asset_totals(before, [cost_asset, reward_asset])
            # النقل غيّر نسخ_etag_الرصات، فخطوط الأصناف المطلوبة بتتعيد من القراءة الجديدة.
            consume, lacking = consume_required(pioneer_tree.Tree((before or {}).get("items") or []), offer, qty)
            if lacking:
                detail = ("Clearing room moved the items this offer takes, and %s is no longer "
                          "available in full. Nothing was sent to the gateway." % _missing_detail(lacking))
                store.log_action(conn, account, "trade:buy", request, "blocked", detail, 0)
                return {"ok": False, "error": "missing_required", "code": 409, "stage": "requirements",
                        "detail": detail}
            request["itemsToConsume"] = consume
        _log_make_room(conn, account, step)
    else:
        free, total = _free_stash(before)
        detail = ("The stash is full (%d / %d cells) and clearing cells did not free enough room for the delivery. "
                  "Nothing was purchased and nothing was charged." % (total - free, total))
        store.log_action(conn, account, "trade:buy", request, "blocked", detail, 0)
        return {"ok": False, "error": "stash_full", "code": 409, "stage": "space_check",
                "detail": detail, "free_cells": free, "total_cells": total}

    try:
        response = pc.post_json(OFFER_ACCEPT_PATH, request, token=rec["token"])
    except Exception as exc:
        store.log_action(conn, account, "trade:buy", request, "failed", str(exc)[:300], 0)
        if _not_enough_space(exc):
            # القراءة فاتت على أمل إن حد فضّى خانة في اللعبة — البوابة رفضت برضه.
            free, total = _free_stash(before)
            if consume and free:
                # الخامات متبعتة وفي الخانات سِعة: 400 عام هنا معناه إن نسخة_etag_
                # رصة مطلوبة اتغيّرت بعد القراءة (الستاش اتلمس في اللعبة مثلاً).
                return {"ok": False, "error": "stale_tree", "code": 409, "stage": "accept",
                        "detail": ("The gateway refused the purchase even though %s is included and the stash "
                                   "has room (%d free of %d cells) — the inventory copy it was read from has "
                                   "changed since. Press SYNC and buy again; nothing was charged." %
                                   ("the offer items" if qty > 1 else "the offer item", free, total)),
                        "free_cells": free, "total_cells": total, "gateway": str(exc)[:200]}
            return {"ok": False, "error": "stash_full", "code": 409, "stage": "accept",
                    "detail": ("The gateway refused the purchase: the stash is full (%d / %d cells), so the item "
                               "cannot be delivered. Buy inside the game for now, or free a cell and try again. "
                               "The balance was not charged." % (total - free, total)),
                    "free_cells": free, "total_cells": total, "gateway": str(exc)[:200]}
        return dict(_purchase_error(exc), stage="accept")
    rejected = _gateway_rejection(response)
    if rejected:
        store.log_action(conn, account, "trade:buy", request, "rejected", rejected["detail"], qty)
        if room["moved"]:
            _put_items_back(conn, account, room, before)
        return dict(rejected, stage="accept")

    try:
        after = pc.fetch_inventory_for(account)
    except Exception as exc:
        store.log_action(conn, account, "trade:buy", request, "accepted_unverified", str(exc)[:300], qty)
        return {"ok": True, "executed": True, "verified": False, "account": account,
                "offer_id": gateway_offer_id, "qty": qty, "detail":
                    "The gateway accepted the purchase, but the verification read failed — press SYNC before any other operation.",
                "error": str(exc)[:300]}

    post_totals = _asset_totals(after, [cost_asset, reward_asset])
    cost_delta = post_totals.get(cost_asset, 0) - actual.get(cost_asset, 0)
    reward_delta = post_totals.get(reward_asset, 0) - actual.get(reward_asset, 0)
    # التحقق المعتبر: البوابة قبلت + الثمن اتخصم من الرصيد الرسمي. الشحنة نفسها
    # ممكن تنزل في أي مكان (تجهيز/أوفر فلو/قطعة مش ستاك) ففرقها استعلامي بس.
    paid = cost_delta == -total_cost
    refreshed = pioneer_write._refresh_data(conn, account, after)
    _consume_plan(conn, account, gateway_offer_id, qty)
    summary = {
        "trader": trader.get("name"), "reward": reward.get("name"), "cost": cost.get("name"),
        "cost_delta": cost_delta, "reward_delta": reward_delta,
        "expected_reward": expected_reward, "expected_cost": -total_cost,
    }
    store.log_action(conn, account, "trade:buy", request,
                     "executed" if paid else "accepted_unverified", summary, qty)

    detail = ("Bought %s × %s for %s %s." %
              (qty, reward.get("name") or "the item", total_cost, cost.get("name") or "the currency"))
    if room["moved"]:
        detail += _moved_note(room["moved"], room["free"], room["total"])
        restored = _put_items_back(conn, account, room, after)
        if restored:
            detail += _restored_note(restored)
            try:
                refreshed = pioneer_write._refresh_data(conn, account,
                                                        pc.fetch_inventory_for(account))
            except Exception:
                pass
    if not paid:
        detail += " the gateway accepted the request but the deduction did not appear in the tree — press SYNC and check the balance."
    elif reward_delta < expected_reward:
        detail += " the item may have landed somewhere else in the stash — press SYNC."
    return {"ok": True, "executed": True, "verified": paid, "account": account,
            "offer_id": gateway_offer_id, "qty": qty, "detail": detail,
            "summary": summary, "deltas": {"cost": cost_delta, "reward": reward_delta},
            "balance": post_totals.get(cost_asset, 0), "refreshed": refreshed}
