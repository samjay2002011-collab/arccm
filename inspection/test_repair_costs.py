"""قياس معزول لتعلّم تكلفة الإصلاح: الكتابة في ملف مؤقت، وملف التعلم الحقيقي بيفضل زي ما هو."""
import gzip
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import actions, config, repair_costs, store  # noqa: E402

TMP_DIR = tempfile.mkdtemp()
repair_costs.FILE = os.path.join(TMP_DIR, "repair_costs.json")
LIVE = os.path.join(config.DATA_DIR, "repair_costs.json")
live_before = os.path.getmtime(LIVE) if os.path.exists(LIVE) else None

try:
    conn = store.db()
    account = "G22"
    payload, _ = store.read_snapshot(conn, account)
    cells = repair_costs._cells(payload)
    target_iid, (target_asset, _, target_dur) = next(
        (i, v) for i, v in cells.items() if v[2] is not None and v[2] < 0.9)
    spent_asset, spent_extra = next(
        (str((s.get("item") or {}).get("asset_id")), 2)
        for s in payload.get("stash") or []
        if (s.get("item") or {}).get("instanceId") != target_iid
        and int((s.get("item") or {}).get("amount") or 1) >= 3
        and str((s.get("item") or {}).get("asset_id")) != target_asset)

    prev = json.loads(json.dumps(payload))
    bumped = 0
    for slot in prev.get("stash") or []:
        item = slot.get("item") or {}
        if item.get("instanceId") == target_iid:
            item["durability"] = max(0.05, target_dur - 0.3)
        if bumped or str(item.get("asset_id")) != spent_asset:
            continue
        item["amount"] = item["quantity"] = int(item.get("amount") or item.get("quantity") or 1) + spent_extra
        item["instanceId"] = item["id"] = "test-prev-stack"
        bumped += 1
    print("material stacks bumped:", bumped)
    prev_gz = os.path.join(TMP_DIR, "prev.json.gz")
    with gzip.open(prev_gz, "wb") as fh:
        fh.write(json.dumps(prev).encode("utf-8"))

    print("repaired asset", target_asset, "durability", target_dur, "| spent", spent_asset, "+%d" % spent_extra)
    print("observe ->", repair_costs.observe(account, payload, prev_gz))
    print("cost_for ->", repair_costs.cost_for(target_asset))
    built = actions.plan(conn, account, "repair", [target_iid])
    print("plan materials ->", json.dumps(built.get("materials"), ensure_ascii=False))
    print("plan can_repair ->", built.get("can_repair"), "| blocked ->", built.get("blocked"),
          "| unknown_costs ->", built.get("unknown_costs"))
    print("plan items ->", [(i["name"], i["health"]) for i in built["items"]])
finally:
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    repair_costs.FILE = LIVE
    repair_costs._cache.update({"mtime": None, "data": {}})
    live_after = os.path.getmtime(LIVE) if os.path.exists(LIVE) else None
    print("live repair_costs.json untouched:", live_before == live_after)
