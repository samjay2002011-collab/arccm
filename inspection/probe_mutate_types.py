# -*- coding: utf-8 -*-
"""اختبار الأنواع اللي البوابة بتعرفها فعلاً: delete / recycle / scrap / repair.

النتيجة اللي أمنتها: أسماء زي sell/trade/split بيرجع لها UNKNOWN (البوابة مابتعرفهاش)،
بينما delete/recycle/scrap/repair بيرجعوا INVENTORY_ITEM_NOT_FOUND على id وهمي —
يعني النوع مقبول والطلب وصل لمنطق العنصر.

الطور ده آمن: بيستخدم amount=0 (مرفوض قبل التنفيذ) و repair على عنصر سليم.
الطور المدمّر (--burn) بينفذ على أرخص ستاك بقطعة واحدة، وده مطلوب صراحةً من المستخدم.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import config, pioneer_client as pc, pioneer_tree, pioneer_write as pw, store  # noqa: E402

BURN = "--burn" in sys.argv
ACCOUNT = next((a for a in sys.argv[1:] if not a.startswith("--")), "")


def call(disc, instance_id, amount=None, extra=None):
    mut = {"discriminator": disc, "instanceId": instance_id}
    if amount is not None:
        mut["amount"] = amount
    mut.update(extra or {})
    body = {"mutations": [mut], "requestId": ""}
    try:
        return {"ok": True, "response": pc.post_json(pw._url(), body, token=TOKEN)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:260]}


def main():
    global TOKEN
    conn = store.db()
    names = [r["name"] for r in store.list_accounts(conn, enabled_only=True)]
    target = ACCOUNT or names[0]
    TOKEN = pc.account_token(target)
    data = pc.fetch_inventory_for(target)
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    payload, _ = store.read_snapshot(conn, target)
    print("account:", target, "| items in tree:", len(tree.items))

    # أرخص ستاك مسمّى في الستاش — أي تجربة مدمّرة تروح على أقل قيمة
    sample = None
    for slot in (payload or {}).get("stash") or []:
        item = slot.get("item") or {}
        qty = int(item.get("quantity") or item.get("amount") or 1)
        nm = (item.get("display_name") or item.get("name") or "").strip()
        iid = str(item.get("instanceId") or "")
        if qty < 2 or not nm or nm.lower().startswith("item ") or iid not in tree.by_id:
            continue
        if sample is None or qty < sample[1]:
            sample = (iid, qty, nm)
    if not sample:
        print("مفيش ستاك مناسب في الستاش")
        return
    iid, qty, name = sample
    entry = tree.by_id[iid]
    print("sample: %s | instance %s | amount %s\n" % (name, iid, entry.get("amount")))

    print("== amount=0 (مرفوض قبل التنفيذ — بيكشف شكل الطلب)")
    for disc in ("delete", "recycle", "scrap", "repair"):
        show = call(disc, iid, 0)
        print("%-9s %s" % (disc, json.dumps(show, ensure_ascii=False)[:240]))

    print("\n== repair على عنصر سليم (غير مدمّر)")
    print(json.dumps(call("repair", iid), ensure_ascii=False)[:240])

    if not BURN:
        print("\n(الشغل المدمّر متوقّف — شغّل بـ --burn)")
        return

    print("\n== BURN: recycle لقطعة واحدة من %s" % name)
    before = int(entry.get("amount") or 1)
    out = call("recycle", iid, 1)
    print(json.dumps(out, ensure_ascii=False)[:400])
    fresh = pioneer_tree.Tree((pc.fetch_inventory_for(target) or {}).get("items") or [])
    after = fresh.by_id.get(iid)
    print("amount %s -> %s (العنصر %s)" % (before, after and after.get("amount"),
                                           "موجود" if after else "اختفى"))
    if after:
        print("\n== BURN: delete لقطعة واحدة")
        out = call("delete", iid, 1)
        print(json.dumps(out, ensure_ascii=False)[:400])
        fresh = pioneer_tree.Tree((pc.fetch_inventory_for(target) or {}).get("items") or [])
        gone = fresh.by_id.get(iid)
        print("amount دلوقتي: %s" % (gone and gone.get("amount")))
    conn.close()


if __name__ == "__main__":
    main()
