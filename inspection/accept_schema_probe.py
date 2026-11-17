# -*- coding: utf-8 -*-
"""مسح مخطط `AcceptOffersRequest` بقرار من البوابة نفسها — صفر أثر.

القاعدة اللي بنستغلها: فك الترميز في Go بيرجع رسالة باسم الحقل ونوعه لما النوع
يكون غلط:
    json: cannot unmarshal object into AcceptOffersRequest.itemsToConsume.0 of type openapi.InventoryItem
والحقول المجهولة بتتجاهل في صمت. فلو بصنا حقل باسم موجود بشكل غلط بنشوف اسمه ونوعه،
ولو البوابة رجعت `400 internal error` (رفض منطقي) يبقى الاسم مالوش وجود.

الجسم الأساسي مرفوض قياسًا (أيدي وهمية مش في الشجرة + عرض RoundCrafting)، فمهما أضفنا
حقول ما فيش حاجة تتصرف: مفيش نسخة موجودة عشان تُستهلك.

بنمسح:
  أ) الحقول فوق `AcceptOffersRequest` نفسه.
  ب) الحقول جوه عنصر `openapi.InventoryItem` (المكان اللي فيه سر `requiredItems`).

    python -m inspection.accept_schema_probe G18
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
PROBE = {"probe": 1}

TOP_FIELDS = [
    "offerId", "amount", "itemsToConsume", "requiredItems", "cost", "costs", "consume",
    "transactionId", "durationInSeconds", "duration", "ownerInstanceId", "generatorId",
    "acceptAll", "all", "expectedEtag", "etag", "inventoryEtag", "wrapperId", "containerId",
    "slotId", "parentInstanceId", "manifestId", "raiderId", "account", "accountId",
    "embarkUserId", "user", "hideout", "hideoutId", "station", "stationId", "project",
    "projectId", "claim", "claimAll", "skip", "force", "dryRun", "confirm", "rounds",
    "roundsPlayed", "itemIds", "instanceIds", "items", "itemsToClaim", "rewards",
]
ITEM_FIELDS = [
    "instanceId", "itemInstanceId", "gameAssetId", "assetId", "itemGameAssetId", "amount",
    "quantity", "count", "etag", "durability", "maxDurability", "slots", "updatedAt",
    "modTime", "wrapperId", "containerId", "parentInstanceId", "ownerInstanceId", "slotId",
    "slotIndex", "position", "x", "y", "stackSize", "isBound", "bound", "flags", "tags",
    "guid", "id", "uuid", "templateId", "displayName", "name", "childInstanceId",
]


def round_offer(tree):
    tier = max([GEN_TIER[str(n.get("gameAssetId"))] for n in tree.by_id.values()
                if str(n.get("gameAssetId")) in GEN_TIER] or [0])
    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    rc = [o for o in offers if o.get("offerType") == "RoundCrafting" and o.get("requiredItems")
          and str(o["ownerGameAssetId"]) in {k for k, v in GEN_TIER.items() if v == tier}]
    return tier, sorted(rc, key=lambda o: o["durationInSeconds"])[0]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    tier, offer = round_offer(tree)
    base = {"offerId": offer["offerId"], "itemsToConsume": [{"instanceId": GHOST}], "amount": 1}
    print("%s | ديك %s | عرض %s (%s) | الجسم الأساسي: %s"
          % (account, tier, offer["offerId"], offer["title"], json.dumps(base)))

    def ask(body):
        try:
            resp = pc.post_json(ACCEPT, body, token=token)
            return "200 " + json.dumps(resp, ensure_ascii=False)[:120]
        except Exception as err:
            text = str(err)
            if "cannot unmarshal" in text:
                return "FIELD>> " + text.split("cannot unmarshal", 1)[1][:110]
            return "ignored/logic-refusal: " + text.split("->")[-1].strip()[:60]

    print("\n###كنترول: الجسم الأساسي لوحده")
    print("  ", ask(base))

    print("\n###أ) حقول فوق AcceptOffersRequest")
    top_hits = []
    for name in TOP_FIELDS:
        if name in base:
            continue
        verdict = ask({**base, name: PROBE})
        if verdict.startswith("FIELD>>"):
            top_hits.append((name, verdict))
            print("  +-- %-22s %s" % (name, verdict))
    print("  الحقول المؤكدة:", [n for n, _ in top_hits])

    print("\n###ب) حقول جوه openapi.InventoryItem")
    item_hits = []
    for name in ITEM_FIELDS:
        item = {"instanceId": GHOST}
        if name in item:
            continue
        item[name] = PROBE
        verdict = ask({**base, "itemsToConsume": [item]})
        if verdict.startswith("FIELD>>"):
            item_hits.append((name, verdict))
            print("  +-- %-22s %s" % (name, verdict))
    print("  الحقول المؤكدة:", [n for n, _ in item_hits])

    after = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    print("\nRounds Played بعد المسح:", sum(int(n.get("amount") or 0) for n in after.by_id.values()
                                        if str(n.get("gameAssetId")) == str(ROUNDS_ASSET)))


if __name__ == "__main__":
    main()
