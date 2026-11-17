"""قراءة فقط: مقارنة شجرة لوداوت باسم معيّن بالشجرة الي اللوحة بتقراها.

بيطبعoccupancy خانات التجهيز والشنطة للشجرتين عشان نعرف أي واحدة هي الحيّة
فعلاً (الي فيها السلاح والكدّات والشنطة ملانة).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc          # noqa: E402
from backend import pioneer_tree as pt            # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"
tree = pt.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])
lay = pt.layout(tree)


def describe(node, title):
    print(f"\n--- {title}: {tree.label(node)} ({node[:8]}) ---")
    for slot in tree.children(node):
        label = tree.label(slot)
        key = pt._slot_key(label)
        container = tree.first_child(slot)
        cells = tree.children(container) if container else []
        filled = []
        for cell in cells:
            content = tree.first_child(cell)
            if not content:
                continue
            # الخانة بتحط الصنف في حفيد (Item Slot -> الصنف نفسه)
            leaf = tree.first_child(content) or content
            filled.append(tree.name_of(leaf) or tree.label(leaf))
        print(f"  {key or '?':<12} {label[:44]:<44} cells={len(cells):<3} filled={len(filled)} :: "
              + json.dumps([f for f in filled if f][:10], ensure_ascii=False)[:200])


inv = lay["inventory_root"]
print("account:", ACCOUNT)
print("panel reads:", lay["backpack"]["loadout"], "mode:", lay["loadout"]["mode"])
describe(lay["loadout"]["node"], "PANEL CONTAINER")
if lay["loadout"]["equipped_node"] and lay["loadout"]["equipped_node"] != lay["loadout"]["node"]:
    describe(lay["loadout"]["equipped_node"], "EQUIPPED POINTER")

# أي شجرة loadout تانية فيها شنطة ملانة؟
for node in tree.items:
    iid = str(node["instanceId"])
    if "loadout" not in tree.label(iid).lower():
        continue
    if iid in {lay["loadout"]["node"], lay["loadout"]["equipped_node"]}:
        continue
    if tree.parent.get(iid):
        continue  # جذور بس
    bags = [c for c in tree.children(iid) if pt._slot_key(tree.label(c)) == "backpack"]
    for b in bags:
        inner = tree.first_child(b)
        if not inner:
            continue
        cells = tree.children(inner)
        filled = [tree.name_of(tree.first_child(c) or c) for c in cells if tree.first_child(c)]
        filled = [f for f in filled if f and not f.startswith("Item Slot")]
        if filled:
            describe(iid, "OTHER LOADOUT ROOT")
            break
