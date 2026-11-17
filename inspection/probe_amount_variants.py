# -*- coding: utf-8 -*-
"""بيجرب كل الأشكال اللي ممكن تخلي البوابة تقبل تغيير كمية عنصر.

المقيس: `update` بكمية مساوية = 200، بكمية مختلفة = INVALID_ARGUMENT. الفرضيات:
  V1 زيادة الهدف + تصفير المصدر في نفس الطلب (حفظ الوحدات جوه الطلب نفسه)
  V2 زيادة الهدف + `delete` للمصدر في نفس الطلب
  V3 زيادة الهدف ومعاها `etag` (قفل تعارض زي اللي في الشجرة)
  V4 زيادة الهدف مع gameAssetId/durability كاملين (عقدة عنصر كاملة)
  V5 تصفير المصدر لوحده (لو ده اتقبل يبقى فيه مسار كمية حر)
  V6 زيادة الخانة (wrapper) نفسها بكمية مجموع أولادها + etag

كل طلب بيتم التحقق منه فورًا، ولو المجموع اتغيّر بنرجّعه بأول شكل شغال.

    python -m inspection.probe_amount_variants RAIDER38830
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402
from backend import pioneer_tree  # noqa: E402
from backend import pioneer_write as pw  # noqa: E402

DST = "110b7eb9-8083-4c4f-b15d-57ea7df9a5b5"   # ARC Alloy 11
SRC = "267acd7e-9079-402d-af16-a427bf747841"   # ARC Alloy 1


def tree(account):
    return pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])


def try_post(token, muts, label, t, aid, total_before):
    body = {"mutations": muts, "requestId": ""}
    print("\n--- %s\n%s" % (label, json.dumps(body)), flush=True)
    try:
        pc.post_json(pw._url(), body, token=token)
    except pc.PioneerError as exc:
        print("    رفض:", str(exc).split("-> ", 1)[-1][:170])
        return False
    time.sleep(2.5)
    fresh = tree(account)
    dst_now = int((fresh.by_id.get(DST) or {}).get("amount") or 0)
    src_now = int((fresh.by_id.get(SRC) or {}).get("amount") or 0)
    total = pw._asset_totals(fresh).get(aid, 0)
    print("    200 | الهدف %d | المصدر %d | مجموع النوع %d (كان %d)"
          % (dst_now, src_now, total, total_before))
    if total != total_before:
        print("    ⚠️ المجموع اتغيّر — بنبلّغ وبنتوقف قبل أي طلب تاني.")
        raise SystemExit(3)
    return True


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "RAIDER38830"
    token = pc.account_token(account)
    t = tree(account)
    a, b = t.by_id.get(DST) or {}, t.by_id.get(SRC) or {}
    if not a or not b:
        print("الرصتين مش في الشجرة.")
        return
    aid = str(a.get("gameAssetId"))
    qa, qb = int(a["amount"]), int(b["amount"])
    cell_a = t.parent.get(DST)
    total_before = pw._asset_totals(t).get(aid, 0)
    print("الهدف %s=%d (خانة %s) | المصدر %s=%d | مجموع %d"
          % (DST[:8], qa, (cell_a or "")[:8], SRC[:8], qb, total_before))
    variants = [
        ("V1: زيادة + تصفير في نفس الطلب",
         [{"discriminator": "update", "instanceId": DST, "amount": qa + qb},
          {"discriminator": "update", "instanceId": SRC, "amount": 0}]),
        ("V2: زيادة + delete للمصدر",
         [{"discriminator": "update", "instanceId": DST, "amount": qa + qb},
          {"discriminator": "delete", "instanceId": SRC}]),
        ("V3: زيادة الهدف ومعها etag",
         [{"discriminator": "update", "instanceId": DST, "amount": qa + qb,
           "etag": str(a.get("etag") or "")}]),
        ("V4: عقدة عنصر كاملة (asset + durability + etag)",
         [{"discriminator": "update", "instanceId": DST, "amount": qa + qb,
           "gameAssetId": int(a.get("gameAssetId") or 0),
           "durability": int(a.get("durability") or 1),
           "maxDurability": int(a.get("maxDurability") or 1),
           "etag": str(a.get("etag") or "")}]),
        ("V5: تصفير المصدر لوحده",
         [{"discriminator": "update", "instanceId": SRC, "amount": 0}]),
    ]
    for label, muts in variants:
        try:
            if try_post(token, muts, label, t, aid, total_before):
                print("\n*** الشكل ده اتقبل وقفلنا السلسلة — نتحقق من الشجرة قبل أي تجربة.")
                return
        except SystemExit:
            raise
        except Exception as exc:
            print("    خطأ:", repr(exc)[:160])
        time.sleep(0.6)
    print("\n== مفيش شكل اتقبل ==")


if __name__ == "__main__":
    main()
