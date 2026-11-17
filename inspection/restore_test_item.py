"""إرجاع القطعة الي نقلها الاختبار للستاش + تثبيت حالة المسار على batch."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc, pioneer_tree as pt, pioneer_write as pw, store  # noqa: E402

ACC, ITEM = "G18", "b3c0bfff-1b1f-41e9-a87f-e24056c036bd"
try:
    os.remove(pw.ROUTE_STATE_FILE)
except OSError:
    pass
print("probe:", pw.probe_route(pc.account_token(ACC))[0], "|", pw.route_state()["endpoint"])

tree = pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])
lay = pt.layout(tree)
print("item where:", tree.parent.get(ITEM), tree.name_of(ITEM), tree.amount(ITEM))
free = [c for c in (str(x) for x in lay["stash"]["slots"]) if not tree.first_child(c)]
print("stash free cells:", len(free))

conn = store.db()
res = pw.move_plan(conn, ACC, [{"target_container": "stash", "target_wrapper_id": "",
                                "target_slot": "", "instance_ids": [ITEM]}])
conn.close()
print("restore ->", json.dumps({k: res.get(k) for k in
      ("executed", "error", "detail", "items", "to_overflow", "verification")},
      ensure_ascii=False, default=str)[:400])

after = pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])
in_stash = str(after.parent.get(ITEM) or "") in set(str(c) for c in after.kids) and \
    str(after.parent.get(ITEM) or "") in set(str(c) for c in lay["stash"]["slots"])
print("item now:", after.parent.get(ITEM), "amount", after.amount(ITEM), "in stash cells:", in_stash)
print("route state:", json.dumps(pw.route_state(), ensure_ascii=False)[:180])
