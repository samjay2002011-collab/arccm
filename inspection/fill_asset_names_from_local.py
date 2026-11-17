"""تعبئة أسماء الأصول الناقصة من مصادر محلية موجودة على القرص (من غير أي طلب شبكي).

المصادر (كلها مقاسة ومخزّنة من قبل):
  1. `data/craft_offers_raw.json` — طرح قديم فيه `reward_meta`/خامات لكل صنف:
     `asset_id` + `display_name` + الندرة.
  2. `data/snapshots/*.json.gz` -> `item_mappings` — نفس الحاجة لكل أيتم في آخر
     لقطة لكل حساب (بنستثني أسماءنا المشتقة `Item <id>` لأنها مش مصدر).

الأسماء بتتكتب في `data/catalog/asset_index_local.csv` عن طريق `pioneer_tree.remember()`
(نفس الملف اللي فيه التعريفات اليدوية السابقة)، فالأصلي `asset_index.csv` بيفضل زي ما هو.

  python inspection/fill_asset_names_from_local.py            # معاينة بس
  python inspection/fill_asset_names_from_local.py --apply    # يكتب
"""
import argparse
import collections
import glob
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import items_db, pioneer_tree  # noqa: E402

DUMP = ROOT / "data" / "craft_offers_raw.json"
SNAPS = str(ROOT / "data" / "snapshots" / "*.json.gz")
PLACEHOLDER = re.compile(r"^Item -?[0-9]+$")


def decode_stream(text):
    dec = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \r\n\t":
            i += 1
        if i >= n:
            return
        obj, end = dec.raw_decode(text, i)
        yield obj
        i = end


def walk(node, out):
    """أي dict فيه asset_id + display_name حقيقي بنخده."""
    if isinstance(node, str):
        try:
            for inner in decode_stream(node):
                walk(inner, out)
        except ValueError:
            pass
        return
    if isinstance(node, dict):
        aid = node.get("asset_id")
        nm = node.get("display_name")
        if aid is not None and isinstance(nm, str) and nm.strip():
            out[str(aid)].add(nm.strip())
        for value in node.values():
            walk(value, out)
    elif isinstance(node, list):
        for value in node:
            walk(value, out)


def collect():
    names = collections.defaultdict(set)
    walk(json.load(open(DUMP, encoding="utf-8")), names)
    for path in glob.glob(SNAPS):
        payload = json.loads(gzip.open(path, "rt", encoding="utf-8").read())
        for aid, row in (payload.get("item_mappings") or {}).items():
            nm = str((row or {}).get("display_name") or (row or {}).get("name") or "").strip()
            if nm:
                names[str(aid)].add(nm)
    return {k: {n for n in v if not PLACEHOLDER.match(n)} for k, v in names.items()}


def pick(aid, candidates):
    """اسم واحد: الأفضل اللي الفهرس المحلي بيعرفه (أيقونة + ندرة)، وبعدين الأطول."""
    known = [n for n in candidates if items_db.find(name=n)]
    if len(known) > 1:
        return known[0], "arctracker"
    if known:
        return known[0], "arctracker"
    if len(candidates) == 1:
        return next(iter(candidates)), "name-only"
    return None, "conflict"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from sqlite3 import connect  # noqa: PLC0415
    from backend import config
    conn = connect(config.DB_FILE)
    owned = {str(r[0]) for r in conn.execute(
        "SELECT DISTINCT asset_id FROM instances WHERE asset_id IS NOT NULL AND asset_id <> ''")}

    index = pioneer_tree.asset_names()
    candidates = collect()
    rows, skipped = [], collections.Counter()
    for aid, cands in sorted(candidates.items()):
        if not cands:
            skipped["فاضي"] += 1
            continue
        cur = index.get(aid) or {}
        if (cur.get("display_name") or cur.get("game_asset_name") or "").strip():
            skipped["موجود في الفهرس"] += 1
            continue
        name, why = pick(aid, cands)
        if not name:
            skipped["أسماء متضاربتة"] += 1
            continue
        rows.append((aid, name, why, aid in owned))

    print("أسماء مقترحة:", len(rows))
    for key, n in skipped.items():
        print("  متجاهل (%s): %d" % (key, n))
    in_stock = [r for r in rows if r[3]]
    print("منها موجود في مخازن حساباتنا:", len(in_stock))
    for aid, name, why, present in rows[:15]:
        print("   %s %-28s %s %s" % (aid, name, why, "<- في المخزن" if present else ""))
    if not args.apply:
        print("\n(معاينة بس — `--apply` هيكتب في asset_index_local.csv)")
        return 0
    for aid, name, why, _present in rows:
        pioneer_tree.remember(aid, name, "local evidence: rampart-era offers/snapshot mappings (%s)" % why)
    print("\n[+] اتكتب %d اسم في %s" % (len(rows), Path(pioneer_tree.ASSET_LOCAL_FILE).name))
    after = pioneer_tree.asset_names()
    still = sorted(a for a in owned if not ((after.get(a) or {}).get("display_name")
                                            or (after.get(a) or {}).get("game_asset_name")))
    print("فاضل مجهول في مخازن حساباتنا: %d" % len(still))
    for a in still[:20]:
        print("   ", a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
