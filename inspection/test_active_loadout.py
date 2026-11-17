# -*- coding: utf-8 -*-
"""بلا كتابة: اللوحة لازم تعرض الشنطة الي اللعبة بتقرأها فعلاً.

الحالات منسوخة من لايف 2026-10-29 على تلات حسابات:
  أ) الخانة المجهّزة بتشاور على الحاوية القياسية، وفي شجرة أوجمنت تانية مليانة
     عناصر. الموقع القديم كان بيهرب للشجرة المليانة، فالكتابة كانت بتختفي من
     الستاش وماابتباناش في الماتش.
  ب) مفيش أوجمنت مجهّز والخانة المجهّزة لسه شايلة آخر أوجمنت اتلمس (شجرة فاضية)،
     والشنطة الحيّة — اللي فيها غنائم الرايد — في شجرة "Equipped Loadout" تانية.
     متابعة المؤشر لوحدها كانت بتعرض اللوحة فاضية والنبات في شنطة اللعبة.
  ج) أوجمنت مجهّز: شجرته هي الوجهة.
  د) مفيش مؤشر خالص: يرجع لأحدث شجرة فيها عناصر وبيحذّر (pointed=False).
  هـ) حاويات ما بعد الكتابة: خانة الأوجمنت (برّه شجرة اللوداوت) مقبولة، وشجرة
     الأوجمنت التانية المخفية مرفوضة — عكسها كان بيرفض تجهيز الأوجمنت ويرجّعه.
"""
import sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")
from backend import pioneer_tree as pt

NEW = 2_000_000_000_000_000_000
OLD = 1_000_000_000_000_000_000


class Fake(pt.Tree):
    def __init__(self, items, labels, updated):
        pt.Tree.__init__(self, items)
        self._labels, self._updated = labels, updated

    def label(self, iid):
        return self._labels.get(str(iid), pt.Tree.label(self, iid))

    def _row(self, iid):
        row = dict(pt.Tree._row(self, iid) or {})
        row.setdefault("updatedAt", self._updated.get(str(iid), OLD))
        return row


def build(pointer="base", base_under_inv=False, augment="", base_cells=(), preset_cells=(),
          pointer_name="", aug_cells=()):
    """شجرة مصغّرة: Inventory Root + ستاش + خانة مجهّزة + شنطة قياسية + شجرة أوجمنت.

    pointer: الحاوية الي الخانة المجهّزة شايلتها ("base" أو "preset").
    base_cells / preset_cells: خانات الشنطة، None = خانة فاضية.
    pointer_name: اسم تاني للحاوية المجهّزة (المؤشر بيعرف يفضل لسه ماسك أوجمنت قديم).
    aug_cells: خانات شنطة شجرة الأوجمنت المجهّز نفسها (جذر مستقل باسمه).
    """
    items = [{"instanceId": "inv", "gameAssetId": "ROOT",
              "slots": ["eq_slot", "stash_slot", "aug_slot", "preset"]
                      + (["base"] if base_under_inv else [])},
             {"instanceId": "eq_slot", "gameAssetId": "SLOT", "slots": [pointer]},
             {"instanceId": "stash_slot", "gameAssetId": "SLOT", "slots": ["stash"]},
             {"instanceId": "stash", "gameAssetId": "CONT", "slots": ["st1"]},
             {"instanceId": "st1", "gameAssetId": "CELL", "slots": ["ammo"]},
             {"instanceId": "ammo", "gameAssetId": "999000111", "amount": 30, "slots": []},
             {"instanceId": "aug_slot", "gameAssetId": "SLOT",
              "slots": [augment] if augment else []}]
    labels = {"inv": "Inventory Root", "eq_slot": "Equipped Loadout Container Slot",
              "stash_slot": "Stash Container Slot", "stash": "Stash VIII", "st1": "Slot 1",
              "ammo": "Light Ammo", "aug_slot": "Equipped Augment Slot"}
    updated = {"stash": NEW if preset_cells or base_cells else OLD}

    def loadout(node, name, bag, cells):
        slot = "%s_s" % bag
        items.append({"instanceId": node, "gameAssetId": "CONT", "slots": [slot]})
        items.append({"instanceId": slot, "gameAssetId": "SLOT", "slots": [bag]})
        container = {"instanceId": bag, "gameAssetId": "CONT", "slots": []}
        items.append(container)
        labels[node] = name
        labels[slot] = "%s Backpack Slot" % name
        labels[bag] = "%s Backpack" % name
        for i, c in enumerate(cells):
            cid = c or ("%s_free%d" % (bag, i))
            container["slots"].append(cid)
            labels[cid] = "Slot %d" % (i + 1)
            if c is None:
                items.append({"instanceId": cid, "gameAssetId": "CELL", "slots": []})
                continue
            items.append({"instanceId": cid, "gameAssetId": "CELL", "slots": [c + "_i"]})
            items.append({"instanceId": c + "_i", "gameAssetId": "99900%03d" % i,
                          "amount": 3, "slots": []})
            labels[c + "_i"] = "Candleberries"
        updated[bag] = NEW if any(cells) else OLD

    loadout("base", "Equipped Loadout", "base_bp", base_cells)
    loadout("preset", "Looting Mk. 3 (Survivor)", "preset_bp", preset_cells)
    if pointer_name:
        labels["preset"] = pointer_name
        labels["preset_s"] = "%s Backpack Slot" % pointer_name
        labels["preset_bp"] = "%s Backpack" % pointer_name
    if aug_cells:
        # شجرة الأوجمنت المجهّز: جذر مستقل، وبيكتب اسمه "MK." بس اللوداوت "Mk." — نفس الاسم
        loadout("augtree", "Looting MK. 3 (Survivor)", "augtree_bp", aug_cells)
    if augment:
        items.append({"instanceId": augment, "gameAssetId": "303567898", "amount": 1, "slots": []})
        labels[augment] = "Looting Mk. 3 (Survivor)"
    return Fake(items, labels, updated)


def bag_of(tree):
    return pt.layout(tree)["backpack"]["container"]


# أ) المؤشر على الحاوية القياسية — يفضل عليها حتى وهي فاضية وشجرة الأوجمنت مليانة
t = build("base", base_cells=(None, None), preset_cells=("p1",))
lay = pt.layout(t)
assert lay["loadout"]["name"] == "Equipped Loadout", lay["loadout"]
assert bag_of(t) == "base_bp", bag_of(t)
assert lay["loadout"]["pointed"] is True, lay["loadout"]
assert pt.equipped_container(t) == "base", pt.equipped_container(t)
body, _, _, _ = pt.plan_move(t, ["ammo"], "backpack")
assert all(s["target"].startswith("base_") for s in body["steps"]), body["steps"]
print("أ — الكتابة والعرض على الحاوية المجهّزة حتى وهي فاضية")

# ب) مفيش أوجمنت، والمؤشر لسه ماسك شجرة أوجمنت فاضية: الشنطة الحيّة في القياسية
t = build("preset", base_under_inv=True, base_cells=("b1", "b2", None), preset_cells=(None, None))
lay = pt.layout(t)
assert lay["loadout"]["mode"] == "base", lay["loadout"]
assert lay["loadout"]["name"] == "Equipped Loadout", lay["loadout"]
assert bag_of(t) == "base_bp", bag_of(t)
assert lay["loadout"]["pointed"] is True, lay["loadout"]
assert pt.equipped_container(t) == "base", pt.equipped_container(t)
body, _, _, _ = pt.plan_move(t, ["ammo"], "backpack")
assert all(s["target"].startswith("base_") for s in body["steps"]), body["steps"]
print("ب — من غير أوجمنت اللوحة بتعرض شنطة اللعبة نفسها وبتكتب فيها")

# ج) أوجمنت مجهّز: شجرته هي الوجهة، والمؤشر بيتّبع
t = build("preset", base_under_inv=True, base_cells=("b1",), preset_cells=("p1",),
          augment="aug_item")
lay = pt.layout(t)
assert lay["loadout"]["mode"] == "equipped", lay["loadout"]
assert bag_of(t) == "preset_bp", bag_of(t)
print("ج — والأوجمنت المجهّز بياخد شجرته زي الأول")

# د) مفيش مؤشر خالص: أحدث شجرة فيها عناصر، مع تحذير إن الاختيار تخمين
t = build("preset", base_under_inv=False, base_cells=("b1",), preset_cells=("p1", "p2"))
t.kids["eq_slot"] = []
lay = pt.layout(t)
assert lay["loadout"]["mode"] == "active_tree", lay["loadout"]
assert bag_of(t) == "base_bp", bag_of(t)
assert lay["loadout"]["pointed"] is False, lay["loadout"]
print("د — ومن غير أي حاوية معروفة بيدور على الأحدث وبيحذّر")
# هـ) حارس ما بعد الكتابة: كل خانات اللوحة مقبولة، وشجرة الأوجمنت التانية لأ
t = build("preset", base_under_inv=True, base_cells=("b1", "b2", None), preset_cells=("p1",))
nodes = pt.active_containers(t)


def in_any(cell):
    return any(pt.in_subtree(t, cell, n) for n in nodes)


lay = pt.layout(t)
assert in_any("aug_slot"), nodes          # خانة الأوجمنت برّه شجرة اللوداوت deliberately
assert in_any("base_bp") and in_any("base_bp_free2"), nodes
assert not in_any("preset_bp"), nodes     # الحاوية المخفية لسه مرفوضة
for key, slots in lay["loadout"]["slots"].items():
    assert all(in_any(s["wrapper"]) for s in slots), (key, nodes)
assert all(in_any(s["wrapper"]) for s in lay["backpack"]["slots"]), nodes
print("هـ — حارس التحقق بيقبل خانة الأوجمنت ويرفض اللوداوت التاني")

# و) أوجمنت مجهّز والمؤشر لسه ماسك شنطة أوجمنت تاني (لايف G22/G14 2026-11-05):
#    اللوحة والكتابة يروحوا شجرة الأوجمنت نفسه، مش الحاوية القديمة الفاضية.
t = build("preset", base_under_inv=True, pointer_name="Looting Mk. 2",
          preset_cells=(None, None), augment="aug_item", aug_cells=("a1", None))
lay = pt.layout(t)
assert lay["loadout"]["mode"] == "augment_loadout", lay["loadout"]
assert lay["loadout"]["name"] == "Looting MK. 3 (Survivor)", lay["loadout"]
assert bag_of(t) == "augtree_bp", bag_of(t)
assert lay["loadout"]["pointed"] is True, lay["loadout"]
assert pt.equipped_container(t) == "augtree", pt.equipped_container(t)
body, _, _, _ = pt.plan_move(t, ["ammo"], "backpack")
assert all(s["target"].startswith("augtree_") for s in body["steps"]), body["steps"]
print("و — والمؤشر الغلط بيتتصالح معاه: الأوجمنت المجهّز بياخد شجرته بالاسم")
print("OK — الشنطة الي بتبان في اللعبة هي نفسها الي بتبان وتكتب في اللوحة")
