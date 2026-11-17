# -*- coding: utf-8 -*-
"""أوراكل لايف على ش形ل الدمج الحقيقي — على الكومين اللي فاضل إدخالهم (13 + 5).

الهدف: نكتشف هل بوابة Embark بتقبل نقل كمية من كوم لكوم. الفرق عن كل
الأوراكل اللي فاتت: هنا الآيديز حقيقية والكميات معروفة، فأي طلب بيتقبل
بيغيّر الحالة فعلاً — فبنقفل بعد كل محاولة: نقرأ الشجرة وبنطبع مجموع العنصر
والأكوام، ولو المجموع اتغيّر ((io) عناصر ضاعت أو اتزادت) بنوقف فوراً.

الأشكال المتجربة بالترتيب (كل واحد لوحده):
  A) المتلقي absorbs المصدر: update(dst, slots=[src], amount=18)
  B) نقل صريح: update(src, targetInstanceId=dst, amount=5)
  C) تعيين كمية مع هدف: update(dst, amount=18, targetInstanceId=src)
  D) delete + update (الحلمة الحقيقية:Gluing): update(dst,amount=18) ثم delete(src)

العنصر المختار: Heavy Ammo على G18 (13 + 5 = 18 وحد الحصة 47).

    python -m inspection.probe_merge_live2 G18
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G18"
ASSET = "-1402742438"          # Heavy Ammo على G18


def tree():
    return pioneer_tree.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])


def stacks(t):
    out = []
    for iid, row in t.by_id.items():
        if row.get("slots"):
            continue
        if str(row.get("gameAssetId") or "") != ASSET:
            continue
        out.append({"iid": str(iid), "amount": int(row.get("amount") or 0),
                    "parent": str(t.parent.get(str(iid)) or ""),
                    "cap": int(row.get("stackSize") or 0)})
    return sorted(out, key=lambda s: -s["amount"])


def total(t):
    return sum(s["amount"] for s in stacks(t))


def post(muts, label):
    body = {"mutations": muts, "requestId": ""}
    token = pc.account_token(ACCOUNT)
    try:
        resp = pc.post_json(pw._url(), body, token=token)
        print("  [%s] 200 %s" % (label, json.dumps(resp, ensure_ascii=False)[:400]))
        return True, resp
    except Exception as exc:
        print("  [%s] REFUSED %s" % (label, str(exc)[:320]))
        return False, None


def main():
    t0 = tree()
    st = stacks(t0)
    print("الحالة:", json.dumps(st, ensure_ascii=False))
    print("المجموع:", total(t0))
    if len(st) < 2:
        print("مفيش كومين للتجربة.")
        return
    dst = st[0] if st[0]["amount"] >= st[1]["amount"] else st[1]
    src = st[1] if dst is st[0] else st[0]
    want = dst["amount"] + src["amount"]
    cap = dst["cap"] or src["cap"]
    print("\nالهدف: %s (%d) + %s (%d) = %d  [الحد %d]"
          % (dst["iid"][:8], dst["amount"], src["iid"][:8], src["amount"], want, cap))
    if cap and want > cap:
        print("المجموع أكبر من الحد — الدمج الكامل مش هينفع، هنجرب نقل جزئي.")
    if not cap:
        print("مفيش stackSize — هنجرب برضه.")

    shapes = [
        ("A absorb", [{"discriminator": "update", "instanceId": dst["iid"],
                       "slots": [src["iid"]], "amount": want}]),
        ("B transfer", [{"discriminator": "update", "instanceId": src["iid"],
                         "targetInstanceId": dst["iid"], "amount": src["amount"]}]),
        ("C set+target", [{"discriminator": "update", "instanceId": dst["iid"],
                           "amount": want, "targetInstanceId": src["iid"]}]),
    ]
    for label, muts in shapes:
        before = total(tree())
        ok, _ = post(muts, label)
        time.sleep(0.6)
        t1 = tree()
        after = total(t1)
        print("     المجموع %d -> %d | %s" % (before, after, json.dumps(stacks(t1), ensure_ascii=False)))
        if after != before:
            print("     >>> المجموع اتغيّر! وقف الفحص فورًا.")
            return
        if ok:
            print("     >>> الطلب اتقبل — بنفحص الشكل ده أكتر.")
    print("\nfinal:", json.dumps(stacks(tree()), ensure_ascii=False))


if __name__ == "__main__":
    main()
