# -*- coding: utf-8 -*-
"""اختبار الترقية الحقيقي على سلاح فيرو (Ferro) بس — بالمmaneuver واحد.

الحارس جوه: أي سلاح غير Ferro بيت رفض قبل أي طلب. الراتر والستيتشر مش
 허용 فيهم خالص.

  python inspection/upgrade_ferro_test.py            # انتظار + تقرير (بلا تنفيذ)
  python inspection/upgrade_ferro_test.py --run       # تنفيذ الترقية لفل 4
  python inspection/upgrade_ferro_test.py --run --to 2
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import pioneer_client as pc, pioneer_tree, store, weapon_tiers  # noqa: E402

ONLY_FAMILY = "BattleRifle_BreachAction_01"   # Ferro
FAMILY_LABEL = "Ferro"


def find_ferro(account, wait=0):
    """يدوّر على سلاح Ferro في الشجرة الحية (وبيستنى لو اتطلب)."""
    deadline = time.time() + max(0, wait)
    while True:
        data = pc.fetch_inventory_for(account) or {}
        tree = pioneer_tree.Tree(data.get("items") or [])
        hits = []
        for iid, node in tree.by_id.items():
            asset = str(node.get("gameAssetId") or "")
            if weapon_tiers.family_of(asset) != ONLY_FAMILY:
                continue
            hits.append({
                "instance_id": iid,
                "asset_id": asset,
                "level": weapon_tiers.level_of_asset(asset),
                "name": weapon_tiers.name_of(asset),
                "etag": node.get("etag"),
                "parent": tree.parent.get(iid),
                "durability": node.get("durability"),
                "max_durability": node.get("maxDurability"),
            })
        if hits or time.time() >= deadline:
            return data, tree, hits
        print("    ... في انتظار Ferro", flush=True)
        time.sleep(10)


def materials(account):
    data = pc.fetch_inventory_for(account) or {}
    tree = pioneer_tree.Tree(data.get("items") or [])
    counts = {}
    for node in tree.by_id.values():
        counts[str(node.get("gameAssetId"))] = counts.get(str(node.get("gameAssetId")), 0) + int(node.get("amount") or 0)
    return counts, tree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="نفّذ فعلياً")
    ap.add_argument("--to", type=int, default=4, help="الفل المطلوب")
    ap.add_argument("--wait", type=int, default=0, help="ثواني انتظار لو Ferro لسه مش موجود")
    ap.add_argument("--account", default="")
    args = ap.parse_args()

    conn = store.db()
    accounts = [r["name"] for r in store.list_accounts(conn, enabled_only=True)]
    account = args.account or (accounts[0] if accounts else "")
    conn.close()
    print("account:", account)
    if not account:
        print("[-] مفيش حساب")
        return 2

    data, tree, hits = find_ferro(account, args.wait)
    if not hits:
        print("[-] Ferro لسه مش موجود في الحساب. حطه في اللود آوت واعمل SYNC وجرّب تاني.")
        return 1
    for h in hits:
        print("[+] Ferro: %s | level %s | asset %s | etag %s | instance %s"
              % (h["name"], h["level"], h["asset_id"], h["etag"], h["instance_id"]))

    target = max(2, min(4, args.to))
    if hits[0]["level"] >= target:
        print("[!] السلاح خلاص في FL %s — مفيش ترقية." % hits[0]["level"])
        return 0

    counts, _ = materials(account)
    up = json.loads((ROOT / "data" / "weapon_upgrades.json").read_text(encoding="utf-8"))
    table = (up.get(FAMILY_LABEL) or {}).get("levels") or {}
    names = json.loads((ROOT / "data" / "upgrade_materials.json").read_text(encoding="utf-8"))
    print("\n== المتطلبات (من الجدول المحلي — البوابة هي المرجع) ==")
    for lvl in range(hits[0]["level"] + 1, target + 1):
        cost = (table.get(str(lvl)) or {}).get("cost") or {}
        parts = ", ".join("%s ×%d (عندك %d)" % ((names.get(k) or {}).get("name", k), v, counts.get(k, 0))
                          for k, v in cost.items())
        print("   FL %d: %s" % (lvl, parts or "مفيش"))

    if not args.run:
        print("\n(--run للتف تنفيذ فعلي)")
        return 0

    conn = store.db()
    try:
        from backend import pioneer_write
        out = pioneer_write.upgrade_item(conn, account, hits[0]["instance_id"], target)
    finally:
        conn.close()
    print("\n== نتيجة الترقية ==")
    print(json.dumps({k: v for k, v in out.items() if k not in ("result", "refreshed")},
                     ensure_ascii=False, indent=1)[:1200])
    print("gateway response:", json.dumps((out.get("result") or {}).get("response") or {},
                                          ensure_ascii=False)[:600])

    data2, tree2, hits2 = find_ferro(account, 0)
    if hits2:
        print("\n== بعد الترقية ==")
        print("   %s | level %s | asset %s | durability %s/%s"
              % (hits2[0]["name"], hits2[0]["level"], hits2[0]["asset_id"],
                 hits2[0]["durability"], hits2[0]["max_durability"]))
        counts2, _ = materials(account)
        for aid, cnt in counts2.items():
            if cnt != counts.get(aid):
                print("   مادة %s: %d → %d" % ((names.get(aid) or {}).get("name", aid),
                                               counts.get(aid, 0), cnt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
