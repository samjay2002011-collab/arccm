"""ليه bench_levels_from_tree رجعت فاضي؟ بنقارن على نفس الكاش:
  - بدون فلتر الأب،
  - مع فلتر الأب،
  وبنطبع أب كل عقدة محطة عشان نعرف هي في أي حاوية فعلاً.
"""
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import knowledge, pioneer_tree  # noqa: E402

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_trees_cache.json.gz")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bench_debug_out.txt")

with gzip.open(CACHE, "rt", encoding="utf-8") as fh:
    trees = json.load(fh)

lines = []
say = lambda *a: lines.append(" ".join(str(x) for x in a))  # noqa: E731

for account in sorted(trees):
    tree = pioneer_tree.Tree(trees.get(account) or [])
    say("\n== %s (%s عقدة)" % (account, len(tree.by_id)))
    loose, any_parent = {}, {}
    for iid in tree.by_id:
        name = tree.name_of(iid)
        hit = knowledge.bench_object(name)
        if not hit:
            continue
        key, level = hit
        parent = tree.parent.get(iid) or ""
        plabel = tree.name_of(parent) or "(بلا أب)"
        say("   %-16s LV%s  %-24s أب=%s" % (key, level, name[:24], plabel[:34]))
        if not parent:
            loose[key] = max(level, int(loose.get(key) or 0))
        any_parent[key] = max(level, int(any_parent.get(key) or 0))
    say("   بدون فلتر الأب: %s" % (any_parent or "{}"))
    say("   بفلاتر الطافية بس: %s" % (loose or "{}"))
    say("   bench_levels_from_tree(): %s" % (knowledge.bench_levels_from_tree(tree) or "{}"))

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("wrote", OUT)
