# -*- coding: utf-8 -*-
"""أوراكل بدون أي أثر: هل بوابة Embark الرسمية تعرف split/combine/stack_merge لتوكن إحنا؟

رامبرت بعتت للتوكرين دول حرفياً ونجحوا عند Embark (اتحققنا من الشجرة الرسمية).
السؤال الوحيد الفاصل: هل توكن الرفيق بتاعنا مسموحله نفس الـ discriminators ولا لأ.

الطلبات كلها بـ instanceId وهمي (مافيش عنصر بالآيدي ده أصلاً) فمستحيل تغيّر حاجة:
  INVENTORY_ITEM_NOT_FOUND  ⇐ الـ discriminator معروف، جرّبنا بشكل غلط قبل كده
  UNKNOWN                   ⇐ الـ discriminator مش في enum التوكن ده

وكمان بتمسح مسارات batch-mutate المحتملة بـ GET: 405 = المسار موجود، 404 = مش موجود.

    python -m inspection.probe_split_official
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import config, pioneer_client as pc, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "RAIDER60766"
FAKE = "00000000-0000-4000-8000-000000000000"
TOKEN = pc.account_token(ACCOUNT)


def why(exc):
    text = str(exc)
    try:
        body = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception:
        return text[:160]
    if isinstance(body, dict):
        return "%s %s" % (body.get("reason") or body.get("detail") or "?",
                          str(body.get("message") or "")[:90])
    return text[:160]


def try_mutate(label, muts):
    try:
        resp = pc.post_json(pw._url(), {"mutations": muts, "requestId": ""}, token=TOKEN)
        cs = (resp.get("changeset") or {}).get("items") or {}
        print("  %-34s 200 created=%s updated=%s" % (label, len(cs.get("created") or []),
                                                     len(cs.get("updated") or [])))
    except Exception as exc:
        print("  %-34s %s" % (label, why(exc)))


def sweep():
    print("== مسارات محتملة باسم batch-mutate (GET: 405=موجود / 404=مش موجود) ==")
    for path in ("/v1/pioneer/inventory/batch-mutate",
                 "/v1/pioneer/inventory/v1/batch-mutate",
                 "/v1/pioneer/inventory/v1/mutate/batch",
                 "/v1/pioneer/inventory/stack-merge",
                 "/v1/pioneer/inventory/v1/split",
                 "/v1/pioneer/inventory/v1/combine",
                 "/v1/pioneer/inventory/merge",
                 "/v1/pioneer/inventory/v1/mutate"):
        try:
            r = pc.request(path, token=TOKEN, method="GET", timeout=12)
            print("  %-46s %s" % (path, r.status_code))
        except Exception as exc:
            print("  %-46s %s" % (path, why(exc)))


def variants():
    """رامبرت سيرفر بيبلّع التوكن ويعيد إرساله — يمكن الفرق في الهيدرز مش في التوكن.
    كلها أوراكل بآيدي وهمي: مافيش أي أثر على الحساب."""
    print("\n== نفس الـ split بآيدي وهمي مع هيدرز مختلفة ==")
    mut = [{"discriminator": "split", "instanceId": FAKE, "targetWrapperId": FAKE, "amount": 1}]
    for label, mid in (("بدون مانيفست", ""), ("مانيفست صفر", "0"),
                       ("مانيفست الحالي", pc.load_manifest()), ("مانيفست قديم", "1")):
        try:
            resp = pc.post_json(pw._url(), {"mutations": mut, "requestId": ""},
                                token=TOKEN, manifest_id=mid)
            print("  %-22s 200 %s" % (label, str(resp)[:120]))
        except Exception as exc:
            print("  %-22s %s" % (label, why(exc)))


def main():
    print("الحساب: %s | البوابة: %s" % (ACCOUNT, config.PIONEER_BASE if hasattr(config, "PIONEER_BASE") else pc.BASE))
    sweep()
    print("\n== أوراكل الـ discriminator بآيدي وهمي (مافيش أثر) ==")
    try_mutate("split / targetWrapperId",
               [{"discriminator": "split", "instanceId": FAKE, "targetWrapperId": FAKE, "amount": 1}])
    try_mutate("split / targetInstanceId",
               [{"discriminator": "split", "instanceId": FAKE, "targetInstanceId": FAKE, "amount": 1}])
    try_mutate("combine / targetInstanceId",
               [{"discriminator": "combine", "instanceId": FAKE, "targetInstanceId": FAKE, "amount": 1}])
    try_mutate("combine / targetWrapperId",
               [{"discriminator": "combine", "instanceId": FAKE, "targetWrapperId": FAKE, "amount": 1}])
    # stack_merge لوحدها بتلمّ كل الستاش — مش بتتحط غير بـ --with-merge وبعد إذن صريح.
    if "--with-merge" in sys.argv:
        try_mutate("stack_merge (bare)", [{"discriminator": "stack_merge"}])
    else:
        print("  %-34s متخطّية (كتابة على كل الحساب — محتاجة --with-merge)" % "stack_merge (bare)")
    print("\n== تحكم: discriminator معروف (update) بآيدي وهمي ==")
    try_mutate("update / fake", [{"discriminator": "update", "instanceId": FAKE,
                                  "slots": None, "amount": 1}])
    try_mutate("recycle / fake", [{"discriminator": "recycle", "instanceId": FAKE}])
    variants()
    return 0


if __name__ == "__main__":
    sys.exit(main())
