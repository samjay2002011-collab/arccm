"""فحص عقد "Unlock Craft": أي اسم بيفتح أكتر من هدف، وعلاقة أصل العقدة بأصل العنصر.

الهدف: نعرف بالظبطكام عقدة اسمها مالوش هدف واحد (زي "Extended Barrel") عشان الفلتر
الصارم ما يديش دليل لعنصرين مع بعض، ولو فيه علاقة رقم بين أصل العقدة وأصل العنصر
نقدر نفصل الطبقات.
"""
import builtins
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, pioneer_tree  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_unlock_nodes_ambig_out.txt")


def main():
    uni = knowledge.unlock_universe()
    with open(OUT, "w", encoding="utf-8") as fh:
        say = lambda *a: builtins.print(*a, file=fh)  # noqa: E731
        multi, no_target = [], []
        for ref in uni.values():
            if len(ref["gates"]) > 1:
                multi.append(ref)
            elif not ref["gates"]:
                no_target.append(ref)
        say(f"== عقد بأكتر من هدف ({len(multi)}) ==")
        for ref in multi:
            say(" ", json.dumps(ref, ensure_ascii=False))
        say(f"\n== عقد بلا هدف ({len(no_target)}) ==")
        for ref in no_target:
            say(" ", json.dumps(ref, ensure_ascii=False))

        # علاقة أصل العقدة بأصل العنصر: طباعة أزواج للحالات الواضحة
        say("\n== أزواج (أصل العقدة -> أصول العنصر) ==")
        rows = []
        for ref in uni.values():
            if len(ref["gates"]) == 1:
                tgt = items_db.by_slug(ref["gates"][0]) or {}
                rows.append((ref["name"], ref["assets"], tgt.get("asset_ids") or []))
        for name, node_assets, tgt_assets in sorted(rows):
            delta = []
            for n in node_assets:
                for t in tgt_assets:
                    try:
                        delta.append(int(n) - int(t))
                    except (TypeError, ValueError):
                        pass
            say(f"  {name:40s} node={node_assets} target={tgt_assets} delta={delta}")
        deltas = {}
        for name, node_assets, tgt_assets in rows:
            for n in node_assets:
                for t in tgt_assets:
                    deltas.setdefault(int(n) - int(t), 0)
                    deltas[int(n) - int(t)] += 1
        say("\ndelta counts:", sorted(deltas.items(), key=lambda i: -i[1])[:10])

        # Extended Barrel تحديداً: أصول العقد في الفهرس
        say("\n== الفهرس: كل أصل اسمه فيه Extended ==")
        for aid, row in pioneer_tree.asset_names().items():
            label = str(row.get("display_name") or row.get("game_asset_name") or "")
            if "Extended Barrel" in label or "extended_barrel" in label.lower():
                say("  ", aid, "|", label, "|", row.get("game_asset_name"))
    builtins.print("wrote", OUT)


if __name__ == "__main__":
    main()
