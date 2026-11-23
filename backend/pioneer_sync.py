"""بناء مخزن محلي من بوابة Pioneer الرسمية مباشرة — قراءة فقط.

`GET /v1/pioneer/inventory` بيرجّع كل الأصول المسجّلة للحساب: عناصر المخزن،
سلوتات الحاويات، المظاهر، الإيموتات، وعملات/إحصائيات. الموديول ده بيفلتر
العناصر الحقيقية بس ويبني payload بنفس شكل Rampart اللي بقية المشروع متعوّد
عليه (stash/backpack/overflow/containers/item_mappings/stats) عشان اللوحة
والمزامنة تكمل من غير أي طلب لأي خدمة خارجية.

الرد الرسمي فيه الشجرة كاملة (كل عنصر عنده slots فيها أولاده)، فبنقرأ المواقع
الحقيقية من pioneer_tree: الستاش، شنطة الـ loadout المفعّلة، وخانات التجهيز.
شجرات الـ loadouts المحفوظة (presets) مش بتتحسب كستاش.
"""
import csv
import gzip
import json
import os
import re

from . import (asset_meta, config, gearops, items_db, knowledge, pioneer_client as pc,
               pioneer_tree, store)

ASSET_INDEX_FILE = os.path.join(config.DATA_DIR, "catalog", "asset_index.csv")
CATALOG_FILE = os.path.join(config.DATA_DIR, "items_catalog.json")
META_INDEX_FILE = os.path.join(config.DATA_DIR, "metaforge_items_cache.json")
GAME_DATA_FILE = os.path.join(config.DATA_DIR, "pioneer_game_data.json")

# أرقام أصول مش عناصر مخزن: عملات/إكس بي/إحصائيات.
PSEUDO = {
    "1672558715": ("xp", None),
    "-898439395": ("coins", "99aa07df-211c-4b66-b360-308f66a305c3.webp"),
    "3396527901": ("coins", "99aa07df-211c-4b66-b360-308f66a305c3.webp"),
    "1979925731": ("cred", "ad766af4-f4a4-4922-ac01-9c3d677a067a.webp"),
    "941631263": ("tokens", "92e89cae-a386-4980-abe4-625540bece89.webp"),
}
# أصول مش موجودة في المخزن: عملات مواسم + عدّادات إحصائيات + محطات الهيدآوت.
SKIP_PREFIX = ("DA_Item_Currency_", "DA_Item_XP", "DA_Item_Rounds")
SKIP_CONTAINS = ("Station_", "Bench", "Smelter", "ResourceGenerator")

# درجة السلاح: البوابة بترمّزها في اسم الأصل نفسه (_Quality0..3 = فل 1..4)،
# ولما الاسم مالوش أصل في الفهرس بنرجع للرقم الروماني في آخر الاسم المعروض.
QUALITY_MARK = re.compile(r"_Quality([0-4])(?:_|$)")
TIER_TAIL = re.compile(r"\s(I|II|III|IV|V)$", re.I)
ROMAN_TIER = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
BLUEPRINT_TAIL = re.compile(r"\s*blueprint\s*$", re.I)
# الاسم اللي بنولّده من الرقم لوحده مش دليل على إننا عرفنا القطعة.
DERIVED_NAME = re.compile(r"^Item -?\d+$")

_cache = {"key": None, "index": None, "catalog": None, "metaforge": None}


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _sources():
    """يقرأ الفهرس/الكتالوج/الحاجات المحلية، ويعيد بناء الكاش لو الملفات اتغيرت."""
    def stamp(f):
        try:
            return os.path.getmtime(f)
        except OSError:
            return -1.0
    # الفهرس المحلي (اللي بكتبه pioneer_tree.remember) لازم يدخل المفتاح والقراءة
    # مع بعض: من غيره أي اسم بنسجله لقطعة باتش جديد بيفضل مخفي عن اللوحة.
    key = (stamp(ASSET_INDEX_FILE), stamp(pioneer_tree.ASSET_LOCAL_FILE), stamp(CATALOG_FILE))
    if _cache["key"] == key and _cache["index"] is not None:
        return _cache

    index = {}
    for path in (ASSET_INDEX_FILE, pioneer_tree.ASSET_LOCAL_FILE):
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if row.get("game_asset_id"):
                        index[row["game_asset_id"]] = row
        except OSError:
            pass

    catalog = {}
    data = _read_json(CATALOG_FILE) or {}
    unnamed = {}
    for entry in (data.get("items") or {}).values():
        for variant in entry.get("variants") or []:
            asset_id = variant.get("asset_id")
            if asset_id not in (None, "", "None"):
                catalog.setdefault(str(asset_id), variant)
            else:
                unnamed.setdefault(str(variant.get("name") or "").strip().lower(), variant)

    # صفحة الويكي بتيجي من غير asset_id، فالقطعة اللي الفهرس المحلي عرف رقمها
    # بتفضل بلا ندرة وبلا تصنيف. ربطها بالاسم بيخلي التسمية الوحيدة اللي عندنا
    # (الفهرس) تفتح بقية الداتا، والكاتالوج يفضل قابل لإعادة البناء من غير ما
    # نغيّره.
    if unnamed:
        for asset_id, row in index.items():
            variant = unnamed.get(str(row.get("display_name") or "").strip().lower())
            if variant is not None:
                catalog.setdefault(str(asset_id), variant)

    metaforge = {}
    data = _read_json(META_INDEX_FILE) or {}
    for entry in (data.get("items") or {}).values():
        name = (entry.get("name") or "").strip().lower()
        if name and entry.get("image_local"):
            metaforge.setdefault(name, entry["image_local"])

    _cache.update({"key": key, "index": index, "catalog": catalog, "metaforge": metaforge})
    return _cache


_game_cache = {"key": None, "info": {}}


def official_info():
    """`gameAssetId -> (itemType, maxAmount)` من رد اللعبة الرسمي (pioneer_game_data.json).

    المخزن الحقيقي = `GameItem` بسعة معقولة؛ الباقي سجلات حساب (مهارات، مظاهر،
    أيقونات فتح، إيموتات) وعدّادات/عملات بسعة 2e9 — بتترجع عائمة في الشجرة،
    ولو قبلناها بلاطات لاحت اللوحة بعلامات استفهام مش قطعة واحدة منها.
    بنحتفظ بالاختصار بس عشان الملف 10 ميجا والجهاز ضعيف.
    """
    try:
        key = (os.path.getmtime(GAME_DATA_FILE), os.path.getsize(GAME_DATA_FILE))
    except OSError:
        return {}
    if _game_cache["key"] != key:
        data = _read_json(GAME_DATA_FILE) or {}
        rows = (data.get("items-description") or {}).get("itemDescriptions") or []
        if isinstance(rows, dict):
            rows = [dict(r, gameAssetId=aid) for aid, r in rows.items()]
        _game_cache.update({"key": key,
                            "info": {str(r.get("gameAssetId")): (str(r.get("itemType") or ""),
                                                                 int(r.get("maxAmount") or 0))
                                     for r in rows}})

    return _game_cache["info"]


def _named_assets(mappings):
    """الـ asset ids اللي ليها اسم حقيقي في الـ mappings المحفوظة.

    الاسم المشتق «Item <رقم>» مش تسمية: لولا الفلتر ده آخر مزامنة بتسجّل
    المجهول في الـ snapshot وبعدها المزامنة اللي بعدها تعدّه معروفاً،
    فالعلامة الاستفهام بتعيش مهما نضّفنا.
    """
    out = set()
    for aid, row in (mappings or {}).items():
        if isinstance(row, dict):
            name = str(row.get("display_name") or row.get("name") or "").strip()
        else:
            name = str(row or "").strip()
        if name and not DERIVED_NAME.match(name):
            out.add(str(aid))
    return out


def _snapshot_mappings(conn, account):
    """item_mappings من آخر snapshot محفوظ — مصدر أسماء ثانوي لعناصر الفهرس مايعرفهاش."""
    try:
        path = store.latest_snapshot_path(conn, account)
    except Exception:
        return {}
    if not path or not os.path.isfile(path):
        return {}
    try:
        with gzip.open(path, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return payload.get("item_mappings") or {}


def _local_image(*candidates):
    for name in candidates:
        if not name:
            continue
        rel = str(name).replace("\\", "/")
        if ".." in rel.split("/"):
            continue
        if os.path.isfile(os.path.join(config.ITEM_ASSETS_DIR, rel)):
            return rel
    return ""


def _cell_item(asset_id, asset_name, known):
    """هل اللي جوه الخانة دي عنصر؟

    الفهرس العام متوقّف عند باتش قديم: القطع الجديدة بتيجي من غير اسم خالص،
    ولو أنكرنا كل مش معروف بتختفي من اللوحة وهي قدام عين المستخدم في شنطة
    اللعبة. فاللي مالوش اسم بنعتبره عنصر (الستاش والشنطة ما بيشيلوش غير عناصر)،
    والتركيبية المعروفة بأسمائها (DA_ModSlot_/Station_/Currency) بتفضل مرفوضة.
    """
    if asset_id in PSEUDO:
        return False
    if not asset_name:
        return True
    return _is_item(asset_id, asset_name, known)


def _is_item(asset_id, asset_name, known):
    if asset_id in PSEUDO:
        return False
    if asset_name.startswith(SKIP_PREFIX) or any(mark in asset_name for mark in SKIP_CONTAINS):
        return False
    return asset_name.startswith("DA_Item") or asset_id in known


def _item_meta(asset_id, indexed, catalog, snapshot, metaforge):
    """اسم/نوع/ندرة/قيمة/صورة لعنصر واحد: الجدول المتقاطع ثم الفهرس ثم snapshot ثم الكتالوج."""
    fixed = asset_meta.get(asset_id)
    name = (fixed.get("name") or indexed.get("display_name") or "").strip()
    extra = catalog or {}
    snap = snapshot or {}
    if not name:
        name = (snap.get("display_name") or snap.get("name") or extra.get("name") or "").strip()
    if not name:
        name = "Item %s" % asset_id

    item_type = fixed.get("type") or extra.get("type") or snap.get("type") or ""
    rarity = fixed.get("rarity") or extra.get("rarity") or snap.get("rarity") or ""
    value = fixed.get("value")
    if value is None:
        value = extra.get("value")
    if value is None:
        value = snap.get("value")
    stack = fixed.get("stack_size") or extra.get("stack_size") or snap.get("stack_size")
    image = _local_image(fixed.get("image"), metaforge.get(name.strip().lower()), extra.get("image"),
                         snap.get("image_filename"))
    # الكتالوج المحلي ما بيغطيش عناصر الباتش الجديد، فبلاطاتها بتفضل بلا ندرة
    # وتصنيف وصورة حتى بعد ما الفهرس المحلي يعرف اسمها. المرجع التاني:
    # قاعدة العناصر المخزنة على الديسك — بنفس الاسم اللي فات الفهرس.
    if not (item_type and rarity and image):
        official = items_db.find(asset_id=str(asset_id), name=name) or {}
        item_type = item_type or official.get("type") or ""
        rarity = rarity or official.get("rarity") or ""
        if value is None:
            value = official.get("value")
        if stack is None:
            stack = official.get("stack_size")
        image = image or _local_image(items_db.icon_for(official))
    level = _weapon_level(indexed.get("game_asset_name") or "", name,
                          gearops.is_weapon({"name": name, "type": item_type}))
    return {
        "name": name,
        "display_name": name,
        "type": item_type,
        "rarity": rarity,
        "value": value,
        "image_filename": image,
        "stack_size": stack,
        "is_blueprint": bool(fixed.get("is_blueprint") or extra.get("is_blueprint")
                             or str(item_type).lower() == "blueprint"),
        "max_attachments": extra.get("max_attachments"),
        "level": level or None,
        "quality_level": (level - 1) if level else None,
        "max_health": (100 + (level - 1) * 10) if level else None,
    }


def _is_weapon_row(info):
    """نفس فحص gearops.is_weapon لكن على بيانات _item_meta الخام."""
    return gearops.is_weapon({"name": info.get("name"), "type": info.get("type")})


def _weapon_level(asset_name, name, is_weapon):
    """فل السلاح (1..4)، و0 لما الدرجة تكون مجهولة.

    الاسم المشتق «Item <رقم>» مش دليل، فبنعتبره مجهولاً عشان اللوحة ما تفتكرش
    إن قطعة بلا اسم سلاح من الدرجة الأولى.
    """
    if not is_weapon:
        return 0
    match = QUALITY_MARK.search(asset_name or "")
    if match:
        return int(match.group(1)) + 1
    base = BLUEPRINT_TAIL.sub("", str(name or "").strip())
    if base.startswith("Item "):
        return 0
    match = TIER_TAIL.search(base)
    return ROMAN_TIER.get(match.group(1).upper(), 0) if match else 0


def _health(entry, max_health):
    """المتانة بالأرقام الصحيحة زي ما اللعبة بتعرضها (79/110 مش 0.72/1).

    البوابة بترجّع durability كنسبة و maxDurability = 1 دايمًا، فالسقف لازم
    يجي من درجة السلاح. لغير الأسلحة السقف مجهول فبنسيب النسبة زي ما هي.
    """
    raw = entry.get("durability")
    top = entry.get("maxDurability")
    if raw is None or not max_health:
        return raw, top
    try:
        ratio = float(raw) / (float(top) or 1.0)
    except (TypeError, ValueError):
        return raw, top
    cap = int(max_health)
    return int(round(min(1.0, max(0.0, ratio)) * cap)), cap


def _slot_entries(tree, item_id, meta):
    """خانات مرفقات السلاح — الفاضية زي الممتلئة.

    البوابة بتحط تحت كل سلاح ابن لكل خانة من نوع DA_ModSlot_*، والمرفق
    المركّب بيكون ابن الخانة. فيه كمان ابن واحد لكل سلاح مش في الفهرس
    العام ومفيش له أولاد خالص (بقايا موديل السلاح)، وده مش خانة مرفق
    فالمنطق بيشيلّه عشان العدد يطلع زي ما اللعبة بتعرضه. بنستثني بس
    لو طلع فيه مرفق فعلي — مفيش مرفق حقيقي يختفي من الواجهة.
    """
    out = []
    for kid in tree.children(item_id):
        entry = tree.by_id.get(kid) or {}
        asset_id = str(entry.get("gameAssetId"))
        indexed = meta["index"].get(asset_id) or {}
        asset_name = indexed.get("game_asset_name") or ""
        if _is_item(asset_id, asset_name, meta["known"]):
            continue
        rule = (meta.get("rules") or {}).get(asset_id) or {}
        att_id = tree.first_child(kid)
        att = tree.by_id.get(att_id) if att_id else None
        is_slot = (asset_name.upper().startswith("DA_MODSLOT_") or bool(rule) or att)
        if not is_slot:
            continue
        label = (indexed.get("display_name") or "").strip() or "Mod Slot"
        slot = {"instance_id": kid, "instanceId": kid, "wrapper_id": kid, "wrapperId": kid,
                "slot_asset_id": asset_id, "slot_name": rule.get("name") or "mod_slot",
                "name": label, "display_name": label, "is_empty": True, "asset_id": None,
                "rarity": None, "value": 0, "image_filename": "", "level": None, "etag": ""}
        if att:
            att_asset = str(att.get("gameAssetId"))
            info = _item_meta(att_asset, meta["index"].get(att_asset) or {},
                              meta["catalog"].get(att_asset), meta["snapshot"].get(att_asset),
                              meta["metaforge"])
            slot.update({"is_empty": False, "asset_id": att_asset,
                         "instance_id": att_id, "instanceId": att_id,
                         "etag": att.get("etag") or "",
                         "amount": int(att.get("amount") or 1),
                         "durability": att.get("durability"),
                         "max_durability": att.get("maxDurability"),
                         "name": info["name"], "display_name": info["display_name"],
                         "rarity": info["rarity"], "type": info["type"],
                         "value": info["value"] or 0, "image_filename": info["image_filename"]})
        out.append(slot)
    return out


def _slot(tree, wrapper_id, container_id, slot_index, meta):
    """خانة واحدة بشكل Rampart: wrapper_id + العنصر اللي جواها (لو موجود)."""
    slot = {"container_id": container_id, "slot_index": slot_index,
            "wrapper_id": wrapper_id, "is_empty": True, "item": None}
    item_id = tree.first_child(wrapper_id)
    if not item_id:
        return slot
    entry = tree.by_id.get(item_id) or {}
    asset_id = str(entry.get("gameAssetId"))
    indexed = meta["index"].get(asset_id) or {}
    if not _cell_item(asset_id, indexed.get("game_asset_name") or "", meta["known"]):
        return slot
    info = _item_meta(asset_id, indexed, meta["catalog"].get(asset_id),
                      meta["snapshot"].get(asset_id), meta["metaforge"])
    amount = int(entry.get("amount") or 1)
    cur, mx = _health(entry, info["max_health"])
    mods = _slot_entries(tree, item_id, meta) if _is_weapon_row(info) else []
    item = {
        "id": item_id,
        "instanceId": item_id,
        "wrapperId": wrapper_id,
        "gameAssetId": entry.get("gameAssetId"),
        "asset_id": asset_id,
        "is_empty": False,
        "amount": amount,
        "quantity": amount,
        "durability": cur,
        "max_durability": mx,
        "etag": entry.get("etag") or "",
        "attachments": mods,
        "max_attachments": len(mods) or info["max_attachments"],
        "name": info["name"],
        "display_name": info["display_name"],
        "rarity": info["rarity"],
        "type": info["type"],
        "image_filename": info["image_filename"],
        "image_wide": info["image_filename"],
        "value": info["value"],
        "stack_size": info["stack_size"],
        "level": info["level"],
        "quality_level": info["quality_level"],
        "is_blueprint": info["is_blueprint"],
    }
    slot.update({"is_empty": False, "item": item})
    meta["mappings"].setdefault(asset_id, {
        "name": info["name"], "display_name": info["display_name"], "type": info["type"],
        "rarity": info["rarity"], "value": info["value"],
        "image_filename": info["image_filename"], "stack_size": info["stack_size"],
        "is_blueprint": info["is_blueprint"], "level": info["level"],
        "quality_level": info["quality_level"],
    })
    return slot


def _loose_slot(tree, item_id, entry, slot_index, meta):
    """عنصر الأوفر ستاش — عائم في الشجرة من غير خانة أب (زي ما البوابة بترجّعه)."""
    asset_id = str(entry.get("gameAssetId"))
    indexed = meta["index"].get(asset_id) or {}
    info = _item_meta(asset_id, indexed, meta["catalog"].get(asset_id),
                      meta["snapshot"].get(asset_id), meta["metaforge"])
    amount = int(entry.get("amount") or 1)
    cur, mx = _health(entry, info["max_health"])
    mods = _slot_entries(tree, item_id, meta) if _is_weapon_row(info) else []
    item = {
        "id": item_id,
        "instanceId": item_id,
        "wrapperId": "",
        "gameAssetId": entry.get("gameAssetId"),
        "asset_id": asset_id,
        "is_empty": False,
        "amount": amount,
        "quantity": amount,
        "durability": cur,
        "max_durability": mx,
        "etag": entry.get("etag") or "",
        "attachments": mods,
        "max_attachments": len(mods) or info["max_attachments"],
        "name": info["name"],
        "display_name": info["display_name"],
        "rarity": info["rarity"],
        "type": info["type"],
        "image_filename": info["image_filename"],
        "image_wide": info["image_filename"],
        "value": info["value"],
        "stack_size": info["stack_size"],
        "level": info["level"],
        "quality_level": info["quality_level"],
        "is_blueprint": info["is_blueprint"],
    }
    meta["mappings"].setdefault(asset_id, {
        "name": info["name"], "display_name": info["display_name"], "type": info["type"],
        "rarity": info["rarity"], "value": info["value"],
        "image_filename": info["image_filename"], "stack_size": info["stack_size"],
        "is_blueprint": info["is_blueprint"], "level": info["level"],
        "quality_level": info["quality_level"],
    })
    return {"container_id": "overflow", "slot_index": slot_index, "wrapper_id": "",
            "is_empty": False, "item": item}


def build_payload(conn, account, data=None):
    """يرجع payload المخزن بالشكل اللي store/derive بيفهموه، من البوابة مباشرة.

    المواقع بقت حقيقية: STASH من Stash VIII، BACKPACK من شنطة الـ loadout المفعّل،
    والتجهيز من خانات الـ loadout نفسها. شجرات الـ loadouts المحفوظة (presets)
    مش بتتحسب كستاش — كل حاجة في مكانها الفعلي.
    """
    if data is None:
        data = pc.fetch_inventory_for(account)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise pc.PioneerError("The direct response has no items list.")
    tree = pioneer_tree.Tree(items)
    lay = pioneer_tree.layout(tree)

    src = _sources()
    snapshot = _snapshot_mappings(conn, account)
    meta = {
        "index": src["index"], "catalog": src["catalog"], "metaforge": src["metaforge"],
        "snapshot": snapshot, "known": set(src["catalog"]) | _named_assets(snapshot),
        "mappings": {},
        "rules": gearops.slot_rules(),
    }

    stats = {key: {"value": 0, "image": image} for key, image in
             (("coins", PSEUDO["-898439395"][1]), ("cred", PSEUDO["1979925731"][1]),
              ("xp", None), ("tokens", PSEUDO["941631263"][1]))}
    owned = set()
    for entry in tree.items:
        asset_id = str(entry.get("gameAssetId"))
        owned.add(asset_id)
        if asset_id in PSEUDO:
            stats[PSEUDO[asset_id][0]]["value"] += int(entry.get("amount") or 0)

    stash = [_slot(tree, wrapper, "stash", index, meta)
             for index, wrapper in enumerate(lay["stash"]["slots"])]
    backpack = [_slot(tree, slot["wrapper"], "backpack", index, meta)
                for index, slot in enumerate(lay["backpack"]["slots"])]
    containers = {}
    for key, slots in lay["loadout"]["slots"].items():
        if key not in ("shield", "gun_1", "gun_2", "quick_use", "safe_pocket", "augmented_slots"):
            continue
        containers[key] = [_slot(tree, slot["wrapper"], key, index, meta)
                           for index, slot in enumerate(slots)]
    if lay["augment"]:
        containers["augment"] = [_slot(tree, lay["augment"]["wrapper"], "augment", 0, meta)]
    augment_asset = None
    if lay["augment"] and lay["augment"].get("item"):
        augment_entry = tree.by_id.get(lay["augment"]["item"]) or {}
        augment_asset = str(augment_entry.get("gameAssetId") or "")

    # الأوفر ستاش = العناصر العائمة (من غير أب) اللي نوعها عنصر مخزن معروف.
    # البوابة بتحط فيه الليت الزيادة عن الـ 280 خانة وبترجّعه عائم في الشجرة،
    # وبتسحب منه تلقائياً أول ما خانة ستاش تفضى. الكوزمتيكس/الإحصائيات
    # مش عناصر مخزن فمش بتتضمّن (مش في الكتالوج ولا شُفت قبل كده في الأقسام).
    known_aids = set(src["catalog"]) | _named_assets(snapshot) | _named_assets(meta["mappings"])
    # محتوى أي حاوية حقيقية (الستاش / الشنطة / اللوداوت) مابيتعدّش عائم — حماية من
    # الرجوع لحالة "البوابة بعتت الـ parent" اللى كان بيعمل بلاطة مكررة لكل قطعة.
    mounted = set()
    for node in (lay["stash"].get("slots") or []) + (lay["backpack"].get("slots") or []):
        mounted.add(node if isinstance(node, str) else (node or {}).get("wrapper"))
    for slots in (lay["loadout"].get("slots") or {}).values():
        for slot in slots or []:
            mounted.add((slot or {}).get("wrapper"))
    mounted.discard(None)
    overflow = []
    for iid in tree.roots():
        entry = tree.by_id.get(iid) or {}
        aid = str(entry.get("gameAssetId"))
        if iid in mounted:
            continue
        if aid not in known_aids:
            # البند مش في الكتالوج. الفهرس المحلي بيعرف اسم الأصل مش اسم العرض بس:
            # DA_Item_SMG_01_Quality0 = سلاح حقيقي (Bobcat I) وليه بنات مرفقات،
            # فاستبعاده بالاسم كان بيخفّي كل بنادق الباتش الجديد من الأوفر (الحساب
            # 2026-11-13: 10 بوبكات + Il Toro IV اختفوا). القوالب الحقيقية هي اللي
            # أسماؤها DA_Inventory_* — دي بتتشال هنا.
            asset_name = str((src["index"].get(aid) or {}).get("game_asset_name") or "").upper()
            if aid in PSEUDO or asset_name.startswith("DA_INVENTORY_"):
                continue
            # البوتقة الأخيرة: رد اللعبة الرسمي بيفصّل الأصل. المخزن الحقيقي =
            # GameItem، والباقي (CharacterSkill/CharacterItem/OnlineItem/Emote/NPC)
            # سجلات حساب بتترجع عائمة في الشجرة — قبلناها كلوت وملئت اللوحة
            # علامات استفهام. اللي مالوش سجل خالص (نزل في باتش جديد) بيفضل ظاهر.
            official = official_info().get(aid) or ("", 0)
            if official[0] and (official[0] != "GameItem" or official[1] >= 1000000):
                continue
        # السلاح في الأوفر ستاش بيطلع له أولاد (خانات المرفقات) فمش بنعتبره حاوية:
        # بنستبعد بس الأبواب اللي جواها عناصر حقيقية — هياكل الـ loadout والشنط.
        kids = tree.children(iid)
        # شجرة خانات الأوجمنت نفسها بيفضل عائم في الشجرة على طول (أولاده كلهم
        # DA_Inventory_*_ContainerSlot_* من غير أي قطعة جواها) — القطعة الحقيقية
        # مالهاش أولاد خالص. مقيس G14 2026-11-04: القالب كان بيوصل نفسه كبلاطة
        # "شنطة" في الأوفر، والبوابة بترفض تنقله لأنه مش قطعة أصلًا.
        if kids and all(str((meta["index"].get(str((tree.by_id.get(k) or {}).get("gameAssetId"))) or {})
                             .get("game_asset_name") or "").upper().startswith("DA_INVENTORY_")
                        for k in kids):
            continue
        if kids and any(_is_item(str((tree.by_id.get(k) or {}).get("gameAssetId")),
                                 (meta["index"].get(str((tree.by_id.get(k) or {}).get("gameAssetId"))) or {})
                                 .get("game_asset_name") or "",
                                 meta["known"]) for k in kids):
            continue
        overflow.append(_loose_slot(tree, iid, entry, len(overflow), meta))

    return {
        "source": "pioneer",
        "stats": stats,
        "augment": {"asset_id": augment_asset},
        "stash": stash,
        "overflow": overflow,
        "backpack": backpack,
        "containers": containers,
        "allowed_slots": {},
        "bench_levels": knowledge.bench_levels_from_tree(tree),
        "unlocked_blueprints": knowledge.unlocked_rows(tree),
        "owned_asset_ids": sorted(int(a) for a in owned if a.lstrip("-").isdigit()),
        "item_mappings": meta["mappings"],
        "locations": {
            "stash_container": lay["stash"]["container"],
            "backpack_container": lay["backpack"]["container"],
            "loadout": lay["loadout"]["name"],
            "loadout_mode": lay["loadout"]["mode"],
            "equipped_loadout": lay["loadout"].get("equipped_name") or "",
            "pointed": bool(lay["loadout"].get("pointed")),
        },
    }
