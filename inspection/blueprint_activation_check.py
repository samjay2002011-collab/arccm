"""فحص حالة التفعيل بعد الإصلاح — قراءة بس، من غير أي طلب للبوابة.

    python inspection/blueprint_activation_check.py

بيرجّع لكل حساب: عدد عقد القفل المقروءة، توزيع حالات الـ ٩١ مخطوطة، وأي "learned"
بلا دليل (لا عقدة في شجرة الحساب ولا تحديد يدوي) — وده بالظبط الغلط اللي كان.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, store, workshop  # noqa: E402


def main():
    conn = store.db()
    accounts = [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]
    gated = knowledge.gated_slugs()
    print("عقد التفعيل في الفهرس المحلي: %s اسم | عناصر ليها احتمال دليل: %s"
          % (len(knowledge.unlock_universe()), len(gated)))
    bad_total = 0
    hidden_total = 0
    for name in accounts:
        rows = knowledge.unlocked(conn, name)
        owned = knowledge.owned_map(conn, name)
        states = knowledge.blueprint_state(conn, name, owned, knowledge.owned_map(conn, name))
        counts = {}
        for value in states.values():
            counts[value] = counts.get(value, 0) + 1
        stray = sorted(set(states.values()) - {"learned", "in_stash", "not_learned"})
        proven_slugs = {str(r.get("slug") or "") for r in rows} - {""}
        proven_assets = {str(a) for r in rows for a in (r.get("assets") or [])}
        proven_names = {items_db.norm(str(r.get("name") or "")) for r in rows} - {""}
        data = knowledge._get(conn, name)
        forced = set(data.get("learned") or [])
        unjustified = []
        for target, value in states.items():
            if value != "learned":
                continue
            tgt = items_db.by_slug(target) or {}
            assets = {str(a) for a in (tgt.get("asset_ids") or [])}
            if (target in proven_slugs or (assets & proven_assets)
                    or items_db.norm(tgt.get("name") or "") in proven_names or target in forced):
                continue
            unjustified.append(target)
        bad_total += len(unjustified)
        access = knowledge.craft_access(conn, name, owned)
        visible = {str(r.get("slug")) for r in workshop.recipes(conn, name)}
        leaked = sorted(s for s in visible if not access.get(s))
        hidden_total += len(leaked)
        allowed = sum(1 for ok in access.values() if ok)
        print("%-14s measured=%-5s nodes=%-3s %s learned-bla-dalil=%s مسموحة=%s/كل=%s مخفية=%s تسرب=%s حالات-غريبة=%s"
              % (name, knowledge.unlock_measured(conn, name), len(rows),
                 " ".join("%s=%s" % (k, counts.get(k, 0)) for k in
                          ("learned", "in_stash", "not_learned")),
                 len(unjustified), allowed, len(access), len(access) - allowed, len(leaked), stray))
        if unjustified:
            print("        ", unjustified)
        if leaked:
            print("         متظاهرة رغم منع البوابة:", leaked)
        if name.startswith("RAIDER38830"):
            print("         snap_hook ->", states.get("snap_hook"), "| tether_launcher ->",
                  states.get("tether_launcher"), "| zipline ->", access.get("zipline"))
    print("الإجمالي: learned بلا دليل=%s (لازم صفر) | وصفة ظاهرة وهي ممنوعة=%s (لازم صفر)"
          % (bad_total, hidden_total))
    return 0 if not bad_total and not hidden_total else 1


if __name__ == "__main__":
    sys.exit(main())
