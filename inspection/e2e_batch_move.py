"""نهاية-لنهاية على مسار batch-operation من كود الموقع نفسه:

1) يمسح حالة المسار ويجبر الراوتر على الفحص من جديد (لاقي batch-operation).
2) ينفّذ نقلة حقيقية واحدة بـ pioneer_write.move_plan (ستاش -> شنطة).
3) يرجّعها لنفس الخانة ويتأكد إن الشجرة مطابقة 100% لحالتها الأولى.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc, pioneer_tree as pt, pioneer_write as pw, store  # noqa: E402

ACC = "G18"
TOKEN = pc.account_token(ACC)

try:
    os.remove(pw.ROUTE_STATE_FILE)
except OSError:
    pass
print("paused:", pw.paused())
alive, detail = pw.probe_route(TOKEN)
print("probe ->", alive, "|", str(detail)[:200])
print("route state:", json.dumps(pw.route_state(), ensure_ascii=False))
print("status:", json.dumps({k: pw.status()[k] for k in ("endpoint", "route_style", "detail")},
                            ensure_ascii=False))
if not pw.batch_route():
    sys.exit("المسار المكتشف مش batch — وقفنا")


def snap():
    t = pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])
    return t, {str(e["instanceId"]): str(t.parent.get(str(e["instanceId"])) or "") for e in t.items}


tree, first = snap()
lay = pt.layout(tree)
cells = [str(c) for c in lay["stash"]["slots"]]
bp = [str(c["wrapper"] if isinstance(c, dict) else c) for c in (lay["backpack"]["slots"] or [])]
src_cell = src_item = ""
for c in cells:
    it = tree.first_child(c)
    if it and "bandage" in (tree.name_of(it) or "").lower():
        src_cell, src_item = c, it
        break
free_bp = next((c for c in bp if not tree.first_child(c)), "")
print("move %s (%s x%d) : %s -> %s" % (tree.name_of(src_item), src_item[:8],
                                       tree.amount(src_item), src_cell[:8], free_bp[:8]))

conn = store.db()
res = pw.move_plan(conn, ACC,
                   [{"target_container": "backpack", "target_wrapper_id": free_bp,
                     "target_slot": "", "instance_ids": [src_item]}])
conn.close()
print("\nmove_plan ->", json.dumps({k: res.get(k) for k in
      ("executed", "error", "detail", "items", "requests", "elapsed_ms", "to_overflow",
       "restored", "verification")}, ensure_ascii=False, default=str)[:700])
print("batch meta:", json.dumps((res.get("preview") or {}).get("body"), ensure_ascii=False)[:300])

t2, now = snap()
print("after move: parent=%s (want %s) diff_vs_first=%d"
      % (now.get(src_item), free_bp, len([k for k in first if first[k] != now.get(k)])))

conn = store.db()
back = pw.move_plan(conn, ACC, [{"target_container": "stash", "target_wrapper_id": src_cell,
                                 "target_slot": "", "instance_ids": [src_item]}])
conn.close()
print("\nmove back ->", json.dumps({k: back.get(k) for k in
      ("executed", "error", "detail", "items", "restored")}, ensure_ascii=False, default=str)[:500])

t3, done = snap()
diff = [k for k in first if first[k] != done.get(k)]
gone = [k for k in first if k not in done]
added = [k for k in done if k not in first]
print("\nFINAL: moved=%d gone=%d added=%d | item parent=%s amount=%s"
      % (len(diff), len(gone), len(added), done.get(src_item), t3.amount(src_item)))
print("route state after:", json.dumps(pw.route_state(), ensure_ascii=False)[:200])
