"""اختبار التقسيم الرسمي: نقصان المصدر بـ update + رصة جديدة بـ create في نفس الطلب.

اكتشاف 2026-10-31 (inspection/probe_create_shape.py): `create` موجود في قاموس mutate
وبيقبل الحقول دي بالظبط — instanceId / gameAssetId / amount / slots (أي اسم تاني بيتجاهله
الـ parser، والحقل المعروف بقيمة من نوع غلط بيرجع UNKNOWN بدل ZERO_AMOUNT).
يعني العميل هو اللي بيولّد الآيدي الجديد، والسيرفر بيقبله.

كل الأشكال تحت مبنية على **حفظ الوحدات**: النقصان = الزيادة، فالمجموع ما بيتغيّرش.
لو أي شكل اترفض البوابة بتلغي الطلب كله (مقيس في الدمج: الزيادة لوحدها اترفضت
والمخزن ما اتحرّكش)، وبنقرأ الشجرة تاني بعد كل محاولة للتأكد.

مسار: python inspection/probe_split_pair.py [الحساب] [اسم العنصر] [الكمية المفصولة]
"""
import sys, os, json, time, uuid, collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import pioneer_client as pc, pioneer_write as pw, pioneer_tree as pt, store

conn = store.db()


def snapshot(tree, aid):
    stacks = [(iid, int(n.get("amount") or 0), tree.parent.get(iid, ""))
              for iid, n in tree.by_id.items() if str(n.get("gameAssetId") or "") == aid]
    return sum(q for _, q, _ in stacks), stacks


def free_cells(tree, container_id):
    """الخانات الفاضية جوه كونتينر معيّن (عقدة slots=[] من غير أطفال)."""
    out = []
    for iid in tree.by_id.get(container_id, {}).get("slots") or []:
        if not tree.kids.get(str(iid)):
            out.append(str(iid))
    return out


def roots(tree):
    """الكونتينرات الكبيرة: الستاش / الشنطة / الأوفر فلو — اللي أبوها مفيش."""
    return [iid for iid in tree.by_id if not tree.parent.get(iid)]


def find_container(tree, label_needles):
    for iid in roots(tree):
        name = (tree.name_of(iid) or tree.label(iid)).lower()
        if all(n in name for n in label_needles):
            return iid
    for iid in tree.by_id:
        if iid in tree.parent:
            continue
        name = (tree.name_of(iid) or "").lower()
        if all(n in name for n in label_needles):
            return iid
    return ""


def try_send(account, mutations, label, src, aid, take):
    request = {"mutations": mutations, "requestId": ""}
    before_tree = pt.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    total_before, stacks_before = snapshot(before_tree, aid)
    src_before = dict((s, q) for s, q, _ in stacks_before)
    try:
        response = pc.post_json(pw._url(), request, token=pc.account_token(account))
        verdict = "200 مقبول"
    except pc.PioneerError as exc:
        print("   [%s] مرفوض: %s" % (label, str(exc)[:220]))
        pw._log(conn, account, {"kind": "probe", "ids": [src], "amount": take,
                                "mutations": mutations}, "probe_refused",
                {"error": str(exc)[:400]}, 1)
        return None
    time.sleep(1.2)
    after_tree = pt.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    total_after, stacks_after = snapshot(after_tree, aid)
    after_ids = set(s for s, _, _ in stacks_after)
    created = [i for i in after_ids if i not in src_before]
    removed = [i for i in src_before if i not in after_ids]
    print("   [%s] %s | مجموع %d → %d | جديد: %s | راح: %s"
          % (label, verdict, total_before, total_after,
             [(c[:8], int((after_tree.by_id[c]).get("amount") or 0),
               (after_tree.parent.get(c) or "بلا أب")[:8]) for c in created],
             [(r[:8], src_before[r]) for r in removed]))
    pw._log(conn, account, {"kind": "probe", "ids": [src], "amount": take,
                            "mutations": mutations}, "probe_ok",
            {"total_before": total_before, "total_after": total_after,
             "created": created, "removed": removed}, 1)
    return {"response": response, "total_before": total_before, "total_after": total_after,
            "created": created, "removed": removed, "tree": after_tree}


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "RAIDER38830"
    needle = (sys.argv[2] if len(sys.argv) > 2 else "electrical").lower()
    take = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    tree = pt.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    cands = [(iid, int(n.get("amount") or 0), str(n.get("gameAssetId") or ""))
             for iid, n in tree.by_id.items()
             if needle in (tree.name_of(iid) or "").lower() and int(n.get("amount") or 0) > take]
    if not cands:
        print("مفيش رصة فيها '%s' أكبر من %d عند %s" % (needle, take, account))
        return
    src, qty, aid = cands[0]
    # البوابة بترجّع gameAssetId كرقم (int) — لو انبعته نص بيحصل نفس فشل التحليل
    # اللي بيرجع UNKNOWN، فكل الأشكال دي بتبعته رقم.
    aid_int = int(aid)
    name = tree.name_of(src)
    cell = tree.parent.get(src, "")
    container = tree.parent.get(cell, "")
    print("المصدر: %s ×%d | id=%s | الخانة=%s | الكونتينر=%s (%s) | النوع=%s"
          % (name, qty, src[:8], cell[:8] if cell else "أوفر فلو",
             container[:8] if container else "—",
             tree.name_of(container) if container else "بلا أب", aid))
    print("مجموع النوع: %d" % snapshot(tree, aid)[0])

    # خانات فاضية متاحة في نفس الكونتينر (ولو مفيش، في الستاش)
    cells = free_cells(tree, container) if container else []
    stash = find_container(tree, ("stash",))
    if not cells:
        cells = free_cells(tree, stash)
    print("خانات فاضية متاحة: %d" % len(cells))

    print("\n== T1: نقصان المصدر + create بلا أب (القطعة الجديدة تروح الأوفر) ==")
    new_id = str(uuid.uuid4())
    got = try_send(account, [
        {"discriminator": "update", "instanceId": src, "amount": qty - take},
        {"discriminator": "create", "instanceId": new_id, "gameAssetId": aid_int, "amount": take},
    ], "T1", src, aid, take)
    if got and got["total_after"] == got["total_before"] and got["created"]:
        print("\nT1 نجح — التقسيم بقى حقيقي.")
        return

    print("\n== T2: نفس الزوج + تركيب الخانة على الآيدي الجديد (slots) ==")
    if cells:
        fresh = pt.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
        node = fresh.by_id.get(src) or {}
        now_qty = int(node.get("amount") or 0)
        target = cells[0]
        new_id2 = str(uuid.uuid4())
        cell_node = fresh.by_id.get(target) or {}
        kids = [str(k) for k in (cell_node.get("slots") or [])]
        try_send(account, [
            {"discriminator": "update", "instanceId": src, "amount": max(now_qty - take, 1)}
            if now_qty > take else {"discriminator": "delete", "instanceId": src},
            {"discriminator": "create", "instanceId": new_id2, "gameAssetId": aid_int, "amount": take},
            {"discriminator": "update", "instanceId": target, "amount": 1,
             "slots": kids + [new_id2]},
        ], "T2", src, aid, take)
    else:
        print("   مفيش خانة فاضية — T2 اتخطّى.")

    print("\n== T3: create بحقل slots فاضي صراحة (شكل العقدة الكامل) ==")
    fresh = pt.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    node = fresh.by_id.get(src) or {}
    now_qty = int(node.get("amount") or 0)
    if now_qty > take:
        try_send(account, [
            {"discriminator": "update", "instanceId": src, "amount": now_qty - take},
            {"discriminator": "create", "instanceId": str(uuid.uuid4()), "gameAssetId": aid_int,
             "amount": take, "slots": [], "durability": int(node.get("durability") or 0),
             "maxDurability": int(node.get("maxDurability") or 0)},
        ], "T3", src, aid, take)
    else:
        print("   المصدر بقى أصغر من الكمية — اتخطّى.")


if __name__ == "__main__":
    main()
