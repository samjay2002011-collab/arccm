"""قياس من لقطات المحفوظة (بدون أي طلب للبوابة): عقد التفعيل العائمة في شجرة كل حساب.

السؤالين:
  1) هل أصل كل عقدة "Unlock Craft X" = أصل العنصر X نفسه؟ (دلّا على إن الإثبات
     يبقى بمطابقة الـ asset id مش بالاسم — بيشوف حتى العقد اللي الفهرس ما اسمهاش.)
  2) كام عقدة عائمة في الشجرة مالهاش اسم في الفهرس أصلاً — دي إثباتات تفعيل بنضيعها.
"""
import builtins
import glob
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, pioneer_tree  # noqa: E402
from backend.pioneer_tree import Tree  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_floating_nodes_out.txt")
SNAP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "snapshots")
PREFIX = "Unlock Craft "


def asset_to_item():
    """{asset_id: slug} لأي عنصر في القاعدة (وصفات ومخطوطات وكل حاجة)."""
    out = {}
    for slug, row in (items_db._load().get("items") or {}).items():
        for a in row.get("asset_ids") or []:
            out[str(a)] = slug
    return out


def main():
    names = pioneer_tree.asset_names()
    by_asset = asset_to_item()
    craftable = {str(r["slug"]) for r in items_db.craftable_rows()}
    lines = []
    say = lambda *a: lines.append(" ".join(str(x) for x in a))  # noqa: E731

    files = {}
    for path in glob.glob(os.path.join(SNAP_DIR, "*.json.gz")):
        acc = os.path.basename(path).rsplit("_2026", 1)[0]
        if acc not in files or path > files[acc]:
            files[acc] = path

    for acc in sorted(files):
        with gzip.open(files[acc], "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        raw = payload.get("raw") or payload.get("payload") or payload
        items = raw.get("items") or raw.get("instances") or []
        tree = Tree(items)
        floating = [iid for iid in tree.by_id if not tree.parent.get(iid)]
        unlock_named, other_named, unnamed = [], [], []
        for iid in floating:
            entry = tree.by_id[iid]
            aid = str(entry.get("assetId") or entry.get("asset_id") or "")
            label = (tree.name_of(iid) or "").strip()
            if label.startswith(PREFIX):
                unlock_named.append((label[len(PREFIX):].strip(), aid, int(entry.get("amount") or 1)))
            elif label:
                other_named.append((label, aid))
            else:
                unnamed.append((aid, int(entry.get("amount") or 1), str(entry.get("templateId") or "")))
        say(f"\n===== {acc}  ملف={os.path.basename(files[acc])}")
        say(f"  instances={len(tree.by_id)} floating={len(floating)} "
            f"unlock_named={len(unlock_named)} other_named={len(other_named)} unnamed={len(unnamed)}")
        matched = [(n, a) for n, a, _amt in unlock_named if a in by_asset]
        unmatched = [(n, a) for n, a, _amt in unlock_named if a not in by_asset]
        say(f"  عقد تفعيل أصلها = أصل عنصر في القاعدة: {len(matched)} / {len(unlock_named)}")
        say(f"  عقد تفعيل أصلها مش معروف كعنصر عندنا: {len(unmatched)} -> {unmatched}")
        craft_matched = sorted({by_asset[a] for _n, a in matched if by_asset[a] in craftable})
        say(f"  دول بيطابقوا وصفات تصنيع ({len(craft_matched)}): {craft_matched}")
        named_assets = {a for _n, a, _amt in unlock_named}
        extra = sorted({(a, by_asset[a]) for _l, a in other_named
                        if a in by_asset and by_asset[a] in craftable})
        say(f"  عقد عائمة تانية بأسماء مش 'Unlock Craft' وبتطابق وصفات ({len(extra)}): {extra[:40]}")
        say(f"  أصول عائمة بلا اسم في الفهرس ({len(unnamed)}):")
        for aid, amt, tmpl in unnamed:
            mark = " <= عنصر معروف: " + str(by_asset.get(aid, "")) if aid in by_asset else ""
            say(f"    {aid:>14} x{amt} {tmpl}{mark}")
        # مطابقة بالعربية: اسم العقدة مقابل اسماء الوصفات اللي مالهاش asset
        empty_asset_recipes = sorted(str(r["slug"]) for r in items_db.craftable_rows()
                                     if not (r.get("asset_ids") or []))
        say(f"  وصفات تصنيع مالهاش أي asset_id في القاعدة ({len(empty_asset_recipes)}): "
            f"{empty_asset_recipes}")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    builtins.print("wrote", OUT)


if __name__ == "__main__":
    main()
