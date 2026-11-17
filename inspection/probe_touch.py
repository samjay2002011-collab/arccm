# -*- coding: utf-8 -*-
"""هل "لمس" القطعة بنفس قيمتها يغيّر حاجة في الشجرة؟

الفكرة اللي بتتاختبار: زرار UPDATE في رامبارت بيغيّر id القطعة، والاحتمال إن
اللي بيصلح موضوع "القطعة بتظهر في الماتش بعد ما أرجع للوبي" مش الـ id الجديد
نفسه — لكن إن سيرفر Embark حدّث سجل القطعة (updatedAt/etag)، فالكلَاينت بيشوف
إن نسخته القديمة اتقادمة وبيسحبها من جديد.

الاختبار بيبعت update بنفس الـ slots ونفس الـ amount بالظبط (كتابة محايدة:
مفيش عنصر بيتحرك ولا كمية بتتغيّر) وبيقارن الشجرة قبل وبعد سطر بسطر.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "RAIDER33368"


def snap():
    data = pc.fetch_inventory_for(ACCOUNT) or {}
    tree = pioneer_tree.Tree(data.get("items") or [])
    state, stamp, tags = {}, {}, {}
    for iid, row in tree.by_id.items():
        state[iid] = (str(tree.parent.get(iid) or ""), int(tree.amount(iid) or 1),
                      tuple(str(s) for s in (row.get("slots") or [])),
                      str(row.get("gameAssetId")))
        stamp[iid] = int(row.get("updatedAt") or 0)
        tags[iid] = str(row.get("etag") or "")
    return tree, state, stamp, tags, {str(k): v for k, v in (data or {}).items() if k != "items"}


def main():
    print("writes paused?", pioneer_write.paused())
    tree, before, stamp_before, tag_before, meta_before = snap()
    lay = pioneer_tree.layout(tree)
    cands = []
    for wrapper in (lay["backpack"].get("slots") or []):
        wid = str(wrapper.get("wrapper") if isinstance(wrapper, dict) else wrapper)
        item = tree.first_child(wid)
        if item:
            cands.append(("backpack", wid, str(item)))
    for key, eq in (lay["loadout"].get("slots") or {}).items():
        for wrapper in eq:
            wid = str(wrapper.get("wrapper") if isinstance(wrapper, dict) else wrapper)
            item = tree.first_child(wid)
            if item:
                cands.append(("loadout:" + str(key), wid, str(item)))
    if not cands:
        print("مفيش حاجة مجهّزة في الشنطة/اللوداوت — اختار حساب فيه تجهيز.")
        return
    where, cell, target = cands[0]
    row = tree.by_id[target]
    print("القطعة: %s  asset=%s  في %s" % (tree.label(target), row.get("gameAssetId"), where))
    print("  item instanceId=%s amount=%s" % (target, row.get("amount")))
    print("  cell instanceId=%s slots=%s amount=%s" % (cell, tree.children(cell), tree.amount(cell)))
    print("  item  etag=%s updatedAt=%s" % (tag_before.get(target), stamp_before.get(target)))
    print("  cell  etag=%s updatedAt=%s" % (tag_before.get(cell), stamp_before.get(cell)))

    # الشكل القانوني الوحيد: تعديل الخانة (wrapper) بنفس قيمتها بالظبط — مفيش
    # عنصر بيتحرك ولا كمية بتتغيّر. تعديل العقدة بتاعة العنصر نفسه مرفوض.
    req = {"mutations": [{"discriminator": "update", "instanceId": cell,
                          "slots": [target], "amount": tree.amount(cell)}], "requestId": ""}
    print("\n→ POST %s\n  %s" % (pioneer_write._url(), req))
    token = pc.account_token(ACCOUNT)
    try:
        resp = pc.post_json(pioneer_write._url(), req, token=token)
        err = None
    except Exception as exc:                      # noqa: BLE001
        resp, err = None, str(exc)[:300]
    if err:
        print("  مرفوض:", err)
        return
    print("  رد البوابة: %s" % str(resp)[:500])

    tree2, after, stamp_after, tag_after, meta_after = snap()
    moved = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
    bumped = {k: (stamp_before.get(k), stamp_after.get(k)) for k in stamp_after
              if stamp_before.get(k) != stamp_after.get(k)}
    retagged = {k: (tag_before.get(k), tag_after.get(k)) for k in tag_after
                if tag_before.get(k) != tag_after.get(k)}
    print("\n=== النتيجة ===")
    print("عناصر اتغيّر مكانها أو كميتها: %d %s" % (len(moved), moved[:6]))
    print("عناصر اتغيّر updatedAt: %d" % len(bumped))
    for k, (a, b) in list(bumped.items())[:8]:
        print("   %s %s -> %s  (%s)" % (k[:12], a, b, tree2.label(k)[:26]))
    print("عناصر اتغيّر etag: %d" % len(retagged))
    for k, (a, b) in list(retagged.items())[:8]:
        print("   %s %s -> %s  (%s)" % (k[:12], a, b, tree2.label(k)[:26]))
    print("meta الرد اتغيّر: %s" % (meta_before != meta_after))
    print("  before: %s" % str(meta_before)[:260])
    print("  after : %s" % str(meta_after)[:260])


main()
