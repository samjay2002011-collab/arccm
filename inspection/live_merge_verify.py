"""تحقق لايف للدمج على batch-operation: moveAmount لخانة فيها رصة من نفس النوع.

الخطوة نفسها هي اللي زر COMBINE بيعملها. لو البوابة رفضت: مافيش أي تغيير أصلاً.
لو قبلت: الإسكربت يرجّع نفس العدد فوراً بنفس الأمر في الاتجاه العكسي، ويفايق
الشجرة كاملة قبل/بعد (عدد النسخ + كل كمية).
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
TAKE = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SITE = "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_merge_run")
os.makedirs(OUT, exist_ok=True)

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
            return e.code, {"raw": raw[:300].decode("utf-8", "replace")}


def snapshot(tag):
    data = pc.fetch_inventory_for(ACCOUNT) or {}
    items = data.get("items") or []
    with open(os.path.join(OUT, "tree_%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump(items, fh)
    tree = pt.Tree(items)
    stacks = {iid: int(n.get("amount") or 0) for iid, n in tree.by_id.items() if not n.get("slots")}
    return tree, stacks


before_tree, before_stacks = snapshot("before")
lay = pt.layout(before_tree)
stash_cells = set(str(c) for c in lay["stash"]["slots"])

db = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "items_db.json"), encoding="utf-8"))
by_asset = db.get("by_asset") or {}
items_db = db.get("items") or {}

groups = {}
for iid, node in before_tree.by_id.items():
    if node.get("slots") or int(node.get("amount") or 0) < 1:
        continue
    if str(before_tree.parent.get(iid) or "") not in stash_cells:
        continue
    groups.setdefault(str(node.get("gameAssetId")), []).append((iid, int(node.get("amount"))))
pairs = [(aid, rows) for aid, rows in groups.items() if len(rows) >= 2]


def cap_of(aid):
    row = items_db.get(by_asset.get(aid) or "") or {}
    return int(row.get("stack_size") or 0)


best = None
for aid, rows in pairs:
    rows.sort(key=lambda r: -r[1])
    cap = cap_of(aid)
    if not cap:
        continue
    src, tgt = rows[0], rows[1]
    if tgt[1] + TAKE <= cap and src[1] - tgt[1] >= TAKE:
        best = (aid, src, tgt, cap)
        break
if not best:
    sys.exit("no stash pair on %s can take a %d-unit merge inside its cap" % (ACCOUNT, TAKE))

aid, (src_id, src_q), (tgt_id, tgt_q), cap = best
print("account=%s | %s (cap %d): source %s x%d -> destination %s x%d, take %d"
      % (ACCOUNT, before_tree.name_of(src_id), cap, src_id[:8], src_q, tgt_id[:8], tgt_q, TAKE))

status, out = api("/api/actions/combine", {"account": ACCOUNT, "instance_id": src_id,
                                           "target_instance_id": tgt_id, "amount": TAKE,
                                           "confirmed": True})
print("\n== COMBINE http %s executed=%s error=%s" % (status, out.get("executed"), out.get("error")))
print("   sent:", json.dumps((out.get("preview") or {}).get("body"))[:240])
print("   detail:", (out.get("detail") or "")[:280])
print("   after:", out.get("after"), "| lost:", out.get("lost"))

mid_tree, mid_stacks = snapshot("middle")
print("   middle: source=%s destination=%s" % (mid_stacks.get(src_id), mid_stacks.get(tgt_id)))

if not out.get("executed"):
    print("\nREFUSED by the gateway — nothing changed "
          "(diff vs baseline: %s)" % ({k: (before_stacks[k], mid_stacks.get(k))
                                       for k in before_stacks if before_stacks[k] != mid_stacks.get(k)} or "none"))
    sys.exit(0)

# إرجاع نفس العدد بالعكس بالظبط
status, back = api("/api/actions/combine", {"account": ACCOUNT, "instance_id": tgt_id,
                                            "target_instance_id": src_id, "amount": TAKE,
                                            "confirmed": True})
print("\n== RESTORE http %s executed=%s error=%s" % (status, back.get("executed"), back.get("error")))
print("   detail:", (back.get("detail") or "")[:240])

after_tree, after_stacks = snapshot("after")
diff = {k[:8]: (before_stacks[k], after_stacks.get(k)) for k in
        set(before_stacks) | set(after_stacks) if before_stacks.get(k) != after_stacks.get(k)}
print("\n== FINAL CHECK")
print("   instances before/after:", len(before_tree.by_id), "/", len(after_tree.by_id))
print("   stack diffs:", diff or "NONE")
print("   RESULT:", "RESTORED EXACTLY" if not diff else "NOT RESTORED — see data/…/live_merge_run/")
