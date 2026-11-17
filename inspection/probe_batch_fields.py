"""استخراج حقول كل discriminator معروف — كلها بـ UUID صفر فماولّش أي قطعة.

المنطق: RIGHT_FIELDS+ZERO_ID  ->  INVENTORY_ITEM_NOT_FOUND
         غلط/ناقص             ->  INVALID_ARGUMENT أو UNKNOWN
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc  # noqa: E402

TOKEN = pc.account_token("G18")
URL = pc.BASE + "/v1/pioneer/v1/batch-operation"
HDRS = pc.headers(TOKEN, pc.load_manifest())
ZERO = "00000000-0000-0000-0000-000000000000"


def ask(op):
    try:
        r = requests.post(URL, headers=HDRS, json={"operations": [op]}, timeout=config.HTTP_TIMEOUT)
        try:
            reason = r.json().get("reason")
        except ValueError:
            reason = r.text[:60]
        return "%s %s" % (r.status_code, reason)
    except requests.RequestException as exc:
        return "network %s" % type(exc).__name__


CASES = {
    "setParents": [
        {"discriminator": "setParents", "itemInstanceId": ZERO, "parentInstanceIds": [ZERO]},
        {"discriminator": "setParents", "instanceId": ZERO, "parentInstanceIds": [ZERO]},
        {"discriminator": "setParents", "itemInstanceId": ZERO, "slotInstanceIds": [ZERO]},
    ],
    "moveAmount": [
        {"discriminator": "moveAmount", "fromInstanceId": ZERO, "toInstanceId": ZERO, "amount": 1},
        {"discriminator": "moveAmount", "sourceInstanceId": ZERO, "targetInstanceId": ZERO, "amount": 1},
        {"discriminator": "moveAmount", "itemInstanceId": ZERO, "targetInstanceId": ZERO, "amount": 1},
        {"discriminator": "moveAmount", "fromInstanceId": ZERO, "toInstanceId": ZERO, "amount": 1,
         "parentInstanceId": ZERO},
        {"discriminator": "moveAmount", "fromInstanceId": ZERO, "toParentInstanceId": ZERO, "amount": 1},
    ],
    "upgrade": [
        {"discriminator": "upgrade", "instanceId": ZERO},
        {"discriminator": "upgrade", "itemInstanceId": ZERO},
        {"discriminator": "upgrade", "itemInstanceId": ZERO, "level": 1},
        {"discriminator": "upgrade", "itemInstanceId": ZERO, "targetLevel": 1},
    ],
    "recycle": [
        {"discriminator": "recycle", "instanceId": ZERO},
        {"discriminator": "recycle", "itemInstanceId": ZERO},
        {"discriminator": "recycle", "itemInstanceIds": [ZERO]},
    ],
    "scrap": [
        {"discriminator": "scrap", "instanceId": ZERO},
        {"discriminator": "scrap", "itemInstanceId": ZERO},
    ],
    "repair": [
        {"discriminator": "repair", "instanceId": ZERO},
        {"discriminator": "repair", "itemInstanceId": ZERO},
        {"discriminator": "repair", "itemInstanceId": ZERO, "amount": 1},
    ],
}

for name, variants in CASES.items():
    print("== %s" % name)
    for v in variants:
        print("   %-42s -> %s" % (", ".join(k for k in v if k != "discriminator"), ask(v)))

print("\n== multi-op atomicity (1 good-shaped no-op + 1 bad)")
t = pc.fetch_inventory_for("G18")
from backend import pioneer_tree as pt  # noqa: E402
tree = pt.Tree((t or {}).get("items") or [])
lay = pt.layout(tree)
cells = [str(c) for c in lay["stash"]["slots"]]
item = next((tree.first_child(c) for c in cells if "bandage" in (tree.name_of(tree.first_child(c)) or "").lower()), "")
if item:
    mixed = {"operations": [
        {"discriminator": "setParents", "itemInstanceId": item,
         "parentInstanceIds": [str(tree.parent.get(item))]},
        {"discriminator": "setParents", "itemInstanceId": ZERO, "parentInstanceIds": [ZERO]},
    ]}
    r = requests.post(URL, headers=HDRS, json=mixed, timeout=config.HTTP_TIMEOUT)
    print("   mixed batch -> %s %s" % (r.status_code, r.text[:160]))
    after = pt.Tree((pc.fetch_inventory_for("G18") or {}).get("items") or [])
    print("   item parent still %s ? %s" % (tree.parent.get(item),
                                            after.parent.get(item) == tree.parent.get(item)))
