"""قياس حجم المشكلة: كام خامة في كل الوصفات ملهاش asset_id في items_db،
وكام واحدة فيهم بتتحل لو طلعنا الـ ids من فهرس الأصول المحلي بالاسم.

كمان بيطبع حالة التطابق مع اللي مخزنه في جدول instances (أرقام حقيقية من البوابة).
قراءة وبس.
"""
import io
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, pioneer_tree, store, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_material_coverage_out.txt")


def main():
    conn = store.db()
    buf = io.StringIO()
    w = buf.write

    names = pioneer_tree.asset_names()
    w("فهرس الأصول المحلي: %s أصل\n" % len(names))
    w("هل -605737193 موجود في الفهرس؟ %s\n" % (names.get("-605737193"),))

    by_norm = defaultdict(list)
    for aid, row in names.items():
        label = (row.get("display_name") or row.get("game_asset_name") or "").strip()
        if label:
            by_norm[items_db.norm(label)].append(str(aid))

    # أي asset_id موجود في instances (عند أي حساب) مربوط بأي اسم؟
    inst = defaultdict(set)
    for r in conn.execute("SELECT DISTINCT asset_id, name FROM instances "
                          "WHERE asset_id IS NOT NULL AND asset_id <> ''").fetchall():
        inst[items_db.norm(r["name"])].add(str(r["asset_id"]))

    rows = items_db.craftable_rows()
    mats = {}
    for row in rows:
        for m in row.get("materials") or []:
            mats[(str(m.get("slug")), str(m.get("name")))] = m
    w("\nإجمالي الوصفات: %s | خامات مميزة: %s\n" % (len(rows), len(mats)))

    no_id = [(k, m) for k, m in sorted(mats.items()) if not (m.get("asset_ids") or [])]
    w("خامات ملهاش أي asset_id في items_db: %s\n" % len(no_id))
    fixed = still = 0
    for (slug, name), m in no_id:
        key = items_db.norm(name)
        idx = sorted(set(by_norm.get(key) or []))
        own = sorted(inst.get(key) or [])
        pool = sorted(set(idx) | set(own))
        if pool:
            fixed += 1
            w("   ✔ %-34s slug=%-30s من الفهرس=%s من الشجرة=%s\n" % (name, slug, idx or "-", own or "-"))
        else:
            still += 1
            w("   ✗ %-34s slug=%-30s (مفيش أي أصل بهذا الاسم)\n" % (name, slug))
    w("\nاللي اتحل بالفهرس/الشجرة: %s | اللي لسه غامض: %s\n" % (fixed, still))

    # الخامات اللي ليها id بس الـ id ده مش موجود في شجرة أي حساب
    bad = []
    for (slug, name), m in sorted(mats.items()):
        ids = [str(a) for a in (m.get("asset_ids") or [])]
        if not ids:
            continue
        key = items_db.norm(name)
        seen = inst.get(key) or set()
        if seen and not (set(ids) & seen):
            bad.append((name, slug, ids, sorted(seen)))
    w("\nخامات ليها id في items_db لكن قطع الشجرة الحقيقية مسجلة بـ id تاني: %s\n" % len(bad))
    for name, slug, ids, seen in bad:
        w("   ! %-34s slug=%-30s items_db=%s instances=%s\n" % (name, slug, ids, seen))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
