"""يبني data/items_catalog.json من كل مصادر اللعبة:

1) جدول items في Cargo على arcraiders.wiki (565 عنصرًا بأنواعها ودقتها وصورها).
2) صفحات الأسلحة (Category:Weapons) لأن الأسلحة مش موجودة في جدول items.
3) صفحات/تصنيف Quick Use كاملةً.
4) آخر snapshot لكل حساب من Rampart (asset_id / value / الصورة المحلية).

قراءة فقط بالكامل: مفيش أي طلب لـ rampart. التشغيل: python inspection/build_items_catalog.py
"""
import glob
import gzip
import json
import os
import re
import sys
import time
from urllib.parse import quote

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import catalog  # noqa: E402

API = "https://arcraiders.wiki/w/api.php"
HEADERS = {"User-Agent": "FahmyLocalMirror/1.0 (read-only item catalog)"}
SNAPSHOT_GLOB = os.path.join(ROOT, "data", "snapshots", "*.json.gz")
OUT_FILE = os.path.join(ROOT, "data", "items_catalog.json")
CARGO_FIELDS = "_pageName=page,name,image,rarity,description,type,weight,stacksize,sellprice"
RARITIES = ("Common", "Uncommon", "Rare", "Epic", "Legendary", "Amplified")
ROMAN = re.compile(r"\s+(I|II|III|IV|V)$", re.I)
INFOBOX = re.compile(r"\{\{\s*Infobox[^\n]*\n(.*?)\n\}\}", re.S)
GENERIC_TYPES = {"", "item"}


# ------------------------------------------------------------------ snapshots
def latest_snapshots():
    out = {}
    for path in sorted(glob.glob(SNAPSHOT_GLOB), key=os.path.getmtime):
        match = re.match(r"^(.+)_\d{8}-\d{6}\.json\.gz$", os.path.basename(path))
        if match:
            out[match.group(1)] = path
    return out


def strip_blueprint(name):
    return name[:-len(" Blueprint")].strip() if name.lower().endswith(" blueprint") else name.strip()


def base_display(name, item_type, is_blueprint):
    base = strip_blueprint(name)
    if str(item_type or "").strip().lower() in catalog.WEAPON_TYPES:
        base = ROMAN.sub("", base).strip()
    return base


def add_variant(store, item, asset_id=""):
    name = str(item.get("display_name") or item.get("name") or "").strip()
    if not name:
        return
    item_type = str(item.get("type") or "Item").strip()
    is_bp = item_type.lower() == "blueprint" or name.lower().endswith(" blueprint")
    base = base_display(name, item_type, is_bp)
    dedup = (catalog.normalize(base), item_type.lower(), is_bp)
    variant = {
        "name": name,
        "type": item_type,
        "is_blueprint": is_bp,
        "raw_categories": list(item.get("category") or []),
        "rarity": str(item.get("rarity") or ""),
        "value": item.get("value"),
        "image": str(item.get("image_filename") or item.get("image") or ""),
        "stack_size": item.get("stack_size"),
        "max_attachments": item.get("max_attachments") or 0,
        "quality_level": item.get("quality_level"),
        "level": item.get("level"),
        "asset_id": str(asset_id or item.get("asset_id") or item.get("gameAssetId") or ""),
        "source": "rampart",
    }
    old = store.get(dedup)
    if old is None:
        store[dedup] = variant
        return
    old_value = old.get("value") if isinstance(old.get("value"), (int, float)) else -1
    new_value = variant.get("value") if isinstance(variant.get("value"), (int, float)) else -1
    if new_value > old_value:
        keep = {k: old.get(k) for k in ("wiki_title", "wiki_type", "wiki_categories", "group", "quick_use")}
        store[dedup] = variant
        for key, value in keep.items():
            if value not in (None, "", []):
                variant[key] = value
    if not old.get("max_attachments") and variant.get("max_attachments"):
        old["max_attachments"] = variant["max_attachments"]


def collect_variants():
    store = {}
    snapshots = latest_snapshots()
    for account, path in snapshots.items():
        with gzip.open(path, "rb") as f:
            payload = json.loads(f.read().decode("utf-8"))
        for asset_id, mapping in (payload.get("item_mappings") or {}).items():
            add_variant(store, mapping, asset_id)
        slots = []
        for container in ("stash", "overflow", "backpack"):
            slots += payload.get(container) or []
        for group in (payload.get("containers") or {}).values():
            if isinstance(group, list):
                slots += group
        for slot in slots:
            item = slot.get("item") or {}
            if not isinstance(item, dict) or not item or item.get("is_empty"):
                continue
            add_variant(store, item, item.get("asset_id") or item.get("gameAssetId"))
    return store, snapshots


# ------------------------------------------------------------------ wiki
def _get(session, params, tries=3):
    last = None
    for attempt in range(tries):
        try:
            res = session.get(API, params=params, headers=HEADERS, timeout=60)
            res.raise_for_status()
            return res.json()
        except Exception as exc:  # الويكي بيرجع 5xx أحيانًا؛ نعيد المحاولة
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("wiki request failed: %s" % last)


def fetch_cargo_items(session):
    rows, offset = [], 0
    while True:
        data = _get(session, {
            "action": "cargoquery", "tables": "items", "fields": CARGO_FIELDS,
            "limit": "500", "offset": str(offset), "format": "json", "formatversion": "2",
        })
        batch = [row["title"] for row in (data.get("cargoquery") or [])]
        rows += batch
        if len(batch) < 500:
            break
        offset += 500
    out = {}
    for row in rows:
        page = str(row.get("page") or row.get("name") or "").strip()
        if page:
            out.setdefault(page, row)
    return list(out.values())


def fetch_category_members(session, category):
    out, cont = [], {}
    while True:
        params = {"action": "query", "list": "categorymembers", "cmtitle": "Category:" + category,
                  "cmnamespace": "0", "cmlimit": "max", "format": "json", "formatversion": "2"}
        params.update(cont)
        data = _get(session, params)
        out += [m["title"] for m in ((data.get("query") or {}).get("categorymembers") or [])]
        cont = data.get("continue") or {}
        if not cont:
            break
    return out


def fetch_page_details(session, titles):
    out = {}
    titles = sorted({t for t in titles if t})
    for start in range(0, len(titles), 25):
        batch = titles[start:start + 25]
        data = _get(session, {
            "action": "query", "prop": "revisions", "rvslots": "main", "rvprop": "content",
            "titles": "|".join(batch), "redirects": "1", "format": "json", "formatversion": "2",
        })
        query = data.get("query") or {}
        alias = {}
        for row in query.get("normalized") or []:
            alias[row["from"]] = row["to"]
        for row in query.get("redirects") or []:
            alias[row["from"]] = row["to"]
        pages = {p.get("title"): p for p in query.get("pages") or []}
        for title in batch:
            resolved, seen = title, set()
            while resolved in alias and resolved not in seen:
                seen.add(resolved)
                resolved = alias[resolved]
            page = pages.get(resolved) or pages.get(title) or {}
            if page.get("missing"):
                continue
            revisions = page.get("revisions") or []
            content = ""
            if revisions:
                content = ((revisions[0].get("slots") or {}).get("main") or {}).get("content") or ""
            out[title] = {"page": page.get("title") or resolved, "content": content}
        time.sleep(0.15)
    return out


def fetch_wiki_categories(session, titles):
    """يرجع {title: [categories] أو None لو الصفحة مش موجودة}."""
    out = {}
    title_list = sorted({t for t in titles if t})
    for start in range(0, len(title_list), 50):
        batch = title_list[start:start + 50]
        data = _get(session, {
            "action": "query", "prop": "categories", "titles": "|".join(batch),
            "cllimit": "max", "redirects": "1", "format": "json", "formatversion": "2",
        })
        query = data.get("query") or {}
        alias = {}
        for row in query.get("normalized") or []:
            alias[row["from"]] = row["to"]
        for row in query.get("redirects") or []:
            alias[row["from"]] = row["to"]
        pages = {p.get("title"): p for p in query.get("pages") or []}
        for title in batch:
            resolved, seen = title, set()
            while resolved in alias and resolved not in seen:
                seen.add(resolved)
                resolved = alias[resolved]
            page = pages.get(resolved) or pages.get(title)
            if not page or page.get("missing"):
                out[title] = None
            else:
                out[title] = catalog.clean_wiki([c.get("title") for c in page.get("categories") or []])
        time.sleep(0.15)
    return out


def clean_value(value):
    text = str(value or "").strip()
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"\[\[([^|\]]*\|)?([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_infobox(content):
    match = INFOBOX.search(content or "")
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip().lower()] = clean_value(value)
    return fields


def first_number(value):
    match = re.search(r"\d[\d,]*", str(value or ""))
    return int(match.group(0).replace(",", "")) if match else None


def first_float(value):
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def wiki_image_url(image):
    name = str(image or "").strip()
    if not name:
        return ""
    if name.lower().startswith("file:"):
        name = name.split(":", 1)[1]
    return "https://arcraiders.wiki/wiki/Special:FilePath/" + quote(name.replace(" ", "_"))


def wiki_group(row):
    item_type = str(row.get("type") or "").strip()
    low = item_type.lower()
    name = str(row.get("name") or "").lower()
    if row.get("is_blueprint") or low == "blueprint" or name.endswith(" blueprint"):
        return "Blueprints"
    if row.get("weapon") or low in catalog.WEAPON_TYPES:
        return "Weapons"
    if low == "augment":
        return "Augments"
    if low == "shield":
        return "Shields"
    if low in ("mods", "mod", "modification", "weapon mod"):
        return "Weapon Mods"
    if low in ("quick use", "quickuse"):
        return "Quick Use"
    if low == "ammunition":
        return "Ammunition"
    if low == "key":
        return "Keys"
    if low in ("recyclable", "topside material", "refined material", "basic material", "material", "nature"):
        return "Crafting Materials"
    if low in ("trinket", "quest item", "research item", "misc"):
        return "Misc"
    return catalog.classify(name=row.get("name"), item_type=item_type,
                            raw_categories=[], wiki_categories=row.get("wiki_categories") or [])


def collect_wiki_rows(session):
    rows = {}

    def add(row):
        page = row.get("page") or row.get("name")
        if not page:
            return
        row["page"] = page
        row.setdefault("name", page)
        row.setdefault("type", "")
        row.setdefault("is_blueprint", False)
        row.setdefault("weapon", False)
        row["group"] = wiki_group(row)
        row["quick_use"] = row["group"] == "Quick Use"
        rows.setdefault(page, row)

    for raw in fetch_cargo_items(session):
        name = str(raw.get("name") or raw.get("page") or "").strip()
        item_type = str(raw.get("type") or "").strip() or "Item"
        add({
            "page": str(raw.get("page") or name).strip(),
            "name": name,
            "type": item_type,
            "is_blueprint": item_type.lower() == "blueprint" or name.lower().endswith(" blueprint"),
            "rarity": str(raw.get("rarity") or "").strip(),
            "description": clean_value(raw.get("description")),
            "image": str(raw.get("image") or "").strip(),
            "weight": first_float(raw.get("weight")),
            "stack_size": first_number(raw.get("stacksize")),
            "sellprice": first_number(raw.get("sellprice")),
        })

    weapons = fetch_category_members(session, "Weapons")
    details = fetch_page_details(session, weapons)
    for title in weapons:
        info = parse_infobox((details.get(title) or {}).get("content") or "")
        weapon_type = info.get("type") or "Weapon"
        add({
            "page": (details.get(title) or {}).get("page") or title,
            "name": title,
            "type": weapon_type,
            "is_blueprint": False,
            "weapon": True,
            "rarity": info.get("rarity") or "",
            "description": info.get("weaponquote") or info.get("quote") or "",
            "image": info.get("image") or "",
            "weight": first_float(info.get("weight")),
            "stack_size": 1,
            "sellprice": first_number(info.get("sellprice")),
            "infobox": info,
        })

    quick_members = fetch_category_members(session, "Quick Use")
    missing = [t for t in quick_members if t not in rows]
    q_details = fetch_page_details(session, missing)
    for title in missing:
        info = parse_infobox((q_details.get(title) or {}).get("content") or "")
        add({
            "page": (q_details.get(title) or {}).get("page") or title,
            "name": title,
            "type": info.get("type") or "Quick Use",
            "is_blueprint": False,
            "rarity": info.get("rarity") or "",
            "description": info.get("quote") or "",
            "image": info.get("image") or "",
            "weight": first_float(info.get("weight")),
            "stack_size": first_number(info.get("stacksize")),
            "sellprice": first_number(info.get("sellprice")),
            "quick_use": True,
        })
    for title in quick_members:
        if title in rows:
            rows[title]["quick_use"] = True
            if not rows[title].get("is_blueprint"):
                rows[title]["group"] = "Quick Use"

    # categories for every page + rarity fallback
    categories = fetch_wiki_categories(session, [r["page"] for r in rows.values()])
    for row in rows.values():
        cats = categories.get(row["page"]) or []
        row["wiki_categories"] = cats
        if not row.get("rarity"):
            for rarity in RARITIES:
                if rarity in cats:
                    row["rarity"] = rarity
                    break
        if row.get("quick_use") and not row.get("is_blueprint"):
            row["group"] = "Quick Use"
        else:
            row["group"] = wiki_group(row)
            row["quick_use"] = row["group"] == "Quick Use"
        row["image_url"] = wiki_image_url(row.get("image"))
    return rows


# ------------------------------------------------------------------ merge
def type_family(item_type):
    low = str(item_type or "").strip().lower()
    if low in GENERIC_TYPES:
        return "generic"
    if low in catalog.WEAPON_TYPES:
        return "weapons"
    if low in ("mods", "mod", "modification", "attachment", "weapon mod"):
        return "mods"
    if low in ("quick use", "quickuse", "consumable"):
        return "quick use"
    if low in ("topside material", "refined material", "basic material", "material", "recyclable", "nature"):
        return "materials"
    if low == "blueprint":
        return "blueprints"
    return low


def combined_group(item_type, is_blueprint, wiki_group):
    """Rampart types are explicit for mods/shields/augments; the wiki fills generic 'Item' rows."""
    low = str(item_type or "").strip().lower()
    if is_blueprint or low == "blueprint":
        return "Blueprints"
    if low == "augment":
        return "Augments"
    if low == "shield":
        return "Shields" if wiki_group == "Misc" else wiki_group
    if low in ("mods", "mod", "modification", "attachment", "weapon mod"):
        return "Weapon Mods"
    if low in catalog.WEAPON_TYPES:
        return "Weapons"
    if low == "key":
        return "Keys"
    if low in ("topside material", "refined material", "basic material", "material", "recyclable", "nature"):
        return "Crafting Materials"
    if low in ("quick use", "quickuse", "consumable"):
        return "Quick Use"
    return wiki_group


def apply_wiki(variant, row):
    variant["wiki_title"] = row["page"]
    variant["wiki_type"] = row.get("type") or ""
    variant["wiki_categories"] = row.get("wiki_categories") or []
    variant["is_blueprint"] = bool(row.get("is_blueprint"))
    variant["group"] = combined_group(variant.get("type"), variant["is_blueprint"], row["group"])
    variant["quick_use"] = variant["group"] == "Quick Use"
    variant["wiki_image"] = row.get("image") or ""
    variant["wiki_image_url"] = row.get("image_url") or ""
    variant["description"] = row.get("description") or ""
    if not variant.get("rarity"):
        variant["rarity"] = row.get("rarity") or ""
    if variant.get("value") in (None, 0) and row.get("sellprice"):
        variant["value"] = row["sellprice"]
    if variant.get("weight") in (None, 0) and row.get("weight"):
        variant["weight"] = row["weight"]
    if variant.get("stack_size") in (None, 0) and row.get("stack_size"):
        variant["stack_size"] = row["stack_size"]


def catalog_variant(row):
    return {
        "name": row["name"],
        "type": row.get("type") or "Item",
        "is_blueprint": bool(row.get("is_blueprint")),
        "raw_categories": [],
        "rarity": row.get("rarity") or "",
        "value": row.get("sellprice"),
        "image": "",
        "stack_size": row.get("stack_size"),
        "max_attachments": 0,
        "quality_level": None,
        "level": None,
        "asset_id": "",
        "source": "wiki",
        "wiki_title": row["page"],
        "wiki_type": row.get("type") or "",
        "wiki_categories": row.get("wiki_categories") or [],
        "group": row["group"],
        "quick_use": row["group"] == "Quick Use",
        "description": row.get("description") or "",
        "weight": row.get("weight"),
        "wiki_image": row.get("image") or "",
        "wiki_image_url": row.get("image_url") or "",
    }


def build():
    store, snapshots = collect_variants()
    if not store:
        raise SystemExit("no snapshots found")

    session = requests.Session()
    print("[wiki] fetching Cargo items + weapons + quick use...", flush=True)
    wiki_rows = collect_wiki_rows(session)
    print("[wiki] pages=%d" % len(wiki_rows), flush=True)

    index = {}
    for row in wiki_rows.values():
        base = base_display(row["name"], row.get("type"), row.get("is_blueprint"))
        index.setdefault((catalog.normalize(base), bool(row.get("is_blueprint"))), []).append(row)

    used = set()
    for variant in store.values():
        base = base_display(variant["name"], variant["type"], variant["is_blueprint"])
        candidates = index.get((catalog.normalize(base), variant["is_blueprint"])) or []
        if not candidates:
            continue
        family = type_family(variant["type"])
        chosen = next((r for r in candidates if type_family(r.get("type")) == family), None)
        if chosen is None and len(candidates) == 1:
            chosen = candidates[0]
        if chosen is None:
            chosen = candidates[0]
        apply_wiki(variant, chosen)
        used.add(chosen["page"])

    added = set()
    for row in wiki_rows.values():
        if row["page"] in used:
            continue
        base = base_display(row["name"], row.get("type"), row.get("is_blueprint"))
        key_base = catalog.normalize(base)
        family = type_family(row.get("type"))
        existing = None
        for variant in store.values():
            vbase = catalog.normalize(base_display(variant["name"], variant["type"], variant["is_blueprint"]))
            if vbase != key_base or bool(variant["is_blueprint"]) != bool(row.get("is_blueprint")):
                continue
            vfamily = type_family(variant["type"])
            if vfamily == family or vfamily == "generic" or family == "generic":
                existing = variant
                break
        if existing is not None:
            apply_wiki(existing, row)
            used.add(row["page"])
            continue
        dedup = (key_base, family, bool(row.get("is_blueprint")))
        if dedup in added:
            continue
        variant = catalog_variant(row)
        store[dedup] = variant
        added.add(dedup)

    items = {}
    for variant in store.values():
        if not variant.get("group"):
            variant["group"] = catalog.classify(
                name=variant["name"], item_type=variant["type"],
                raw_categories=variant.get("raw_categories") or [],
                wiki_categories=variant.get("wiki_categories") or [])
        variant["quick_use"] = variant["group"] == "Quick Use"
        base = base_display(variant["name"], variant["type"], variant["is_blueprint"])
        key = catalog.normalize(base)
        entry = items.setdefault(key, {"name": strip_blueprint(base), "variants": []})
        entry["variants"].append(variant)

    for entry in items.values():
        entry["variants"].sort(key=lambda v: (v["is_blueprint"], v["name"].lower(), v["type"].lower()))

    group_counts = {g: 0 for g in catalog.GROUPS}
    quick_use, blueprints, weapons = [], [], []
    for entry in items.values():
        for variant in entry["variants"]:
            group_counts[variant["group"]] = group_counts.get(variant["group"], 0) + 1
            if variant["group"] == "Quick Use" and not variant["is_blueprint"]:
                quick_use.append(variant["name"])
            elif variant["group"] == "Blueprints":
                blueprints.append(variant["name"])
            elif variant["group"] == "Weapons":
                weapons.append(variant["name"])

    data = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": {
            "rampart": "item_mappings + slots من آخر snapshot لكل حساب (data/snapshots)",
            "wiki_items": API + "?action=cargoquery&tables=items",
            "wiki_weapons": "Category:Weapons (infobox)",
            "wiki_quick_use": "Category:Quick Use + Quick Use subpages",
            "snapshots": {acc: os.path.basename(path) for acc, path in snapshots.items()},
            "wiki_pages": len(wiki_rows),
        },
        "groups": catalog.GROUPS,
        "group_counts": group_counts,
        "item_count": len(items),
        "variant_count": sum(len(e["variants"]) for e in items.values()),
        "wiki_item_count": len(wiki_rows),
        "quick_use_count": len({catalog.normalize(n) for n in quick_use}),
        "blueprint_count": len({catalog.normalize(n) for n in blueprints}),
        "weapon_count": len({catalog.normalize(n) for n in weapons}),
        "quick_use_items": sorted(quick_use, key=str.lower),
        "blueprint_items": sorted(blueprints, key=str.lower),
        "weapon_items": sorted(weapons, key=str.lower),
        "items": items,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


if __name__ == "__main__":
    data = build()
    print("[catalog] items=%d variants=%d wiki_pages=%d quick_use=%d blueprints=%d weapons=%d -> %s" % (
        data["item_count"], data["variant_count"], data["wiki_item_count"], data["quick_use_count"],
        data["blueprint_count"], data["weapon_count"], OUT_FILE))
    for group in catalog.GROUPS:
        print("  %-20s %d" % (group, data["group_counts"].get(group, 0)))
