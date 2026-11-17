"""تحليل بيانات بس فقط: مين العناصر اللي ليها مخطوطة أصلاً، وإيه اللي تنزل مفتوحة من البداية.

الهدف: نبني قائمة DEFAULT_UNLOCKED_RECIPES صلبة من دليل مش من تخمين:
  1) وصفات arctracker مالهاش any blueprint requirement (blueprint_locked = False).
  2) مطحونة ضد عالم عقد "Unlock Craft X" في الفهرس المحلي: لو للعنصر عقدة قفل
     فهو مقفول يقيناً حتى لو arctracker ما قالش كده.
  3) متقاطعة مع شجرة G18 (حساب فيه 0 عقد تفعيل): أي وصفة ظهرت هناك = أساسية فعلاً.
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, items_db, knowledge, pioneer_tree  # noqa: E402


def main():
    rows = items_db.craftable_rows()
    uni = knowledge.unlock_universe()
    gated = set()
    for ref in uni.values():
        for s in ref["gates"]:
            gated.add(s)
        if ref["slug"]:
            gated.add(ref["slug"])
    node_names = {items_db.norm(k) for k in uni}
    print(f"craftable_rows={len(rows)}  unlock_nodes={len(uni)}  gated_slugs={len(gated)}")

    buckets = {"free_no_node": [], "locked_no_node": [], "free_has_node": [],
               "locked_has_node": [], "target_not_in_rows": []}
    bp_targets = {r["target"] for r in items_db.blueprint_rows() if r.get("target")}
    for row in rows:
        slug = str(row.get("slug") or "")
        name = items_db.norm(row.get("name") or "")
        locked = bool(row.get("blueprint_locked"))
        has_node = slug in gated or name in node_names
        if not locked and not has_node:
            buckets["free_no_node"].append((slug, row.get("name"), row.get("stations")))
        elif locked and not has_node:
            buckets["locked_no_node"].append((slug, row.get("name"), row.get("blueprint")))
        elif not locked and has_node:
            buckets["free_has_node"].append((slug, row.get("name")))
        else:
            buckets["locked_has_node"].append((slug, row.get("name")))
    for key, items in buckets.items():
        print(f"\n== {key} ({len(items)}) ==")
        for item in sorted(items, key=lambda i: str(i[1]).lower()):
            print("  ", item)

    # 91 مخطوطة: كام منها ليها عقدة قفل
    no_node = []
    for r in items_db.blueprint_rows():
        tgt = r.get("target")
        if not tgt:
            continue
        trow = items_db.by_slug(tgt) or {}
        key = items_db.norm(trow.get("name") or r.get("target_name") or "")
        if tgt not in gated and key not in node_names:
            no_node.append((tgt, trow.get("name") or r.get("target_name")))
    print(f"\n== blueprint targets بلا عقدة قفل ({len(no_node)}) ==")
    for item in sorted(no_node, key=lambda i: str(i[1]).lower()):
        print("  ", item)

    # أي حسابات مقاسة وعندها عقد، وكام
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    accounts = [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]
    print("\naccounts:", accounts)
    per = {}
    for acc in accounts:
        if not knowledge.unlock_measured(conn, acc):
            per[acc] = None
            continue
        per[acc] = len(knowledge.unlocked(conn, acc))
    print("unlocked node counts:", per)

    # G18 / أي حساب بـ 0 عقد: شجرة وصنّف الوصفات بالنِسبة لخاماته
    zero = [a for a, n in per.items() if n == 0]
    print("accounts with zero nodes:", zero)
    for acc in zero:
        owned = {str(r["asset_id"]): int(r["q"] or 0) for r in conn.execute(
            "SELECT asset_id, SUM(qty) q FROM instances WHERE account=? AND asset_id IS NOT NULL"
            " AND asset_id <> '' GROUP BY asset_id", (acc,))}
        names = {items_db.norm(r["name"]): int(r["q"] or 0) for r in conn.execute(
            "SELECT name, SUM(qty) q FROM instances WHERE account=? GROUP BY name", (acc,))}
        states = knowledge.blueprint_state(conn, acc, owned, names)
        from collections import Counter
        print(f"  {acc}: owned_assets={len(owned)} state_counts={Counter(states.values())}")
    conn.close()


if __name__ == "__main__":
    main()
