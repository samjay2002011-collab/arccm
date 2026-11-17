# -*- coding: utf-8 -*-
"""بحث عن مسارات البوابة: بيفرق بين «المسار مش موجود» و«المسار موجود والطلب مرفوض».

    python -m inspection.route_probe G18          # namespace الرفيق (pioneer)
    python -m inspection.route_probe G18 game     # namespace اللعبة (/v1/inventory)

كل الطلبات بجسم مستحيل (معرّف GUID غير موجود + كمية -1)، فمهما كان المسار
موجود مافيش تنفيذ لحاجة. رد 404 = مفيش مسار؛ 403 RBAC أو 400/404 بحقل
INVENTORY_* = المسار موجود والرفض من طبقة الصلاحيات/الفحص.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import config, pioneer_client as pc  # noqa: E402

# أسماء تطلب معرّف عنصر بالضرورة — مستحيل تشتغل بجسم مهمل.
PIONEER_PATHS = [
    "/v1/pioneer/inventory/v1/split",
    "/v1/pioneer/inventory/v1/split-stack",
    "/v1/pioneer/inventory/v1/merge",
    "/v1/pioneer/inventory/v1/combine",
    "/v1/pioneer/inventory/v1/stack",
    "/v1/pioneer/inventory/v1/stack-merge",
    "/v1/pioneer/inventory/v1/create",
    "/v1/pioneer/inventory/v1/add",
    "/v1/pioneer/inventory/v1/duplicate",
    "/v1/pioneer/inventory/v1/id-update",
    "/v1/pioneer/inventory/v1/refresh-ids",
    "/v1/pioneer/inventory/v1/mutate-item",
    "/v1/pioneer/inventory/v1/item",
    "/v1/pioneer/inventory/v1/items",
    "/v1/pioneer/inventory/split",
    "/v1/pioneer/inventory/merge",
]

GAME = "/v1/inventory/"
GAME_PATHS = [GAME + n for n in (
    "split", "split-stack", "merge", "stack-merge", "combine", "create", "add",
    "duplicate", "move", "batch-move", "mutate", "batch-mutate", "recycle",
    "scrap", "repair", "upgrade", "id-update", "refresh-ids", "delete",
    "discard", "contents", "items", "slots", "stash", "backpack", "overflow",
    "move-all-to-overflow", "attachments/attach", "attachments/detach",
    "weapon/upgrade", "v1/mutate", "v1/split",
)] + [
    "/v1/inventory",
    "/v1/items",
    "/v1/raiders",
    "/v1/market",
    "/v1/workshop",
]

BAD = {"instanceId": "11111111-1111-1111-1111-111111111111",
       "targetWrapperId": "11111111-1111-1111-1111-111111111111",
       "targetInstanceId": "11111111-1111-1111-1111-111111111111",
       "amount": -1, "qty": -1, "count": -1,
       "mutations": [{"discriminator": "split",
                      "instanceId": "11111111-1111-1111-1111-111111111111",
                      "amount": -1}],
       "requestId": ""}


def classify(text):
    """404 page not found = مفيش مسار خالص. أي حاجة تانية = المسار موجود."""
    if "404 page not found" in text or "405" in text[:40] and "page not found" in text:
        return "مفيش مسار"
    if "RBAC" in text:
        return "موجود — التوكن مرفوض (RBAC)"
    if "INVENTORY_" in text:
        return "موجود — رفض فحص المخزن"
    if "UNAUTH" in text or "401" in text[:40]:
        return "موجود — توكن مرفوض"
    return "موجود؟"


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    which = (sys.argv[2] if len(sys.argv) > 2 else "pioneer").lower()
    paths = GAME_PATHS if which == "game" else PIONEER_PATHS
    token = pc.account_token(account)
    if not token:
        print("مفيش توكن لـ %s" % account)
        return 1
    hits = []
    for path in paths:
        try:
            pc.post_json(pc.BASE + path, BAD, token=token)
            verdict, detail = "قَبِل الطلب!!", "لازم نطمن على المخزن"
        except pc.PioneerError as exc:
            text = str(exc).replace(pc.BASE, "").replace(path, "").strip()
            verdict = classify(text)
            detail = text[:150]
        except Exception as exc:      # noqa: BLE001
            verdict, detail = "خطأ", (type(exc).__name__ + " " + str(exc))[:150]
        print("%-46s %-28s %s" % (path, verdict, detail))
        if verdict != "مفيش مسار":
            hits.append(path)
    print("\nالمسارات الموجودة: %d" % len(hits))
    for h in hits:
        print("  ", h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
