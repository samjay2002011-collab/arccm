"""قفشة واحدة من مصدر حقيقي في الستاش: أوجمنت -> خانة الأوجمنت الفاضية، ورجوع.

الهدف: نفرّق بين 'البوابة بترفض أي حاجة على الأوجمنت' و'الرفض سببه إن القطعة
عائمة في الأوفر'. كل خطوة كتابة حقيقية وبتترجع لأصلها في نفس التشغيل.
"""
import sys
from backend import store, pioneer_client as pc
from backend import pioneer_tree as pt, pioneer_write as pw

ACC = sys.argv[1] if len(sys.argv) > 1 else "G14"
IID = sys.argv[2] if len(sys.argv) > 2 else "0a8e5c45-86db-4c3a-bedd-278def9766e7"
conn = store.db()


def state(label):
    data = pc.fetch_inventory_for(ACC)
    tree = pt.Tree((data or {}).get("items") or [])
    lay = pt.layout(tree)
    parent = str(tree.parent.get(IID) or "")
    aug = lay.get("augment") or {}
    print("%-12s item parent=%s (%s) | augment cell=%s occupant=%s"
          % (label, parent[:8] or "OVERFLOW", tree.label(parent) if parent else "floating",
             (aug.get("wrapper") or "")[:8], (aug.get("item") or "")[:8]))
    return tree, lay, aug


tree, lay, aug = state("BEFORE")
src_cell = str(tree.parent.get(IID) or "")
if not src_cell:
    print("this probe wants a piece that sits in a real cell")
    sys.exit(0)

out = pw.move_plan(conn, ACC, [{"target_container": "loadout", "target_slot": "augment",
                                "target_wrapper_id": aug.get("wrapper") or "",
                                "instance_ids": [IID]}])
print("EQUIP executed=%s error=%s" % (out.get("executed"), out.get("error")))
if not out.get("executed"):
    print("   ", str(out.get("detail"))[:400])
state("AFTER")

if out.get("executed"):
    back = pw.move_plan(conn, ACC, [{"target_container": "stash",
                                           "target_wrapper_id": src_cell,
                                           "instance_ids": [IID]}])
    print("UNEQUIP/RESTORE executed=%s error=%s %s" % (back.get("executed"), back.get("error"),
                                                       str(back.get("detail"))[:250]))
    state("RESTORED")
