"""تحقق لايف على G14: تقسيم حقيقي بالـ API ثم دمج تاني — مع مقارنة الشجرة قبل وبعد.

الإسكربت بيقفل نفسه لو ماوصلش لمرحلة الإرجاع: بيحفظ baseline.json قدام كل خطوة
فأي اختلاف متبقي يبان بالأرقام مش بالحدس.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc, pioneer_tree as pt  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G18"
SITE = "http://127.0.0.1:8000"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_split_run")
os.makedirs(OUT_DIR, exist_ok=True)

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
opener.open(SITE + "/login", urllib.parse.urlencode({"password": "2JR-KB8-XNT"}).encode(), timeout=15)


def api(path, payload):
    req = urllib.request.Request(SITE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        r = opener.open(req, timeout=180)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:400].decode("utf-8", "replace")}


def snap(tag):
    data = pc.fetch_inventory_for(ACCOUNT) or {}
    items = data.get("items") or []
    tree = pt.Tree(items)
    with open(os.path.join(OUT_DIR, "tree_%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump(items, fh)
    return tree


before = snap("before")
lay = pt.layout(before)
stash_cells = set(str(c) for c in lay["stash"]["slots"])
bp = [str((s.get("wrapper") if isinstance(s, dict) else s)) for s in lay["backpack"]["slots"]]
free_bp = [c for c in bp if c in before.by_id and not before.first_child(c)]

src_id, cell = "", free_bp[0] if free_bp else ""
PREFER = ("Fabric", "Plastic Parts", "Rubber Parts", "Metal Parts", "Medium Ammo", "Light Ammo")
rows = []
for iid, n in before.by_id.items():
    if n.get("slots"):
        continue
    q = int(n.get("amount") or 0)
    if not (6 <= q <= 40):
        continue
    if str(before.parent.get(iid) or "") not in stash_cells:
        continue
    rows.append((before.name_of(iid), iid, q, str(n.get("gameAssetId"))))
named = [r for r in rows if r[0] in PREFER]
named.sort(key=lambda r: PREFER.index(r[0]))
pick = (named or rows or [None])[0]
if pick:
    src_id = pick[1]
    print("picked %s x%d (%s) in stash; merge-back target is the same stack" % (pick[0], pick[2], pick[1][:8]))
else:
    sys.exit("no stash stack in 6..40 to split on %s" % ACCOUNT)
print("baseline instances:", len(before.by_id))
print("source stack:", src_id, before.name_of(src_id), before.by_id[src_id].get("amount"),
      "| target cell:", cell)
TAKE = 4
baseline = {iid: int(n.get("amount") or 0) for iid, n in before.by_id.items() if not n.get("slots")}
base_total = sum(v for k, v in baseline.items() if str(before.by_id[k].get("gameAssetId")) ==
                 str(before.by_id[src_id].get("gameAssetId")))

status, out = api("/api/actions/split", {"account": ACCOUNT, "instance_id": src_id,
                                         "target_wrapper_id": cell, "amount": TAKE,
                                         "confirmed": True})
print("\n== SPLIT http %s executed=%s error=%s" % (status, out.get("executed"), out.get("error")))
print("   detail:", (out.get("detail") or "")[:300])
print("   sent:", json.dumps((out.get("preview") or {}).get("body") or (out.get("preview") or {}))[:260])
print("   after:", out.get("after"), "| created:", (out.get("created") or "")[:8],
      "| cell:", (out.get("cell") or "")[:8], "| lost:", out.get("lost"))
piece = out.get("created") or ""

if not out.get("executed"):
    print("\nSPLIT لم ينفّذ — مافيش حاجة ترجّع، الشجرة زي ما هي.")
    sys.exit(1)

status, out2 = api("/api/actions/combine", {"account": ACCOUNT, "instance_id": piece,
                                            "target_instance_id": src_id, "confirmed": True})
print("\n== COMBINE http %s executed=%s error=%s" % (status, out2.get("executed"), out2.get("error")))
print("   detail:", (out2.get("detail") or "")[:300])
print("   sent:", json.dumps((out2.get("preview") or {}).get("body") or (out2.get("preview") or {}))[:260])
print("   after:", out2.get("after"), "| lost:", out2.get("lost"))

after = snap("after")
after_totals = {}
for iid, n in after.by_id.items():
    if n.get("slots"):
        continue
    if str(n.get("gameAssetId")) == str(before.by_id[src_id].get("gameAssetId")):
        after_totals[iid] = int(n.get("amount") or 0)
print("\n== RESTORE CHECK")
print("   instances before/after:", len(before.by_id), "/", len(after.by_id))
print("   asset total before/after:", base_total, "/", sum(after_totals.values()))
print("   source stack now:", after.by_id.get(src_id, {}).get("amount"), "in",
      after.label(str(after.parent.get(src_id) or "")) or after.parent.get(src_id, ""))
print("   piece still exists:", piece in after.by_id)
if out2.get("executed") and piece not in after.by_id and \
        int(after.by_id.get(src_id, {}).get("amount") or 0) == baseline[src_id]:
    print("   RESULT: RESTORED EXACTLY")
else:
    diff = {k: (baseline[k], after_totals.get(k)) for k in set(baseline) | set(after_totals)
            if str(before.by_id.get(k, {}).get("gameAssetId")) ==
            str(before.by_id[src_id].get("gameAssetId"))
            and baseline.get(k) != after_totals.get(k)}
    print("   RESULT: DIFF =", {k[:8]: v for k, v in diff.items()})
