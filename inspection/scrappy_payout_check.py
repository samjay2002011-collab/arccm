# -*- coding: utf-8 -*-
"""عدد الموارد في حساب + عقد Rounds Played بالتفصيل (قراءة فقط)."""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

ROUNDS = "-1869396984"


def label(names, aid):
    n = names.get(str(aid))
    if isinstance(n, dict):
        return n.get("display_name") or n.get("game_asset_name") or str(aid)
    return str(n or aid)


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    ids = sys.argv[2:] or ["-1565478080", "599997416", "-1437131902", "-1580114534",
                           "828947161", "-2048050889", ROUNDS]
    data = pc.fetch_inventory_for(account)
    names = pioneer_tree.asset_names()
    acc = {}
    nodes = []
    for n in data.get("items") or []:
        aid = str(n.get("gameAssetId"))
        acc[aid] = acc.get(aid, 0) + int(n.get("amount") or 0)
        if aid == ROUNDS:
            nodes.append(n)
    for aid in ids:
        print("%-24s = %s" % (label(names, aid), acc.get(aid, 0)))
    print("\nعقد Rounds Played (%d):" % len(nodes))
    for n in nodes:
        print("  " + json.dumps(n, ensure_ascii=False)[:300])
    # مقارنة بشكل عقدة ليمون (اللي اتصرف بنجاح)
    lem = [n for n in (data.get("items") or []) if str(n.get("gameAssetId")) == "599997416"]
    print("\nمثال عقد ليمون:\n  " + json.dumps(lem[0], ensure_ascii=False)[:300] if lem else "")


if __name__ == "__main__":
    main()
