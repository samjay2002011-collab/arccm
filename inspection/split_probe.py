# -*- coding: utf-8 -*-
"""مسبار بلا أثر: يبعث طلبات مرفوضة بالقطع عشان يقرأ رسالة الخطأ بس.

    python -m inspection.split_probe G18

الكل بكميات مستحيلة (-1) أو بمعرّف غير موجود — البوابة بترفض قبل ما تلمس
أي حاجة في المخزن. الهدف: نفرّق بين "النوع مش معروف" و"النوع معروف والقيمة غلط"،
وده بيحدد هل تقسيم الأكوام متاح لتوكننا ولا لأ.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw, pioneer_tree  # noqa: E402


def pick(tree):
    """أكوم لها حد أعلى أكبر من 1 وكمية أكبر من 1 — مصدر معقول للتجربة."""
    best = None
    for iid, row in tree.by_id.items():
        amt = int(row.get("amount") or 0)
        if amt > 1 and not tree.children(iid) and tree.parent.get(iid):
            if best is None or amt > int(tree.by_id[best].get("amount") or 0):
                best = iid
    return best or ""


def slot_of(tree, iid):
    return tree.parent.get(iid) or ""


def send(url, token, body):
    try:
        data = pc.post_json(url, body, token=token)
        return {"sent": True, "accepted": True, "response": data}
    except pc.PioneerError as exc:
        return {"sent": True, "accepted": False, "code": getattr(exc, "code", None),
                "error": getattr(exc, "error", None), "detail": str(exc)[:260]}
    except Exception as exc:      # noqa: BLE001
        return {"sent": False, "error": type(exc).__name__, "detail": str(exc)[:260]}


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    if not token:
        print("مفيش توكن لـ %s" % account)
        return 1
    url = pw._url()
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    iid = pick(tree)
    if not iid:
        print("مفيش أكوام جاهزة للتجربة.")
        return 1
    wrapper = slot_of(tree, iid)
    row = tree.by_id[iid]
    print("المصدر: %s %s | كمية %d | الخانة %s" % (
        iid[:8], tree.name_of(iid), int(row.get("amount") or 0), wrapper[:8]))
    print("المسار: %s\n" % url)

    cases = [
        # الشكل المقبول فعلاً: instanceId = الخانة، وslots = أبنائها، وamount = محتواها.
        # كل الحالات بكمية مستحيلة (-1) فمفيش أي احتمال يتنفذ حاجة.
        ("control update بكمية -1", {"discriminator": "update", "instanceId": wrapper,
                                     "slots": pw._slots_payload([iid]), "amount": -1}),
        ("split بكمية -1", {"discriminator": "split", "instanceId": wrapper,
                            "slots": pw._slots_payload([iid]), "amount": -1}),
        ("combine بكمية -1", {"discriminator": "combine", "instanceId": wrapper,
                              "slots": pw._slots_payload([iid]), "amount": -1}),
        ("stack_merge بكمية -1", {"discriminator": "stack_merge", "instanceId": wrapper,
                                  "slots": pw._slots_payload([iid]), "amount": -1}),
        ("update بمعرف عنصر جديد", {"discriminator": "update", "instanceId": wrapper,
                                    "slots": ["11111111-1111-1111-1111-111111111111"], "amount": -1}),
        ("نوع مجهول", {"discriminator": "zzz_not_a_kind", "instanceId": wrapper,
                       "slots": pw._slots_payload([iid]), "amount": -1}),
    ]
    for label, mut in cases:
        res = send(url, token, {"mutations": [mut], "requestId": ""})
        print("%-28s → %s" % (label, json.dumps(res, ensure_ascii=False)[:300]))

    after = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    same = int(after.by_id[iid].get("amount") or 0) == int(row.get("amount") or 0)
    print("\nالمخزن بعد المسبار: %s | عدد العقد %d→%d | مجموع الوحدات %d→%d" % (
        "زي ما هو" if same and len(after.by_id) == len(tree.by_id) else "اتغيّر!!",
        len(tree.by_id), len(after.by_id),
        sum(int(v.get("amount") or 0) for v in tree.by_id.values()),
        sum(int(v.get("amount") or 0) for v in after.by_id.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
