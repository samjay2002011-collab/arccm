# -*- coding: utf-8 -*-
"""أول قبض سكرابي حقيقي — واحدة بس، على حساب اختيار، مع قياس كامل قبل/بعد.

الدليل اللي أوصل هنا: رسالة فك الترميز بتاعة البوابة نفسها
    AcceptOffersRequest.itemsToConsume.0 of type openapi.InventoryItem
فالعنصر المطلوب (`Rounds Played`) بيتبعت كينونته كاملة زي ما البوابة رجّعتها
(`amount/durability/etag/gameAssetId/instanceId/maxDurability/slots/updatedAt`)،
والجسم ده ما اتقستش قبل كده لأن `amount: 0` مرفوض لأي عرض عليه `requiredItems`.

اللي بنعمله:
  1) قراءة كاملة قبل: عدد Rounds Played + إجمالي كل asset في الشجرة.
  2) عرض قصير المدة (Minute 1 = 60 ثانية) عشان نلحق اللوت ونعرف المعاملة بتتقفل إزاي.
  3) POST واحد، ونطبّع الـ changeset كامل — خصوصاً `transactionsCreated` (شكل المعاملة
     والـ eta بتاعها: ده اللي الواجهة هتعرضه).
  4) قراءة بعد فورًا وبعد المدة: الفرق في الأصول = اللوت اللي نزل.

الحراسة: لو الرد جاء رفض بنص غامض بنعيد المحاولة بنفس الصورة مرة واحدة بس؟ لأ —
مفيش تكرار. محاولة واحدة، والفرق بيتسجّل في الكلام.

    python -m inspection.scrappy_first_claim G18
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
SETTLE_SECONDS = 75


def tree_of(account):
    return pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])


def totals(tree):
    out = {}
    for node in tree.by_id.values():
        aid = str(node.get("gameAssetId"))
        out[aid] = out.get(aid, 0) + int(node.get("amount") or 0)
    return out


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    before_tree = tree_of(account)
    tier = max([GEN_TIER[str(n.get("gameAssetId"))] for n in before_tree.by_id.values()
                if str(n.get("gameAssetId")) in GEN_TIER] or [0])
    node = next((dict(n) for n in before_tree.by_id.values()
                 if str(n.get("gameAssetId")) == str(ROUNDS_ASSET)), None)
    if not node:
        print("مفيش Rounds Played عند", account)
        return
    mine = [o for o in offers if o.get("offerType") == "RoundCrafting" and o.get("requiredItems")
            and str(o["ownerGameAssetId"]) in {k for k, v in GEN_TIER.items() if v == tier}]
    offer = sorted(mine, key=lambda o: (o["durationInSeconds"], o["orderIndex"]))[0]
    rewards = {str(r["gameAssetId"]): int(r["amount"]) for r in offer["rewardPackage"]["rewardedItems"]}
    names = pioneer_tree.asset_names()
    print("%s | ديك مستوى %s | Rounds Played = %s" % (account, tier, int(node.get("amount") or 0)))
    print("العرض:", offer["offerId"], offer["title"], "| مدة %ds" % offer["durationInSeconds"],
          "| المفروض:", ", ".join("%s x%d" % ((names.get(a) or {}).get("display_name") or a, q)
                                 for a, q in rewards.items()))
    body = {"offerId": offer["offerId"], "itemsToConsume": [node], "amount": 1}
    print("\nالجسم:", json.dumps(body, ensure_ascii=False)[:300])

    t0 = totals(before_tree)
    try:
        resp = pc.post_json(ACCEPT, body, token=token)
    except Exception as err:
        print("\nرفض البوابة:", str(err)[:400])
        print("\nلو الرفض سببه الصورة، الخطوة الجاية تجربة `itemsToConsume: []` بنفس الـ amount:")
        try:
            resp = pc.post_json(ACCEPT, {"offerId": offer["offerId"], "itemsToConsume": [],
                                        "amount": 1}, token=token)
            print("   قبل بـ itemsToConsume=[] -> 200")
        except Exception as err2:
            print("   وهي كمان رفضت:", str(err2)[:200])
            return
    ch = (resp or {}).get("changeset") or {}
    txs = (ch.get("offers") or {}).get("transactionsCreated") or []
    print("\n200 | items created=%d deleted=%d updated=%d | txCreated=%d | notifications=%d"
          % (len((ch.get("items") or {}).get("created") or []),
             len((ch.get("items") or {}).get("deleted") or []),
             len((ch.get("items") or {}).get("updated") or []), len(txs),
             len(ch.get("notifications") or [])))
    print("المعاملات:", json.dumps(txs, ensure_ascii=False)[:1200])
    upd = (ch.get("items") or {}).get("updated") or []
    print("العناصر المحدّثة:", json.dumps(upd, ensure_ascii=False)[:600])

    t1 = totals(tree_of(account))
    print("\nفرق فوري:", {a: t1.get(a, 0) - t0.get(a, 0) for a in
                         set(list(rewards) + [str(ROUNDS_ASSET)])
                         if t1.get(a, 0) - t0.get(a, 0)})
    print("في انتظار انتهاء المدة (%d ثانية)..." % SETTLE_SECONDS)
    time.sleep(SETTLE_SECONDS)
    t2 = totals(tree_of(account))
    delta = {a: t2.get(a, 0) - t0.get(a, 0) for a in set(list(rewards) + [str(ROUNDS_ASSET)])
             if t2.get(a, 0) - t0.get(a, 0)}
    print("\nبعد %d ثانية الفرق:" % SETTLE_SECONDS, json.dumps(
        {((names.get(a) or {}).get("display_name") or a): q for a, q in delta.items()},
        ensure_ascii=False))
    print("المتوقع من الكتالوج:", json.dumps(
        {((names.get(a) or {}).get("display_name") or a): q for a, q in rewards.items()},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
