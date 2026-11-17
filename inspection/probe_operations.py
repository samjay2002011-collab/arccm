# -*- coding: utf-8 -*-
"""بيختبر فرضية strong طلعت من ذاكرة اللعبة: نفس مسار mutate بيقبل شكل تاني خالص.

المكتشف من جدول أسماء UE جوه الذاكرة (inspection/mem_symbol_harvest.py):
  • الطلب الحقيقي بتاع اللعبة = FPioneerOnlineBatchOperationRequest
  • و فيه oneof اسمه operation، حالاته (EPioneerOnlineOperationType + الحقول اللي اتقابت):
    moveItem / moveItemAmount / setParents / scrap / recycle / repair / upgrade / acceptOffer
  • و إحنا عارفين إن mutate بيقبل {"mutations":[{"discriminator":…}]} — ودي تسمية
    الـoneof كمان (discriminator = اسم الحالة)، بس enum التوكن عندنا صغير.

يبقى السؤال اللي محدش سأله: هل `/v1/pioneer/inventory/v1/mutate` بيقبل كمان
{"operations":[…]} أو {"batchOperations":[…]}؟ الأوراكل كلها بآيدي وهمي = صفر أثر:
  INVENTORY_ITEM_NOT_FOUND  → الشكل اتحلل والسيرفر وصل لمرحلة البحث عن العنصر (كنز!)
  UNKNOWN / field error     → الشكل مش مقبول
  200                       → (متوقعش، بس لو حصل يبقى عملية فارغة)

    python -m inspection.probe_operations G22
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"
FAKE = "00000000-0000-4000-8000-000000000000"

OPS = ["moveItem", "moveItemAmount", "setParents", "scrap", "recycle", "repair",
       "upgrade", "acceptOffer", "claimScrappy", "collectResources", "donate",
       "combine", "split", "stackMerge"]
ARRAY_KEYS = ["operations", "batchOperations", "operationsList", "requests"]
INNER_KEYS = ["operation", "op", "type", "kind", "discriminator"]


def detail(exc):
    text = str(exc)
    return text[:200].replace("\n", " ")


def ask(token, body, label):
    try:
        out = pc.post_json(pw._url(), body, token=token)
        return "200 " + json.dumps(out)[:110]
    except Exception as exc:  # noqa: BLE001
        return detail(exc)


def main():
    token = pc.account_token(ACCOUNT)
    if not token:
        print("مافيش توكن لـ", ACCOUNT)
        return
    print("المسار:", pw._url())

    print("\n== 1) أي اسم مصفوفة بيمرر فحص التحليل؟ ==")
    for key in ARRAY_KEYS:
        for op in ("moveItem", "scrap"):
            body = {key: [{op: {"instanceId": FAKE}}], "requestId": ""}
            print("   %-18s %-14s -> %s" % (key, op, ask(token, body, key)))

    print("\n== 2) نفس المصفوفات بشكل {discriminator:…} زي mutate ==")
    body = {"operations": [{"discriminator": "moveItem", "instanceId": FAKE}],
            "requestId": ""}
    print("   operations+discriminator ->", ask(token, body, ""))

    print("\n== 3) حقل واحد وهمي أعلى الطلب (اختبار الصرامة) ==")
    print("   zzz                      ->",
          ask(token, {"zzz": 1, "mutations": []}, ""))
    print("   operations=[] فارغة      ->",
          ask(token, {"operations": []}, ""))
    print("   mutations=[] فارغة       ->",
          ask(token, {"mutations": []}, ""))

    print("\n== 4) الضوابط المعروفة ==")
    print("   update/آيدي وهمي         ->",
          ask(token, {"mutations": [{"discriminator": "update", "instanceId": FAKE}]}, ""))
    print("   scrap/آيدي وهمي          ->",
          ask(token, {"mutations": [{"discriminator": "scrap", "instanceId": FAKE}]}, ""))
    print("   moveItem/آيدي وهمي       ->",
          ask(token, {"mutations": [{"discriminator": "moveItem", "instanceId": FAKE}]}, ""))


if __name__ == "__main__":
    main()
