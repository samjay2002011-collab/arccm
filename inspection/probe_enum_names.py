# -*- coding: utf-8 -*-
"""مسح أسماء discriminators محتملة للدمج/التفكيك على بوابة Embark — كله بآيدي وهمي.

القاعدة: UNKNOWN = الاسم مش في enum التوكن ده. INVENTORY_ITEM_NOT_FOUND = الاسم معروف
والسيرفر وصل لمرحلة البحث عن العنصر. فأي اسم بيرد بـ NOT_FOUND كسرنا بيه الحيطة.

    python -m inspection.probe_enum_names RAIDER60766
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "RAIDER60766"
FAKE = "00000000-0000-4000-8000-000000000000"
TOKEN = pc.account_token(ACCOUNT)

NAMES = [
    "Split", "SPLIT", "splitStack", "split_stack", "SplitStack", "stack_split", "StackSplit",
    "splitItem", "split_item", "splitAmount", "split_amount", "SplitInventoryItem",
    "InventoryItemSplit", "inventory_item_split", "InventorySplit", "EInventoryMutation::Split",
    "Combine", "COMBINE", "combineStack", "combine_stack", "CombineStack", "stack_combine",
    "StackCombine", "combineItem", "combine_item", "merge", "Merge", "mergeStack", "merge_stack",
    "MergeStack", "MergeItem", "merge_item", "item_merge", "ItemMerge", "consolidate",
    "Consolidate", "consolidateStacks", "consolidate_stacks", "stackAll", "stack_all",
    "StackAll", "stack_merge", "StackMerge", "STACK_MERGE", "stackMerge", "mergeStacks",
    "restack", "Restack", "re_stack", "auto_stack", "autoStack", "AutoStack",
    "sort", "sortInventory", "sort_inventory", "organize", "arrange", "gather",
    "move", "moveItem", "move_item", "transfer", "transferItem", "equip", "attach", "detach",
    "update", "recycle",
]


def reason(exc):
    text = str(exc)
    try:
        body = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception:
        return text[:120]
    return str(body.get("reason") or body.get("detail") or "?")


def ask(name):
    muts = [{"discriminator": name, "instanceId": FAKE, "targetInstanceId": FAKE,
             "targetWrapperId": FAKE, "amount": 1}]
    try:
        pc.post_json(pw._url(), {"mutations": muts, "requestId": ""}, token=TOKEN)
        return "200"
    except Exception as exc:
        return reason(exc)


def build_names():
    """توليد كل الأشكال الممكنة لأفعال تكويم الستاكات — الأوراكل رخيص فمسح 300 اسم معقول."""
    verbs = ["split", "combine", "merge", "stack_merge", "stackmerge", "consolidate",
             "unstack", "restack", "stack", "sort", "organise", "organize", "tidy"]
    nouns = ["", "Item", "Items", "Stack", "Stacks", "Inventory", "InventoryItem"]
    forms = []
    for v in verbs:
        parts = [p for p in v.replace("-", "_").split("_") if p]
        snake = "_".join(parts)
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
        pascal = "".join(p.capitalize() for p in parts)
        for base in dict.fromkeys([snake, camel, pascal, v.upper(), snake.upper()]):
            for n in nouns:
                if not n:
                    forms.append(base)
                else:
                    forms.append("%s_%s" % (base, n))                      # split_InventoryItem
                    forms.append(base + n)                                 # splitInventoryItem
                    forms.append(pascal + n)                               # SplitInventoryItem
                    forms.append("%s%s" % (camel, n))                      # splitInventoryItem
                    forms.append("%s::%s" % ("EInventoryMutation", pascal))
                    forms.append("inventory_%s" % base)
                    forms.append("Inventory%s" % pascal)
    return list(dict.fromkeys(forms))


def main():
    names = ["update", "recycle"] + build_names()      # الضبط الحي الأول عشان نعرف الأوراكل شغال
    if len(sys.argv) > 2 and sys.argv[2] == "--quick":
        names = NAMES
    print("تجربة %d اسم على بوابة Embark (كلها بآيدي وهمي = صفر أثر)..." % len(names))
    hits = {}
    for i, name in enumerate(names):
        got = ask(name)
        hits.setdefault(got, []).append(name)
        if got != "UNKNOWN":
            print("  [%3d/%d] %-40s %s   <<< مش UNKNOWN" % (i + 1, len(names), name, got))
        elif i % 40 == 39:
            print("  ... %d/%d لسه كله UNKNOWN" % (i + 1, len(names)))
        sys.stdout.flush()
    print("\nالملخص: " + " | ".join("%s=%d" % (k, len(v)) for k, v in hits.items()))
    known = hits.get("INVENTORY_ITEM_NOT_FOUND") or []
    print("الأسماء المعروفة للـ enum: %s" % (known or "ولا واحد"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
