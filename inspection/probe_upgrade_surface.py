# -*- coding: utf-8 -*-
"""مسح: هل بوابة Embark بتعرف ترقّي سلاح (upgrade)؟

كل الطلبات هنا على instanceId وهمي (مش موجود) أو على مسار مش موجود — فمفيش
أي عنصر بيتلمس ولا بيتغير. بنقرا رسالة الرفض نفسها عشان نعرف:
  UNKNOWN = النوع/المسار مش موجود أصلاً
  غير ذلك = موجود بس مرفوض (يعني ممكن نلاقي له طريقة)
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

BAD = "00000000-0000-4000-8000-000000000000"
ACCOUNT = "ELCONEJOMALO"

DISCRIMINATORS = [
    "update", "create", "delete", "recycle", "scrap", "repair",
    "upgrade", "enhance", "forge", "craft", "workbench", "bench",
    "modify", "transform", "evolve", "ascend", "tier", "levelup",
    "level_up", "reroll", "salvage", "dismantle", "breakdown",
]

ROUTES = [
    "/v1/pioneer/inventory/v1/upgrade",
    "/v1/pioneer/inventory/v1/weapon/upgrade",
    "/v1/pioneer/inventory/v1/craft",
    "/v1/pioneer/inventory/v1/recipe",
    "/v1/pioneer/inventory/v1/bench",
    "/v1/pioneer/inventory/v1/workbench",
    "/v1/pioneer/inventory/v1/forge",
    "/v1/pioneer/weapons/v1/upgrade",
    "/v1/pioneer/weapon/v1/upgrade",
    "/v1/pioneer/crafting/v1/upgrade",
    "/v1/pioneer/crafting/v1/craft",
    "/v1/pioneer/workbench/v1/upgrade",
    "/v1/pioneer/workbench/v1/craft",
    "/v1/pioneer/bench/v1/upgrade",
    "/v1/pioneer/forge/v1/upgrade",
    "/v1/pioneer/recipes/v1/list",
    "/v1/pioneer/benchmarks/v1/list",
    "/v1/pioneer/loot/v1/upgrade",
    "/v1/pioneer/stash/v1/upgrade",
    "/v1/pioneer/raiders",
    "/v1/pioneer/inventory/v1/mutate",
]

UPDATE_FIELDS = [
    {"gameAssetId": 123456},
    {"qualityLevel": 2},
    {"level": 2},
    {"targetLevel": 2},
    {"upgradeLevel": 2},
    {"quality_level": 2},
    {"displayName": "X"},
]


def brief(err):
    text = str(err)
    for code in ("UNKNOWN", "INVENTORY_ITEM_NOT_FOUND", "INVALID_ARGUMENT",
                 "INVENTORY_ITEM_ZERO_AMOUNT", "FAILED_PRECONDITION", "RBAC",
                 "404 page not found", "405", "403"):
        if code in text:
            return code + " :: " + text[:190]
    return text[:220]


def main():
    token = pc.account_token(ACCOUNT)
    print("account:", ACCOUNT, "| token:", "yes" if token else "NO")
    if not token:
        return

    print("\n== 1) أنواع الـ mutate (على id وهمي) ==")
    for disc in DISCRIMINATORS:
        body = {"mutations": [{"discriminator": disc, "instanceId": BAD}], "requestId": ""}
        try:
            out = pc.post_json(pw._url(), body, token=token)
            print("%-12s OK  %s" % (disc, json.dumps(out, ensure_ascii=False)[:200]))
        except Exception as exc:
            print("%-12s %s" % (disc, brief(exc)))

    print("\n== 2) مسارات تحت /v1/pioneer (GET ثم POST فاضي) ==")
    for path in ROUTES:
        try:
            out = pc.request(path, token=token, method="GET")
            print("GET  %-42s OK %s" % (path, json.dumps(out, ensure_ascii=False)[:120]))
        except Exception as exc:
            g = brief(exc)
            if "404 page not found" in g:
                print("GET  %-42s 404 (المسار مش موجود)" % path)
            else:
                print("GET  %-42s %s" % (path, g))
        try:
            out = pc.request(path, token=token, method="POST", body={})
            print("POST %-42s OK %s" % (path, json.dumps(out, ensure_ascii=False)[:120]))
        except Exception as exc:
            p = brief(exc)
            if "404 page not found" in p:
                print("POST %-42s 404 (المسار مش موجود)" % path)
            else:
                print("POST %-42s %s" % (path, p))

    print("\n== 3) حقول updateExtra (هل الـ update بيقبل تغيير الأصل/المستوى؟) ==")
    for extra in UPDATE_FIELDS:
        mut = {"discriminator": "update", "instanceId": BAD, "slots": [], "amount": 1}
        mut.update(extra)
        body = {"mutations": [mut], "requestId": ""}
        try:
            out = pc.post_json(pw._url(), body, token=token)
            print("%-22s OK %s" % (json.dumps(extra), json.dumps(out, ensure_ascii=False)[:200]))
        except Exception as exc:
            print("%-22s %s" % (json.dumps(extra), brief(exc)))


if __name__ == "__main__":
    main()
