# -*- coding: utf-8 -*-
"""أوراكل «الامتصاص»: هل البوابة بتدمج كومين لما كوم يبتلع التاني كابن؟

الشكل: `update(الكوم المتلقي, slots=[الكوم المصدر], amount=N)` — نفس صيغة النقل
المعروفة (الخانة = حاوية بـ slots)، بس بدل خانة بنستخدم كوم نفسه. لو البوابة
بتفسّر slots على الكوم كـ«ابتلاع»، هدمج الكومين في واحد.

الاختيار:账户 RAIDER60766 — Crude Explosives (1 + 1 + 1، الحد 10). أسوأ سيناريو
ممكن: نخسر وحدة واحدة من عنصر رخيص. كل محاولة بتتقرأ بعدها الشجرة فورًا، ولو
المجموع اتغيّر بنوقف.

    python -m inspection.probe_absorb RAIDER60766 1625205858
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "RAIDER60766"
ASSET = sys.argv[2] if len(sys.argv) > 2 else "1625205858"


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
                    "parent": str(t.parent.get(str(iid)) or "")})
    return sorted(out, key=lambda s: -s["amount"])


def total(t):
    return sum(s["amount"] for s in stacks(t))


def post(muts, label):
    try:
        resp = pc.post_json(pw._url(), {"mutations": muts, "requestId": ""},
                            token=pc.account_token(ACCOUNT))
        print("  [%s] 200 %s" % (label, json.dumps(resp, ensure_ascii=False)[:300]))
        return True
    except Exception as exc:
        print("  [%s] REFUSED %s" % (label, str(exc)[:260]))
        return False


def main():
    t0 = tree()
    st = stacks(t0)
    print("الحالة:", json.dumps(st, ensure_ascii=False), "| المجموع", total(t0))
    if len(st) < 2:
        print("مفيش كومين.")
        return
    dst, src = st[0], st[1]
    merged = dst["amount"] + src["amount"]
    shapes = [
        ("A1 absorb amount=1", {"discriminator": "update", "instanceId": dst["iid"],
                                "slots": [src["iid"]], "amount": 1}),
        ("A2 absorb amount=merged", {"discriminator": "update", "instanceId": dst["iid"],
                                     "slots": [src["iid"]], "amount": merged}),
        ("A3 absorb+target", {"discriminator": "update", "instanceId": dst["iid"],
                              "slots": [src["iid"]], "amount": 1,
                              "targetInstanceId": src["iid"]}),
        ("A4 absorb both orders", {"discriminator": "update", "instanceId": src["iid"],
                                   "slots": [dst["iid"]], "amount": 1}),
    ]
    for label, mut in shapes:
        before = total(tree())
        ok = post([mut], label)
        time.sleep(0.6)
        t1 = tree()
        after = total(t1)
        print("     %d -> %d | %s" % (before, after, json.dumps(stacks(t1), ensure_ascii=False)))
        if after != before:
            print("     >>> المجموع اتغيّر! وقف.")
            return
        if ok and len(stacks(t1)) < len(stacks(t0)):
            print("     >>>Reduction في الأكوام! ")
    print("\nfinal:", json.dumps(stacks(tree()), ensure_ascii=False))


if __name__ == "__main__":
    main()
