"""تضييق المجهول ببصمة أعمق: (سعة + قيمة الخردة + شكل الريسايكل/الترميم/الأبجراد).

البصمة القديمة كانت (stack, scrap-value) وبس، فبعض الـ ids بتفضل مشتركة بين
كذا اسم. رد اللعبة الرسمي معاه كمان `recycle.rewardedItems` و`repair.costItems`
و`upgrade.nextItemGameAssetId` — ودي حاجات arctracker بيغطيها بـ
`recycles_into` / `salvages_into` / `upgrade_cost`. بنعاير التطابق الأول على
كل الـ ids المعروفة، وبعدين بس نطبق البصمة الكاملة على المجهول.

قراءة بس. مافيش أي كتابة للمتجر ولا للعبة.
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config  # noqa: E402

GAME = os.path.join(config.DATA_DIR, "pioneer_game_data.json")
ITEMS = os.path.join(config.DATA_DIR, "items_db.json")
INDEX = os.path.join(config.DATA_DIR, "catalog", "asset_index_local.csv")


def has_rewards(node):
    pkg = (node or {}).get("rewardPackage") or {}
    items = pkg.get("rewardedItems")
    if items:
        return True
    rnd = pkg.get("randomRewards") or {}
    return bool(rnd.get("pools")) or int(rnd.get("maxAmount") or 0) > 0


def fingerprint(rec):
    """البصمة الكاملة لسجل اللعبة الرسمي."""
    scrap = 0
    pkg = ((rec or {}).get("scrap") or {}).get("rewardPackage") or {}
    for it in (pkg.get("rewardedItems") or []):
        if str(it.get("gameAssetId")) == "-898439395":
            scrap = int(it.get("amount") or 0)
    return {
        "stack": int((rec or {}).get("maxAmount") or 0),
        "scrap": scrap,
        "recycle": has_rewards((rec or {}).get("recycle")),
        "upgrade": int(((rec or {}).get("upgrade") or {}).get("nextItemGameAssetId") or 0),
    }


def main():
    game = json.load(open(GAME, encoding="utf-8"))
    rows = (game.get("items-description") or {}).get("itemDescriptions") or []
    info = {str(r.get("gameAssetId")): r for r in rows}

    db = json.load(open(ITEMS, encoding="utf-8"))
    items = db.get("items") or {}

    # الـ slugs اللي فات مربوطة بـ asset id تاني معناها معروف اسمُه —
    # دي اللي بتستبعد نفسها من الترشيح (زي ما حصل مع Mask Fragment).
    pinned = set()
    if os.path.isfile(INDEX):
        with open(INDEX, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                aid = str(row.get("game_asset_id") or "").strip()
                nm = (row.get("display_name") or row.get("game_asset_name") or "").strip()
                if aid and nm and not re.match(r"^Item -?\d+$", nm):
                    pinned.add(aid)
    for aid, slug in (db.get("by_asset") or {}).items():
        if str(aid) in pinned:
            continue

    # ---- معايرة: items_db فيه asset_ids لكل اسم. بنطابق البصمة ----
    agree = {"recycle": [0, 0], "upgrade": [0, 0]}
    for slug, r in items.items():
        for aid in (r.get("asset_ids") or []):
            g = info.get(str(aid))
            if not g or g.get("itemType") != "GameItem":
                continue
            fp = fingerprint(g)
            agree["recycle"][1] += 1
            if fp["recycle"] == bool(r.get("recycles_into")):
                agree["recycle"][0] += 1
            agree["upgrade"][1] += 1
            if bool(fp["upgrade"]) == bool(r.get("upgrade_cost") or r.get("upgrades_to")):
                agree["upgrade"][0] += 1

    print("المعايرة على ids من items_db:")
    for k, (a, t) in agree.items():
        print(f"  {k}: متطابق {a}/{t}")

    # ---- المجهول المطلوب ----
    todo = sys.argv[1:] or ["-486136037", "1817122194"]
    for aid in todo:
        g = info.get(aid)
        if not g:
            print(aid, "مالوش سجل في رد اللعبة")
            continue
        fp = fingerprint(g)
        cands = []
        for slug, r in items.items():
            if int(r.get("stack_size") or 0) != fp["stack"]:
                continue
            if int(r.get("value") or 0) != fp["scrap"]:
                continue
            if bool(r.get("recycles_into")) != fp["recycle"]:
                continue
            if bool(r.get("upgrade_cost") or r.get("upgrades_to")) != bool(fp["upgrade"]):
                continue
            others = [str(x) for x in (r.get("asset_ids") or []) if str(x) != str(aid)]
            claimed = [x for x in others if x in pinned]
            cands.append((slug, r.get("name"), r.get("rarity"), r.get("type"),
                          "مثبّت على " + ",".join(claimed) if claimed else "غير مثبّت"))
        print(f"\n{aid} بصمة {fp}")
        print(f"  مرشح بعد البصمة الكاملة: {len(cands)}")
        for c in cands:
            print("   ", c)


if __name__ == "__main__":
    main()
