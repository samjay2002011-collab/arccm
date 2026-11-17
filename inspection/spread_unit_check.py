# -*- coding: utf-8 -*-
"""اختبار بلا أي كتابة: spread_plan على شجرة صناعية (خانات ستاش معروفة).

    python -m inspection.spread_unit_check
"""
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_tree as pt  # noqa: E402

ASSET = "999000111"
FOREIGN = "999000222"


class Fake(pt.Tree):
    """شجرة صناعية: التسميات معطاة يدويًا عشان layout() يلاقي الستاش."""

    def __init__(self, items, labels):
        pt.Tree.__init__(self, items)
        self._map = labels

    def label(self, iid):
        return self._map.get(str(iid), pt.Tree.label(self, iid))


def build(cells, ours, foreign=(), loose=0):
    """cells=عدد الخانات، ours={رقم الخانة: كمية}، foreign=[كمية...] للخانات المتبقية."""
    items = [{"instanceId": "root", "gameAssetId": "ROOT", "slots": ["stash_slot"]}]
    items.append({"instanceId": "stash_slot", "gameAssetId": "SLOT", "slots": ["stash"]})
    cell_ids = ["c%02d" % i for i in range(cells)]
    items.append({"instanceId": "stash", "gameAssetId": "CONTAINER", "slots": cell_ids})
    labels = {"root": "Inventory Root", "stash_slot": "Stash Container Slot",
              "stash": "Stash Container"}
    for i, cid in enumerate(cell_ids):
        slot = []
        if i in ours:
            items.append({"instanceId": "s%d" % i, "gameAssetId": ASSET,
                          "amount": ours[i], "slots": []})
            slot = ["s%d" % i]
            labels["s%d" % i] = "Our Stack"
        elif foreign:
            items.append({"instanceId": "f%d" % i, "gameAssetId": FOREIGN,
                          "amount": 7, "slots": []})
            slot = ["f%d" % i]
            labels["f%d" % i] = "Foreign Stack"
        items.append({"instanceId": cid, "gameAssetId": "CELL", "amount": 1, "slots": slot})
        labels[cid] = "Stash Cell"
    for k in range(loose):
        # أوفر فلو = عناصر ملهاش أب في الشجرة الرسمية
        items.append({"instanceId": "loose%d" % k, "gameAssetId": ASSET,
                      "amount": 3 + k, "slots": []})
        labels["loose%d" % k] = "Our Stack"
    return Fake(items, labels)


def check(name, cond, extra=""):
    print("%-4s %s%s" % ("ok" if cond else "FAIL", name, (" | " + extra) if extra else ""))
    return bool(cond)


def main():
    ok = True

    # أ) 3 أكوام في الستاش + واحد طالع من الأوفر، و17 خانة فاضية
    tree = build(20, {0: 5, 1: 4, 2: 3}, loose=1)
    plan = pt.spread_plan(tree, ASSET)
    targets = [m["target_wrapper_id"] for m in plan["moves"]]
    ok &= check("A يتحرك كل كوم طليق ويزيح الزحمة", len(plan["moves"]) == 3, str(plan["moves"]))
    ok &= check("A أهداف متمايزة", len(set(targets)) == len(targets))
    ok &= check("A الأهداف كانت خانات فاضية فعلًا",
                all(not tree.first_child(t) for t in targets))
    ok &= check("A مفيش كوم اتحرك مرتين",
                len({i for m in plan["moves"] for i in m["instance_ids"]}) == len(targets))
    ok &= check("A أربع خانات أهداف", len(plan["targets"]) == 4, str(plan["targets"]))
    ok &= check("A التباعد أكبر من واحد", plan["gap"] > 1, "gap=%s" % plan["gap"])
    gaps = [b - a for a, b in zip(plan["targets"], plan["targets"][1:])]
    ok &= check("A كل الجيران على بعد gap على الأقل", min(gaps) >= plan["gap"], str(gaps))
    ok &= check("A ثابتة = الأكوام اللي مكانها كويس", plan["kept"] == 1, "kept=%s" % plan["kept"])

    # ب) الأوفر فلو لوحده: الخانات الفاضية كافية
    tree = build(20, {}, loose=4)
    plan = pt.spread_plan(tree, ASSET)
    ok &= check("ب أربع نقلات من الأوفر للستاش", len(plan["moves"]) == 4,
                "targets=%s" % plan["targets"])
    ok &= check("ب أهداف متباعدة", min(b - a for a, b in
                                       zip(plan["targets"], plan["targets"][1:])) >= plan["gap"])

    # ج) ستاش مليان: مفيش خانة فاضية → رفض برقم صحيح مش سالب
    tree = build(20, {0: 1, 1: 1, 2: 1, 3: 1}, foreign=[9] * 16, loose=2)
    try:
        pt.spread_plan(tree, ASSET)
        ok &= check("ج الرفض لازم يطلع", False)
    except pt.TreeError as exc:
        ok &= check("ج السبب not_enough_cells", exc.error == "not_enough_cells", exc.detail)
        ok &= check("ج الرقم موجب", "ناقصك 2" in exc.detail, exc.detail)

    # د) مفرود بالفعل → صفر نقلات ورسالة أوضح
    tree = build(20, {0: 9, 10: 8, 19: 7})
    plan = pt.spread_plan(tree, ASSET)
    ok &= check("د مفيش حركة", plan["moves"] == [] and "تتحرّك" in plan["detail"], plan["detail"])

    # هـ) كوم واحد بس → مفيش حاجة تتفرّد
    try:
        pt.spread_plan(build(20, {4: 9}), ASSET)
        ok &= check("ه الرفض لازم يطلع", False)
    except pt.TreeError as exc:
        ok &= check("ه السبب nothing_to_spread", exc.error == "nothing_to_spread")

    # و) الكميات ما بتتغيرش: مفيش أي amount في مخرجات الخطة
    tree = build(12, {0: 5, 1: 4, 2: 3, 3: 2}, loose=1)
    plan = pt.spread_plan(tree, ASSET)
    flat = str(plan["moves"])
    ok &= check("و مفيش تعديل كمية في الطلب", "amount" not in flat, flat[:120])
    ok &= check("و كل حركة بتحدد خانة واحدة وعنصر واحد",
                all(len(m["instance_ids"]) == 1 and m["target_container"] == "stash"
                    for m in plan["moves"]))

    print("\n%s" % ("كل الاختبارات عدّت" if ok else "فيه فشل — صلّح قبل لايف"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
