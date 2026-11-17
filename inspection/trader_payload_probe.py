# -*- coding: utf-8 -*-
"""قياس شكل طلب شراء التاجر على البوابة — قراءة فقط، صفر كتابة.

بيرفض كل محاولة قبل ما تتبعت لو ممكن، وبعدها بيبعت نسخ بتفشل *قبل* الصرف:
`amount: 0` و`offerId` مش موجود. لو البوابة رجّعت 400 لقبولها الشكل، معناها
الشكل سليم والرفض جه من المنطق (مكان التخزين). لو رجّعت "cannot unmarshal"
يبقى الحقل نفسه غلط وبيبان اسمه.

حاجة واحدة بس بتتشغل فعليًا (وفقط بـ --live): طلب حقيقي واحد بالشكل المفترح.

    python -m inspection.trader_payload_probe G22 727507836
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

ACCEPT = "/v1/pioneer/offers/accept"
GHOST = "00000000-0000-4000-8000-000000000000"
UNKNOWN_OFFER = 123456789


def verdict(body, token):
    try:
        resp = pc.post_json(ACCEPT, body, token=token)
        return "200 " + json.dumps(resp, ensure_ascii=False)[:200]
    except Exception as exc:
        text = str(exc)
        if "cannot unmarshal" in text:
            return "SCHEMA>> " + text.split("cannot unmarshal", 1)[1][:160]
        tail = text.split("->")[-1].strip()
        return tail[:160]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    offer_id = int(sys.argv[2]) if len(sys.argv) > 2 else 727507836
    password = "--live" in sys.argv

    token = pc.account_token(account)
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    print("حساب:", account, "| عرض:", offer_id)

    coins = [n for n in tree.by_id.values() if str(n.get("gameAssetId")) == "-898439395"]
    for n in coins:
        print("  عملة:", n.get("instanceId"), "| كمية:", n.get("amount"),
              "| container:", n.get("parentInstanceId") or n.get("wrapperId"))

    key = "-500614359"
    req = [n for n in tree.by_id.values() if str(n.get("gameAssetId")) == key]
    print("  المطلوب كخامة (itemGameAssetId", key, "):", len(req), "نسخة")

    cases = [
        ("control/غرض وهمي + كمية 0", {"offerId": UNKNOWN_OFFER, "itemsToConsume": [], "amount": 0}),
        ("شكلنا الحالي + كمية 0", {"offerId": offer_id, "itemsToConsume": [], "amount": 0}),
    ]
    for label, body in cases:
        print("\n%-34s %s" % (label, json.dumps(body, ensure_ascii=False)))
        print("   ->", verdict(body, token))

    print("\n###مسح حقول فوق AcceptOffersRequest (بكمية 0 = مفيش صرف)")
    fields = ["quantity", "count", "ownerInstanceId", "owner_instance_id", "ownerId",
              "instanceId", "instance_id", "tradersOfferId", "traderOfferId", "offerInstanceId",
              "offer_instance_id", "targetWrapperId", "targetWrapper", "stashId", "containerId",
              "targetContainer", "etag", "expectedEtag", "inventoryEtag", "itemsToConsume"]
    for name in fields:
        probe = {"offerId": offer_id, "itemsToConsume": [], "amount": 0, name: "x"}
        out = verdict(probe, token)
        if out.startswith("SCHEMA>>") or out.startswith("200"):
            print("  +-- %-22s %s" % (name, out))

    print("\n###مسح حقول جوه openapi.InventoryItem")
    item_fields = ["instanceId", "itemInstanceId", "gameAssetId", "assetId", "amount",
                   "quantity", "etag", "wrapperId", "containerId", "slotId", "durability"]
    for name in item_fields:
        item = {"instanceId": GHOST}
        if name != "instanceId":
            item[name] = "x"
        body = {"offerId": UNKNOWN_OFFER, "itemsToConsume": [item], "amount": 0}
        out = verdict(body, token)
        if out.startswith("SCHEMA>>") or out.startswith("200"):
            print("  +-- %-22s %s" % (name, out))

    if password:
        body = {"offerId": offer_id, "itemsToConsume": [], "amount": 1}
        print("\n###تنفيذ حقيقي واحد:", json.dumps(body, ensure_ascii=False))
        print("   ->", verdict(body, token))


if __name__ == "__main__":
    main()
