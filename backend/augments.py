"""مواصفات الشنط (Augments) — مصدرها جدول Rampart الداخلي + تحقق من الويكي.

الملف data/augments_specs.json بيتولد من حزمة الموقع نفسها (Ul map) لأن أرقام
الويكي أقدم من اللعبة في بعض الصفوف.
"""
import json
import os

from . import config

_CACHE = {"mtime": None, "data": None, "by_asset": {}}
SPEC_FILE = os.path.join(config.DATA_DIR, "augments_specs.json")


def _load():
    try:
        mtime = os.path.getmtime(SPEC_FILE)
    except OSError:
        mtime = 0
    if _CACHE["data"] is None or _CACHE["mtime"] != mtime:
        try:
            with open(SPEC_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {"base": {"name": "Base Pack Bag", "asset_ids": [], "backpack": 10,
                             "quick_use": 4, "safe_pocket": 1, "augmented": 0},
                    "augments": []}
        by_asset = {}
        for spec in list(data.get("augments") or []) + [data.get("base") or {}]:
            for asset_id in spec.get("asset_ids") or []:
                by_asset[str(asset_id)] = spec
        _CACHE.update(mtime=mtime, data=data, by_asset=by_asset)
    return _CACHE


def resolve(asset_id):
    """مواصفات الشنطة الملبوسة، أو الـ Base Pack Bag لو الخانة فاضية/غير معروفة."""
    data = _load()
    if asset_id is None or asset_id == "":
        return data["data"]["base"]
    return data["by_asset"].get(str(asset_id)) or data["data"]["base"]


def public():
    _load()
    data = _CACHE["data"]
    return {"base": data.get("base"), "augments": data.get("augments") or [],
            "sources": data.get("sources") or [], "generated_at": data.get("generated_at")}


def capacities(spec):
    return {key: int(spec.get(key) or 0) for key in ("backpack", "quick_use", "safe_pocket", "augmented")}


SHIELD_LEVEL = {"light": 1, "medium": 2, "heavy": 3}
SHIELD_NAMES = {1: "Light", 2: "Light/Medium", 3: "Light/Medium/Heavy"}


def shield_level(spec):
    """أعلى نوع درع بتدعمه الشنطة: 1 لايت، 2 لايت+ميديوم، 3 التلاتة."""
    return int((spec or {}).get("shield_compatibility") or 0)


def shield_supports(spec, shield_type):
    level = SHIELD_LEVEL.get(str(shield_type or "").lower())
    if not level:
        return True, ""
    top = shield_level(spec) or 3
    if level <= top:
        return True, ""
    return False, ("%s supports %s shields only — a %s shield will not fit."
                   % ((spec or {}).get("name") or "This bag", SHIELD_NAMES.get(top, "Light").lower(),
                      str(shield_type).capitalize()))
