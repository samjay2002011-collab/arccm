"""Rebuild the repair-cost dictionary from Fahmy's own recorded gateway mutations.

The Pioneer gateway never publishes a repair price, but every repair it executes
returns a changeset: the repaired instances plus the material stacks it drained
(post-state) and the stacks it consumed to zero (deleted). Walking every recorded
mutation in time order per account gives us the previous amount of each stack, so
a repair row turns into an exact `{asset_id: {material_asset_id: qty}}` measurement.

    python inspection/build_repair_costs.py            # report only
    python inspection/build_repair_costs.py --write    # write data/repair_costs.json
"""

import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import config, repair_costs  # noqa: E402

OUT = os.path.join(config.DATA_DIR, "repair_costs.json")
DURABILITY_MATERIALS = ("plastic_parts",)


def asset_of(entry):
    return str(entry.get("asset_id") or entry.get("gameAssetId") or "")


def changeset(response):
    try:
        parsed = json.loads(response or "{}")
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    items = (parsed.get("changeset") or {}).get("items")
    return items if isinstance(items, dict) else None


def load_rows(conn):
    rows = conn.execute(
        "SELECT ts, account, kind, request, response FROM actions ORDER BY ts"
    ).fetchall()
    out = []
    for ts, account, kind, request, response in rows:
        try:
            req = json.loads(request or "{}")
        except (TypeError, ValueError):
            req = {}
        out.append({"ts": float(ts), "account": account, "kind": kind or "",
                    "request": req, "changeset": changeset(response)})
    return out


def harvest(rows):
    """Replays every changeset to keep the last known stack size per instance."""
    known = {}   # (account, instance_id) -> (asset_id, amount)
    samples = []
    for row in rows:
        cs = row["changeset"]
        if not cs:
            continue
        account = row["account"]
        repaired = set(row["request"].get("ids") or [])
        is_repair = row["kind"] == "mutate:repair" and repaired
        spent = {}

        for entry in (cs.get("updated") or []):
            iid = entry.get("instanceId")
            if not iid:
                continue
            asset, amount = asset_of(entry), int(entry.get("amount") or 1)
            prev = known.get((account, iid))
            if is_repair and prev and prev[0] == asset and asset not in repaired:
                drop = prev[1] - amount
                if 0 < drop <= 200:
                    spent[asset] = spent.get(asset, 0) + drop
            known[(account, iid)] = (asset, amount)

        for iid in (cs.get("deleted") or []):
            prev = known.pop((account, iid), None)
            if is_repair and prev and prev[0] not in repaired and 0 < prev[1] <= 200:
                spent[prev[0]] = spent.get(prev[0], 0) + prev[1]

        if not is_repair:
            continue
        for entry in (cs.get("updated") or []):
            iid = entry.get("instanceId")
            if iid in repaired:
                samples.append({
                    "account": account, "ts": row["ts"], "asset_id": asset_of(entry),
                    "durability": entry.get("durability"), "max_durability": entry.get("maxDurability"),
                    "materials": dict(spent),
                })
    return samples


def main():
    write = "--write" in sys.argv
    conn = sqlite3.connect(os.path.join(config.DATA_DIR, "rampart_local.db"))
    samples = harvest(load_rows(conn))
    conn.close()

    print("repair samples read: %d" % len(samples))
    per_asset = {}
    for s in samples:
        if s["materials"]:
            per_asset.setdefault(s["asset_id"], []).append(s)

    costs = {}
    if write and os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as fh:
            costs = (json.load(fh) or {}).get("costs") or {}

    for asset, lst in sorted(per_asset.items()):
        # كل عينة بتدخل على القاموس بنفس منطق المتعلّم: أعلى كمية مقاسة لكل خامة.
        for s in lst:
            repair_costs._merge(costs, asset, s["materials"], 1.0, "gateway")
        entry = costs[asset]
        print("  asset %-13s n=%d  cost=%s" % (asset, len(lst),
                                               json.dumps(entry["materials"], sort_keys=True)))

    print("costs table: %d assets" % len(costs))
    if not write:
        print("\n(dry run — pass --write to save)")
        return
    payload = {"costs": costs, "updated_at": int(time.time())}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    os.replace(tmp, OUT)
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
