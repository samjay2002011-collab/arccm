# -*- coding: utf-8 -*-
"""معاينة زرار ⇄ من غير أي كتابة: يبعت dry=1 لكل حساب ويطبع الخطة.

القراءة بس (fetch_inventory_for) — مفيش mutate خالص.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from backend import actions, config, store  # noqa: E402


def main():
    conn = store.db()
    try:
        accounts = [r["account"] for r in
                    conn.execute("SELECT DISTINCT account FROM instances ORDER BY account").fetchall()]
    finally:
        conn.close()
    for account in accounts:
        conn = store.db()
        try:
            out = actions.merge_all(conn, account, dry=True)
        finally:
            conn.close()
        plan = out.get("merge_all") or {}
        s = plan.get("summary") or out.get("summary") or {}
        print("\n=== %s ===" % account)
        print("reason=%s executed=%s %s" % (out.get("reason") or out.get("error"),
                                            out.get("executed"), out.get("detail", "")[:160]))
        if not s:
            continue
        print("assets=%s owed=%s drags=%s moves=%s free=%s no_cap=%s cells=%s"
              % (s.get("assets"), s.get("owed"), s.get("drags"), s.get("moves"),
                 s.get("free"), s.get("no_cap"), s.get("stash_cells")))
        for g in (plan.get("owed") or [])[:12]:
            print("  %-28s cap=%-4s %s -> %s  drags=%s stash=%s ovf=%s mv=%s"
                  % (g["name"][:28], g["cap"], g["amounts"], g["ideal"],
                     g["drags"], g["in_stash"], g["in_overflow"], len(g["moves"])))
        for mv in (plan.get("moves") or [])[:6]:
            print("  move", mv)


main()
