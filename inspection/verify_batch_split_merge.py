"""إثبات مسار batch للتقسيم والدمج من غير أي كتابة على البوابة.

post_mutate / _refetch / _refresh_data / _log كلهم مستبدلين: الإسكربت مابعتهزش
يولّد أمرًا واحدًا حقيقي، وبيبنأ شجرة "بعد" مصنوعة عشان يفحص منطق التحقق نفسه.
"""
import copy
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc, pioneer_tree as pt, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G18"
TAKE = 5
SENT = []
CONVERTED = []


def fake_post(request, token):
    SENT.append(request)
    # التحويل نفسه جزء من المنطق: بنسجّله وهو رايح للبواب عشان الأسماء تتفحص هنا
    ops, unsupported = pw.to_operations((request or {}).get("mutations"))
    CONVERTED.append((ops, unsupported))
    return {"changeset": {"items": {"created": [], "updated": []}}}


pw.post_mutate = fake_post
pw._refresh_data = lambda conn, account, data: {"ok": True, "stubbed": True}
pw._log = lambda *a, **k: None
pw._pause_block = lambda: None

# المعرّف اللي بيتولّد للقطعة الجديدة ثابت هنا، عشان الشجرة المصنوعة تستخدم نفس الآيدي
FIXED_ID = str(uuid.uuid4())


class _FixedUuid:
    @staticmethod
    def uuid4():
        return FIXED_ID


pw.uuid = _FixedUuid

data = pc.fetch_inventory_for(ACCOUNT) or {}
items = data.get("items") or []
tree = pt.Tree(items)
lay = pt.layout(tree)
stash_cells = set(lay["stash"]["slots"])

src = ""
for iid, node in tree.by_id.items():
    if node.get("slots") or int(node.get("amount") or 0) <= TAKE:
        continue
    par = str(tree.parent.get(iid) or "")
    if par and par in stash_cells:
        src = iid
        break
if not src:
    sys.exit("no stash stack big enough for the test")

aid = str(tree.by_id[src].get("gameAssetId"))
qty = int(tree.by_id[src].get("amount"))
free_bp = [str((s.get("wrapper") if isinstance(s, dict) else s))
           for s in lay["backpack"]["slots"]
           if not tree.first_child(str((s.get("wrapper") if isinstance(s, dict) else s)))]
print("account=%s src=%s(%s) qty=%d asset=%s | empty backpack cells=%d"
      % (ACCOUNT, tree.name_of(src), src[:8], qty, aid, len(free_bp)))
if not free_bp:
    sys.exit("the backpack has no empty cell — the split needs one")
cell = free_bp[0]

# --- split -------------------------------------------------------------------
out = pw.split_attempt(None, ACCOUNT, src, cell, TAKE, cap=0)
print("   first call ->", {k: out.get(k) for k in ("executed", "error", "detail", "kind")})
muts = SENT[-1]["mutations"]
print("\n== SPLIT sends:", json.dumps(muts)[:260])
assert muts[0]["discriminator"] == "moveAmount", muts
assert muts[0]["fromInstanceId"] == src and muts[0]["amount"] == TAKE
assert len(muts) == 2 and muts[1]["discriminator"] == "setParents", muts
new_id = muts[0]["toInstanceId"]
assert uuid.UUID(new_id) and muts[1]["itemInstanceId"] == new_id
assert muts[1]["parentInstanceIds"] == [cell]
print("   destination id minted by the site:", new_id[:8], "-> placed under", cell[:8])

wire, uns = CONVERTED[-1]
print("   what the batch route actually receives:", json.dumps(wire)[:300])
assert not uns, uns
assert wire == [{"discriminator": "moveAmount", "fromInstanceId": src,
                 "toInstanceId": new_id, "amount": TAKE},
                {"discriminator": "setParents", "itemInstanceId": new_id,
                 "parentInstanceIds": [cell]}], wire

after = copy.deepcopy(items)
by = {str(e["instanceId"]): e for e in after}
by[src]["amount"] = qty - TAKE
fresh = copy.deepcopy(by[src])
fresh["instanceId"] = new_id
fresh["amount"] = TAKE
by.setdefault(cell, {})
if by[cell].get("slots") is None:
    by[cell]["slots"] = []
by[cell]["slots"].append(new_id)
after.append(fresh)
pw._refetch = lambda account: {"items": after}
out = pw.split_attempt(None, ACCOUNT, src, cell, TAKE, cap=0)
print("   verified -> executed=%s created=%s cell=%s after=%s" % (
    out["executed"], (out.get("created") or "")[:8], (out.get("cell") or "")[:8], out["after"]))
print("   detail:", out.get("detail"))
assert out["executed"] and out["created"] == new_id and out["cell"] == cell and not out["lost"]

# --- merge the piece back ----------------------------------------------------
pw._refetch = lambda account: {"items": items}
other = ""
for iid, node in tree.by_id.items():
    if iid != src and not node.get("slots") and str(node.get("gameAssetId")) == aid:
        par = str(tree.parent.get(iid) or "")
        if par and par in stash_cells:
            other = iid
            break
tgt = other or src
tgt_qty = int(tree.by_id[tgt].get("amount")) if tgt in tree.by_id else qty
if not other:
    print("\n== COMBINE skipped: no second stash stack of the same type")
else:
    out = pw.combine_attempt(None, ACCOUNT, src, tgt, TAKE, cap=0)
    op = SENT[-1]["mutations"][0]
    print("\n== COMBINE sends:", op)
    assert op["discriminator"] == "moveAmount" and op["toInstanceId"] == tgt, op
    assert op["fromInstanceId"] == src and op["amount"] == TAKE

    merged = copy.deepcopy(items)
    mby = {str(e["instanceId"]): e for e in merged}
    mby[tgt]["amount"] = tgt_qty + TAKE
    mby[src]["amount"] = qty - TAKE
    if qty - TAKE == 0:
        merged = [e for e in merged if str(e["instanceId"]) != src]
    pw._refetch = lambda account: {"items": merged}
    out = pw.combine_attempt(None, ACCOUNT, src, tgt, TAKE, cap=0)
    print("   verified -> executed=%s after=%s" % (out["executed"], out["after"]))
    print("   detail:", out.get("detail"))
    assert out["executed"] and not out["lost"]

    # لو البوابة فصلت بدل ما دمجّت: التحقق لازم يمسكها
    wrong = copy.deepcopy(items)
    wby = {str(e["instanceId"]): e for e in wrong}
    wby[src]["amount"] = qty - TAKE
    piece = copy.deepcopy(wby[src])
    piece["instanceId"] = str(uuid.uuid4())
    piece["amount"] = TAKE
    wrong.append(piece)
    pw._refetch = lambda account: {"items": wrong}
    out = pw.combine_attempt(None, ACCOUNT, src, tgt, TAKE, cap=0)
    print("   anti-merge tree -> executed=%s | %s" % (out["executed"], (out.get("detail") or "")[:70]))
    assert not out["executed"]

print("\nALL ASSERTIONS PASSED — no request left this process.")
