"""العناصر اللي arctracker بيقول ملهاش مخطوطة لكن اللعبة نفسها ليها عقدة تفعيل.

    python inspection/node_only_recipes_probe.py

لازم نعرفهم بالظبط: دول اللي الفلترة الصارمة بتخفيهم لو العقدتهم مش في شجرة الحساب،
فأي واحد فيهم الرايدر بيفتحه جوه اللعبة يحتاج مخرج تحديد يدوي.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_node_only_recipes_out.txt")


def main():
    lines = []
    recipes = {str(r.get("slug")): r for r in items_db.craftable_rows()}
    targets = {str(row.get("target")) for row in items_db.blueprint_rows() if row.get("target")}
    universe = knowledge.unlock_universe()
    gated = knowledge.gated_slugs()

    free_with_node = sorted(gated & {s for s, r in recipes.items() if not r.get("blueprint_locked")})
    lines.append("ملهاش قفل في arctracker + ليها عقدة تفعيل في الفهرس: %s" % len(free_with_node))
    for slug in free_with_node:
        row = recipes[slug]
        lines.append("  %-32s مخطوطة=%-6s محطة=%-16s مستوى=%s بحث=%s في الـ 91=%s"
                     % (slug, bool(row.get("related_blueprint_id")),
                        ",".join(row.get("stations") or []), row.get("station_level"),
                        bool(row.get("research_perk")), slug in targets))

    node_slugs = sorted({str(ref.get("slug")) for ref in universe.values() if ref.get("slug")})
    only_nodes = [s for s in node_slugs if s not in targets]
    lines.append("")
    lines.append("عقدة تفعيل بس من غير مخطوطة في الـ 91 (محتاج مخرج يدوي): %s" % len(only_nodes))
    for slug in only_nodes:
        row = items_db.by_slug(slug) or {}
        lines.append("  %-32s %s | locked=%s | bench=%s"
                     % (slug, row.get("name"), row.get("blueprint_locked"),
                        ",".join(str(b) for b in (row.get("craft_bench") or []))))

    lines.append("")
    lines.append("عقد غامضة (بتغطي أكتر من عنصر أو ملهاش slug): ")
    for key, ref in sorted(universe.items(), key=lambda kv: kv[1]["name"]):
        if ref.get("slug") or len(ref.get("gates") or []) > 1:
            lines.append("  %-34s gates=%s" % (ref["name"], json.dumps(ref.get("gates"), ensure_ascii=False)))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("written: %s (%s lines)" % (OUT, len(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
