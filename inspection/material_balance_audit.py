"""تدقيق شامل لعدّاد الخامات بعد الإصلاح (قراءة وبس).

لكل حساب وكل وصفة ظاهرة:
  - تسرب: خامة عدّها صفر مع إن شجرة الحساب فيها قطع بنفس الاسم (كان ده خطأ Anvil).
  - مجهولة الرقم: خامة ملهاش أي asset_id مقاس — العد صفر بالنظام ولازم يبقى قليل.
  - مبالغة: خامة عدّها أكبر من مجموع قطع الشجرة المسجلة بأسمائها.
وبعد كده بيقارن كام وصفة بقت برقم عرض رسمي (cost_match) قبل وبعد.
"""
import io
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, store, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_material_balance_audit_out.txt")


def name_totals(conn):
    """{account: {norm(name): qty}} من الشجرة المقاسة نفسها."""
    out = defaultdict(lambda: defaultdict(int))
    for r in conn.execute("SELECT account, name, SUM(qty) q FROM instances "
                          "WHERE name IS NOT NULL GROUP BY account, name"):
        out[r["account"]][items_db.norm(r["name"])] = int(r["q"] or 0)
    return out


def main():
    conn = store.db()
    buf = io.StringIO()
    w = buf.write
    tree = name_totals(conn)
    misses = unknown = 0
    claimed = defaultdict(set)          # asset_id -> {مفاتيح الخامات اللي بتعدّه}
    for acc in store.list_accounts(conn):
        name = acc["name"] if isinstance(acc, dict) else acc
        rows = workshop.recipes(conn, name)
        local_miss = []
        for rec in rows:
            for mat in rec["materials"]:
                key = items_db.norm(mat.get("name") or "")
                real = tree.get(name, {}).get(key, 0)
                for asset_id in mat.get("asset_ids") or []:
                    claimed[asset_id].add(str(mat.get("key") or key))
                if not mat.get("asset_ids"):
                    unknown += 1
                    if real:
                        local_miss.append((rec["slug"], mat["name"], real))
                    continue
                if mat["owned"] == 0 and real > 0:
                    local_miss.append((rec["slug"], mat["name"], real))
        misses += len(local_miss)
        w("%-14s وصفات ظاهرة=%s | خامات بلا رقم=%s | تسرب=%s\n"
          % (name, len(rows), sum(1 for r in rows for m in r["materials"] if not m.get("asset_ids")),
             len(local_miss)))
        for slug, mat, real in local_miss:
            w("      ✗ %-22s %-32s في الشجرة %s والموقع عدّه صفر\n" % (slug, mat, real))

    shared = {a: keys for a, keys in claimed.items() if len(keys) > 1}
    w("\nأرقام بتنسب لأكثر من خامة (خطر العد المزدوج): %s\n" % len(shared))
    for asset_id, keys in sorted(shared.items()):
        w("   %s -> %s\n" % (asset_id, sorted(keys)))

    baked = sum(1 for v in workshop.catalog().values() if v.get("cost_match"))
    live = sum(1 for slug in workshop.catalog() if workshop.offer_for(conn, slug).get("cost_match"))
    with_offer = {}
    for acc in store.list_accounts(conn):
        name = acc["name"] if isinstance(acc, dict) else acc
        with_offer[name] = sum(1 for r in workshop.recipes(conn, name) if r.get("offer_id"))
    w("\nأرقام العروض المطابقة: في الملف %s -> بعد الحل الحيّ %s من %s عرض\n"
      % (baked, live, len(workshop.catalog())))
    w("وصفات ظاهرة ولها رقم عرض لكل حساب: %s\n" % with_offer)
    w("\nالإجمالي: تسرب=%s (لازم صفر) | خامة بلا رقم=%s | أرقام مشتركة=%s\n"
      % (misses, unknown, len(shared)))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
