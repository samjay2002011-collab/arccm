"""يبني قاعدة بيانات كاملة لعناصر ARC Raiders من arctracker.io (مشروع مصدره الموقع الرسمي).

المصدر ملفات JSON الرسمية اللي بيولّدها arctracker.io (نفس البيانات اللي بتظهر على صفحة
كل عنصر: Recycling + Crafting recipe + Upgrade):
  items-detail.en.json    الاسم/الدرجة/القيمة/الوزن/الوصف/الأيقونة/foundIn
  items-crafting.en.json   وصفات الصناعة بالبلوبرنت (ingredients)
  items-blueprints.json    أي عنصر له بلوبرنت وأي بلوبرنت بيطلّع أي عنصر
  tracker-data.en.json     recyclesInto / salvagesInto / recipe / craftBench /
                           stationLevelRequired / craftSkills / upgradesTo / upgradeCost

والكتابة:
  data/items_db.json                         قاعدة البيانات (مفهرسة بالسلج وبالاسم وبـ asset id)
  assets/items/arctracker/<slug>.png         الأيقونات (زي build_arctracker_cache.py)

بعدها السيرفر والواجهة بيقروا الملفات المحلية فقط — أي طلب خارجي بيكون مرة واحدة هنا.
التشغيل: python inspection/build_items_db.py
"""
import csv
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "inspection"))

from build_arctracker_cache import (BASE, HEADERS, ICON_DIR, TIMEOUT, download_icon,  # noqa: E402
                                    english_effects, group_for, icon_target)

DB_FILE = os.path.join(ROOT, "data", "items_db.json")
ASSET_INDEX = [os.path.join(ROOT, "data", "catalog", "asset_index.csv"),
               os.path.join(ROOT, "data", "catalog", "asset_index_local.csv")]
FILES = {"detail": "items-detail.en.json", "crafting": "items-crafting.en.json",
         "blueprints": "items-blueprints.json", "tracker": "tracker-data.en.json",
         "manifest": "manifest.json"}

WEAPON_TIER = re.compile(r"\s+(I{1,3}|IV|V?I{0,3})$")


def fetch(name):
    res = requests.get("%s/%s" % (BASE, name), headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def norm(text):
    s = str(text or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def without_tier(text):
    return norm(WEAPON_TIER.sub("", text))


def asset_ids_by_name():
    """display_name -> [game_asset_id] من فهرس الأصول الرسمي (الشجرة بتاعتنا بالـ id)."""
    out = {}
    for path in ASSET_INDEX:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                name = norm(row.get("display_name"))
                aid = str(row.get("game_asset_id") or "").strip()
                if not name or not aid:
                    continue
                bucket = out.setdefault(name, [])
                if aid not in bucket:
                    bucket.append(aid)
    return out


def material_rows(raw, items_by_slug, ids_by_name):
    """{metal_parts: 4} -> [{slug, name, qty, asset_ids}] — الاسم من نفس القاعدة."""
    out = []
    for slug, qty in (raw or {}).items():
        row = items_by_slug.get(slug) or {}
        name = row.get("name") or slug.replace("_", " ").title()
        out.append({"slug": slug, "name": name, "qty": int(qty or 0),
                    "asset_ids": ids_by_name.get(norm(name), [])})
    out.sort(key=lambda m: m["name"].lower())
    return out


def icon_local(url):
    target = icon_target(url)
    return "arctracker/" + os.path.basename(target) if target else None


def build():
    print("fetching arctracker official JSON...")
    raw = {key: fetch(name) for key, name in FILES.items()}
    details = raw["detail"].get("items") or {}
    tracker = raw["tracker"].get("items") or {}
    crafting = raw["crafting"].get("blueprintRecipes") or {}
    blueprints = raw["blueprints"].get("blueprints") or {}

    ids_by_name = asset_ids_by_name()
    print("asset index names: %d" % len(ids_by_name))

    items = {}
    for slug, row in details.items():
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        tr = tracker.get(slug) or {}
        image_url = row.get("imageFilename") or ""
        item_type = str(row.get("type") or "Misc").strip()
        bench = tr.get("craftBench")
        if isinstance(bench, str):
            bench = [bench]
        items[slug] = {
            "slug": slug,
            "name": name,
            "name_lower": norm(name),
            "type": item_type,
            "group": group_for(item_type),
            "rarity": row.get("rarity") or "",
            "value": row.get("value") if row.get("value") is not None else tr.get("value"),
            "stack_size": row.get("stackSize"),
            "weight_kg": row.get("weightKg"),
            "description": row.get("description") or "",
            "effects": english_effects(row.get("effects")),
            "found_in": row.get("foundIn") or [],
            "is_weapon": bool(tr.get("isWeapon")) or group_for(item_type) == "Weapons",
            "is_blueprint": bool(row.get("isBlueprint")),
            "related_blueprint_id": row.get("relatedBlueprintId"),
            "target_item_id": row.get("targetItemId"),
            "quest_item": bool(row.get("questItem")),
            "research_perk": bool(row.get("researchPerk")),
            "phased_out": bool(row.get("phasedOut")),
            "blueprint_locked": bool(tr.get("blueprintLocked")),
            "station_level": tr.get("stationLevelRequired"),
            "craft_bench": bench or [],
            "craft_skills": tr.get("craftSkills") or {},
            "craft_quantity": tr.get("craftQuantity"),
            "upgrades_to": tr.get("upgradesTo"),
            "upgrade_stations": tr.get("upgradeStations") or [],
            "image_source": image_url,
            "image_local": icon_local(image_url),
            "asset_ids": ids_by_name.get(norm(name), []),
            "recycles_into": {}, "salvages_into": {}, "recipe": {}, "upgrade_cost": {},
            "_tr": tr,
        }

    for slug, row in items.items():
        row["recycles_into"] = material_rows(row["_tr"].get("recyclesInto") or {}, items, ids_by_name)
        row["salvages_into"] = material_rows(row["_tr"].get("salvagesInto") or {}, items, ids_by_name)
        row["recipe"] = material_rows(row["_tr"].get("recipe") or {}, items, ids_by_name)
        row["upgrade_cost"] = material_rows(row["_tr"].get("upgradeCost") or {}, items, ids_by_name)
        if not row["recipe"]:
            for bid, rec in crafting.items():
                if rec.get("targetItemId") == slug:
                    row["recipe"] = material_rows(
                        {i["itemId"]: i["quantity"] for i in rec.get("ingredients") or []},
                        items, ids_by_name)
                    if not row.get("related_blueprint_id"):
                        row["related_blueprint_id"] = bid
                    break
        del row["_tr"]

    by_name, by_asset = {}, {}
    for slug, row in items.items():
        by_name.setdefault(row["name_lower"], slug)
        by_name.setdefault(without_tier(row["name"]) if row["is_weapon"] else row["name_lower"], slug)
        for aid in row["asset_ids"]:
            by_asset.setdefault(str(aid), slug)

    # الأيقونات الناقصة
    os.makedirs(ICON_DIR, exist_ok=True)
    urls = sorted({r["image_source"] for r in items.values() if r.get("image_source")})
    failed = {}
    todo = [u for u in urls if not os.path.isfile(icon_target(u) or "")]
    print("items %d | icons %d (to download %d)" % (len(items), len(urls), len(todo)))
    for url in todo:
        _, path, error = download_icon(url)
        if error:
            failed[url] = error
    for row in items.values():
        local = row.get("image_local")
        row["icon_ok"] = bool(local and os.path.isfile(os.path.join(ROOT, "assets", "items", local)))

    counts = lambda key: sum(1 for r in items.values() if r.get(key))  # noqa: E731
    db = {
        "meta": {
            "source": "https://arctracker.io/items",
            "data_files": sorted(FILES.values()),
            "site_version": str(raw["detail"].get("version") or ""),
            "generated_at": raw["detail"].get("generatedAt"),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "item_count": len(items),
            "recycle_count": counts("recycles_into"),
            "salvage_count": counts("salvages_into"),
            "recipe_count": counts("recipe"),
            "upgrade_cost_count": counts("upgrade_cost"),
            "asset_id_count": len(by_asset),
            "icon_count": sum(1 for r in items.values() if r.get("icon_ok")),
            "failed_icons": failed,
            "note": "بيانات recycling/crafting/upgrade من arctracker.io الرسمي — البوابة "
                    "لسا بتفضل هي المرجع وقت التنفيذ.",
        },
        "items": items,
        "by_name": by_name,
        "by_asset": by_asset,
    }
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DB_FILE)
    print("wrote %s" % DB_FILE)
    print(json.dumps({k: v for k, v in db["meta"].items() if k != "failed_icons"},
                     ensure_ascii=False, indent=1))
    print("unmatched names (مش في فهرس الأصول): %d" %
          sum(1 for r in items.values() if not r["asset_ids"]))
    return db


if __name__ == "__main__":
    build()
