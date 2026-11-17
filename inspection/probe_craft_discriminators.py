# -*- coding: utf-8 -*-
"""قياس رد البوابة على كل اسم discriminator ممكن على مسار الـmutate — بآيدي وهمية.

ليه: مفيش مسار تصنيع مستقبلي في البوابة (كل أسماء craft رجعت `404 page not found`)،
لكن التوكن بتاعنا مسموحله `update/recycle/scrap/repair` بس، والـmutate نفسه بيقبل
discriminators تانية (split/combine/create مرفوضة). يبقى السؤال: التصنيع اسم
discriminator معروف للسيرفر ولا مفيش خالص؟

التوقيع: لو الاسم مش معروف البوابة بترد نفس الرد العام؛ ولو معروف وبيحتاج صلاحية
تانية الرد بيبان مختلف (أو بيرجع خطأ على الـinstance الوهمي بدل الـUNKNOWN).

الأمان: كل الآيدي وهمية (GUID صفر + assetId 1) — مفيش نسخة حقيقية في الطلب،
فمفيش أي قطعة تقدر تتلمس.

    python -m inspection.probe_craft_discriminators G22
"""
import json
import sys

sys.path.insert(0, ".")

from backend import config, pioneer_client as pc  # noqa: E402

MUTATE = "/v1/pioneer/inventory/v1/mutate"
FAKE_INSTANCE = "00000000-0000-0000-0000-000000000000"

NAMES = [
    "update", "recycle", "scrap", "repair", "delete",
    "split", "combine", "stack_merge", "create",
    "craft", "craft_item", "crafting", "cook", "build", "produce", "fabricate",
    "workbench", "craft_recipe", "recipe", "unlock", "learn", "activate",
    "upgrade", "assemble", "synthesize", "trade", "sell",
]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    if not token:
        print("مفيش توكن للحساب", account)
        return
    headers = pc.headers(token)
    sess = pc._session()
    print("### account:", account, "| manifest:", pc.load_manifest()[:12], "\n")
    for name in NAMES:
        body = {"mutations": [{"discriminator": name, "instanceId": FAKE_INSTANCE,
                              "assetId": 1, "amount": 1, "gameAssetId": 1,
                              "recipeId": 1, "wrapperId": FAKE_INSTANCE}]}
        resp = sess.post(pc.BASE + MUTATE, headers=headers, json=body,
                         timeout=min(config.HTTP_TIMEOUT, 25), verify=True)
        try:
            parsed = resp.json()
        except ValueError:
            parsed = {"raw": resp.text[:120]}
        reason = parsed.get("reason") or ""
        message = str(parsed.get("message") or "")[:60]
        print("%-13s -> %s %-18s %s" % (name, resp.status_code, reason, message))
    print()


if __name__ == "__main__":
    main()
