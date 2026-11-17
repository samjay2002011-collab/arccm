"""قراءة فقط: تقارن بين الحاوية الي اللوحة بتقراها والحاوية الي اللعبة ملانتها فعلاً.

لكل حساب: الأوجمنت المجهّز + اللوداوت الي المؤشر بيشاور عليه + كل شنطة ليها
أبناء، وكم واحدة مشغولة وأسماء اللي جواها. من غير أي كتابة.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config                       # noqa: E402
from backend import pioneer_client as pc         # noqa: E402
from backend import pioneer_tree as pt           # noqa: E402
from backend import store                        # noqa: E402

conn = store.db()
try:
    names = [a["name"] for a in store.list_accounts(conn)]
finally:
    conn.close()

targets = sys.argv[1:] or names
for acc in targets:
    try:
        data = pc.fetch_inventory_for(acc)
    except Exception as exc:
        print(f"\n### {acc}: fetch failed -> {exc}")
        continue
    tree = pt.Tree((data or {}).get("items") or [])
    try:
        lay = pt.layout(tree)
    except pt.TreeError as exc:
        print(f"\n### {acc}: layout error -> {exc}")
        continue
    aug = lay["augment"]["item"] if lay.get("augment") else ""
    print(f"\n### {acc}")
    print("  augment equipped :", tree.name_of(aug) or "(none)")
    print("  panel reads      :", lay["backpack"]["loadout"], "| mode", lay["loadout"]["mode"],
          "| cells", len(lay["backpack"]["slots"]),
          "| filled", sum(1 for s in lay["backpack"]["slots"] if s.get("item")))
    print("  stash filled     :", sum(1 for s in lay["stash"]["slots"] if tree.first_child(s)),
          "/", len(lay["stash"]["slots"]))
    for node in tree.items:
        iid = str(node["instanceId"])
        if "backpack" not in tree.label(iid).lower():
            continue
        kids = tree.children(iid)
        if not kids:
            continue
        filled = [tree.name_of(k) for k in kids if tree.first_child(k)]
        if not filled:
            continue
        print("  FILLED BAG       :", tree.label(iid), "|", len(filled), "cells ->",
              json.dumps(filled, ensure_ascii=False)[:220])
