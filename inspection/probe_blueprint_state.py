"""READ-ONLY probe: can activated blueprints be inferred from data we already have?

For each account's latest snapshot:
  * blueprint scrolls physically present in inventory  -> found, activation unknown/not done
  * blueprint TARGET items physically present          -> implies the blueprint was activated at
    some point (craft-only items cannot otherwise appear)
Nothing is written; the gateway is never contacted.
"""
import glob
import gzip
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = json.load(open(os.path.join(ROOT, "data", "items_db.json"), encoding="utf-8"))
ITEMS = list(DB["items"].values())
BY_SLUG = {it["slug"]: it for it in ITEMS}

BLUEPRINTS = [it for it in ITEMS if it.get("is_blueprint")]
print("catalog blueprints:", len(BLUEPRINTS))

# blueprint scroll asset ids + their target asset ids
pairs = []
for bp in BLUEPRINTS:
    scroll_ids = {str(a) for a in (bp.get("asset_ids") or [])}
    tgt = BY_SLUG.get(bp.get("target_item_id") or "")
    target_ids = {str(a) for a in (tgt.get("asset_ids") or [])} if tgt else set()
    pairs.append((bp["slug"], bp["name"], scroll_ids, tgt["slug"] if tgt else None, target_ids,
                  bool((tgt or {}).get("found_in")), (tgt or {}).get("craft_bench")))

have_target = sum(1 for p in pairs if p[4])
print("blueprints with a resolved target item:", have_target, "/", len(pairs))
print("targets that also list world spawns (found_in non-empty):", sum(1 for p in pairs if p[5]))

snapdir = os.path.join(ROOT, "data", "snapshots")
for acc in ("G14", "G18", "G22", "RAIDER74888"):
    files = sorted(glob.glob(os.path.join(snapdir, acc + "_*.json.gz")))
    if not files:
        print(acc, "no snapshot")
        continue
    d = json.loads(gzip.open(files[-1], "rt", encoding="utf-8").read())
    owned = {str(a) for a in (d.get("owned_asset_ids") or [])}
    scrolls = [p for p in pairs if p[2] & owned]
    implied = [p for p in pairs if p[4] & owned]
    both = [p for p in pairs if (p[2] & owned) and (p[4] & owned)]
    print("==", acc, os.path.basename(files[-1]), "owned_asset_ids:", len(owned))
    print("   scroll still in inventory:", len(scrolls))
    print("   target item owned (implies activated):", len(implied))
    print("   both scroll+target:", len(both))
    print("   implied names:", sorted(n for _s, n, _i, _t, _a, _f, _b in implied)[:60])
    print("   scroll names:", sorted(n for _s, n, _i, _t, _a, _f, _b in scrolls)[:60])

# bench/station level availability
print("\nstation_level distribution in catalog:",
      {lv: sum(1 for it in ITEMS if str(it.get("station_level")) == lv)
       for lv in ("None", "1", "2", "3")})
bench_keys = {}
for it in ITEMS:
    for b in (it.get("craft_bench") or []):
        bench_keys[b] = bench_keys.get(b, 0) + 1
print("craft_bench keys:", bench_keys)
