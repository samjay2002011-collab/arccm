# -*- coding: utf-8 -*-
"""أوراكل «الخانة theologians»: خانة فيها أكومين من نفس العنصر — البوابة بتدمجهم؟

الشكل: `update(خانة, slots=[كوم1, كوم2], amount=2)` — نفس صيغة النقل المعروفة،
بس الخانة بتاخد عنصرين. لو البوابة بتعمل الدمج أوتوماتيك جوه الخانة (نفس
العنصر) هنلاقي الأكوام اتقفلت في كوم واحد.

الاختيار: Crude Explosives (1 + 1 + 1) على RAIDER60766 — أسوأ سيناريو نخسر
فيه وحدة واحدة من عنصر رخيص. كل محاولة بتتقرأ بعدها الشجرة فورًا.

    python -m inspection.probe_cellmerge RAIDER60766 1625205858
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
    cells = [s for s in st if s["parent"]]
    if len(st) < 2 or not cells:
        print("مفيش كومين في خانات.")
        return
    a = cells[0]
    b = next((s for s in st if s["iid"] != a["iid"]), None)
    shapes = [
        ("B1 cell two slots amount=2", {"discriminator": "update", "instanceId": a["parent"],
                                         "slots": [a["iid"], b["iid"]], "amount": 2}),
        ("B2 cell two slots amount=1", {"discriminator": "update", "instanceId": a["parent"],
                                         "slots": [a["iid"], b["iid"]], "amount": 1}),
        ("B3 cell two slots + target", {"discriminator": "update", "instanceId": a["parent"],
                                        "slots": [a["iid"], b["iid"]], "amount": 2,
                                        "targetInstanceId": b["iid"]}),
        ("B4 empty-ish cell + one", {"discriminator": "update", "instanceId": a["parent"],
                                     "slots": [b["iid"]], "amount": 1}),
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
    print("\nfinal:", json.dumps(stacks(tree()), ensure_ascii=False))


if __name__ == "__main__":
    main()
