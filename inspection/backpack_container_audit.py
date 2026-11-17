"""قراءة فقط: كل حاوية شنطة في شجرة البوابة الحيّة وكم خانة فيها مشغولة.

بنطبع كمان اللوداوت اللي اللوحة بتقراه (=layout) عشان نقارن بالي اللعبة
بتحط فيه غنائم الرايد فعلاً. مفيش أي كتابة على الحساب.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc          # noqa: E402
from backend import pioneer_tree as pt            # noqa: E402
from backend import store                         # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"

data = pc.fetch_inventory_for(ACCOUNT)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)

inv_root = lay["inventory_root"]
print("account:", ACCOUNT)
print("panel reads ->", json.dumps({
    "loadout": lay["backpack"]["loadout"],
    "mode": lay["loadout"]["mode"],
    "equipped_name": lay["loadout"]["equipped_name"],
    "backpack_container": lay["backpack"]["container"],
    "backpack_cells": len(lay["backpack"]["slots"]),
    "backpack_filled": sum(1 for s in lay["backpack"]["slots"] if s.get("item")),
    "augment": tree.name_of(lay["augment"]["item"]) if lay.get("augment") and lay["augment"].get("item") else "",
}, ensure_ascii=False))

print("\n-- every container under a loadout-ish parent --")
for node in tree.items:
    iid = str(node["instanceId"])
    label = tree.label(iid).lower()
    if "backpack" not in label and "loadout" not in label:
        continue
    kids = tree.children(iid)
    if not kids:
        continue
    filled = [tree.name_of(k) for k in kids if tree.first_child(k)]
    parent = tree.parent.get(iid) or ""
    print(json.dumps({
        "label": tree.label(iid),
        "id": iid[:8],
        "parent": tree.label(parent) if parent else "(root)",
        "children": len(kids),
        "filled": len(filled),
        "items": filled[:14],
        "is_panel_backpack": iid == lay["backpack"]["container"],
    }, ensure_ascii=False))

print("\n-- loadout nodes and their backpack slot --")
for node in tree.items:
    iid = str(node["instanceId"])
    if "loadout" not in tree.label(iid).lower():
        continue
    slots = [k for k in tree.children(iid)]
    print(json.dumps({
        "loadout": tree.label(iid),
        "id": iid[:8],
        "slot_labels": [tree.label(k) for k in slots][:8],
        "filled_total": pt._filled_items(tree, iid),
    }, ensure_ascii=False))
