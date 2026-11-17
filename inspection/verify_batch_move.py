"""تأكيد نقل حقيقية واحدة على batch-operation ثم إرجاعها فورًا لنفس الخانة.

القطعة: أقل خامة قيمة في الستاش. النقل لخانة ستاش فاضية في نفس الحاوية
(أقل خطر) — وبعدين reverse setParents للتأكد إن الحالة رجعت بالظبط.
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc, pioneer_tree as pt  # noqa: E402

TOKEN = pc.account_token("G18")
URL = pc.BASE + "/v1/pioneer/v1/batch-operation"
HDRS = pc.headers(TOKEN, pc.load_manifest())


def tree_of():
    data = pc.fetch_inventory_for("G18")
    t = pt.Tree((data or {}).get("items") or [])
    lay = pt.layout(t)
    return t, lay


def send(label, ops):
    body = {"operations": ops}
    r = requests.post(URL, headers=HDRS, json=body, timeout=config.HTTP_TIMEOUT)
    print("\n%s -> HTTP %s" % (label, r.status_code))
    try:
        out = r.json()
    except ValueError:
        print("  raw:", r.text[:300]); return None
    cs = out.get("changeset") or {}
    items = cs.get("items") or {}
    print("  created=%s deleted=%s updated=%s" % (items.get("created"),
                                                  items.get("deleted"), items.get("updated")))
    if items.get("updated"):
        for u in items["updated"][:3]:
            print("   updated keys:", json.dumps(u)[:400])
    rest = {k: v for k, v in cs.items() if k != "items"}
    print("  other changeset:", json.dumps(rest)[:250])
    if r.status_code >= 400:
        print("  error:", json.dumps(out)[:300])
    return out


t, lay = tree_of()
cells = [str(c) for c in lay["stash"]["slots"]]
bp = [str(c["wrapper"] if isinstance(c, dict) else c) for c in (lay["backpack"]["slots"] or [])]
free_bp = [c for c in bp if not t.first_child(c)]
print("stash cells=%d | backpack cells=%d free=%d" % (len(cells), len(bp), len(free_bp)))
src_cell = src_item = None
for c in cells:
    it = t.first_child(c)
    if it and "bandage" in (t.name_of(it) or "").lower() and t.amount(it) <= 5:
        src_cell, src_item = c, it
        break
empty_cell = next((c for c in cells if not t.first_child(c)), "") or (free_bp[0] if free_bp else "")
print("item=%s name=%s amount=%s from cell=%s -> dest cell=%s (backpack=%s)"
      % (src_item, t.name_of(src_item), t.amount(src_item), src_cell, empty_cell,
         empty_cell in free_bp))
if not (src_item and empty_cell):
    sys.exit("nothing to test")

before = {str(e["instanceId"]): str(t.parent.get(str(e["instanceId"])) or "") for e in t.items}

send("MOVE to empty cell", [{"discriminator": "setParents",
                            "itemInstanceId": src_item, "parentInstanceIds": [empty_cell]}])

t2, _ = tree_of()
now_parent = t2.parent.get(src_item)
print("verified after move: parent=%s (expect %s) | amount=%s"
      % (now_parent, empty_cell, t2.amount(src_item)))
print("old cell now holds:", t2.first_child(src_cell) or "EMPTY")

send("BACK to original cell", [{"discriminator": "setParents",
                                "itemInstanceId": src_item, "parentInstanceIds": [src_cell]}])

t3, _ = tree_of()
after = {str(e["instanceId"]): str(t3.parent.get(str(e["instanceId"])) or "") for e in t3.items}
moved = [k for k in before if k in after and before[k] != after[k]]
gone = [k for k in before if k not in after]
added = [k for k in after if k not in before]
print("\nfinal diff vs start: moved=%d gone=%d added=%d" % (len(moved), len(gone), len(added)))
print("item parent=%s (orig %s) amount=%s empty cell now=%s"
      % (after.get(src_item), src_cell, t3.amount(src_item), t3.first_child(empty_cell) or "EMPTY"))
print("names moved:", [t3.name_of(k) for k in moved][:10])
print("names gone:", [t.name_of(k) for k in gone][:10])
