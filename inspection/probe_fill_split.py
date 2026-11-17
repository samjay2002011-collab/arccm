"""قراية بس (من غير أي كتابة): رصّات نوع محدد في الشجرة الحية وأبوها الحقيقي.

السبب: رسالة "floating in the overflow stash" طلعت لحساب الأوفر فيه فاضي،
فسالمصدر اللي اتفصل منه مفاده أبه مش في خانات الستاش — بنطبع السلسلة الكاملة.
"""
import sys
from backend import pioneer_client as pc, pioneer_tree as pt

ACC = sys.argv[1] if len(sys.argv) > 1 else "G14"
QUERY = " ".join(sys.argv[2:]) or "heavy fireworks"

data = pc.fetch_inventory_for(ACC) or {}
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
stash_cells = set(lay["stash"]["slots"])
bp = lay.get("backpack") or {}

want = QUERY.strip().lower()
hits = {}
for iid, node in tree.by_id.items():
    if node.get("slots"):
        continue
    nm = (tree.name_of(iid) or "").strip().lower()
    if want not in nm:
        continue
    aid = str(node.get("gameAssetId") or "")
    hits.setdefault(aid, []).append(iid)

print("account", ACC, "| roots", len(tree.roots()),
      "| stash cells", len(stash_cells),
      "| backpack cells", len(bp.get("slots") or {}))
for aid, ids in hits.items():
    tot = sum(int(tree.by_id[i].get("amount") or 0) for i in ids)
    print("\nasset", aid, "name", tree.name_of(ids[0]), "| stacks", len(ids), "| total", tot)
    for iid in sorted(ids, key=lambda i: -int(tree.by_id[i].get("amount") or 0)):
        node = tree.by_id[iid]
        par = str(tree.parent.get(iid) or "")
        chain = []
        cur = par
        while cur and cur in tree.by_id:
            chain.append("%s[%s]" % ((tree.label(cur) or "?")[:26],
                                      "cell" if cur in stash_cells else "other"))
            cur = str(tree.parent.get(cur) or "")
        amt = int(node.get("amount") or 0)
        print("  %-6s in_stash_cells=%-5s par=%-5s chain=%s" %
              (str(amt), par in stash_cells, bool(par), " < ".join(chain) or "NO PARENT (root)"))
    floating = [i for i in ids if not tree.parent.get(i)]
    print("  stacks with NO parent:", len(floating))
    in_stash = [i for i in ids if tree.parent.get(i) in stash_cells]
    print("  stacks in a stash cell:", len(in_stash))
    outside = [i for i in ids if tree.parent.get(i) and tree.parent.get(i) not in stash_cells]
    print("  stacks elsewhere:", len(outside))
    for i in outside[:5]:
        print("    ", (tree.name_of(i) or "")[:20], "par:", tree.label(str(tree.parent.get(i))),
              "<", tree.label(str(tree.parent.get(str(tree.parent.get(i)) or ""))))
