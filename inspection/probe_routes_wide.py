# -*- coding: utf-8 -*-
"""مسح أوسع لمسارات بوابة Embark: هل فيه مسار ترقية/مworkshop غير اللي نعرفه؟

كل الطلبات GET فقط — مفيش أي كتابة. البوابة بترد 404 على المسار الغلط و405/200
على المسار الصح، فالفرق بيكشف المسارات الموجودة.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402

ACCOUNT = "ELCONEJOMALO"

PATHS = [
    "/v1/pioneer/inventory/v1/items",
    "/v1/pioneer/inventory/v1/cells",
    "/v1/pioneer/inventory/v1/contents",
    "/v1/pioneer/inventory/v1/recipes",
    "/v1/pioneer/inventory/v1/upgrade",
    "/v1/pioneer/inventory/v1/bench",
    "/v1/pioneer/inventory/v1/status",
    "/v1/pioneer/inventory/v1/meta",
    "/v1/pioneer/inventory/v1/items/upgrade",
    "/v1/pioneer/inventory/v1/items/recipe",
    "/v1/pioneer/raiders/v1/list",
    "/v1/pioneer/raiders/v1/inventory",
    "/v1/pioneer/progress",
    "/v1/pioneer/profile",
    "/v1/pioneer/assets",
    "/v1/pioneer/manifest",
    "/v1/pioneer/loot",
    "/v1/pioneer/quests",
    "/v1/pioneer/quest",
    "/v1/pioneer/workshop",
    "/v1/pioneer/workbench",
    "/v1/pioneer/benchmarks",
    "/v1/pioneer/stash",
    "/v1/pioneer/backpack",
    "/v1/pioneer/loadout",
    "/v1/pioneer/blueprints",
    "/v1/pioneer/openapi.json",
    "/v1/pioneer/swagger.json",
    "/v1/pioneer/inventory/v1/openapi.json",
    "/v1/shared/profile",
    "/v1/shared/manifest",
    "/v1/shared/crafting",
    "/v1/shared/workbench",
    "/v1/shared/inventory",
    "/v1/shared/config",
    "/v1/shared/items",
    "/v1/shared/catalog",
    "/v1/shared/assets",
    "/v1/shared/blueprints",
    "/v1/shared/upgrade",
]


def main():
    token = pc.account_token(ACCOUNT)
    if not token:
        print("no token")
        return
    print("== GET sweep (404 = مش موجود، غيره = موجود) ==")
    for path in PATHS:
        try:
            out = pc.request(path, token=token, method="GET")
            text = json.dumps(out, ensure_ascii=False)
            print("%-42s EXISTS %s" % (path, text[:150]))
        except Exception as exc:
            msg = str(exc)
            if "404 page not found" in msg:
                print("%-42s 404" % path)
            elif "403" in msg:
                print("%-42s 403 (معروف بس مقفول على هذا التوكن)" % path)
            else:
                print("%-42s %s" % (path, msg[:150]))


if __name__ == "__main__":
    main()
