"""تشخيص خطأ عدّاد الخامات: Anvil I / Hand Drill على G22.

بيقارن ثلاث حاجات بالظبط:
  1) الـ asset_id اللي وصفة Anvil I طلبته لكل خامة (والبدائل المتاحة في items_db)،
  2) الـ asset_id + الاسم اللي مخزن الحساب مسجل بيهم القطع فعلاً (جدول instances)،
  3) اللي بتشوفه دالة `workshop.recipes()` الوقتي (have/owned).
قراءة وبس — مفيش أي كتابة على البوابة أو الداتابيز.
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, store, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_material_id_trace_out.txt")
SLUG = "anvil_i"


def dump_mats(w):
    row = items_db.by_slug(SLUG) or {}
    w("وصفة %s (%s) — الخامات زي ما هي في items_db:\n" % (SLUG, row.get("name")))
    for mat in row.get("recipe") or []:
        w("   %-34s qty=%s slug=%-26s asset_ids=%s\n"
          % (mat.get("name"), mat.get("qty"), mat.get("slug"), mat.get("asset_ids")))
    w("نفس الخامات بعد `_material_rows` (اللي بيشوفها المصنع):\n")
    for m in items_db.recipe_by_slug(SLUG)["materials"]:
        w("   %-34s asset_id(المستخدم)=%-12s كل البدائل=%s qty=%s\n"
          % (m["name"], m["asset_id"] or "-", m["asset_ids"], m["qty"]))


def dump_hand_drill(w, conn):
    hd = items_db.find(name="Hand Drill") or {}
    w("\nHand Drill في items_db: slug=%s asset_ids=%s\n" % (hd.get("slug"), hd.get("asset_ids")))
    w("أي عناصر تانية في القاعدة اسمها فيه 'drill':\n")
    for slug, item in sorted((items_db._load().get("items") or {}).items()):
        if "drill" in str(item.get("name") or "").lower():
            w("   %-30s name=%-24s asset_ids=%s\n" % (slug, item.get("name"), item.get("asset_ids")))
    w("\nقطع 'Hand Drill' في جدول instances لكل حساب:\n")
    rows = conn.execute("SELECT account, asset_id, name, SUM(qty) q, COUNT(*) tiles FROM instances "
                        "WHERE lower(name) LIKE '%drill%' GROUP BY account, asset_id, name "
                        "ORDER BY account, q DESC").fetchall()
    for r in rows:
        w("   %-14s asset_id=%-12s name=%-22s qty=%-4s خانات=%s\n"
          % (r["account"], r["asset_id"], r["name"], r["q"], r["tiles"]))
    if not rows:
        w("   (ولا سطر — مفيش أي قطعة اسمها drill في أي حساب)\n")


def main():
    conn = store.db()
    buf = io.StringIO()
    w = buf.write
    dump_mats(w)
    dump_hand_drill(w, conn)
    for acc in ("G22", "HEZRON"):
        name = None
        for row in store.list_accounts(conn):
            key = row["name"] if isinstance(row, dict) else row
            if str(key).upper().startswith(acc):
                name = key
                break
        if not name:
            continue
        w("\n== %s ==\n" % name)
        owned = workshop.owned_by_asset(conn, name)
        w("   إجمالي الشجرة لكل asset_id خاص بـ Hand Drill: %s\n"
          % json.dumps({a: owned.get(str(a), 0)
                        for a in (items_db.find(name="Hand Drill") or {}).get("asset_ids") or []}))
        rec = next((r for r in workshop.recipes(conn, name) if r["slug"] == SLUG), None)
        if not rec:
            w("   الوصفة مش ظاهرة في مصنع الحساب (فلتر التفعيل).\n")
            continue
        for m in rec["materials"]:
            w("   %-34s need=%s have=%s owned=%s asset_id=%s\n"
              % (m["name"], m["need"], m["have"], m["owned"], m["asset_id"]))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
