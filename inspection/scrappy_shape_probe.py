# -*- coding: utf-8 -*-
"""ميزان شكل جسم القبول لعروض سكرابي — بحارس يمنع أي قبض بدون علم.

المقيس (2026-11-01، كل الحسابات):
  • `amount: 0` على عرض RoundCrafting له `requiredItems` (Rounds Played) -> 400 "internal error"
  • `amount: 0` على عرض RoundCrafting له `cost.itemAmounts` (أكل الديك) -> 200 بـ changeset فاضي
  • العرض الشغال (التصنيع/الشراء) بيخدم الخامات من `cost` لوحده بـ itemsToConsume=[]
 فالسؤال: `requiredItems` بيتقدّم إزاي — اسم الحقل وصورته؟

الحارس: قبل كل طلب وبعده بنعيد عدد `Rounds Played` من الشجرة. أي فرق = الطلب ده
قبض فعلًا، فالسكربت بيقف فورًا وبيطبّع الطلب المتّهم. كده مفيشWAY قبض صامت.

الحالات: أيدي وهمية (UUID مش في الشجرة) أو `amount: 0` أو `amount` مستحيل
(999999 > أي رصيد) — كلها مفيش لها أثر نظريًا، والحارس بيحوّل النظرية لدليل.

    python -m inspection.scrappy_shape_probe G18
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

GEN_TIER = {"1657228973": 1, "2041317243": 2, "1434069496": 3,
            "2080275953": 4, "1781867314": 5}
ROUNDS_ASSET = -1869396984
GHOST = "00000000-0000-4000-8000-000000000000"
ACCEPT = "/v1/pioneer/offers/accept"
GAME_DATA = "data/pioneer_game_data.json"


def tree_of(account):
    data = pc.fetch_inventory_for(account)
    return pioneer_tree.Tree(data.get("items") or [])


def state(tree):
    tier, rounds, stack_ids = 0, 0, []
    for iid, node in tree.by_id.items():
        aid = str(node.get("gameAssetId"))
        if aid in GEN_TIER:
            tier = max(tier, GEN_TIER[aid])
        if aid == str(ROUNDS_ASSET):
            rounds += int(node.get("amount") or 0)
            stack_ids.append(str(iid))
    return tier, rounds, stack_ids


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    tier, rounds, stack_ids = state(tree_of(account))
    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    rc = [o for o in offers if o.get("offerType") == "RoundCrafting" and o.get("requiredItems")]
    mine = [o for o in rc if str(o["ownerGameAssetId"]) in {k for k, v in GEN_TIER.items() if v == tier}]
    offer = (mine or rc)[0]
    real = stack_ids[0] if stack_ids else GHOST
    print("%s: ديك مستوى %s | Rounds Played = %s في %d عقدة" % (account, tier, rounds, len(stack_ids)))
    print("العرض:", offer["offerId"], offer["title"], "| required:", json.dumps(offer["requiredItems"]))
    print("عقدة Rounds حقيقية (بتدخل بس في حالات amount المستحيل):", real, "\n")

    cases = [
        ("bare uuid / amount=1", {"offerId": offer["offerId"], "itemsToConsume": [GHOST], "amount": 1}),
        ("{instanceId} / amount=1", {"offerId": offer["offerId"],
                                     "itemsToConsume": [{"instanceId": GHOST}], "amount": 1}),
        ("{instanceId,amount} / amount=1", {"offerId": offer["offerId"],
                                            "itemsToConsume": [{"instanceId": GHOST, "amount": 1}],
                                            "amount": 1}),
        ("{itemInstanceId,amount} / amount=1", {"offerId": offer["offerId"],
                                                "itemsToConsume": [{"itemInstanceId": GHOST,
                                                                    "amount": 1}], "amount": 1}),
        ("{instanceId,gameAssetId,amount} / amount=1",
         {"offerId": offer["offerId"],
          "itemsToConsume": [{"instanceId": GHOST, "gameAssetId": ROUNDS_ASSET, "amount": 1}],
          "amount": 1}),
        ("{gameAssetId,amount} / amount=0", {"offerId": offer["offerId"],
                                             "itemsToConsume": [{"gameAssetId": ROUNDS_ASSET,
                                                                  "amount": 1}], "amount": 0}),
        ("requiredItems field / amount=0", {"offerId": offer["offerId"], "amount": 0,
                                            "requiredItems": [{"instanceId": GHOST, "amount": 1}]}),
        ("consumedItems field / amount=0", {"offerId": offer["offerId"], "amount": 0,
                                            "consumedItems": [{"instanceId": GHOST, "amount": 1}]}),
        ("itemsToConsume=[] / amount=999999", {"offerId": offer["offerId"],
                                               "itemsToConsume": [], "amount": 999999}),
        ("real instance / amount=999999", {"offerId": offer["offerId"],
                                          "itemsToConsume": [{"instanceId": real,
                                                               "gameAssetId": ROUNDS_ASSET,
                                                               "amount": 999999}],
                                          "amount": 999999}),
    ]

    current = rounds
    for label, body in cases:
        print("--- %-40s\n    %s" % (label, json.dumps(body)))
        try:
            resp = pc.post_json(ACCEPT, body, token=token)
            print("    200:", json.dumps(resp, ensure_ascii=False)[:300])
        except Exception as err:
            print("    رفض:", str(err)[:220])
        _, now, _ = state(tree_of(account))
        delta = now - current
        print("    Rounds Played: %d -> %d (فرق %d)" % (current, now, delta))
        if delta:
            print("\n!!! الحارس: الطلب ده غيّر الرصيد — قبض فعلاني. واقف عند هنا.")
            print("    الجسم:", json.dumps(body))
            return
        current = now
    print("\nالحارس: مفيش أي تغيير في الرصيد عبر كل الحالات — كلها صفر أثر.")


if __name__ == "__main__":
    main()
