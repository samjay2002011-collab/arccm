"""جرد الـ discriminators اللي بيقبلها batch-operation.

الحيلة: اسم وهمي بيرجع UNKNOWN (الراوتر ما عرفوش)، واسم موجود بيرجع خطأ تاني
(INVALID_ARGUMENT / NOT_FOUND) لأن تحقيق وصل لحقول العملية نفسها.
كل الطلبات بـ UUID صفر فمستحيل تلمس قطعة حقيقية.
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
NAMES = [
    "setParents", "moveAmount", "update", "create", "delete", "remove",
    "combine", "split", "stackMerge", "stack_merge", "merge", "mergeStack",
    "move", "moveItem", "transfer", "attach", "detach", "equip", "unequip",
    "swap", "swapSlots", "upgrade", "downgrade", "recycle", "scrap", "salvage",
    "repair", "sell", "craft", "activate", "consume", "use", "addToStack",
    "removeFromStack", "setAmount", "updateAmount", "setSlots", "setDurability",
    "setInstance", "modify", "mutate", "operate", "operation", "bulk",
    "reparent", "setParent", "moveTo", "placeItem", "pickUp", "drop",
]


def ask(name):
    # حقل غرض عام: لو الاسم موجود البوابة بتشتكي من حقوله، لو مش موجود بتشتكي من الاسم
    body = {"operations": [{"discriminator": name, "instanceId": ZERO, "itemInstanceId": ZERO,
                           "parentInstanceIds": [ZERO], "amount": 1}]}
    try:
        r = requests.post(URL, headers=HDRS, json=body, timeout=config.HTTP_TIMEOUT)
        return r.status_code, (r.json().get("reason") if r.headers.get(
            "content-type", "").startswith("application/json") else r.text[:60])
    except (requests.RequestException, ValueError) as exc:
        return "err", type(exc).__name__


known, unknown = [], []
for n in NAMES:
    code, reason = ask(n)
    tag = "UNKNOWN" if reason == "UNKNOWN" else str(reason)
    print("%-18s %s %s" % (n, code, tag))
    (unknown if tag == "UNKNOWN" else known).append(n)

print("\nKNOWN (%d):" % len(known), known)
print("unknown names:", len(unknown))
