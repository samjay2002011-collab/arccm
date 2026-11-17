"""تبديل أوجمنت فوق تاني مجهّز: أمر واحد والخانة بتطرد القديمة لخانتها، ورجوع.

الترتيب:
  1) مجهّس أوجمنت من مكانه في الستاش (الفضة فاضية).
  2) مجهّس تاني فوقه — المفروض المطرود يرجع لخانتة نفسها من غير طلب إضافي.
  3) إرجاع الحالة بالأصل: المطرود في خانته، والمجهّز التاني في خانة نفسه.
"""
import sys
from backend import store, pioneer_client as pc, pioneer_tree as pt, pioneer_write as pw

ACC = sys.argv[1] if len(sys.argv) > 1 else "G14"
A = "0a8e5c45-86db-4c3a-bedd-278def9766e7"   # Looting Mk. 2
B = "bca2e36e-95d2-4bec-ad10-a1528d1d976e"   # Combat Mk. 3 (Aggressive)
conn = store.db()


def snap(tag):
    tree = pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])
    lay = pt.layout(tree)
    aug = lay.get("augment") or {}
    info = {}
    for iid in (A, B):
        p = str(tree.parent.get(iid) or "")
        info[iid[:8]] = (tree.name_of(iid)[:20], p[:8] or "FLOATING")
    print("%-8s augment cell=%s occupant=%s | %s" % (tag, (aug.get("wrapper") or "")[:8],
                                                     (aug.get("item") or "")[:8] or "empty", info))
    return tree, lay


tree, lay = snap("BEFORE")
home_a = str(tree.parent.get(A) or "")
home_b = str(tree.parent.get(B) or "")
cell = (lay.get("augment") or {}).get("wrapper") or ""
if tree.first_child(cell) or not home_a or not home_b:
    print("the two pieces need real cells and an empty augment cell to start")
    sys.exit(0)


def equip(iid, tag):
    out = pw.move_plan(conn, ACC, [{"target_container": "loadout", "target_slot": "augment",
                                    "target_wrapper_id": cell, "instance_ids": [iid]}])
    print("%s executed=%s error=%s %s" % (tag, out.get("executed"), out.get("error"),
                                          str(out.get("detail"))[:220]))
    return out


r1 = equip(A, "EQUIP A  ")
snap("after A")
if r1.get("executed"):
    r2 = equip(B, "SWAP IN B")
    after = snap("after B ")
    # الإرجاع: اللي اتطرد يرجع لخانتة، والمجهّز بيتنقل لخانتة هو
    displaced = after[0].first_child(cell)
    if str(after[0].parent.get(A) or "") == home_a:
        print("A auto-returned to its own cell:", home_a[:8])
    back = pw.move_plan(conn, ACC, [{"target_container": "stash", "target_wrapper_id": home_b,
                                     "instance_ids": [B]}])
    print("RESTORE B executed=%s error=%s %s" % (back.get("executed"), back.get("error"),
                                                 str(back.get("detail"))[:200]))
    final = snap("FINAL")
    print("EXACT RESTORE:", str(final[0].parent.get(A) or "") == home_a
          and str(final[0].parent.get(B) or "") == home_b
          and not final[0].first_child(cell))
