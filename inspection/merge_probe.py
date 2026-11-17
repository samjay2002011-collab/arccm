# -*- coding: utf-8 -*-
"""فحص أكوام العنصر الواحد على بوابة Embark الرسمية + تجربة دمج حقيقي.

--dump  قراءة فقط: بيطبع كل عنصر عنده أكوام أكتر من واحدة — الكمية، الحد
        (stackSize)، والمكان (خانة ستاش / أوفر فلو / شنطة).

--probe بيجرّب أشكال الطلب اللي ممكن تخلي البوابة تدمج كوم في كوم (رمي كوم
        على خانة فيها كوم من نفس النوع) وبيقيس الشجرة قبل/بعد بالظبط:
        مجموع النوع لازم يفضل زي ما هو، وعدد الأكوام لازم يقل، ومفيش فقد.
        من غير --apply بيطبع الطلب بس وما بيبعتش حاجة.

    python -m inspection.merge_probe G18 --dump
    python -m inspection.merge_probe G18 --probe --apply
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

MUTATE_PATH = "/v1/pioneer/inventory/v1/mutate"


def load(account):
    data = pc.fetch_inventory_for(account) or {}
    tree = pioneer_tree.Tree(data.get("items") or [])
    lay = pioneer_tree.layout(tree)
    stash_cells = set(str(c) for c in lay["stash"]["slots"])
    stacks = []
    for iid, row in tree.by_id.items():
        if row.get("slots"):
            continue
        amount = int(row.get("amount") or 0)
        if amount <= 0:
            continue
        parent = tree.parent.get(iid) or ""
        place = "stash" if parent in stash_cells else ("overflow" if not parent else "other")
        stacks.append({"iid": iid, "asset": str(row.get("gameAssetId") or ""),
                       "name": tree.name_of(iid), "amount": amount,
                       "cap": int(row.get("stackSize") or 0), "cell": parent,
                       "place": place, "etag": str(row.get("etag") or "")})
    return tree, stacks


def groups(stacks):
    out = {}
    for row in stacks:
        out.setdefault(row["asset"], []).append(row)
    return {aid: rows for aid, rows in out.items() if len(rows) > 1}


def dump(account, only_stackable=False, owed_only=False):
    tree, stacks = load(account)
    print("== أكوام (%d عنصر) ==" % len(stacks))
    for aid, rows in sorted(groups(stacks).items(),
                            key=lambda kv: sum(r["amount"] for r in kv[1])):
        cap = max([r["cap"] for r in rows] + [r["amount"] for r in rows])
        if only_stackable and cap <= 1:
            continue
        rows = sorted(rows, key=lambda r: -r["amount"])
        units = sum(r["amount"] for r in rows)
        ideal = [cap] * (units // cap) + ([units % cap] if units % cap else [])
        if owed_only and sorted(r["amount"] for r in rows) == sorted(ideal):
            continue
        print("\n%s  [%s]  إجمالي %d  الحد %d  الأكوام %d  المثالي %s" %
              (rows[0]["name"] or aid, aid, units, cap, len(rows), "+".join(str(i) for i in ideal)))
        for r in rows:
            print("   %-38s %4d  %-9s cell=%s" % (r["iid"], r["amount"], r["place"], r["cell"][:8]))


def pick_pair(rows):
    """ destination: كوم في خانة ستاش فيه مكان؛ source: كوم تاني أصغر منه."""
    dst = None
    for r in rows:
        if r["place"] == "stash" and r["cap"] > r["amount"]:
            if dst is None or r["amount"] > dst["amount"]:
                dst = r
    if dst is None:
        for r in rows:
            if r["place"] == "stash":
                dst = dst or r
    if dst is None:
        return None, None
    src = None
    for r in rows:
        if r["iid"] == dst["iid"]:
            continue
        if src is None or r["amount"] < src["amount"]:
            src = r
    return dst, src


def shape_bodies(dst, src):
    """الأشكال المحتملة للدمج على البوابة."""
    return [
        ("A: رمي الكوم في خانة الكوم (slots)", {
            "discriminator": "update", "instanceId": dst["cell"],
            "slots": [src["iid"]], "amount": 1}),
        ("B: تحديث الكوم نفسه بـ parentId", {
            "discriminator": "update", "instanceId": src["iid"],
            "parentId": dst["cell"], "amount": src["amount"]}),
        ("C: targetInstanceId على الكوم", {
            "discriminator": "update", "instanceId": src["iid"],
            "targetInstanceId": dst["iid"], "amount": src["amount"]}),
        ("D: combine مباشر", {
            "discriminator": "combine", "instanceId": src["iid"],
            "targetInstanceId": dst["iid"], "amount": src["amount"]}),
        ("E: stack_merge عام", {"discriminator": "stack_merge"}),
    ]


def totals(rows, asset):
    sel = [r for r in rows if r["asset"] == asset]
    return sum(r["amount"] for r in sel), len(sel)


def probe(account, apply=False, dst_id="", src_id="", only=""):
    tree, stacks = load(account)
    g = groups(stacks)
    if not g:
        print("مفيش عنصر عنده أكوام أكتر من واحدة.")
        return
    # نختار العنصر اللي مجموعه أصغر — أقل مخاطرة في أي تجربة.
    aid, rows = min(g.items(), key=lambda kv: sum(r["amount"] for r in kv[1]))
    if dst_id:
        rows = [r for r in stacks if r["iid"] == dst_id] + \
               [r for r in rows if r["iid"] != dst_id]
        aid = rows[0]["asset"]
    dst, src = pick_pair(rows)
    if dst_id:
        dst = next((r for r in stacks if r["iid"] == dst_id), dst)
    if src_id:
        src = next((r for r in stacks if r["iid"] == src_id), src)
    if not dst or not src:
        print("مفيش زوج مناسب للتجربة في العنصر ده.")
        return
    units_before, count_before = totals(stacks, aid)
    print("العنصر: %s [%s]  إجمالي %d في %d أكوام  الحد %d" %
          (dst["name"], aid, units_before, count_before, dst["cap"]))
    print("الهدف : %s  %d (خانة %s)" % (dst["iid"], dst["amount"], dst["cell"][:8]))
    print("المصدر: %s  %d (%s)" % (src["iid"], src["amount"], src["place"]))
    token = pc.account_token(account)
    if not token:
        print("مفيش توكن.")
        return
    for label, mut in shape_bodies(dst, src):
        if only and not label.startswith(only):
            continue
        body = {"mutations": [mut], "requestId": ""}
        print("\n--- %s" % label)
        print("    %s" % json.dumps(body, ensure_ascii=False))
        if not apply:
            print("    (بدون --apply — ما بتبعتش)")
            continue
        try:
            response = pc.post_json(MUTATE_PATH, body, token=token)
            print("    رد: %s" % json.dumps(response, ensure_ascii=False)[:300])
        except Exception as exc:
            print("    رفض: %s" % str(exc)[:300])
        tree2, stacks2 = load(account)
        units_after, count_after = totals(stacks2, aid)
        d2 = next((r for r in stacks2 if r["iid"] == dst["iid"]), None)
        s2 = next((r for r in stacks2 if r["iid"] == src["iid"]), None)
        print("    بعد: الهدف %s | المصدر %s | الأكوام %d->%d | المجموع %d->%d" % (
            (d2 or {}).get("amount"), (s2 or {}).get("amount"),
            count_before, count_after, units_before, units_after))
        if count_after < count_before and units_after == units_before:
            print("    ✔ دمج حقيقي: اتجمع كومين في واحد والمجموع سليم.")
            print("    بعد التجربة كاملة:")
            for r in sorted([x for x in stacks2 if x["asset"] == aid],
                            key=lambda r: -r["amount"]):
                print("      %-38s %4d %s" % (r["iid"], r["amount"], r["place"]))
            return
        if count_after != count_before or units_after != units_before:
            print("    ! تغيير في الشجرة — بنوقف هنا.")
            for r in sorted([x for x in stacks2 if x["asset"] == aid],
                            key=lambda r: -r["amount"]):
                print("      %-38s %4d %s" % (r["iid"], r["amount"], r["place"]))
            return


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    if "--dump" in sys.argv:
        dump(account, only_stackable="--stacks" in sys.argv,
             owed_only="--owed" in sys.argv)
        return
    if "--probe" in sys.argv:
        def arg(flag):
            return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else ""
        probe(account, apply="--apply" in sys.argv, dst_id=arg("--dst"),
              src_id=arg("--src"), only=arg("--only"))
        return
    dump(account)


if __name__ == "__main__":
    main()
