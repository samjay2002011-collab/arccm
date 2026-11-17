"""قياس الفلترة الصارمة بعد إلغاء التخمين — قراءة بس، من غير أي طلب للبوابة.

    python inspection/strict_gate_probe.py

بيطبع في ملف UTF-8 (مش على الشاشة، cp1252 بيبوظ العربي): لكل حساب كام وصفة ظهرت،
كام اختفت، وهل العناصر المشكوك فيها (Tether Launcher وSnap Hook) مختفية فعلاً ولا لأ.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, store, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_strict_gate_out.txt")

SUSPECT = ["tether_launcher", "snap_hook", "advanced_camera", "grappling_hook", "banjo",
           "white_flag", "stiletto_i", "light_ammo", "bandage", "basic_camera",
           "showstopper", "explosive_mine", "trailblazer", "aphelion"]


def main():
    lines = []

    def say(text=""):
        lines.append(str(text))

    conn = store.db()
    accounts = [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]
    recipes = items_db.craftable_rows()
    locked_rows = [r for r in recipes if r.get("blueprint_locked")]
    free_rows = [r for r in recipes if not r.get("blueprint_locked")]
    say("وصفات في القاعدة: %s | blueprint_locked=%s | ملهاش قفل=%s"
        % (len(recipes), len(locked_rows), len(free_rows)))
    say("DEFAULT_UNLOCKED_RECIPES: %s" % len(knowledge.default_recipes()))
    free_not_default = sorted(str(r.get("slug")) for r in free_rows
                              if r.get("slug") not in knowledge.default_recipes())
    say("ملهاش قفل في arctracker ومع ذلك مش في القائمة الأساسية (%s): %s"
        % (len(free_not_default), free_not_default))
    default_locked = sorted(s for s in knowledge.default_recipes()
                            if any(str(r.get("slug")) == s and r.get("blueprint_locked") for r in recipes))
    say("في القائمة الأساسية وblueprint_locked=true مع بعض (%s): %s" % (len(default_locked), default_locked))
    universe = knowledge.unlock_universe()
    say("عقد التفعيل في الفهرس: %s | slugs ليها احتمال دليل: %s" % (len(universe), len(knowledge.gated_slugs())))
    no_node = sorted(str(r.get("slug")) for r in locked_rows
                     if r.get("slug") not in knowledge.gated_slugs()
                     and r.get("slug") not in knowledge.default_recipes())
    say("مقفولة ومالهاش عقدة تفعيل في الفهرس = هتفضل مخفية (%s): %s" % (len(no_node), no_node))

    for name in accounts:
        rows = knowledge.unlocked(conn, name)
        owned = workshop.owned_by_asset(conn, name)
        owned_names = workshop.owned_by_name(conn, name)
        states = knowledge.blueprint_state(conn, name, owned, owned_names)
        access = knowledge.craft_access(conn, name, owned, owned_names)
        counts = {}
        for value in states.values():
            counts[value] = counts.get(value, 0) + 1
        allowed = sorted(s for s, ok in access.items() if ok)
        proven_only = [s for s in allowed if s not in knowledge.default_recipes()]
        visible = workshop.recipes(conn, name)
        say("")
        say("== %s" % name)
        say("   عقد تفعيل مقروءة=%s measured=%s | حالات المخطوطات %s"
            % (len(rows), knowledge.unlock_measured(conn, name),
               " ".join("%s=%s" % (k, counts.get(k, 0)) for k in
                        ("learned", "in_stash", "not_learned"))))
        say("   مسموح=%s (أساسية %s + بدليل %s) | مخفي=%s | شغالة في الوصفة=%s"
            % (len(allowed), len(allowed) - len(proven_only), len(proven_only),
               len(access) - len(allowed), len(visible)))
        say("   اللي اتفتحت بالدليل بس: %s" % sorted(proven_only))
        bad = [r["slug"] for r in visible if not access.get(r["slug"])]
        say("   وصفة ظاهرة رغم إنها مش مسموحة (%s): %s" % (len(bad), bad))
        say("   مفيش حالة unknown خالص: %s" % ("نعم" if "unknown" not in counts else "لأ!!"))
        for slug in SUSPECT:
            if slug in access:
                say("      %-18s مسموحة=%-5s حالة المخطوطة=%s"
                    % (slug, access[slug], states.get(slug) or "-"))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("written: %s (%s lines)" % (OUT, len(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
