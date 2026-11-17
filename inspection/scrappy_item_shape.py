# -*- coding: utf-8 -*-
"""ميزان حقل `itemsToConsume` بصورة `openapi.InventoryItem` الكاملة — بحارس صفر أثر.

المكتشف للتو: الرفض بيرجع رسالة فك الترميز الحقيقية —
    AcceptOffersRequest.itemsToConsume.0 of type openapi.InventoryItem
يعني العنصر المطلوب هو نفس كائن الشجرة (`amount/durability/etag/gameAssetId/
instanceId/maxDurability/slots/updatedAt`)، والكائن الناقص بيبقى `400 internal error`.

الحيل: كل الطلبات بـ `amount: 0` — ومقيس إنها ما تولّدش معاملة ولا تصرف خامة، فبنقدر
نجرب الصور كاملة وناقصة بلا أثر، والحارس (قراءة Rounds Played قبل وبعد كل طلب) بيوقف
أي تغيير.

    python -m inspection.scrappy_item_shape G18
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

GEN_TIER = {"1657228973": 1, "2041317243": 2, "1434069496": 3,
            "2080275953": 4, "1781867314": 5}
ROUNDS_ASSET = -1869396984
ACCEPT = "/v1/pioneer/offers/accept"
GAME_DATA = "data/pioneer_game_data.json"


def tree_of(account):
    return pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])


def rounds_of(tree):
    return sum(int(n.get("amount") or 0) for n in tree.by_id.values()
               if str(n.get("gameAssetId")) == str(ROUNDS_ASSET))


def tier_of(tree):
    tier = 0
    for node in tree.by_id.values():
        aid = str(node.get("gameAssetId"))
        if aid in GEN_TIER:
            tier = max(tier, GEN_TIER[aid])
    return tier


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    tree = tree_of(account)
    tier = tier_of(tree)
    node = next((dict(n) for n in tree.by_id.values()
                 if str(n.get("gameAssetId")) == str(ROUNDS_ASSET)), None)
    if not node:
        print("مفيش عقدة Rounds Played عند", account)
        return
    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    rc = [o for o in offers if o.get("offerType") == "RoundCrafting" and o.get("requiredItems")
          and str(o["ownerGameAssetId"]) in {k for k, v in GEN_TIER.items() if v == tier}]
    offer = rc[0]
    print("%s: ديك %s | Rounds Played = %s | العرض %s (%s)"
          % (account, tier, rounds_of(tree), offer["offerId"], offer["title"]))
    print("العقدة الخام:", json.dumps(node, ensure_ascii=False), "\n")

    stripped = {}
    variants = [
        ("العقدة كما هي", dict(node)),
        ("slots=null حذف", {k: v for k, v in node.items() if k != "slots"}),
        ("updatedAt حذف", {k: v for k, v in node.items() if k != "updatedAt"}),
        ("durability/maxDurability حذف",
         {k: v for k, v in node.items() if k not in ("durability", "maxDurability")}),
        ("amount=1 فقط (قيمة مطلوبة)",
         {"instanceId": node["instanceId"], "gameAssetId": ROUNDS_ASSET, "amount": 1,
          "etag": node.get("etag")}),
        ("بلا etag", {k: v for k, v in node.items() if k != "etag"}),
        ("بلا instanceId", {k: v for k, v in node.items() if k != "instanceId"}),
        ("العقدة بـ amount=99 (أكبر من المطلوب)", {**node, "amount": 99}),
    ]
    current = rounds_of(tree)
    for label, item in variants:
        body = {"offerId": offer["offerId"], "itemsToConsume": [item], "amount": 0}
        print("--- %-34s" % label)
        print("    ", json.dumps(item, ensure_ascii=False)[:190])
        try:
            resp = pc.post_json(ACCEPT, body, token=token)
            ch = (resp or {}).get("changeset") or {}
            print("    200 | created=%d updated=%d txCreated=%d"
                  % (len((ch.get("items") or {}).get("created") or []),
                     len((ch.get("items") or {}).get("updated") or []),
                     len((ch.get("offers") or {}).get("transactionsCreated") or [])))
            stripped[label] = "200"
        except Exception as err:
            print("    رفض:", str(err)[:170])
            stripped[label] = "400"
        after = rounds_of(tree_of(account))
        if after != current:
            print("\n!!! الحارس: الرصيد اتغير (%d -> %d) — واقف." % (current, after))
            return
        current = after
    print("\nالخلاصة (amount=0): " + " | ".join("%s=%s" % kv for kv in stripped.items()))


if __name__ == "__main__":
    main()
