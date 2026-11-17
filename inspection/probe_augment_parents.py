"""قياس لايف: أينا أب بتقبله البوابة لأوجمنت، وشرط مكان الأوجمنت نفسه.

الفرضية: الرفض ماحدّوش على الخانة — الرفض على إن القطعة كانت سايبة في الأوفر ستاش.
اللعبة بتجهّز الأوجمنت من الستاش، فأول تجربة بتاخد أوجمنت موجود فعلاً في خلية
ستاش وبتجرّب عليه الأبواب المرشحة واحد ورا التاني، وبعدين ترجّعه خليته الأصلية.

  python inspection/probe_augment_parents.py G14
"""
import sys

from backend import pioneer_client as pc
from backend import pioneer_tree as T
from backend import pioneer_write as pw

AUG_NAMES = ("Looting", "Combat", "Tactical", "Medic")


def build(account):
    data = pc.fetch_inventory_for(account)
    tree = T.Tree((data or {}).get("items") or [])
    T.layout(tree)
    return tree


def label(tree, iid):
    if not iid:
        return "-"
    parent = tree.parent.get(iid)
    return "%s @ %s" % (tree.name_of(iid) or iid[:8],
                        (tree.name_of(parent) or "?") if parent else "FLOATING")


def find_stashed_augment(tree):
    lay = T.layout(tree)
    for cell in (lay["stash"]["slots"] or []):
        item = tree.first_child(cell)
        if not item:
            continue
        nm = tree.name_of(item) or ""
        if any(nm.startswith(p) for p in AUG_NAMES) and "Loadout" not in nm:
            return item, cell
    return "", ""


def candidates(tree):
    inv = next(r for r in tree.roots() if tree.label(r).strip().lower() == "inventory root")
    out = []
    aug_slot = tree.find_descendant(inv, "equipped augment slot")
    if aug_slot:
        out.append(("Equipped Augment Slot", aug_slot))
        out.append(("Equipped Augment Container", tree.parent.get(aug_slot) or ""))
        out.append(("Equipped Augment Container Slot", tree.parent.get(tree.parent.get(aug_slot) or "") or ""))
    eq_slot = tree.find_child(inv, "equipped loadout container slot")
    if eq_slot:
        out.append(("Equipped Loadout Container Slot", eq_slot))
    lay = T.layout(tree)
    for slot in lay["backpack"]["slots"]:
        if not slot.get("item"):
            out.append(("BACKPACK (empty cell)", slot["wrapper"]))
            break
    for group in (lay["loadout"]["slots"] or {}).values():
        for slot in group:
            if not slot.get("item") and slot.get("wrapper") != aug_slot:
                out.append(("LOADOUT cell %s" % (tree.name_of(slot["wrapper"]) or "?"), slot["wrapper"]))
                break
    return [(n, p) for n, p in out if p]


def set_parent(token, item, parent):
    body = {"mutations": [{"discriminator": "setParents", "itemInstanceId": item,
                           "parentInstanceIds": [parent]}], "requestId": ""}
    try:
        return {"ok": True, "resp": pw.post_mutate(body, token)}
    except Exception as exc:
        return {"ok": False, "literal": str(exc)[:300]}


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G14"
    tree = build(account)
    item, home_cell = find_stashed_augment(tree)
    print("account %s | stashed augment: %s (cell %s)" % (account, label(tree, item), home_cell[:8] or "-"))
    if not item:
        print("MISSING — need one augment sitting in a stash cell.")
        return
    if pw.paused():
        print("WRITES PAUSED — probe aborted.")
        return
    token = pc.account_token(account)
    moved = False
    for name, parent in candidates(tree):
        res = set_parent(token, item, parent)
        after = build(account)
        where = label(after, item)
        print("\n-> %-32s %s" % (name, "OK" if res["ok"] else res["literal"]))
        print("   item now: %s" % where)
        if res["ok"]:
            moved = True
            back = set_parent(token, item, home_cell)
            done = build(account)
            print("   restore -> stash cell: %s | now %s"
                  % ("OK" if back["ok"] else back["literal"], label(done, item)))
    if not moved:
        print("\nno parent accepted a stashed augment.")
    final = build(account)
    ok = final.parent.get(item) == home_cell
    print("\nSTATE RESTORED: %s | %s" % (ok, label(final, item)))


if __name__ == "__main__":
    main()
