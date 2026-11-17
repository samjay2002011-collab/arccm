# -*- coding: utf-8 -*-
"""بيختبر التقسيم الرسمي: create لرصتين جوه طلب واحد + نقص كمية الأصل.

اللي اتقاس: الزيادة بـ update اتقبلت لما اتحفظت الوحدات في نفس الطلب (دمج ARC Alloy
11+1=12 لايف). كمان `create` بيردّ على الأسماء الغلط بـ 400 UNKNOWN لكنه بيقرا الحقول
(B3 راجع بـ INVENTORY_ITEM_ZERO_AMOUNT) — يعني معروف. لو التقسيم اتقبل بنفس المنطق
(نقص الأصل + create للفرع في طلب واحد) يبقى مسار `split` الرسمي اتفتح، وده اللي
مطلوب في نافذة SPLIT STACK.

الترتيب مقصود: create الأول، فالنقص بعده — لو النقص فشل الخسارة بتكون +رصّة إضافية
تقدر تتشال بـ delete، مش فقد مواد.

    python -m inspection.probe_split_create RAIDER38830
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402
from backend import pioneer_tree  # noqa: E402
from backend import pioneer_write as pw  # noqa: E402

ASSET = 1370841463          # ARC Alloy
SRC = "110b7eb9-8083-4c4f-b15d-57ea7df9a5b5"   # الرصة الأم (12 بعد الدمج)
TAKE = 5


def tree(account):
    return pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])


def empty_stash_cell(t):
    """خانة ستاش فاضية — البوابة بتعرّف الخانة الفاضية بـ slots=[""]."""
    for iid, node in t.by_id.items():
        slots = node.get("slots")
        if slots in ([], [""]) and str(node.get("gameAssetId") or "") not in ("0", ""):
            kids = t.kids.get(iid) or []
            if not kids:
                return iid
    return ""


def post(token, muts, label):
    body = {"mutations": muts, "requestId": ""}
    print("\n--- %s\n%s" % (label, json.dumps(body)), flush=True)
    try:
        resp = pc.post_json(pw._url(), body, token=token)
        print("    200:", json.dumps(resp)[:240])
        return resp, None
    except pc.PioneerError as exc:
        print("    رفض:", str(exc).split("-> ", 1)[-1][:200])
        return None, str(exc)


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "RAIDER38830"
    token = pc.account_token(account)
    t = tree(account)
    node = t.by_id.get(SRC) or {}
    qty = int(node.get("amount") or 0)
    cell = empty_stash_cell(t)
    if not qty or qty <= TAKE:
        print("الرصة الأم صغيرة للتجربة (=%d)." % qty)
        return
    if not cell:
        print("مفيش خانة ستاش فاضية — مفيش مكان للفرع.")
        return
    aid = str(node.get("gameAssetId"))
    total_before = pw._asset_totals(t).get(aid, 0)
    print("الأصل %s=%d في %s | الخانة الفاضية %s | مجموع النوع %d"
          % (SRC[:8], qty, (t.parent.get(SRC) or "")[:8], cell[:8], total_before))

    resp, err = post(token, [
        {"discriminator": "create", "instanceId": cell, "gameAssetId": int(aid),
         "amount": TAKE},
        {"discriminator": "update", "instanceId": SRC, "amount": qty - TAKE},
    ], "تقسسيم: create فرع %d + نقص الأصل لـ %d" % (TAKE, qty - TAKE))
    if err:
        print("\nمرفوض — الشجرة ما اتغيرتش.")
        return
    time.sleep(3)
    fresh = tree(account)
    total = pw._asset_totals(fresh).get(aid, 0)
    kids = [k for k in (fresh.kids.get(cell) or [])]
    print("\n== النتيجة == الأصل %s | الفرع في الخانة: %s | مجموع النوع %d (كان %d)"
          % ((fresh.by_id.get(SRC) or {}).get("amount"), kids, total, total_before))
    if total != total_before:
        print("⚠️ المجموع اتغيّر — بننضّف: بنرجّع الأصل %d وبنمسح أي فرع متزايد." % qty)
        if kids:
            post(token, [{"discriminator": "delete", "instanceId": kids[0]}], "تنظيف الفرع")
        post(token, [{"discriminator": "update", "instanceId": SRC, "amount": qty}],
             "تنظيف الأصل")
    else:
        print("✅ التقسيم اتعمل على مسار رسمي والمجموع سالم.")


if __name__ == "__main__":
    main()
