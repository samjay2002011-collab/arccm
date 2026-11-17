# -*- coding: utf-8 -*-
"""كل أسطح القراءة المتبقية على البوابة — بحث عن حالة الـtransaction اللي عملناها."""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc  # noqa: E402

GETS = ["/v1/pioneer/quests", "/v1/pioneer/levels/list", "/v1/pioneer/expeditions",
        "/v1/pioneer/seasonal-rewards", "/v1/pioneer/compensations", "/v1/pioneer/bonuses",
        "/v1/pioneer/crates", "/v1/pioneer/raiders", "/v1/pioneer/stats",
        "/v1/pioneer/offers/transactions/list", "/v1/pioneer/transactions",
        "/v1/pioneer/generators", "/v1/pioneer/hideout", "/v1/pioneer/hideout/state",
        "/v1/shared/raiders", "/v1/pioneer/profile"]
POSTS = [("/v1/pioneer/inventory/list", {}),
         ("/v1/pioneer/projects/list", {}),
         ("/v1/pioneer/offers/transactions/list", {}),
         ("/v1/pioneer/offers/list", {})]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    for path in GETS:
        try:
            resp = pc.request(path, token=token)
            txt = json.dumps(resp, ensure_ascii=False)
            flag = "  <<< فيه transaction/offer" if ("transaction" in txt.lower() or "offerId" in txt) else ""
            print("GET  %-40s 200 %s%s" % (path, txt[:320], flag))
        except Exception as err:
            print("GET  %-40s %s" % (path, str(err)[:120]))
    for path, body in POSTS:
        try:
            resp = pc.post_json(path, body, token=token)
            txt = json.dumps(resp, ensure_ascii=False)
            flag = "  <<< فيه transaction/offer" if ("transaction" in txt.lower() or "offerId" in txt) else ""
            print("POST %-40s 200 %s%s" % (path, txt[:320], flag))
        except Exception as err:
            print("POST %-40s %s" % (path, str(err)[:160]))


if __name__ == "__main__":
    main()
