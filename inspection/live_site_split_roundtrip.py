"""اختبار نهاية-ل-نهاية للموقع: SPLIT ثم COMBINE من خلال /api/actions — على حساب محدد.

السيناريو: رصة من الستاش -> تقسيم لمعظمها لخانة فاضية في الشنطة -> دمجها رجوع في نفس
الرصة. لازم الشجرة ترجع زي ما كانت بالحرف (نفس عدد المعرّفات ونفس الكميات).
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
TAKE = int(sys.argv[2]) if len(sys.argv) > 2 else 5
SITE = "http://127.0.0.1:8000"

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
opener.open(SITE + "/login", urllib.parse.urlencode({"password": "2JR-KB8-XNT"}).encode(), timeout=15)


def api(path, payload):
    req = urllib.request.Request(SITE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        r = opener.open(req, timeout=180)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw[:300].decode("utf-8", "replace")}


def snap():
    items = (pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or []
    tree = pt.Tree(items)
    amounts = {i: int(n.get("amount") or 0) for i, n in tree.by_id.items() if not n.get("slots")}
    parents = {i: str(tree.parent.get(i) or "") for i in tree.by_id}
    return tree, amounts, parents


base_tree, base_amt, base_par = snap()
lay = pt.layout(base_tree)
wrappers = [str(s.get("wrapper")) for s in (lay["backpack"].get("slots") or []) if isinstance(s, dict)]
free = [w for w in wrappers if w in base_tree.by_id and not base_tree.first_child(w)]
cells = {str(c) for c in lay["stash"]["slots"]}
src = ""
for iid, node in base_tree.by_id.items():
    if not node.get("slots") and int(node.get("amount") or 0) > TAKE and str(base_tree.parent.get(iid) or "") in cells:
        src = iid
        break
if not src or not free:
    sys.exit("need a stash pile bigger than %d and a free backpack cell (src=%s free=%d)"
             % (TAKE, src, len(free)))
qty = int(base_tree.by_id[src].get("amount") or 0)
cell = free[0]
print("%s | split %s (%s) x%d from stash cell -> free backpack cell %s"
      % (ACCOUNT, src[:8], base_tree.name_of(src), qty, cell[:8]))

st, out = api("/api/actions/split", {"account": ACCOUNT, "instance_id": src,
                                     "target_wrapper_id": cell, "amount": TAKE, "confirmed": True})
print("\n1) POST /api/actions/split -> http %s executed=%s error=%s" % (st, out.get("executed"), out.get("error")))
print("   detail:", (out.get("detail") or "")[:240])
print("   created:", (out.get("created") or "")[:8], "| landed:", (out.get("cell") or "")[:8],
      "| after:", out.get("after"), "| lost:", out.get("lost"))
if not out.get("executed"):
    print("   body:", json.dumps((out.get("preview") or {}).get("body"))[:300])
    sys.exit(1)
piece = out["created"]

t2, a2, p2 = snap()
print("   live check: source x%s (was %d) | piece x%s under %s | instances %d -> %d"
      % (a2.get(src), qty, a2.get(piece), (p2.get(piece) or "overflow")[:8],
         len(base_tree.by_id), len(t2.by_id)))

st, out = api("/api/actions/combine", {"account": ACCOUNT, "instance_id": piece,
                                       "target_instance_id": src, "amount": TAKE, "confirmed": True})
print("\n2) POST /api/actions/combine -> http %s executed=%s error=%s" % (st, out.get("executed"), out.get("error")))
print("   detail:", (out.get("detail") or "")[:240])
print("   after:", out.get("after"), "| lost:", out.get("lost"))

t3, a3, p3 = snap()
amt_diff = {k[:8]: (base_amt.get(k), a3.get(k)) for k in set(base_amt) | set(a3)
            if base_amt.get(k) != a3.get(k)}
par_diff = {k[:8]: (base_par.get(k, "gone")[:8] or "NONE", p3.get(k, "gone")[:8] or "NONE")
            for k in set(base_par) | set(p3) if base_par.get(k) != p3.get(k)}
print("\n== RESTORE CHECK")
print("   instances: %d -> %d" % (len(base_tree.by_id), len(t3.by_id)))
print("   amount diffs vs baseline:", amt_diff or "NONE")
print("   parent diffs vs baseline:", par_diff or "NONE")
