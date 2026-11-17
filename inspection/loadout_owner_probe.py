"""قراءة فقط: مين صاحب الشنطة الملانة، وكم خانة مشغولة في كل شجرة لوداوت مرشّحة."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc          # noqa: E402
from backend import pioneer_tree as pt            # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"
tree = pt.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])

WANT = sys.argv[2:] or ["Looting Mk. 2", "Looting Mk. 3 (Survivor)", "Equipped Loadout"]


def chain(iid):
    out = []
    cur = iid
    while cur:
        out.append(tree.label(cur))
        cur = tree.parent.get(cur) or ""
    return " < ".join(out)


def occupancy(node):
    rows = []
    for slot in tree.children(node):
        key = pt._slot_key(tree.label(slot))
        container = tree.first_child(slot)
        cells = tree.children(container) if container else []
        names = []
        for cell in cells:
            content = tree.first_child(cell)
            if not content:
                continue
            leaf = tree.first_child(content) or content
            n = tree.name_of(leaf) or tree.label(leaf)
            if n and not n.startswith("Item Slot"):
                names.append(n)
        rows.append((key or "?", len(cells), len(names), names[:8]))
    return rows


for name in WANT:
    nodes = [str(e["instanceId"]) for e in tree.items if tree.label(e["instanceId"]) == name]
    for n in nodes:
        if tree.children(n):
            print(f"\n=== {name} ({n[:8]}) parent={chain(n).split(' < ')[-1]}")
            print("    chain:", chain(n)[:160])
            for key, cells, filled, names in occupancy(n):
                print(f"    {key:<15} cells={cells:<3} filled={filled:<3} {json.dumps(names, ensure_ascii=False)[:150]}")

print("\n=== who owns every backpack container that has real items ===")
for e in tree.items:
    iid = str(e["instanceId"])
    if "backpack" not in tree.label(iid).lower() or not tree.children(iid):
        continue
    names = []
    for cell in tree.children(iid):
        content = tree.first_child(cell)
        if not content:
            continue
        leaf = tree.first_child(content) or content
        n = tree.name_of(leaf) or tree.label(leaf)
        if n and not n.startswith("Item Slot"):
            names.append(n)
    if names:
        print(f"  {tree.label(iid)[:40]:<42} filled={len(names):<3} chain={chain(iid)[:150]}")
        print(f"      items: {json.dumps(names, ensure_ascii=False)[:260]}")
