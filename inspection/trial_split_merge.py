# -*- coding: utf-8 -*-
"""تجربة حقيقية على G18: combine → split → stack_merge، وكل خطوة بتتقاس على البوابة.

مفيش أي فقدان: بعد كل طلب بنعيد قراءة الشجرة ونتأكد إن مجموع الوحدات لنفس العنصر
ما اتغيّرش (الدمج والتفكيك نقل كميات، مش إنشاء/إلغاء). لو أي مجموع تحرّك
السكربت بيقف فورًا وبيطبع الحالة.

    python -m inspection.trial_split_merge G18
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G18"
TOKEN = pc.account_token(ACCOUNT)
WATCH = {}          # asset_id -> الاسم، للعناصر اللي بنتجرب عليها


def tree():
    return pioneer_tree.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])


def units(t, asset):
    return sum(int(r.get("amount") or 0) for r in t.by_id.values()
               if str(r.get("gameAssetId")) == asset and not r.get("slots"))


def stacks(t, asset):
    out = []
    for i, r in t.by_id.items():
        if str(r.get("gameAssetId")) == asset and not r.get("slots"):
            out.append((i, int(r.get("amount") or 1), r.get("parentId") or ""))
    return sorted(out, key=lambda s: -s[1])


def empty_cell(t):
    lay = pioneer_tree.layout(t)
    for cell in lay.get("stash", {}).get("slots") or []:
        cell = str(cell)
        if not t.first_child(cell):
            return cell
    return ""


def reason(exc):
    text = str(exc)
    try:
        body = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception:
        return text[:200]
    return "%s %s" % (body.get("reason") or body.get("detail") or "?",
                      str(body.get("message") or "")[:60])


def attempt(label, muts, asset, base_units):
    t0 = tree()
    before = units(t0, asset)
    print("\n>> %s" % label)
    print("   الجسم: %s" % json.dumps(muts, ensure_ascii=False)[:220])
    try:
        resp = pc.post_json(pw._url(), {"mutations": muts, "requestId": ""}, token=TOKEN)
        cs = (resp.get("changeset") or {}).get("items") or {}
        print("   200 created=%s updated=%s deleted=%s" % (
            [(r.get("instanceId", "")[:8], r.get("amount")) for r in (cs.get("created") or [])],
            [(r.get("instanceId", "")[:8], r.get("amount")) for r in (cs.get("updated") or [])],
            [str(x)[:8] for x in (cs.get("deleted") or [])]))
    except Exception as exc:
        print("   مرفوض: %s" % reason(exc))
    time.sleep(0.6)
    t1 = tree()
    after = units(t1, asset)
    st = [(i[:8], a, ("stash" if p else "overflow")) for i, a, p in stacks(t1, asset)]
    print("   الأكوام دلوقتي: %s | المجمول %d -> %d" % (st, before, after))
    if after != base_units.get(asset, before):
        print("   ⚠⚠ مجموع الوحدات اتغيّر عن أساس %d — وقّفنا." % base_units.get(asset))
        raise SystemExit(1)
    return t1


def main():
    t = tree()
    # الهدّاف من الـ snapshot المحلي: Rubber Parts (خانتين في الستاش) وFabric (أوفر فلو)
    import sqlite3
    conn = sqlite3.connect(r"C:\Users\Administrator\Desktop\rr\data\rampart_local.db")
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "select asset_id,name,instance_id,qty,container,wrapper_id from instances "
        "where account=? and name in ('Rubber Parts','Fabric') and qty>0", (ACCOUNT,))]
    conn.close()
    by_asset = {}
    for r in rows:
        by_asset.setdefault(str(r["asset_id"]), []).append(r)
    assets = list(by_asset)
    if not assets:
        print("مفيش هدّاف على %s — جرّب اسم تاني." % ACCOUNT)
        return 1
    base = {}
    for a in assets:
        WATCH[a] = by_asset[a][0]["name"]
        base[a] = units(t, a)
        print("هدّف %-14s (%s) | أكوام %s | المجمول عند البوابة %d"
              % (WATCH[a], a, [(r["instance_id"][:8], r["qty"], r["container"]) for r in by_asset[a]], base[a]))

    rubber = next((a for a, n in WATCH.items() if n == "Rubber Parts"), None)
    fabric = next((a for a, n in WATCH.items() if n == "Fabric"), None)

    if rubber:
        st = stacks(t, rubber)
        if len(st) >= 2:
            src, samount, _ = st[-1]
            dst, damount, _ = st[0]
            attempt("combine: ادمج %d على %d (Rubber Parts)" % (samount, damount),
                    [{"discriminator": "combine", "instanceId": src,
                      "targetInstanceId": dst, "amount": samount}], rubber, base)
            t = tree()
            cell = empty_cell(t)
            st = stacks(t, rubber)
            if st and cell:
                big, bigamt, _ = st[0]
                attempt("split: افصل 1 من %d في خانة فاضية %s (Rubber Parts)" % (bigamt, cell[:8]),
                        [{"discriminator": "split", "instanceId": big,
                          "targetWrapperId": cell, "amount": 1}], rubber, base)
    if fabric:
        attempt("stack_merge: التجميع العام (هيأثر على كل العناصر اللي قابلة للتكويم)",
                [{"discriminator": "stack_merge"}], fabric, base)

    t = tree()
    print("\n== الحالة النهائية ==")
    for a, n in WATCH.items():
        print("  %-14s %s | المجمول %d (كان %d)" % (n, a, units(t, a), base[a]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
