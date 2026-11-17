# تثبيت اسم البلاطة المجهولة -486136037 ثم إعادة المزامنة عشان السطور تاخد الاسم.
# قراءة من المنبع الرسمي بس: /api/assets/name بيكتب في الفهرس المحلي، و
# /api/actions/sync بيسحب شجرة الحساب من البوابة الرسمية — ولا طلب كتابة للعبة.
import json
import sys

import requests

BASE = "http://127.0.0.1:8000"
ASSET = "-486136037"
NAME = "Colorful Shoes (Green)"
HINT = ("game card proof 2026-11-02: TRINKET EPIC, value 7000, weight 0.5, stack 1; "
        "official blob gameAssetId -486136037 maxAmount=1 scrap=7000 (the other two shoe "
        "ids are already pinned: -1088151347 Legendary/10000, -1526934024 Rare/3000 stack 3)")
ACCOUNTS = ["G22", "RAIDER74888"]

s = requests.Session()
pw = json.load(open(r"C:\Users\Administrator\Desktop\rr\data\access.json", encoding="utf-8"))["password"]
r = s.post(f"{BASE}/login", data={"password": pw}, timeout=30)
print("login:", r.status_code)

r = s.post(f"{BASE}/api/assets/name", json={"asset_id": ASSET, "name": NAME, "hint": HINT}, timeout=30)
print("name:", r.status_code, r.text[:200])

for acc in ACCOUNTS:
    try:
        out = s.post(f"{BASE}/api/actions/sync", json={"account": acc}, timeout=180).json()
        print(f"sync {acc}: ok={out.get('ok')} items={out.get('item_count')} err={out.get('error')}")
    except Exception as exc:
        print(f"sync {acc}: FAILED {type(exc).__name__}: {exc}")

for acc in ACCOUNTS:
    data = s.get(f"{BASE}/api/sections?account={acc}", timeout=120).json()
    hits = []
    for key, bucket in (data.get("sections") or {}).items():
        for cell in bucket.get("slots") or []:
            item = cell.get("item") if isinstance(cell, dict) else None
            if not item or str(item.get("asset_id")) != ASSET:
                continue
            hits.append((key, item.get("display_name") or item.get("name"),
                         item.get("arctracker_rarity"), item.get("arctracker_value"),
                         item.get("arctracker_weight"), item.get("type_label"),
                         (item.get("arctracker_image") or item.get("image") or "")[-28:],
                         bool(item.get("description"))))
    print(f"\n{acc}: {len(hits)} بلاطة {ASSET}")
    for h in hits:
        print("   ", h)

    unknown = [ (k, c.get("item", {}).get("name"))
                for k, b in (data.get("sections") or {}).items()
                for c in b.get("slots") or []
                if isinstance(c, dict) and c.get("item")
                and str(c["item"].get("name") or "").startswith("Item -") ]
    print(f"    بلاطات 'Item -' الفاضلة: {len(unknown)}")

print("\nunknown endpoint:")
for acc in ACCOUNTS:
    u = s.get(f"{BASE}/api/assets/unknown?account={acc}", timeout=120).json()
    print(f"  {acc}: in_inventory={len(u.get('in_inventory') or [])} index_gaps={len(u.get('index_gaps') or [])}")
