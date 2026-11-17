"""تقسيم حقيقي جوه الستاش على batch-operation — مع تجهيز خانة فاضية وإرجاعها.

الترتيب:
  A) نقل قطعة صغيرة من الستاش للأوفر (setParents — المتأكد إنه شغال) عشان نفتح خانة.
  B) moveAmount: مفصول من رصة كبيرة لنفس الخانة الفاضية (التقسيم الحقيقي).
  C) الدمج: setParents للقطعة الجديدة على الخانة اللي فيها الرصة الكبيرة — اختبار
     لو البوابة تدمج ولا لأ.
  D) إرجاع كل قطعة لمكانها الأصلي بالحرف، وطباعة الفروق.
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
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_instash_run")
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


def snap(tag):
    data = pc.fetch_inventory_for(ACCOUNT) or {}
    items = data.get("items") or []
    with open(os.path.join(OUT, "tree_%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump(items, fh)
    tree = pt.Tree(items)
    stacks = {iid: int(n.get("amount") or 0) for iid, n in tree.by_id.items() if not n.get("slots")}
    return tree, stacks


tree, stacks = snap("before")
lay = pt.layout(tree)
stash_cells = [str(c) for c in lay["stash"]["slots"]]
cells_set = set(stash_cells)

# --- A: افتح خانة بقطعة صغيرة (مش سلاح، مش حاوية، كمية صغيرة) -----------------
small = None
for iid, node in tree.by_id.items():
    if node.get("slots") or str(tree.parent.get(iid) or "") not in cells_set:
        continue
    q = int(node.get("amount") or 0)
    nm = (tree.name_of(iid) or "")
    if q < 1 or int(node.get("maxDurability") or 0) > 1:
        continue
    if any(k in nm.lower() for k in ("rifle", "smg", "pistol", "shotgun", "bow", "backpack")):
        continue
    if small is None or q < small[1]:
        small = (iid, q, nm, str(tree.parent.get(iid) or ""))
if not small:
    sys.exit("no small stash item to relocate")
mv_id, mv_q, mv_name, mv_cell = small
print("A) relocate %s x%d from cell %s to overflow" % (mv_name, mv_q, mv_cell[:8]))
st, out = api("/api/actions/move", {"account": ACCOUNT, "target_container": "overflow",
                                    "instance_ids": [mv_id], "confirmed": True})
print("   -> http %s executed=%s error=%s | %s" % (st, out.get("executed"), out.get("error"),
                                                   (out.get("detail") or "")[:120]))
tree2, stacks2 = snap("middle_a")
freed = mv_cell if mv_cell in tree2.by_id and not tree2.first_child(mv_cell) else ""
print("   freed cell:", freed[:8] or "NOT FREE", "| moved item parent:",
      str(tree2.parent.get(mv_id) or "")[:8] or "overflow")
if not freed:
    sys.exit("stop — the relocation did not free a stash cell; nothing else was tried")

# --- B: تقسيم حقيقي لنفس الخانة الفاضية --------------------------------------
big = max(((iid, q) for iid, q in stacks2.items()
           if str(tree2.parent.get(iid) or "") in cells_set and q > TAKE + 5),
          key=lambda r: r[1])
src_id, src_q = big
aid = str(tree2.by_id[src_id].get("gameAssetId"))
print("\nB) SPLIT %s x%d -> %d + %d into the freed cell %s"
      % (tree2.name_of(src_id), src_q, src_q - TAKE, TAKE, freed[:8]))
st, out = api("/api/actions/split", {"account": ACCOUNT, "instance_id": src_id,
                                     "target_wrapper_id": freed, "amount": TAKE, "confirmed": True})
print("   -> http %s executed=%s error=%s" % (st, out.get("executed"), out.get("error")))
print("   sent:", json.dumps((out.get("preview") or {}).get("body"))[:230])
print("   detail:", (out.get("detail") or "")[:260])
print("   created:", (out.get("created") or "")[:8], "cell:", (out.get("cell") or "")[:8],
      "after:", out.get("after"), "lost:", out.get("lost"))
tree3, stacks3 = snap("middle_b")
piece = out.get("created") or ""
asset_total = sum(int(n.get("amount") or 0) for n in tree3.by_id.values()
                  if not n.get("slots") and str(n.get("gameAssetId")) == aid)
print("   live: source=%s piece=%s (parent %s) total asset=%d"
      % (stacks3.get(src_id), stacks3.get(piece),
         (str(tree3.parent.get(piece) or "")[:8] if piece else "-"), asset_total))
if not out.get("executed"):
    print("\nSPLIT refused — reverting only step A.")
    st, back = api("/api/actions/move", {"account": ACCOUNT, "target_container": "stash",
                                         "instance_ids": [mv_id], "target_wrapper_id": freed,
                                         "confirmed": True})
    print("   A-revert -> http %s executed=%s %s" % (st, back.get("executed"),
                                                     (back.get("detail") or "")[:120]))
    tree_r, stacks_r = snap("after")
    print("   stack diffs vs baseline:", {k[:8]: (stacks[k], stacks_r.get(k))
                                          for k in set(stacks) | set(stacks_r)
                                          if stacks.get(k) != stacks_r.get(k)} or "NONE")
    sys.exit(0)

# --- C: الدمج بـ setParents على خانة الرصة الكبيرة ----------------------------
print("\nC) MERGE the piece onto the source stack's cell with setParents")
src_cell = str(tree3.parent.get(src_id) or "")
st, out2 = api("/api/actions/move", {"account": ACCOUNT, "target_container": "stash",
                                     "instance_ids": [piece], "target_wrapper_id": src_cell,
                                     "confirmed": True})
print("   -> http %s executed=%s error=%s | %s" % (st, out2.get("executed"), out2.get("error"),
                                                   (out2.get("detail") or "")[:150]))
tree4, stacks4 = snap("middle_c")
print("   live: source=%s piece still there=%s piece parent=%s"
      % (stacks4.get(src_id), piece in stacks4, str(tree4.parent.get(piece) or "")[:8]))

merged_ok = piece not in stacks4 and stacks4.get(src_id) == src_q
if not merged_ok:
    print("   no merge — the %d + %d split stays (units conserved)" % (src_q - TAKE, TAKE))
# الخانة اللي بنرجّع ليها الأداة لازم تكون فاضية فعلًا دلوقتي
target_for_a = freed if (freed in tree4.by_id and not tree4.first_child(freed)) else ""
print("\nD) put %s back into %s" % (mv_name, (target_for_a[:8] or "any free cell")))
st, back = api("/api/actions/move", {"account": ACCOUNT, "target_container": "stash",
                                     "instance_ids": [mv_id], "target_wrapper_id": target_for_a,
                                     "confirmed": True})
print("   -> http %s executed=%s error=%s | %s" % (st, back.get("executed"), back.get("error"),
                                                   (back.get("detail") or "")[:150]))

tree5, stacks5 = snap("after")
diff = {k[:8]: (stacks.get(k), stacks5.get(k)) for k in set(stacks) | set(stacks5)
        if stacks.get(k) != stacks5.get(k)}
moved = {k[:8]: (str(tree.parent.get(k) or "")[:8], str(tree5.parent.get(k) or "")[:8])
         for k in stacks if str(tree.parent.get(k) or "") != str(tree5.parent.get(k) or "")}
print("\n== FINAL")
print("   instances:", len(tree.by_id), "->", len(tree5.by_id))
print("   amount diffs:", diff or "NONE")
print("   parent diffs:", moved or "NONE")
