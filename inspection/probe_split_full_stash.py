"""تقسيم ستاك في قسم مليان: الفضلة تنزل الأوفر زي اللعبة، وبعدين دمجها رجوع.

الحركة واحدة على حساب محدد، وكل حاجة بترجع لأصلها في نفس التشغيل:
  ستاك x N في الستاش -> مفصول 1 (عائم) -> الدمج تاني -> N زي ما كانت.
"""
import sys
from backend import store, pioneer_client as pc, pioneer_tree as pt, pioneer_write as pw

ACC = sys.argv[1] if len(sys.argv) > 1 else "G21"
conn = store.db()


def tree_now():
    return pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])


def stacks(tree):
    """ستاكات الستاش اللي كمية her أكتر من 2 وسعتها تسمح بفضلة."""
    lay = pt.layout(tree)
    stash_cells = set(lay["stash"]["slots"])
    out = []
    for iid, row in tree.by_id.items():
        qty = int(row.get("amount") or 0)
        if qty < 3 or tree.children(iid):
            continue
        parent = str(tree.parent.get(iid) or "")
        if parent not in stash_cells:
            continue
        out.append((iid, tree.name_of(iid), qty, parent, parent))
    free = [c for c in lay["stash"]["slots"] if not tree.first_child(c)]
    return out, len(free)


tree = tree_now()
cands, free = stacks(tree)
print("stash free cells=%d | candidate stacks=%d" % (free, len(cands)))
for c in cands[:5]:
    print("   %s | %s x%d | cell %s" % (c[0][:8], c[1][:26], c[2], c[3][:8]))
if not cands:
    sys.exit("nothing to split")

src, name, qty, cell, holder = cands[0]
aid = str((tree.by_id.get(src) or {}).get("gameAssetId"))
total_before = pw._asset_totals(tree).get(aid, 0)
print("\nSPLIT %s (x%d, %d of this type) from cell %s" % (name, qty, total_before, cell[:8]))

out = pw.split_attempt(conn, ACC, src, "", 1)
print("executed=%s error=%s" % (out.get("executed"), out.get("error")))
print("detail:", str(out.get("detail"))[:320])
piece = out.get("created") or ""

tree2 = tree_now()
if piece:
    print("piece %s amount=%s parent=%s" % (piece[:8], (tree2.by_id.get(piece) or {}).get("amount"),
                                            str(tree2.parent.get(piece) or "")[:8] or "FLOATING"))
    back = pw.combine_attempt(conn, ACC, piece, src, 1)
    print("MERGE BACK executed=%s error=%s %s" % (back.get("executed"), back.get("error"),
                                                  str(back.get("detail"))[:220]))
tree3 = tree_now()
print("\nFINAL src amount=%s (was %d) | piece still there=%s | type total=%s (was %d)"
      % (int((tree3.by_id.get(src) or {}).get("amount") or 0), qty, piece in tree3.by_id,
         pw._asset_totals(tree3).get(aid, 0), total_before))
print("parent back to the same cell:", str(tree3.parent.get(src) or "") == cell)
