# -*- coding: utf-8 -*-
"""أوراكل بدون أي تأثير: هل `create` بيخلص لما يكون جوه دفرة محفوظة الكمية؟

اللي مقس ثابت: الـenum بتاع الرفيق بيقبل update/create/recycle/scrap/repair/delete،
والكمية في `update` بتتقرا (−1 بترد INVENTORY_ITEM_MIN_AMOUNT_EXCEEDED) بس أي تغيير
حقيقي مرفوض INVALID_ARGUMENT، و`create` بترد 412 FAILED_PRECONDITION في كل الأشكال.
والـmanifest الحي فعّل gameflags.enable_inventory_batch_operations = "true".

الفرضية: البوابة بتمنع توليد كمية من العدم (precondition)، وبتسمح بيها بس جوه
batch فيه طرف تاني بينقص بنفس القدر. الأوراكل كلها بمعرفات وهمية — مافيش عنصر
حقيقي بيتلمس، والطلب الناجح مستحيل لأنه مافيش أب مزروع موجود.

    python -m inspection.probe_create_batch
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw, store  # noqa: E402

FAKE = "11111111-1111-1111-1111-111111111111"
FAKE2 = "22222222-2222-4222-8222-222222222222"
ROUTE = "/v1/pioneer/inventory/v1/mutate"


def call(mutations, label):
    body = {"mutations": mutations, "requestId": ""}
    try:
        out = pc.request(ROUTE, method="POST", body=body)
        print("%-46s 200 %s" % (label, json.dumps(out, ensure_ascii=False)[:200]))
        return "200", out
    except Exception as exc:
        msg = str(exc)
        reason = ""
        try:
            reason = json.loads(msg.split(":", 1)[1]).get("reason", "")
        except Exception:
            pass
        print("%-46s %s" % (label, msg[:200]))
        return msg, None


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else ""
    conn = store.db()
    rows = conn.execute("select asset_id, name, qty from instances where account=? "
                        "and qty > 1 order by qty desc limit 3", (account,)).fetchall() if account else []
    asset = rows[0]["asset_id"] if rows else "1004246812"
    print("نوع للتجربة (من المحلي، بيتستخدم في assetId بس):", asset,
          (rows[0]["name"] if rows else ""))

    print("\n== 1) المراجع: create لوحده (معرّف أب وهمي) ==")
    call([{"discriminator": "create", "assetId": asset, "amount": 1,
           "parentId": FAKE, "instanceId": FAKE2}], "create بأب وهمي")
    call([{"discriminator": "create", "assetId": asset, "amount": 1}], "create من غير أب")

    print("\n== 2) الدفرة المحفوظة: update بينقص + create بيزيد (معرفات وهمية) ==")
    call([{"discriminator": "update", "instanceId": FAKE, "slots": [FAKE2], "amount": 7},
          {"discriminator": "create", "assetId": asset, "amount": 1, "parentId": FAKE}],
         "update(−1) + create(+1)")
    call([{"discriminator": "update", "instanceId": FAKE, "slots": [], "amount": 7},
          {"discriminator": "create", "assetId": asset, "amount": 1}],
         "update(−1) + create(بلا أب)")

    print("\n== 3) دفرة فيها نوعين unknown عشان نعرف الترتيب ==")
    call([{"discriminator": "update", "instanceId": FAKE, "slots": [], "amount": 8},
          {"discriminator": "zzz_not_a_kind", "instanceId": FAKE}],
         "update سليم + نوع مجهول")
    call([{"discriminator": "create", "assetId": asset, "amount": 1},
          {"discriminator": "zzz_not_a_kind", "instanceId": FAKE}],
         "create + نوع مجهول")

    print("\n== 4) هل فيه حقل batch/operations في نفس المسار؟ ==")
    for extra in ({"batch": True}, {"batchOperations": True}, {"flags": ["batch"]}):
        body = {"mutations": [{"discriminator": "create", "assetId": asset, "amount": 1,
                               "parentId": FAKE}], "requestId": ""}
        body.update(extra)
        try:
            out = pc.request(ROUTE, method="POST", body=body)
            print("%-46s 200 %s" % (list(extra)[0], json.dumps(out, ensure_ascii=False)[:160]))
        except Exception as exc:
            print("%-46s %s" % (list(extra)[0], str(exc)[:160]))

    print("\n== 5) التوكن لسه حي على القراءة؟ ==")
    try:
        inv = pc.fetch_inventory()
        print("قراءة نجحت، عدد العقد:", len((inv or {}).get("items") or []))
    except Exception as exc:
        print("قراءة فشلت:", str(exc)[:160])


if __name__ == "__main__":
    main()
