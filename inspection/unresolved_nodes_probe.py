"""كل عقدة تفعيل في شجرة كل حساب + اللي هي اتحلت لعنصر ولا لأ.

    python inspection/unresolved_nodes_probe.py

العقدة اللي ما تتحلتش لـ slug واحد بتسيب الوصفة مخفية رغم إن اللعبة فتحتها — فدي
قايمة الغلط المحتم. بتطبع كمان أي عنصر في القاعدة اسمه فيه "energy clip" أو شبهه
عشان نعرف سبب الغموض.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, pioneer_tree, store  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_unresolved_nodes_out.txt")


def main():
    lines = []
    conn = store.db()
    accounts = [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]

    for name in accounts:
        rows = knowledge.unlocked(conn, name)
        unresolved = [r for r in rows if not r.get("slug")]
        lines.append("== %s | عقد=%s | بيتحلو=%s | غامض/محلوش=%s"
                     % (name, len(rows), len(rows) - len(unresolved), len(unresolved)))
        for row in unresolved:
            lines.append("   غامض: %-34s gates=%s assets=%s"
                         % (row.get("name"), row.get("gates"), row.get("assets")))

    lines.append("")
    lines.append("== أسماء في القاعدة فيها clip/energy")
    for row in items_db.craftable_rows():
        label = str(row.get("name") or "")
        if "clip" in items_db.norm(label) or "energy" in items_db.norm(label):
            lines.append("   %-32s %-28s locked=%s assets=%s"
                         % (row.get("slug"), label, row.get("blueprint_locked"),
                            row.get("asset_ids")))

    lines.append("")
    lines.append("== الفهرس: أي أصل اسمه فيه Energy Clip")
    for asset_id, info in sorted(pioneer_tree.asset_names().items()):
        label = str(info.get("display_name") or info.get("game_asset_name") or "")
        if "energy clip" in items_db.norm(label):
            lines.append("   %-14s %-40s -> %s" % (asset_id, label, knowledge.unlock_target(label)))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("written: %s (%s lines)" % (OUT, len(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
