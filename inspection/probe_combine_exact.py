# -*- coding: utf-8 -*-
"""أوراكل شكل الدمج الحقيقي — بتجرّب الأنواع اللي بيبعتها Rampart بالضبط على بوابة Embark.

المسح القديم (probe_merge_shapes.py) جرّب stack_merge ومعاها targetInstanceId،
لكن كود Rampart نفسه بيبعت حاجتين تانيتين:
  • {"discriminator":"combine","instanceId":src,"targetInstanceId":dst,"amount":n}
  • {"discriminator":"stack_merge"} من غير أي حقول تانية خالص (زرار consolidate)
أي طلب مرفوض مابيغيّرش حاجة، فالأوراكل بيقارن مجموع الوحدات قبل وبعد كل محاولة.

    python -m inspection.probe_combine_exact RAIDER33368 -1580114534
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "RAIDER33368"
ASSET = sys.argv[2] if len(sys.argv) > 2 else "-1580114534"


def tree():
    return pioneer_tree.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])


def stacks(t):
    out = []
    for cell in t.children(str(pioneer_tree.layout(t)["stash"]["container"])):
        item = t.first_child(cell)
        row = t.by_id.get(item) or {}
        if str(row.get("gameAssetId")) == ASSET and not row.get("slots"):
            out.append((cell, str(item), int(row.get("amount") or 1)))
    return out


def total(t):
    return sum(int(r.get("amount") or 0) for r in t.by_id.values()
               if str(r.get("gameAssetId")) == ASSET and not r.get("slots"))


def reason(text):
    try:
        i = text.index("{")
        return (json.loads(text[i:]).get("reason") or "?")
    except Exception:
        return (text or "?")[-90:]


def run(label, muts):
    before, n_before = total(tree()), len(stacks(tree()))
    try:
        resp = pc.post_json(pw._url(), {"mutations": muts, "requestId": ""},
                            token=pc.account_token(ACCOUNT))
        upd = ((resp.get("changeset") or {}).get("items") or {}).get("updated") or []
        print("%-46s ACCEPTED updated=%s" % (label, [(u.get("instanceId", "")[:8],
                                                     u.get("amount")) for u in upd]))
    except Exception as exc:
        print("%-46s %s" % (label, reason(str(exc))))
    time.sleep(0.4)
    t1 = tree()
    after, n_after = total(t1), len(stacks(t1))
    if after != before or n_after != n_before:
        print("   ⚠ المجمول %d→%d وعدد الأكوام %d→%d" % (before, after, n_before, n_after))
    return after


def main():
    t = tree()
    st = sorted(stacks(t), key=lambda s: s[2])
    if len(st) < 2:
        print("مفيش أكتر من كوم واحد من العنصر ده في الستاش.")
        return 1
    cap = int((t.by_id.get(st[0][1]) or {}).get("stackSize") or 0)
    (ca, ia, aa), (cb, ib, ab) = st[0], st[1]
    print("هدف %s(%d)  مصدر %s(%d)  الحد=%s  المجمول %d في %d كوم\n"
          % (ia[:8], aa, ib[:8], ab, cap or "?", total(t), len(st)))

    print("== combine بنفس شكل Rampart ==")
    run("combine amount=0 (استطلاع الـenum)",
        [{"discriminator": "combine", "instanceId": ib, "targetInstanceId": ia, "amount": 0}])
    run("combine بدون amount",
        [{"discriminator": "combine", "instanceId": ib, "targetInstanceId": ia}])
    run("combine amount=%d (آمن: %d+%d)" % (ab, aa, ab),
        [{"discriminator": "combine", "instanceId": ib, "targetInstanceId": ia, "amount": ab}])
    run("combine لكل المصدر على هدف مليان",
        [{"discriminator": "combine", "instanceId": ib, "targetInstanceId": ia, "amount": ab}])

    print("\n== stack_merge bare زي زرار consolidate ==")
    run("stack_merge من غير أي حقول", [{"discriminator": "stack_merge"}])
    run("stack_merge + assetId", [{"discriminator": "stack_merge", "assetId": int(ASSET)}])

    print("\n== أسماء تانية ==")
    for name in ("merge", "stack", "consolidate", "stack_combine"):
        run("disc=%s combine-shape" % name,
            [{"discriminator": name, "instanceId": ib, "targetInstanceId": ia, "amount": ab}])

    t2 = tree()
    print("\nالحالة: %s | المجمول %d" % ([(i[:8], a) for _, i, a in stacks(t2)], total(t2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
