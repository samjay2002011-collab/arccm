"""تسمية مجهول بمقارنة «أين يسمح بوضعه» مع مرشح معروف.

البصمة الرقمية (سعة + قيمة الخردة) بتسيب أكتر من اسم على بعض. رد اللعبة الرسمي
فيه حاجة تانية مقارِنة: كل حاوية (InventoryStructure/OutpostSlot) بتحدد
`slotConfig.allowedSlotAssetIds` — ومجموعة الحاويات اللي بتسمح بأصل معيّن بصمة
شكلها ثابت لكل قطعة. لو مجهول بيفصّل نفس مجموعة حاويات مرشح بالظبط، يبقى نسخة
من نفس القطعة (زي ما كان happen مع Mask Fragment و Design بتاع Aviary Table).

قراءة بس.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config  # noqa: E402

GAME = os.path.join(config.DATA_DIR, "pioneer_game_data.json")
ITEMS = os.path.join(config.DATA_DIR, "items_db.json")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "-486136037"
    data = json.load(open(GAME, encoding="utf-8"))
    rows = (data.get("items-description") or {}).get("itemDescriptions") or []
    info = {str(r.get("gameAssetId")): r for r in rows}

    homes = {}
    for r in rows:
        allowed = ((r.get("slotConfig") or {}).get("allowedSlotAssetIds")) or []
        for aid in allowed:
            homes.setdefault(str(aid), set()).add(str(r.get("gameAssetId")))

    mine = homes.get(str(target))
    if mine is None:
        print(target, "مش موجود في أي قائمة حاويات — البصمة دي مفيش منها حاجة")
        raise SystemExit(0)
    print(f"{target} مسموح بيه في {len(mine)} حاوية")

    rec = info.get(str(target)) or {}
    stack = int(rec.get("maxAmount") or 0)
    scrap = 0
    for it in (((rec.get("scrap") or {}).get("rewardPackage") or {}).get("rewardedItems") or []):
        if str(it.get("gameAssetId")) == "-898439395":
            scrap = int(it.get("amount") or 0)

    items = json.load(open(ITEMS, encoding="utf-8")).get("items") or {}
    scored = []
    for r in items.values():
        if int(r.get("stack_size") or 0) != stack or int(r.get("value") or 0) != scrap:
            continue
        for other in (r.get("asset_ids") or []):
            oh = homes.get(str(other))
            if oh is None:
                continue
            same = len(oh & mine) == len(oh | mine)
            jac = len(oh & mine) / max(1, len(oh | mine))
            scored.append((jac, same, r.get("name"), str(other), len(oh)))
    scored.sort(reverse=True)
    exact = [s for s in scored if s[1]]
    print(f"\nمرشح بنفس البصمة الرقمية: {len(scored)}")
    for s in scored[:12]:
        print(f"  تشابه {s[0]:.2f}{'  ← مطابق بالظبط' if s[1] else ''} | {s[2]} | id {s[3]} | حاوياته {s[4]}")
    if len(exact) == 1:
        print(f"\nالنتيجة: {target} = {exact[0][2]}")
    elif exact:
        print(f"\nفي {len(exact)} مرشح مطابق — محتاج دليل إضافي.")
    else:
        print("\nمافيش تطابق كامل.")


if __name__ == "__main__":
    main()
