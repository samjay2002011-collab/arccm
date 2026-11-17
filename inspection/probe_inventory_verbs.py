"""جرد أفعال تحت خدمة الـinventory بصيغة `/v1/pioneer/inventory/<action>` (مسار مخصّص).

ليه الصيغة دي بالذات: `upgrade` طلع مسار مستقل (`/v1/pioneer/inventory/upgrade`)
مش discriminator جوه mutate — يعني Embark بيضيف مسار لكل عملية خاصة. فبنلفّ
على أسماء عملية التقسيم/لمّ الأكوام بكل الأشكال (with/without /v1/, kebab,
snake, camel) عشان نمسك أي مسار موجود بمقياس 404 مقابل 405.
GET بس — أي مسار يطلع موجود بنسأله POST بتوكن وهمي (صفر أثر) لو --post.
"""
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from backend import pioneer_client

VERBS = [
    "split", "split-stack", "split_stack", "splitStack", "stack-split", "stack_split",
    "merge", "merge-stack", "merge_stacks", "mergeStacks", "combine", "unstack",
    "un-stack", "divide", "portion", "partial", "partial-move", "partial_move",
    "move-partial", "move_partial", "move-amount", "set-amount", "adjust-amount",
    "quantity", "amount", "quantities", "redistribute", "rebalance", "distribute",
    "consolidate", "stack", "stack-all", "stack_all", "autostack", "auto-stack",
    "tidy", "tidy-stacks", "organize", "sort", "arrange", "pack", "compact",
    "gather", "collect", "bulk", "batch", "batch-move", "batch_move",
    "batch-mutate", "batch_mutate", "mutations", "operations", "actions", "commands",
    "move", "moves", "move-all", "move_all", "move-all-to-overflow", "overflow",
    "equip", "unequip", "attach", "detach", "recycle", "scrap", "salvage", "sell",
    "delete", "destroy", "repair", "learn", "upgrade", "mutate", "sync", "refresh",
    "tree", "root", "items", "containers", "cells", "wrappers", "slots",
]
FORMS = ["/v1/pioneer/inventory/%s", "/v1/pioneer/inventory/v1/%s",
         "/v1/pioneer/%s", "/v1/pioneer/items/%s", "/v1/pioneer/stacks/%s"]


def call(path, tok, method="GET"):
    req = urllib.request.Request(pioneer_client.BASE + path, method=method, headers={
        "User-Agent": pioneer_client.UA, "Accept": "application/json",
        "Content-Type": "application/json", "Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(160)
    except urllib.error.HTTPError as e:
        return e.code, e.read(160)
    except Exception as e:
        return None, str(e)[:120].encode()


def main():
    tok = pioneer_client.account_token()
    do_post = "--post" in sys.argv
    seen = set()
    for fmt in FORMS:
        for v in VERBS:
            path = fmt % v
            if path in seen:
                continue
            seen.add(path)
            code, body = call(path, tok)
            if code != 404:
                txt = body.decode("utf-8", "replace").replace("\n", " ")[:90]
                print("HIT %-52s GET=%s %s" % (path, code, txt))
                if do_post and code in (405, 200, 401, 403):
                    pcode, pbody = call(path, tok, "POST")
                    print("     POST=%s %s" % (pcode, pbody.decode("utf-8", "replace")[:90]))
            time.sleep(0.4)
    print("\nفحصت %s مسار." % len(seen))


if __name__ == "__main__":
    main()
