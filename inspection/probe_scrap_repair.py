# -*- coding: utf-8 -*-
"""scrap / repair / delete على عناصرها الصح: سلاح للإعدام، عنصر تالف للإصلاح.

كل الطلبات على حساب جديد أذن صاحبه بأي تجربة. بنطبع الفرق في الشجرة بعد كل طلب.
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import catalog, pioneer_client as pc, pioneer_tree, pioneer_write as pw, store  # noqa: E402

ACCOUNT = next((a for a in sys.argv[1:] if not a.startswith("--")), "")


def attempt(token, body):
    try:
        out = pc.post_json(pw._url(), {"mutations": [body], "requestId": ""}, token=token)
        return {"ok": True, "response": out}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def main():
    conn = store.db()
    target = ACCOUNT or [r["name"] for r in store.list_accounts(conn, enabled_only=True)][0]
    token = pc.account_token(target)
    payload, _ = store.read_snapshot(conn, target)
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(target) or {}).get("items") or [])
    names = pioneer_tree.asset_names()

    slots = [(s.get("item") or {}) for s in ((payload or {}).get("stash") or [])]
    slots += [(s.get("item") or {}) for s in ((payload or {}).get("overflow") or [])]
    weapons = [i for i in slots if i.get("attachments") is not None
               and catalog.group_for(i.get("display_name") or i.get("name"),
                                     asset_id=str(i.get("asset_id") or "")) == "Weapons"]
    damaged = [i for i in slots if (i.get("durability") or 0) < (i.get("max_durability") or 0)]
    print("account:", target, "| أسلحة في المخزن:", len(weapons), "| تالف:", len(damaged))

    if weapons:
        w = weapons[0]
        iid = str(w.get("instanceId"))
        nm = w.get("display_name") or w.get("name") or "?"
        aid = str(w.get("gameAssetId") or w.get("asset_id") or "")
        print("\n== scrap على %s" % nm)
        for body in ({"discriminator": "scrap", "instanceId": iid},
                     {"discriminator": "scrap", "instanceId": iid,
                      "amount": int(w.get("quantity") or 1)}):
            print(json.dumps(body, ensure_ascii=False)[:120], "->",
                  json.dumps(attempt(token, body), ensure_ascii=False)[:500])
            fresh = pioneer_tree.Tree((pc.fetch_inventory_for(target) or {}).get("items") or [])
            print("   موجود في الشجرة؟", iid in fresh.by_id)
            if iid not in fresh.by_id:
                break

    if damaged:
        d = damaged[0]
        iid = str(d.get("instanceId"))
        print("\n== repair على %s (%s/%s)" % (d.get("display_name") or d.get("name"),
                                             d.get("durability"), d.get("max_durability")))
        for body in ({"discriminator": "repair", "instanceId": iid},
                     {"discriminator": "repair", "instanceId": iid, "amount": 1}):
            print(json.dumps(body, ensure_ascii=False)[:120], "->",
                  json.dumps(attempt(token, body), ensure_ascii=False)[:500])
    else:
        print("\n(مفيش عنصر تالف نجرب عليه repair)")

    # delete: يمكن محتاج الأب (الخان اللي العنصر جواها) مش نفس النسخة
    one = next((i for i in slots if int(i.get("quantity") or 1) >= 1), None)
    if one:
        iid = str(one.get("instanceId"))
        cell = str(tree.parent.get(iid) or "")
        print("\n== delete بنمط الأب/الخانة %s" % cell)
        for body in ({"discriminator": "delete", "instanceId": cell, "slots": [s for s in
                        (tree.kids.get(cell) or []) if s != iid]},
                     {"discriminator": "delete", "instanceId": iid, "wrapperId": cell}):
            print(json.dumps(body, ensure_ascii=False)[:160], "->",
                  json.dumps(attempt(token, body), ensure_ascii=False)[:400])
    conn.close()


if __name__ == "__main__":
    main()
