# -*- coding: utf-8 -*-
"""بحث عن مسار BatchOperations اللي اللعبة نفسها بتستخدمه للكتابة.

من ذاكرة اللعبة (inspection/pf/mem_body_catch.txt) لقينا C++ flag حرفي:
"Route all client inventory mutations through the BatchOperations API instead
of MutateInventoryV1". يعني اللعبة ممكن تبعت الكتابة على مسار تاني غير
/v1/pioneer/inventory/v1/mutate — وده ممكن يفتح الدمج (combine) اللي
الـenum بتاع المسار الحالي مرفوض فيه.

المنهج آمن: GET بس (405 = المسار موجود بالفعل، 404 = مش موجود)، وبعدين POST
بجسم مجهول + instanceId وهمي (مفيش أي تغيير على أي عنصر).

    python -m inspection.probe_batch_ops G18
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402

FAKE = "11111111-1111-1111-1111-111111111111"

PREFIXES = ["/v1/pioneer/inventory/v1/", "/v1/pioneer/inventory/", "/v1/pioneer/"]

NAMES = [
    "batch-operations", "batch_operations", "batchoperations", "batchOperations",
    "batch-operate", "batch_operate", "batch-operations/mutate", "mutate/batch-operations",
    "inventory-batch-operations", "inventory_batch_operations", "inventoryoperations",
    "item-operations", "item_operations", "operations", "operation", "operations/batch",
    "batch-mutate/batch", "batch", "batches", "mutations", "batch_update", "batch-update",
    "batchUpdate", "batch_mutation", "batch-mutation", "batch_mutations", "batch-mutations",
    "combine", "combine-stacks", "combine_stacks", "stack", "stacks", "stack-merge",
    "stack_merge", "stackmerge", "consolidate", "merge", "split", "unstack",
    "amount", "quantity", "quantities", "transfer", "transfer-batch",
]

VERSIONS = ["", "v1/", "v2/"]


def candidates():
    out = []
    for pre in PREFIXES:
        for ver in VERSIONS:
            for name in NAMES:
                out.append(pre + ver + name)
    return out


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account or None)
    if not token:
        print("مفيش توكن جاهز — شغّل FahmySync واللعبة مفتوحة.")
        return
    print("حساب:", account)
    hits = []
    print("\n== 1) GET: 405 يعني المسار موجود ==")
    for path in candidates():
        try:
            out = pc.request(path, token=token, method="GET")
            print("!! %-58s موجود %s" % (path, json.dumps(out, ensure_ascii=False)[:100]))
            hits.append(path)
        except Exception as exc:
            msg = str(exc)
            if "404" in msg:
                continue
            if "405" in msg:
                print("!! %-58s 405 => مسار موجود!" % path)
                hits.append(path)
            else:
                print("?  %-58s %s" % (path, msg[:90]))
    print("\n== 2) POST بجسم مجهول (أوراكل — مفيش أي تأثير) ==")
    for path in hits:
        body = {"mutations": [{"discriminator": "zzz_not_a_kind", "instanceId": FAKE}],
                "requestId": ""}
        try:
            out = pc.request(path, token=token, method="POST", body=body)
            print("!! %-58s 200 %s" % (path, json.dumps(out, ensure_ascii=False)[:160]))
        except Exception as exc:
            print("   %-58s %s" % (path, str(exc)[:160]))
    if not hits:
        print("\nمفيش مسار جديد — كل الأسماء رجعت 404.")


if __name__ == "__main__":
    main()
