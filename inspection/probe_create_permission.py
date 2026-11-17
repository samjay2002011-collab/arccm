# -*- coding: utf-8 -*-
"""هل التوكن بتاعنا مسموحله بـ discriminator=create؟ — بقيم وهمية فقط.

التوقيع اللي اتقاس: السيرفر بيرد `500 internal error` على الأسماء اللي يعرفها
(update/recycle/scrap/repair/delete/create) و`400` على أي اسم تاني — يعني `create`
قيمة enum حقيقية في مسار الـmutate. السؤال الفاصل: مسموح بينا ولا لأ؟

القياس ده بـ assetId وهمي (1) وبكمية 1: مفيش أيدي حقيقي لأي عنصر أو نسخة أو وصفة،
فمستحيل تنتج قطعة فعلية. لو الرد طلع سبب مفصّل (PERMISSION / FORBIDDEN / NOT_FOUND)
يبقى عرفنا الجواب من غير ما نلمس حاجة.

    python -m inspection.probe_create_permission G22
"""
import json
import sys

sys.path.insert(0, ".")

from backend import config, pioneer_client as pc  # noqa: E402

MUTATE = "/v1/pioneer/inventory/v1/mutate"
FAKE = "00000000-0000-0000-0000-000000000000"

# كل الأجسام بـ assetId وهمي (1) — رقم مش موجود في اللعبة.
CASES = [
    ("create/assetId", {"mutations": [{"discriminator": "create", "assetId": 1, "amount": 1}]}),
    ("create/gameAssetId", {"mutations": [{"discriminator": "create", "gameAssetId": 1, "amount": 1}]}),
    ("create/instanceId", {"mutations": [{"discriminator": "create", "instanceId": FAKE, "amount": 1}]}),
    ("create/bare", {"mutations": [{"discriminator": "create"}]}),
    ("update/assetId (كنترول)", {"mutations": [{"discriminator": "update", "assetId": 1, "amount": 1}]}),
    ("recycle/bare (كنترول)", {"mutations": [{"discriminator": "recycle"}]}),
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
    for label, body in CASES:
        resp = sess.post(pc.BASE + MUTATE, headers=headers, json=body,
                         timeout=min(config.HTTP_TIMEOUT, 25), verify=True)
        try:
            parsed = json.dumps(resp.json(), ensure_ascii=False)[:220]
        except ValueError:
            parsed = resp.text[:220].replace("\n", " ")
        print("%-26s %s  %s" % (label, resp.status_code, parsed))
    print()


if __name__ == "__main__":
    main()
