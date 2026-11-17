# -*- coding: utf-8 -*-
"""فارزة offline: هل البوابة بتنّفّذ بس العروض اللي ليها cost.itemAmounts غير فاضي؟"""
import json
from collections import Counter

GAME_DATA = "data/pioneer_game_data.json"

offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
tab = Counter()
for o in offers:
    cost = (o.get("cost") or {}).get("itemAmounts") or []
    req = o.get("requiredItems") or []
    rp = ((o.get("rewardPackage") or {}).get("rewardedItems") or [])
    pools = ((o.get("rewardPackage") or {}).get("randomRewards") or {}).get("pools") or []
    key = (o.get("offerType"),
           "cost+" if cost else "cost0",
           "req+" if req else "req0",
           "fixed" if rp else ("rand" if pools else "none"))
    tab[key] += 1

print("%-16s %-6s %-6s %-6s %s" % ("offerType", "cost", "req", "reward", "عدد"))
for k, v in sorted(tab.items()):
    print("%-16s %-6s %-6s %-6s %s" % (k[0], k[1], k[2], k[3], v))

print("\n=== RoundCrafting بالتفصيل ===")
for o in offers:
    if o.get("offerType") != "RoundCrafting":
        continue
    cost = (o.get("cost") or {}).get("itemAmounts") or []
    req = o.get("requiredItems") or []
    pools = ((o.get("rewardPackage") or {}).get("randomRewards") or {}).get("pools") or []
    print("  %-10s |%-34s|cost=%d req=%s pools=%d|dur=%ss|owner=%s" %
          (o["offerId"], str(o.get("title"))[:34], len(cost),
           ",".join(str(i.get("amount")) for i in req), len(pools),
           o.get("durationInSeconds"), o.get("ownerGameAssetId")))
