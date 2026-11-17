# -*- coding: utf-8 -*-
"""ينفّذ تصنيع عرض واحد على بوابة Embark الرسمية ويسجّل الطلب والرد وحرفيًا.

اللي اتقاس قبل ده: بوابة Pioneer مفيهاش أي مسار manufacturing، لكن التصنيع في بيانات
اللعبة نفسه "عرض" (`type: "crafting"`) بنفس رقم العرض اللي بيتستخدم في الشراء
(`offer_id`)، وبنفس نقطة القبول. السكربت ده يقيس الفرضية على بوتة رسمية واحدة:

    POST /v1/pioneer/offers/accept   {"offerId": <id>, "itemsToConsume": [], "amount": <n>}

بیقرأ شجرة المخزون الرسمي قبل وبعد، فيطلع الخصم والإضافة حرفيين. كتابة واحدة على
العرض المحدد، ومافيش أي محاولة تانية لو رفضته البوابة — الرد بيتطبع كامل.

    python -m inspection.craft_once G22 357023568 1
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402

ACCEPT = "/v1/pioneer/offers/accept"
CATALOG = r"C:\Users\Administrator\Desktop\rr\data\craft_offers_source.json"


def offer_row(offer_id):
    data = json.load(open(CATALOG, encoding="utf-8"))
    for rows in (data.get("grouped_offers") or {}).values():
        for row in rows:
            if str(row.get("offer_id")) == str(offer_id):
                return row
    return None


def totals(items, asset_ids):
    out = {str(a): 0 for a in asset_ids}
    for node in items or []:
        key = str(node.get("gameAssetId"))
        if key in out:
            out[key] += int(node.get("amount") or 0)
    return out


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    offer_id = sys.argv[2] if len(sys.argv) > 2 else "357023568"
    amount = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    row = offer_row(offer_id)
    if not row:
        print("العرض مش في الكتالوج المحفوظ:", offer_id)
        return
    cost_assets = [c.get("asset_id") for c in row.get("cost") or []]
    reward_asset = (row.get("reward") or {}).get("asset_id")
    watch = cost_assets + [reward_asset]
    token = pc.account_token(account)
    print("حساب:", account, "| عرض:", offer_id, "| كمية:", amount)
    print("محطة:", row.get("bench_key"), "| نسخة المحطة عندهم:", row.get("owner_id"))
    print("المطلوب:", [(c.get("meta", {}).get("display_name"), c.get("amount") * amount)
                       for c in row.get("cost") or []])
    print("المنتج:", row.get("reward_meta", {}).get("display_name"),
          (row.get("reward") or {}).get("amount", 1) * amount)

    before = pc.fetch_inventory_for(account)
    pre = totals(before.get("items"), watch)
    print("\nقبل:", json.dumps(pre, ensure_ascii=False))

    body = {"offerId": int(offer_id), "itemsToConsume": [], "amount": amount}
    print("الطلب:", "POST", ACCEPT, json.dumps(body, ensure_ascii=False))
    try:
        response = pc.post_json(ACCEPT, body, token=token)
    except Exception as exc:
        print("الرد:", type(exc).__name__, str(exc)[:900])
        print("\nمافيش تنفيذ تاني — القرار بعد قراءة الرفض.")
        return
    print("الرد:", json.dumps(response, ensure_ascii=False)[:1800])

    after = pc.fetch_inventory_for(account)
    post = totals(after.get("items"), watch)
    print("\nبعد:", json.dumps(post, ensure_ascii=False))
    print("الفارق:", json.dumps({k: post[k] - pre.get(k, 0) for k in post}, ensure_ascii=False))


if __name__ == "__main__":
    main()
