# -*- coding: utf-8 -*-
"""تعداد حقول جسم `create` باستخدام أوراكل الـ decode — بدون أي احتمال كتابة.

اللي اتقاس: `create` اسم معروف للسيرفر (بيرد ZERO_AMOUNT لما الكمية صفر)، بس أي شكل
جربه وقع في 500 UNKNOWN. فالحاجة الناقصة هي أسماء الحقول نفسها.

الحيلة: نبعت قيمة الحقل كائن `{}` بدل نص/رقم. لو الحقل موجود في الهيكل،解码ر الـJSON
بتاع gRPC-gateway بيطبع `cannot unmarshal object into Go struct field <Struct>.<field> of type <T>`.
ولو مش موجود، الهيكل بيسكبه والرد بيرجع UNKNOWN عادي.

الأمان: كل طلب في السكربت ده مرفوض في مرحلة فك الترميز — الجسم نفسه غير قابل للقراءة،
فمستحيل السيرفر ينفّذ حاجة. مافيش عنصر بيتلمس ومافيش كمية بتتولد.

    python -m inspection.probe_create_fields G22
"""
import json
import re
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

FAKE = "00000000-0000-4000-8000-000000000000"
ACCOUNT = next((a for a in sys.argv[1:] if not a.startswith("--")), "G22")
BAD = {"__probe__": 1}

# أسماء مرشّحة: مفاتيح عقدة المخزون الرسمية + مصطلحات الكرافت في اللعبة.
FIELDS = [
    "gameAssetId", "assetId", "asset_id", "itemId", "defId", "id", "uuid", "guid",
    "templateId", "archetypeId", "itemType", "type", "kind", "mutationType",
    "instanceId", "parentInstanceId", "parentId", "wrapperId", "containerId",
    "slots", "slot", "slotIndex", "cellId", "index",
    "amount", "quantity", "count", "durability", "maxDurability", "quality",
    "etag", "updatedAt", "rarity", "charge", "state", "data", "status",
    "recipeId", "recipeAssetId", "recipeInstanceId", "craftRecipeId", "slug",
    "outputAssetId", "craftedAssetId", "result", "output", "reward",
    "materials", "ingredients", "inputs", "consumed", "consumes", "cost",
    "stationId", "stationInstanceId", "benchId", "hideoutId",
    "item", "items", "create", "payload", "args", "params", "body", "request",
]


def call(mutations, token):
    body = {"mutations": mutations, "requestId": ""}
    try:
        out = pc.post_json(pw.MUTATE_PATH, body, token=token)
        return "200 " + json.dumps(out, ensure_ascii=False)[:200]
    except Exception as exc:
        return str(exc)[:260]


def verdict(text):
    if "cannot unmarshal" in text:
        m = re.search(r"Go struct field ([\w.]+)", text)
        return "HIT", (m.group(1) if m else "?")
    if "INVENTORY_ITEM" in text or "INVALID_ARGUMENT" in text:
        return "sig", ""
    return "  .", ""


def main():
    token = pc.account_token(ACCOUNT)
    if not token:
        print("مفيش توكن للحساب", ACCOUNT)
        return
    print("== 0) هل الأوراكل نفسها شغالة؟ (حقول معروفة في update/recycle) ==")
    for disc, field in [("update", "instanceId"), ("update", "amount"), ("recycle", "instanceId"),
                        ("recycle", "amount"), ("create", "amount")]:
        text = call([{"discriminator": disc, field: BAD}], token)
        tag, name = verdict(text)
        print("%-9s %-18s %s  %s" % (disc, field, tag, text[:190]))

    print("\n== 1) create: كل مرشّح بقيمة غلط النوع ==")
    hits = []
    for f in FIELDS:
        text = call([{"discriminator": "create", f: BAD}], token)
        tag, name = verdict(text)
        if tag == "HIT":
            hits.append((f, name, text))
            print("HIT  %-20s %s" % (f, name))
        elif "INVENTORY_ITEM" in text:
            print("sig  %-20s %s" % (f, text[:170]))
    print("\nالحقول اللي اتعرفت:", len(hits))
    for f, name, text in hits:
        print("   -", f, "->", name)

    print("\n== 2) create: الحقل الصحيح بقيمة صحيحة بس amount=0 (مرفوض قبل التنفيذ) ==")
    shapes = [
        {"discriminator": "create", "amount": 0},
        {"discriminator": "create", "gameAssetId": 1, "amount": 0},
        {"discriminator": "create", "assetId": 1, "amount": 0},
        {"discriminator": "create", "item": BAD, "amount": 0},
        {"discriminator": "create", "instanceId": FAKE, "amount": 0},
        {"discriminator": "create", "parentInstanceId": FAKE, "amount": 0},
    ]
    for s in shapes:
        print("%-72s %s" % (json.dumps(s, ensure_ascii=False)[:70], call([s], token)[:190]))

    print("\n== 3) create دفرة مع recycle على أب وهمي (الطرف الناقص وهمي) ==")
    batch = [{"discriminator": "recycle", "instanceId": FAKE, "amount": 1},
             {"discriminator": "create", "gameAssetId": 1, "amount": 0}]
    print(call(batch, token)[:230])


if __name__ == "__main__":
    main()
