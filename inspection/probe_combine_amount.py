# -*- coding: utf-8 -*-
"""الدمج الرسمي عن طريق تعديل كمية العنصر نفسه — مش كلمة combine.

اللي اتقاس لايف (2026-10-31):
  • `{"discriminator":"update","instanceId":<آيد العنصر>,"amount":11}` → **200** (الشكل ده مقبول)
  • `combine/split/stack_merge` → 400 UNKNOWN (أسماء مش في قاموس البوابة أصلاً)
  • الخانة نفسها ليها amount خاص بيها، ولو بعته بكمية ابنها ردّت `INVENTORY_ITEM_NOT_STACKABLE`

فالخطوة دي بتختبر: لو زوّدت كمية الهدف بنفس الـupdate، ومحت المصدر بـ`delete` — المجموع
بيفضل ثابت والرصتين تدمجوا فعلاً؟ كل خطوة بتتأكد من الشجرة قبل اللي بعدها، وأي انحراف
بيرجّع الرقم الأصلي.

    python -m inspection.probe_combine_amount RAIDER38830 <DEST> <SRC>
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402
from backend import pioneer_tree  # noqa: E402
from backend import pioneer_write as pw  # noqa: E402


def tree(account):
    return pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])


def post(token, muts):
    try:
        return pc.post_json(pw._url(), {"mutations": muts, "requestId": ""}, token=token), None
    except pc.PioneerError as exc:
        return None, str(exc)[:220]


def wait_amount(account, iid, want, tries=6):
    """يستنى الشجرة تبين الكمية المتوقعة (المنبع بيأخر القراءة شوية)."""
    for i in range(tries):
        t = tree(account)
        node = t.by_id.get(iid)
        got = int((node or {}).get("amount") or 0)
        if node is None and want == 0:
            return t, 0
        if got == want:
            return t, got
        time.sleep(1.5 + i)
    return t, got  # آخر حالة مقروءة


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "RAIDER38830"
    dst = sys.argv[2] if len(sys.argv) > 2 else "110b7eb9-8083-4c4f-b15d-57ea7df9a5b5"
    src = sys.argv[3] if len(sys.argv) > 3 else "267acd7e-9079-402d-af16-a427bf747841"
    token = pc.account_token(account)
    t = tree(account)
    a, b = t.by_id.get(dst) or {}, t.by_id.get(src) or {}
    if not a or not b:
        print("الرصتين مش في الشجرة — اعمل SYNC.")
        return
    if str(a.get("gameAssetId")) != str(b.get("gameAssetId")):
        print("نوعين مختلفين — مفيش اختبار.")
        return
    aid = str(a.get("gameAssetId"))
    qa, qb = int(a.get("amount") or 0), int(b.get("amount") or 0)
    total_before = pw._asset_totals(t).get(aid, 0)
    print("الهدف %s=%d | المصدر %s=%d | مجموع النوع %d"
          % (dst[:8], qa, src[:8], qb, total_before))

    # 1) نكمّل الهدف للمجموع
    resp, err = post(token, [{"discriminator": "update", "instanceId": dst,
                              "amount": qa + qb}])
    print("\n1) update الهدف لـ %d → %s" % (qa + qb, err or "200"))
    if err:
        print("   المنبع رفض — مفيش أي تغيير في الشجرة.")
        return
    t2, got = wait_amount(account, dst, qa + qb)
    print("   القراءة بعد الطلب: الهدف = %s" % got)
    if got != qa + qb:
        print("   البوابة ردّت OK بس الكمية ماتبسطتش — نرجع 200 من غير تنفيذ.")
        return

    # 2) نمحي المصدر (وحداته اتحسبت في الهدف خلاص)
    resp, err = post(token, [{"discriminator": "delete", "instanceId": src}])
    print("\n2) delete المصدر → %s" % (err or "200"))
    t3, src_now = wait_amount(account, src, 0)
    dst_now = int((t3.by_id.get(dst) or {}).get("amount") or 0)
    total_after = pw._asset_totals(t3).get(aid, 0)
    print("\n== النتيجة == الهدف %d | المصدر %s | مجموع النوع %d (كان %d)"
          % (dst_now, "اتشال" if src_now == 0 else src_now, total_after, total_before))
    if total_after != total_before:
        print("⚠️ المجموع اتغيّر — نرجّع الهدف فورًا لـ %d" % qa)
        post(token, [{"discriminator": "update", "instanceId": dst, "amount": qa}])
    elif src_now != 0:
        print("المصدر لسه موجود — نجرب `recycle`؟ لأ: بنسبّه ونبلّغ.")
    else:
        print("✅ الدمج اتعمل على مسار رسمي: %d + %d = %d" % (qa, qb, dst_now))
    print("\nردّ الطلب الأول:", json.dumps(resp)[:300] if resp else "-")


if __name__ == "__main__":
    main()
