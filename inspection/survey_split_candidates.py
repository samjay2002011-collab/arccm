"""قراية نصفة للشجرة الحية: الخانات الفاضية + الرص المرشّحة لاختبار moveAmount.

مفيش أي كتابة هنا — بس GET /v1/pioneer/inventory.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc, pioneer_tree as pt, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G18"
print("route:", pw.route_state())
data = pc.fetch_inventory_for(ACCOUNT) or {}
tree = pt.Tree(data.get("items") or [])
lay = pt.layout(tree)
print("nodes=%d account=%s" % (len(tree.by_id), ACCOUNT))
for name in ("stash", "backpack", "overflow"):
    block = lay.get(name) or {}
    slots = [str(s) for s in (block.get("slots") or [])]
    empty = [s for s in slots if not tree.first_child(s)]
    print("  %-9s slots=%d empty=%d" % (name, len(slots), len(empty)))

# الرص: عنصر مش حاوية، كميته >= 2، ومعه أب حقيقي (مش عائم في الأوفر)
cands = []
for iid, node in tree.by_id.items():
    if node.get("slots"):
        continue
    qty = int(node.get("amount") or 0)
    if qty < 2:
        continue
    parent = str(tree.parent.get(iid) or "")
    cands.append((qty, iid, tree.name_of(iid), str(node.get("gameAssetId")), parent,
                  tree.label(parent)))
cands.sort(key=lambda r: -r[0])
print("  stacks>=2: %d" % len(cands))
for row in cands[:12]:
    qty, iid, name, aid, parent, plabel = row
    grand = str(tree.parent.get(parent) or "")
    print("     %-34s qty=%-4d asset=%-12s parent=%s(%s) grandparent=%s" %
          (name, qty, aid, str(parent)[:8], plabel, tree.label(grand)))
