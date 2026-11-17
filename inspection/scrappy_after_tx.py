# -*- coding: utf-8 -*-
"""بعد قبضة الأكل الناجحة على G22: هلTransaction اتدفع؟ وهل عرض الدقائق بقى متاح؟

مفيش أي write هنا — قراءة شجرة + GET للـtransactions + dry-run بـ amount=0.
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree, store  # noqa: E402

GEN_TIER = {"1657228973": 1, "2041317243": 2, "1434069496": 3,
            "2080275953": 4, "1781867314": 5}
ROUNDS = "-1869396984"
LEMON = "599997416"
CHEM = "-1565478080"
GAME_DATA = "data/pioneer_game_data.json"


def totals(data, ids):
    acc = {str(i): 0 for i in ids}
    for node in (data or {}).get("items") or []:
        aid = str(node.get("gameAssetId"))
        if aid in acc:
            acc[aid] += int(node.get("amount") or 0)
    return acc


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    data = pc.fetch_inventory_for(account)
    names = pioneer_tree.asset_names()
    t = totals(data, [ROUNDS, LEMON, CHEM])
    print("%s | Rounds=%s | Lemon=%s | Chemicals=%s" %
          (account, t[ROUNDS], t[LEMON], t[CHEM]))

    tree = pioneer_tree.Tree(data.get("items") or [])
    tier = 0
    for iid, node in tree.by_id.items():
        aid = str(node.get("gameAssetId"))
        if aid in GEN_TIER:
            tier = max(tier, GEN_TIER[aid])
            print("  جيلدا موجود: %s (%s) في أب %s" %
                  (names.get(aid, aid), aid, node.get("parentItemId") or "—"))
    print("  tier الحساب = %s" % tier)

    for path in ("/v1/pioneer/offers/transactions", "/v1/pioneer/offers"):
        try:
            resp = pc.request(path, token=token)
            print("\nGET %s ->\n  %s" % (path, json.dumps(resp, ensure_ascii=False)[:1500]))
        except Exception as err:
            print("\nGET %s رفض: %s" % (path, str(err)[:200]))

    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    rc = [o for o in offers if o.get("offerType") == "RoundCrafting"]
    mine = [o for o in rc if str(o.get("ownerGameAssetId")) in
            {k for k, v in GEN_TIER.items() if v == tier}]
    print("\nعروض بمستوى حسابي: %d" % len(mine))
    for o in mine[:6]:
        req = o.get("requiredItems") or []
        cost_lbl = ", ".join("%s x%s" % (names.get(str(i.get("itemGameAssetId")), "?"), i.get("amount")) for i in req)
        body = {"offerId": o["offerId"], "itemsToConsume": [], "amount": 0}
        try:
            resp = pc.post_json("/v1/pioneer/offers/accept", body, token=token)
            verdict = "200 %s" % json.dumps(resp, ensure_ascii=False)[:220]
        except Exception as err:
            verdict = "رفض: %s" % str(err)[:160]
        print("\n--- dry %s | %s |تكلفة %s\n    %s" % (o["offerId"], o.get("title"), cost_lbl, verdict))


if __name__ == "__main__":
    main()
