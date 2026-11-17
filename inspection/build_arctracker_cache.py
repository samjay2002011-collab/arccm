"""يبني كاش محلي كامل لعناصر اللعبة من arctracker.io (تشغيل يدوي مرة واحدة).

بيحمّل ملفات JSON المولّدة على الموقع + كل الأيقونات، ويكتب:
  data/arctracker_items_cache.json
  assets/items/arctracker/<slug>.png

بعد كده السيرفر والواجهة بيقروا الملفات المحلية فقط، بدون أي طلب خارجي.
التشغيل: python inspection/build_arctracker_cache.py
"""
import concurrent.futures
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(ROOT, "data", "arctracker_items_cache.json")
ICON_DIR = os.path.join(ROOT, "assets", "items", "arctracker")
BASE = "https://arctracker.io/generated/client/items"
HEADERS = {"User-Agent": "FahmyLocalMirror/1.0 (offline item cache)"}
TIMEOUT = 45
WORKERS = 12

WEAPON_TYPES = {"assault rifle", "battle rifle", "hand cannon", "lmg", "pistol", "shotgun",
                "smg", "sniper rifle", "special"}
MATERIAL_TYPES = {"recyclable", "basic material", "topside material", "refined material", "nature"}
GROUP_BY_TYPE = {
    "blueprint": "Blueprints",
    "design": "Designs",
    "stencil": "Stencils",
    "augment": "Augments",
    "shield": "Shields",
    "modification": "Weapon Mods",
    "quick use": "Quick Use",
    "ammunition": "Ammunition",
    "key": "Keys",
    "trinket": "Trinkets",
    "research": "Research",
    "outpost furniture": "Furniture",
    "outpost room": "Furniture",
}


def group_for(item_type):
    kind = str(item_type or "").strip().lower()
    if kind in WEAPON_TYPES:
        return "Weapons"
    if kind in MATERIAL_TYPES:
        return "Crafting Materials"
    return GROUP_BY_TYPE.get(kind, "Misc")


def fetch_json(name, attempts=3):
    url = "%s/%s" % (BASE, name)
    last = None
    for attempt in range(attempts):
        try:
            res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            res.raise_for_status()
            return res.json()
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("failed to fetch %s: %s" % (url, last))


def english_effects(effects):
    out = {}
    for key, value in (effects or {}).items():
        if not isinstance(value, dict):
            continue
        label = value.get("en") or key
        out[label] = value.get("value")
    return out


def durability_max_of(detail):
    top = detail.get("durability")
    if isinstance(top, (int, float)) and top > 0:
        return int(round(top))
    effect = (detail.get("effects") or {}).get("Durability") or {}
    value = effect.get("value")
    if isinstance(value, str):
        match = re.match(r"^\s*([\d.]+)\s*/\s*([\d.]+)\s*$", value)
        if match:
            return int(round(float(match.group(2))))
        if value.strip().replace(".", "", 1).isdigit():
            return int(round(float(value)))
    if isinstance(value, (int, float)) and value > 0:
        return int(round(value))
    return None


def icon_target(url):
    base = os.path.basename(urlparse(url).path)
    if not base or "." not in base:
        return None
    return os.path.join(ICON_DIR, base)


def valid_png(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def download_icon(url):
    target = icon_target(url)
    if not target:
        return url, None, "bad url"
    if valid_png(target):
        return url, target, None
    last = None
    for attempt in range(4):
        try:
            res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            res.raise_for_status()
            if res.content[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError("not a png")
            tmp = target + ".part"
            with open(tmp, "wb") as fh:
                fh.write(res.content)
            os.replace(tmp, target)
            return url, target, None
        except Exception as exc:
            last = exc
            time.sleep(1.2 * (attempt + 1))
    return url, None, str(last)


def build():
    print("fetching arctracker manifests...")
    manifest = fetch_json("manifest.json")
    index = fetch_json("items-index.en.json")
    detail = fetch_json("items-detail.en.json")
    values = fetch_json("item-values.json").get("values") or {}
    tracker = fetch_json("tracker-data.en.json").get("items") or {}

    details = detail.get("items") or {}
    index_rows = index.get("items") or []
    if isinstance(index_rows, dict):
        index_rows = index_rows.values()
    for row in index_rows:
        if isinstance(row, dict) and row.get("id") and row["id"] not in details:
            details[row["id"]] = row
    items = {}
    for item_id, row in details.items():
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        effects = english_effects(row.get("effects"))
        dur_max = durability_max_of(row)
        value = row.get("value")
        if value is None:
            value = values.get(item_id)
        image_url = row.get("imageFilename") or ""
        local = None
        if image_url:
            target = icon_target(image_url)
            if target:
                local = "arctracker/" + os.path.basename(target)
        item_type = str(row.get("type") or "Misc").strip()
        items[item_id] = {
            "id": item_id,
            "name": name,
            "name_search": row.get("nameSearch") or name.lower(),
            "type": item_type,
            "group": group_for(item_type),
            "rarity": row.get("rarity") or "",
            "value": value,
            "weight_kg": row.get("weightKg"),
            "stack_size": row.get("stackSize"),
            "has_durability": dur_max is not None,
            "durability_max": dur_max,
            "description": row.get("description") or "",
            "effects": effects,
            "is_blueprint": bool(row.get("isBlueprint")),
            "related_blueprint_id": row.get("relatedBlueprintId"),
            "target_item_id": row.get("targetItemId"),
            "quest_item": bool(row.get("questItem")),
            "research_perk": bool(row.get("researchPerk")),
            "phased_out": bool(row.get("phasedOut")),
            "image_source": image_url,
            "image_local": local,
            "updated_at": row.get("updatedAt"),
            "tracker": tracker.get(item_id) or {},
        }

    os.makedirs(ICON_DIR, exist_ok=True)
    urls = sorted({v["image_source"] for v in items.values() if v.get("image_source")})
    print("items: %d | unique icons: %d" % (len(items), len(urls)))
    failed = {}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_icon, url): url for url in urls}
        for future in concurrent.futures.as_completed(futures):
            url, path, error = future.result()
            done += 1
            if error:
                failed[url] = error
            if done % 100 == 0 or done == len(urls):
                print("icons %d/%d (failed %d)" % (done, len(urls), len(failed)), flush=True)

    for item in items.values():
        local = item.get("image_local")
        item["icon_ok"] = bool(local and os.path.isfile(os.path.join(ROOT, "assets", "items", local)))

    cache = {
        "source": "https://arctracker.io/items",
        "offline": True,
        "version": str(detail.get("version") or manifest.get("version") or ""),
        "generated_at": detail.get("generatedAt") or manifest.get("generatedAt"),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "item_count": len(items),
        "icon_count": sum(1 for v in items.values() if v.get("icon_ok")),
        "unique_icon_count": len(urls),
        "failed_icons": failed,
        "items": items,
    }
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, CACHE_FILE)
    print("wrote %s (%d items, %d icons local, %d failed)"
          % (CACHE_FILE, len(items), cache["icon_count"], len(failed)))
    return cache


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise
