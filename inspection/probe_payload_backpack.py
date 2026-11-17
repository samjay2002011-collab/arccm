# قراءة فقط: build_payload على بيانات حية — هو بيفقد قطع الشنطة ولا لأ؟
import sys, io, gzip, json, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from backend import pioneer_client as pc, pioneer_tree as pt, pioneer_sync

acct = sys.argv[1] if len(sys.argv) > 1 else "G18"
data = pc.fetch_inventory_for(acct)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)
live = [(s["wrapper"], s["item"]) for s in lay["backpack"]["slots"]]
print("حي: خانات", len(live), "| فيها قطع", sum(1 for _, i in live if i))
for w, i in live:
    if i:
        row = tree.by_id.get(i) or {}
        print("   cell", w[:8], "item", i[:8], "asset", row.get("gameAssetId"),
              "amount", row.get("amount"), "label", repr(tree.label(i))[:44])

conn = sqlite3.connect("data/rampart_local.db")
payload = pioneer_sync.build_payload(conn, acct, data=data)
bp = payload.get("backpack") or []
print("payload.backpack:", len(bp), "| مليان", sum(1 for s in bp if not s.get("is_empty")))
for s in bp:
    it = s.get("item") or {}
    print("   idx", s.get("slot_index"), "|", repr(it.get("name")), it.get("asset_id"))

path = conn.execute("SELECT path FROM snapshots WHERE account=? ORDER BY fetched_at DESC LIMIT 1",
                    (acct,)).fetchone()[0]
with gzip.open(path, "rt", encoding="utf-8") as fh:
    stored = json.load(fh)
sbp = stored.get("backpack") or []
print("سنابشوت محفوظ:", path.split("\\")[-1])
print("   backpack:", len(sbp), "| مليان", sum(1 for s in sbp if not s.get("is_empty")))

stash = payload.get("stash") or []
filled = [s for s in stash if not s.get("is_empty")]
nameless = [s for s in filled if str((s.get("item") or {}).get("name") or "").startswith("Item ")]
print("   الستاش في الـ payload الجديد:", len(filled), "خانة مليانة — منها بلا اسم:", len(nameless))
for s in nameless[:10]:
    it = s["item"]
    print("      ", it.get("asset_id"), "| qty", it.get("amount"))
