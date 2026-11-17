# -*- coding: utf-8 -*-
"""يقارن خط الأساس بالحالة الرسمية الحالية ويقوّط كل تقسيم: مين فقد كمية،
ومين ظهر جديد، وكل ده في أنهي خانة وأنهي صندوق.

    python -m inspection.split_forensic G18

قراءة بس (GET /v1/pioneer/inventory) — مفيش أي كتابة.
"""
import json
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import config, pioneer_client as pc, pioneer_tree  # noqa: E402

from inspection.split_watch import path as base_path, snap  # noqa: E402


def when(updated):
    """updatedAt بتاع البوابة = ميليثواني × 1e6 — نحوّله لوقت محلي."""
    try:
        ms = int(str(updated)) / 1e6
    except (TypeError, ValueError):
        return "?"
    import datetime
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S.%f")[:-3]


def trail(tree, iid, depth=6):
    """مسار العقدة لأعلى: الصندوق/الخانة اللي ساكنة فيها."""
    parts, cur, guard = [], str(iid), 0
    while cur and guard < depth:
        guard += 1
        label = tree.label(cur)
        if label and label != str(cur):
            parts.append(label.strip())
        cur = tree.parent.get(cur) or ""
    return " ← ".join(parts) or "طليق"


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    if not os.path.isfile(base_path(account)):
        print("مفيش خط أساس — شغّل `python -m inspection.split_watch save %s` الأول." % account)
        return 1
    with open(base_path(account), encoding="utf-8") as fh:
        base = json.load(fh)
    now = snap(account)
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])

    added = {k: v for k, v in now.items() if k not in base}
    gone = {k: v for k, v in base.items() if k not in now}
    changed = {k: (base[k], now[k]) for k in set(base) & set(now) if base[k] != now[k]}

    losers = {k: (b, a) for k, (b, a) in changed.items()
              if a["asset"] and b["amount"] > a["amount"] and a["kids"] == 0}
    gainers = {k: (b, a) for k, (b, a) in changed.items()
               if a["asset"] and a["amount"] > b["amount"] and a["kids"] == 0}

    print("عقد جديدة %d | اختفت %d | اتغيّرت %d" % (len(added), len(gone), len(changed)))
    print("ناقصة كمية %d | زيادة كمية %d\n" % (len(losers), len(gainers)))

    # كل كومية جديدة بتتشابه بأقرب ناقص لنفس العنصر وأقرب وقت
    used = set()
    for iid, v in sorted(added.items(), key=lambda kv: str(kv[1]["updated"])):
        if v["kids"]:
            continue
        cand = []
        for lid, (b, a) in losers.items():
            if lid in used or a["asset"] != v["asset"]:
                continue
            try:
                dt = abs(int(a["updated"]) - int(v["updated"]))
            except (TypeError, ValueError):
                dt = 10 ** 18
            cand.append((dt, lid, b, a))
        cand.sort()
        tag = ""
        if cand and cand[0][0] < 5 * 10 ** 9:      # جوه 5 ثواني
            used.add(cand[0][1])
            b, a = cand[0][2], cand[0][3]
            tag = "  ⇐  من %s (%d→%d)" % (str(cand[0][1])[:8], b["amount"], a["amount"])
        print("+ %s %-20s كمية %d | وقت %s%s" % (
            str(iid)[:8], (v["name"] or v["asset"])[:20], v["amount"], when(v["updated"]), tag))
        print("    مكان: %s" % trail(tree, iid))
    for lid, (b, a) in sorted(losers.items()):
        if lid in used:
            continue
        print("- %s %-20s %d→%d | وقت %s" % (
            str(lid)[:8], (a["name"] or a["asset"])[:20], b["amount"], a["amount"],
            when(a["updated"])))
        print("    مكان: %s" % trail(tree, lid))

    for iid, (b, a) in sorted(gainers.items(), key=lambda kv: str(kv[1][1]["updated"])):
        print("≈ %s %-20s %d→%d | وقت %s" % (
            str(iid)[:8], (a["name"] or a["asset"])[:20],
            b["amount"], a["amount"], when(a["updated"])))
        print("    مكان: %s" % trail(tree, iid))
    for iid, v in sorted(gone.items(), key=lambda kv: -kv[1]["amount"]):
        print("× اختفى %s %-20s كمية %d" % (str(iid)[:8], (v["name"] or v["asset"])[:20], v["amount"]))

    tot_b = sum(v["amount"] for v in base.values())
    tot_a = sum(v["amount"] for v in now.values())
    print("\nمجموع الوحدات: %d → %d (%s)" % (
        tot_b, tot_a, "مافيش فقد" if tot_a == tot_b else "فرق %+d — وقّف وراجع" % (tot_a - tot_b)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
