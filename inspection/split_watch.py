# -*- coding: utf-8 -*-
"""يسجّل شجرة حساب رسمية كخط أساس، ثم يقارن بعدها — عشان نشوف شكل التقسيم الحقيقي.

    python -m inspection.split_watch save G18
    python -m inspection.split_watch diff G18

القراءة بس (GET /v1/pioneer/inventory) — مفيش أي كتابة للبوابة.
"""
import json
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import config, pioneer_client as pc, pioneer_tree  # noqa: E402


def snap(account):
    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    out = {}
    for iid, row in tree.by_id.items():
        out[iid] = {"asset": str(row.get("gameAssetId") or ""),
                    "amount": int(row.get("amount") or 0),
                    "parent": tree.parent.get(iid) or "",
                    "updated": str(row.get("updatedAt") or ""),
                    "kids": len(tree.children(iid)),
                    "name": tree.name_of(iid)}
    return out


def path(account):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "split_baseline_%s.json" % account)


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "save").lower()
    account = sys.argv[2] if len(sys.argv) > 2 else "G18"
    now = snap(account)
    if mode == "save":
        with open(path(account), "w", encoding="utf-8") as fh:
            json.dump(now, fh, ensure_ascii=False)
        stacks = sum(1 for v in now.values() if v["amount"] > 1)
        print("خط أساس %s: %d عقدة | أكوام >1: %d | وحدات في الأكوام: %d"
              % (account, len(now), stacks, sum(v["amount"] for v in now.values())))
        return 0
    if not os.path.isfile(path(account)):
        print("مفيش خط أساس — شغّل `save %s` الأول." % account)
        return 1
    with open(path(account), encoding="utf-8") as fh:
        base = json.load(fh)
    added = {k: v for k, v in now.items() if k not in base}
    gone = {k: v for k, v in base.items() if k not in now}
    changed = {k: (base[k], now[k]) for k in set(base) & set(now) if base[k] != now[k]}
    print("خط أساس %s → الآن: عقد جديدة %d | اختفت %d | اتغيّرت %d"
          % (account, len(added), len(gone), len(changed)))

    def short(iid):
        return str(iid)[:8]

    for iid, v in sorted(added.items(), key=lambda kv: -kv[1]["amount"])[:20]:
        print("  + جديد   %-8s %-22s كمية %s | أب %s | updated %s"
              % (short(iid), (v["name"] or v["asset"])[:22], v["amount"],
                 short(v["parent"]) or "طليق", v["updated"]))
    for iid, v in sorted(gone.items(), key=lambda kv: -kv[1]["amount"])[:20]:
        print("  - اختفى   %-8s %-22s كمية %s | أب %s"
              % (short(iid), (v["name"] or v["asset"])[:22], v["amount"],
                 short(v["parent"]) or "طليق"))
    for iid, (b, a) in list(changed.items())[:30]:
        bits = []
        for key in ("amount", "parent", "updated", "kids", "asset"):
            if b[key] != a[key]:
                if key == "updated":
                    bits.append("updated %s→%s" % (str(b[key])[-6:], str(a[key])[-6:]))
                elif key == "parent":
                    bits.append("أب %s→%s" % (short(b[key]) or "طليق", short(a[key]) or "طليق"))
                else:
                    bits.append("%s %s→%s" % (key, b[key], a[key]))
        print("  ~ اتغير   %-8s %-22s %s" % (short(iid), (a["name"] or a["asset"])[:22],
                                             " ".join(bits)))
    tot_b = sum(v["amount"] for v in base.values())
    tot_a = sum(v["amount"] for v in now.values())
    print("مجموع الوحدات: %d → %d (%s)" % (tot_b, tot_a,
          "مافيش فقد" if tot_a == tot_b else "فرق %d — وقّف وراجع" % (tot_a - tot_b)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
