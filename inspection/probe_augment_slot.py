# قراءة فقط: تجهيز أوجمنت من غير ما نكتب — الخانة الصح مسموحة؟
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from backend import pioneer_client as pc, pioneer_tree as pt

acct = sys.argv[1] if len(sys.argv) > 1 else "G22"
specs = json.load(open("data/augments_specs.json", encoding="utf-8"))
ids = {str(a) for aug in specs.get("augments") or [] for a in (aug.get("asset_ids") or [])}

data = pc.fetch_inventory_for(acct)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
nodes = pt.active_containers(tree)
cands = [i for i, row in tree.by_id.items()
         if str(row.get("gameAssetId")) in ids and tree.parent.get(i)]
print("أوجمنت مملوك في المخزن:", [(i, tree.name_of(i), tree.label(tree.parent.get(i) or "")) for i in cands][:6])
if not cands:
    sys.exit("مفيش أوجمنت جاهز للتجهيز في الحساب ده.")

iid = cands[0]
body, dest, moved, _ = pt.plan_move(tree, [iid], "loadout", "augment")
for s in body["steps"]:
    ok = any(pt.in_subtree(tree, s["target"], n) for n in nodes)
    print("خطوة:", tree.name_of(iid), "->", repr(tree.label(s["target"])),
          "| مسموحة في الحارس:", ok)
    assert ok, "الحارس لسه بيرفض خانة الأوجمنت"
print("OK — الخطة بتروح لخانة الأوجمنت الحقيقية والحارس بيقبلها (مفيش كتابة اتبعتت)")
