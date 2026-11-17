"""تنزيل أيقونات MetaForge لكل عناصر ARC Raiders وربطها بالكاش المحلي.

بيقرأ صفحات قاعدة البيانات عبر __data.json (SvelteKit) بدون متصفح، بينزّل الصور
في assets/items/metaforge/، ثم بيضيف metaforge_image لكل عنصر في كاش arctracker
كأيقونة أساسية مع إبقاء image_local كاحتياطي. أيقونات arctracker لا تُحذف.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\rr"
DATA = os.path.join(ROOT, "data")
ASSETS = os.path.join(ROOT, "assets", "items")
MF_DIR = os.path.join(ASSETS, "metaforge")
MF_CACHE = os.path.join(DATA, "metaforge_items_cache.json")
AR_CACHE = os.path.join(DATA, "arctracker_items_cache.json")
AUG_SPECS = os.path.join(DATA, "augments_specs.json")

BASE = "https://metaforge.app/arc-raiders/database/items/page/{page}/__data.json"
IMAGE_HOST = "static.metaforge.app"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json,image/avif,image/webp,image/png,*/*",
    "Referer": "https://metaforge.app/arc-raiders/database/items/page/1",
}
ROMAN_TAIL = re.compile(r"^(.*?)\s+(i{1,3}|iv|v)$")
MOD_SYNONYMS = {"incendiary rounds": "incendiary grenades"}


def http_get(url, binary=False, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as res:
                raw = res.read()
                return raw if binary else json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - retry any transport error
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise last


def decode_page(node):
    arr = node

    def build(value):
        if isinstance(value, dict):
            return {k: pick(v) for k, v in value.items()}
        if isinstance(value, list):
            return [pick(v) for v in value]
        return value

    def pick(value):
        if isinstance(value, int) and 0 <= value < len(arr):
            return build(arr[value])
        if isinstance(value, int) and value < 0:
            return None
        return value

    return build(arr[0])


def fetch_items(pages_limit=0):
    items, page = [], 1
    while True:
        payload = http_get(BASE.format(page=page))
        node = None
        for n in payload.get("nodes") or []:
            data = n.get("data") or []
            if data and isinstance(data[0], dict) and "allItemsCount" in data[0]:
                node = data
                break
        if node is None:
            raise RuntimeError("page %d: no items data node" % page)
        page_data = decode_page(node)
        chunk = page_data.get("data") or []
        if not chunk:
            break
        items.extend(chunk)
        pagination = page_data.get("pagination") or {}
        print("  page %d: %d items (total %d)" % (page, len(chunk), len(items)))
        if not pagination.get("hasNextPage"):
            break
        page += 1
        if pages_limit and page > pages_limit:
            break
        time.sleep(0.12)
    seen, unique = set(), []
    for item in items:
        if item.get("id") and item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    return unique


def norm(name):
    text = str(name or "").strip().lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\b(mk)\.\s*(\d)", r"\1.\2", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(name):
    return re.sub(r"[^a-z0-9]+", "", norm(name))


def parse_variant(name):
    text = norm(name)
    match = re.match(r"^(.*?)\s*\((.*)\)\s*$", text)
    if match:
        base, tail = match.group(1).strip(), match.group(2)
    else:
        parts = re.split(r"\s*·\s*", text, maxsplit=1)
        if len(parts) == 2:
            base, tail = parts[0].strip(), parts[1]
        else:
            base, tail = text, ""
    mods = []
    for part in re.split(r"[,+]", tail):
        key = MOD_SYNONYMS.get(norm(part), norm(part))
        if key:
            mods.append(key)
    return base, tuple(sorted(mods))


def build_matcher(mf_items):
    exact, comp, variants, by_rarity = {}, {}, {}, {}
    for item in mf_items:
        key = norm(item["name"])
        exact.setdefault(key, item)
        comp.setdefault(compact(key), item)
        variants.setdefault(parse_variant(key), item)
        by_rarity.setdefault((key, norm(item.get("rarity"))), item)
    for item in mf_items:
        if norm(item["name"]) == "colorful shoes":
            by_rarity.setdefault(("colorful shoes", norm(item.get("rarity"))), item)

    def match(item):
        name = norm(item.get("name"))
        kind = norm(item.get("type"))
        hit = exact.get(name)
        if hit:
            return hit, "exact"
        hit = comp.get(compact(name))
        if hit:
            return hit, "compact"
        hit = variants.get(parse_variant(name))
        if hit:
            return hit, "variant"
        if kind in ("stencil", "blueprint") or name.endswith(" blueprint"):
            for candidate in (name + " stencil", name + " blueprint"):
                hit = exact.get(candidate) or comp.get(compact(candidate))
                if hit:
                    return hit, "suffix"
        if name == "colorful shoes" or name.startswith("colorful shoes ("):
            hit = by_rarity.get((name.split(" (")[0], norm(item.get("rarity"))))
            if hit:
                return hit, "rarity"
        roman = ROMAN_TAIL.match(name)
        if roman:
            for candidate in (roman.group(1).strip(), roman.group(1).strip() + " i"):
                hit = exact.get(candidate) or comp.get(compact(candidate))
                if hit:
                    return hit, "tier"
        for candidate in (name + " i", name + " 1"):
            hit = exact.get(candidate) or comp.get(compact(candidate))
            if hit:
                return hit, "tier-up"
        return None, ""

    return match


def icon_file(item):
    url = item.get("icon") or ""
    ext = ".webp" if urllib.parse.urlparse(url).path.lower().endswith(".webp") else ".png"
    return item["id"] + ext


def valid_image(path):
    if not os.path.isfile(path) or os.path.getsize(path) < 100:
        return False
    with open(path, "rb") as fh:
        head = fh.read(16)
    return head.startswith(b"\x89PNG\r\n\x1a\n") or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")


def download_icons(mf_items, force=False, workers=6):
    os.makedirs(MF_DIR, exist_ok=True)
    tasks, skipped = [], 0
    for item in mf_items:
        if not item.get("icon"):
            continue
        path = os.path.join(MF_DIR, icon_file(item))
        if not force and valid_image(path):
            skipped += 1
            continue
        tasks.append((item, path))
    failures = []

    def fetch(task):
        item, path = task
        try:
            raw = http_get(item["icon"], binary=True)
            if not raw:
                raise RuntimeError("empty body")
            tmp = path + ".part"
            with open(tmp, "wb") as fh:
                fh.write(raw)
            if not valid_image(tmp):
                os.remove(tmp)
                raise RuntimeError("invalid image data")
            os.replace(tmp, path)
            return item["id"], len(raw)
        except Exception as exc:  # noqa: BLE001 - collect per-icon failures
            return item["id"], str(exc)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item_id, result in pool.map(fetch, tasks):
            done += 1
            if isinstance(result, str):
                failures.append((item_id, result))
            if done % 100 == 0:
                print("  downloaded %d/%d" % (done, len(tasks)))
    return skipped, failures


def update_arctracker(mf_items, match):
    with open(AR_CACHE, encoding="utf-8") as fh:
        cache = json.load(fh)
    matched = fallback = 0
    missing_files = 0
    for item in (cache.get("items") or {}).values():
        hit, _how = match(item)
        local = icon_file(hit) if hit else ""
        path = os.path.join(MF_DIR, local) if local else ""
        if hit and valid_image(path):
            item["metaforge_image"] = "metaforge/" + local
            item["metaforge_id"] = hit["id"]
            item["metaforge_name"] = hit["name"]
            matched += 1
        else:
            if hit:
                missing_files += 1
            item.pop("metaforge_image", None)
            item.pop("metaforge_id", None)
            item.pop("metaforge_name", None)
            fallback += 1
    cache["metaforge_source"] = "metaforge.app"
    cache["metaforge_image_dir"] = "metaforge"
    cache["metaforge_matched"] = matched
    cache["metaforge_fallback"] = fallback
    cache["metaforge_built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = AR_CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, AR_CACHE)
    return matched, fallback, missing_files


def update_augments(mf_items, match):
    try:
        with open(AUG_SPECS, encoding="utf-8") as fh:
            specs = json.load(fh)
    except OSError:
        return 0
    updated = 0
    groups = [specs.get("base") or {}] + list(specs.get("augments") or [])
    for spec in groups:
        hit, _how = match(spec)
        if hit and valid_image(os.path.join(MF_DIR, icon_file(hit))):
            spec["image"] = "metaforge/" + icon_file(hit)
            updated += 1
    tmp = AUG_SPECS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(specs, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, AUG_SPECS)
    return updated


def write_cache(mf_items):
    payload = {
        "source": "https://metaforge.app/arc-raiders/database/items",
        "offline": all(valid_image(os.path.join(MF_DIR, icon_file(it)))
                       for it in mf_items if it.get("icon")),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "item_count": len(mf_items),
        "unique_icon_count": len({it.get("icon") for it in mf_items if it.get("icon")}),
        "items": {
            it["id"]: {
                "id": it["id"], "name": it.get("name"), "type": it.get("item_type"),
                "rarity": it.get("rarity"), "value": it.get("value"),
                "icon_url": it.get("icon"), "image_local": "metaforge/" + icon_file(it),
            }
            for it in mf_items if it.get("icon")
        },
    }
    tmp = MF_CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, MF_CACHE)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download existing icons")
    parser.add_argument("--pages", type=int, default=0, help="limit pages (debug)")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    print("--- MetaForge items ---")
    items = fetch_items(args.pages)
    print("items:", len(items), "| unique icons:", len({it.get("icon") for it in items if it.get("icon")}))
    if args.skip_download:
        with open(MF_CACHE, encoding="utf-8") as fh:
            cached = json.load(fh)
        by_id = {v["name"]: v for v in cached.get("items", {}).values()}
        items = [dict(it, icon=(by_id.get(it["name"]) or {}).get("icon_url")) for it in items]

    print("--- icons ---")
    skipped, failures = (0, []) if args.skip_download else download_icons(items, args.force)
    present = sum(1 for it in items if it.get("icon")
                  and valid_image(os.path.join(MF_DIR, icon_file(it))))
    print("downloaded now:", len(items) - skipped - len(failures), "| already cached:", skipped,
          "| present:", present, "/", len(items), "| failures:", len(failures))
    for item_id, error in failures[:10]:
        print("  FAIL", item_id, error)

    payload = write_cache(items)
    print("cache:", os.path.relpath(MF_CACHE, ROOT), "| offline:", payload["offline"])

    match = build_matcher(items)
    print("--- arctracker mapping ---")
    matched, fallback, missing = update_arctracker(items, match)
    print("matched:", matched, "| fallback:", fallback, "| icon file missing:", missing)
    aug = update_augments(items, match)
    print("augment specs updated:", aug)
    print("REPORT:", json.dumps({"items": len(items), "present_icons": present,
                                 "match": matched, "fallback": fallback,
                                 "failures": len(failures), "augments": aug},
                                ensure_ascii=False))
    return 1 if failures or missing else 0


if __name__ == "__main__":
    sys.exit(main())
