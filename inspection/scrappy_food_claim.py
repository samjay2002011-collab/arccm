# -*- coding: utf-8 -*-
"""قرار RoundCrafting: أكل الديك (Lemon -> Chemicals) — محاولة حقيقية واحدة.

اللي عرفناه بالقياس:
  • مسار القبول الوحيد هو `offers/accept` (مفيش `/rounds` ولا `/generator` ولا `/scrappy`).
  • مخطط الجسم: `{offerId, itemsToConsume[] of openapi.InventoryItem, amount}` ومفيش حقول تانية.
  • عروض الدقيقة (`requiredItems: Rounds Played x1`) اترفضت بكل الصور الممكنة — نفس
    `400 internal error` سواء بعنصر كامل أو فاضي أو amount مستحيل.
  • عروض الأكل (`cost.itemAmounts: Lemon x1`) عدّت التحقق بـ amount=0.
فالسؤال الفاصل: هل RoundCrafting بيتنفّذ أصلاً للتوكن ده؟ لو الأكل اتنفّذ يبقى
المسار شغال، والرفض حق `requiredItems` بالذات — وده بيحوّل التخمين لخمس كلمات.

التكلفة الحقيقية: ليمونة واحدة من 60 عند G22 -> 5 Chemicals (صفقة الديك نفسها).
القياس: قبل/بعد على الشجرة + انتظار المدة (360 ثانية) نشوف اللوت ينزل إمتى،
ونطبّع شكل المعاملة اللي بيرجعها السيرفر (ده اللي الواجهة هتعرضه).

    python -m inspection.scrappy_food_claim G22
"""
import json
import sys
import time

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

ACCEPT = "/v1/pioneer/offers/accept"
GAME_DATA = "data/pioneer_game_data.json"
OFFER = 577343568  # ScrappyLemon: Lemon x1 -> Chemicals x5، 360 ثانية


def tree_of(account):
    return pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])


def totals(tree):
    out = {}
    for node in tree.by_id.values():
        aid = str(node.get("gameAssetId"))
        out[aid] = out.get(aid, 0) + int(node.get("amount") or 0)
    return out


def diff(a, b, names):
    out = {}
    for aid in set(list(a) + list(b)):
        d = b.get(aid, 0) - a.get(aid, 0)
        if d:
            out[(names.get(aid) or {}).get("display_name") or aid] = d
    return out


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    names = pioneer_tree.asset_names()
    offers = {o["offerId"]: o for o in
              json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]}
    offer = offers[OFFER]
    rewards = {str(r["gameAssetId"]): int(r["amount"]) for r in offer["rewardPackage"]["rewardedItems"]}
    costs = {str(c["gameAssetId"]): int(c["amount"]) for c in offer["cost"]["itemAmounts"]}
    tree = tree_of(account)
    before = totals(tree)
    print("%s | عرض %s (%s) |تكلفة %s -> مكافأة %s"
          % (account, OFFER, offer["title"],
             ", ".join("%s x%d (عندك %d)" % ((names.get(a) or {}).get("display_name") or a, q, before.get(a, 0))
                       for a, q in costs.items()),
             ", ".join("%s x%d (عندك %d)" % ((names.get(a) or {}).get("display_name") or a, q, before.get(a, 0))
                       for a, q in rewards.items())))
    body = {"offerId": OFFER, "itemsToConsume": [], "amount": 1}
    print("\nالجسم:", json.dumps(body))
    t0 = time.time()
    try:
        resp = pc.post_json(ACCEPT, body, token=token)
    except Exception as err:
        print("رفض:", str(err)[:300])
        print("\nيبقى RoundCrafting مقفول للتوكن ده بالكلية — العرض اللي عدّ التحقق بـ amount=0 "
              "بيرفض عند التنفيذ فعلًا.")
        return
    print("\n200 كامل:")
    print(json.dumps(resp, ensure_ascii=False)[:3000])
    immediate = totals(tree_of(account))
    print("\nفرق فوري (%.0fs):" % (time.time() - t0), json.dumps(diff(before, immediate, names), ensure_ascii=False))
    wait = int(offer["durationInSeconds"]) + 15
    print("... في انتظار %d ثانية (مدة العرض %d + هامش)" % (wait, offer["durationInSeconds"]))
    time.sleep(wait)
    final = totals(tree_of(account))
    print("\nالفرق بعد المدة:", json.dumps(diff(before, final, names), ensure_ascii=False))
    expected = {((names.get(a) or {}).get("display_name") or a): -q for a, q in costs.items()}
    for aid, q in rewards.items():
        label = (names.get(aid) or {}).get("display_name") or aid
        expected[label] = expected.get(label, 0) + q
    print("المتوقع من الكتالوج:", json.dumps(
        {k: v for k, v in expected.items() if v}, ensure_ascii=False))


if __name__ == "__main__":
    main()
