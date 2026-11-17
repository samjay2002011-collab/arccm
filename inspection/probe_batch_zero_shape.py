"""قياس حقول batch-operation بمعرّفات صفرية فقط — مفيش أي قطعة بتتلمس.

RIGHT_FIELDS + ZERO -> INVENTORY_ITEM_NOT_FOUND
غلط/ناقص            -> INVALID_ARGUMENT
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G18"
TOKEN = pc.account_token(ACCOUNT)
URL = pc.BASE + "/v1/pioneer/v1/batch-operation"
HDRS = pc.headers(TOKEN, pc.load_manifest())
ZERO = "00000000-0000-0000-0000-000000000000"


def ask(op):
    try:
        r = requests.post(URL, headers=HDRS, json={"operations": [op]}, timeout=config.HTTP_TIMEOUT)
        try:
            body = r.json()
            return "%s | %s | %s" % (r.status_code, body.get("reason"), str(body.get("message"))[:70])
        except ValueError:
            return "%s | %s" % (r.status_code, r.text[:70])
    except requests.RequestException as exc:
        return "network %s" % type(exc).__name__


CASES = {
    "recycle": [
        {"discriminator": "recycle", "instanceId": ZERO},
        {"discriminator": "recycle", "itemInstanceId": ZERO},
        {"discriminator": "recycle", "instanceIds": [ZERO]},
        {"discriminator": "recycle", "itemInstanceId": ZERO, "amount": 1},
    ],
    "scrap": [
        {"discriminator": "scrap", "instanceId": ZERO, "amount": 1},
        {"discriminator": "scrap", "itemInstanceId": ZERO, "amount": 1},
    ],
    "repair": [
        {"discriminator": "repair", "instanceId": ZERO},
        {"discriminator": "repair", "itemInstanceId": ZERO},
    ],
    "moveAmount": [
        {"discriminator": "moveAmount", "fromInstanceId": ZERO, "toParentInstanceId": ZERO, "amount": 1},
        {"discriminator": "moveAmount", "fromInstanceId": ZERO, "toInstanceId": ZERO, "amount": 1},
        {"discriminator": "moveAmount", "itemInstanceId": ZERO, "toParentInstanceId": ZERO, "amount": 1},
        {"discriminator": "moveAmount", "fromInstanceId": ZERO, "toParentInstanceId": [], "amount": 1},
        {"discriminator": "moveAmount", "fromInstanceId": ZERO, "toParentInstanceId": ZERO, "amount": 0},
    ],
}

print("== batch field probe | account=%s" % ACCOUNT)
for name, variants in CASES.items():
    print("-- %s" % name)
    for v in variants:
        fields = ", ".join("%s=%s" % (k, "[]" if isinstance(val, list) else
                                      ("ZERO" if val == ZERO else val))
                           for k, val in v.items() if k != "discriminator")
        print("   %-62s -> %s" % (fields, ask(v)))
