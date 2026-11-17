# -*- coding: utf-8 -*-
"""لقرة قراءة فقط من بوابة Embark الرسمية — بتطبع شكل أكوام عنصر واحد لكل حساب.

بتتعمل قبل وبعد تجربة الدمج على موقع Rampart، فالفرق بينها يقرر:
هل دمج Rampart كتابة حقيقية عند Embark ولا سجل داخلي عندهم بس.

    python -m inspection.stack_snapshot RAIDER33368 1827408349
"""
import json
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

ACCOUNTS = sys.argv[1:-1] or ["RAIDER33368"]
ASSET = sys.argv[-1] if len(sys.argv) > 2 else "1827408349"


def snapshot(account, asset=None):
    asset = str(asset or ASSET)
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    lay = pioneer_tree.layout(tree)
    cells = {}
    for name in ("stash", "overflow", "backpack"):
        cont = str((lay.get(name) or {}).get("container") or "")
        if not cont:
            continue
        for cell in tree.children(cont):
            for item in tree.children(cell) or []:
                row = tree.by_id.get(item) or {}
                if str(row.get("gameAssetId")) == asset and not row.get("slots"):
                    cells[item] = (name, int(row.get("amount") or 1),
                                   int(row.get("stackSize") or 0))
    loose = {i: r for i, r in tree.by_id.items()
             if str(r.get("gameAssetId")) == asset and not r.get("slots")}
    amounts = sorted((a for _, a, _ in cells.values()), reverse=True)
    total = sum(int(r.get("amount") or 0) for r in loose.values())
    cap = max([c for _, _, c in cells.values()] +
              [int(r.get("stackSize") or 0) for r in loose.values()] or [0])
    return {"account": account, "placed": len(cells), "loose": len(loose),
            "total": total, "cap": cap, "amounts": amounts,
            "ideal": -(-total // cap) if cap else None,
            "where": sorted({name for name, _, _ in cells.values()}),
            "ids": {i[:8]: w for i, w in cells.items()},
            "stacks": sorted([[i[:8], int(r.get("amount") or 0),
                               (tree.parent.get(i) or "-")[:8]]
                              for i, r in loose.items()], key=lambda s: (-s[1], s[0]))}


def main():
    asset = sys.argv[-1] if len(sys.argv) > 2 else ASSET
    accs = sys.argv[1:-1] if len(sys.argv) > 2 else (ACCOUNTS or [sys.argv[1]])
    for acc in accs:
        s = snapshot(acc, asset)
        print("%-14s الكوم المرصوص %d | الحر %d | المجمول %d | الحد %s |Ideal %s"
              % (acc, s["placed"], s["loose"], s["total"], s["cap"] or "?",
                 s["ideal"] if s["ideal"] is not None else "?"))
        print("   %s" % s["amounts"])
        print("   أماكن: %s" % (",".join(s["where"]) or "-"))
        for row in s["stacks"]:
            print("      %s  %4d" % (row[0], row[1]))
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "snapshot_%s_%s.json" % (acc, asset)), "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
