"""قياس لايف: تجهيز أوجمنت من الستاش بيفسّح اللوداوت ولا لأ؟

السؤال الي بيجاوب عليه: لما البوابة بتحط أوجمنت في "Equipped Augment Slot"
  - هل هي بتبني الخانات (شنطة/كويك يوز/سيف بوكيت...) تحته زي اللعبة بالظبط؟
  - هل بتوجّه "Equipped Loadout Container Slot" على شجرته؟
  - ولما يتشيل، الخانات دي بتتمسح ولا بتسيب بقايا بتعلق القطعة؟
الديكت لفّ الأوجمنت على الخانة وبعدين رجّعه خليته الأصلية وقارن الثلاثة قياسات.
  python inspection/probe_augment_equip_shape.py G14
"""
import sys

from backend import pioneer_client as pc
from backend import pioneer_tree as T
from backend import pioneer_write as pw

AUG_PREFIXES = ("Looting", "Combat", "Tactical")


def snap(account):
    data = pc.fetch_inventory_for(account)
    tree = T.Tree((data or {}).get("items") or [])
    lay = T.layout(tree)
    return tree, lay


def shape(tree, lay):
    slot = (lay["augment"] or {}).get("wrapper") or ""
    return {
        "aug_cell": tree.name_of(tree.first_child(slot)) if slot else "-",
        "aug_cell_kids": len(tree.kids.get(slot) or []),
        "eq_slot_child": tree.name_of(lay["loadout"].get("equipped_node")) or "-",
        "mode": lay["loadout"].get("mode"),
        "loadout": tree.name_of(lay["loadout"].get("node")) or "-",
        "backpack_cells": len(lay["backpack"]["slots"]),
    }


def print_shape(tag, tree, lay, extra=""):
    s = shape(tree, lay)
    print("%-10s | cell=%-26s | eq_slot=%-26s | mode=%-8s | shown=%-26s | bag %2d %s"
          % (tag, s["aug_cell"], s["eq_slot_child"], s["mode"], s["loadout"],
             s["backpack_cells"], extra))


def candidates(tree, lay):
    for cell in (lay["stash"]["slots"] or []):
        item = tree.first_child(cell)
        nm = tree.name_of(item) or "" if item else ""
        if item and any(nm.startswith(p) for p in AUG_PREFIXES) \
                and "Loadout" not in nm and "Free" not in nm and not (tree.kids.get(item) or []):
            yield item, cell, nm


def set_parent(token, item, parents):
    body = {"mutations": [{"discriminator": "setParents", "itemInstanceId": item,
                           "parentInstanceIds": list(parents)}], "requestId": ""}
    try:
        pw.post_mutate(body, token)
        return "OK"
    except Exception as exc:
        return str(exc)[:180]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G14"
    tree, lay = snap(account)
    slot = (lay["augment"] or {}).get("wrapper") or ""
    cands = list(candidates(tree, lay))
    print("%s | augment cell %s" % (account, slot[:8] or "-"))
    if not slot or not cands:
        print("MISSING — need the augment cell and one clean stashed augment.")
        return
    item, cell, name = cands[0]
    kids_before = len(tree.kids.get(item) or [])
    print("X=%s (%s) | kids %d" % (name, item[:8], kids_before))
    if pw.paused():
        print("WRITES PAUSED — probe aborted.")
        return
    token = pc.account_token(account)
    print_shape("before", tree, lay)

    print("\nequip -> %s" % set_parent(token, item, [slot]))
    tree2, lay2 = snap(account)
    print_shape("equipped", tree2, lay2, "| X kids %d" % len(tree2.kids.get(item) or []))
    print("   X now @ %s" % (tree2.name_of(tree2.parent.get(item) or "") or "FLOATING"))

    print("\nunequip back -> %s" % set_parent(token, item, [cell]))
    tree3, lay3 = snap(account)
    print_shape("restored", tree3, lay3, "| X kids %d" % len(tree3.kids.get(item) or []))
    print("\nSTATE RESTORED: %s (kids %d -> %d)"
          % (tree3.parent.get(item) == cell, kids_before, len(tree3.kids.get(item) or [])))


if __name__ == "__main__":
    main()
