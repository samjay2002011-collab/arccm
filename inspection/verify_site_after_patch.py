"""نهاية-لنهاية بعد الباتش: الموقع نفسه — مزامنة لكل الحسابات + نقل حقيقي ورجوع + عدّ المجهول.

  python inspection/verify_site_after_patch.py
"""
import sys

import requests

BASE = "http://127.0.0.1:8000"
S = requests.Session()
S.post(BASE + "/login", data={"password": "2JR-KB8-XNT"}, timeout=30)
print("login:", S.status_code if hasattr(S, "status_code") else "ok")

r = S.post(BASE + "/api/refresh", timeout=600)
print("refresh:", r.status_code, str(r.text)[:200])

st = S.get(BASE + "/api/status", timeout=60).json()
print("status keys:", {k: st.get(k) for k in ("manifest", "manifest_status", "write_paused", "source") if k in st})

for acc in ("G14", "G18", "G21", "G22"):
    try:
        sec = S.get(BASE + "/api/sections", params={"account": acc}, timeout=120).json()
    except Exception as exc:  # noqa: BLE001
        print(acc, "sections ERR", exc)
        continue
    stash = sec.get("stash") or {}
    tiles = stash.get("items") or []
    unknown = sum(1 for t in tiles if str(t.get("name") or "").startswith("Item ") or t.get("name") in ("?", ""))
    print("%-4s stash %d/%d tiles=%d unknown=%d overflow=%d backpack=%d" % (
        acc, stash.get("used") or 0, stash.get("total") or 0, len(tiles), unknown,
        len((sec.get("overflow") or {}).get("items") or []),
        len((sec.get("backpack") or {}).get("items") or [])))

acc = "G14"
sec = S.get(BASE + "/api/sections", params={"account": acc}, timeout=120).json()
cells = [c for c in (sec.get("stash") or {}).get("cells") or []]
item = next((c["items"][0] for c in cells if c.get("items")), None)
empty = next((c for c in cells if not c.get("items")), None)
if not (item and empty):
    print("مفيش قطعة + خانة فاضية في الستاش — اتخطى اختبار النقل.")
    raise SystemExit(0)
src, dst = item.get("cell") or item.get("wrapper"), empty.get("id") or empty.get("wrapper")
iid = item.get("instance_id") or item.get("uid")
print("moving %s (%s) %s -> %s" % (str(iid)[:8], item.get("name"), src, dst))
mv = S.post(BASE + "/api/actions/move", json={"account": acc, "target_container": "stash",
                                              "instance_ids": [iid], "target_wrapper_id": dst},
            timeout=300).json()
print("MOVE executed=%s error=%s" % (mv.get("executed"), mv.get("error")))
bk = S.post(BASE + "/api/actions/move", json={"account": acc, "target_container": "stash",
                                              "instance_ids": [iid], "target_wrapper_id": src},
             timeout=300).json()
print("RESTORE executed=%s error=%s" % (bk.get("executed"), bk.get("error")))
