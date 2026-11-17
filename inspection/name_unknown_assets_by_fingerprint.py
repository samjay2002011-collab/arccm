"""تسمية الأصول المجهولة بالبصمة الرقمية من بيانات اللعبة + arctracker (معاينة بس).

الفكرة: شجرة البوابة بتدي `gameAssetId` من غير اسم، و`asset_index.csv` الرسمي
مالوش أصناف الباتش الجديد. لكن `data/pioneer_game_data.json` (رد اللعبة نفسه)
فيه لكل أصل: حجم الرصة `maxAmount`، ودرجة `qualityLevel`، وقيمة التفكيك بالـ Coins،
وحصيلة الـ recycle — ودي أرقام arctracker نفسها اللي في `data/items_db.json`.
فالمطابقة بتتم على الأرقام المقاسة مش على الاسم: بند مجهول بيطلع مرشح واحد
عند نفس (الرصة + القيمة + الندرة + حصيلة الريسايكل) = اسم، ومرشحين = غامض.

  python inspection/name_unknown_assets_by_fingerprint.py            # تقرير
  python inspection/name_unknown_assets_by_fingerprint.py --apply    # يكتب في asset_index_local.csv
"""
import csv
import datetime
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import pioneer_tree  # noqa: E402

APPLY = "--apply" in sys.argv
DUMP = json.load(open(ROOT / "data" / "pioneer_game_data.json", encoding="utf-8"))
ITEMS = json.load(open(ROOT / "data" / "items_db.json", encoding="utf-8"))["items"]
COINS = "-898439395"

# ---- بصمة كل أصل من بيانات اللعبة نفسها -------------------------------------
def yields(pkg):
    """`scrap.rewardPackage.rewardedItems` و`recycle.rewardedItems` — شكلين مختلفين في نفس الرد."""
    pkg = pkg or {}
    items = pkg.get("rewardedItems")
    if items is None:
        items = (pkg.get("rewardPackage") or {}).get("rewardedItems") or []
    out = []
    for r in items:
        out.append((str(r.get("gameAssetId")), int(r.get("amount") or 0)))
    return tuple(sorted(out))


game = {}
for row in DUMP.get("items-description", {}).get("itemDescriptions") or []:
    aid = str(row.get("gameAssetId") or "")
    if aid:
        game.setdefault(aid, row)

# ---- معايرة: grade -> rarity، والتأكد إن الأرقام بتتطابق فعلاً --------------
name_of = {}
with open(ROOT / "data" / "catalog" / "asset_index.csv", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        name_of[str(r.get("game_asset_id"))] = (r.get("display_name") or "").strip()

grade_to_rarity, agree = Counter(), Counter()
for it in ITEMS.values():
    for aid in it.get("asset_ids") or []:
        g = game.get(str(aid))
        if not g:
            continue
        grade_to_rarity[(int(g.get("qualityLevel") or 0), it.get("rarity"))] += 1
        agree["stack"] += int(g.get("maxAmount") or 0) == int(it.get("stack_size") or 0)
        agree["value"] += yields(g.get("scrap")) == ((COINS, int(it.get("value") or 0)),)
        agree["rows"] += 1
print("calibration on %d known ids: stack agrees %d, coin-value agrees %d"
      % (agree["rows"], agree["stack"], agree["value"]))
for (grade, rarity), n in sorted(grade_to_rarity.items(), key=lambda x: -x[1])[:8]:
    print("   grade %d -> %s (%d)" % (grade, rarity, n))

RARITY_BY_GRADE = {g: r for (g, r), n in grade_to_rarity.items() if n >= 3}

# ---- بصمة كل بند في arctracker (الأسماء اللي ملهاش id هي المرشح) ------------
# الندرة مش في البصمة: `qualityLevel` في بيانات اللعبة مش درجة الندرة (الصفرة
# بتدي grade 0 لكل الندرات)، فالمطابقة على الأرقام المقيسة بس.
def fingerprint(stack, coins, rec):
    return (int(stack or 0), int(coins or 0), tuple(sorted(rec or [])))


by_fp = {}
for it in ITEMS.values():
    if it.get("asset_ids"):
        continue
    rec = sorted([(str(a.get("name")), int(a.get("qty") or 0)) for a in it.get("recycles_into") or []])
    by_fp.setdefault(fingerprint(it.get("stack_size"), it.get("value"), rec), []).append(it)

conn = sqlite3.connect(ROOT / "data" / "rampart_local.db")
unknown = sorted({str(a) for (a,) in conn.execute(
    "SELECT DISTINCT asset_id FROM instances WHERE name LIKE 'Item %'")})
print("unknown ids in his accounts:", len(unknown))

hits, ambiguous, none = [], [], []
for aid in unknown:
    g = game.get(aid)
    if not g:
        none.append((aid, "no record in the game dump"))
        continue
    coins = dict(yields(g.get("scrap"))).get(COINS, 0)
    rec = sorted((name_of.get(str(k)) or str(k), v)
                 for k, v in yields(g.get("recycle")) if str(k) != COINS)
    key = fingerprint(g.get("maxAmount"), coins, rec)
    cands = by_fp.get(key) or []
    row = {"id": aid, "stack": key[0], "value": key[1], "recycle": rec,
           "tags": ",".join(g.get("tags") or []),
           "where": [r[0] for r in conn.execute(
               "SELECT DISTINCT account FROM instances WHERE asset_id=?", (aid,))]}
    if len(cands) == 1:
        hits.append((row, cands[0]))
    elif cands:
        ambiguous.append((row, [c["name"] for c in cands]))
    else:
        none.append((row, "no arctracker row with that fingerprint"))

print("\n=== UNIQUE MATCH (%d) ===" % len(hits))
for row, it in hits:
    print("  %-12s %-28s stack %-5s value %-6s recycle %-30s [%s] in %s"
          % (row["id"], it["name"], row["stack"], row["value"],
             " + ".join("%s x%s" % (n, q) for n, q in row["recycle"]) or "-",
             (it.get("type") or "?"), ",".join(row["where"])))
print("\n=== AMBIGUOUS (%d) ===" % len(ambiguous))
for row, names in ambiguous:
    print("  %-12s stack %s value %s recycle %s -> %s" % (row["id"], row["stack"], row["value"],
                                                          " + ".join("%s x%s" % (n, q) for n, q in row["recycle"]) or "-",
                                                          " / ".join(names)))
print("\n=== NO MATCH (%d) ===" % len(none))
for row, why in none:
    if isinstance(row, dict):
        print("  %-12s stack %-5s value %-6s recycle %-22s [%s] %s"
              % (row["id"], row["stack"], row["value"],
                 " + ".join("%s x%s" % (n, q) for n, q in row["recycle"]) or "-",
                 row["tags"][:40], why))
    else:
        print("  %s %s" % (row, why))

if APPLY:
    for row, it in hits:
        pioneer_tree.remember(row["id"], it["name"],
                              hint="identified %s by fingerprint (stack %s, value %s, recycle %s)"
                                   % (datetime.date.today().isoformat(), row["stack"], row["value"],
                                      " + ".join("%s x%s" % (n, q) for n, q in row["recycle"]) or "none"))
    print("wrote %d names into asset_index_local.csv" % len(hits))
else:
    print("\n(dry run — add --apply to write the unique matches)")
