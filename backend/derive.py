"""استخراج نفس أسماء العناصر وقواعد الفلترة المستخدمة في auto_sync_v2.py (بدون استيراد السكربت).

الهدف: أرقام اللوحة المحلية تطابق اللي بيشوفه سكريبت المزامنة:
  - اسم العنصر من display_name/name، ومعادلة blueprint والمستوى الروماني للسلاح.
  - استبعاد العناصر التالفة (نفس الشرط).
  - تجميع per-account ثم الدمج بين الحسابات بـ max (مش sum).
"""
import re

from . import asset_meta

FIREARM_TYPES = ("weapon", "smg", "assault rifle", "battle rifle", "shotgun", "sniper rifle",
                 "hand cannon", "lmg", "pistol")
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
ROMANToInt = {v: k for k, v in ROMAN.items()}
TIER_TAIL = re.compile(r"\s(I|II|III|IV|V)$", re.I)
ASSET_ID_KEYS = ("asset_id", "gameAssetId", "game_asset_id", "item_id", "template_id", "def_id")


def is_firearm_type(item_type):
    t = str(item_type or "").lower()
    return any(k in t for k in FIREARM_TYPES)


def mapping_for(item_data, slot, mappings):
    for src in (item_data, slot):
        for key in ASSET_ID_KEYS:
            val = src.get(key)
            if val is not None and str(val) in mappings:
                return mappings[str(val)] or {}
    return {}


def hp_values(item_data):
    cur = next((item_data.get(k) for k in ("durability", "health", "condition") if item_data.get(k) is not None), None)
    mx = next((item_data.get(k) for k in ("max_durability", "maxDurability", "max_health", "maxHealth", "maxCondition")
               if item_data.get(k) is not None), None)
    return cur, mx


def read_level(item_data, slot, mapping):
    for src in (item_data, slot):
        for key in ("level", "tier"):
            if src.get(key) is not None:
                val = src.get(key)
                if isinstance(val, int):
                    return val
                return ROMANToInt.get(str(val).strip().upper(), 0)
    val = mapping.get("level")
    if isinstance(val, int):
        return val
    return ROMANToInt.get(str(val or "").strip().upper(), 0)


def is_blueprint(item_data, slot, mapping):
    if item_data.get("is_blueprint") or slot.get("is_blueprint"):
        return True
    if str(item_data.get("type") or "").strip().lower() == "blueprint":
        return True
    if mapping.get("is_blueprint") is True or str(mapping.get("type") or "").lower() == "blueprint":
        return True
    for key in ("category", "item_category", "itemCategory"):
        blob = str(mapping.get(key) or "").lower()
        if "recipe" in blob or "blueprint" in blob:
            return True
    return False


def parse_slot(slot, mappings, keep_damaged=False):
    """يرجع (اسم، كمية، تفاصيل العرض) أو None لو العنصر مستبعد (تالف/فاضي).

    keep_damaged=True يستخدم للوحة الإدارة فقط: بنعرض القطع التالفة لكن أرقام
    auto_sync (الافتراضي False) بتفضل محسوبة بنفس الشرط القديم حرفياً.
    """
    if not isinstance(slot, dict) or slot.get("is_empty", True):
        return None
    item_data = slot.get("item")
    if not isinstance(item_data, dict):
        return None
    mapping = mapping_for(item_data, slot, mappings)
    asset_id = str(item_data.get("asset_id") if item_data.get("asset_id") is not None
                   else (item_data.get("gameAssetId") or ""))
    # الجدول المتقاطع هو المرجع الأخير للاسم: البوابة بتحذف درجة المرفق
    # (Extended Barrel بدل Extended Barrel III) وبتلحق "Blueprint" بالديزاين
    # والستنسل، والـ mapping المحفوظ بيكرّر نفس النقص. فالاشتقاق القديم بيشتغل
    # بس للأصول اللي الجدول لسه ما يعرفهاش.
    official = asset_meta.name(asset_id)
    name = official or str(item_data.get("display_name") or item_data.get("name")
                           or mapping.get("display_name") or mapping.get("name") or "Unknown").strip()
    if not official and (mapping.get("display_name") or mapping.get("name")):
        name = str(mapping.get("display_name") or mapping.get("name")).strip()

    item_type = str(mapping.get("type") or item_data.get("type") or "")
    firearm = is_firearm_type(item_type)
    blueprint = is_blueprint(item_data, slot, mapping)

    cur, mx = hp_values(item_data)
    stats = item_data.get("stats") or {}
    for key in ("health", "durability", "condition"):
        st = stats.get(key)
        if isinstance(st, dict):
            if cur is None:
                cur = st.get("current") if st.get("current") is not None else st.get("value")
            if mx is None:
                mx = st.get("max")

    level = read_level(item_data, slot, mapping)
    ql = item_data.get("quality_level")
    if ql is None:
        ql = mapping.get("quality_level")
    if firearm and not level and isinstance(ql, int) and 0 <= ql <= 4:
        level = ql + 1

    damaged = False
    # المتانة الحقيقية بالأرقام (79/110) بتقول التالف لوحده؛ شرط «الدرجة أقل من
    # IV يبقى تالف» كان بديل مصنوع من زمن الرد ما كانش بيجيب مقام صحة صحيح،
    # ولو فضل شغال مع الأرقام الحقيقية كان وسم سلاح سليم كاملة أنه تالف.
    real_health = cur is not None and mx is not None and int(mx) > 1
    if firearm and cur is not None and mx is not None and int(cur) < int(mx):
        damaged = True
    if blueprint:
        damaged = False
        if not official:
            name = (re.sub(r"\s*blueprint\s*", " ", name, flags=re.I).strip() + " Blueprint")
    elif firearm and 0 < level < 4 and not real_health:
        damaged = True
    elif firearm and level > 0 and not official and not TIER_TAIL.search(name):
        name = "%s %s" % (name, ROMAN.get(min(level, 5), ""))

    if damaged and not keep_damaged:
        return None

    qty = item_data.get("quantity")
    if qty is None:
        qty = item_data.get("count")
    if qty is None:
        qty = item_data.get("amount", 1)
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 1

    uid = str(item_data.get("id") or slot.get("id") or "slot_%s" % slot.get("slot_index"))
    return {
        "name": re.sub(r"\s+", " ", name).strip(),
        "qty": qty,
        "uid": uid,
        "rarity": str(item_data.get("rarity") or mapping.get("rarity") or ""),
        "type": str(item_type or ""),
        "category": mapping.get("category") or item_data.get("category") or [],
        "value": item_data.get("value") if item_data.get("value") is not None else mapping.get("value"),
        "image": str(item_data.get("image_filename") or mapping.get("image_filename") or ""),
        "level": level,
        "stack_size": item_data.get("stack_size") or mapping.get("stack_size"),
        "container": str(slot.get("container_id") or ""),
        # --- حقول الهوية والحالة: مطلوبة لإجراءات النقل/التقسيم (إضافة فقط، بلا تأثير على الأرقام) ---
        "instance_id": str(item_data.get("instanceId") or item_data.get("id") or ""),
        "wrapper_id": str(slot.get("wrapper_id") or item_data.get("wrapperId") or ""),
        "etag": str(item_data.get("etag") or ""),
        "slot_index": slot.get("slot_index"),
        "asset_id": asset_id,
        "durability": cur,
        "max_durability": mx,
        "show_durability": bool(item_data.get("show_durability")),
        "quality_level": ql,
        "is_blueprint": bool(blueprint),
        "is_firearm": bool(firearm),
        "damaged": bool(damaged),
        "total_count": item_data.get("total_count"),
        "attachments": item_data.get("attachments") or [],
        "max_attachments": item_data.get("max_attachments"),
        "craft_bench": mapping.get("craft_bench") or item_data.get("craft_bench"),
        "recipe": mapping.get("recipe") or item_data.get("recipe"),
        "recycle_info": mapping.get("recycle_info") or item_data.get("recycle_info"),
        "repair_cost": mapping.get("repair_cost") or item_data.get("repair_cost"),
    }


def flatten_payload(payload, keep_damaged=False):
    """{name: qty} + تفاصيل العرض + التكرارات لحساب واحد."""
    mappings = (payload or {}).get("item_mappings") or {}
    totals, details, seen = {}, {}, set()
    for container in ("stash", "overflow", "backpack"):
        for slot in (payload or {}).get(container) or []:
            parsed = parse_slot(slot, mappings, keep_damaged=keep_damaged)
            if not parsed or parsed["uid"] in seen:
                continue
            seen.add(parsed["uid"])
            totals[parsed["name"]] = totals.get(parsed["name"], 0) + parsed["qty"]
            details.setdefault(parsed["name"], []).append(parsed)
    return totals, details


def equipped_instances(payload):
    """المعدات المُرتدية (سلاح/درع/إسمنت/جيوب) من dict الـ containers — للوحة الإدارة فقط."""
    mappings = (payload or {}).get("item_mappings") or {}
    out = {}
    for key, slots in ((payload or {}).get("containers") or {}).items():
        if key in ("stash", "backpack") or not isinstance(slots, list):
            continue
        for slot in slots:
            parsed = parse_slot(slot, mappings, keep_damaged=True)
            if parsed:
                parsed["container"] = key
                out.setdefault(parsed["name"], []).append(parsed)
    return out
