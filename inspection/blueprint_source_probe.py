# -*- coding: utf-8 -*-
"""فحص قراءة فقط: فين حالة "البلوبرنت اتفعّل" جوه شجرة البوابة الرسمية؟

    python inspection/blueprint_source_probe.py RAIDER38830

بترد على 3 أسئلة بالمقاس لايف:
 1) أي عقد اسمها فيه blueprint/recipe/knowledge/research/learn/unlock/collect؟
 2) كام عقدة "عائمة" (مش تحت أي حاوية) — دي المرشح الوحيد لعلامة "مفعّل".
 3) البلوبرنتات اللي في stash مقابل اللي مش موجودة — إيه اللي بيطابق عدّاد اللعبة؟
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree, store  # noqa: E402

NEEDLES = ("blueprint", "recipe", "knowledge", "research", "learn", "unlock",
           "collect", "journal", "codex", "tech", "perk", "skill")

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "RAIDER38830"


def main():
    inv = pc.fetch_inventory_for(ACCOUNT) or {}
    tree = pioneer_tree.Tree(inv.get("items") or [])
    lay = pioneer_tree.layout(tree)
    print("الحساب: %s | عقد الشجرة: %d" % (ACCOUNT, len(tree.items)))

    keys = set()
    for e in tree.items:
        keys |= set(e)
    print("مفاتيح العقد:", sorted(keys))

    named = {}
    for iid, row in tree.by_id.items():
        nm = (tree.name_of(iid) or "").lower()
        hit = [n for n in NEEDLES if n in nm]
        if hit:
            named.setdefault(hit[0], []).append((iid, row))
    print("\n=== عقد بأسماؤها فيها كلمات الدلالة ===")
    for k in sorted(named):
        rows = named[k]
        print("%-10s: %d" % (k, len(rows)))
        for iid, row in rows[:6]:
            print("    ", tree.name_of(iid), "| asset", row.get("gameAssetId"),
                  "| amount", row.get("amount"), "| slots",
                  len(row.get("slots") or []))

    reachable = set()
    roots = [str((lay.get(n) or {}).get("container") or "")
             for n in ("stash", "overflow", "backpack")]
    stack = [r for r in roots if r]
    stack += [str(iid) for iid, row in tree.by_id.items()
              if (tree.name_of(iid) or "").lower().startswith("item slot")]
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        stack += [str(c) for c in (tree.by_id.get(cur, {}).get("slots") or [])]
    loose = [iid for iid in tree.by_id if iid not in reachable]
    print("\n=== عقد خارج الحاويات: %d ===" % len(loose))
    for iid in loose[:25]:
        print("    ", tree.name_of(iid), "| asset", tree.by_id[iid].get("gameAssetId"))

    db = json.load(open(r"C:\Users\Administrator\Desktop\rr\data\items_db.json",
                        encoding="utf-8"))
    bp = {str(a): v for v in db["items"].values()
          if (v.get("is_blueprint") or (v.get("group") or "").lower() == "blueprints")
          for a in (v.get("asset_ids") or [])}
    owned = set(str(r.get("gameAssetId")) for r in tree.items)
    print("\n=== مطابقة قائمة البلوبرنتات (%d asset) ===" % len(bp))
    print("موجودة في الشجرة:", len(owned & set(bp)))
    print("غير موجودة في الشجرة:", len(set(bp) - owned))
    with store.db() as conn:
        from backend import knowledge
        owned = knowledge.owned_map(conn, ACCOUNT)
        st = knowledge.blueprint_state(conn, ACCOUNT, owned)
        print("\n=== طبقة knowledge الحالية (مصدر الموقع دلوقتي) ===")
        print(json.dumps(knowledge.summary(conn, ACCOUNT, owned), ensure_ascii=False)[:600])
        print("توزيع الحالات:", {k: sum(1 for v in st.values() if v == k)
                                  for k in ("learned", "in_stash", "never_found")})


if __name__ == "__main__":
    main()
