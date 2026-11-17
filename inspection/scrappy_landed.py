# -*- coding: utf-8 -*-
"""هل مكافأة الأكل وصلت بعد كده؟ مقارنة الشجرة الحية بالسنابشوت المحلي + كرايتات."""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree, store  # noqa: E402


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    live = pc.fetch_inventory_for(account)
    names = pioneer_tree.asset_names()

    def label(aid):
        n = names.get(str(aid))
        if isinstance(n, dict):
            return n.get("display_name") or n.get("game_asset_name") or str(aid)
        return str(n or aid)

    conn = store.db()
    snap = store.get_snapshot(conn, account) if hasattr(store, "get_snapshot") else None
    print("سنابشوت محلي موجود؟ %s" % (bool(snap)))

    def totals(data):
        acc = {}
        for node in (data or {}).get("items") or []:
            acc[str(node.get("gameAssetId"))] = acc.get(str(node.get("gameAssetId")), 0) + int(node.get("amount") or 0)
        return acc

    if isinstance(snap, dict):
        cur = totals(live)
        old = totals(snap)
        diffs = {k: cur[k] - old.get(k, 0) for k in cur if cur[k] != old.get(k, 0)}
        print("فرق حي مقابل محلي:")
        for k, v in sorted(diffs.items(), key=lambda kv: -abs(kv[1]))[:25]:
            print("  %-28s %s+%s" % (label(k), v, k))
    for path in ("/v1/pioneer/crates", "/v1/pioneer/bonuses"):
        try:
            print("\nGET %s -> %s" % (path, json.dumps(pc.request(path, token=token), ensure_ascii=False)[:600]))
        except Exception as err:
            print("\nGET %s -> %s" % (path, str(err)[:200]))
    blob = json.dumps(live, ensure_ascii=False)
    print("\nمفاتيح المخزون الحي: %s" % list(live.keys()))
    print("فيه transaction؟ %s | فيه startTime؟ %s" % ("transaction" in blob.lower(), "startTime" in blob))


if __name__ == "__main__":
    main()
