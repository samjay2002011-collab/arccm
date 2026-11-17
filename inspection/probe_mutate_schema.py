# -*- coding: utf-8 -*-
"""بيستجوب البوابة عن قائمة الـ discriminators المقبولة — من غير ما يلمس أي قطعة.

الفكرة: بنبعث نفس الشكل لكن بـ instanceId وهمي (UUID مش موجود في الشجرة). السيرفر
مستحيل ينفّذ حاجة على آيد مش لاقيه، فالردّ بيكون رسالة تحقق بحتة وده كفيل يفرّق
بين:
  • reason=UNKNOWN        → الاسم مش في الـenum أصلاً (زي combine بالظبط)
  • reason=INVALID_ARGUMENT → الاسم معروف بس الحقول ناقصة/غلط  ← ده اللي بندوّر عليه
  • reason=FAILED_PRECONDITION → الاسم معروف والحالة مرفوضة

    python -m inspection.probe_mutate_schema RAIDER38830
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402
from backend import pioneer_write as pw  # noqa: E402

# آيد وهمي بصيغة سليمة: مفيش قطعة في أي شجرة تطابقه.
BOGUS = "00000000-0000-4000-8000-000000000000"
BOGUS2 = "00000000-0000-4000-8000-000000000001"

NAMES = ["update", "create", "delete", "recycle", "scrap", "repair",        # المعروف
         "combine", "split", "stack_merge", "merge", "move", "transfer",    # المرشحين
         "consolidate", "stack", "stack_split", "split_stack", "add_amount",
         "set_amount", "amount", "swap", "exchange", "recount", "join",
         "unmerge", "redistribute", "top_off", "fill", "withdraw", "deposit"]


def classify(text):
    for reason in ("UNKNOWN", "INVALID_ARGUMENT", "FAILED_PRECONDITION", "NOT_FOUND",
                   "UNAUTHENTICATED", "PERMISSION_DENIED", "OUT_OF_RANGE"):
        if reason in text:
            return reason
    return "OTHER"


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "RAIDER38830"
    token = pc.account_token(account)
    if not token:
        print("مفيش توكن للحساب", account)
        return
    print("حساب: %s | مسار: %s\n" % (account, pw._url()))
    buckets = {}
    for name in NAMES:
        body = {"mutations": [{"discriminator": name, "instanceId": BOGUS,
                               "targetInstanceId": BOGUS2, "amount": 1,
                               "slots": [BOGUS]}], "requestId": ""}
        try:
            resp = pc.post_json(pw._url(), body, token=token)
            verdict, text = "ACCEPTED", json.dumps(resp)[:200]
        except pc.PioneerError as exc:
            verdict, text = classify(str(exc)), str(exc)[:200]
        except Exception as exc:  # شبكة/وقت انتظار
            verdict, text = "ERROR", repr(exc)[:160]
        buckets.setdefault(verdict, []).append(name)
        print("  %-16s %-20s %s" % (name, verdict, text.replace("\n", " ")[:150]), flush=True)
        time.sleep(0.35)
    print("\n== التلخيص ==")
    for verdict, names in sorted(buckets.items()):
        print("  %-20s %s" % (verdict, ", ".join(names)))


if __name__ == "__main__":
    main()
