# -*- coding: utf-8 -*-
"""فين بتروح القطعة فعليًا لما أحطها في الشنطة من الموقع؟ (قراءة بس، من غير كتابة)

بيطبع لكل حساب:
  1) المؤشر المجهّز (equipped loadout container slot) بيشاور على أي حاوية، وعدد خاناتها ومحتواها.
  2) كل شجرة loadout في الشجرة: اسمها، عدد العناصر جواها، وآخر تحديث، وأي واحدة الموقع بيختارها.
  3) الحاوية الي الموقع بيكتب فيها فعلًا (layout()["backpack"]) وعدد الخانات الي بتعرضها الصفحة.
  4) آخر كتابات mutate من سجل الأكشنز: كل خانة اتكتبت بتنتمي لأي حاوية، ومجهّزة ولا لأ.

لو الحاوية الي الموقع بيكتب فيها مش هي الي اللعبة مجهّزتها — دي بالضبط حالة
"حطيت حاجة في الشنطة، مش ظاهرة في الماتش، اختفت من الستاش، وظهرت لما رجعت من اللوبي".
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree as pt, store  # noqa: E402

ACCOUNTS = sys.argv[1:] or None


def root_of(tree, iid):
    """اسم العنصر الأب (الـ root) لأي عقدة — بنمشي الأباء لفوق."""
    cur = iid
    seen = set()
    while cur and cur in tree.by_id and cur not in seen:
        seen.add(cur)
        parent = tree.parent.get(cur) or ""
        if not parent:
            break
        cur = parent
    return cur


def describe(tree, label_iid):
    if not label_iid:
        return "— (مفيش)"
    cells = [w for w in tree.children(label_iid) if (tree._row(w) or {}).get("slots") is not None]
    filled = pt._filled_items(tree, label_iid)
    return "%s | خانات=%s | عناصر جواها=%s | آخر تحديث=%s" % (
        tree.label(label_iid) or label_iid[:8], len(cells), filled, tree.subtree_updated(label_iid))


def main():
    conn = store.db()
    names = ACCOUNTS or [r["name"] for r in conn.execute(
        "SELECT name FROM accounts WHERE enabled=1 ORDER BY name").fetchall()]
    for name in names:
        print("=" * 78)
        print("حساب: %s" % name)
        try:
            data = pc.fetch_inventory_for(name) or {}
        except Exception as exc:
            print("  تعذّر القراءة: %s" % exc)
            continue
        tree = pt.Tree(data.get("items") or [])
        inv = ""
        for r in tree.roots():
            if tree.label(r).lower() == "inventory root":
                inv = r
        if not inv:
            print("  مفيش Inventory Root")
            continue
        slot = tree.find_child(inv, "equipped loadout container slot")
        equipped = tree.first_child(slot)
        node, mode = pt._active_loadout(tree, inv)
        lay = pt.layout(tree)
        bp = lay["backpack"]
        print("  المجهّز (الموقع الي اللعبة بتستخدمه): %s" % describe(tree, equipped))
        print("  الموقع اختار (mode=%s):            %s" % (mode, describe(tree, node)))
        print("  حاوية الشنطة الي بنكتب فيها: %s | خانات معروضة=%s" % (
            tree.label(bp["container"]) or (bp["container"] or "")[:8], len(bp["slots"])))
        lo = lay["loadout"]
        print("  ⚠ الخانة المجهّزة بتتشاور على الحاوية الي بنكتب فيها؟ %s" % (
            "أيوه — الكتابة بتوصل للعبة" if lo.get("pointed")
            else "لأ! بنكتب في حاوية اللعبة مابتقرأهاش (بتفضل مخفية لحد ما يتوجّه الربط)"))
        print("  --- كل أشجار اللوداوت ---")
        for r in tree.roots():
            if r == inv or not tree.find_child(r, "backpack slot"):
                continue
            mark = "  <== الموقع بيختارها" if r == node else ""
            print("   %s%s" % (describe(tree, r), mark))
        # سجل آخر كتابات: الـ response فيه changeset بالخانات الي اتكتبت فعلًا
        rows = conn.execute(
            "SELECT ts, kind, request, response FROM actions WHERE account=? "
            "AND kind LIKE 'mutate%' ORDER BY ts DESC LIMIT 8", (name,)).fetchall()
        if rows:
            print("  --- آخر كتابات mutate (الخانات الي اتكتب فيها) ---")
            eq_root = root_of(tree, equipped) if equipped else ""
            for row in rows:
                cells = []
                try:
                    resp = json.loads(row["response"] or "{}")
                except Exception:
                    resp = {}
                for it in ((resp.get("changeset") or {}).get("items") or {}).get("updated") or []:
                    cell = str(it.get("instanceId") or "")
                    if cell not in tree.by_id:
                        continue
                    owner = root_of(tree, cell)
                    cells.append("%s%s" % ((tree.label(cell) or "?")[:12],
                                           "" if owner == eq_root else " ≠مجهّز"))
                try:
                    req = json.loads(row["request"] or "{}")
                except Exception:
                    req = {}
                ids = [str(x) for x in (req.get("ids") or [])]
                moved = []
                for iid in ids:
                    if iid not in tree.by_id:
                        moved.append("%s (مش في الشجرة)" % iid[:8])
                        continue
                    p = tree.parent.get(iid) or ""
                    moved.append("%s في %s" % ((tree.name_of(iid) or iid[:6])[:14],
                                               (tree.label(p) or p[:8])[:22]))
                line = " | ".join(moved) or (" ; ".join(cells[:4])) or str(json.loads(row["request"] or "{}")
                                                                            .get("target_container", ""))
                print("   %s %-16s %s" % (time_str(row["ts"]), row["kind"], line or "—"))
    conn.close()


def time_str(ts):
    import datetime
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except Exception:
        return "?"


if __name__ == "__main__":
    main()
