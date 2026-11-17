"""حسابات الترقية/الإصلاح/التفكيك/البيع/المرفقات — قراءة فقط من snapshot.

جداول الترقية والألوان مأخوذة حرفياً من حزمة rampart الأصلية، وتُستخدم لعرض
المواد المطلوبة والمتاح من المخزن قبل أي كتابة.
"""
import json
import os
import re

from . import catalog, config, items_db, repair_costs

ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
RARITY_SCORE = {"amplified": 600, "legendary": 500, "epic": 400, "rare": 300, "uncommon": 200, "common": 100}
SLOT_LABELS = {
    "muzzle": "Muzzle / Silencer", "grip": "Underbarrel / Grip", "stock": "Stock",
    "light_mag": "Light Magazine", "medium_mag": "Medium Magazine",
    "shotgun_mag": "Shotgun Magazine", "anvil_splitter": "Tech Mod (Splitter)",
    "shotgun_muzzle": "Shotgun Muzzle / Choke",
}
FIREARM_HINTS = ("weapon", "smg", "assault rifle", "battle rifle", "shotgun", "sniper rifle",
                 "hand cannon", "lmg", "pistol", "special", "rifle", "gun")


def _load(name, default):
    try:
        with open(os.path.join(config.DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


MATERIALS = _load("upgrade_materials.json", {})
UPGRADES = _load("weapon_upgrades.json", {})
FALLBACK = _load("upgrade_fallback.json", {})
_SLOTS = _load("attachment_slots.json", {"slots": []})
# جدول إعادة التدوير: {asset_id: {yield_asset_id: qty}} — عرض فقط، البوابة هي المرجع.
_RECYCLE_RAW = _load("recycle_yields.json", {})
RECYCLE_FIELDS = _RECYCLE_RAW.get("yields") or {}
RECYCLE_META = _RECYCLE_RAW.get("meta") or {}
# بذرة الجدول بأرقام الـ asset بتاعة مصدر تاني، فلو العنصر Live مالوش رقم مطابق
# بنطابقه بالاسم — الاسم ثابت بين النسخ.
RECYCLE_YIELDS = RECYCLE_FIELDS
RECYCLE_BY_NAME = {}
for _aid, _nm in (_RECYCLE_RAW.get("item_names") or {}).items():
    RECYCLE_BY_NAME.setdefault(str(_nm or "").strip().lower(), _aid)


def roman(n):
    return ROMAN.get(int(n or 0), str(n or ""))


def base_name(name):
    text = str(name or "").strip()
    if text.lower().startswith("amplified "):
        text = text[10:].strip()
    return re.sub(r"\s+(I|II|III|IV|V|1|2|3|4|5)$", "", text, flags=re.I).strip()


def _item_type(row):
    return str(row.get("type") or row.get("arctracker_type") or "").strip().lower()


def is_weapon(row):
    name = base_name(row.get("name") or row.get("display_name"))
    if name in UPGRADES:
        return True
    kind = _item_type(row)
    if any(h in kind for h in FIREARM_HINTS):
        return True
    if row.get("attachments"):
        try:
            atts = json.loads(row["attachments"]) if isinstance(row["attachments"], str) else row["attachments"]
            if atts:
                return True
        except (TypeError, ValueError):
            pass
    return False


def level_of(row):
    ql = row.get("quality_level")
    if isinstance(ql, int) and ql >= 0:
        return min(4, max(1, ql + 1))
    raw = row.get("level")
    if isinstance(raw, int) and raw > 0:
        return min(5, raw)
    text = str(raw or "").strip().upper()
    if text in ("I", "II", "III", "IV", "V"):
        return {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}[text]
    match = re.search(r"\s+(I|II|III|IV|V)$", str(row.get("name") or row.get("display_name") or "").strip(), re.I)
    if match:
        return {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}[match.group(1).upper()]
    return 1


def upgrade_table(row):
    base = base_name(row.get("name") or row.get("display_name"))
    table = UPGRADES.get(base)
    if table:
        return table
    for key, val in UPGRADES.items():
        if key.lower() == base.lower():
            return val
    return {"key": base.lower().replace(" ", "_"),
            "levels": FALLBACK.get(str(row.get("rarity") or "Uncommon").lower()) or FALLBACK.get("uncommon") or {}}


def upgrade_costs(row, current, target):
    """مواد الترقية من current لـ target: سعر كل طبقة من قاعدة بيانات arctracker
    (الموقع الرسمي)، ولو الطبقة مش موجودة بنرجع لجدول النادر المحلي."""
    if target <= current:
        return {}
    official = items_db.upgrade_costs_for(row.get("name") or row.get("display_name"), current, target)
    if official:
        return official
    table = upgrade_table(row)
    costs = {}
    for level in range(current + 1, target + 1):
        for asset_id, qty in ((table.get("levels") or {}).get(str(level), {}).get("cost") or {}).items():
            costs[str(asset_id)] = costs.get(str(asset_id), 0) + int(qty)
    return costs


def mapping_for(payload, row):
    return ((payload or {}).get("item_mappings") or {}).get(str(row.get("asset_id") or ""), {}) or {}


def catalog_rarity(name):
    """درجة الخامة من فهرس arctracker المحلي — المصدر الوحيد اللي بيعرفها للخامات
    اللي مجاش ذكر لندرتها في جدول الترقيات."""
    return str((catalog.arctracker_lookup(name) or {}).get("rarity") or "").lower()


def material_meta(asset_id, payload=None, row=None):
    meta = MATERIALS.get(str(asset_id)) or {}
    map_row = mapping_for(payload, row or {"asset_id": asset_id})
    db_row = items_db.find(asset_id=str(asset_id)) or {}
    name = (meta.get("name") or map_row.get("display_name") or map_row.get("name")
            or db_row.get("name") or ("Material %s" % asset_id))
    local = catalog.arctracker_lookup(name)
    image = (catalog.icon_of(local) or meta.get("image_filename")
             or items_db.icon_for(db_row) or map_row.get("image_filename"))
    return {"asset_id": str(asset_id), "name": name, "image_filename": image,
            "rarity": str(meta.get("rarity") or catalog_rarity(name) or db_row.get("rarity")
                          or map_row.get("rarity") or "common").lower()}


def container_rows(payload):
    rows = []
    for key in ("stash", "overflow", "backpack"):
        rows.extend((payload or {}).get(key) or [])
    for key, slots in ((payload or {}).get("containers") or {}).items():
        if isinstance(slots, list):
            rows.extend(slots)
    return rows


def counters(payload):
    counts, seen = {}, set()
    for slot in container_rows(payload):
        item = slot.get("item") if isinstance(slot, dict) else None
        if not item or slot.get("is_empty"):
            continue
        iid = item.get("instanceId") or item.get("id")
        if iid and iid in seen:
            continue
        if iid:
            seen.add(iid)
        asset_id = str(item.get("asset_id") if item.get("asset_id") is not None else item.get("gameAssetId") or "")
        if not asset_id:
            continue
        counts[asset_id] = counts.get(asset_id, 0) + int(item.get("amount") or 1)
    return counts


def material_list(costs, payload):
    counts = counters(payload)
    out = []
    for asset_id, needed in costs.items():
        meta = material_meta(asset_id, payload)
        available = counts.get(str(asset_id), 0)
        out.append(dict(meta, needed=int(needed), available=available, has_enough=available >= int(needed)))
    out.sort(key=lambda m: (not m["has_enough"], m["name"].lower()))
    return out


def upgrade_plan(rows, payload, targets):
    items, totals = [], {}
    for row in rows:
        current = level_of(row)
        target = int((targets or {}).get(row.get("instance_id")) or min(4, current + 1))
        target = min(4, max(2, target))
        costs = upgrade_costs(row, current, target) if current < 4 and target > current else {}
        for asset_id, qty in costs.items():
            totals[asset_id] = totals.get(asset_id, 0) + qty
        items.append({
            "instance_id": row.get("instance_id"), "name": row.get("name"),
            "rarity": row.get("rarity"), "image_filename": row.get("image"),
            "current": current, "current_label": roman(current),
            "target": target, "target_label": roman(target),
            "maxed": current >= 4, "steps": max(0, target - current),
            "costs": {k: v for k, v in costs.items()},
        })
    materials = material_list(totals, payload)
    possible = any(item["steps"] > 0 for item in items) and all(m["has_enough"] for m in materials)
    return {"items": items, "materials": materials, "can_upgrade": possible,
            "targets": targets or {}, "blocked": "max_level" if not any(i["steps"] > 0 for i in items) else
            (None if possible else "insufficient_materials")}


def health_of(row):
    weapon = is_weapon(row)
    max_health = 100 + (int(row.get("quality_level") or 0) * 10) if weapon else 100
    if not weapon and float(row.get("max_durability") or 1) > 1:
        max_health = int(float(row["max_durability"]))
    raw = row.get("durability")
    max_raw = float(row.get("max_durability") or 1)
    if raw is None:
        current = max_health
    elif float(raw) > 1 and max_raw <= 1:
        current = round(float(raw))
    else:
        current = round((float(raw) / max_raw) * max_health) if max_raw > 0 else 0
    current = max(0, min(max_health, current))
    gain = round(max_health * 0.5)
    new_current = min(max_health, current + gain)
    return {"current": current, "max": max_health, "gain": new_current - current,
            "new_current": new_current, "damaged": current < max_health}


def repair_plan(rows, payload):
    items, totals = [], {}
    for row in rows:
        health = health_of(row)
        if not health["damaged"]:
            continue
        cost = mapping_for(payload, row).get("repair_cost")
        if not isinstance(cost, dict) or not cost:
            continue
        for asset_id, qty in cost.items():
            totals[str(asset_id)] = totals.get(str(asset_id), 0) + int(qty)
        items.append({
            "instance_id": row.get("instance_id"), "name": row.get("name"),
            "rarity": row.get("rarity"), "image_filename": row.get("image"),
            "container": row.get("container"), **health,
        })
    materials = material_list(totals, payload)
    possible = bool(items) and all(m["has_enough"] for m in materials)
    return {"items": items, "materials": materials, "can_repair": possible,
            "blocked": None if possible else ("nothing_damaged" if not items else "insufficient_materials")}


def recycle_plan(rows, payload):
    items, totals = [], {}
    for row in rows:
        info = mapping_for(payload, row).get("recycle_info")
        if not isinstance(info, dict) or not info:
            continue
        for asset_id, qty in info.items():
            totals[str(asset_id)] = totals.get(str(asset_id), 0) + int(qty)
        items.append({
            "instance_id": row.get("instance_id"), "name": row.get("name"),
            "rarity": row.get("rarity"), "image_filename": row.get("image"),
            "qty": row.get("qty"), "recycle_info": info,
        })
    materials = []
    for asset_id, qty in totals.items():
        meta = material_meta(asset_id, payload)
        materials.append(dict(meta, amount=int(qty)))
    materials.sort(key=lambda m: m["name"].lower())
    return {"items": items, "materials": materials, "can_recycle": bool(items)}


def sell_plan(rows):
    items, total = [], 0
    for row in rows:
        qty = int(row.get("qty") or 1)
        value = int(row.get("value") or 0) * qty
        total += value
        items.append({"instance_id": row.get("instance_id"), "name": row.get("name"),
                      "rarity": row.get("rarity"), "image_filename": row.get("image"),
                      "qty": qty, "value": value})
    return {"items": items, "total": total, "count": len(items)}


def recycle_yield_rows(asset_id, payload=None, name=None):
    """مواد إعادة التدوير لعنصر واحد: [{asset_id, name, image_filename, qty, source}].

    الترتيب: قاعدة بيانات arctracker الرسمية (جواب كامل لكل العناصر، من غير تجربة)،
    ثم الجدول المحلي اللي تعلّم من البوابة، ثم recycle_info من الـ payload.
    لو ولا مصدر عرف العنصر رجعنا [] — يعني "مش معروف"، مش تخمين."""
    rows = items_db.recycle_for(asset_id, name)
    if rows:
        return [dict(row, source="arctracker",
                     rarity=str(row.get("rarity") or catalog_rarity(row.get("name")) or "common").lower())
                for row in rows]
    info = RECYCLE_YIELDS.get(str(asset_id or "")) or {}
    source = "gateway" if info else ""
    if not info:
        from_payload = (mapping_for(payload, {"asset_id": asset_id}) or {}).get("recycle_info")
        if isinstance(from_payload, dict):
            info, source = from_payload, "payload"
    if not info and name:
        seed_id = RECYCLE_BY_NAME.get(str(name).strip().lower())
        if seed_id:
            info, source = RECYCLE_FIELDS.get(str(seed_id)) or {}, "gateway"
    out = []
    for aid, qty in (info or {}).items():
        known = RECYCLE_META.get(str(aid)) or {}
        base = material_meta(aid, payload)
        mat_name = known.get("name") or base["name"]
        image = catalog.icon_of(catalog.arctracker_lookup(mat_name)) or known.get("image_filename") or base["image_filename"]
        out.append({"asset_id": str(aid), "name": mat_name, "image_filename": image,
                    "rarity": known.get("rarity") or base["rarity"],
                    "qty": int(qty or 0), "source": source})
    out.sort(key=lambda m: m["name"].lower())
    return out


def direct_plan(kind, rows, payload):
    """خطة الوضع المباشر (بوابة Embark الرسمية) — البوابة هي المرجع، مفيش gate على
    خرائط element من مصدر تاني.

    recycle/scrap بيقبلوا أي نسخة موجودة في الشجرة، فـ can_* بتعتمد على وجود
    العناصر نفسها. repair لوحده بيحتاج عنصر تالف فعلاً — إصلاح سليم بيرفضه المنبع."""
    items = []
    for row in rows:
        health = health_of(row)
        if kind == "repair" and not health["damaged"]:
            continue
        items.append({"instance_id": row.get("instance_id"), "name": row.get("name"),
                      "rarity": row.get("rarity"), "image_filename": row.get("image"),
                      "qty": int(row.get("qty") or 1), "container": row.get("container"),
                      "asset_id": str(row.get("asset_id") or ""),
                      "group": row.get("group") or "",
                      "value": int(row.get("value") or 0),
                      **({"health": health} if kind == "repair" else {})})
    total = sum(i["value"] * i["qty"] for i in items)
    out = {"items": items, "materials": [], "total": total, "direct": True,
           "can_recycle": kind == "recycle" and bool(items),
           "can_repair": kind == "repair" and bool(items),
           "can_sell": kind == "sell" and bool(items)}
    if kind == "repair" and not items:
        out["detail"] = "The selected items are in perfect condition — the gateway refuses to repair anything undamaged."
    if kind == "repair" and items:
        # القاموس المحلي (data/repair_costs.json): قياسات من إصلاحاته هو، والنموذج
        # بالفئة لسدّ القطع اللي لسه ما اتقاست. الأرقام للعرض — البوابة بتقرر خصمها.
        totals, estimated = {}, 0
        for item in items:
            obs = repair_costs.cost_for(item["asset_id"], item)
            cost = {mid: max(1, int(qty)) for mid, qty in obs["materials"].items()}
            item["cost"] = cost
            item["cost_estimated"] = obs["estimated"]
            for mid, need in cost.items():
                totals[mid] = totals.get(mid, 0) + need * item["qty"]
            if obs["estimated"]:
                estimated += 1
        materials = material_list(totals, payload) if totals else []
        out["materials"] = materials
        out["cost_estimated"] = estimated
        out["measured"] = len(items) - estimated
        if estimated:
            out["can_repair"] = False
            out["blocked"] = "repair_cost_unknown"
            out["detail"] = "Verified repair materials are unavailable. Repair is disabled rather than using guessed costs."
        if totals and estimated == 0 and not all(m["has_enough"] for m in materials):
            out["can_repair"] = False
            out["blocked"] = "insufficient_materials"
    if kind == "recycle":
        totals, unknown = {}, 0
        for item in items:
            yields = recycle_yield_rows(item["asset_id"], payload, item.get("name"))
            item["yields"] = yields
            item["yields_known"] = bool(yields)
            item["yields_source"] = yields[0]["source"] if yields else ""
            if not yields:
                unknown += 1
            for y in yields:
                key = y["asset_id"] or "name:" + y["name"].lower()
                entry = totals.setdefault(key, {"asset_id": y["asset_id"], "name": y["name"],
                                                "image_filename": y["image_filename"],
                                                "rarity": y.get("rarity") or "common", "qty": 0})
                entry["qty"] += y["qty"] * item["qty"]
        materials = sorted(totals.values(), key=lambda m: m["name"].lower())
        out["materials"] = materials
        out["unknown_yields"] = unknown
        sources = {i["yields_source"] for i in items if i.get("yields_source")}
        out["yields_source"] = "arctracker" if "arctracker" in sources else (sorted(sources)[0] if sources else "")
        if out["yields_source"] == "arctracker":
            out["yields_built_at"] = items_db.meta().get("built_at")
    return out


def slot_rules():
    rules = {}
    for rule in (_SLOTS.get("slots") or []):
        if rule.get("slot_asset_id") is not None:
            rules[str(rule["slot_asset_id"])] = {
                "name": rule.get("name") or "",
                "allowed_ids": [str(v) for v in (rule.get("allowed_ids") or [])],
            }
    return rules


def allowed_asset_ids(rules=None):
    rules = rules or slot_rules()
    out = set()
    for rule in rules.values():
        out.update(rule.get("allowed_ids") or [])
    return out


def parse_attachments(row):
    atts = row.get("attachments")
    if isinstance(atts, str):
        try:
            atts = json.loads(atts)
        except ValueError:
            atts = []
    return atts if isinstance(atts, list) else []


def slot_label(name):
    return SLOT_LABELS.get(str(name or ""), str(name or "Slot").replace("_", " ").title())


STENCIL_SLOT_ASSET_ID = "67839673"


def is_stencil(att):
    """الـ Stencil لون تجميلي مش قطعة مادية — البوابة بترفض فكّه مع باقي المرفقات.

    البوابة بتحطه في خانة mod_slot (نفس آيدي الأصل) وبتسمي نوعه Stencil،
    فالتفرقة بتحصل بالنوع أو بخانته نفسها.
    """
    if not isinstance(att, dict):
        return False
    if str(att.get("type") or "").strip().lower() == "stencil":
        return True
    name = str(att.get("display_name") or att.get("name") or "").strip().lower()
    return "stencil" in name and str(att.get("slot_asset_id") or "") == STENCIL_SLOT_ASSET_ID


def inventory_attachments(rows, rules=None):
    """عناصر المخزن التي يمكن تركيبها في أي خانة (فريدة لكل instance)."""
    allowed = allowed_asset_ids(rules)
    out, seen = [], set()
    for row in rows:
        asset_id = str(row.get("asset_id") or "")
        iid = row.get("instance_id")
        if not asset_id or asset_id not in allowed or not iid or iid in seen:
            continue
        if row.get("container") == "loadout":
            continue
        seen.add(iid)
        out.append({"instance_id": iid, "asset_id": asset_id, "name": row.get("name"),
                    "display_name": row.get("display_name") or row.get("name"),
                    "rarity": row.get("rarity"), "image_filename": row.get("image"),
                    "level": row.get("level"), "quality_level": row.get("quality_level"),
                    "wrapper_id": row.get("wrapper_id"), "container": row.get("container"),
                    "qty": row.get("qty")})
    out.sort(key=lambda i: (str(i.get("name") or "").lower(), -int(i.get("level") or 0)))
    return out


def level_score(item):
    level = item.get("level")
    if isinstance(level, int):
        return level * 10
    text = str(level or "").strip().upper()
    if text in ("I", "II", "III", "IV", "V"):
        return {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}[text] * 10
    return 0


def attachment_score(item):
    return (RARITY_SCORE.get(str(item.get("rarity") or "common").lower(), 100)
            + level_score(item))


def _weapon_slots(weapon):
    return [a for a in parse_attachments(weapon) if isinstance(a, dict) and not is_stencil(a)]


def plan_paste(weapons, setup, inventory, rules):
    slots = (setup or {}).get("slots") or []
    used, ops, matched, missing, already = set(), [], 0, 0, 0
    for weapon in weapons:
        for slot in _weapon_slots(weapon):
            target = None
            for candidate in slots:
                if (candidate.get("slot_name") and candidate.get("slot_name") == slot.get("slot_name")) or \
                   (candidate.get("slot_asset_id") and slot.get("slot_asset_id") and
                        str(candidate.get("slot_asset_id")) == str(slot.get("slot_asset_id"))):
                    target = candidate
                    break
            if not target:
                continue
            if not slot.get("is_empty") and str(slot.get("asset_id")) == str(target.get("asset_id")):
                already += 1
                continue
            rule = rules.get(str(slot.get("slot_asset_id"))) if slot.get("slot_asset_id") else None
            if rule and str(target.get("asset_id")) not in set(rule.get("allowed_ids") or []):
                continue
            item = next((i for i in inventory
                         if str(i.get("asset_id")) == str(target.get("asset_id"))
                         and i.get("instance_id") not in used), None)
            if item:
                used.add(item["instance_id"])
                ops.append({"weapon_id": weapon.get("instance_id"),
                            "slot_wrapper_id": slot.get("wrapperId") or slot.get("wrapper_id"),
                            "attachment_id": item["instance_id"],
                            "source_wrapper_id": item.get("wrapper_id")})
                matched += 1
            else:
                missing += 1
    return {"operations": ops, "matchedCount": matched, "missingCount": missing,
            "alreadyEquippedCount": already}


def plan_auto_fill(weapons, inventory, rules):
    empty = []
    for weapon in weapons:
        for slot in _weapon_slots(weapon):
            if slot.get("is_empty") and (slot.get("wrapperId") or slot.get("wrapper_id")) and slot.get("slot_asset_id"):
                empty.append({"weapon": weapon, "slot": slot,
                              "score": attachment_score(weapon)})
    empty.sort(key=lambda e: -e["score"])
    pool = list(inventory)
    used, ops = set(), []
    for entry in empty:
        rule = rules.get(str(entry["slot"].get("slot_asset_id")))
        if not rule:
            continue
        allowed = set(rule.get("allowed_ids") or [])
        candidates = [i for i in pool if str(i.get("asset_id")) in allowed and i.get("instance_id") not in used]
        if not candidates:
            continue
        best = max(candidates, key=attachment_score)
        used.add(best["instance_id"])
        ops.append({"weapon_id": entry["weapon"].get("instance_id"),
                    "slot_wrapper_id": entry["slot"].get("wrapperId") or entry["slot"].get("wrapper_id"),
                    "attachment_id": best["instance_id"],
                    "source_wrapper_id": best.get("wrapper_id")})
    return {"operations": ops, "filled": len(ops)}


def manager_slots(weapons, inventory, rules):
    """تجميع خانات الأسلحة حسب نوع الخانة مع المتاح في المخزن.

    القائمة المتاحة = كارت لكل نوع (qty = مجموع النسخ)، مش كارت لكل نسخة: النسخ
    المتماثلة مابتفرقش في الاختيار، والفرق بيحصل بين الأنواع. النسخة اللي بتمثل
    النوع هي أحسن نسخة (attachment_score) عشان التركيب يفضل زي AUTO-FILL بالظبط.
    """
    groups = {}
    for weapon in weapons:
        for slot in _weapon_slots(weapon):
            name = slot.get("slot_name") or "slot"
            group = groups.setdefault(name, {"slot_name": name, "label": slot_label(name),
                                              "slot_asset_id": slot.get("slot_asset_id"),
                                              "empty": 0, "filled": 0, "weapons": []})
            if slot.get("is_empty"):
                group["empty"] += 1
            else:
                group["filled"] += 1
            group["weapons"].append({"instance_id": weapon.get("instance_id"),
                                     "name": weapon.get("name"),
                                     "wrapper_id": slot.get("wrapperId") or slot.get("wrapper_id"),
                                     "is_empty": bool(slot.get("is_empty")),
                                     "asset_id": str(slot.get("asset_id") or ""),
                                     "attachment_name": slot.get("name") or slot.get("display_name")})
    for group in groups.values():
        rule = rules.get(str(group.get("slot_asset_id")))
        allowed = set((rule or {}).get("allowed_ids") or [])
        by_type = {}
        for item in inventory:
            asset_id = str(item.get("asset_id") or "")
            if not asset_id or asset_id not in allowed:
                continue
            entry = by_type.get(asset_id)
            if entry is None:
                entry = dict(item, asset_id=asset_id, qty=0)
                by_type[asset_id] = entry
            entry["qty"] += int(item.get("qty") or 1)
            if attachment_score(item) > attachment_score(entry):
                for key in ("instance_id", "level", "rarity", "quality_level",
                            "wrapper_id", "container", "image_filename", "name", "display_name"):
                    entry[key] = item.get(key)
        installed = {str(w.get("asset_id") or "") for w in group["weapons"] if not w.get("is_empty")}
        for entry in by_type.values():
            entry["installed"] = entry["asset_id"] in installed
        group["available"] = sorted(by_type.values(), key=lambda e: str(e.get("name") or "").lower())
    return list(groups.values())
