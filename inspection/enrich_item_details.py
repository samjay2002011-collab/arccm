"""إثراء كاش arctracker ببيانات التصاميم والاستنسل (قراءة فقط من المصادر العامة).

- Design: يقرأ صفحة العنصر على arctracker.io ويستخرج "Required materials".
- Stencil: يقرأ جدول stencil-tracker على metaforge.app ويستخرج تكلفة Stencil Parts
  والأسلحة المتوافقة.
- يضبط group الصحيح: Designs / Stencils، ويضيف required_materials / compatible_with.

التشغيل: python inspection/enrich_item_details.py
"""
import concurrent.futures
import html
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "arctracker_items_cache.json")
MF_CACHE = os.path.join(ROOT, "data", "metaforge_items_cache.json")
AR_PAGE = "https://arctracker.io/items/%s"
MF_STENCILS = "https://metaforge.app/arc-raiders/stencil-tracker"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/141.0 Safari/537.36",
}
TIMEOUT = 45
WORKERS = 4
MAT_RE = re.compile(r'aria-label="([^"]+),\s*([\d,]+)"[^>]*href="/items/([^"]+)"')


def norm(name):
    text = str(name or "").strip().lower().replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", text)


def get(url, attempts=3):
    last = None
    for attempt in range(attempts):
        try:
            res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            res.raise_for_status()
            return res.text
        except Exception as exc:  # noqa: BLE001 - retry transport errors
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise last


def design_materials(page):
    start = page.find("Required materials</h3>")
    if start < 0:
        return []
    chunk = page[start:start + 14000]
    end = chunk.find("</section>")
    if end > 0:
        chunk = chunk[:end]
    out, seen = [], set()
    for name, qty, slug in MAT_RE.findall(chunk):
        name = html.unescape(name).strip()
        key = (norm(name), slug)
        if key in seen:
            continue
        seen.add(key)
        out.append({"item_id": slug, "name": name, "qty": int(qty.replace(",", ""))})
    return out


def stencil_table():
    page = get(MF_STENCILS)
    rows = {}
    for match in re.finditer(r"<tr>(.*?)</tr>", page, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", match.group(1), re.S)]
        if len(cells) == 4 and cells[0] != "Stencil":
            rows[norm(cells[0])] = {
                "rarity": cells[1],
                "parts": int(cells[2].replace(",", "") or 0),
                "fits": cells[3],
            }
    return rows


def main():
    with open(CACHE, encoding="utf-8") as fh:
        cache = json.load(fh)
    items = cache.get("items") or {}
    by_name = {}
    for item in items.values():
        by_name.setdefault(norm(item.get("name")), item)
    try:
        with open(MF_CACHE, encoding="utf-8") as fh:
            mf_by_name = {norm(v.get("name")): v for v in (json.load(fh).get("items") or {}).values()}
    except OSError:
        mf_by_name = {}

    designs = [it for it in items.values() if norm(it.get("type")) == "design"]
    stencils = [it for it in items.values() if norm(it.get("type")) == "stencil"]
    stencil_rows = stencil_table()
    stencil_parts = by_name.get("stencil parts") or {}

    def icon_for(name):
        hit = by_name.get(norm(name))
        if hit:
            return hit.get("metaforge_image") or hit.get("image_local") or ""
        hit = mf_by_name.get(norm(name))
        return (hit or {}).get("image_local") or ""

    for stencil in stencils:
        stencil["group"] = "Stencils"
        row = stencil_rows.get(norm(stencil.get("name"))) or {}
        parts = int(row.get("parts") or 0)
        stencil["stencil_parts_cost"] = parts
        fits = row.get("fits") or ""
        stencil["compatible_with"] = [fits] if fits == "All weapons" else \
            [part.strip() for part in fits.split(",") if part.strip()]
        stencil["required_materials"] = ([{
            "item_id": "stencil_parts",
            "name": "Stencil Parts",
            "qty": parts,
            "image": stencil_parts.get("metaforge_image") or stencil_parts.get("image_local") or "",
        }] if parts else [])

    failed = {}

    def fetch_design(design):
        try:
            page = get(AR_PAGE % design["id"])
            return design, design_materials(page), None
        except Exception as exc:  # noqa: BLE001 - collect failures
            return design, [], str(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(fetch_design, d) for d in designs]
        done = 0
        for future in concurrent.futures.as_completed(futures):
            design, mats, error = future.result()
            design["group"] = "Designs"
            design["compatible_with"] = []
            if error:
                failed[design["id"]] = error
            for mat in mats:
                mat["image"] = icon_for(mat["name"])
            design["required_materials"] = mats
            done += 1
            if done % 20 == 0 or done == len(designs):
                print("designs %d/%d (failed %d)" % (done, len(designs), len(failed)), flush=True)

    cache["details_source"] = {"designs": "https://arctracker.io/items/<id>",
                               "stencils": "https://metaforge.app/arc-raiders/stencil-tracker"}
    cache["details_enriched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    cache["details_failed"] = failed
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE)

    with_mats = sum(1 for d in designs if d["required_materials"])
    print("designs:", len(designs), "with materials:", with_mats,
          "| stencils:", len(stencils), "| failures:", len(failed))
    for sid, error in list(failed.items())[:8]:
        print("  FAIL", sid, error)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
