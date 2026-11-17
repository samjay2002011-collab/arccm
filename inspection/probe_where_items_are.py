# قراءة فقط: الشنطة في الشجرة الحية مقابل الي موقعك عارضها (حساب واحد)
import sys, io, json, sqlite3, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from backend import pioneer_client as pc, pioneer_tree as pt

acct = sys.argv[1] if len(sys.argv) > 1 else "G18"
data = pc.fetch_inventory_for(acct)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
bag = lay["backpack"]
print("=== الحية ===")
print("mode", lay["loadout"]["mode"], "| loadout", repr(lay["loadout"]["name"]),
      "| حاوية", bag["container"][:8], repr(tree.label(bag["container"])),
      "| خانات", len(bag["slots"]))
for s in bag["slots"]:
    it = s["item"]
    row = tree.by_id.get(str(it)) or {}
    print("   ", s["wrapper"][:8], "| item:", (it or "-")[:8],
          "| asset:", row.get("gameAssetId"), "| label:", repr(tree.label(it)),
          "| amount:", row.get("amount"))

conn = sqlite3.connect("data/rampart_local.db")
conn.row_factory = sqlite3.Row
print("=== آخر سنابشوت محفوظ ===")
r = conn.execute("SELECT fetched_at, path, item_count, ok FROM snapshots WHERE account=? "
                 "ORDER BY fetched_at DESC LIMIT 1", (acct,)).fetchone()
if r:
    print("   ", r["fetched_at"], "ok", r["ok"], "items", r["item_count"], r["path"])
    try:
        p = json.load(open(r["path"], encoding="utf-8"))
    except Exception as err:
        print("   قراءة السنابشوت:", err)
        p = {}
    print("   locations:", json.dumps(p.get("locations") or {}, ensure_ascii=False)[:220])
    bp = p.get("backpack") or []
    print("   backpack في السنابشوت:", len(bp))
    for x in bp[:12]:
        print("      ", x.get("slot_index"), x.get("name"), x.get("asset_id"))
print("=== الي بترجعه الـ API ===")
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/sections?account=%s" % acct))
print("   locations:", json.dumps(d.get("locations"), ensure_ascii=False)[:220])
slots = (d.get("loadout") or {}).get("slots", {}).get("backpack") or []
print("   api backpack:", len(slots), "مليان", sum(1 for s in slots if s.get("item")))
for s in slots:
    if s.get("item"):
        print("      idx", s.get("slot_index"), (s["item"] or {}).get("name"))

