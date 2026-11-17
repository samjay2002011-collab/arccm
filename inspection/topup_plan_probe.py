"""خطة تزويد الخانة الناقصة من المخزن: قياس على نسخة معزولة من القاعدة.

ما بيلمسش القاعدة الحية ولا البوابة — بيضيف رصة وهمية في الستاش وبيبصّ الخطة
وال معاينة: لازم الخانة تبقى executable من غير ما تحتاج تصنيع ولا شراء.
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIVE = ROOT / "data" / "rampart_local.db"
tmp = Path(tempfile.mkdtemp()) / "probe.db"
shutil.copy2(LIVE, tmp)
before = LIVE.stat().st_mtime_ns

from backend import config  # noqa: E402
config.DB_FILE = str(tmp)
from backend import loadouts, store  # noqa: E402

ACCOUNT, LOADOUT = "G22", 68
conn = store.db()

out = loadouts.plan(conn, ACCOUNT, LOADOUT)
gaps = list((out.get("short") or {}).values())
print("live db untouched:", LIVE.stat().st_mtime_ns == before)
print("gaps:", [(g["name"], g["have"], g["need"], g["from_stash"], g["still"]) for g in gaps])
print("executable (no fake yet):", out["executable"], "| already:", out["already"])

gap = gaps[0]
fake = "PROBE-STACK-1"
with conn:
    conn.execute("INSERT INTO instances (instance_id, account, container, qty, asset_id, name,"
                 " rarity, value, image, stack_size) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (fake, ACCOUNT, "stash", 999, gap["asset_id"], gap["name"], "Common", 0, "",
                  gap["cap"]))

out = loadouts.plan(conn, ACCOUNT, LOADOUT)
g = [x for x in out["short"].values() if x["instance_id"] == gap["instance_id"]][0]
print("after fake  -> takes:", g["takes"], "from_stash:", g["from_stash"], "still:", g["still"],
      "executable:", out["executable"])

pv = loadouts.preview(conn, ACCOUNT, LOADOUT)
s = pv["summary"]
print("summary:", {k: s[k] for k in ("ready", "missing", "short", "short_units", "short_covered",
                                     "topup_cells", "short_covered_cells", "short_needing",
                                     "craftable", "buyable", "unfillable")})
for c in pv["cards"]:
    if c["status"] == "short":
        print(" card:", c["name"], "have/need", c["short_have"], "/", c["short_need"],
              "| from_stash:", c["from_stash"], "| need_to_get:", c["need_to_get"],
              "| fill:", bool(c["fill"]), "| over_cap:", c["over_cap"], "cap", c["cap"])
print("live db untouched:", LIVE.stat().st_mtime_ns == before)
conn.close()
