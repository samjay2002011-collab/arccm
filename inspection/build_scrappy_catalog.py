# -*- coding: utf-8 -*-
"""يبني data/scrappy_catalog.json من الكتالوج الرسمي: عروض الديك بكل مستوياته.

المصدر: `GET /v1/pioneer/game-data` -> `offer-descriptions.offerDescriptions`، وده
كتالوج Embark الرسمي نفسه اللي بيقرؤه اللانشر — من غير أي سيرفر وسيط ولا قراءة
ذاكرة. بنفلتر `offerType == "RoundCrafting"` (38 عرضًا) ونربط كل عرض بمستوى الديك
من `ownerGameAssetId` (`DA_Item_ResourceGenerator_01..05`)، وبنحل أسماء الأيقونات
من catalog المحلي زي ما بقية الصفوات بتعمل.

النوعان (بالقياس على البوابة 2026-11-01):
  • kind="food":   تكلفة `cost.itemAmounts` = زراعة x1 -> قرعة من pool، مدة 360s.
                   ده النوع الوحيد اللي `offers/accept` بيينفّذه فعلًا (خصم الخامة
                   وعمل transaction برقم عرض وstartTime).
  • kind="rounds": تكلفة `requiredItems` = Rounds Played x1 و`cost.itemAmounts` فاضي.
                   كل أجسام القبول اترفضت 400 internal error على ثلاث حسابات بمستويات
                   مختلفة — القياس إن `offers/accept` ما بيشغّرش العروض اللي تكلفة
                   `cost.itemAmounts` فاضية، فدي قراءة للمواعيد مش تنفيذ.

    python -m inspection.build_scrappy_catalog
"""
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_DATA = os.path.join(ROOT, "data", "pioneer_game_data.json")
OUT = os.path.join(ROOT, "data", "scrappy_catalog.json")
VERSION = 1


def gen_table():
    return {1: ("1657228973", "Scrappy I"), 2: ("2041317243", "Scrappy II"),
            3: ("1434069496", "Scrappy III"), 4: ("2080275953", "Scrappy IV"),
            5: ("1781867314", "Scrappy V")}


def upgrade_chain(docs, resolve, gens):
    """مسار ترقية الديك من وصف العناصر الرسمي: كل مستوى وتكلفة نقله للي فوقه."""
    by_id = {str(row.get("gameAssetId")): row for row in docs["items-description"]["itemDescriptions"]}
    label_of = {asset_id: label for asset_id, label in gens.values()}
    out = []
    for tier, (asset_id, label) in sorted(gens.items()):
        up = (by_id.get(asset_id) or {}).get("upgrade") or {}
        nxt = str(up.get("nextItemGameAssetId") or "")
        out.append({
            "tier": tier,
            "asset_id": asset_id,
            "label": label,
            "next_asset_id": nxt if nxt not in ("", "0") else "",
            "next_label": label_of.get(nxt, ""),
            "cost": [{**resolve(c["gameAssetId"]), "amount": int(c["amount"] or 0)}
                     for c in (up.get("cost") or {}).get("itemAmounts") or []],
        })
    return out


def main():
    import sys
    sys.path.insert(0, ROOT)
    from backend import catalog, pioneer_tree

    names = pioneer_tree.asset_names()
    docs = json.load(open(GAME_DATA, encoding="utf-8"))
    offers = docs["offer-descriptions"]["offerDescriptions"]
    tier_of = {str(a): t for t, (a, _label) in gen_table().items()}

    def resolve(asset_id):
        aid = str(asset_id)
        row = (names.get(aid) or {})
        label = row.get("display_name") or row.get("game_asset_name") or aid
        image = catalog.icon_of(catalog.arctracker_lookup(label)) or ""
        return {"asset_id": aid, "name": label, "image": image}

    def pool_of(offer):
        """عروض الزراعة مكافأتها قرعة من pool — بنطلّع الأسماء المحتملة بوزنها."""
        pools = ((offer.get("rewardPackage") or {}).get("randomRewards") or {}).get("pools") or []
        out, seen = [], set()
        for bucket in pools:
            for item in bucket.get("items") or []:
                aid = str(item.get("gameAssetId"))
                if aid in seen:
                    continue
                seen.add(aid)
                out.append({**resolve(aid), "amount": int(item.get("amount") or 0),
                            "weight": round(float(item.get("weight") or 0), 4)})
        out.sort(key=lambda r: (-r["weight"], r["name"].lower()))
        return out

    rows = []
    for offer in offers:
        if offer.get("offerType") != "RoundCrafting":
            continue
        tier = int(tier_of.get(str(offer.get("ownerGameAssetId"))) or 0)
        reward = [{**resolve(r["gameAssetId"]), "amount": int(r["amount"] or 0)}
                  for r in (offer["rewardPackage"] or {}).get("rewardedItems") or []]
        cost = [{**resolve(c["gameAssetId"]), "amount": int(c["amount"] or 0)}
                for c in (offer["cost"] or {}).get("itemAmounts") or []]
        required = [{**resolve(r["itemGameAssetId"]), "amount": int(r["amount"] or 0)}
                    for r in offer.get("requiredItems") or []]
        pool = pool_of(offer)
        rows.append({
            "offer_id": int(offer["offerId"]),
            "tier": tier,
            "kind": "rounds" if required else ("food" if cost else "unknown"),
            "title": offer.get("title") or "",
            "duration_seconds": int(offer.get("durationInSeconds") or 0),
            "order_index": int(offer.get("orderIndex") or 0),
            "cost": required or cost,
            "reward": reward,
            "reward_pool": pool,
            "reward_total": sum(r["amount"] for r in reward),
        })

    rows.sort(key=lambda r: (r["tier"], r["duration_seconds"], r["order_index"]))
    tiers = upgrade_chain(docs, resolve, gen_table())
    payload = {
        "version": VERSION,
        "built_at": int(time.time()),
        "source": "GET /v1/pioneer/game-data -> offer-descriptions (offerType RoundCrafting) "
                  "— الكتالوج الرسمي نفسه، من غير أي وسيط",
        "accept_path": "/v1/pioneer/offers/accept",
        "rounds_asset": "-1869396984",
        "generators": [{"tier": t, "asset_id": a, "label": label}
                       for t, (a, label) in sorted(gen_table().items())],
        "upgrades": tiers,
        "stats": {"offers": len(rows),
                  "rounds": sum(1 for r in rows if r["kind"] == "rounds"),
                  "food": sum(1 for r in rows if r["kind"] == "food"),
                  "tiers": sorted({r["tier"] for r in rows})},
        "offers": rows,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(json.dumps(payload["stats"], ensure_ascii=False))
    for row in rows[:6]:
        print(row["tier"], row["kind"], row["offer_id"], row["duration_seconds"],
              row["title"][:34], "| cost", [(c["name"], c["amount"]) for c in row["cost"]],
              "| reward", row["reward_total"])
    print("الملف:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
