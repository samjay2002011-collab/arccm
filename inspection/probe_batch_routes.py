# -*- coding: utf-8 -*-
"""بحث عن سطح "batch inventory operations" اللي الـmanifest فعّله.

gameflags.enable_inventory_batch_operations = "true" في manifest الحي، ورامبارت
يبعت لـ /inventory/batch-mutate — فالمسار ممكن يكون تحت الـprefix بتاعنا
وبتسمية مختلفه (/v1/pioneer/inventory/v1/batch-mutate).

المنهج آمن: GET بس (405/200 = المسار موجود، 404 = مش موجود)، وبعدين POST بجسم
discriminator مجهول + instanceId وهمي — مابعملش أي تغيير على أي عنصر.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402

FAKE = "11111111-1111-1111-1111-111111111111"

CANDIDATES = [
    "/v1/pioneer/inventory/v1/batch-mutate",
    "/v1/pioneer/inventory/v1/batch_mutate",
    "/v1/pioneer/inventory/v1/batchmutate",
    "/v1/pioneer/inventory/v1/batch",
    "/v1/pioneer/inventory/v1/batch-update",
    "/v1/pioneer/inventory/v1/mutate-batch",
    "/v1/pioneer/inventory/v1/mutate/batch",
    "/v1/pioneer/inventory/v1/mutations",
    "/v1/pioneer/inventory/batch-mutate",
    "/v1/pioneer/batch-mutate",
    "/v1/pioneer/inventory/v1/split",
    "/v1/pioneer/inventory/v1/combine",
    "/v1/pioneer/inventory/v1/merge",
    "/v1/pioneer/inventory/v1/stack-merge",
    "/v1/pioneer/inventory/v1/split-stack",
    "/v1/pioneer/inventory/v1/consolidate",
    "/v1/pioneer/inventory/v1/stacks/split",
    "/v1/pioneer/inventory/v1/stacks/merge",
    "/v1/pioneer/inventory/v1/items/split",
    "/v1/pioneer/inventory/v1/items/merge",
    "/v1/pioneer/inventory/v1/amount",
    "/v1/pioneer/inventory/v1/amounts",
    "/v1/pioneer/inventory/v1/move",
    "/v1/pioneer/inventory/v1/moves",
    "/v1/pioneer/inventory/v1/move-all-to-overflow",
    "/v1/pioneer/inventory/v1/operations",
    "/v1/pioneer/inventory/v1/item-operations",
    "/v1/pioneer/inventory/v1/sort",
    "/v1/pioneer/inventory/v1/organize",
    "/v1/pioneer/inventory/v2/mutate",
    "/v1/pioneer/inventory/v1/mutate/all",
    "/v1/pioneer/inventory/v1/batch-mutate/",
    "/v1/pioneer/offers/v1/batch-mutate",
    "/v1/pioneer/inventory/v1/mutateBatch",
    "/v1/pioneer/inventory/v1/batchMutate",
]

BODY = {"mutations": [{"discriminator": "zzz_not_a_kind", "instanceId": FAKE}], "requestId": ""}


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else ""
    token = pc.account_token(account or None)
    if not token:
        print("مفيش توكن جاهز — شغّل FahmySync واللعبة مفتوحة.")
        return
    print("حساب:", account or "(النشيط)")
    print("\n== 1) وجود المسار (GET: 404 = مش موجود / أي حاجة تانية = موجود) ==")
    hits = []
    for path in CANDIDATES:
        try:
            out = pc.request(path, token=token, method="GET")
            print("%-48s موجود %s" % (path, json.dumps(out, ensure_ascii=False)[:120]))
            hits.append(path)
        except Exception as exc:
            msg = str(exc)
            if "404 page not found" in msg:
                print("%-48s 404" % path)
            elif "405" in msg:
                print("%-48s 405 => مسار POST موجود!" % path)
                hits.append(path)
            else:
                print("%-48s %s" % (path, msg[:110]))

    print("\n== 2) أوراكل POST بجسم مجهول (مفيش أي تأثير) ==")
    for path in CANDIDATES:
        try:
            out = pc.request(path, token=token, method="POST", body=BODY)
            print("%-48s 200 %s" % (path, json.dumps(out, ensure_ascii=False)[:160]))
        except Exception as exc:
            msg = str(exc)
            if "404 page not found" in msg:
                continue
            tag = "موجود ومرفوض" if ("UNKNOWN" in msg or "NOT_FOUND" in msg or "INVALID" in msg) else "؟"
            print("%-48s %s %s" % (path, tag, msg[:130]))

    print("\n== 3) المقارنة بالمسار المعروف شغّال ==")
    for body in ({"mutations": [{"discriminator": "update", "instanceId": FAKE}], "requestId": ""}, BODY):
        try:
            out = pc.request("/v1/pioneer/inventory/v1/mutate", token=token, method="POST", body=body)
            print(json.dumps(out, ensure_ascii=False)[:160])
        except Exception as exc:
            print("mutate:", str(exc)[:160])


if __name__ == "__main__":
    main()
