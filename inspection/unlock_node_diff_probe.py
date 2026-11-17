"""قراءة واحدة من البوابة لكل حساب (GET /v1/pioneer/inventory) ومقارنة عقد التفعيل.

السؤال: إيه اللي بيفرق المفعل عن غير المفعل بالظبط؟ مخرج بس:
  - لكل حساب: عدد العقد العائمة (بره أي حاوية) وأسماءها وأرقام أصولها وحقولها الخام.
  - مطابقة أصل العقدة مع أصل العنصر في items_db (لو هما نفس الرقم، الإثبات يبقى
    بـ asset id مش بالاسم، وده بيشوف حتى العقد اللي الفهرس ما اسمهاش).
  - فرق الحسابين على نفس العقدة.

ممنوع أي كتابة — المسار GET فقط، والتوكن بياخده pioneer_client من القاعدة.
"""
import builtins
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, pioneer_client as pc, pioneer_tree, store  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_node_diff_out.txt")
ACCOUNTS = ["RAIDER38830", "G22", "RAIDER74888", "G18"]


def asset_to_items():
    out = {}
    for slug, row in (items_db._load().get("items") or {}).items():
        for a in row.get("asset_ids") or []:
            out.setdefault(str(a), []).append((slug, row.get("name")))
    return out


def main():
    lines = []
    say = lambda *a: lines.append(" ".join(str(x) for x in a))  # noqa: E731
    by_asset = asset_to_items()
    craft_names = {items_db.norm(r.get("name") or ""): r["slug"] for r in items_db.craftable_rows()}
    conn = store.db()

    for acc in ACCOUNTS:
        say("\n" + "=" * 70)
        say(f"== {acc}")
        try:
            data = pc.fetch_inventory_for(acc)
        except Exception as exc:  # noqa: BLE001 - القياس بيتقطّع بالتوكن
            say("   READ FAILED:", type(exc).__name__, str(exc)[:200])
            continue
        items = (data or {}).get("items") or []
        tree = pioneer_tree.Tree(items)
        floating = [iid for iid in tree.by_id if not tree.parent.get(iid)]
        say(f"   instances={len(tree.by_id)} floating={len(floating)}")
        unlock = []
        for iid in floating:
            entry = tree.by_id[iid]
            label = (tree.name_of(iid) or "").strip()
            if label.startswith("Unlock Craft "):
                unlock.append((label[len("Unlock Craft "):].strip(), str(entry.get("gameAssetId")), entry))
        say(f"   عقد Unlock Craft مرئية بالاسم = {len(unlock)}")
        same_asset = 0
        for _name, aid, _e in unlock:
            if aid in by_asset:
                same_asset += 1
        say(f"   أصل العقدة = أصل عنصر معروف في items_db: {same_asset}/{len(unlock)}")
        say("   نموذج 3 عقد خام (كل الحقول):")
        for name, aid, entry in unlock[:3]:
            say("     ", json.dumps(entry, ensure_ascii=False)[:400], "| باسم:", name,
                "| عناصر بنفس الأصل:", by_asset.get(aid))
        # أسماء العقد اللي بتطابق وصفات تصنيع بالاسم مباشرة
        hit = [(n, a) for n, a, _e in unlock if items_db.norm(n) in craft_names]
        say(f"   عقد بأسماء بيطابقوا وصفات تصنيع ({len(hit)}): "
            + json.dumps([(n, craft_names[items_db.norm(n)] if False else craft_names[items_db.norm(n)])
                          for n, _a in hit], ensure_ascii=False))
        # العائم اللي مالوش اسم في الفهرس: هل أصله = أصل وصفة؟
        unnamed = []
        for iid in floating:
            entry = tree.by_id[iid]
            if (tree.name_of(iid) or "").strip():
                continue
            aid = str(entry.get("gameAssetId"))
            if aid in by_asset:
                unnamed.append((aid, by_asset[aid], entry.get("amount")))
        say(f"   عائم بلا اسم في الفهرس بس أصله معروف ({len(unnamed)}): "
            + json.dumps(unnamed, ensure_ascii=False)[:1200])
        rows = knowledge.unlocked(conn, acc)
        say(f"   المحفوظ من آخر مزامنة: rows={len(rows)} measured={knowledge.unlock_measured(conn, acc)}")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    builtins.print("wrote", OUT)


if __name__ == "__main__":
    main()
