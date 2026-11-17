"""استطلاع آمن لمسار batch-operation الي بعتلنا بابا ستالين.

كل الطلبات هنا بجسم مستحيل يتنفّذ (UUID صفر / فارغ) فلو المسار mounteds هيرفض
من مرحلة التحقق مش من مرحلة الكتابة.
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc, pioneer_write as pw  # noqa: E402

TOKEN = pc.account_token("G18")
HDRS = pc.headers(TOKEN, pc.load_manifest())

PATHS = [
    "/v1/pioneer/v1/batch-operation",
    "/v1/pioneer/batch-operation",
    "/v1/pioneer/inventory/v1/batch-operation",
]

ZERO = "00000000-0000-0000-0000-000000000000"
BODIES = [
    ("empty-mutations", {"mutations": []}),
    ("empty-operations", {"operations": []}),
    ("moveAmount-bad-id", {"operations": [{"discriminator": "moveAmount",
                                          "fromInstanceId": ZERO,
                                          "toInstanceId": ZERO, "amount": 1}]}),
    ("setParents-bad-id", {"operations": [{"discriminator": "setParents",
                                          "itemInstanceId": ZERO,
                                          "parentInstanceIds": [ZERO]}],
                           "requestId": "00112233445566778899aabbccddeeff"}),
]

print("old route state:", json.dumps(pw.route_state(), ensure_ascii=False))
print("base:", pc.BASE)
for path in PATHS:
    url = pc.BASE + path
    for label, body in BODIES:
        try:
            r = requests.post(url, headers=HDRS, json=body, timeout=config.HTTP_TIMEOUT)
            verdict = ("UNMOUNTED" if r.status_code == 404 and "404 page not found" in r.text
                       else "MOUNTED?" if r.status_code in (400, 412, 422)
                       else "REFUSED" if r.status_code in (401, 403)
                       else "OTHER")
            print("%-42s %-20s -> %s %s | %s" % (path, label, r.status_code, verdict,
                                                 r.text[:200].replace("\n", " ")))
        except requests.RequestException as exc:
            print("%-42s %-20s -> network %s" % (path, label, type(exc).__name__))
    print("-" * 70)
