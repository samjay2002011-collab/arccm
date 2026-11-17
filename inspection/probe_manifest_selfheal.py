"""يثبت إن الموقع بيرجّع المانيفست بنفسه بعد أي باتش: يحط الرقم القديم، يعمل نقل، ويستنى النجاح.

  python inspection/probe_manifest_selfheal.py G14
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree as pt, pioneer_write as pw, store  # noqa: E402

ACC = sys.argv[1] if len(sys.argv) > 1 else "G14"
good = pc.load_manifest()
pc.save_manifest("4444166003814106529", build="CL1438640-A968EFC7-BK4912")
print("forced stale manifest:", pc.load_manifest())
try:
    tree = pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])
    cells = list(pt.layout(tree)["stash"]["slots"])
    item = next((str(tree.first_child(c)) for c in cells if tree.first_child(c)), "")
    src = tree.parent.get(item)
    dst = next((c for c in cells if c != src and not tree.first_child(c)), "")
    out = pw.move(store.db(), ACC, "stash", [{"instance_id": item}], target_wrapper_id=dst)
    print("MOVE executed=%s error=%s" % (out.get("executed"), out.get("error")))
    back = pw.move(store.db(), ACC, "stash", [{"instance_id": item}], target_wrapper_id=src)
    print("RESTORE executed=%s" % back.get("executed"))
finally:
    now = pc.load_manifest()
    print("manifest now: %s | was good: %s | same: %s" % (now, good, now == good))
    if now != good:
        pc.save_manifest(good)
        print("restored to", pc.load_manifest())
