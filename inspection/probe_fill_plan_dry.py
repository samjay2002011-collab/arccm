"""dry-run لخطة fill (confirmed=False): مفيش أي كتابة، بنشوف الخطة والرفض."""
import sys, json
from backend import config, store, actions, pioneer_client as pc, pioneer_tree as pt

acc, pat, want = sys.argv[1], " ".join(sys.argv[2:3]), int(sys.argv[3])
data = pc.fetch_inventory_for(acc) or {}
tree = pt.Tree((data or {}).get("items") or [])
aid = ""
for iid, node in tree.by_id.items():
    if node.get("slots"):
        continue
    if pat.lower() in (tree.name_of(iid) or "").lower():
        aid = str(node.get("gameAssetId"))
        break
print("account", acc, "asset", aid, "name", tree.name_of(next((i for i in tree.by_id if str(tree.by_id[i].get("gameAssetId")) == aid), "")))
lay = pt.layout(tree)
stash_cells = set(lay["stash"]["slots"])
free = [c for c in lay["stash"]["slots"] if not tree.first_child(c)]
print("stash filled %d/%d | free cells %d" % (len(stash_cells) - len(free), len(stash_cells), len(free)))
bp = lay["backpack"]["slots"]
print("backpack cells %d | filled %d" % (len(bp), sum(1 for s in bp if s.get("item"))))
conn = store.db()
out = actions.fill(conn, acc, aid, want, target_wrapper="", confirmed=False)
print(json.dumps({k: v for k, v in out.items() if k != "refreshed"}, ensure_ascii=False, indent=1)[:2000])
