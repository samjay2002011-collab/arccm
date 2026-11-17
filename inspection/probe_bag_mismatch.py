# قراءة فقط: هل كل خانات اللوحة جوا حاوية بتقرأها اللعبة؟
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from backend import pioneer_client as pc, pioneer_tree as pt

acct = sys.argv[1] if len(sys.argv) > 1 else "G22"
data = pc.fetch_inventory_for(acct)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
nodes = pt.active_containers(tree)
print("mode :", lay["loadout"]["mode"], "| loadout:", repr(tree.label(lay["loadout"]["node"])))
print("active_containers:")
for n in nodes:
    print("   ", n, repr(tree.label(n)))
bad = []
for key, slots in lay["loadout"]["slots"].items():
    for s in slots:
        if not any(pt.in_subtree(tree, s["wrapper"], n) for n in nodes):
            bad.append((key, s["wrapper"]))
for s in lay["backpack"]["slots"]:
    w = s["wrapper"]
    if not any(pt.in_subtree(tree, w, n) for n in nodes):
        bad.append(("backpack", w))
print("خانات برّه أي حاوية:", len(bad))
for b in bad[:12]:
    print("   ", b[0], repr(tree.label(b[1])))
