"""عرض صفوف items_db لوصفات معينة: كل الحقول عشان نقرر مين أساسي ومين مقفول.

الخرج بيتكتب في inspection/_rows_fields_out.txt بـ UTF-8 (الكونسول على ويندوز
بيضرب العربي).
"""
import builtins
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rows_fields_out.txt")

SLUGS = ["blaze_grenade_trap", "smoke_grenade_trap", "mountaineers_detector", "tether_launcher",
         "light_ammo", "basic_camera", "looting_mk1", "looting_mk3_cautious", "combat_mk2",
         "snap_hook", "zipline", "energy_clip", "advanced_camera", "white_flag", "banjo",
         "dolabra", "emperor_gateway_conduit", "grappling_hook", "surge_coil", "yank_grenade",
         "rascal_i", "stiletto_i", "bantam_i", "canto_i", "crash_mat", "powered_descender",
         "tactical_mk3_smoke", "ferro_i", "arpeggio_i", "raider_hatch_key", "agave_juice"]

KEYS = ("name", "type", "group", "rarity", "craft_bench", "station_level",
        "blueprint_locked", "related_blueprint_id", "target_item_id", "is_blueprint",
        "quest_item", "phased_out", "found_in", "description", "craft_quantity", "asset_ids")


def main():
    db = items_db._load()
    items = db.get("items") or {}
    with open(OUT, "w", encoding="utf-8") as fh:
        say = lambda *a: builtins.print(*a, file=fh)  # noqa: E731
        for slug in SLUGS:
            row = items.get(slug)
            if not row:
                say(f"### {slug}: NOT IN DB")
                continue
            say(f"### {slug}")
            for k in KEYS:
                if k in row:
                    say("   ", k, "=", json.dumps(row[k], ensure_ascii=False)[:220])
            say("    other keys:", [k for k in row if k not in KEYS])

        bp_targets = {r["target"]: r["slug"] for r in items_db.blueprint_rows() if r.get("target")}
        say("\n== وصفات غير مقفولة بس ليها مخطوطة تستهدفها ==")
        for row in items_db.craftable_rows():
            slug = str(row.get("slug") or "")
            if not row.get("blueprint_locked") and slug in bp_targets:
                say("  ", slug, "-> blueprint", bp_targets[slug],
                    "name=", (items.get(bp_targets[slug]) or {}).get("name"))
    builtins.print("wrote", OUT)


if __name__ == "__main__":
    main()
