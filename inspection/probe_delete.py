# -*- coding: utf-8 -*-
"""شكل طلب delete الناجح + تأكيد النتيجة من الشجرة الحية.

البوابة بترفض delete من غير amount صحيح (INVALID_ARGUMENT) وبتقبل recycle
للنسخة كلها. الاختبار ده بيحط amount=1 على ستاك أرخص عنصر في الستاش — المستخدم
أذن بالحذف على الحساب ده لأنه حساب جديد ملوش أهمية.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, pioneer_write as pw, store  # noqa: E402

ACCOUNT = next((a for a in sys.argv[1:] if not a.startswith("--")), "")
ACTION = "delete"


def pick(conn, target, tree):
    """أرخص ستاك مسمّى في الستاش، وبعيد عن آخر نسخة اتلمست."""
    payload, _ = store.read_snapshot(conn, target)
    best = None
    for slot in (payload or {}).get("stash") or []:
        item = slot.get("item") or {}
        qty = int(item.get("quantity") or item.get("amount") or 1)
        nm = (item.get("display_name") or item.get("name") or "").strip()
        iid = str(item.get("instanceId") or "")
        if qty < 2 or not nm or nm.lower().startswith("item ") or iid not in tree.by_id:
            continue
        if best is None or qty < best[1]:
            best = (iid, qty, nm)
    return best


def main():
    conn = store.db()
    target = ACCOUNT or [r["name"] for r in store.list_accounts(conn, enabled_only=True)][0]
    token = pc.account_token(target)
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(target) or {}).get("items") or [])
    picked = pick(conn, target, tree)
    if not picked:
        print("مفيش ستاك مناسب")
        return
    iid, qty, name = picked
    row = tree.by_id[iid]
    full = int(row.get("amount") or qty)
    print("قبل: %s | amount %s | instance %s" % (name, full, iid))

    variants = [
        ("amount = الكل", {"discriminator": "delete", "instanceId": iid, "amount": full}),
        ("الكل + slots", {"discriminator": "delete", "instanceId": iid, "amount": full, "slots": [""]}),
        ("الكل + etag", {"discriminator": "delete", "instanceId": iid, "amount": full,
                        "etag": row.get("etag")}),
        ("بلا amount", {"discriminator": "delete", "instanceId": iid}),
        ("بلا amount + slots", {"discriminator": "delete", "instanceId": iid, "slots": [""]}),
    ]
    for label, body in variants:
        try:
            out = pc.post_json(pw._url(), {"mutations": [body], "requestId": ""}, token=token)
            print("\nطلب [%s] %s -> نجح" % (label, json.dumps(body, ensure_ascii=False)[:150]))
            print(json.dumps(out, ensure_ascii=False)[:900])
            break
        except Exception as exc:
            print("\nطلب [%s] -> %s" % (label, str(exc)[:200]))

    fresh = pioneer_tree.Tree((pc.fetch_inventory_for(target) or {}).get("items") or [])
    row = fresh.by_id.get(iid)
    print("\nبعد: %s" % (json.dumps({k: row.get(k) for k in ("amount", "gameAssetId", "etag")},
                                    ensure_ascii=False) if row else "النسخة اختفت"))
    conn.close()


if __name__ == "__main__":
    main()
