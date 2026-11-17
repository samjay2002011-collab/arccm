"""يحدّث data/augments_specs.json من جدول augments في arcraiders.wiki (Cargo).

الأرقام: backpack / quick_use / safe_pocket من الويكي مباشرة، و augmented =
مجموع الخانات المتخصصة (healing + grenade + trinket + utility) لأن الويكي
بيفصلها بينما واجهة اللعبة بتعرضها كقسم AUGMENTED واحد.
التشغيل: python inspection/sync_augment_specs.py
"""
import json
import os
from datetime import date

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

API = "https://arcraiders.wiki/w/api.php"
HEADERS = {"User-Agent": "FahmyLocalMirror/1.0 (read-only augment specs)"}
SPEC_FILE = os.path.join(ROOT, "data", "augments_specs.json")
FIELDS = ",".join([
    "items._pageName=name", "items.image=image",
    "augments.weight_limit=weight_limit", "augments.shield_compatibility=shield_compatibility",
    "augments.slot_weapon=slot_weapon", "augments.slot_backpack=backpack",
    "augments.slot_quickuse=quick_use", "augments.slot_safepocket=safe_pocket",
    "augments.slot_healing=healing", "augments.slot_grenade=grenade",
    "augments.slot_trinket=trinket", "augments.slot_utility=utility",
])


def cargo_augments():
    res = requests.get(API, params={
        "action": "cargoquery", "tables": "items,augments",
        "join_on": "augments._pageName=items._pageName",
        "fields": FIELDS, "limit": "100", "format": "json", "formatversion": "2",
    }, headers=HEADERS, timeout=60)
    res.raise_for_status()
    rows = (res.json() or {}).get("cargoquery") or []
    return [row["title"] for row in rows]


def number(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def main():
    wiki = {row["name"]: row for row in cargo_augments()}
    if not wiki:
        raise SystemExit("wiki returned no augment rows")

    with open(SPEC_FILE, encoding="utf-8") as fh:
        data = json.load(fh)

    updated, missing = 0, []
    for spec in data.get("augments") or []:
        row = wiki.get(spec["name"])
        if not row:
            missing.append(spec["name"])
            continue
        spec["backpack"] = number(row.get("backpack"))
        spec["quick_use"] = number(row.get("quick_use"))
        spec["safe_pocket"] = number(row.get("safe_pocket"))
        spec["healing"] = number(row.get("healing"))
        spec["grenade"] = number(row.get("grenade"))
        spec["trinket"] = number(row.get("trinket"))
        spec["utility"] = number(row.get("utility"))
        spec["augmented"] = spec["healing"] + spec["grenade"] + spec["trinket"] + spec["utility"]
        spec["weapon_slots"] = number(row.get("slot_weapon"))
        spec["weight_limit"] = float(row.get("weight_limit") or 0)
        spec["shield_compatibility"] = number(row.get("shield_compatibility"))
        if row.get("image"):
            spec["wiki_image"] = row["image"]
        updated += 1

    data["generated_at"] = date.today().isoformat()
    data["sources"] = [
        "https://arcraiders.wiki/wiki/Augments — Cargo table (items + augments)",
        "live GET /inventory/parsed item_mappings (for asset_ids)",
    ]
    data["note"] = ("Quick Use / Backpack / Safe Pocket are the wiki values. Augmented is the sum of the "
                    "wiki's typed slots (healing + grenade + trinket + utility), which the game groups "
                    "under AUGMENTED SLOTS.")
    data["augments"].sort(key=lambda s: s["name"].lower())

    with open(SPEC_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("[augments] updated=%d missing=%s" % (updated, missing or "none"))
    for spec in data["augments"]:
        print("  %-32s bp=%-2d qu=%-2d sp=%-2d aug=%d" % (
            spec["name"], spec["backpack"], spec["quick_use"], spec["safe_pocket"], spec["augmented"]))


if __name__ == "__main__":
    main()
