# -*- coding: utf-8 -*-
"""بيختبر فرضية الدمج على مسار `update` المقبول — من غير كلمة combine.

اللي مقيس: البوابة بتعرف `update` (بينقل بين الخانات) وبترفض أي `amount` جديد على
عقدة العنصر، و`combine` بيردّ UNKNOWN زي الاسم المضروب بالظبط. في المقابل شجرة اللعبة
نفسها بتقول إن الخانة (الـwrapper) ليها `amount` مجموعي، ورامبارت بتعمل الدمج على
سيرفرها. الفرضية هنا: لو حطّيت رصتين من نفس النوع في **نفس الخانة** بـ
`slots=[a, b]` و`amount = مجموعهم`، السيرفر نفسه يوحّدهم في رصة واحدة — وده مسار رسمي
مش محتاج صلاحيات أعلى.

    python -m inspection.probe_combine_update --list          # قراءة فقط
    python -m inspection.probe_combine_update --try A B       # كتابة محسوبة (قطعتين)
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402
from backend import pioneer_tree  # noqa: E402
from backend import pioneer_write as pw  # noqa: E402

ACCOUNT = "RAIDER38830"


def tree():
    data = pc.fetch_inventory_for(ACCOUNT) or {}
    return pioneer_tree.Tree(data.get("items") or [])


def candidates():
    """أزواج من نفس النوع في خانتين مختلفتين، والمجموع تحت سقف الرصة."""
    t = tree()
    out = []
    for iid, node in t.by_id.items():
        if node.get("slots"):
            continue
        cell = t.parent.get(iid) or ""
        cap = int(node.get("maxStack") or node.get("stackSize") or 0)
        out.append((iid, cell, node))
    by_asset = {}
    for iid, cell, node in out:
        by_asset.setdefault(str(node.get("gameAssetId")), []).append((iid, cell, node))
    pairs = []
    for aid, items in by_asset.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ia, ca, na), (jb, cb, nb) = items[i], items[j]
                if ca == cb or not ca or not cb:
                    continue
                qty_a, qty_b = int(na.get("amount") or 0), int(nb.get("amount") or 0)
                pairs.append((aid, ia, ca, qty_a, jb, cb, qty_b))
    return pairs, t


def show():
    t = tree()
    sample = next((n for n in t.by_id.values() if not n.get("slots")), {})
    print("== مفاتيح عقدة عنصر كاملة ==")
    print(json.dumps(sample, indent=1)[:700])
    print("\n== مفاتيح خانة (wrapper) ==")
    cell = next((t.parent.get(i) for i, n in t.by_id.items() if not n.get("slots")), "")
    print(cell, json.dumps(t.by_id.get(cell, {}), indent=1)[:700])
    pairs, _ = candidates()
    print("\n== أزواج مرشحة (%d) ==" % len(pairs))
    for aid, ia, ca, qa, jb, cb, qb in pairs[:25]:
        print("   asset=%-12s %s:%d (خانة %s) + %s:%d (خانة %s)"
              % (aid, ia[:8], qa, ca[:8], jb[:8], qb, cb[:8]))


def attempt(src, dst):
    """يكتب التجربة دي بحذر: يحفظ حالة الخانتين الأول ويرجّعهم لو النتيجة مش اندماج نظيف."""
    t = tree()
    a, b = t.by_id.get(src) or {}, t.by_id.get(dst) or {}
    if not a or not b:
        print("الآيد مش في الشجرة")
        return
    ca, cb = t.parent.get(src), t.parent.get(dst)
    if not ca or not cb or ca == cb:
        print("الرصتين مش في خانتين مختلفتين — مفيش اختبار.")
        return
    original = {ca: list(t.kids.get(ca) or []), cb: list(t.kids.get(cb) or [])}
    total = int(a.get("amount") or 0) + int(b.get("amount") or 0)
    token = pc.account_token(ACCOUNT)
    print("المصدر %s (%d) في %s | الهدف %s (%d) في %s | المجموع %d"
          % (src[:8], int(a.get("amount") or 0), ca[:8], dst[:8],
             int(b.get("amount") or 0), cb[:8], total))
    print("حالة الخانتين الأصلية:", {k[:8]: [i[:8] for i in v] for k, v in original.items()})
    before = pw._asset_totals(t).get(str(a.get("gameAssetId")), 0)

    body = {"mutations": [{"discriminator": "update", "instanceId": ca,
                           "slots": original[ca] + [dst],
                           "amount": total}], "requestId": ""}
    print("الجسم:", json.dumps(body))
    try:
        resp = pc.post_json(pw._url(), body, token=token)
        print("ردّ 200:", json.dumps(resp)[:300])
    except pc.PioneerError as exc:
        print("المنبع رفض:", json.dumps(pw._gateway_error(exc, "combine"),
                                        ensure_ascii=False)[:500])
        return
    fresh = tree()
    after = pw._asset_totals(fresh).get(str(a.get("gameAssetId")), 0)
    print("مجموع النوع: قبل %d | بعد %d" % (before, after))
    merged = None
    for iid in (src, dst):
        node = fresh.by_id.get(iid)
        state = "راحت" if not node else "amount=%s في خانة %s" % (node.get("amount"),
                                                                 (fresh.parent.get(iid) or "")[:8])
        print("   %s -> %s" % (iid[:8], state))
        if node and int(node.get("amount") or 0) == total:
            merged = iid
    gone = [iid for iid in (src, dst) if iid not in fresh.by_id]
    if merged and len(gone) == 1 and after == before:
        print("\n*** اندماج نظيف: رصة واحدة amount=%d في خانة %s"
              % (total, (fresh.parent.get(merged) or "")[:8]))
        return
    print("\nالنتيجة مش اندماج نظيف — برجّع الخانتين لأصلهم…")
    back = pw._state_mutations(fresh, original)
    print("رجوع:", json.dumps(back))
    try:
        pc.post_json(pw._url(), {"mutations": back, "requestId": ""}, token=token)
        restored = tree()
        print("بعد الرجوع:", {k[:8]: [i[:8] for i in (restored.kids.get(k) or [])]
                             for k in original})
    except pc.PioneerError as exc:
        print("!! الرجوع رفضه المنبع — لازم تتأكد من اللعبة:",
              json.dumps(pw._gateway_error(exc, "restore"), ensure_ascii=False)[:300])


def main():
    args = sys.argv[1:]
    if "--try" in args:
        i = args.index("--try")
        attempt(args[i + 1], args[i + 2])
    else:
        show()


if __name__ == "__main__":
    main()
