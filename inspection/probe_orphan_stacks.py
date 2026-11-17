"""قراية بس: الرصّات الي مالهاش أب في الشجرة الحية = اللي الباكند بيشيلها كأوفر.

بنقارنها بالأقسام الي الموقع بيعرضها فعلاً (pioneer_tree.layout) عشان نعرف
الرسالة "floating in the overflow" كانت صح ولا على قطعة بتبان في الستاش.
"""
import sys
from backend import pioneer_client as pc, pioneer_tree as pt

for acc in (sys.argv[1:] or ["G14", "G22", "G21", "G18"]):
    try:
        data = pc.fetch_inventory_for(acc) or {}
    except Exception as exc:
        print(acc, "FETCH FAIL", type(exc).__name__, str(exc)[:120]); continue
    tree = pt.Tree((data or {}).get("items") or [])
    lay = pt.layout(tree)
    stash_cells = set(lay["stash"]["slots"])
    over_keys = set((lay.get("overflow") or {}).get("slots") or {})
    orphans = [iid for iid, n in tree.by_id.items()
               if not n.get("slots") and not tree.parent.get(iid)
               and int(n.get("amount") or 0) > 0]
    print("\n=== %s | nodes %d | roots %d | stash cells %d | orphan stacks %d"
          % (acc, len(tree.by_id), len(tree.roots()), len(stash_cells), len(orphans)))
    named = {}
    for iid in orphans:
        named.setdefault((tree.name_of(iid) or "?")[:30], []).append(int(tree.by_id[iid].get("amount") or 0))
    for nm, amts in sorted(named.items(), key=lambda kv: -sum(kv[1]))[:12]:
        print("   %-30s stacks=%-4d amounts=%s" % (nm, len(amts), sorted(amts, reverse=True)[:8]))
    in_stash_cells = [iid for iid in orphans if iid in stash_cells]
    print("   orphans that ARE stash cells:", len(in_stash_cells))
    big = [i for i in orphans if int(tree.by_id[i].get("amount") or 0) >= 3]
    print("   orphan stacks with amount>=3:", len(big))
    print("   overflow section shown:", len(over_keys), "labels:",
          [tree.label(k)[:24] for k in list(over_keys)[:6]])
