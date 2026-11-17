"""تحليل بس: مطابقة اسماء عقد "Unlock Craft" مع الوصفات المقفولة اللي مالهاش عقدة.

السؤال: الـ 21 وصفة اللي arctracker بيقول عليها blueprint_locked ومفيش ليها عقدة في
الفهرس — هل فعلاً مالهاش عقدة، ولا اسمها في الفهرس مكتوب بطريقة تانية (مثلاً
"Yank Nade" بدل "Yank Grenade")؟ ولو الفهرس فيه اسم عقدة مالوش وصفة عندنا، ده يبان
كمان.
"""
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, items_db, knowledge, pioneer_tree  # noqa: E402


def toks(text):
    return {t for t in re.sub(r"[^a-z0-9]+", " ", items_db.norm(text)).split() if t}


def main():
    uni = knowledge.unlock_universe()
    node_names = {v["name"] for v in uni.values()}
    print(f"unlock node distinct names = {len(node_names)}")
    print("\n== كل اسماء العقد ==")
    for n in sorted(node_names, key=str.lower):
        ref = uni[items_db.norm(n)]
        print(f"  {n!r:55s} slug={ref['slug']!r:30s} gates={ref['gates']}")

    gated = set()
    for ref in uni.values():
        gated |= {str(s) for s in ref["gates"]}
        if ref["slug"]:
            gated.add(ref["slug"])

    rows = items_db.craftable_rows()
    missing = [r for r in rows if r.get("blueprint_locked")
               and str(r["slug"]) not in gated
               and items_db.norm(r.get("name") or "") not in {items_db.norm(n) for n in node_names}]
    print(f"\n== وصفات مقفولة بلا عقدة ({len(missing)}) + اقرب اسم عقدة ==")
    for row in missing:
        rt = toks(row.get("name"))
        scored = sorted(((len(rt & toks(n)), n) for n in node_names), reverse=True)[:3]
        print(f"  {row['name']!r:40s} bp={row.get('blueprint')!r:35s} overlap={scored}")

    # عقد مالهاش وصفة عندنا
    recipe_names = {items_db.norm(r.get("name") or "") for r in rows}
    orphan = [n for n in node_names if items_db.norm(n) not in recipe_names]
    print(f"\n== اسماء عقد مالهاش وصفة في items_db ({len(orphan)}) ==")
    for n in sorted(orphan, key=str.lower):
        print("  ", n)

    # هل الفهرس فيه اصول بلا اسم؟ (عقد ممكن تكون موجودة بس مجهولة)
    names = pioneer_tree.asset_names()
    print(f"\nasset index rows={len(names)}")
    no_display = [a for a, r in names.items()
                  if not str(r.get("display_name") or "").strip()]
    print(f"rows بلا display_name = {len(no_display)}")

    # حسابات: كام عقدة مقروءة مقابل عدد الاصول العائمة اللي مالهاش اسم في الشجرة
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    for acc in [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]:
        print(f"\n== {acc}: rows={len(knowledge.unlocked(conn, acc))} "
              f"measured={knowledge.unlock_measured(conn, acc)}")
    conn.close()


if __name__ == "__main__":
    main()
