"""أشكال "من غير خانة" (الأوفر ستاش) على batch-operation — بـ UUID صفر، فمافيش كتابة.

INVENTORY_ITEM_NOT_FOUND = الشكل مقبول والقطعة مش لاقيه.
INVALID_ARGUMENT         = الشكل مرفوض أصلاً.
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc, pioneer_tree as pt  # noqa: E402

ACC = "G18"
TOKEN = pc.account_token(ACC)
URL = pc.BASE + "/v1/pioneer/v1/batch-operation"
HDRS = pc.headers(TOKEN, pc.load_manifest())
Z = "00000000-0000-0000-0000-000000000000"

tree = pt.Tree((pc.fetch_inventory_for(ACC) or {}).get("items") or [])
roots = tree.roots()
root = max(roots, key=lambda i: len(tree.children(i)))
print("nodes=%d roots=%d" % (len(tree.items), len(roots)))
print("busiest root=%s name=%r kids=%d" % (root, tree.name_of(root), len(tree.children(root))))
print("root kids names=%s" % [tree.name_of(k) for k in tree.children(root)][:8])
stash = tree.find_child(root, "stash")
print("stash container=%s name=%r kids=%d" % (stash, tree.name_of(stash), len(tree.children(stash))))
loose_items = [i for i in roots if not tree.children(i)]
print("loose (parentless) leaf nodes=%d" % len(loose_items))
for i in loose_items[:5]:
    print("   %s qty=%s name=%r" % (i, tree.amount(i), tree.name_of(i)))


def ask(op, tag):
    try:
        r = requests.post(URL, headers=HDRS, json={"operations": [op]}, timeout=config.HTTP_TIMEOUT)
        try:
            j = r.json()
            reason = "%s %s" % (r.status_code, j.get("reason") or str(j)[:60])
        except ValueError:
            reason = "%s %s" % (r.status_code, r.text[:60])
    except requests.RequestException as exc:
        reason = "network %s" % type(exc).__name__
    print("   %-44s -> %s" % (tag, reason))
    return reason


print("== setParents (القطعة وهمية: مافيش كتابة ممكنة)")
ask({"discriminator": "setParents", "itemInstanceId": Z, "parentInstanceIds": []}, "parentInstanceIds=[]")
ask({"discriminator": "setParents", "itemInstanceId": Z, "parentInstanceIds": [""]}, 'parentInstanceIds=[""]')
ask({"discriminator": "setParents", "itemInstanceId": Z, "parentInstanceIds": [root]}, "parentInstanceIds=[root]")
ask({"discriminator": "setParents", "itemInstanceId": Z, "parentInstanceIds": [stash]}, "parentInstanceIds=[stash]")
ask({"discriminator": "setParents", "itemInstanceId": Z, "parentInstanceIds": [Z]}, "parentInstanceIds=[fake]")
ask({"discriminator": "setParents", "itemInstanceId": Z}, "بدون parentInstanceIds")

print("== moveAmount")
ask({"discriminator": "moveAmount", "fromInstanceId": Z, "toParentInstanceId": "", "amount": 1}, 'toParentInstanceId=""')
ask({"discriminator": "moveAmount", "fromInstanceId": Z, "toParentInstanceId": root, "amount": 1}, "toParentInstanceId=root")
ask({"discriminator": "moveAmount", "fromInstanceId": Z, "toParentInstanceId": stash, "amount": 1}, "toParentInstanceId=stash")
