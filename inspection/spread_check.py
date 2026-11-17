# -*- coding: utf-8 -*-
"""فحص خطة FRD (تفريد الأكوام على خانات متباعدة) — قراءة فقط، ولا كتابة للبوابة.

    python -m inspection.spread_check G18
    python -m inspection.spread_check G18 -1402742438
"""
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402


def assets_of(tree):
    """كل asset له أكثر من كوم حر (في الستاش أو طليق في الأوفر)."""
    out = {}
    for iid, row in tree.by_id.items():
        if row.get("slots"):
            continue
        aid = str(row.get("gameAssetId") or "")
        if not aid:
            continue
        out.setdefault(aid, []).append(iid)
    return {a: ids for a, ids in out.items() if len(ids) > 1}


def main():
    acc = sys.argv[1] if len(sys.argv) > 1 else "G18"
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    for aid, ids in sorted(assets_of(pc_tree(acc)).items(), key=lambda kv: -len(kv[1]))[:12]:
        if only and aid != only:
            continue
        name = pc_tree(acc).name_of(ids[0])
        try:
            plan = pioneer_tree.spread_plan(pc_tree(acc), aid)
        except pioneer_tree.TreeError as exc:
            print("%-26s %s  -> %s: %s" % (name[:26], aid, exc.error, exc.detail))
            continue
        print("%-26s %s | أكوام %d (طلايق %d) | فاضي %d | خانات %d"
              % (name[:26], aid, plan["total"], plan["loose"], plan["free"], plan["cells"]))
        print("   نقلات %d | تباعد %d | ثابتة %d" % (len(plan["moves"]), plan["gap"], plan["kept"]))
        print("   الخانات المستهدفة: %s" % plan["targets"])
        for m in plan["moves"][:6]:
            print("   -> خانة %s : %s" % (str(m["target_wrapper_id"])[:8], str(m["instance_ids"][0])[:8]))
        print("   %s" % plan["detail"])
    return 0


_CACHES = {}


def pc_tree(account):
    if account not in _CACHES:
        _CACHES[account] = pioneer_tree.Tree(
            (pc.fetch_inventory_for(account) or {}).get("items") or [])
    return _CACHES[account]


if __name__ == "__main__":
    sys.exit(main())
