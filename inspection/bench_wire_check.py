"""تأكيد أخير قبل الوصل: مكان عقد المحطات + هل عائلاتنا بتتشابه مع مستويات الوصفات.

  (أ) بنبني الشجرة بـ pioneer_tree.Tree (الـ slots عنده نصوص مش كائنات) ونتأكد
      إن جسم المحطة فعلاً بلا أب (برا أي حاوية) وإن نسخة واحدة لكل عائلة.
  (ب) من items_db: لكل محطة، أعلى station_level مطلوب لأي وصفة عندها — عشان
      نعرف المحطات اللي مفيش لها نسخ مستويات في الفهرس (Workbench) متقفل عليها إيه.
قراءة من الكاش — مفيش شبكة ولا كتابة.
"""
import gzip
import io
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, pioneer_tree  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bench_wire_check_out.txt")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_trees_cache.json.gz")


def main():
    buf = io.StringIO()
    w = buf.write
    with gzip.open(CACHE, "rt", encoding="utf-8") as fh:
        trees = json.load(fh)

    w("===== (أ) أجسام المحطات بـ pioneer_tree.Tree =====\n")
    for account in sorted(trees):
        tree = pioneer_tree.Tree(trees.get(account) or [])
        found = defaultdict(list)
        for iid in tree.by_id:
            hit = knowledge.bench_object(tree.name_of(iid))
            if not hit:
                continue
            key, level = hit
            found[key].append((level, iid, bool(tree.parent.get(iid)),
                               len(tree.children(iid)), str(iid)[:8]))
        w("\n== %s\n" % account)
        for key in sorted(found):
            for level, _iid, has_parent, kids, short in sorted(found[key]):
                w("   %-16s LV%s أب=%s أبناه=%s %s\n" % (
                    key, level, "جوّه حاوية" if has_parent else "طافية", kids, short))
        missing = [k for k in knowledge.BENCH_STATIONS if k not in found and k != "in_raid"]
        w("   ما اتقراش: %s\n" % (", ".join(missing) or "-"))

    w("\n===== (ب) مستويات الوصفات المطلوبة لكل محطة (items_db) =====\n")
    per_station = defaultdict(Counter)
    for row in items_db.craftable_rows():
        for st in row.get("stations") or []:
            per_station[st][int(row.get("station_level") or 0)] += 1
    for st in sorted(per_station):
        w("   %-16s %s\n" % (st, dict(sorted(per_station[st].items()))))

    w("\n===== أسماء أجسام المحطات المعتمدة =====\n")
    for name, hit in sorted(knowledge.BENCH_OBJECTS.items()):
        w("   %-24s -> %s LV%s\n" % (name, hit[0], hit[1]))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
