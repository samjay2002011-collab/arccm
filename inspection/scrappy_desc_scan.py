# -*- coding: utf-8 -*-
"""وصف الجيلدا/سكرابي من البيانات الرسمية + هل مكافآت rewardedItems موجودة فعلاً في الشجرة؟"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

GAME_DATA = "data/pioneer_game_data.json"
GEN = ["1657228973", "2041317243", "1434069496", "2080275953", "1781867314"]
ROUNDS_IDS = {"-1869396984", "599997416", "-1565478080"}


def main():
    gd = json.load(open(GAME_DATA, encoding="utf-8"))
    items = gd["items-description"]["itemDescriptions"]
    by_id = {}
    for it in items:
        by_id.setdefault(str(it.get("gameAssetId", it.get("itemGameAssetId", ""))), it)
    print("مفاتيح وصف العنصر: %s" % sorted(set().union(*[set(i) for i in items[:50]])))
    for aid in GEN:
        row = by_id.get(aid)
        print("\n=== %s ===\n%s" % (aid, json.dumps(row, ensure_ascii=False, indent=1)[:900] if row else "مفيش وصف"))

    # أي عنصر في الوصف فيه tag أو itemType فيه scrappy/rooster/generator؟
    print("\n--- عناصر بعلامة/نوع له علاقة ---")
    seen = set()
    for it in items:
        blob = json.dumps(it, ensure_ascii=False).lower()
        if any(k in blob for k in ("scrappy", "rooster", "generator")):
            key = str(it.get("gameAssetId"))
            if key in seen:
                continue
            seen.add(key)
            nm = it.get("displayName") or it.get("name") or ""
            print("  %-40s | %s | %s" % (str(nm)[:40], it.get("itemType"), json.dumps({k: v for k, v in it.items() if k in ("slots", "maxAmount", "stackable", "tags")}, ensure_ascii=False)[:200]))

    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    data = pc.fetch_inventory_for(account)
    names = pioneer_tree.asset_names()
    tree = pioneer_tree.Tree(data.get("items") or [])
    ids = {str(i) for i in tree.by_id}
    offers = gd["offer-descriptions"]["offerDescriptions"]
    ro = [o for o in offers if o.get("offerType") == "RoundCrafting"]
    in_tree = tot = 0
    for o in ro:
        for r in (o.get("rewardPackage") or {}).get("rewardedItems") or []:
            tot += 1
            if str(r.get("aliasInstanceId")) in ids:
                in_tree += 1
    print("\naliasInstanceId موجودين في شجرة %s: %d/%d" % (account, in_tree, tot))
    rounds_nodes = [n for n in (data.get("items") or []) if str(n.get("gameAssetId")) in ROUNDS_IDS]
    print("\nعقد Rounds Played/الليمون/الكيميكال (%d):" % len(rounds_nodes))
    for n in rounds_nodes[:12]:
        print("  %s | amount=%s | أب=%s | etag=%s | slots=%s" %
              ((names.get(str(n.get("gameAssetId"))) or {}).get("display_name") if isinstance(names.get(str(n.get("gameAssetId"))), dict) else n.get("gameAssetId"),
               n.get("amount"), n.get("parentItemId") or "—", n.get("etag"), n.get("slots")))


if __name__ == "__main__":
    main()
