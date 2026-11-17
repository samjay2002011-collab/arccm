# -*- coding: utf-8 -*-
"""مسح سطح الكتابة بتاع بوابة Pioneer: إيه اللي البوابة بتقبله غير النقل؟

بنبعت أشكال طلبات على instanceId مش موجود (مفيش حاجة تتنفذ فعلاً) عشان نقرأ
رسالة الرفض نفسها: بروتوكول البوابة بيفصل بين "الحقل مش معروف" (يعني المسار
موجود) و"العملية مرفوضة" (يعني موجودة بس مقفولة).

قراءة بس للمخزن + طلبات مرفوضة متعمّدة — مفيش أي عنصر بيتلمس.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw, store  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else ""

BAD = "00000000-0000-4000-8000-000000000000"

DISCRIMINATORS = ["update", "delete", "destroy", "discard", "remove", "sell", "recycle",
                  "scrap", "salvage", "repair", "upgrade", "split", "combine", "stack_merge",
                  "unload", "unequip", "drop", "trade", "give", "create", "amount", "modify"]

PATHS = ["/v1/pioneer/inventory/v1/mutate", "/v1/pioneer/inventory/v1/sell",
         "/v1/pioneer/inventory/v1/trade", "/v1/pioneer/inventory/v1/recycle",
         "/v1/pioneer/trading/v1/sell", "/v1/pioneer/traders/v1/offers",
         "/v1/pioneer/market/v1/sell", "/v1/pioneer/inventory/v1/destroy",
         "/v1/pioneer/inventory/v1/delete", "/v1/pioneer/inventory/v1/modify"]


def show(label, obj):
    print("%-28s %s" % (label, json.dumps(obj, ensure_ascii=False)[:300]))


def main():
    conn = store.db()
    accounts = [r["name"] for r in store.list_accounts(conn, enabled_only=True)]
    conn.close()
    target = ACCOUNT or (accounts[0] if accounts else "")
    token = pc.account_token(target)
    print("account:", target, "| token:", "yes" if token else "NO")
    if not token:
        return

    print("\n== 1) أي حقل بيقبله الـ mutate؟ (خطأ التحقق بيعدّد البدائل)")
    for disc in DISCRIMINATORS:
        body = {"mutations": [{"discriminator": disc, "instanceId": BAD}], "requestId": ""}
        try:
            show("POST mutate/%s" % disc, pc.post_json(pw._url(), body, token=token))
        except Exception as exc:
            show("POST mutate/%s" % disc, {"error": str(exc)[:220]})

    print("\n== 2) المسارات التانية موجودة ولا لأ؟ (GET بس)")
    for path in PATHS:
        try:
            show("GET %s" % path, pc.request(path, token=token, method="GET"))
        except Exception as exc:
            show("GET %s" % path, {"error": str(exc)[:220]})

    print("\n== 3) نفس المسارات بـ POST فاضي")
    for path in PATHS[1:]:
        try:
            show("POST %s" % path, pc.request(path, token=token, method="POST", body={}))
        except Exception as exc:
            show("POST %s" % path, {"error": str(exc)[:220]})


if __name__ == "__main__":
    main()
