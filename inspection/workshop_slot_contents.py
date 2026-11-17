"""جرد حاوية «Workshop Slot» في كل شجرة مخزّنة: إيه اللي جواها بالظبط؟

السبب: لو الحساب فيه 6 محطات مقروءة وحساب تاني فيه واحدة، لازم نعرف الفرق ده
حقيقي (المحطة ماابتناش) ولا إن اسم الأصل بييجي بصيغة تانية وإحنا مش قرّينه.
قراءة فقط على الكاش المحلي — مفيش أي طلب للبوابة.
"""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import knowledge, pioneer_tree  # noqa: E402

OUT = Path(__file__).with_name("_workshop_slot_contents_out.txt")
CACHE = Path(__file__).with_name("_trees_cache.json.gz")


def main():
    lines = []
    data = json.loads(gzip.open(CACHE, "rt", encoding="utf-8").read())
    for account, payload in sorted((data if isinstance(data, dict) else {}).items()):
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            lines.append(f"===== {account}\n   شكل الكاش مش قائمة nodes: {type(payload).__name__} keys={list(payload)[:8] if isinstance(payload, dict) else '-'}")
            continue
        tree = pioneer_tree.Tree(items)
        lines.append(f"===== {account} ({len(tree.by_id)} عقدة)")
        slots = [iid for iid in tree.by_id if "workshop slot" in (tree.name_of(iid) or "").lower()]
        if not slots:
            lines.append("   مفيش حاوية باسم Workshop Slot خالص.")
        for sid in slots:
            kids = tree.children(sid)
            lines.append(f"   حاوية {tree.name_of(sid) or tree.label(sid)} (asset={tree._row(sid).get('gameAssetId')}) فيها {len(kids)} عنصر:")
            for kid in kids:
                node = tree.by_id.get(kid, {})
                name = tree.name_of(kid) or "?"
                hit = knowledge.bench_object(name)
                tag = f"-> {hit[0]} LV{hit[1]}" if hit else "-> (مش محطة)"
                lines.append(f"      - {name:<26} amount={node.get('amount')} "
                             f"asset={node.get('gameAssetId')} {tag}")
        # أي عقدة في الشجرة اسمها فيه كلمة محطة/ترقية، برا الحاوية كمان
        needles = ("bench", "workbench", "refiner", "gunsmith", "medical", "utility", "explosives", "anvil")
        loose = {}
        for iid in tree.by_id:
            nm = (tree.name_of(iid) or "").lower()
            if any(n in nm for n in needles) and tree.parent.get(iid) not in slots:
                loose[nm] = loose.get(nm, 0) + 1
        lines.append("   أسماء فيها كلمة محطة وبره الحاوية:")
        for nm in sorted(loose):
            lines.append(f"      {nm} ×{loose[nm]}")
        lines.append(f"   المقروء من الشجرة: {knowledge.bench_levels_from_tree(tree)}")
        lines.append("")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"مكتوب {OUT}")


if __name__ == "__main__":
    main()
