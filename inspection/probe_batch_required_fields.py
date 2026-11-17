"""أي حقول بتتقبل فعلاً على batch-operation — كل المعرّفات صفرية، فمفيش قطعة هتتلمس.

المنطق: الحقل المطلوب موجود + معرّف مش موجود -> 404 NOT_FOUND
        حقل ناقص / زيادة مرفوضة               -> 400 INVALID_ARGUMENT
"""
import json
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
BOGUS = "deadc0de-0000-4000-8000-000000000000"


def ask(op):
    r = requests.post(URL, headers=HDRS, json={"operations": [op]}, timeout=config.HTTP_TIMEOUT)
    try:
        body = r.json()
        return "%s %s" % (r.status_code, body.get("reason"))
    except ValueError:
        return "%s %s" % (r.status_code, r.text[:60])


CASES = [
    ("recycle bare (no id)", {"discriminator": "recycle"}),
    ("recycle instanceId", {"discriminator": "recycle", "instanceId": ZERO}),
    ("recycle itemInstanceId", {"discriminator": "recycle", "itemInstanceId": ZERO}),
    ("recycle instanceIds[]", {"discriminator": "recycle", "instanceIds": [ZERO]}),
    ("recycle itemIds[]", {"discriminator": "recycle", "itemIds": [ZERO]}),
    ("recycle + bogus field", {"discriminator": "recycle", "instanceId": ZERO, "zzz": 1}),
    ("recycle bogus id", {"discriminator": "recycle", "instanceId": BOGUS}),
    ("recycle amount only", {"discriminator": "recycle", "amount": 1}),
    ("scrap bare", {"discriminator": "scrap"}),
    ("scrap instanceId+amount", {"discriminator": "scrap", "instanceId": ZERO, "amount": 1}),
    ("repair bare", {"discriminator": "repair"}),
    ("repair instanceId", {"discriminator": "repair", "instanceId": ZERO}),
    ("repair itemInstanceId", {"discriminator": "repair", "itemInstanceId": ZERO}),
    ("repair instanceId+amount", {"discriminator": "repair", "instanceId": ZERO, "amount": 1}),
    ("repair itemInstanceId+amount", {"discriminator": "repair", "itemInstanceId": ZERO, "amount": 1}),
    ("moveAmount bare", {"discriminator": "moveAmount"}),
    ("moveAmount from+to+amount", {"discriminator": "moveAmount", "fromInstanceId": ZERO,
                                   "toParentInstanceId": ZERO, "amount": 1}),
    ("moveAmount + bogus", {"discriminator": "moveAmount", "fromInstanceId": ZERO,
                            "toParentInstanceId": ZERO, "amount": 1, "zzz": 1}),
    ("unknown discriminator", {"discriminator": "split", "instanceId": ZERO}),
]

print("== batch shape probe | %s" % ACCOUNT)
for label, op in CASES:
    try:
        print("   %-32s -> %s" % (label, ask(op)))
    except requests.RequestException as exc:
        print("   %-32s -> network %s" % (label, type(exc).__name__))
