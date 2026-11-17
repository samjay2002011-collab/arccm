# -*- coding: utf-8 -*-
"""قياس الأشكال اللي بيبعتها rampart فعلياً على بوابة Embark: split و combine و stack_merge.

الترتيب round-trip عشان مابقاش في خسارة: نفصل 10 من كوم 50 (split)، وبعدين نرجّع
العشرة دي لنفس الكوم (combine). المجمول لازم يفضل 50 في كل خطوة، وبنقايصه قدام.

    python -m inspection.probe_split_combine
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "ELCONEJOMALO"
ASSET = sys.argv[2] if len(sys.argv) > 2 else "-1580114534"   # Fabric


def tree():
    return pioneer_tree.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])


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


def total(t):
    return sum(int(r.get("amount") or 0) for r in t.by_id.values()
               if str(r.get("gameAssetId")) == ASSET and not r.get("slots"))


def post(label, muts):
    t0 = tree()
    before = total(t0)
    body = {"mutations": muts, "requestId": ""}
    try:
        resp = pc.post_json(pw._url(), body, token=pc.account_token(ACCOUNT))
        upd = ((resp.get("changeset") or {}).get("items") or {})
        print("%-14s OK" % label)
        for key in ("created", "updated", "deleted"):
            rows = upd.get(key) or []
            if rows:
                print("   %s: %s" % (key, json.dumps(
                    [{k: r.get(k) for k in ("instanceId", "gameAssetId", "amount", "slots")
                      if r.get(k) is not None} for r in rows], ensure_ascii=False)[:600]))
        ok = True
    except Exception as exc:
        print("%-14s %s" % (label, str(exc)[:420]))
        ok = False
    time.sleep(0.7)
    t1 = tree()
    st = [(i[:8], a) for _, i, a in stacks(t1)]
    print("   مجموع %d -> %d | أكوام %s" % (before, total(t1), st))
    return ok, total(t1) - before


def main():
    t = tree()
    st = stacks(t)
    print("الأكوام:", [(i[:8], a) for _, i, a in st], "المجمول", total(t))
    lay = pioneer_tree.layout(t)
    empty = [str(c) for c in lay["stash"]["slots"] if not t.first_child(str(c))]
    print("خانات فاضية:", len(empty))
    if not st or not empty:
        print("محتاج كوم وخانة فاضية.")
        return
    big = max(st, key=lambda s: s[2])
    cell, item, amt = big
    base = tree()
    orig_total = total(base)

    print("\n== 1) split: افصل 10 من كوم %d في خانة فاضية ==" % amt)
    ok, d = post("split", [{"discriminator": "split", "instanceId": item,
                            "targetWrapperId": empty[0], "amount": 10}])
    if not ok:
        print("   جرّب version تانية بنفس الشكل مع amount في الخانة:")
        post("split+etags", [{"discriminator": "split", "instanceId": item,
                              "targetWrapperId": empty[0], "amount": 10,
                              "etag": (base.by_id.get(item) or {}).get("etag") or ""}])
        return
    if d != 0:
        print("   !! الفرق %d — وقّفنا وحاولنا نرجّع." % d)

    t2 = tree()
    st2 = stacks(t2)
    ten = [s for s in st2 if s[2] == 10 and s[1] != item]
    keep = [s for s in st2 if s[1] == item]
    print("\n== 2) combine: ارجع العشرة للكوم الأساسي ==")
    if ten and keep:
        post("combine", [{"discriminator": "combine", "instanceId": ten[0][1],
                          "targetInstanceId": keep[0][1], "amount": 10}])
    else:
        print("   مفيش كوم 10 جديد — الأشكال اتغيرت:", st2)

    t3 = tree()
    print("\nالرجوع للحالة الأصلية: مجموع %d (كان %d) | %s"
          % (total(t3), orig_total, [(i[:8], a) for _, i, a in stacks(t3)]))

    print("\n== 3) stack_merge global (من غير أي آيدي) ==")
    all_before = sum(int(r.get("amount") or 0) for r in tree().by_id.values()
                     if not r.get("slots"))
    post("stack_merge", [{"discriminator": "stack_merge"}])
    t4 = tree()
    all_after = sum(int(r.get("amount") or 0) for r in t4.by_id.values() if not r.get("slots"))
    print("مجموع كل العناصر %d -> %d" % (all_before, all_after))


if __name__ == "__main__":
    main()
