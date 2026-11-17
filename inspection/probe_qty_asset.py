"""قراية بس: فين رصّات نوع معين في الشجرة الحية (ستاش/عائم) وبأي كميات.

الرسالة الي طابعت على الشاشة بتقول المصدر عائم في الأوفر واللوحة مافيهاش حاجة،
فنبنشغي الرصّات كلها ونشوف أبوها الحقيقي وكم amount كل واحدة.
"""
import sys
from backend import pioneer_client as pc, pioneer_tree as pt

acc = sys.argv[1]
pat = " ".join(sys.argv[2:]).lower()

data = pc.fetch_inventory_for(acc) or {}
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
stash_cells = set(lay["stash"]["slots"])
print("%s | nodes %d | roots %d | stash cells %d | stash filled %d"
      % (acc, len(tree.by_id), len(tree.roots()), len(stash_cells),
         sum(1 for c in stash_cells if tree.first_child(c))))
seen = {}
for iid, node in tree.by_id.items():
    if node.get("slots"):
        continue
    nm = (tree.name_of(iid) or "")
    if pat and pat not in nm.lower():
        continue
    aid = str(node.get("gameAssetId") or "")
    par = str(tree.parent.get(iid) or "")
    seen.setdefault(aid, []).append((iid, int(node.get("amount") or 0), par,
                                     nm, bool(node.get("durability"))))
for aid, rows in seen.items():
    tot = sum(r[1] for r in rows)
    print("\nasset %s | %s | stacks %d | total %d" % (aid, rows[0][3], len(rows), tot))
    for iid, amt, par, nm, _d in sorted(rows, key=lambda r: -r[1]):
        where = ("stash cell" if par in stash_cells else
                 ("FLOATING (no parent)" if not par else "inside " + (tree.label(par) or par[:8])))
        print("   amount=%-5s %-20s cell=%s" % (amt, where, par[:8] or "-"))
