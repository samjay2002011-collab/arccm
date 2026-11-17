"""اختبار لايف بحجم حركة واحدة + إرجاع الحالة بالحرف.

بنفس gesture بتاعه: بلاطة أوجمنت عائمة في الأوفر -> خانة في الشنطة / خانة الأوجمنت.
أي كتابة بتنجح بترجع لأصلها في نفس التشغيل، والرسالة الحرفية للبوابة بتطبع.
"""
import json
import sys
from backend import store
from backend import pioneer_client as pc
from backend import pioneer_tree as pt, pioneer_write as pw

ACC = sys.argv[1] if len(sys.argv) > 1 else "G14"
TARGET = sys.argv[2] if len(sys.argv) > 2 else "backpack"   # backpack | augment
IID = sys.argv[3] if len(sys.argv) > 3 else "cdd09c3e-589f-4ea7-a243-5e478495b667"

conn = store.db()
print("pause block:", pw._pause_block())


def snapshot(label):
    data = pc.fetch_inventory_for(ACC)
    tree = pt.Tree((data or {}).get("items") or [])
    lay = pt.layout(tree)
    parent = str(tree.parent.get(IID) or "")
    aug = lay.get("augment") or {}
    print("%-10s item parent=%r (%s) | augment cell=%s occupant=%s | stash free=%d | bag free=%d"
          % (label, parent, tree.label(parent) if parent else "OVERFLOW",
             (aug.get("wrapper") or "")[:8], (aug.get("item") or "")[:8],
             sum(1 for w in lay["stash"]["slots"] if not tree.first_child(w)),
             sum(1 for s in lay["backpack"]["slots"] if s["wrapper"] and not tree.first_child(s["wrapper"]))))
    return tree, lay


tree, lay = snapshot("BEFORE")
orig_parent = str(tree.parent.get(IID) or "")
if TARGET == "backpack":
    cells = [s["wrapper"] for s in lay["backpack"]["slots"] if s["wrapper"] and not tree.first_child(s["wrapper"])]
    move = {"target_container": "backpack", "target_wrapper_id": cells[0], "instance_ids": [IID]}
else:
    move = {"target_container": "loadout", "target_slot": "augment",
            "target_wrapper_id": lay["augment"]["wrapper"], "instance_ids": [IID]}
print("sending:", json.dumps(move))

out = pw.move_plan(conn, ACC, [move])
print("executed=%s error=%s" % (out.get("executed"), out.get("error")))
print("detail:", str(out.get("detail"))[:400])

tree2, lay2 = snapshot("AFTER")
if out.get("executed"):
    undo_parent = orig_parent
    undo = {"target_container": "overflow" if not undo_parent else "stash",
            "target_wrapper_id": "" if not undo_parent else undo_parent,
            "instance_ids": [IID]}
    if undo["target_container"] == "stash":
        # الخانة الأصلية محددة: رجّعها لنفس الخانة بالضبط
        undo["target_wrapper_id"] = undo_parent
    back = pw.move_plan(conn, ACC, [undo])
    print("restore executed=%s error=%s detail=%s" % (back.get("executed"), back.get("error"),
                                                      str(back.get("detail"))[:250]))
    snapshot("RESTORED")
