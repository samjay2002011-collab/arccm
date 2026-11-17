# -*- coding: utf-8 -*-
"""أين جيلدا (Scrappy) في شجرة G22؟ وفيه خانات تركيب فاضية؟ قراءة فقط."""
import json
import re
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

GEN = {"1657228973": "I", "2041317243": "II", "1434069496": "III",
       "2080275953": "IV", "1781867314": "V"}


def label(names, aid):
    n = names.get(str(aid))
    if isinstance(n, dict):
        return n.get("display_name") or n.get("game_asset_name") or str(aid)
    return str(n or aid)


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    data = pc.fetch_inventory_for(account)
    names = pioneer_tree.asset_names()
    tree = pioneer_tree.Tree(data.get("items") or [])

    def path_of(node):
        out, cur, seen = [], node, set()
        while cur is not None and str(cur.get("instanceId")) not in seen:
            seen.add(str(cur.get("instanceId")))
            out.append(label(names, cur.get("gameAssetId")))
            pid = cur.get("parentItemId")
            cur = tree.by_id.get(str(pid)) if pid else None
        return " < ".join(x for x in out if x)[:160]

    print("--- عقد الجيلدا ---")
    for iid, node in tree.by_id.items():
        aid = str(node.get("gameAssetId"))
        if aid in GEN:
            print("  Scrappy %s | amount=%s | أب=%s | المسار: %s" %
                  (GEN[aid], node.get("amount"), node.get("parentItemId") or "—", path_of(node)))

    print("\n--- خانات اسمها Generator/Chamber/Room ---")
    for iid, node in tree.by_id.items():
        nm = label(names, node.get("gameAssetId"))
        if re.search(r"Generator|Chamber|Room|Slot", str(nm), re.I):
            kids = [k for k in tree.by_id.values() if str(k.get("parentItemId")) == str(iid)]
            print("  %-46s | أب=%s | أبناء=%s | %s" %
                  (str(nm)[:46], node.get("parentItemId") or "—", len(kids), path_of(node)[:110]))


if __name__ == "__main__":
    main()
