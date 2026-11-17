"""قراءة فقط: كل وجهات الأوجمنتز المجهّزة — الخطة بتتبني ولا الحارس المحلي بيمانع؟

بنجرّب الأوجمنتز اللي في الأوفر واللي في الستاش على ثلاث وجهات (خانة الأوجمنت،
الشنطة، الستاش) من غير أي إرسال، وبنطبع أوامر البوابة اللي كانت هتتمشي.
"""
import sys
from backend import store
from backend import pioneer_client as pc
from backend import pioneer_tree as pt, pioneer_write as pw

ACC = sys.argv[1] if len(sys.argv) > 1 else "G14"
conn = store.db()
data = pc.fetch_inventory_for(ACC)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
aug_cell = (lay.get("augment") or {}).get("wrapper") or ""
bag = [s["wrapper"] for s in lay["backpack"]["slots"] if s["wrapper"]]
print("account=%s augment cell=%s occupant=%s backpack cells=%d"
      % (ACC, aug_cell[:8], (lay.get("augment") or {}).get("item"), len(bag)))

owned = {str(r["uid"]): (r["name"], r["type"]) for r in
         conn.execute("select uid, name, type from items where account=?", (ACC,))}
augments = [(iid, name) for iid, (name, typ) in owned.items()
            if str(typ or "").lower() == "augment"]

for iid, name in augments:
    parent = str(tree.parent.get(iid) or "")
    where = "OVERFLOW" if not parent else tree.label(parent)
    print("\n== %s (%s) in %s" % (name, iid[:8], where))
    for label, call in (
        ("loadout/augment cell", lambda: pt.plan_move(tree, [iid], "loadout", "augment", aug_cell)),
        ("loadout/augment (no wrapper)", lambda: pt.plan_move(tree, [iid], "loadout", "augment", "")),
        ("backpack cell", lambda: pt.plan_move(tree, [iid], "backpack", "", bag[0] if bag else "")),
        ("backpack (auto)", lambda: pt.plan_move(tree, [iid], "backpack", "", "")),
    ):
        try:
            body, _dest, _moved, _lay = call()
            print("   OK   %-28s ops=%s" % (label, pw.to_parent_ops(body["steps"])))
        except pt.TreeError as exc:
            print("   BLOCK %-27s %s: %s" % (label, exc.error, exc.detail))
