"""جدول الأسماء والتصنيف والخصائص لكل asset_id — data/catalog/asset_meta.csv.

بيتبني أوفلاين من ست مصادر رسمية (inspection/build_asset_meta.py): عروض البوابة،
بلوب اللعبة، arctracker، كتالوج الويكي، metaforge، وفهرس الأصول. الاسم اللي هنا
هو المرجع النهائي: البوابة بتبعت أسماء ناقصة الدرجة (Extended Barrel بدل
Extended Barrel III) وبتسمّي الديزاين/الستنسل "Blueprint"، فالجدول بيصحّح ده
مرة واحدة بدل ما كل مسار قراءة يعيد اشتقاقه غلط.
"""
import csv
import json
import os
import re
import threading

from . import config, items_db

FILE = os.path.join(config.DATA_DIR, "catalog", "asset_meta.csv")
GAME_DATA_FILE = os.path.join(config.DATA_DIR, "pioneer_game_data.json")
ROMAN_TAIL = re.compile(r"\s+(I|II|III|IV|V|VI)$", re.I)
_dyn_lock = threading.Lock()
_blob_cache = {"key": None, "entries": {}}


def _blob():
    """gameAssetId -> عنصر كامل من items-description.itemDescriptions (كاش بالميل تايم)."""
    try:
        key = os.path.getmtime(GAME_DATA_FILE)
    except OSError:
        return {}
    with _dyn_lock:
        if _blob_cache["key"] != key:
            try:
                with open(GAME_DATA_FILE, encoding="utf-8") as fh:
                    data = json.load(fh)
                rows = (data.get("items-description") or {}).get("itemDescriptions") or []
                if isinstance(rows, dict):
                    rows = list(rows.values())
                _blob_cache.update({"key": key,
                                    "entries": {str(r.get("gameAssetId")): r for r in rows}})
            except (OSError, ValueError):
                _blob_cache.update({"key": key, "entries": {}})
        return _blob_cache["entries"]


def _family(name):
    return ROMAN_TAIL.sub("", str(name or "")).strip()


def _resolve_amplified(asset_id, entry):
    """درجة Amplified: علم Item.Flag.Upgraded من بلوب اللعبة، والربط مع
    arctracker بمطابقة كمية amplified_fragments في الرسايكل (نفس دليل
    build_asset_meta). بترجع None لو المطابقة مش فريدة."""
    amt = (((entry or {}).get("recycle") or {}).get("rewardedItems") or [{}])[0].get("amount")
    if amt is None:
        return None
    db = items_db._load()
    by_asset = db.get("by_asset") or {}
    root = str(entry.get("baseGameAssetId") or "")
    root_row = (db.get("items") or {}).get(by_asset.get(root) or "") or {}
    fam = _family(root_row.get("name"))
    hits = []
    for row in (db.get("items") or {}).values():
        nm = str(row.get("name") or "")
        if not nm.lower().startswith("amplified"):
            continue
        if fam and fam.lower() not in nm.lower():
            continue
        for ri in row.get("recycles_into") or []:
            if ri.get("slug") == "amplified_fragments" and int(ri.get("qty", -1)) == int(amt):
                hits.append(row)
    if len(hits) != 1:
        return None
    r = hits[0]
    return {
        "name": r.get("name") or "", "slug": r.get("slug") or "",
        "type": r.get("type") or "", "group": r.get("group") or "",
        "rarity": "Amplified", "value": r.get("value"),
        "stack_size": r.get("stack_size"), "weight_kg": r.get("weight_kg"),
        "description": r.get("description") or "", "image": r.get("image_local") or "",
        "is_blueprint": bool(r.get("is_blueprint")),
    }

_lock = threading.Lock()
_cache = {"mtime": None, "map": {}}


def _number(text, cast):
    try:
        return cast(str(text).strip())
    except (TypeError, ValueError):
        return None


def load():
    try:
        mtime = os.path.getmtime(FILE)
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] == mtime and _cache["map"]:
            return _cache["map"]
        out = {}
        with open(FILE, "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                asset_id = str(row.get("asset_id") or "").strip()
                name = str(row.get("name") or "").strip()
                if not asset_id or not name:
                    continue
                out[asset_id] = {
                    "name": name,
                    "slug": str(row.get("slug") or "").strip(),
                    "type": str(row.get("type") or "").strip(),
                    "group": str(row.get("group") or "").strip(),
                    "rarity": str(row.get("rarity") or "").strip(),
                    "value": _number(row.get("value"), int),
                    "stack_size": _number(row.get("stack_size"), int),
                    "weight_kg": _number(row.get("weight_kg"), float),
                    "description": str(row.get("description") or "").strip(),
                    "image": str(row.get("image") or "").strip(),
                    "is_blueprint": bool(_number(row.get("is_blueprint"), int)),
                }
        _cache.update({"mtime": mtime, "map": out})
        return out


def get(asset_id):
    key = str(asset_id if asset_id is not None else "").strip()
    rec = load().get(key)
    if not rec:
        # أوتوماتيك: أي asset_id مش في الجدول بيتحل من بلوب اللعبة مباشرة
        # (علم Item.Flag.Upgraded → درجة Amplified) من غير إضافة يدوية.
        entry = _blob().get(key)
        if entry and "Item.Flag.Upgraded" in list(entry.get("tags") or []):
            rec = _resolve_amplified(key, entry)
        elif entry:
            root = load().get(str(entry.get("baseGameAssetId") or "")) or {}
            quality = entry.get("qualityLevel")
            if root.get("group") == "Weapons" and quality in (0, 1, 2, 3):
                tier_name = _family(root["name"]) + " " + ("I", "II", "III", "IV")[int(quality)]
                item = items_db.find(name=tier_name) or {}
                if item:
                    rec = {"name": item["name"], "slug": item.get("slug") or "",
                           "type": item.get("type") or "", "group": "Weapons",
                           "rarity": item.get("rarity") or root.get("rarity"),
                           "value": item.get("value"), "stack_size": item.get("stack_size"),
                           "weight_kg": item.get("weight_kg"), "description": item.get("description") or "",
                           "image": item.get("image_local") or "", "is_blueprint": False}
    elif rec and "Item.Flag.Upgraded" in list(_blob().get(key, {}).get("tags") or []):
        rec = dict(rec, rarity="Amplified")
    return rec or {}


def name(asset_id):
    return get(asset_id).get("name") or ""