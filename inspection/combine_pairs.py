"""جرد حيّ لاحتمالات الدمج القانونية: رصتين من نفس النوع مجموعهم <= السقف = زرار COMBINE هيشتغل.

القراية من بوابة اللعبة نفسها (نسخة الـ DB بتبقى قديمة بعد أي دمج جوه اللعبة).
مسار: python inspection/combine_pairs.py [RAIDER38830 ...]
"""
import sys, os, collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import pioneer_client as pc, pioneer_tree as pt, store, items_db


def cap_for(conn, account, asset_id):
    try:
        cap = int(conn.execute("select max(stack_size) from instances where account=? and asset_id=?",
                               (account, str(asset_id))).fetchone()[0] or 0)
    except Exception:
        cap = 0
    if not cap:
        cap = int((items_db.dossier(asset_id=str(asset_id)) or {}).get("stack_size") or 0)
    return cap


def main():
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    conn = store.db()
    accounts = [r["name"] for r in conn.execute("select name from accounts order by name").fetchall()]
    if wanted:
        accounts = [a for a in accounts if a in wanted]
    shown = 0
    for account in accounts:
        try:
            data = pc.fetch_inventory_for(account)
            tree = pt.Tree((data or {}).get("items") or [])
        except Exception as exc:
            print("%-14s فشل القراية: %s" % (account, str(exc)[:120]))
            continue
        groups = collections.defaultdict(list)
        for iid, node in tree.by_id.items():
            aid = str(node.get("gameAssetId") or "")
            cell = tree.parent.get(iid, "")
            amount = int(node.get("amount") or 0)
            if not aid or not cell or amount <= 0:
                continue
            name = tree.name_of(iid) or ""
            if not name or name.lower().endswith("slot"):
                continue                        # دي خانات فاضية/أوعية، مش عناصر
            groups[(aid, cell_root(tree, cell))].append((iid, amount))
        rows = []
        for (aid, root), stacks in groups.items():
            cap = cap_for(conn, account, aid)
            if cap < 2 or len(stacks) < 2:
                continue
            legal = []
            for i, (sid, sq) in enumerate(stacks):
                for tid, tq in stacks:
                    if tid == sid or tq + sq > cap:
                        continue
                    legal.append((sq, sid, tq, tid))
            if not legal:
                continue
            legal.sort(key=lambda r: (-r[0], r[2]))
            sq, sid, tq, tid = legal[0]
            rows.append((len(legal), tree.name_of(sid), cap, sorted((s[1] for s in stacks), reverse=True),
                         sq, sid, tq, tid, root))
        rows.sort(key=lambda r: -r[0])
        print("\n== %s | %d نوع عنده دمج قانوني دلوقتي" % (account, len(rows)))
        for n, name, cap, amounts, sq, sid, tq, tid, root in rows[:14]:
            shown += 1
            print("   %-24s سقف %-4d | %s | دمج %d -> %d (%d)  [%d احتمال]  src=%s tgt=%s → %s"
                  % (name[:24], cap, "+".join(str(a) for a in amounts[:9]), sq, tq + sq, tq,
                     n, sid[:8], tid[:8], root))
        if not rows:
            print("   مفيش زوج مجموعهم وقع تحت السقف — كل الرصي كاملة.")
    conn.close()
    print("\nالإجمالي المعروض: %d" % shown)


def cell_root(tree, cell):
    """اسم الكونتينر اللي الخانة دي جواه (ستاش / شنطة / أوفر فلو) — عشان نعرف الدمج فين."""
    seen = set()
    cur = str(cell)
    while cur and cur not in seen:
        seen.add(cur)
        parent = tree.parent.get(cur, "")
        if not parent:
            label = (tree.name_of(cur) or cur).strip()
            return label if label else "أوفر فلو"
        cur = parent
    return "?"


if __name__ == "__main__":
    main()
