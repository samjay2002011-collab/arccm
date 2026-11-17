"""درجات الأسلحة: ربط الـ asset id بالفل.

بوابة Embark بترمّز درجة السلاح في الأصل نفسه (Quality0..3 = فل 1..4)،
فمفيش حقل level في الشجرة. الجدول ده (data/weapon_tiers.json) بيقول لنا:
الفل الحالي للسلاح، وأي asset id هو الفل اللي بعده.
"""
import json
import os

from . import config

TIERS_FILE = os.path.join(config.DATA_DIR, "weapon_tiers.json")
_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        try:
            with open(TIERS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        _CACHE = {"families": data.get("families") or {}, "assets": data.get("assets") or {}}
        from . import asset_meta
        entries = asset_meta._blob()
        for asset_id, entry in entries.items():
            if asset_id in _CACHE["assets"]:
                continue
            base = str(entry.get("baseGameAssetId") or "")
            root = asset_meta.get(base)
            if root.get("group") != "Weapons" or "Item.Flag.Upgraded" in (entry.get("tags") or []):
                continue
            quality = entry.get("qualityLevel")
            if quality not in (0, 1, 2, 3):
                continue
            level = int(quality) + 1
            family = (_CACHE["assets"].get(base) or {}).get("family") or base
            name = asset_meta._family(root["name"]) + " " + ("I", "II", "III", "IV")[level - 1]
            _CACHE["assets"][asset_id] = {"family": family, "level": level, "name": name}
            _CACHE["families"].setdefault(family, {})[str(level)] = {"asset": asset_id, "name": name}
    return _CACHE


def reload():
    global _CACHE
    _CACHE = None
    return _load()


def level_of_asset(asset_id):
    """فل السلاح من الـ asset id (0 لو مش سلاح معروف)."""
    return int((_load()["assets"].get(str(asset_id)) or {}).get("level") or 0)


def family_of(asset_id):
    return str((_load()["assets"].get(str(asset_id)) or {}).get("family") or "")


def name_of(asset_id):
    return str((_load()["assets"].get(str(asset_id)) or {}).get("name") or "")


def asset_for_level(family, level):
    """asset id الخاص بالفل ده من نفس عائلة السلاح ('' لو مفيش)."""
    tiers = (_load()["families"].get(str(family)) or {})
    row = tiers.get(str(int(level or 0))) or {}
    return str(row.get("asset") or "")


def name_for_level(family, level):
    tiers = (_load()["families"].get(str(family)) or {})
    row = tiers.get(str(int(level or 0))) or {}
    return str(row.get("name") or "")


def max_level(family):
    tiers = (_load()["families"].get(str(family)) or {})
    return max([int(k) for k in tiers] or [0])
