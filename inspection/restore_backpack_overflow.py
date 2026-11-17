"""يرجّع رصّات محددة من الشنطة للأوفر (تحميل مكانها اللي كانت فيه قبل التحقق)."""
import sys
from backend import store, pioneer_write as pw, pioneer_client as pc, pioneer_tree as pt

ACC = "G21"
ids = sys.argv[1:]
conn = store.db()
out = pw.move_plan(conn, ACC, [{"target_container": "overflow", "target_wrapper_id": "",
                                "target_slot": "", "instance_ids": ids}])
print("executed", out.get("executed"), "|", (out.get("detail") or out.get("error") or "")[:300])
data = pc.fetch_inventory_for(ACC) or {}
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
stash = set(lay["stash"]["slots"])
bp = {s["wrapper"] for s in lay["backpack"]["slots"]}
for iid, node in sorted(tree.by_id.items(), key=lambda kv: kv[0]):
    if node.get("slots") or str(node.get("gameAssetId")) != "787027311":
        continue
    par = str(tree.parent.get(iid) or "")
    where = "float" if not par else "stash" if par in stash else "backpack" if par in bp else "other"
    print("%s amount=%s %s" % (iid[:8], node.get("amount"), where))
