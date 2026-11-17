"""قراءة بس: مقارنة شجرة G22 قبل القبض (inspection/_scrappy_before.json) بالشجرة
الحية على البوابة الرسمية، وإظهار أثر قبض Scrappy بالبايت.
مفيش أي كتابة على البوابة ولا في الداتابيز."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

BEFORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scrappy_before.json")


def main():
    raw = json.load(open(BEFORE, encoding="utf-8"))
    items = raw.get("items") if isinstance(raw, dict) else raw
    before = pioneer_tree.Tree(items or [])
    after = pioneer_tree.Tree((pc.fetch_inventory_for("G22") or {}).get("items") or [])
    created = [i for i in after.by_id if i not in before.by_id]
    deleted = [i for i in before.by_id if i not in after.by_id]
    grown, total = [], 0
    for iid, node in after.by_id.items():
        if iid not in before.by_id:
            continue
        delta = int(node.get("amount") or 0) - int(before.by_id[iid].get("amount") or 0)
        if delta <= 0:
            continue
        label = after.label(iid)
        grown.append((label, delta, int(before.by_id[iid].get("amount") or 0), int(node["amount"])))
        total += delta
    print("nodes before=%d after=%d" % (len(before.by_id), len(after.by_id)))
    print("created=%d deleted=%d grown=%d total_units=+%d" % (len(created), len(deleted), len(grown), total))
    for label, delta, b, a in sorted(grown, key=lambda r: -r[1]):
        print("  %-28s %6d -> %6d  (+%d)" % (label[:28], b, a, delta))


main()
