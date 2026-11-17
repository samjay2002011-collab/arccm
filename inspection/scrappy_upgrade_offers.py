# -*- coding: utf-8 -*-
"""في عرض رسمي يطلّع جيلدا/سكرابي للمستوى اللي فوق؟ بحث في كل العروض عن مكافأة = asset جيلدا."""
import json

from backend import pioneer_tree

GAME_DATA = "data/pioneer_game_data.json"
GEN = {"1657228973": "I", "2041317243": "II", "1434069496": "III",
       "2080275953": "IV", "1781867314": "V"}

gd = json.load(open(GAME_DATA, encoding="utf-8"))
names = pioneer_tree.asset_names()
offers = gd["offer-descriptions"]["offerDescriptions"]
items = gd["items-description"]["itemDescriptions"]


def lab(aid):
    n = names.get(str(aid))
    if isinstance(n, dict):
        return n.get("display_name") or str(aid)
    return str(n or aid)


print("--- عروض مكافأتها جيلدا ---")
hits = 0
for o in offers:
    for r in (o.get("rewardPackage") or {}).get("rewardedItems") or []:
        if str(r.get("gameAssetId")) in GEN:
            hits += 1
            cost = (o.get("cost") or {}).get("itemAmounts") or []
            print("  offer %s %s -> جيلدا %s | نوع %s | duration %s | تكلفة %s" %
                  (o["offerId"], o.get("title"), GEN[str(r.get("gameAssetId"))],
                   o.get("offerType"), o.get("durationInSeconds"),
                   ", ".join("%s x%s" % (lab(c.get("gameAssetId")), c.get("amount")) for c in cost)))
print("  مجموع: %d" % hits)

print("\n--- مسار ترقية الجيلدا من وصف العنصر ---")
by_id = {str(i.get("gameAssetId")): i for i in items}
for aid, tier in sorted(GEN.items(), key=lambda kv: kv[1] and list(GEN).index(kv[0])):
    row = by_id.get(aid) or {}
    up = row.get("upgrade") or {}
    nxt = up.get("nextItemGameAssetId")
    cost = (up.get("cost") or {}).get("itemAmounts") or []
    print("  Scrappy %-4s -> %s | %s" % (tier, lab(nxt) if nxt else "أقصى مستوى",
          ", ".join("%s x%s" % (lab(c.get("gameAssetId")), c.get("amount")) for c in cost) or "مفيش"))
