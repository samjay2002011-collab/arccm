# -*- coding: utf-8 -*-
"""صيد مسارات عروض/مستويات على البوابة: GET على مسار كتابة بيرجع 405، والمfilosofiغير الموجود 404."""
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc  # noqa: E402

SUFFIX = ["", "/list", "/accept", "/claim", "/complete", "/cancel", "/update", "/open",
          "/start", "/finish", "/collect", "/execute", "/create", "/delete", "/state", "/get"]
BASE = ["/v1/pioneer/offers", "/v1/pioneer/offers/transaction", "/v1/pioneer/offers/transactions",
        "/v1/pioneer/levels", "/v1/pioneer/levels/reward", "/v1/pioneer/generator",
        "/v1/pioneer/generators", "/v1/pioneer/scrappy", "/v1/pioneer/rooster",
        "/v1/pioneer/rounds", "/v1/pioneer/round", "/v1/pioneer/chamber", "/v1/pioneer/chambers",
        "/v1/pioneer/crafting", "/v1/pioneer/craft", "/v1/pioneer/transactions",
        "/v1/pioneer/queue", "/v1/pioneer/timers", "/v1/pioneer/boosters",
        "/v1/pioneer/inventory/accept", "/v1/pioneer/inventory/claim"]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    found, missing = [], []
    for base in BASE:
        for suf in SUFFIX:
            path = base + suf
            try:
                pc.request(path, token=token)
                verdict = "200"
            except Exception as err:
                text = str(err)
                if "404" in text:
                    verdict = "404"
                elif "405" in text:
                    verdict = "405 (مسار كتابة موجود)"
                elif "500" in text:
                    verdict = "500"
                else:
                    verdict = text[:70]
            if verdict != "404":
                found.append("%-46s %s" % (path, verdict))
                print(found[-1])
            else:
                missing.append(path)
    print("\nغير موجود: %d مسار" % len(missing))


if __name__ == "__main__":
    main()
