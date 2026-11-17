"""خصاعة مسار batch-operation — ما فيش طلب هنا بينقل حاجة:
إما UUID غلط/صفر، أو setParents للأب اللي القطعة فيه أصلًا (no-op).
"""
import json
import os
import sys
import uuid

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc, pioneer_tree as pt  # noqa: E402

TOKEN = pc.account_token("G18")
URL = pc.BASE + "/v1/pioneer/v1/batch-operation"
HDRS = pc.headers(TOKEN, pc.load_manifest())
ZERO = "00000000-0000-0000-0000-000000000000"


def post(label, body):
    try:
        r = requests.post(URL, headers=HDRS, json=body, timeout=config.HTTP_TIMEOUT)
        print("%-34s -> %s %s" % (label, r.status_code, r.text[:230].replace("\n", " ")))
        return r
    except requests.RequestException as exc:
        print("%-34s -> network %s" % (label, type(exc).__name__))
        return None


print("=== 1. form validation (zero uuids: nothing can resolve) ===")
post("unknown discriminator", {"operations": [{"discriminator": "teleport", "foo": 1}]})
post("moveAmount no amount", {"operations": [{"discriminator": "moveAmount",
                                             "fromInstanceId": ZERO, "toInstanceId": ZERO}]})
post("moveAmount amount 0", {"operations": [{"discriminator": "moveAmount",
                                            "fromInstanceId": ZERO, "toInstanceId": ZERO,
                                            "amount": 0}]})
post("setParents no requestId", {"operations": [{"discriminator": "setParents",
                                                "itemInstanceId": ZERO,
                                                "parentInstanceIds": [ZERO]}]})
post("setParents empty parents", {"operations": [{"discriminator": "setParents",
                                                 "itemInstanceId": ZERO,
                                                 "parentInstanceIds": []}]})
post("2 ops both bad", {"operations": [{"discriminator": "setParents",
                                       "itemInstanceId": ZERO, "parentInstanceIds": [ZERO]},
                                      {"discriminator": "setParents",
                                       "itemInstanceId": ZERO, "parentInstanceIds": [ZERO]}]})
post("wrong field names", {"operations": [{"discriminator": "setParents",
                                          "instanceId": ZERO, "parentIds": [ZERO]}]})
post("well-formed unknown uuid", {"operations": [{"discriminator": "setParents",
                                                 "itemInstanceId": str(uuid.uuid4()),
                                                 "parentInstanceIds": [str(uuid.uuid4())]}]})

print("\n=== 2. real read ===")
data = pc.fetch_inventory_for("G18")
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
cells = [str(c["wrapper"]) if isinstance(c, dict) else str(c) for c in (lay["stash"]["slots"] or [])]
print("stash cells=%d items=%d" % (len(cells), len(tree.items)))

snap = {str(e["instanceId"]): str(e.get("instanceId") and tree.parent.get(str(e["instanceId"])) or "")
        for e in tree.items}

# أرخص خامة في الستاش: قطعة صغيرة مش سلاح
pick = None
for cell in cells:
    item = tree.first_child(cell)
    if not item:
        continue
    nm = (tree.name_of(item) or "").lower()
    if any(k in nm for k in ("rock", "fabric", "plastic", "bolt", "cloth", "bandage", "candy")):
        pick = (cell, item, tree.name_of(item), tree.amount(item))
        break
if not pick:
    for cell in cells:
        item = tree.first_child(cell)
        if item and tree.amount(item) <= 3:
            pick = (cell, item, tree.name_of(item) or "?", tree.amount(item))
            break
print("pick:", pick)

if pick:
    cell, item, name, amt = pick
    print("\n=== 3. no-op writes (parent = the cell it is already in) ===")
    post("setParents same cell", {"operations": [{"discriminator": "setParents",
                                                 "itemInstanceId": item,
                                                 "parentInstanceIds": [cell]}]})
    post("moveAmount 0 own stack", {"operations": [{"discriminator": "moveAmount",
                                                   "fromInstanceId": item,
                                                   "toInstanceId": item, "amount": 0}]})
    post("setParents x2 same", {"operations": [
        {"discriminator": "setParents", "itemInstanceId": item, "parentInstanceIds": [cell]},
        {"discriminator": "setParents", "itemInstanceId": item, "parentInstanceIds": [cell]}]})

    after = pc.fetch_inventory_for("G18")
    tree2 = pt.Tree((after or {}).get("items") or [])
    now = {str(e["instanceId"]): str(tree2.parent.get(str(e["instanceId"])) or "") for e in tree2.items}
    moved = [k for k in snap if k in now and snap[k] != now[k]]
    gone = [k for k in snap if k not in now]
    added = [k for k in now if k not in snap]
    print("diff: moved=%d gone=%d added=%d" % (len(moved), len(gone), len(added)))
    print("our item parent now=%s | was=%s | amount=%s"
          % (now.get(item), snap.get(item), tree2.amount(item)))
    print("names of moved:", [tree2.name_of(k) for k in moved][:8])
