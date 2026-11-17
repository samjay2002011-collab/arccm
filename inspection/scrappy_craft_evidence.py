# -*- coding: utf-8 -*-
"""من سجل التنفيذ: العروض اللي اتنفّذت فعلًا — هل فيها requiredItems؟ وهل ليها cost؟"""
import json
import sqlite3
import sys

sys.path.insert(0, ".")

from backend import config, store  # noqa: E402

GAME_DATA = "data/pioneer_game_data.json"
offers = {o["offerId"]: o for o in
          json.load(open(GAME_DATA, encoding="utf-8"))["offer-descriptions"]["offerDescriptions"]}

conn = store.db()
rows = conn.execute("SELECT ts, account, kind, request, status, response FROM actions "
                    "WHERE kind LIKE '%accept%' OR kind LIKE '%craft%' OR kind LIKE '%scrappy%' "
                    "ORDER BY ts DESC LIMIT 40").fetchall()
print("سجل executions: %d صف" % len(rows))
for r in rows:
    ts, acct, kind, req, status, resp = r[0], r[1], r[2], r[3], r[4], r[5]
    try:
        oid = (json.loads(req or "{}")).get("offerId")
    except Exception:
        oid = None
    o = offers.get(oid) or {}
    cost = (o.get("cost") or {}).get("itemAmounts") or []
    print("\n%s %s %s offer=%s status=%s" % (ts, acct, kind, oid, status))
    print("   نوع=%s | cost=%d | req=%s | body=%s" %
          (o.get("offerType"), len(cost), json.dumps(o.get("requiredItems")), (req or "")[:140]))
    print("   رد: %s" % (resp or "")[:260])
