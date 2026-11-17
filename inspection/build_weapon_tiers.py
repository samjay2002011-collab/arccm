# -*- coding: utf-8 -*-
"""بناء جدول درجات الأسلحة من فهرس الأصول.

الدرجة مش حقل في الشجرة: السلاح Quality0 = فل 1، Quality1 = فل 2 ... فبنشتق
الربط (asset id ↔ فل) من أسماء الأصول الداخلية DA_Item_<family>_Quality<N>.
بيطلع data/weapon_tiers.json.
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "catalog" / "asset_index.csv"
OUT = ROOT / "data" / "weapon_tiers.json"
PAT = re.compile(r"^DA_Item_(.+)_Quality([0-3])$")


def main():
    families, assets = {}, {}
    with open(SRC, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("game_asset_name") or "").strip()
            m = PAT.match(name)
            if not m:
                continue
            family, tier = m.group(1), int(m.group(2))
            asset_id = str(row.get("game_asset_id") or "").strip()
            if not asset_id:
                continue
            families.setdefault(family, {})[tier] = {
                "asset": asset_id,
                "name": (row.get("display_name") or "").strip() or name,
            }
            assets[asset_id] = {"family": family, "level": tier + 1, "name": (row.get("display_name") or "").strip()}

    # بس العائلات اللي عندها ٤ درجات
    full = {}
    for family, tiers in families.items():
        if len(tiers) != 4:
            continue
        full[family] = {str(t + 1): tiers[t] for t in range(4)}
    keep = set()
    for tiers in full.values():
        for row in tiers.values():
            keep.add(row["asset"])
    assets = {a: v for a, v in assets.items() if a in keep}

    payload = {"families": full, "assets": assets, "source": SRC.name}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[+] %d عائلات / %d أصل → %s" % (len(full), len(assets), OUT))
    for fam, tiers in list(full.items())[:3]:
        print("   ", fam, {k: v["name"] for k, v in tiers.items()})


if __name__ == "__main__":
    sys.exit(main())
