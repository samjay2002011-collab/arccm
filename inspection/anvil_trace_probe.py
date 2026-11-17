"""تشخيص دقيق: ليه Anvil ظهر عند HEZRON؟

المخرج ملف UTF-8 (الكونسول بيعفّش العربي). بيطبع لكل حساب:
  - اسم الرايدر المسجل عندنا،
  - كل عقدة تفعيل مخزّنة: اسمها الخام + الـ slug اللي اتحل لها + البوابات،
  - الوصفات الظاهرة مقسومة: أساسية (من DEFAULT) vs مثبتة بعقدة،
  - حالة anvil_i تحديداً من أين جه الدليل.
مفيش أي كتابة على البوابة ومفيش أي تعديل على الداتابيز — قراءة وبس.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, pioneer_tree, store, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_anvil_trace_out.txt")


def account_label(conn, name):
    row = store.get_account(conn, name)
    row = dict(row or {})
    for key in ("raider_name", "raider", "display_name", "profile_name", "handle"):
        if row.get(key):
            return str(row[key])
    return "?"


def main():
    conn = store.db()
    buf = io.StringIO()
    w = buf.write
    defaults = sorted(knowledge.default_recipes())
    w("عدد الوصفات الأساسية في القائمة الصلبة: %s\n" % len(defaults))
    w("هل anvil_i أساسية؟ %s\n" % ("anvil_i" in defaults))
    anvil = items_db.by_slug("anvil_i") or {}
    w("anvil_i من arctracker: blueprint_locked=%s related_blueprint_id=%s station=%s lvl=%s name=%r\n"
      % (anvil.get("blueprint_locked"), anvil.get("related_blueprint_id"),
         anvil.get("craft_bench"), anvil.get("station_level"), anvil.get("name")))
    hits = sorted(str(row.get("display_name") or row.get("game_asset_name") or "").strip()
                  for row in pioneer_tree.asset_names().values()
                  if "anvil" in str(row.get("display_name") or "").lower())
    w("أصول في الفهرس فيها 'anvil': %s\n" % (hits or "-"))
    for h in hits:
        w("   حل اسم %r -> %s\n" % (h, knowledge._resolve_target(h)))

    for acc in store.list_accounts(conn):
        name = acc["name"] if isinstance(acc, dict) else acc
        rows = knowledge.unlocked(conn, name)
        w("\n== %s (رايدر: %s) — %s عقدة\n" % (name, account_label(conn, name), len(rows)))
        for i, row in enumerate(sorted(rows, key=lambda r: str(r.get("name"))), 1):
            w("   %2d. %-42s -> slug=%-28s gates=%s\n"
              % (i, str(row.get("name"))[:42], row.get("slug"), row.get("gates")))
        access = knowledge.craft_access(conn, name)
        proven = knowledge.proven_keys(conn, name)
        visible = sorted(str(r.get("slug")) for r in workshop.recipes(conn, name))
        from_def = [s for s in visible if s in defaults]
        from_node = [s for s in visible if s not in defaults]
        w("   ظاهرة=%s (من الأساسية %s + من العقد %s)\n"
          % (len(visible), len(from_def), len(from_node)))
        w("   من العقد: %s\n" % (", ".join(from_node) or "-"))
        w("   حالة anvil_i: allowed=%s | في defaults=%s | في proven slugs=%s\n"
          % (access.get("anvil_i"), "anvil_i" in defaults, "anvil_i" in proven["slugs"]))
        # أي اسم/نواة ثبتت anvil؟
        anvil_names = {items_db.norm(anvil.get("name") or ""), knowledge._core(anvil.get("name") or "")}
        w("   تطابق بالاسم؟ %s | بالنواة؟ %s\n"
          % (bool(anvil_names & proven["names"]), bool({a for a in anvil_names if a} & proven["cores"])))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
