"""تقسيم المشكلة لحركة-حركة: أي قفشة في المسار بيرفضها البوابة؟

الخطوات: أوفر (عائمة) -> ستاش -> شنطة -> أوفر. كل خطوة كتابة حقيقية، واللي
بتنجح بترجع لأصلها على طول. الهدف: نعرف الرفض من الأوفر ولا من الخانة.
"""
import sys
from backend import store, pioneer_client as pc
from backend import pioneer_tree as pt, pioneer_write as pw

ACC = sys.argv[1] if len(sys.argv) > 1 else "G14"
IID = sys.argv[2] if len(sys.argv) > 2 else "cdd09c3e-589f-4ea7-a243-5e478495b667"
conn = store.db()


def state(label):
    data = pc.fetch_inventory_for(ACC)
    tree = pt.Tree((data or {}).get("items") or [])
    lay = pt.layout(tree)
    parent = str(tree.parent.get(IID) or "")
    print("%-14s parent=%s (%s) | item still owned=%s" % (label, parent[:8] or "OVERFLOW",
                                                           tree.label(parent) if parent else "floating",
                                                           IID in tree.by_id))
    return tree, lay


def step(label, move):
    out = pw.move_plan(conn, ACC, [move])
    print("\n%s -> executed=%s error=%s" % (label, out.get("executed"), out.get("error")))
    if not out.get("executed"):
        print("   ", str(out.get("detail"))[:300])
    return out


tree, lay = state("START")
if str(tree.parent.get(IID) or ""):
    print("the item is not floating — this probe only makes sense for an overflow piece")
    sys.exit(0)

free_stash = next((w for w in lay["stash"]["slots"] if not tree.first_child(w)), "")
free_bag = next((s["wrapper"] for s in lay["backpack"]["slots"]
                 if s["wrapper"] and not tree.first_child(s["wrapper"])), "")
aug_cell = (lay.get("augment") or {}).get("wrapper") or ""
print("chosen free stash cell=%s free bag cell=%s augment cell=%s"
      % (free_stash[:8], (free_bag or "")[:8], aug_cell[:8]))

r1 = step("OVERFLOW->STASH", {"target_container": "stash", "target_wrapper_id": free_stash,
                              "instance_ids": [IID]})
if r1.get("executed"):
    state("after stash")
    r2 = step("STASH->BACKPACK", {"target_container": "backpack", "target_wrapper_id": free_bag,
                                  "instance_ids": [IID]})
    if r2.get("executed"):
        state("after backpack")
        step("BACKPACK->OVERFLOW (restore)", {"target_container": "overflow", "instance_ids": [IID]})
    else:
        step("STASH cell -> OVERFLOW (restore)", {"target_container": "overflow", "instance_ids": [IID]})
    state("RESTORED")
else:
    state("unchanged")
