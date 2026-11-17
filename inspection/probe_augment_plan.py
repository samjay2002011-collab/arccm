"""قراءة فقط: هل خطة تجهيز أوجمنت في خانة مشغولة بقت ممكنة من غير ما تتBLOCK؟

بيطبع الأوجمنت المجهّز + الأوجمنتز اللي في الستاش + أوامر البوابة اللي الخطة
هايبعتها — من غير أي كتابة.
"""
import sys
from backend import store
from backend import pioneer_client as pc
from backend import pioneer_tree as pt, pioneer_write as pw

ACC = sys.argv[1] if len(sys.argv) > 1 else "G21"
conn = store.db()
token = pc.account_token(ACC)
print("account=%s token=%s route=%s" % (ACC, bool(token), pw._endpoint()))

data = pc.fetch_inventory_for(ACC)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
aug = lay.get("augment") or {}
print("augment cell=%s occupant=%s (%s)" % (aug.get("wrapper"), aug.get("item"),
                                            tree.name_of(aug.get("item") or "")))
print("loadout keys=%s" % sorted(lay["loadout"]["slots"]))

owned = {str(r["uid"]): (r["name"], r["type"]) for r in
         conn.execute("select uid, name, type from items where account=?", (ACC,))}
cand = []
for iid, (name, typ) in owned.items():
    if str(typ or "").lower() != "augment":
        continue
    parent = str(tree.parent.get(iid) or "")
    where = "OVERFLOW" if not parent else tree.label(parent)
    cand.append((iid, name, int(tree.amount(iid)), where))
print("\naugments known: %d" % len(cand))
for c in cand[:30]:
    print("  %s | %s x%s | in %s" % (c[0][:8], c[1], c[2], c[3]))

stash_cells = lay["stash"]["slots"]
occupied = sum(1 for w in stash_cells if tree.first_child(w))
print("\nstash cells=%d occupied=%d free=%d" % (len(stash_cells), occupied,
                                                len(stash_cells) - occupied))

for iid, name, amount, where in cand:
    if where.upper() == "OVERFLOW":
        continue
    try:
        body, dest, moved, _ = pt.plan_move(tree, [iid], "loadout", "augment",
                                            aug.get("wrapper") or "")
    except pt.TreeError as exc:
        print("\nPLAN %s -> augment cell BLOCKED locally: %s %s" % (name, exc.error, exc.detail))
        continue
    print("\nPLAN %s -> augment cell OK: steps=%s ops=%s"
          % (name, body["steps"], pw.to_parent_ops(body["steps"])))
    break
