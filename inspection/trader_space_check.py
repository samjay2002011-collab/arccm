# -*- coding: utf-8 -*-
"""هل رفض الشراء سببه الشكل ولا امتلاء الستاش؟ — قراءة فقط.

الحالتين اللي بيفرّق بينهم:
  أ) عرض مفتوح في الكتالوج ومساحته في الستاش فاضية → لو البوابة قبلت، يبقى الرفض
     السابق كان بسبب المساحة.
  ب) نفس العرض وستاشه مليان → سقف المتوقع 400.

السكربت ما بيشتريش حاجة: بيسأل البوابة عن العرض بكمية 0 (مفيش صرف ومفيش تسليم)
وبيقارن رد كل حساب.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, traders  # noqa: E402

ACCEPT = "/v1/pioneer/offers/accept"


def free_stash(tree):
    lay = pioneer_tree.layout(tree)
    cells = [str(c) for c in (lay.get("stash") or {}).get("slots") or []]
    return sum(1 for c in cells if not tree.first_child(c)), len(cells)


def main():
    offer_id = int(sys.argv[1]) if len(sys.argv) > 1 else 727507836
    accounts = sys.argv[2:] or ["G21", "G22"]
    for account in accounts:
        rec_token = pc.account_token(account)
        data = pc.fetch_inventory_for(account)
        tree = pioneer_tree.Tree((data or {}).get("items") or [])
        open_cells, total = free_stash(tree)
        coins = sum(int(n.get("amount") or 0) for n in tree.by_id.values()
                    if str(n.get("gameAssetId")) == "-898439395")
        print("%s | ستاش %d/%d فاضي | كوينز %d" % (account, open_cells, total, coins))
        body = {"offerId": offer_id, "itemsToConsume": [], "amount": 0}
        try:
            resp = pc.post_json(ACCEPT, body, token=rec_token)
            print("   كمية 0 -> 200", json.dumps(resp, ensure_ascii=False)[:200])
        except Exception as exc:
            print("   كمية 0 ->", str(exc).split("->")[-1].strip()[:160])


if __name__ == "__main__":
    main()
