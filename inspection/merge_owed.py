# -*- coding: utf-8 -*-
"""قراءة فقط: الأنواع اللي فعلاً ناقصة دمج (عدد الأكوام أكبر من المثالي بالحد بتاعها).

بتقرأ الـ snapshot المحلي بعد /api/refresh، فبتدي نفس اللي البوابة الرسمية شايفاه
من غير أي كتابة. تُستعمل قبل/بعد تجربة الدمج على موقع Rampart للمقارنة.

    python -m inspection.merge_owed RAIDER74888
    python -m inspection.merge_owed RAIDER33368 --filter bandage
"""
import re
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import items_db  # noqa: E402

CONTAINERS = ("stash", "overflow")


def owed(account, needle=""):
    conn = sqlite3.connect(r"C:\Users\Administrator\Desktop\rr\data\rampart_local.db")
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "select asset_id,name,qty,container,stack_size from instances "
        "where account=? and qty>0", (account,))]
    conn.close()
    pat = re.compile(re.escape(needle), re.I) if needle else None
    groups = defaultdict(list)
    for r in rows:
        if r["container"] not in CONTAINERS:
            continue
        if pat and not pat.search(str(r["name"] or "")):
            continue
        groups[str(r["asset_id"])].append(r)
    out = []
    for aid, rs in groups.items():
        if len(rs) < 2:
            continue
        total = sum(int(r["qty"]) for r in rs)
        cap = max([int(r["stack_size"] or 0) for r in rs] + [0])
        if not cap:
            cap = int((items_db.dossier(asset_id=aid) or {}).get("stack_size") or 0)
        if cap < 2:
            continue
        ideal = -(-total // cap)
        if len(rs) > ideal:
            out.append({"asset_id": aid, "name": rs[0]["name"], "cap": cap,
                        "stacks": len(rs), "ideal": ideal, "waste": len(rs) - ideal,
                        "total": total,
                        "amounts": sorted((int(r["qty"]) for r in rs), reverse=True),
                        "containers": sorted({r["container"] for r in rs})})
    out.sort(key=lambda o: -o["waste"])
    return out


def main():
    acct = sys.argv[1] if len(sys.argv) > 1 else "RAIDER74888"
    needle = ""
    if "--filter" in sys.argv:
        needle = sys.argv[sys.argv.index("--filter") + 1]
    lst = owed(acct, needle)
    print("%s — أنواع ناقصة دمج: %d" % (acct, len(lst)))
    for o in lst[:25]:
        print("  -%3d كوم | حد %4d | %3d كوم = %5d وحدة | %-30s %s"
              % (o["waste"], o["cap"], o["stacks"], o["total"], o["name"],
                 ",".join(o["containers"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
