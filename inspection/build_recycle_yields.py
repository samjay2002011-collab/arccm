# -*- coding: utf-8 -*-
"""يبني data/recycle_yields.json من كل مصادر الداتا المحلية.

المصدر الرسمي للبوابة ما فيهش endpoint بيرجّع جدول إعادة التدوير (masquer:
الـ manifest بيعلن p2ItemRecycleArtifact بس الـ artifact نفسه مش على البوابة
بنفس التوكن)، فبنجمع اللي عندنا محلياً:

  • inspection/network_payloads.json → api_rampart_suinventory_parsed.json
    (item_mappings فيها recycle_info لكل عنصر مملوك وقت التصوير)
  • data/snapshots/*.json.gz (لقطات سابقة من نفس الحساب)

النتيجة: {asset_id: {yield_asset_id: qty}} + meta لأسماء وصور المواد.
الجدول ده عرض بس — البوابة هي اللي بتقرّر التنفيذ فعلاً.
"""
import glob
import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CAPTURE = os.path.join(ROOT, "inspection", "network_payloads.json")
OUT = os.path.join(DATA, "recycle_yields.json")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _iter_mappings():
    """بينتج (asset_id, item_meta) من كل مصدر محلّي فيه item_mappings."""
    seen = set()

    payload = _load_json(CAPTURE) or {}
    parsed = payload.get("api_rampart_suinventory_parsed.json") or {}
    body = parsed.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = {}
    for asset_id, meta in ((body or {}).get("item_mappings") or {}).items():
        seen.add(str(asset_id))
        yield str(asset_id), meta or {}

    for path in sorted(glob.glob(os.path.join(DATA, "snapshots", "*.json.gz"))):
        try:
            with gzip.open(path, "rb") as fh:
                snap = json.loads(fh.read().decode("utf-8"))
        except (OSError, ValueError):
            continue
        for asset_id, meta in ((snap or {}).get("item_mappings") or {}).items():
            if str(asset_id) in seen:
                continue
            seen.add(str(asset_id))
            yield str(asset_id), meta or {}


def main():
    yields, names, images = {}, {}, {}
    for asset_id, meta in _iter_mappings():
        name = (meta.get("display_name") or meta.get("name") or "").strip()
        if name:
            names.setdefault(asset_id, name)
        image = (meta.get("image_filename") or "").strip()
        if image:
            images.setdefault(asset_id, image)
        info = meta.get("recycle_info")
        if isinstance(info, dict) and info:
            clean = {str(k): int(v) for k, v in info.items() if int(v or 0) > 0}
            if clean:
                yields[asset_id] = clean

    # أسماء وصور المواد: من الكتالوج المحلي + جدول مواد الترقية
    materials = _load_json(os.path.join(DATA, "upgrade_materials.json")) or {}
    for asset_id, meta in materials.items():
        names.setdefault(str(asset_id), meta.get("name") or names.get(str(asset_id), ""))
        images.setdefault(str(asset_id), meta.get("image_filename") or images.get(str(asset_id), ""))

    catalog = _load_json(os.path.join(DATA, "items_catalog.json")) or {}
    for entry in (catalog.get("items") or {}).values():
        for variant in entry.get("variants") or []:
            asset_id = variant.get("asset_id")
            if asset_id in (None, "", "None"):
                continue
            key = str(asset_id)
            names.setdefault(key, variant.get("name") or names.get(key, ""))
            image = variant.get("image") or variant.get("wiki_image_url")
            if image and not images.get(key):
                images[key] = image

    yield_assets = set()
    for info in yields.values():
        yield_assets.update(info.keys())

    payload = {
        "source": "local captures (rampart inventory parsed + snapshots)",
        "yields": yields,
        "meta": {aid: {"name": names.get(aid, ""), "image_filename": images.get(aid, "")}
                 for aid in sorted(yield_assets)},
        "item_names": {aid: names.get(aid, "") for aid in sorted(yields)},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)

    print("wrote %s" % OUT)
    print("assets with known yields: %d" % len(yields))
    print("yield assets referenced  : %d" % len(yield_assets))
    missing = [a for a in yield_assets if not names.get(a)]
    print("yield assets without name : %d %s" % (len(missing), missing[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
