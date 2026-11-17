"""شكل الأوفر ستاش على batch-operation: نقله حقيقية واحدة ثم إرجاعها لخانتها.

السؤال: هل setParents بأب = Inventory Root (أو [] أو حاوية الستاش) بيطّلع القطعة
"عائمة" زي ما مسار mutate القديم كان بيعمل؟ بنجرّب واحدة وبيرجّعها بنفسه.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc, pioneer_tree as pt  # noqa: E402

ACC = os.environ.get("FAHMY_ACC", "G18")
TOKEN = pc.account_token(ACC)
BATCH = "/v1/pioneer/v1/batch-operation"


def tree():
    return pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])


def snap(t):
    return {i: str(t.parent.get(i) or "") for i in t.by_id}


def ask(ops):
    try:
        r = pc.post_json(BATCH, {"operations": ops}, token=TOKEN)
        return "200 %s" % str(r)[:160]
    except pc.PioneerError as exc:
        return "%s %s | %s" % (type(exc).__name__, str(exc)[:110], getattr(exc, "reason", ""))


t = tree()
roots = t.roots()
# الـ Inventory Root الحقيقي = الأب اللي جواه حاوية اسمها STASH
inv_root = ""
for rid in roots:
    if any("stash" in t.name_of(k).lower() for k in t.children(rid)):
        inv_root = rid
        break
stash_box = ""
for rid in roots:
    for k in t.children(rid):
        if "stash" in t.name_of(k).lower():
            stash_box = k
            break
    if stash_box:
        break
print("inv_root=%s %r  stash_box=%s %r" % (inv_root, t.name_of(inv_root), stash_box, t.name_of(stash_box)))

lay = pt.layout(t)
cells = [c for c in lay["backpack"]["slots"] if c.get("wrapper")]
pick = None
for c in cells:
    kid = t.first_child(c["wrapper"])
    if kid and t.amount(kid) <= 60 and not t.children(kid):
        pick = (kid, c["wrapper"], c.get("slot_index"), t.name_of(kid), t.amount(kid))
        break
if not pick:
    print("no small backpack item — abort")
    sys.exit(1)
iid, home, slot, name, qty = pick
print("test item=%s %r x%s in backpack cell #%s %s" % (iid, name, qty, slot, home[:8]))

before = snap(t)
print("nodes=%d loose_roots=%d" % (len(before), len([i for i in t.roots() if not t.children(i)])))

def restore():
    return ask([{"discriminator": "setParents", "itemInstanceId": iid, "parentInstanceIds": [home]}])


for tag, parents in (("[]", []), ("[inv_root]", [inv_root]), ("[stash_box]", [stash_box])):
    if tag != "[]" and not parents:
        continue
    t = tree()
    cur_parent = str(t.parent.get(iid) or "")
    if cur_parent != home:
        print("item left its cell (parent=%s) before the test — restoring" % cur_parent[:8])
        print("   restore ->", restore())
    print("== trying parentInstanceIds=%s" % tag)
    verdict = ask([{"discriminator": "setParents", "itemInstanceId": iid, "parentInstanceIds": parents}])
    print("   %s -> %s" % (tag, verdict))
    t2 = tree()
    after = snap(t2)
    if iid not in after:
        print("   item ABSENT from the tree after the call — aborting, needs a human look")
        break
    moved = [i for i in after if after[i] != before.get(i, "<new>")]
    gone = [i for i in before if i not in after]
    new = [i for i in after if i not in before]
    print("   parent(%s)=%r in_roots=%s moved=%d new=%d gone=%d"
          % (iid[:8], after[iid][:8], iid in t2.roots(), len(moved), len(new), len(gone)))
    if after[iid] != home:
        print("   ACCEPTED (item left its cell) -> restoring %s: %s" % (home[:8], restore()))
        t3 = tree()
        print("   restored parent=%r name=%r qty=%s"
              % (str(t3.parent.get(iid) or "")[:8], t3.name_of(iid), t3.amount(iid)))
        print("   accepted shape = %s" % tag)
        break
