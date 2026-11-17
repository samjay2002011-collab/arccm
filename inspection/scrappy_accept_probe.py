# -*- coding: utf-8 -*-
"""ميزان سكرابي بصفر أثر: `amount: 0` على عروض حقيقية + بحث مسار الـ transactions.

المقيس للتو (G18): رقم عرض مش في الكتالوج = `500 internal error`، وعرض حقيقي
بـ `amount: 0` = `200` بـ changeset فاضي (`transactionsCreated: []`) — يعني
الموقع ده بيتنفّذ التحقق وبيرفض أي حاجة ناقصة من غير ما يصرف ولا يولّد معاملة.
فالاستغلال: نقدر نختبر "الحساب مالوش الحاوية دي؟" و"التحقق بيقرأ أي حقل؟" بلا أي أثر.

الحالات:
  1) عرض RoundCrafting بمستوى الحساب نفسه — لازم يعدّي التحقق.
  2) عرض RoundCrafting بمستوى مالوش الحاوية عنده — يفرّق لو البوابة بتتحقق من الديك.
  3) عرض RoundCrafting من غير `itemsToConsume` ومن غير أي توكن؟ لأ — نفس الحساب.
  4) جرد GET على مسارات العروض/المعاملات — عشان نعرف المعاملات المستنية بتقرا منين.

مفيش أي `amount >= 1` هنا: كل الطلبات صفر، فمفيش قبض ولا صرف ولا تايمر.

    python -m inspection.scrappy_accept_probe G18
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

GEN_TIER = {"1657228973": 1, "2041317243": 2, "1434069496": 3,
            "2080275953": 4, "1781867314": 5}
ROUNDS_ASSET = "-1869396984"
GAME_DATA = "data/pioneer_game_data.json"
ACCEPT = "/v1/pioneer/offers/accept"

READ_ROUTES = [
    "/v1/pioneer/offers", "/v1/pioneer/offers/transactions", "/v1/pioneer/transactions",
    "/v1/pioneer/offers/list", "/v1/pioneer/offers/pending", "/v1/pioneer/offers/active",
    "/v1/pioneer/offers/state", "/v1/pioneer/crafting", "/v1/pioneer/crafting/transactions",
    "/v1/pioneer/inventory/transactions", "/v1/pioneer/inventory/offers",
    "/v1/pioneer/inventory/v1/transactions", "/v1/pioneer/production",
    "/v1/pioneer/projects", "/v1/pioneer/projects/list", "/v1/pioneer/raiders",
    "/v1/pioneer/bonuses", "/v1/pioneer/quests", "/v1/pioneer/inventory",
]


def generator_state(account):
    data = pc.fetch_inventory_for(account)
    tree = pioneer_tree.Tree(data.get("items") or [])
    tier, rounds = 0, 0
    for node in tree.by_id.values():
        aid = str(node.get("gameAssetId"))
        if aid in GEN_TIER:
            tier = max(tier, GEN_TIER[aid])
        elif aid == ROUNDS_ASSET:
            rounds += int(node.get("amount") or 0)
    return tier, rounds, tree


def brief(resp):
    """ملخص الـ changeset: عدد Created/Updated + أي رسالة رفض."""
    if not isinstance(resp, dict):
        return str(resp)[:200]
    keys = {k.lower(): v for k, v in resp.items()}
    ch = keys.get("changeset") or {}
    items = ch.get("items") or {}
    offers = ch.get("offers") or {}
    err = keys.get("error")
    return ("error=%s | created=%s deleted=%s updated=%s | txCreated=%s txUpdated=%s"
            % (json.dumps(err, ensure_ascii=False)[:160] if err else "none",
               len(items.get("created") or []), len(items.get("deleted") or []),
               len(items.get("updated") or []),
               len(offers.get("transactionsCreated") or []),
               len(offers.get("transactionsUpdated") or [])))


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    tier, rounds, tree = generator_state(account)
    print("%s: ديك مستوى %s | Rounds Played = %s" % (account, tier, rounds))

    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    rc = [o for o in offers if o.get("offerType") == "RoundCrafting"]
    have = {k for k, v in GEN_TIER.items() if v == tier}
    ours = next((o for o in rc if str(o["ownerGameAssetId"]) in have), None)
    foreign = next((o for o in rc if str(o["ownerGameAssetId"]) not in have), None)

    print("\n###POST amount=0 (تحقق بلا صرف)")
    for label, offer in (("عرض بمستوى ديكنا", ours), ("عرض بمستوى مالوش عندنا", foreign)):
        if not offer:
            continue
        for body in ({"offerId": offer["offerId"], "itemsToConsume": [], "amount": 0},
                     {"offerId": offer["offerId"], "amount": 0}):
            try:
                resp = pc.post_json(ACCEPT, body, token=token)
                print("  %-26s %-52s -> %s" % (label, json.dumps(body)[:50], brief(resp)))
            except Exception as err:
                print("  %-26s %-52s -> رفض %s" % (label, json.dumps(body)[:50], str(err)[:120]))

    print("\n###GET مسارات العروض/المعاملات")
    for path in READ_ROUTES:
        try:
            resp = pc.request(path, token=token)
        except Exception as err:
            print("  %-44s -> %s" % (path, str(err)[:110]))
            continue
        text = json.dumps(resp, ensure_ascii=False)
        marks = []
        for needle in ("offerId", "transactionId", "transactions", "durationInSeconds", "ownerInstanceId"):
            if needle in text:
                marks.append(needle)
        print("  %-44s -> 200 %d bytes %s | %s"
              % (path, len(text), "+".join(marks) or "-", text[:150]))

    after = generator_state(account)
    print("\nبعد كل ده: ديك %s | Rounds Played = %s (كان %s)" % (after[0], after[1], rounds))


if __name__ == "__main__":
    main()
