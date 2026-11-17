# -*- coding: utf-8 -*-
"""ليه عرض الأكل بيتنفّذ وعرض الدقائق بيترفض؟ مقارنة الحقول + شكل الرد الكامل."""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc  # noqa: E402

GAME_DATA = "data/pioneer_game_data.json"
FOOD = 577343568
ROUNDS = 458276432  # Generator Level 5 - Minute 1


def main():
    offers = json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]
    by_id = {o["offerId"]: o for o in offers}
    for oid in (FOOD, ROUNDS):
        print("\n===== %s =====" % oid)
        print(json.dumps(by_id.get(oid), ensure_ascii=False, indent=1)[:2600])

    # أي حقول موجودة في واحدة ومش في التانية؟
    a, b = by_id[FOOD], by_id[ROUNDS]
    keys = sorted(set(a) | set(b))
    print("\n----- مقارنة الحقول -----")
    for k in keys:
        va, vb = a.get(k, "<م absent>"), b.get(k, "<م absent>")
        if json.dumps(va, sort_keys=True) != json.dumps(vb, sort_keys=True):
            print("%-22s food=%s | rounds=%s" % (k, json.dumps(va, ensure_ascii=False)[:150],
                                                 json.dumps(vb, ensure_ascii=False)[:150]))

    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    data = pc.fetch_inventory_for(account)
    print("\n----- مفاتيح رد المخزون -----")
    for k, v in data.items():
        print("%-24s %s" % (k, json.dumps(v, ensure_ascii=False)[:200] if not isinstance(v, list) else "list len=%d" % len(v)))
    # هل في أي قسم فيه transactions جوه أي مفتاح؟
    blob = json.dumps(data, ensure_ascii=False)
    for probe in ("transaction", "offerId", "startTime", "generator", "Scrappy"):
        print("contains %-13s -> %s" % (probe, probe.lower() in blob.lower()))


if __name__ == "__main__":
    main()
