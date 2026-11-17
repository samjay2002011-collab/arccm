# -*- coding: utf-8 -*-
"""بيستجوب حقول `update` و`create` على البوابة — بخطوات ما بتغيّرش المجموع.

اللي اتقاس في probe_mutate_schema: الـenum الرسمي فيه `update/delete/recycle/scrap/repair`
وبس (`create` بيردّ 500 مش 400 فشكله مختلف)، و`combine` مش اسم معروف خالص. الاختبارات
هنا بتفرّض إن تغيير كمية عنصر جوه عقدة العنصر نفسه هو مسار الدمج الحقيقي:

  A) `update` على العنصر بكميته الحالية (no-op) → لو اتقبل، الشكل صحيح ومفيش أي خطر.
  B) `create` بآيد خانة وهمية → نستخرج الحقول المطلوبة من رسالة الخطأ.
  C) مع `--merge` بس: طلب واحد فيه [الهدف += , المصدر = 0] → ده الدمج نفسه.

    python -m inspection.probe_mutate_fields RAIDER38830
    python -m inspection.probe_mutate_fields RAIDER38830 --merge
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402
from backend import pioneer_tree  # noqa: E402
from backend import pioneer_write as pw  # noqa: E402

BOGUS = "00000000-0000-4000-8000-000000000000"
ASSET = 1370841463          # ARC Alloy — مادة رخيصة للاختبار
SRC = "267acd7e-9079-402d-af16-a427bf747841"    # ARC Alloy amount=1
DST = "110b7eb9-8083-4c4f-b15d-57ea7df9a5b5"    # ARC Alloy amount=11


def tree(account):
    return pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])


def send(token, muts, label):
    body = {"mutations": muts, "requestId": ""}
    print("\n--- %s\n%s" % (label, json.dumps(body)), flush=True)
    try:
        resp = pc.post_json(pw._url(), body, token=token)
        print("    200:", json.dumps(resp)[:260])
        return resp
    except pc.PioneerError as exc:
        print("    رفض:", str(exc)[:260])
        return None


def main():
    account = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
        else "RAIDER38830"
    want_merge = "--merge" in sys.argv
    token = pc.account_token(account)
    t = tree(account)
    a, b = t.by_id.get(DST) or {}, t.by_id.get(SRC) or {}
    if not a or not b:
        print("الرصتين المشهودتين مش في الشجرة — اعمل SYNC.")
        return
    print("الهدف %s = %d | المصدر %s = %d | النوع %s"
          % (DST[:8], int(a["amount"]), SRC[:8], int(b["amount"]), a.get("gameAssetId")))

    # A) no-op على عقدة العنصر: نفس الكمية بالظبط
    send(token, [{"discriminator": "update", "instanceId": DST,
                  "amount": int(a["amount"])}], "A1: update عنصر بنفس كميته")
    time.sleep(0.4)
    send(token, [{"discriminator": "update", "instanceId": t.parent.get(DST),
                  "slots": [DST], "amount": int(a["amount"])}],
         "A2: update الخانة بكمية ابنها (شكل النقل المعروف)")

    # B) شكل create
    for label, mut in [
        ("B1: create بآيد خانة وهمية",
         {"discriminator": "create", "instanceId": BOGUS, "gameAssetId": ASSET, "amount": 1}),
        ("B2: create من غير instanceId",
         {"discriminator": "create", "gameAssetId": ASSET, "amount": 1}),
        ("B3: create بـ slots فاضية",
         {"discriminator": "create", "instanceId": BOGUS, "slots": [""]}),
    ]:
        send(token, [mut], label)
        time.sleep(0.4)

    after = tree(account)
    print("\n== بعد A و B == الهدف %s | المصدر %s"
          % ((after.by_id.get(DST) or {}).get("amount"),
             (after.by_id.get(SRC) or {}).get("amount")))
    if not want_merge:
        print("\n(الدمج الحقيقي محتاج `--merge` صريحة)")
        return

    # C) الدمج: الهدف يشيل总量 والمصدر يصفر — في طلب واحد
    total = int(a["amount"]) + int(b["amount"])
    send(token, [
        {"discriminator": "update", "instanceId": DST, "amount": total},
        {"discriminator": "update", "instanceId": SRC, "amount": 0},
    ], "C: دمج ARC Alloy (11+1=12) عن طريق تعديل الكميات")
    time.sleep(2)
    fresh = tree(account)
    print("النتيجة: الهدف %s | المصدر %s | مجموع النوع %d (كان %d)"
          % ((fresh.by_id.get(DST) or {}).get("amount"),
             (fresh.by_id.get(SRC) or {}).get("amount"),
             pw._asset_totals(fresh).get(str(ASSET), 0),
             pw._asset_totals(t).get(str(ASSET), 0)))


if __name__ == "__main__":
    main()
