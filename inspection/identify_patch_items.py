# -*- coding: utf-8 -*-
"""يربط اسم كل قطعة باتش جديد برقمها من الشجرة الحيّة ويسجّله في الفهرس المحلي.

المصدر: المستخدم حرّك التلات قطع لخانات مختلفة في اللعبة، فكل واحدة بقت وحيدة
في حاويتها — وده كفاية عشان نعرف رقمها من غير أي تخمين:
    QUICK USE   → Skulker Targeter
    SAFE POCKET → Laser Level
    BACKPACK    → Fancy Plate

الكتابة كلها محلية (CSV + لا شيء للببوابة): البوابة ما بتديش أسماء أصلاً.
"""
import sys, io, json, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from backend import pioneer_client as pc, pioneer_tree as pt, pioneer_sync

EXPECT = {"quick_use": ("Skulker Targeter", "quick use slot"),
          "safe_pocket": ("Laser Level", "safe pocket slot"),
          "backpack": ("Fancy Plate", "item slot")}

acct = sys.argv[1] if len(sys.argv) > 1 else "G18"
data = pc.fetch_inventory_for(acct)
tree = pt.Tree((data or {}).get("items") or [])
lay = pt.layout(tree)

found = {}
for key, (want, slot_mark) in EXPECT.items():
    ids = []
    slots = (lay.get("loadout") or {}).get("slots", {}).get(key) if key != "backpack" \
        else (lay.get("backpack") or {}).get("slots")
    for s in slots or []:
        item = s.get("item")
        if item:
            parent = tree.parent.get(item) or ""
            ids.append((s.get("wrapper"), item, str((tree.by_id.get(item) or {}).get("gameAssetId")),
                        (tree.label(parent) or "").strip().lower()))
    print("%-12s فيها %d قطعة: %s" % (key, len(ids), [(w[:8], a, lab[:18]) for w, i, a, lab in ids]))
    if len(ids) != 1:
        print("   ✗ مش قطعة واحدة بس — مانمسش حاجة دلوقتي.")
        raise SystemExit(1)
    wrapper, item, asset_id, lab = ids[0]
    if slot_mark not in lab:
        print("   ✗ أبوها مش «%s» («%s») — الربط مش آمن." % (slot_mark, lab))
        raise SystemExit(1)
    found[want] = asset_id

print()
print("الربط:", json.dumps(found, ensure_ascii=False, indent=1))

conn = sqlite3.connect("data/rampart_local.db")
payload = pioneer_sync.build_payload(conn, acct, data=data)
for section in ("backpack", "quick_use", "safe_pocket"):
    for s in payload.get(section) or []:
        it = s.get("item") or {}
        if it:
            print("   payload %-12s idx %s → %r asset %s" %
                  (section, s.get("slot_index"), it.get("name"), it.get("asset_id")))

if "--apply" in sys.argv:
    for name, asset_id in found.items():
        rec = pt.remember(asset_id, name, "patch item, identified 2026-10-30 by container")
        print("   ✓ مسجّل:", asset_id, "=", name, "|", rec.get("path") or rec.get("file") or "")
    payload = pioneer_sync.build_payload(conn, acct, data=data)
    print("بعد التسجيل:")
    for section in ("backpack", "quick_use", "safe_pocket"):
        for s in payload.get(section) or []:
            it = s.get("item") or {}
            if it:
                print("   %-12s idx %s → %r rarity %r type %r value %r image %r" %
                      (section, s.get("slot_index"), it.get("name"), it.get("rarity"),
                       it.get("type"), it.get("value"), it.get("image_filename")))
else:
    print("   (dry run — مرّر --apply عشان يسجّل في data/catalog/asset_index_local.csv)")
conn.close()
