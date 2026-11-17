"""تحقق لايف لخطة الكمية (fill) على G21: QTY 10 = 3+3+3+1*، والمصدر عائم فالستاش مليان.

المطلوب: الشنطة تستلم 10 بالظبط (مش 9). بنصوّر الحالة قبل، بننفّذ، بنقارن،
وبنرجّع كل قطعة لمكانها بالضبط (تحميل للأوفر + دمج القطعة المفصول في مصدرها).
"""
import sys
from backend import store, actions, pioneer_client as pc, pioneer_tree as pt

ACC, AID, WANT = "G21", "787027311", 10


def snap():
    data = pc.fetch_inventory_for(ACC) or {}
    tree = pt.Tree((data or {}).get("items") or [])
    lay = pt.layout(tree)
    stash_cells = set(lay["stash"]["slots"])
    stacks = {}
    for iid, node in tree.by_id.items():
        if node.get("slots") or str(node.get("gameAssetId")) != AID:
            continue
        par = str(tree.parent.get(iid) or "")
        where = ("float" if not par else "stash" if par in stash_cells else
                 "backpack" if par in {s["wrapper"] for s in lay["backpack"]["slots"]} else "other:" + par[:8])
        stacks[iid] = (int(node.get("amount") or 0), where, par)
    return stacks, len([c for c in lay["stash"]["slots"] if not tree.first_child(c)])


before, free_before = snap()
print("BEFORE stacks %d total %d | free stash cells %d | in backpack %d | floating %d"
      % (len(before), sum(v[0] for v in before.values()), free_before,
         sum(v[0] for v in before.values() if v[1] == "backpack"),
         sum(v[0] for v in before.values() if v[1] == "float")))

conn = store.db()
out = actions.fill(conn, ACC, AID, WANT, confirmed=True)
print("\nFILL executed=%s delivered=%s error=%s" % (out.get("executed"), out.get("delivered"), out.get("error")))
print("detail:", (out.get("detail") or "")[:400])
for st in out.get("steps") or []:
    print("  step", st)

after, free_after = snap()
print("\nAFTER stacks %d total %d | in backpack %d | floating %d"
      % (len(after), sum(v[0] for v in after.values()),
         sum(v[0] for v in after.values() if v[1] == "backpack"),
         sum(v[0] for v in after.values() if v[1] == "float")))

moved_backpack = sorted(i for i, v in after.items() if v[1] == "backpack" and before.get(i, (0, "x"))[1] != "backpack")
print("newly in backpack:", [(i[:8], after[i][0]) for i in moved_backpack],
      "| sum", sum(after[i][0] for i in moved_backpack))

# ---- الارجاع بالظبط ----
if moved_backpack:
    back = actions.move(conn, ACC, "overflow", [{"instance_id": i} for i in moved_backpack])
    print("\nRESTORE move->overflow executed=%s detail=%s" % (back.get("executed"), (back.get("detail") or "")[:200]))

restored = snap()[0]
split_piece = [i for i in restored if i not in before]
for pid in split_piece:
    src = [i for i in before if before[i][1] == "float" and restored.get(i, (0, ""))[0] < before[i][0]]
    if not src:
        continue
    tgt = min(src, key=lambda i: restored[i][0])
    c = actions.combine(conn, ACC, pid, tgt, confirmed=True)
    print("RESTORE combine %s -> %s executed=%s detail=%s"
          % (pid[:8], tgt[:8], c.get("executed"), (c.get("detail") or "")[:160]))

final = snap()[0]
same_ids = set(final) == set(before)
same_state = all(final.get(i) == before[i] for i in before) and same_ids
print("\nRESTORED IDENTICAL:", same_state, "| extra", sorted(set(final) - set(before)),
      "| missing", sorted(set(before) - set(final)))
if not same_state:
    for i in sorted(set(before) | set(final)):
        if before.get(i) != final.get(i):
            print("   DIFF", i[:8], "was", before.get(i), "now", final.get(i))
