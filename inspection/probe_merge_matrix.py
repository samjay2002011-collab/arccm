# -*- coding: utf-8 -*-
"""تفصيل سبب الرفض: الـamount نفسه ولا الـslots اللي بعتناها معاه؟

مصفوفة 2×2 على كوم مصدر حقيقية (27 قماش) — كل محاولة لوحدها وبنقارن المجمول
قبل وبعد. أسوأ احتمال خسارة عنصر واحد، والطلبات المرفوضة مابيتلمس فيها حاجة.

    python -m inspection.probe_merge_matrix
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "ELCONEJOMALO"
ASSET = sys.argv[2] if len(sys.argv) > 2 else "-1580114534"


def tree():
    return pioneer_tree.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])


def total(t):
    return sum(int(r.get("amount") or 0) for r in t.by_id.values()
               if str(r.get("gameAssetId")) == ASSET and not r.get("slots"))


def stacks(t):
    lay = pioneer_tree.layout(t)
    out = []
    for cell in lay["stash"]["slots"]:
        cell = str(cell)
        item = t.first_child(cell)
        row = t.by_id.get(item) or {}
        if str(row.get("gameAssetId")) == ASSET and not row.get("slots"):
            out.append((cell, item, int(row.get("amount") or 1)))
    return out


def try_mut(label, mut):
    t0 = tree()
    before = total(t0)
    try:
        resp = pc.post_json(pw._url(), {"mutations": [mut], "requestId": ""},
                            token=pc.account_token(ACCOUNT))
        head = "OK"
        upd = ((resp.get("changeset") or {}).get("items") or {}).get("updated") or []
        detail = json.dumps([{k: r.get(k) for k in ("instanceId", "amount")} for r in upd])[:260]
    except Exception as exc:
        head, detail = "REFUSED", str(exc)[:200]
    time.sleep(0.5)
    t1 = tree()
    after = total(t1)
    mark = "=" if after == before else ("+%d" % (after - before))
    print("%-26s %-9s مجموع %d->%d(%s)  %s" % (label, head, before, after, mark, detail))
    return head == "OK", after - before


def main():
    t = tree()
    st = stacks(t)
    cell, item, amt = st[1]
    print("المصدر: خانة %s / آيتم %s / كمية %d | المجمول %d\n" % (cell[:8], item[:8], amt, total(t)))
    print("عقدة الخانة:", json.dumps({k: v for k, v in (t.by_id.get(cell) or {}).items()
                                      if k != "slots"})[:240])
    print("عقدة الآيتم:", json.dumps({k: v for k, v in (t.by_id.get(item) or {}).items()
                                      if k != "slots"})[:240], "\n")

    print("== A) كميات ناقصة/زائدة بدون slots ==")
    try_mut("amount=-1", {"discriminator": "update", "instanceId": item, "amount": amt - 1})
    try_mut("amount=+1", {"discriminator": "update", "instanceId": item, "amount": amt + 1})
    try_mut("amount=0", {"discriminator": "update", "instanceId": item, "amount": 0})
    try_mut("amount=-1 +slots", {"discriminator": "update", "instanceId": item,
                                 "amount": amt - 1, "slots": [""]})
    try_mut("amount=-1 +slots[item]", {"discriminator": "update", "instanceId": item,
                                       "amount": amt - 1, "slots": [item]})

    print("\n== B) تعديل الخانة (مسار النقل المعروف) مع كمية مختلفة ==")
    try_mut("cell slots+amount-1", {"discriminator": "update", "instanceId": cell,
                                    "slots": [item], "amount": amt - 1})
    try_mut("cell slots-only", {"discriminator": "update", "instanceId": cell,
                                "slots": [item]})
    try_mut("cell amount-only", {"discriminator": "update", "instanceId": cell, "amount": amt})

    print("\n== C) create نسخة ناقصة (مرفوض قبل كده، بنأكد دلوقتي) ==")
    try_mut("create amount=1", {"discriminator": "create", "gameAssetId": int(ASSET),
                                "amount": 1, "parentId": cell})

    print("\n== D) نقل جزئي: خانة فاضية + amount على المصدر ==")
    lay = pioneer_tree.layout(t)
    empt = [str(c) for c in lay["stash"]["slots"] if not t.first_child(str(c))]
    if empt:
        ok, d = try_mut("merge cell->empty", {"discriminator": "update",
                                              "instanceId": empt[0], "slots": [item],
                                              "amount": 1})
        print("    النتيجة:", ok, d)
    else:
        print("    مفيش خانة فاضية.")

    t2 = tree()
    print("\nالحالة النهائية: المجمول %d | %s" % (total(t2), [(i[:8], a) for _, i, a in stacks(t2)]))


if __name__ == "__main__":
    main()
