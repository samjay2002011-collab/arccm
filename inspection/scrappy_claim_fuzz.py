# -*- coding: utf-8 -*-
"""نفّس صور العنصر الحقيقي لعرض سكرابي لحد البوابة تقبل — بحارس ووقوف عند أول نجاح.

المخطط اتقاس من البوابة نفسها: `AcceptOffersRequest{offerId, itemsToConsume[]
(openapi.InventoryItem: instanceId/gameAssetId/amount/etag/durability/maxDurability/
slots[]string/updatedAt), amount}` ومفيش أي حقل فوق كده. فالمرفوض لازم يكون في
*قيمة* الحقول، والاحتمالات المحدودة دي هي اللي بنجرّبها.

الحارس: قبل كل طلب وبعده بنعيد عدد `Rounds Played`. أول ما يجي `200` بنوقف — يعني
لو واحد من الصور دي قبلان فده هو القالب، وسعره round واحد من 105 (ولو فشل كله يبقى
صفر أثر). مفيش هنا أي تكرار لطلب ناجح ولا أي تحويل لأكوام.

    python -m inspection.scrappy_claim_fuzz G18
"""
import json
import sys
import time

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


def totals(tree):
    out = {}
    for node in tree.by_id.values():
        aid = str(node.get("gameAssetId"))
        out[aid] = out.get(aid, 0) + int(node.get("amount") or 0)
    return out


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    tree = tree_of(account)
    tier = max([GEN_TIER[str(n.get("gameAssetId"))] for n in tree.by_id.values()
                if str(n.get("gameAssetId")) in GEN_TIER] or [0])
    node = next((dict(n) for n in tree.by_id.values()
                 if str(n.get("gameAssetId")) == str(ROUNDS_ASSET)), None)
    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    rc = [o for o in offers if o.get("offerType") == "RoundCrafting" and o.get("requiredItems")
          and str(o["ownerGameAssetId"]) in {k for k, v in GEN_TIER.items() if v == tier}]
    offer = sorted(rc, key=lambda o: o["durationInSeconds"])[0]
    iid = str(node["instanceId"])
    print("%s | ديك %s | Rounds Played = %s | عرض %s (%s, %ds)"
          % (account, tier, node["amount"], offer["offerId"], offer["title"],
             offer["durationInSeconds"]))
    before = totals(tree)

    variants = [
        ("adequation: instanceId+gameAssetId+amount=1",
         {"instanceId": iid, "gameAssetId": ROUNDS_ASSET, "amount": 1}),
        ("نفسه + etag", {"instanceId": iid, "gameAssetId": ROUNDS_ASSET, "amount": 1,
                         "etag": node.get("etag")}),
        ("العقدة كاملة لكن amount=1", {**node, "amount": 1}),
        ("العقدة كاملة + slots=[]", {**node, "amount": 1, "slots": []}),
        ("بلا updatedAt", {k: v for k, v in {**node, "amount": 1}.items() if k != "updatedAt"}),
        ("بلا etag وبلا updatedAt",
         {k: v for k, v in {**node, "amount": 1}.items() if k not in ("etag", "updatedAt")}),
        ("كل الحقول بصفر/فضاء",
         {"instanceId": iid, "gameAssetId": ROUNDS_ASSET, "amount": 1, "etag": "",
          "durability": 1, "maxDurability": 1, "slots": [], "updatedAt": 0}),
    ]
    for label, item in variants:
        body = {"offerId": offer["offerId"], "itemsToConsume": [item], "amount": 1}
        print("\n--- %s\n    %s" % (label, json.dumps(body, ensure_ascii=False)[:230]))
        try:
            resp = pc.post_json(ACCEPT, body, token=token)
        except Exception as err:
            print("    رفض:", str(err)[:170])
            after = rounds_of(tree_of(account))
            if after != int(node["amount"]):
                print("    !!! الرصيد اتغير رغم الرفض (%s -> %s) — واقف."
                      % (node["amount"], after))
                return
            continue
        ch = (resp or {}).get("changeset") or {}
        items = ch.get("items") or {}
        txs = (ch.get("offers") or {}).get("transactionsCreated") or []
        print("    200 | created=%d updated=%d deleted=%s txCreated=%d"
              % (len(items.get("created") or []), len(items.get("updated") or []),
                 len(items.get("deleted") or []), len(txs)))
        print("    tx:", json.dumps(txs, ensure_ascii=False)[:800])
        print("    updated:", json.dumps(items.get("updated") or [], ensure_ascii=False)[:500])
        print("    >>> القالب الناجح:", label)
        time.sleep(70)
        after_totals = totals(tree_of(account))
        delta = {a: after_totals.get(a, 0) - before.get(a, 0) for a in
                 set([str(r["gameAssetId"]) for r in offer["rewardPackage"]["rewardedItems"]]
                     + [str(ROUNDS_ASSET)])
                 if after_totals.get(a, 0) - before.get(a, 0)}
        names = pioneer_tree.asset_names()
        print("    فرق الأصول بعد 70 ثانية:", json.dumps(
            {((names.get(a) or {}).get("display_name") or a): q for a, q in delta.items()},
            ensure_ascii=False))
        return
    print("\nكل الصور اترفضت — مفيش أي أثر (Rounds Played زي ما هو).")


if __name__ == "__main__":
    main()
