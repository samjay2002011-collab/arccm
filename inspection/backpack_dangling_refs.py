"""قراءة فقط: هل البوابة بترجع خانات شنطة مملانة بأصناف مش موجودة في نفس الرد؟

الشجرة بتربط الأبناء بشرط `str(child) in by_id` — لو الرد فيه مرجع خانة لصنف
مش مدرّج في نفس الـ payload، الصنف بيختفي من اللوحة والشنطة تبان فاضية.
الفحص ده بيعمل عدّ للمراجع اليتيمة دي وبيطربق أسماء الأصناف اليتيمة كمان.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc          # noqa: E402
from backend import pioneer_tree as pt            # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"
data = pc.fetch_inventory_for(ACCOUNT)
items = (data or {}).get("items") or []
tree = pt.Tree(items)

ids = {str(e["instanceId"]) for e in items if isinstance(e, dict) and e.get("instanceId")}
print("payload entries:", len(items), "unique ids:", len(ids))

dangling = Counter()
for e in items:
    label = tree.label(e["instanceId"]).lower()
    if "backpack" not in label and "loadout" not in label and label not in ("stash", "overflow"):
        continue
    for s in (e.get("slots") or []):
        if str(s) not in ids:
            dangling[tree.label(e["instanceId"])] += 1
print("\ndangling slot refs (child id missing from payload):", json.dumps(dict(dangling), ensure_ascii=False) or "none")

# الأصناف الي مالهاش أب في الرد = مش ظاهرة في أي حاوية
parent = tree.parent
orphans = [str(e["instanceId"]) for e in items
           if str(e["instanceId"]) not in parent and str(e["instanceId"]) not in {str(r) for r in []}]
roots = {str(e["instanceId"]) for e in items if str(e["instanceId"]) not in parent}
named_orphans = [(tree.name_of(i) or tree.label(i)) for i in roots]
print("\ntop-level nodes (no parent):", len(roots))
print("sample labels:", json.dumps(sorted(set(named_orphans))[:25], ensure_ascii=False))

for target in ("Looting Mk. 2 Backpack", "Looting Mk. 3 (Survivor) Backpack"):
    for e in items:
        if tree.label(e["instanceId"]) != target:
            continue
        iid = str(e["instanceId"])
        kids = e.get("slots") or []
        resolved = [k for k in kids if str(k) in ids]
        filled = [k for k in resolved if tree.children(k)]
        print(f"\n{target}: declared cells={len(kids)} resolved={len(resolved)} filled={len(filled)}")
        print("  unresolved cell ids:", json.dumps([str(k)[:8] for k in kids if str(k) not in ids][:30]))
