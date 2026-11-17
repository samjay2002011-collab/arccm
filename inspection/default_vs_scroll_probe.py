"""كروت مخطوطة حالتها مش "learned" لكن وصفتها ظاهرة في المصنع — مين دول؟

    python inspection/default_vs_scroll_probe.py

لو القائمة الأساسية (DEFAULT_UNLOCKED_RECIPES) فيها عنصر ليها مخطوطة في اللعبة،
فده تعارض: arctracker بيقول مش محتاجة مخطط واللعبة ليها ورقة مخطط. بتطبع كمان
أي عنصر في الـ 56 له عقدة تفعيل في الفهرس، عشان نحسم يشيل من القائمة الأساسية ولا لأ.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, store, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_default_vs_scroll_out.txt")


def main():
    lines = []
    conn = store.db()
    targets = {}
    for row in items_db.blueprint_rows():
        if row.get("target"):
            targets.setdefault(row["target"], []).append(row.get("name") or row.get("slug"))
    universe_names = {str(ref.get("name")).lower() for ref in knowledge.unlock_universe().values()}

    lines.append("== عناصر في DEFAULT_UNLOCKED_RECIPES وليها مخطوطة في اللعبة")
    for slug in sorted(knowledge.default_recipes()):
        scrolls = targets.get(slug)
        gated = slug in knowledge.gated_slugs()
        if not scrolls and not gated:
            continue
        row = items_db.by_slug(slug) or {}
        lines.append("   %-28s مخطوطة=%s | عقدة تفعيل=%s | locked=%s | اسم=%s"
                     % (slug, scrolls or "-", gated, row.get("blueprint_locked"), row.get("name")))

    for name in [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]:
        owned = workshop.owned_by_asset(conn, name)
        owned_names = workshop.owned_by_name(conn, name)
        state = knowledge.blueprint_state(conn, name, owned, owned_names)
        access = knowledge.craft_access(conn, name, owned, owned_names)
        odd = [c["target"] for c in knowledge.cards(conn, name, owned, owned_names)
               if c.get("craftable") and state.get(c["target"]) != "learned"]
        lines.append("")
        lines.append("== %s | كروت مش learned لكن مسموحة (%s): %s" % (name, len(odd), odd))
        hidden_locked = [c["target"] for c in knowledge.cards(conn, name, owned, owned_names)
                         if not c.get("craftable") and state.get(c["target"]) == "learned"]
        lines.append("   learned بس مش مسموحة (%s): %s" % (len(hidden_locked), hidden_locked))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("written: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
