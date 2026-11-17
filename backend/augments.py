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
