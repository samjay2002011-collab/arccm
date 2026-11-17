# -*- coding: utf-8 -*-
"""أوراكل أسماء حقول الدمج على بوابة Embark — بصفر تأثير على الحساب.

الفكرة: البوابة بتردّ UNKNOWN لما الـdiscriminator مش في الـenum، وبتردّ
INVENTORY_ITEM_NOT_FOUND لما الـdiscriminator/الحقل معروف بس الآيدي مش موجود.
فبنبعث آيديهات وهمية بأشكال مختلفة وبنشوف الرد: NOT_FOUND = الشكل ده معروف
للبوابة، UNKNOWN = الاسم ده مش موجود.

    python -m inspection.probe_merge_fieldnames G18
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402

FAKE = "11111111-1111-1111-1111-111111111111"
FAKE2 = "22222222-2222-2222-2222-222222222222"
PATH = "/v1/pioneer/inventory/v1/mutate"

DISCRIMINATORS = [
    "combine", "merge", "stack_merge", "stackMerge", "stack-merge", "merge_stacks",
    "mergeStacks", "combine_stacks", "combineStacks", "combine_item_stacks",
    "combineItemStacks", "merge_item_stacks", "mergeItemStacks", "consolidate",
    "consolidate_stacks", "unstack", "split", "split_stack", "splitStack",
    "stack_split", "stackSplit", "restack", "organize", "sort_stacks", "sortStacks",
    "combine_item_stack", "stack_combine", "stackCombine", "merge_stack", "mergeStack",
    "add_to_stack", "addToStack", "transfer", "amount", "set_amount", "setAmount",
    "quantity", "qty", "add_amount", "addAmount",
]

FIELD_NAMES = ["discriminator", "operation", "op", "type", "action", "kind",
               "mutationType", "mutation_type", "method", "command"]

FIELD_BODIES = [
    ("discriminator+instanceId", {"discriminator": "%s", "instanceId": FAKE}),
    ("discriminator+instanceId+amount", {"discriminator": "%s", "instanceId": FAKE,
                                         "amount": 1}),
    ("discriminator+instanceId+targetInstanceId",
     {"discriminator": "%s", "instanceId": FAKE, "targetInstanceId": FAKE2}),
    ("discriminator+instanceId+targetInstanceId+amount",
     {"discriminator": "%s", "instanceId": FAKE, "targetInstanceId": FAKE2, "amount": 1}),
    ("discriminator+instanceId+sourceInstanceId",
     {"discriminator": "%s", "instanceId": FAKE, "sourceInstanceId": FAKE2}),
    ("discriminator+instanceId+parentId",
     {"discriminator": "%s", "instanceId": FAKE, "parentId": FAKE2}),
]

WRAPPERS = ["mutations", "operations", "items", "batch", "requests", "changes"]


def try_body(token, body, label):
    try:
        out = pc.post_json(PATH, body, token=token)
        return "%s => 200 %s" % (label, json.dumps(out, ensure_ascii=False)[:120])
    except Exception as exc:
        msg = str(exc)
        if "INVENTORY_ITEM_NOT_FOUND" in msg:
            tag = "★ NOT_FOUND (الشكل معروف!)"
        elif "UNKNOWN" in msg:
            tag = "UNKNOWN (الاسم مش في الـenum)"
        elif "INVALID_ARGUMENT" in msg:
            tag = "INVALID_ARGUMENT"
        elif "ZERO_AMOUNT" in msg:
            tag = "ZERO_AMOUNT"
        else:
            tag = "؟"
        return "%s => %s | %s" % (label, tag, msg[:110].replace("\n", " "))


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account or None)
    if not token:
        print("مفيش توكن جاهز.")
        return
    print("حساب:", account)
    print("\n== 1) الشكل update (المعروف) بأسماء حقول مختلفة ==")
    for field in FIELD_NAMES:
        for name in ("combine", "merge", "stack_merge"):
            body = {field: name, "instanceId": FAKE, "targetInstanceId": FAKE2, "amount": 1}
            print("  " + try_body(token, {"mutations": [body]}, "%s=%s" % (field, name)))
    print("\n== 2) أسماء discriminator مختلفة داخل mutations[] ==")
    for name in DISCRIMINATORS:
        body = {"discriminator": name, "instanceId": FAKE, "targetInstanceId": FAKE2}
        print("  " + try_body(token, {"mutations": [body]}, name))
    print("\n== 3) غلاف الطلب بأسماء مختلفة ==")
    for wrapper in WRAPPERS:
        body = {"discriminator": "combine", "instanceId": FAKE, "targetInstanceId": FAKE2}
        print("  " + try_body(token, {wrapper: [body]}, wrapper))
    print("\n== 4) update بحقول الهدف (بلا تغيير كمية) ==")
    for label, tpl in FIELD_BODIES:
        body = dict(tpl)
        body["discriminator"] = "update"
        print("  " + try_body(token, {"mutations": [body]}, label))


if __name__ == "__main__":
    main()
