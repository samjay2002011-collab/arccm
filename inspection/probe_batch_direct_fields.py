"""حقول recycle/scrap/repair/upgrade على batch-operation — بـ UUID صفر كلها.

INVALID_ARGUMENT = الحقول ناقصة/غلط.  INVENTORY_ITEM_NOT_FOUND = الحقول مقبولة
والبوابة روحت تدور على القطعة (فالشكل صح).
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc  # noqa: E402

TOKEN = pc.account_token("G18")
URL = pc.BASE + "/v1/pioneer/v1/batch-operation"
HDRS = pc.headers(TOKEN, pc.load_manifest())
Z = "00000000-0000-0000-0000-000000000000"
Z2 = "11111111-1111-1111-1111-111111111111"


def ask(op, tag=""):
    try:
        r = requests.post(URL, headers=HDRS, json={"operations": [op]}, timeout=config.HTTP_TIMEOUT)
        try:
            reason = "%s %s" % (r.status_code, r.json().get("reason"))
        except ValueError:
            reason = "%s %s" % (r.status_code, r.text[:50])
        print("   %-52s -> %s %s" % (tag or ", ".join(sorted(k for k in op if k != "discriminator")),
                                     reason, ""))
    except requests.RequestException as exc:
        print("   %-52s -> network %s" % (tag, type(exc).__name__))


for kind in ("recycle", "scrap", "repair", "upgrade"):
    print("== %s" % kind)
    ask({"discriminator": kind, "instanceId": Z})
    ask({"discriminator": kind, "itemInstanceId": Z})
    ask({"discriminator": kind, "instanceIds": [Z]})
    ask({"discriminator": kind, "itemInstanceIds": [Z]})
    ask({"discriminator": kind, "instanceId": Z, "amount": 1})
    ask({"discriminator": kind, "itemInstanceId": Z, "amount": 1})
    ask({"discriminator": kind, "itemInstanceId": Z, "quantity": 1})
    ask({"discriminator": kind, "itemInstanceId": Z, "materials": []})
    ask({"discriminator": kind, "itemInstanceId": Z, "level": 1})
    ask({"discriminator": kind, "itemInstanceId": Z, "targetLevel": 1})
    ask({"discriminator": kind, "itemInstanceId": Z, "gameAssetId": 1440007245})
    ask({"discriminator": kind, "operations": [{"discriminator": kind, "instanceId": Z}]})
    print()

print("== moveAmount حقول إضافية")
ask({"discriminator": "moveAmount", "fromInstanceId": Z, "toParentInstanceId": Z, "amount": 1})
ask({"discriminator": "moveAmount", "fromInstanceId": Z, "toParentInstanceId": Z,
     "toInstanceId": Z2, "amount": 1}, "toInstanceId+toParentInstanceId")
ask({"discriminator": "moveAmount", "itemInstanceId": Z, "toParentInstanceId": Z,
     "amount": 1}, "itemInstanceId variant")
