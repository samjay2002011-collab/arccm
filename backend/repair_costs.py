"""تكاليف العرض والدفع من تعريفات اللعبة؛ سجل الملاحظات القديم ليس مصدرًا للوصفات."""
import gzip
import json
import os
import time

from . import config

FILE = os.path.join(config.DATA_DIR, "repair_costs.json")
MIN_GAIN = 0.02      # فرق صحة أقل من كده مش إصلاح (ضجيج من الـ sync)
MAX_SPEND = 40       # نقص أكبر من كده غالباه عملية تانية (بيع/صناعة) مش إصلاح

# خامات الإصلاح المعروفة بالـ asset id بتاعها
SIMPLE_GUN_PARTS = "-574262619"
MEDIUM_GUN_PARTS = "-637598838"
HEAVY_GUN_PARTS = "-1903407680"
MECHANICAL = "1959573223"
ADV_MECHANICAL = "-926389249"
ELECTRICAL = "-923201933"
PLASTIC = "828947161"

# النموذج: سعر الإصلاح الكامل. الأسلحة معادلة على القياس الحقيقي (Il Toro IV درجة 4
# = 5 Simple Gun Parts + 4 Mechanical Components)، فدرجة n تاخد (n+1) و (n).
WEAPON_PROFILE = {tier: {SIMPLE_GUN_PARTS: tier + 1, MECHANICAL: tier} for tier in (1, 2, 3, 4, 5)}
SHIELD_PROFILE = {"light": {PLASTIC: 4}, "medium": {PLASTIC: 8}, "heavy": {PLASTIC: 12}}
AUGMENT_PROFILE = {MECHANICAL: 3, ELECTRICAL: 2}
FALLBACK_PROFILE = {MECHANICAL: 1, PLASTIC: 2}

_cache = {"mtime": None, "data": {}}


def _cells(payload):
    """{instance_id: (asset_id, qty, durability)} لكل خانة فيها عنصر."""
    out = {}
    for key in ("stash", "overflow", "backpack"):
        for slot in (payload or {}).get(key) or []:
            _read_slot(slot, out)
    for slots in ((payload or {}).get("containers") or {}).values():
        if isinstance(slots, list):
            for slot in slots:
                _read_slot(slot, out)
    return out


def _read_slot(slot, out):
    item = (slot or {}).get("item")
    if not isinstance(item, dict) or slot.get("is_empty"):
        return
    iid = str(item.get("instanceId") or item.get("id") or "")
    asset = item.get("asset_id")
    if asset is None:
        asset = item.get("gameAssetId")
    if not iid or asset is None:
        return
    try:
        durability = float(item.get("durability")) if item.get("durability") is not None else None
    except (TypeError, ValueError):
        durability = None
    out[iid] = (str(asset), int(item.get("amount") or 1), durability)


def _totals(cells):
    totals = {}
    for asset, qty, _ in cells.values():
        totals[asset] = totals.get(asset, 0) + qty
    return totals


def _load():
    try:
        mtime = os.path.getmtime(FILE)
    except OSError:
        return {"costs": {}}
    if _cache["mtime"] != mtime:
        try:
            with open(FILE, encoding="utf-8") as fh:
                _cache["data"] = json.load(fh)
        except (OSError, ValueError):
            return {"costs": {}}
        _cache["mtime"] = mtime
    return _cache["data"]


def _save(data):
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(tmp, FILE)
    _cache["data"] = data
    _cache["mtime"] = None


def observe(account, payload, prev_path):
    """يقارن اللقطة الجديدة باللي قبلها ويسجّل كل إصلاح اتعمل في النافذة.

    بيرجّع عدد القطع اللي اتصلّحت والخامات اللي اتصرفت، أو None لو مفيش إصلاح.
    """
    if not prev_path or not os.path.isfile(prev_path):
        return None
    try:
        with gzip.open(prev_path, "rb") as fh:
            prev = _cells(json.loads(fh.read().decode("utf-8")))
    except (OSError, ValueError):
        return None
    new = _cells(payload)
    repaired = []
    for iid, (asset, _, durability) in new.items():
        old = prev.get(iid)
        if not old or old[2] is None or durability is None:
            continue
        if durability - old[2] >= MIN_GAIN:
            repaired.append((asset, round(durability - old[2], 3)))
    if not repaired:
        return None
    before, after = _totals(prev), _totals(new)
    spent = {asset: before[asset] - after.get(asset, 0) for asset in before}
    spent = {a: q for a, q in spent.items() if 0 < q <= MAX_SPEND}
    for asset, _gain in repaired:
        spent.pop(asset, None)
    if not spent:
        return None
    data = _load()
    costs = data.setdefault("costs", {})
    stamp = int(time.time())
    for asset, gain in repaired:
        _merge(costs, asset, spent, gain, "snapshot")
    data["updated_at"] = stamp
    _save(data)
    return {"repaired": len(repaired), "materials": spent}


def _merge(costs, asset, materials, basis, source):
    """بيضيف قياس جديد للـ asset: أعلى كمية لكل خامة (أحوط للعرض)."""
    entry = costs.get(str(asset)) or {}
    merged = dict(entry.get("materials") or {})
    for mid, qty in materials.items():
        merged[mid] = max(merged.get(mid, 0), int(qty))
    costs[str(asset)] = {"materials": merged,
                         "basis": max(float(entry.get("basis") or 0), float(basis or 0)) or 1.0,
                         "count": int(entry.get("count") or 0) + 1,
                         "source": source}


WEAPON_TYPES = ("rifle", "cannon", "lmg", "smg", "pistol", "shotgun", "bow", "launcher", "special")


def _klass(asset_id, row):
    """فئة العنصر — الـ group بييجي من قاعدة العناصر لأن صفوف لقطة البوابة فيها `type` بس."""
    row = row or {}
    group = str(row.get("group") or "")
    if group not in ("Weapons", "Shields", "Augments"):
        group = ""
        try:
            from . import items_db
            group = str((items_db.find(asset_id=str(asset_id)) or {}).get("group") or "")
        except Exception:
            pass
    if group in ("Weapons", "Shields", "Augments"):
        return group
    name = str(row.get("name") or row.get("display_name") or "").lower()
    kind = str(row.get("type") or "").lower()
    if "shield" in kind or "shield" in name:
        return "Shields"
    if "augment" in kind or "augment" in name:
        return "Augments"
    if "weapon mod" in group:
        return ""
    if any(h in kind for h in WEAPON_TYPES):
        return "Weapons"
    return ""


def profile_cost(asset_id, row):
    """سعر تقديري بالفئة/الدرجة لما مفيش قياس للعنصر ده — للعرض بس."""
    klass = _klass(asset_id, row)
    name = str((row or {}).get("name") or (row or {}).get("display_name") or "").lower()
    if klass == "Weapons":
        tier = 1
        try:
            from . import weapon_tiers
            tier = max(1, min(5, int(weapon_tiers.level_of_asset(asset_id) or 1)))
        except Exception:
            pass
        return dict(WEAPON_PROFILE[tier])
    if klass == "Shields":
        for key, cost in SHIELD_PROFILE.items():
            if key in name:
                return dict(cost)
        return dict(SHIELD_PROFILE["medium"])
    if klass == "Augments":
        return dict(AUGMENT_PROFILE)
    return dict(FALLBACK_PROFILE)


def cost_for(asset_id, row=None):
    from . import asset_meta
    repair = (asset_meta._blob().get(str(asset_id)) or {}).get("repair") or {}
    rows = (repair.get("costPackage") or {}).get("costItems") or []
    materials = {}
    for material in rows:
        mid = material.get("gameAssetId")
        amount = material.get("amount")
        if mid is None or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            return {"materials": {}, "basis": 1.0, "count": 0,
                    "estimated": True, "known": False, "source": "unverified"}
        materials[str(mid)] = materials.get(str(mid), 0) + amount
    known = bool(materials) and float(repair.get("durabilityReward") or 0) > 0
    return {"materials": materials if known else {},
            "basis": float(repair.get("durabilityReward") or 1), "count": 0,
            "estimated": not known, "known": known, "source": "game_definition" if known else "unverified"}

