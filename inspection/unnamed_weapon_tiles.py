"""ليه بلاطة «Stiletto IV» بتطلع «؟» عندنا؟ — تشخيص من الأشجار المخزّنة.

بنطبع لكل أصل مش معروف الاسم: هو في أي حاوية، أولاده إيه، والـ hint بتاعهم
(الـ hint بيقول نوع السلايح اللي الخانة دي بتقبلها). كده بنعرف هل الأصل ده
سلاح ولا لأ، ومن أي نوع، من غير ما نخمّن اسم تجاري.
قراءة فقط على الكاش المحلي.
"""
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import pioneer_tree  # noqa: E402

OUT = Path(__file__).with_name("_unnamed_weapon_tiles_out.txt")
CACHE = Path(__file__).with_name("_trees_cache.json.gz")


def hint_of(names, aid):
    return (names.get(str(aid)) or {}).get("hint") or ""


def name_of(names, aid):
    row = names.get(str(aid)) or {}
    return (row.get("display_name") or row.get("game_asset_name") or "").strip()


def main():
    lines = []
    names = pioneer_tree.asset_names()
    data = json.loads(gzip.open(CACHE, "rt", encoding="utf-8").read())
    mod_slot_hints = defaultdict(set)   # hint الحاوية -> أنواع الأسلحة اللي بتقبلها
    for account, payload in sorted(data.items()):
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            continue
        tree = pioneer_tree.Tree(items)
        lines.append(f"===== {account}")
        for iid, node in tree.by_id.items():
            aid = str(node.get("gameAssetId"))
            kids = tree.children(iid)
            nm = name_of(names, aid)
            if nm:
                continue
            parent = tree.parent.get(iid) or ""
            pname = name_of(names, str(tree.by_id.get(parent, {}).get("gameAssetId")))
            # سلاح = ليه أولاد في خانات مرفقات (العد من غير كده مفيش لازمة)
            if not kids:
                continue
            kid_names = [name_of(names, str(tree.by_id.get(k, {}).get("gameAssetId"))) for k in kids]
            kid_hints = [hint_of(names, str(tree.by_id.get(k, {}).get("gameAssetId"))) for k in kids]
            lines.append(f"   id={aid:<14} أب={pname or '(عائم)'} "
                         f"dur={node.get('durability')}/{node.get('maxDurability')} أولاد={len(kids)}")
            for kn, kh in zip(kid_names, kid_hints):
                lines.append(f"        - {kn or '(مجهول)'}  | hint={kh[:110]}")
            for kh in kid_hints:
                if kh:
                    mod_slot_hints[aid].add(kh[:80])
        lines.append("")
    lines.append("===== ملخص: كل أصل مجهول بالاسم وبتقبله خانات مرفقات إيه =====")
    for aid, hints in sorted(mod_slot_hints.items()):
        lines.append(f"   {aid}: " + " || ".join(sorted(hints))[:260])
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("مكتوب", OUT, "سطور", len(lines))


if __name__ == "__main__":
    main()
