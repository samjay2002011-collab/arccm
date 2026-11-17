# تسمية البلاطات المجهولة من بصمتها في داتا الرسمية
"""inspection/unknown_fingerprint_name.py

بيدوّر على كل asset id مش معروف في داتابيز المخزن وبيقارن بصمته الرقمية في
data/pioneer_game_data.json (الرسمية) ببصمة عناصر arctracker (stack + value +
ناتج الريسايد بالأسماء). التقرير بس — مافيش كتابة للفهرس من غير --apply.

    python -X utf8 inspection/unknown_fingerprint_name.py            # تقرير
    python -X utf8 inspection/unknown_fingerprint_name.py --apply    # تسجيل الأسماء المؤكدة
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_FILE = os.path.join(ROOT, "data", "rampart_local.db")
GAME_FILE = os.path.join(ROOT, "data", "pioneer_game_data.json")
ITEMS_DB = os.path.join(ROOT, "data", "items_db.json")
COIN_ID = -898439395


def load_game():
    raw = json.load(open(GAME_FILE, encoding="utf-8"))["items-description"]["itemDescriptions"]
    if isinstance(raw, list):
        return {str(r["gameAssetId"]): r for r in raw}
    return raw


def load_items():
    return json.load(open(ITEMS_DB, encoding="utf-8"))["items"]


def scrap_value(rec):
    items = ((rec.get("scrap") or {}).get("rewardPackage") or {}).get("rewardedItems") or []
    for entry in items:
        if entry.get("gameAssetId") == COIN_ID:
            return int(entry.get("amount") or 0)
    return None


def yield_names(rec, id_to_name):
    """ناتج الريسايد بالأسماء — أقوى بصمة بعد الستاك والقيمة."""
    out = []
    for entry in (rec.get("recycle") or {}).get("rewardedItems") or []:
        name = id_to_name.get(str(entry.get("gameAssetId")))
        if name:
            out.append((name.lower(), int(entry.get("amount") or 0)))
    return tuple(sorted(out))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    game = load_game()
    items = load_items()

    id_to_name = {}
    for row in items.values():
        for aid in row.get("asset_ids") or []:
            id_to_name[str(aid)] = row["name"]

    # بصمة arctracker لكل عنصر: (ستاك، قيمة، ناتج ريسايد بالأسماء)
    tracker = {}
    for row in items.values():
        yields = tuple(sorted((str(y["name"]).lower(), int(y["qty"] or 0))
                              for y in row.get("recycles_into") or []))
        tracker.setdefault((int(row.get("stack_size") or 0), int(row.get("value") or 0), yields), []).append(row)

    conn = sqlite3.connect(DB_FILE)
    unknown = [r[0] for r in conn.execute(
        "select distinct asset_id from instances "
        "where asset_id is not null and asset_id<>'' and (name is null or name='' or name like 'Item %')")]
    conn.close()

    named, ambiguous, unmatched = [], [], []
    for aid in sorted(unknown, key=str):
        rec = game.get(str(aid))
        if rec is None:
            unmatched.append((aid, "no official record"))
            continue
        stack = int(rec.get("maxAmount") or 0)
        value = scrap_value(rec)
        yields = yield_names(rec, id_to_name)
        key = (stack, value, yields)
        cands = tracker.get(key) or []
        if len(cands) == 1:
            named.append((aid, cands[0]["name"], key))
        elif len(cands) > 1:
            ambiguous.append((aid, key, [c["name"] for c in cands]))
        else:
            # بدون ناتج ريسايد مسجّل عند arctracker: نجرب الستاك + القيمة لوحدهما
            loose = [c for c in tracker.get((stack, value, ())) or [] if not c.get("recycles_into")]
            if len(loose) == 1:
                named.append((aid, loose[0]["name"], (stack, value, ())))
            else:
                unmatched.append((aid, "stack=%s value=%s yields=%s -> %s names"
                                  % (stack, value, yields or "-", len(loose))))

    print("=" * 78)
    print("بلاطات مجهولة: %s | مؤكدة: %s | متشابهة: %s | بلا مرجع: %s"
          % (len(unknown), len(named), len(ambiguous), len(unmatched)))
    print("=" * 78)
    for aid, name, key in named:
        print("[OK]      %-13s -> %-28s (stack=%s value=%s yields=%s)"
              % (aid, name, key[0], key[1], key[2] or "-"))
    for aid, key, names in ambiguous:
        print("[AMBIG]   %-13s (stack=%s value=%s yields=%s): %s"
              % (aid, key[0], key[1], key[2] or "-", ", ".join(names)))
    for aid, why in unmatched:
        print("[NONE]    %-13s %s" % (aid, why))

    if args.apply:
        from backend import pioneer_tree
        for aid, name, key in named:
            out = pioneer_tree.remember(aid, name, "fingerprint %s/%s%s" % (key[0], key[1], "/" + "+".join("%s x%s" % y for y in key[2]) if key[2] else ""))
            print("[REMEMBERED]", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
