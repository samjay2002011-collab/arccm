# -*- coding: utf-8 -*-
"""يبني data/craft_catalog.json: رقم عرض التصنيع الرسمي لكل وصفة في items_db.

المصدر: data/craft_offers_source.json — كتالوج `type: "crafting"` اللي اتسحب من المتصفح
(317 عرضًا، كل عرض بـ offer_id + المحطة + الخامات + المنتج). دول نفس أرقام العروض اللي
بتشتغل على بوابة Embark الرسمية عبر POST /v1/pioneer/offers/accept (مقيس لايفًا).

الربط: أولًا بـ asset_id بتاع المنتج، ولو ملوش بيطابق بالاسم المطبّع. من المرشحين
بتختار المحطة اللي الوصفة بتاعتها، وأقل مستوى محطة، وأصغر offer_id — عشان الاختيار
يبقى ثابت بين تشغيلين. بنسجّل كمان هل خامات العرض مطابقة لخامات الوصفة المحليّة.

    python -m inspection.build_craft_catalog
"""
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "craft_offers_source.json")
ITEMS = os.path.join(ROOT, "data", "items_db.json")
OUT = os.path.join(ROOT, "data", "craft_catalog.json")
VERSION = 1


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def offers_by_bench(offers):
    out = {}
    for row in offers:
        out.setdefault(row.get("bench_key"), []).append(row)
    return out


def main():
    source = json.load(open(SRC, encoding="utf-8"))
    items = json.load(open(ITEMS, encoding="utf-8"))["items"]
    offers = []
    for rows in (source.get("grouped_offers") or {}).values():
        offers.extend(rows)

    by_asset, by_name = {}, {}
    for offer in offers:
        by_asset.setdefault(str((offer.get("reward") or {}).get("asset_id")), []).append(offer)
        by_name.setdefault(norm((offer.get("reward_meta") or {}).get("display_name")), []).append(offer)

    used = set()
    recipes = {}
    unmatched = []
    for slug, row in items.items():
        if not row.get("recipe"):
            continue
        ids = {str(a) for a in (row.get("asset_ids") or [])}
        candidates = [o for i in ids for o in by_asset.get(i, [])] or \
            by_name.get(norm(row.get("name")), [])
        if not candidates:
            unmatched.append(row.get("name"))
            continue
        wanted = set(row.get("craft_bench") or [])
        stations = sorted(wanted)

        def rank(o):
            return (0 if o.get("bench_key") in wanted else 1,
                    int(o.get("station_level") or 0),
                    stations.index(o.get("bench_key")) if o.get("bench_key") in stations else 9,
                    int(o.get("offer_id") or 0))

        offer = sorted(candidates, key=rank)[0]
        used.add(str(offer.get("offer_id")))
        cost = [{"asset_id": str(c.get("asset_id")),
                 "name": (c.get("meta") or {}).get("display_name"),
                 "amount": int(c.get("amount") or 0)} for c in offer.get("cost") or []]
        local = {str((m.get("asset_ids") or [""])[0]): int(m.get("qty") or 0)
                 for m in row.get("recipe") or []}
        gateway = {c["asset_id"]: c["amount"] for c in cost}
        recipes[slug] = {
            "offer_id": int(offer["offer_id"]),
            "bench_key": offer.get("bench_key"),
            "bench_name": offer.get("bench_name"),
            "station_level": int(offer.get("station_level") or 0),
            "reward_asset_id": str((offer.get("reward") or {}).get("asset_id")),
            "reward_amount": int((offer.get("reward") or {}).get("amount") or 1),
            "limit": int(offer.get("limit") or 0),
            "cost": cost,
            "cost_match": local == gateway,
            "matched_by": "asset_id" if any(i in by_asset for i in ids) else "name",
        }

    payload = {
        "version": VERSION,
        "built_at": int(time.time()),
        "source": "api.rampart.su/crafts/offers (type: crafting) — مسحب من المتصفح، "
                  "والتنفيذ على بوابة Embark الرسمية",
        "accept_path": "/v1/pioneer/offers/accept",
        "stats": {
            "offers_total": len(offers),
            "recipes_total": sum(1 for r in items.values() if r.get("recipe")),
            "mapped": len(recipes),
            "unmapped": len(unmatched),
            "cost_mismatch": sum(1 for v in recipes.values() if not v["cost_match"]),
        },
        "benches": source.get("benches") or [],
        "unmapped_recipes": sorted(unmatched),
        "recipes": recipes,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=1))
    print("غير مطابقة:", len(payload["unmapped_recipes"]), payload["unmapped_recipes"][:12])
    print("مواقع لم تُستخدم بعد:", len(offers) - len(used), "من", len(offers))
    print("الملف:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
