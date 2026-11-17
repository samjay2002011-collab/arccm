# -*- coding: utf-8 -*-
"""أوراكل الأشكال: نجرّب أشكال بيمالوج مختلفة للدمج ونقرأ كود الخطأ المسمّى.

كل كود خطأ مسمّى (INVENTORY_ITEM_NOT_STACKABLE زي كده) بيقولنا أي فاليديتر
في البوابة هو اللي وقع — وده بيقربنا من الشكل المقبول من غير ما نلمس أي عنصر:
الطلبات المرفوضة مابتغيّرش حاجة.

    python -m inspection.probe_merge_shapes
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


def reason(text):
    try:
        i = text.index("{")
        return (json.loads(text[i:]).get("reason") or "?")
    except Exception:
        return (text or "?")[-70:]


def run(label, muts):
    t0 = tree()
    before = total(t0)
    try:
        resp = pc.post_json(pw._url(), {"mutations": muts, "requestId": ""},
                            token=pc.account_token(ACCOUNT))
        got = [(u.get("instanceId", "")[:8], u.get("amount"))
               for u in ((resp.get("changeset") or {}).get("items") or {}).get("updated") or []]
        print("%-34s ACCEPTED  updated=%s" % (label, got))
        res = "OK"
    except Exception as exc:
        print("%-34s %-32s" % (label, reason(str(exc))))
        res = "NO"
    time.sleep(0.35)
    t1 = tree()
    after = total(t1)
    if after != before:
        print("   !! المجمول اتغير %d -> %d" % (before, after))
    return res


def main():
    t = tree()
    st = stacks(t)
    (ca, ia, aa), (cb, ib, ab) = st[0], st[1]
    print("هدف %s(%d)  مصدر %s(%d)  المجمول %d\n" % (ia[:8], aa, ib[:8], ab, total(t)))

    print("== دمج بالأب = الآيتم الوجهة تبقى أب للمصدر ==")
    run("item_a slots=[item_b]", [{"discriminator": "update", "instanceId": ia,
                                  "slots": [ib], "amount": aa}])
    run("item_a slots=[item_b] amt sum", [{"discriminator": "update", "instanceId": ia,
                                          "slots": [ib], "amount": aa + ab}])
    run("item_b slots=[\"\"]", [{"discriminator": "update", "instanceId": ib, "slots": [""]}])
    run("cell_b فارغة + cell_a فيها الاتنين",
        [{"discriminator": "update", "instanceId": cb, "slots": [""], "amount": 1},
         {"discriminator": "update", "instanceId": ca, "slots": [ia, ib], "amount": 1}])
    run("cell_a slots=[ia] amount=sum", [{"discriminator": "update", "instanceId": ca,
                                         "slots": [ia], "amount": aa + ab}])

    print("\n== أنواع discriminator جديدة ==")
    for name, extra in [("move", {"targetInstanceId": ia, "amount": ab}),
                        ("stack", {"targetInstanceId": ia}),
                        ("merge", {"targetInstanceId": ia, "amount": ab}),
                        ("transfer", {"targetInstanceId": ia, "amount": ab}),
                        ("stack_merge", {"targetInstanceId": ia}),
                        ("consolidate", {"assetId": int(ASSET)}),
                        ("sort", {}), ("organize", {})]:
        mut = {"discriminator": name, "instanceId": ib}
        mut.update(extra)
        run("disc=%s" % name, [mut])

    print("\n== أشكال بأسماء حقول تانية على update ==")
    run("update targetInstanceId", [{"discriminator": "update", "instanceId": ib,
                                    "targetInstanceId": ia, "amount": ab}])
    run("update parentId", [{"discriminator": "update", "instanceId": ib, "parentId": ca,
                             "amount": ab}])
    run("update slots=null", [{"discriminator": "update", "instanceId": ib,
                               "slots": None, "amount": ab}])
    run("update amount=كل الكوم (no-op)", [{"discriminator": "update", "instanceId": ib,
                                            "amount": ab}])

    t2 = tree()
    print("\nالحالة: %s | المجمول %d" % ([(i[:8], a) for _, i, a in stacks(t2)], total(t2)))


if __name__ == "__main__":
    main()
