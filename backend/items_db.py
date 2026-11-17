"""قاعدة بيانات العناصر الكاملة (المصدر: arctracker.io الرسمي — ملفات JSON المولّدة هناك).

بتقرأ data/items_db.json (بينبني بـ inspection/build_items_db.py) وبتوفّر:
  row_for(asset_id|name)        صف العنصر بكل بياناته
  recycle_for / salvage_for     مقابل التدوير والتفكيك
  recipe_for                    وصفة الصناعة (الحاجة + محطة الصناعة +_level_ + المهارات)
  upgrade_costs_for             مواد الترقية من مستوى لمستوى (سعر كل طبقة من الموقع)

كل ده عرض فقط — وقت التنفيذ البوابة الرسمية هي اللي بتقرّر، ولو البيانات قديمة
البوابة بترفض (412) من غير أي خسارة.
"""
import json
import os
import re

from . import catalog, config

DB_FILE = os.path.join(config.DATA_DIR, "items_db.json")
ROMAN_TO_NUM = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
NUM_TO_ROMAN = {v: k for k, v in ROMAN_TO_NUM.items()}
TIERED = re.compile(r"^(.*?)\s+(I|II|III|IV|V)$")

_cache = {"key": None, "db": {}, "families": {}}


def _stamp():
    try:
        return os.path.getmtime(DB_FILE)
    except OSError:
        return -1.0


def _load():
    key = _stamp()
    if _cache["key"] == key:
        return _cache["db"]
    try:
        with open(DB_FILE, encoding="utf-8") as fh:
            db = json.load(fh)
    except (OSError, ValueError):
        db = {"meta": {"missing": True}, "items": {}, "by_name": {}, "by_asset": {}}
    families = {}
    for slug, row in (db.get("items") or {}).items():
        if not row.get("is_weapon"):
            continue
        match = TIERED.match(str(row.get("name") or "").strip())
        if not match:
            continue
        family = match.group(1).strip().lower()
        if family.startswith("amplified "):
            continue
        families.setdefault(family, {})[ROMAN_TO_NUM[match.group(2).upper()]] = slug
    _cache.update({"key": key, "db": db, "families": families})
    return db


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def meta():
    return _load().get("meta") or {}


def by_slug(slug):
    return (_load().get("items") or {}).get(str(slug or ""))


def find(asset_id=None, name=None):
    """صف العنصر: بالـ asset id الأول (أدق)، وبعدين بالاسم — ثم بالاسم من غير الطبقة."""
    db = _load()
    items = db.get("items") or {}
    slug = (db.get("by_asset") or {}).get(str(asset_id or ""))
    if slug:
        return items.get(slug)
    key = norm(name)
    if not key:
        return None
    slug = (db.get("by_name") or {}).get(key)
    if slug:
        return items.get(slug)
    match = TIERED.match(str(name or "").strip())
    if match:
        family = match.group(1).strip().lower()
        level = ROMAN_TO_NUM.get(match.group(2).upper())
        slug = (_cache["families"].get(family) or {}).get(level)
        if slug:
            return items.get(slug)
    return None


def _icon(row):
    """الأيقونة المحلية اللي نزّلها البناء (assets/items/arctracker/<slug>.png)."""
    return (row or {}).get("image_local") if (row or {}).get("icon_ok") else ""


def icon_for(row):
    """الأيقونة المحلية لصف عنصر (فاضي لو العنصر ملوش أيقونة متخزنة)."""
    return _icon(row)


def _material_rows(row, key):
    out = []
    for mat in (row or {}).get(key) or []:
        asset_ids = [str(a) for a in (mat.get("asset_ids") or [])]
        name = mat.get("name") or mat.get("slug")
        image = _icon(by_slug(mat.get("slug"))) or catalog.icon_of(catalog.arctracker_lookup(name))
        out.append({"asset_id": asset_ids[0] if asset_ids else "", "asset_ids": asset_ids,
                    "slug": mat.get("slug"), "name": name, "qty": int(mat.get("qty") or 0),
                    "image_filename": image})
    out.sort(key=lambda m: m["name"].lower())
    return out


def recycle_for(asset_id=None, name=None):
    row = find(asset_id, name)
    if not row:
        return []
    return _material_rows(row, "recycles_into")


def salvage_for(asset_id=None, name=None):
    row = find(asset_id, name)
    if not row:
        return []
    return _material_rows(row, "salvages_into")


def _recipe_from_row(row):
    return {"slug": row.get("slug"), "name": row.get("name"),
            "rarity": row.get("rarity"), "image_filename": _icon(row),
            "materials": _material_rows(row, "recipe"),
            "stations": row.get("craft_bench") or [],
            "station_level": row.get("station_level"),
            "craft_skills": row.get("craft_skills") or {},
            "blueprint": row.get("related_blueprint_id"),
            "blueprint_locked": bool(row.get("blueprint_locked")),
            "quantity": int(row.get("craft_quantity") or 1),
            "type": row.get("type"), "group": row.get("group"),
            "asset_ids": [str(a) for a in row.get("asset_ids") or []],
            "value": row.get("value")}


def recipe_for(asset_id=None, name=None):
    row = find(asset_id, name)
    return _recipe_from_row(row) if row else None


def recipe_by_slug(slug):
    """الوصفة الكاملة بـ slug — تشمل الأيقونات المحلولة لكل خامة."""
    row = by_slug(slug)
    return _recipe_from_row(row) if row else None


def craftable_rows():
    """كل وصفات الصناعة في القاعدة — نفس شكل recipe_for، للورك شوب."""
    return [_recipe_from_row(row) for row in (_load().get("items") or {}).values() if row.get("recipe")]


def blueprint_rows():
    """الـ 91 مخطوطة في اللعبة: slugها + العنصر اللي بتفتحه + أرقام أصولها."""
    items = _load().get("items") or {}
    out = []
    for slug, row in items.items():
        if row.get("type") != "Blueprint":
            continue
        target = str(row.get("target_item_id") or "")
        tgt = items.get(target) or {}
        out.append({"slug": slug, "name": row.get("name"), "image": _icon(row),
                    "asset_ids": [str(a) for a in row.get("asset_ids") or []],
                    "target": target, "target_name": tgt.get("name"),
                    "target_image": _icon(tgt), "target_rarity": tgt.get("rarity"),
                    "stations": tgt.get("craft_bench") or [], "station_level": tgt.get("station_level")})
    out.sort(key=lambda r: (str(r.get("target_name") or "").lower(), r["slug"]))
    return out


def families():
    _load()
    return _cache["families"]


def upgrade_costs_for(name, current, target):
    """{asset_id: qty} لمواد الترقية من current لـ target — كل طبقة وسعرها من الموقع.

    الموقع بيخزّن سعر الطبقة على الطبقة نفسها (سعر ferro_ii = اللي بياد عشان توصل II).
    بيرجع {} لو السلاح مش معروف أو الطبقة مش في القاعدة."""
    match = TIERED.match(str(name or "").strip())
    family = (match.group(1) if match else str(name or "")).strip().lower()
    levels = families().get(family) or {}
    if not levels:
        return {}
    costs = {}
    for level in range(int(current) + 1, int(target) + 1):
        row = by_slug(levels.get(level))
        for mat in (row or {}).get("upgrade_cost") or []:
            asset_ids = [str(a) for a in (mat.get("asset_ids") or [])]
            if not asset_ids:
                return {}
            costs[asset_ids[0]] = costs.get(asset_ids[0], 0) + int(mat.get("qty") or 0)
    return costs


def upgrade_rows_for(name, current, target):
    """نفس الحساب بس بالصور والأسماء، لكل طبقة على حدة (عشان المعاينة)."""
    match = TIERED.match(str(name or "").strip())
    family = (match.group(1) if match else str(name or "")).strip().lower()
    levels = families().get(family) or {}
    out = []
    for level in range(int(current) + 1, int(target) + 1):
        slug = levels.get(level)
        row = by_slug(slug) or {}
        out.append({"level": level, "slug": slug, "name": row.get("name"),
                    "image_filename": _icon(row),
                    "materials": _material_rows(row, "upgrade_cost")})
    return out


def dossier(asset_id=None, name=None):
    """كل المعروف عن عنصر واحد من arctracker — للوحة التفاصيل وللبحث عن غير مملوك."""
    row = find(asset_id, name)
    if not row:
        return None
    next_row = by_slug(row.get("upgrades_to"))
    return {"source": "arctracker", "site_version": meta().get("site_version"),
            "slug": row.get("slug"), "name": row.get("name"), "type": row.get("type"),
            "group": row.get("group"), "rarity": row.get("rarity"), "value": row.get("value"),
            "stack_size": row.get("stack_size"), "weight_kg": row.get("weight_kg"),
            "description": row.get("description"), "effects": row.get("effects") or {},
            "found_in": row.get("found_in") or [],
            "image_filename": _icon(row),
            "is_weapon": row.get("is_weapon"), "is_blueprint": row.get("is_blueprint"),
            "quest_item": row.get("quest_item"), "phased_out": row.get("phased_out"),
            "recycles_into": _material_rows(row, "recycles_into"),
            "salvages_into": _material_rows(row, "salvages_into"),
            "recipe": _material_rows(row, "recipe"),
            "craft_bench": row.get("craft_bench") or [],
            "station_level": row.get("station_level"),
            "craft_skills": row.get("craft_skills") or {},
            "blueprint": row.get("related_blueprint_id"),
            "upgrades_to": row.get("upgrades_to"),
            "upgrade_next": _material_rows(next_row, "upgrade_cost") if next_row else [],
            "upgrade_next_name": (next_row or {}).get("name"),
            "upgrade_cost": _material_rows(row, "upgrade_cost")}
