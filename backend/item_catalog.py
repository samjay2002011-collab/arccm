"""فهرس الأيقونات والأسماء المحلي: asset id -> الاسم/الندرة/الأيقونة/الخصائص.

data/item_catalog.json هو المصدر الدائم. صوره في static/item_icons/<slug>.png
(نسخة ثانية من نفس الصور في assets/items/arctracker عشان المسار اللي البلاطة
بتقراه أصلاً). التعريفات اليدوية بتتقفل على asset id مش على الـ instance، فكل
نسخة جديدة من نفس القطعة بتتعرف لوحدها.
"""
import concurrent.futures
import json
import os
import re
import shutil
import threading
import time

import requests

from . import asset_meta, config, item_overrides

FILE = os.path.join(config.DATA_DIR, "item_catalog.json")
BACKUP_DIR = os.path.join(config.DATA_DIR, "item_catalog_backups")
ICON_URL = "static/item_icons/"
ICON_DIR = os.path.join(config.FRONTEND_DIR, "static", "item_icons")
LEGACY_ICON_DIR = os.path.join(config.ITEM_ASSETS_DIR, "arctracker")
REMOTE_MANIFEST = "https://arctracker.io/generated/client/items/manifest.json"
REMOTE_DETAIL = "https://arctracker.io/generated/client/items/items-detail.en.json"
REMOTE_INDEX = "https://arctracker.io/generated/client/items/items-index.en.json"
HEADERS = {"User-Agent": "FahmyLocalMirror/1.0 (offline item cache)"}
TIMEOUT = 45
WORKERS = 12
MAX_BACKUPS = 40
SYNC_LOCK = threading.Lock()
_lock = threading.Lock()
_cache = {"mtime": None, "data": {}}


def _empty():
    return {"version": 1, "synced_at": 0, "source_version": "", "items": {}, "manual": {}}


def _read():
    try:
        with open(FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("items", {})
    data.setdefault("manual", {})
    return data


def _uncached():
    with _lock:
        _cache.update({"mtime": None, "data": {}})
    data = _read()
    _cache.update({"mtime": None, "data": data})
    return data


def load():
    try:
        mtime = os.path.getmtime(FILE)
    except OSError:
        return _empty()
    with _lock:
        if _cache["mtime"] == mtime and _cache["data"]:
            return _cache["data"]
        data = _read()
        _cache.update({"mtime": mtime, "data": data})
        return data


def _snapshot(data):
    """نسخة احتياطية قبل كل تعديل — آخر MAX_BACKUPS بس."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tmp = os.path.join(BACKUP_DIR, "item_catalog-%s.json.part" % stamp)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(BACKUP_DIR, "item_catalog-%s.json" % stamp))
    rows = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".json"))
    for old in rows[:-MAX_BACKUPS]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass


def save(data):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    _snapshot(_uncached())
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    # ويندوز بيمنع استبدال الملف لو أي قارئ فاتحه في اللحظة دي (نافذة بتتفتح
    # بتقري الكتالوج وقت الحفظ) — بنحاول تاني بدل ما الحفظ كله يفشل بـ 500.
    for attempt in range(8):
        try:
            os.replace(tmp, FILE)
            break
        except PermissionError:
            if attempt == 7:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.15 * (attempt + 1))
    _cache.update({"mtime": os.path.getmtime(FILE), "data": data})


def slugify(name, fallback=""):
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")
    return slug or re.sub(r"[^0-9A-Za-z_-]+", "_", str(fallback)).strip("_")


def _local_icon_exists(slug):
    if not slug:
        return False
    for base in (ICON_DIR, LEGACY_ICON_DIR):
        for ext in (".png", ".webp", ".jpg"):
            if os.path.isfile(os.path.join(base, slug + ext)):
                return True
    return False


def _publish_icon(tmp, slug):
    """الصورة بتتحفظ محلياً مرتين: static/item_icons (المكتبة) و assets/items/arctracker
    (المسار اللي البلاطة بتقراه)، فمفيش أي طلب خارجي وقت العرض."""
    os.makedirs(ICON_DIR, exist_ok=True)
    os.makedirs(LEGACY_ICON_DIR, exist_ok=True)
    target = os.path.join(ICON_DIR, slug + ".png")
    if os.path.abspath(tmp) != os.path.abspath(target):
        os.replace(tmp, target)
    legacy = os.path.join(LEGACY_ICON_DIR, slug + ".png")
    if not os.path.isfile(legacy):
        shutil.copyfile(target, legacy)
    return ICON_URL + slug + ".png"


def _grab(url, slug, attempts=3):
    os.makedirs(ICON_DIR, exist_ok=True)
    tmp = os.path.join(ICON_DIR, slug + ".part")
    last = None
    for attempt in range(attempts):
        try:
            res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            res.raise_for_status()
            with open(tmp, "wb") as fh:
                fh.write(res.content)
            if res.content[:8] == b"\x89PNG\r\n\x1a\n":
                return _publish_icon(tmp, slug), None
            if res.content[:4] == b"RIFF" and res.content[8:12] == b"WEBP":
                from PIL import Image  # noqa: WPS433 — متثبتة، بس مش محتاجينها لو PNG
                with Image.open(tmp) as img:
                    img.save(os.path.join(ICON_DIR, slug + ".png"), "PNG")
                os.remove(tmp)
                return _publish_icon(os.path.join(ICON_DIR, slug + ".png"), slug), None
            raise ValueError("not a png")
        except Exception as exc:  # شبكة أو صيغة
            last = exc
            time.sleep(0.8 * (attempt + 1))
    if os.path.isfile(tmp):
        os.remove(tmp)
    return "", str(last)


def rename_legacy(slug, new_slug):
    """أيقونة القطعة قد تكون منزّلة بالاسم القديم — بتتنقل للاسم الجديد."""
    if not slug or not new_slug or slug == new_slug:
        return
    for base in (ICON_DIR, LEGACY_ICON_DIR):
        for ext in (".png", ".webp"):
            src = os.path.join(base, slug + ext)
            dst = os.path.join(base, new_slug + ext)
            if os.path.isfile(src) and not os.path.isfile(dst):
                os.replace(src, dst)


def _remote():
    res = requests.get(REMOTE_DETAIL, headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def sync():
    """بيسحب كاتالوج arctracker ويضيف الجديد بس. التعريفات اليدوية ما بتتمسحش."""
    with SYNC_LOCK:
        remote = _remote()
        rows = remote.get("items") or {}
        data = load()
        before = json.dumps(data, sort_keys=True)
        items = data["items"]
        added, images, renamed = 0, 0, 0
        for key, row in rows.items():
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            slug = slugify(name, key)
            url = str(row.get("imageFilename") or "")
            rec = items.get(key) or {}
            same = str(rec.get("name") or "") == name and rec.get("slug") == slug
            if rec.get("slug") and not same:
                rename_legacy(rec.get("slug"), slug)
                rec["image"] = ""
                renamed += 1
            icon_local = _local_icon_exists(slug)
            icon = rec.get("image") or ""
            if (icon_local or url) and not icon:
                icon = ICON_URL + slug + ".png"
            items[key] = {
                "name": name,
                "slug": slug,
                "type": str(row.get("type") or ""),
                "rarity": str(row.get("rarity") or ""),
                "stack_size": row.get("stackSize"),
                "image_url": url,
                "image": icon if icon_local or icon else "",
            }
            if not same:
                added += 1
        missing = []
        for key, rec in items.items():
            for ext in (".png", ".webp"):
                if os.path.isfile(os.path.join(ICON_DIR, rec["slug"] + ext)):
                    break
            else:
                if rec.get("image_url"):
                    missing.append((rec["slug"], rec["image_url"]))

        def job(pair):
            slug, url = pair
            got, _err = _grab(url, slug)
            return slug, got

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for slug, got in pool.map(job, missing):
                if got:
                    for rec in items.values():
                        if rec.get("slug") == slug:
                            rec["image"] = got
                    images += 1
        icon = sum(1 for rec in items.values() if rec.get("image"))
        if json.dumps(data, sort_keys=True) == before:
            # حتى لو المكتبة مفيش فيها جديد، اللوحة لازم تبان إنها اتزامنت دلوقتي
            data["checked_at"] = int(time.time())
            save(data)
            return {"ok": True, "total": len(items), "added": 0, "images": 0,
                    "icons": icon, "missing_icons": len(items) - icon, "renamed": 0,
                    "unchanged": True, "checked_at": data["checked_at"]}
        data["synced_at"] = int(time.time())
        data["source_version"] = str(remote.get("version") or "")
        save(data)
        return {"ok": True, "total": len(items), "added": added, "images": images,
                "icons": icon, "missing_icons": len(items) - icon, "renamed": renamed}


def _game_facts(asset_id):
    entry = asset_meta._blob().get(str(asset_id)) or {}
    facts = {}
    if not entry:
        return facts
    if entry.get("itemType"):
        facts["item_type"] = entry["itemType"]
    if entry.get("stackable") is not None:
        facts["stackable"] = bool(entry.get("stackable"))
    if entry.get("maxAmount"):
        facts["max_amount"] = entry["maxAmount"]
    scrap = ((entry.get("scrap") or {}).get("rewardPackage") or {}).get("rewardedItems") or []
    if scrap and scrap[0].get("gameAssetId") != asset_id:
        facts["dissolves_to"] = {"asset_id": str(scrap[0].get("gameAssetId")),
                                 "amount": scrap[0].get("amount")}
    repair = (entry.get("repair") or {}).get("durabilityReward")
    if repair:
        facts["repair"] = repair
    tags = [t for t in (entry.get("tags") or []) if str(t).startswith("Online.")]
    if tags:
        facts["release"] = tags[0]
    return facts


def _family(asset_id):
    """رقم الأصل اللي القطعة متفرعة منه (لو مختلف) — الربط التلقائي بالإعتماد عليه."""
    entry = asset_meta._blob().get(str(asset_id)) or {}
    base = str(entry.get("baseGameAssetId") or "")
    if base and base != str(asset_id) and base in load()["items"]:
        return base
    return ""


def resolve(asset_id):
    """(الاسم, الأيقونة, الندرة, التعريف) لقطعة — ولا حاجة لو مش معروفة."""
    key = str(asset_id if asset_id is not None else "").strip()
    data = load()
    manual = data["manual"].get(key) or {}
    if manual.get("name"):
        art = manual.get("image") or ""
        if not art:
            # الاسم اللي متختار من المكتبة بياخد أيقونتها نفسها لو مفيش صورة مرفوعة
            hit = _library_by_name(manual["name"])
            if hit:
                art = hit.get("image") or ""
                if hit.get("rarity") and not manual.get("rarity"):
                    manual["rarity"] = hit["rarity"]
        return {"name": manual["name"], "image": art,
                "rarity": manual.get("rarity") or "", "manual": True, "asset_id": key,
                "type": manual.get("type") or "", "family": manual.get("family") or ""}
    # تعديل المستخدم اليدوي (data/item_overrides.json) بيكسب على الكتالوج دايماً،
    # وبيرجّع آخر بيانات اتسجلت للقطعة حتى لو الكتالوج اتزامن من بعده.
    over = item_overrides.get(key)
    rec = data["items"].get(key)
    if over:
        rec = rec or {}
        return {"name": over.get("name") or rec.get("name") or "",
                "image": over.get("image") or rec.get("image") or "",
                "rarity": over.get("rarity") or rec.get("rarity") or "",
                "manual": True, "override": True, "type": over.get("type") or rec.get("type") or "",
                "value": over.get("value"), "asset_id": key, "family": _family(key)}
    if rec and str(rec.get("asset_id") or key) == key:
        return {"name": rec.get("name") or "", "image": rec.get("image") or "",
                "rarity": rec.get("rarity") or "", "manual": False, "asset_id": key,
                "family": _family(key)}
    fam = _family(key)
    if fam:
        base = data["items"].get(fam) or data["manual"].get(fam) or {}
        if base.get("name"):
            return {"name": base["name"], "image": base.get("image") or "",
                    "rarity": base.get("rarity") or "", "manual": bool(data["manual"].get(fam)),
                    "asset_id": key, "family": fam}
    return {}


def kind(asset_id):
    """نوع اللعبة/التصنيف للقطعة — تعديل المستخدم اليدوي الأول، بعده التعريف المحلي."""
    key = str(asset_id if asset_id is not None else "").strip()
    over = item_overrides.get(key) or {}
    return str(over.get("type") or (load()["manual"].get(key) or {}).get("type") or "")


def _library_by_name(name):
    """أول سطر في المكتبة بنفس الاسم بالظبط (حساسية حروف مش مهمة)."""
    want = str(name or "").strip().lower()
    if not want:
        return None
    for rec in load()["items"].values():
        if str(rec.get("name") or "").strip().lower() == want:
            return rec
    return None


def facts(asset_id):
    key = str(asset_id if asset_id is not None else "").strip()
    manual = load()["manual"].get(key) or {}
    out = _game_facts(key)
    if manual.get("note"):
        out["note"] = manual["note"]
    return out


def unknown_status(asset_id):
    key = str(asset_id if asset_id is not None else "").strip()
    info = resolve(key)
    return {"asset_id": key, "known": bool(info.get("name")), "name": info.get("name") or "",
            "image": info.get("image") or "", "rarity": info.get("rarity") or "",
            "manual": bool(info.get("manual")), "facts": facts(key)}


def search(query="", limit=24):
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    scored = []
    items = dict(load()["items"])
    # تعديلات المستخدم اليدوية بتظهر بالاسم الجديد حتى لو الاسم الأصلي اتغيّر
    for key, rec in item_overrides.all_rows().items():
        row2 = dict(items.get(key) or {})
        row2.update({k: rec.get(k) for k in ("name", "rarity", "type", "image") if rec.get(k)})
        items[key] = row2
    for key, rec in items.items():
        name = str(rec.get("name") or "")
        low = name.lower()
        if needle not in low:
            continue
        rank = 0 if low.startswith(needle) else 1 if re.search(r"\b" + re.escape(needle), low) else 2
        scored.append((rank, len(name), name, key, rec))
    scored.sort()
    out = []
    for _rank, _len, name, key, rec in scored[:limit]:
        if not rec.get("image"):
            slug = rec.get("slug") or ""
            shown = ICON_URL + slug + ".png" if _local_icon_exists(slug) else ""
        else:
            shown = rec.get("image")
        over = item_overrides.get(key) or {}
        out.append({"asset_id": key, "name": over.get("name") or name,
                    "rarity": over.get("rarity") or rec.get("rarity") or "",
                    "type": over.get("type") or rec.get("type") or "",
                    "image": over.get("image") or shown})
    return out


def define(asset_id, name, image="", rarity="", note="", source="manual"):
    """تثبيت اسم/أيقونة/ندرة على asset id. بيرجع التعريف الناتج."""
    key = str(asset_id or "").strip()
    name = str(name or "").strip()
    if not key or not name:
        raise ValueError("asset id and name are required")
    data = load()
    kind = str(_game_facts(key).get("item_type") or "")
    rec = {"name": name, "image": str(image or ""), "rarity": str(rarity or ""),
           "note": str(note or ""), "type": kind, "source": source, "at": int(time.time())}
    family = _family(key)
    if family:
        rec["family"] = family
    data["manual"][key] = rec
    save(data)
    return {"asset_id": key, "name": rec["name"], "image": rec["image"],
            "rarity": rec["rarity"], "manual": True, "family": family, "facts": facts(key)}


def attach_icon(asset_id, filename, blob):
    """صورة من الجهاز لمكتبة الأيقونات، وربطها بالـ asset id."""
    key = str(asset_id or "").strip()
    if not key:
        raise ValueError("asset id is required")
    name = (load()["manual"].get(key) or {}).get("name") or asset_meta.name(key) or ("asset_" + key)
    head = blob[:12]
    ext = ".png" if head.startswith(b"\x89PNG") else ".jpg" if head.startswith(b"\xff\xd8\xff") else ".webp" \
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP" else ""
    if not ext:
        raise ValueError("only PNG, JPG or WEBP pictures are accepted")
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] if filename else ""
    slug = slugify(stem, "") if stem else ""
    if not slug or not re.search(r"[a-z]", slug):
        slug = slugify(name, "asset")
    # الصورة ملك القطعة دي: لو اتبعتت باسم صورة قطعة تانية، صورتها بتتقفل على
    # الـ asset id بتاعها بدل ما تتكتب عليها.
    moved = {}
    for other, rec in list(load()["manual"].items()):
        img = str(rec.get("image") or "")
        if other == key or not img.startswith(ICON_URL + slug + "."):
            continue
        old_ext = img[len(ICON_URL + slug):] or ext
        fresh = slug + "_" + slugify(key, "asset")
        for folder in (ICON_DIR, LEGACY_ICON_DIR):
            src = os.path.join(folder, slug + old_ext)
            if os.path.isfile(src):
                moved[os.path.join(folder, fresh + old_ext)] = src
        load()["manual"][other]["image"] = ICON_URL + fresh + old_ext
    for dst, src in moved.items():
        os.replace(src, dst)
    os.makedirs(ICON_DIR, exist_ok=True)
    target = os.path.join(ICON_DIR, slug + ext)
    with open(target, "wb") as fh:
        fh.write(blob)
    # البلاطة بتقرا الصور من assets/items/arctracker — من غير النسخة دي الصورة
    # بتتحفظ في المكتبة وتفضل البلاطة "؟" زي ما كانت.
    os.makedirs(LEGACY_ICON_DIR, exist_ok=True)
    legacy = os.path.join(LEGACY_ICON_DIR, slug + ext)
    if not os.path.isfile(legacy) or os.path.getmtime(legacy) < os.path.getmtime(target):
        shutil.copyfile(target, legacy)
    return ICON_URL + slug + ext
