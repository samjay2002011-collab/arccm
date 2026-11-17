"""محطات الورشة ومستوياتها (نسخة أوفلاين من arctracker.io/api/hideout).

كل محطة ليها مستويات، ولكل مستوى خامات ترقية ورسم خاص بيه في اللعبة. الملفات
بتتبني بـ inspection/build_hideout_assets.py وبتتخزن محليًا — مفيش أي اتصال
بالموقع وقت التشغيل، وملوش أي علاقة بأي خدمة تانية.
"""
import json
import os

from . import config, items_db

DATA_FILE = os.path.join(config.DATA_DIR, "hideout.json")
ICON_FILE = os.path.join(config.DATA_DIR, "hideout_icons.json")

# ترتيب الشريط زي ما بيظهر جوه اللعبة.
ORDER = ("scrappy", "weapon_bench", "equipment_bench", "utility_bench", "explosives_bench",
         "refiner", "med_station", "workbench", "research_station")
_cache = {"key": None, "data": {}, "icons": {}}


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _stamp(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return -1.0


def _load():
    key = (_stamp(DATA_FILE), _stamp(ICON_FILE))
    if _cache["key"] != key:
        _cache.update({"key": key, "data": _read(DATA_FILE), "icons": _read(ICON_FILE)})
    return _cache["data"].get("hideoutModules") or {}, _cache["icons"]


def label(key):
    modules, _ = _load()
    return ((modules.get(key) or {}).get("name") or {}).get("en") or key


def max_level(key):
    modules, _ = _load()
    return int((modules.get(key) or {}).get("maxLevel") or 0)


# اسم رسم المحطة في اللعبة مش زي مفتاح البيانات حرفيًا.
BASE_NAME = {"weapon_bench": "gunsmith", "equipment_bench": "gear_bench",
             "utility_bench": "utility_station", "explosives_bench": "explosives_station",
             "med_station": "medical_lab"}


def icon(key, level=1):
    """رسم المحطة عند مستوى معيّن — بيرجع لرسم العام لو المستوى مش موجود."""
    _, icons = _load()
    by_level = icons.get(key) or {}
    base = (icons.get("_base") or {})
    return by_level.get(str(level)) or by_level.get("1") or \
        base.get("base_%s" % BASE_NAME.get(key, key)) or base.get("base_%s" % key)


def levels(key):
    """قائمة المستويات: [{level, cost:[{slug,name,image,qty,owned_ok}], requires, image}]"""
    modules, icons = _load()
    by_level = icons.get(key) or {}
    out = []
    for row in (modules.get(key) or {}).get("levels") or []:
        cost = []
        for item in row.get("requirementItemIds") or []:
            slug = str(item.get("itemId") or "")
            db_row = items_db.by_slug(slug) or {}
            cost.append({"slug": slug, "name": db_row.get("name") or slug,
                         "image": items_db.icon_for(db_row), "qty": int(item.get("quantity") or 0)})
        out.append({"level": int(row.get("level") or 0), "cost": cost,
                    "requires": row.get("requires") or [],
                    "image": by_level.get(str(row.get("level") or ""))})
    return out


def station(key, account_level=0):
    """ملخص محطة للواجهة: الاسم، السقف، المستوى الحالي، والتكلفة الجاية إيه."""
    module = {
        "key": key, "label": label(key), "max_level": max_level(key),
        "level": account_level, "icon": icon(key, account_level or 1),
        "levels": levels(key),
    }
    module["next"] = next((row for row in module["levels"] if row["level"] > account_level), None)
    return module
