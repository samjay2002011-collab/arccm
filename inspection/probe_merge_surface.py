# -*- coding: utf-8 -*-
"""بحث عن نوع mutation يعمل دمج الأكوام (stack merge) على بوابة Pioneer.

الفكرة: البوابة بترد "UNKNOWN" على أي discriminator مش معروف عندها، وبترد خطأ
تاني (مش موجود/مرفوض) على النوع المعروف. فبنبعت آيدي وهمي — مفيش أي عنصر بيتلمس
مهما كانت النتيجة — ونفرز اللي بيسقط من الـ UNKNOWN.

    python -m inspection.probe_merge_surface
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw, store  # noqa: E402

BAD = "00000000-0000-4000-8000-000000000000"

# أسماء محتملة لدمج/نقل جزء من الكوم — مقيس منها قبل كده: split/combine/stack_merge/remove
NAMES = ["merge", "Merge", "stack_merge", "merge_stacks", "mergeStacks", "consolidate",
         "combine_stacks", "stack", "stacking", "stack_add", "add_amount", "set_amount",
         "change_amount", "modify_amount", "move_amount", "transfer", "transfer_amount",
         "withdraw", "deposit", "partial_move", "partial", "split_stack", "splitstack",
         "divide", "unstack", "unmerge", "join", "join_stacks", "collect", "gather",
         "compact", "organize", "sort", "reorganize", "arrange", "tidy", "inventory_merge",
         "stack_transfer", "amount_update", "update_amount", "updateAmount", "move_items",
         "move_item", "moveTo", "move_to", "stack_split", "reduce", "increase", "add",
         "subtract", "push", "pull", "swap", "exchange", "put", "take"]


def classify(text):
    low = (text or "").lower()
    if "unknown" in low:
        return "UNKNOWN"
    return "INTERESTING"


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "ELCONEJOMALO"
    token = pc.account_token(account)
    if not token:
        print("NO TOKEN")
        return
    print("== 1) أسماء الـ discriminator (آيدي وهمي = مفيش تنفيذ) ==")
    hits = {}
    for name in NAMES:
        body = {"mutations": [{"discriminator": name, "instanceId": BAD}], "requestId": ""}
        try:
            resp = pc.post_json(pw._url(), body, token=token)
            err = {"ok": True, "response": str(resp)[:160]}
        except Exception as exc:
            err = {"error": str(exc)[:220]}
        kind = classify(json.dumps(err, ensure_ascii=False))
        if kind == "INTERESTING":
            hits[name] = err
            print("  !! %-18s %s" % (name, json.dumps(err, ensure_ascii=False)[:220]))
        else:
            print("  .. %-18s unknown" % name)

    print("\n== 2) تعديل الـamount على آيدي وهمي: البوابة بتقول إيه؟ ==")
    shapes = [
        {"discriminator": "update", "instanceId": BAD, "slots": [""], "amount": 5},
        {"discriminator": "update", "instanceId": BAD, "amount": 5},
        {"discriminator": "update", "instanceId": BAD, "amount": 0},
        {"discriminator": "delete", "instanceId": BAD, "amount": 1},
        {"discriminator": "merge", "instanceId": BAD, "targetInstanceId": BAD, "amount": 1},
    ]
    for mut in shapes:
        try:
            resp = pc.post_json(pw._url(), {"mutations": [mut], "requestId": ""}, token=token)
            print("  ", json.dumps(mut, ensure_ascii=False)[:120], "->", str(resp)[:160])
        except Exception as exc:
            print("  ", json.dumps(mut, ensure_ascii=False)[:120], "->", str(exc)[:200])

    print("\n== 3) حدود التكديج اللي عندنا (stack_size من الشجرة المحلية) ==")
    conn = store.db()
    rows = conn.execute("select name, asset_id, stack_size, count(*) c from instances "
                        "where account=? group by asset_id order by stack_size", (account,)).fetchall()
    for r in rows:
        print("   %-28s stack_size=%-5s نسخ=%s" % (r["name"], r["stack_size"], r["c"]))
    conn.close()
    print("\nالمجموع:", len(hits), "اسم مش UNKNOWN")


if __name__ == "__main__":
    main()
