# -*- coding: utf-8 -*-
"""قياس لايف: هل تقدر بوابة Embark تعمل دمج حقيقي للأكوام (stack merge)؟

الفكرة اللي لازم تتثبت: التحويل الناقص (partial transfer) — يعني نقص كوم من
الخانة المصدر ونزيد نفس العدد في الخانة الوجهة، والمجمول ثابت.

الترتيب آمن: أي خطوة فيها نقص بتسبق الزيادة، وكل طلب بيتأكد منه بمجمول العنصر
قبل وبعد. لو البوابة رفضت، مفيش حاجة اتلمست أصلاً.

    python -m inspection.probe_merge_amount
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402


def live_tree():
    data = pc.fetch_inventory_for(ACCOUNT)
    return pioneer_tree.Tree((data or {}).get("items") or [])


def stacks(tree, asset):
    """كل (خانة، آيتم، كمية) لنفس الأسيت جوه الستاش."""
    lay = pioneer_tree.layout(tree)
    out = []
    for cell in lay["stash"]["slots"]:
        cell = str(cell)
        item = tree.first_child(cell)
        row = tree.by_id.get(item) or {}
        if str(row.get("gameAssetId")) == asset and not row.get("slots"):
            out.append((cell, item, int(row.get("amount") or 1)))
    return out


def total(tree, asset):
    return sum(int(r.get("amount") or 0) for r in tree.by_id.values()
               if str(r.get("gameAssetId")) == asset and not r.get("slots"))


def post(muts, label):
    body = {"mutations": muts, "requestId": ""}
    token = pc.account_token(ACCOUNT)
    try:
        resp = pc.post_json(pw._url(), body, token=token)
        print("  [%s] OK %s" % (label, json.dumps(resp, ensure_ascii=False)[:700]))
        return {"ok": True, "resp": resp}
    except Exception as exc:
        print("  [%s] REFUSED %s" % (label, str(exc)[:500]))
        return {"ok": False, "err": str(exc)}


ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "ELCONEJOMALO"


def main():
    asset = sys.argv[2] if len(sys.argv) > 2 else "-1580114534"   # Fabric
    tree = live_tree()
    st = stacks(tree, asset)
    print("العنصر %s (%s): %d كوم — %s — المجمول %d"
          % (asset, tree.name_of(st[0][1]) if st else "?", len(st),
             [(i, a) for _, i, a in st], total(tree, asset)))
    if len(st) < 2:
        print("محتاج كومين على الأقل.")
        return
    (cell_a, item_a, amt_a), (cell_b, item_b, amt_b) = st[0], st[1]
    limit = None
    row = tree.by_id.get(item_a) or {}
    print("عقدة الآيتم نفسها:", json.dumps(row, ensure_ascii=False)[:500])

    print("\n== 1) no-op: نفس الـamount بالظبط (صفر أثر) ==")
    r = post([{"discriminator": "update", "instanceId": item_a, "amount": amt_a}],
             "noop")
    if not r["ok"]:
        print("الـno-op مرفوض => تعديل الكمية مقفول خالص.")
        return
    t2 = live_tree()
    print("   المجمول بعد الـno-op:", total(t2, asset), "(لازم يفضل", total(tree, asset), ")")

    print("\n== 2) نقص 1 من كوم المصدر (خسارة حدّها عنصر واحد) ==")
    t3 = live_tree()
    cur = int((t3.by_id.get(item_b) or {}).get("amount") or 0)
    if cur != amt_b:
        item_b = stacks(t3, asset)[1][1]
        cur = stacks(t3, asset)[1][2]
    before = total(t3, asset)
    post([{"discriminator": "update", "instanceId": item_b, "amount": cur - 1,
           "slots": [""]}], "minus1")
    time.sleep(0.6)
    t4 = live_tree()
    after_minus = total(t4, asset)
    got = int((t4.by_id.get(item_b) or {}).get("amount") or -1)
    print("   كوم المصدر بقى %s — المجمول %d -> %d" % (got, before, after_minus))
    if got != cur - 1:
        print("   يعني الـamount على الآيتم مالوش أثر (أو اتغير بشكل تاني).")

    print("\n== 3) زيادة 1 على نفس الكوم (الرجوع) ==")
    post([{"discriminator": "update", "instanceId": item_b, "amount": cur,
           "slots": [""]}], "restore")
    time.sleep(0.6)
    t5 = live_tree()
    print("   المجمول النهائي:", total(t5, asset), " (الأصلي", total(tree, asset), ")")
    print("   الكوم:", [(i, a) for _, i, a in stacks(t5, asset)])

    print("\n== 4) نقل ناقص في طلب واحد: المصدر -27 والوجهة +27 ==")
    t6 = live_tree()
    st6 = stacks(t6, asset)
    if len(st6) < 2:
        print("في كوم واحد دلوقتي — اتلغى.")
        return
    (ca, ia, aa), (cb, ib, ab) = st6[0], st6[1]
    before = total(t6, asset)
    res = post([{"discriminator": "update", "instanceId": ib, "amount": 1, "slots": [""]},
                {"discriminator": "update", "instanceId": ia, "amount": aa + ab,
                 "slots": [""]}], "merge-one-way")
    time.sleep(0.8)
    t7 = live_tree()
    after = total(t7, asset)
    print("   المجمول %d -> %d | الكوم الجديدة %s" % (before, after,
          [(i, a) for _, i, a in stacks(t7, asset)]))
    if after != before:
        print("   !! الفرق %d — لازم نرجع حالاً." % (after - before))


if __name__ == "__main__":
    main()
