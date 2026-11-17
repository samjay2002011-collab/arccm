"""Report every damaged item in Fahmy's own snapshots and the cost the repair modal will show.

Read-only: touches snapshots and data/repair_costs.json, never the gateway.

    python inspection/check_repair_live.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import gearops, repair_costs, store  # noqa: E402


def main():
    conn = store.db()
    total = 0
    for acc in store.list_accounts(conn, True):
        payload, _mtime = store.read_snapshot(conn, acc["name"])
        if not payload:
            print("%-14s no snapshot" % acc["name"])
            continue
        items = []
        for cell in gearops.container_rows(payload):
            item = cell.get("item") if isinstance(cell, dict) else None
            if isinstance(item, dict) and not item.get("is_empty"):
                items.append(item)
        damaged = [i for i in items if gearops.health_of(i)["damaged"]]
        total += len(damaged)
        print("%-14s items=%-5d damaged=%d" % (acc["name"], len(items), len(damaged)))
        for row in damaged[:10]:
            health = gearops.health_of(row)
            cost = repair_costs.cost_for(row.get("asset_id"), row)
            print("    %-26s %-9s %-8s %-8s %s/%s est=%-5s %s"
                  % (row.get("name"), row.get("rarity"),
                     repair_costs._klass(row.get("asset_id"), row) or "other",
                     row.get("type"), health["current"], health["max"],
                     cost["estimated"], cost["materials"]))
    print("TOTAL damaged:", total)
    learned = sorted(((repair_costs._load().get("costs") or {}).keys()))
    print("measured assets in dictionary:", len(learned), learned[:10])


if __name__ == "__main__":
    main()
