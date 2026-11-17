# -*- coding: utf-8 -*-
"""مسبار لمسار التصنيع في بوابة Embark — POST بأجسام مستحيل تنفّذ أي شيء.

ليه: الشراء طلع ليه مقابل رسمي (`/v1/pioneer/offers/accept`)، فالتصنيع ممكن يكون
نفس الحالة. البوابة بترد `404 HTTP_STATUS_NOT_FOUND` على المسار الوهمي، و`400
INVALID_ARGUMENT` على مسار موجود بجسم غلط — فالفرق بين الاتنين بيكشف وجود المسار
من غير أي تنفيذ.

الأمان: كل جسم إما فاضي أو أيدي وهمي (`recipeId: 1` / `assetId: 1`) — مفيش أي
أيدي حقيقي لعنصر أو وصفة أو نسخة، فمفيش حاجة تتصرف أو تتحرق. مفيش GET على مسارات كتابة.

    python -m inspection.probe_craft_routes G22
"""
import sys

sys.path.insert(0, ".")

import requests  # noqa: E402

from backend import pioneer_client as pc  # noqa: E402

# مسارات التصنيع المحتملة + كنترول (مسار وهمي ومار موجود فعلاً).
PATHS = [
    ("/v1/pioneer/nope/nope", "كنترول: مسار وهمي"),
    ("/v1/pioneer/inventory/v1/mutate", "كنترول: مسار موجود"),
    ("/v1/pioneer/craft", "craft"),
    ("/v1/pioneer/crafting", "crafting"),
    ("/v1/pioneer/crafting/craft", "crafting/craft"),
    ("/v1/pioneer/crafting/accept", "crafting/accept"),
    ("/v1/pioneer/crafting/v1/craft", "crafting/v1/craft"),
    ("/v1/pioneer/recipes", "recipes"),
    ("/v1/pioneer/recipes/craft", "recipes/craft"),
    ("/v1/pioneer/recipes/accept", "recipes/accept"),
    ("/v1/pioneer/workshop/craft", "workshop/craft"),
    ("/v1/pioneer/hideout/craft", "hideout/craft"),
    ("/v1/pioneer/stations/craft", "stations/craft"),
    ("/v1/pioneer/progression/craft", "progression/craft"),
    ("/v1/pioneer/blueprints/craft", "blueprints/craft"),
    ("/v1/pioneer/production/craft", "production/craft"),
    ("/v1/pioneer/inventory/craft", "inventory/craft"),
    ("/v1/pioneer/inventory/v1/craft", "inventory/v1/craft"),
    ("/v1/pioneer/inventory/recipe", "inventory/recipe"),
    ("/v1/pioneer/inventory/v1/recipe", "inventory/v1/recipe"),
    ("/v1/pioneer/inventory/build", "inventory/build"),
    ("/v1/pioneer/inventory/v1/build", "inventory/v1/build"),
    ("/v1/pioneer/inventory/v1/produce", "inventory/v1/produce"),
    ("/v1/pioneer/inventory/v1/fabricate", "inventory/v1/fabricate"),
    ("/v1/pioneer/inventory/v1/create", "inventory/v1/create"),
    ("/v1/pioneer/inventory/v1/spawn", "inventory/v1/spawn"),
    ("/v1/pioneer/offers/craft", "offers/craft"),
    ("/v1/pioneer/offers/buy", "offers/buy"),
]

# أجسام بلا أي أيدي حقيقي: فاضي، وواحد بحقول وهمية.
BODIES = [{}, {"recipeId": 1}, {"assetId": 1, "amount": 1}]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    if not token:
        print("مفيش توكن للحساب", account)
        return
    headers = pc.headers(token)
    sess = pc._session()
    print("### account:", account, "| manifest:", pc.load_manifest()[:12], "\n")
    for path, label in PATHS:
        seen = set()
        for body in BODIES:
            resp = sess.post(pc.BASE + path, headers=headers, json=body,
                             timeout=config_timeout(), verify=True)
            text = resp.text[:160].replace("\n", " ")
            try:
                import json as _j
                code = (_j.loads(resp.text).get("code") or "")
            except Exception:
                code = ""
            key = (resp.status_code, code)
            if key in seen:
                continue
            seen.add(key)
            mark = "  " if resp.status_code == 404 and "NOT_FOUND" in text else "**"
            print("%s POST %-42s %-14s %s %s | %s" % (mark, path, label[:14],
                                                     resp.status_code, code, text))
        print()


def config_timeout():
    from backend import config
    return min(config.HTTP_TIMEOUT, 25)


if __name__ == "__main__":
    main()
