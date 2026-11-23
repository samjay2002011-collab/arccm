"""فهرس تصنيف العناصر: بيانات rampart + تصنيفات arcraiders.wiki.

الملف data/items_catalog.json هو المصدر (يتبني بـ inspection/build_items_catalog.py).
لو الملف مش موجود: تصنيف احتياطي من type/category بتاع rampart فقط.
"""
import csv
import json
import os
import re
import threading

from . import asset_meta, config, item_catalog, item_overrides

CATALOG_FILE = os.path.join(config.DATA_DIR, "items_catalog.json")
ARCTRACKER_FILE = os.path.join(config.DATA_DIR, "arctracker_items_cache.json")

GROUPS = ["Weapons", "Blueprints", "Designs", "Stencils", "Augments", "Shields", "Weapon Mods",
          "Quick Use", "Ammunition", "Crafting Materials", "Keys", "Trinkets", "Research",
          "Furniture", "Misc"]
GROUP_LABELS = {"Designs": "Design", "Stencils": "Stencil"}

# "Unlock Surge Coil Craft" — token بيفتح وصفة تصنيع العنصر ده.
UNLOCK_CRAFT = re.compile(r"^Unlock\s+(.+?)\s+Craft$", re.I)

WEAPON_TYPES = {"weapon", "smg", "assault rifle", "battle rifle", "hand cannon", "shotgun",
                "sniper rifle", "lmg", "pistol", "special"}
MOD_TYPES = {"modification", "mod", "attachment", "weapon mod"}
MATERIAL_TYPES = {"basic material", "topside material", "refined material", "material",
                  "recyclable", "crafting material"}
AR_TYPE_GROUPS = {"augment": "Augments", "shield": "Shields", "modification": "Weapon Mods",
                  "quick use": "Quick Use", "ammunition": "Ammunition", "key": "Keys",
                  "trinket": "Trinkets", "research": "Research",
                  "outpost furniture": "Furniture", "outpost room": "Furniture",
                  "recyclable": "Crafting Materials", "basic material": "Crafting Materials",
                  "topside material": "Crafting Materials", "refined material": "Crafting Materials",
                  "nature": "Crafting Materials"}
QUICK_TYPES = {"quick use", "quickuse", "consumable"}
MATERIAL_WIKI = {"basic material", "refined material", "topside material", "recyclable", "materials"}
QUICK_WIKI = {"quick use", "gadgets", "grenades", "traps", "consumables"}
# تصنيفات صيانة/صور في الويكي مش مفيدة كـ tags
WIKI_NOISE = ("pages using", "templates based", "articles which use", "stubs",
              "missing weapon durability", " item images", " item icons", " item category",
              " weapon images", " weapon mod images", "weapon mod icons", "weapon images",
              "augment images", "augment ability icons", "shield images", "shield icons",
              "grenade images", "trap images", "key images", "nature item images",
              "research item images", "backpack attachment images", "item icons", "item images",
              "item location icons", "map modifier icons", "quest item images", "trinket images",
              "utility item images", "consumable item images", "gadget images", "arc item images")

# أسماء اللعبة الرسمية (من asset_index) != أسماء arctracker — المفتاح اسم اللعبة
# بعد normalize، والقيمة اسم arctracker بعد normalize.
ALIASES = {"colorful shoes": "colorful shoes (red)",
           "trigger nade": "trigger 'nade",
           "sheetmetal": "sheet metal",
           "poster of natural wonder": "poster of natural wonders",
           "dam control center tower key": "dam control tower key",
           # arctracker عاملها صفحة واحدة باسم "Deprecated Anvil Splitter"
           # (نفس المرفق)، فالصورة هناك مش عند اسم اللعبة المجرّد.
           "anvil splitter": "deprecated anvil splitter"}

_lock = threading.Lock()
_cache = {"mtime": None, "data": None}
_asset_lock = threading.Lock()
_asset_cache = {"mtime": None, "map": {}}
_ar_lock = threading.Lock()
_ar_cache = {"mtime": None, "exact": {}, "compact": {}, "tiers": {}}

_ROMAN_TAIL = re.compile(r"^(.*?)\s+(i{1,3}|iv|v)$")
ROMAN_RANK = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}


def _compact(name):
    return re.sub(r"\s+", " ", normalize(name).replace(". ", ".")).strip()


def _arctracker_data():
    try:
        mtime = os.path.getmtime(ARCTRACKER_FILE)
    except OSError:
        return _ar_cache
    # تعديلات المستخدم اليدوية هي أول ما بيتقرا في بيانات اللعبة — أي حقل معدّل
    # بيغلب نسخة الملف (وملفاته الافتراضية ما بتتعدلش).
    try:
        over_mtime = os.path.getmtime(item_overrides.FILE)
    except OSError:
        over_mtime = -1.0
    with _ar_lock:
        if _ar_cache["mtime"] == mtime and _ar_cache.get("over") == over_mtime and _ar_cache["exact"]:
            return _ar_cache
        with open(ARCTRACKER_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        exact, compact, tiers = {}, {}, {}
        for item in (raw.get("items") or {}).values():
            key = normalize(item.get("name"))
            if not key:
                continue
            exact.setdefault(key, item)
            compact.setdefault(_compact(key), item)
            match = _ROMAN_TAIL.match(key)
            if match:
                tiers.setdefault(match.group(1).strip(), []).append(item)
        for group in tiers.values():
            group.sort(key=lambda it: ROMAN_RANK.get(
                normalize(it.get("name")).rsplit(" ", 1)[-1], 99))
        overrides = list(item_overrides.all_rows().items())
        for key, rec in overrides:
            item = exact.get(normalize(rec.get("name")))
            if isinstance(item, dict):
                item = dict(item)
                exact[normalize(rec.get("name"))] = item
            else:
                item = {"id": key, "asset_ids": [key]}
                exact[normalize(rec.get("name"))] = item
            for field, value in (("name", rec.get("name")), ("rarity", rec.get("rarity")),
                                 ("type", rec.get("type")), ("value", rec.get("value"))):
                if value not in (None, ""):
                    item[field] = value
            # صور الكتالوج الخام بتيجي من الموقع — العرض هنا بيعتمد على الصور المحلية,
            # فمفيش أي رابط خارجي بيتحفظ أو بيتعرض من خلال التعديل اليدوي.
            item["image_local"] = item_overrides.local_image(rec.get("image") or item.get("image_local") or "")
        _ar_cache.update({"mtime": mtime, "over": over_mtime, "exact": exact, "compact": compact, "tiers": tiers})
        return _ar_cache


def search(term, limit=40):
    """بحث بالاسم في كاش arctracker المحلي — للعناصر اللي مش في المخزن."""
    key = normalize(term).strip()
    if len(key) < 2:
        return []
    hits = []
    for item in _arctracker_data()["exact"].values():
        name = normalize(item.get("name"))
        if name.startswith(key):
            score = 0
        elif key in name:
            score = 1
        else:
            continue
        hits.append((score, name, item))
    hits.sort(key=lambda h: (h[0], h[1]))
    ids_by_name = _asset_ids_by_name()
    return [{
        "name": item.get("name"),
        "group": _arctracker_group(item, False),
        "type": item.get("type") or "",
        "rarity": item.get("rarity") or "",
        "image": item.get("image_local") or "",
        "value": item.get("value"),
        "stack": item.get("stack_size"),
        "asset_ids": ids_by_name.get(normalize(item.get("name")), []),
    } for _, _, item in hits[:limit]]


def patch_candidates(limit=12):
    """أسماء آخر باتش عند arctracker ومفيش ليها asset id معروف — مرشّحات التسمية.

    البوابة بترجع أرقام بس، والفهرس العام متوقّف، فدي الطريقة الوحشان نعرف بيها
    إن القطعة المجهولة دي على الأغلب هي "...". لو المرشّح واحد بس يبقى أكيد."""
    ids = _asset_ids_by_name()
    # الترتيب بالتاريخ المفهوم (MM/DD/YYYY) مش بالنص: "12/16/2025"أكبر نصاً من "10/27/2026"
    def stamp(item):
        try:
            m, d, y = (int(x) for x in str(item.get("updated_at") or "").split("/"))
            return (y, m, d)
        except ValueError:
            return (0, 0, 0)
    dated = [(stamp(i), i) for i in _arctracker_data()["exact"].values()]
    if not dated:
        return []
    newest = max(s for s, _ in dated)
    out = [item for s, item in dated
           if s == newest and not ids.get(normalize(item.get("name")))]
    out.sort(key=lambda it: normalize(it.get("name")))
    return [{"name": it.get("name"), "group": _arctracker_group(it, False),
             "rarity": it.get("rarity") or "", "image": it.get("image_local") or "",
             "value": it.get("value"), "updated_at": "%04d-%02d-%02d" % newest}
            for it in out[:limit]]


# صور بيضيفها صاحب الموقع لقطع الفهرس ماعندهوش أرت: بمفتاح asset id (أو الاسم لو
# مفيش id). الملف data/index_art.json — الصور نفسها في assets/items/arctracker
# أو assets/items/uploaded، فبتتخدم زي أي أرت تاني.
INDEX_ART_FILE = os.path.join(config.DATA_DIR, "index_art.json")
_art_lock = threading.Lock()
_art_cache = {"mtime": None, "map": {}}


def _index_art_data():
    try:
        mtime = os.path.getmtime(INDEX_ART_FILE)
    except OSError:
        return {}
    with _art_lock:
        if _art_cache["mtime"] == mtime:
            return _art_cache["map"]
        try:
            with open(INDEX_ART_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except (OSError, ValueError):
            data = {}
        _art_cache.update({"mtime": mtime, "map": data})
        return data


def index_art(asset_id="", name=""):
    """الصورة المضافة يدوياً لقطعة — بالـ id الأول، وبعدين بالاسم."""
    data = _index_art_data()
    aid = str(asset_id or "").strip()
    if aid and aid in data:
        return data[aid].get("image") or ""
    key = normalize(name)
    for row in data.values():
        if row.get("name") and normalize(row.get("name")) == key and row.get("image"):
            return row["image"]
    return ""


def set_index_art(asset_id="", name="", image="", source="arctracker"):
    """يحفظ صورة لقطعة في فهرس الصور ويجعل الكاشات تحس بالتغيير فوراً."""
    aid = str(asset_id or "").strip()
    img = str(image or "").strip()
    if not img:
        raise ValueError("The image path is empty.")
    row = {"image": img, "name": str(name or "").strip(), "source": "upload" if source == "uploaded" else "arctracker"}
    with _art_lock:
        try:
            with open(INDEX_ART_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except (OSError, ValueError):
            data = {}
        key = aid or ("name:" + normalize(name))
        data[key] = row
        os.makedirs(os.path.dirname(INDEX_ART_FILE), exist_ok=True)
        tmp = INDEX_ART_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, INDEX_ART_FILE)
    # الكاشات بتقارن mtime — ملف جديد أو تعديل على arctracker لازم يتشاف في نفس الطلب
    _art_cache.update({"mtime": None, "map": data})
    _ar_cache.update({"mtime": None})
    _ids_cache.update({"mtime": None})
    return row


_ids_lock = threading.Lock()
_ids_cache = {"mtime": None, "map": {}}


def _asset_ids_by_name():
    """اسم العرض بتاع اللعبة -> كل asset ids بتاعته. المطابقة بالـ ID أدق من الاسم:
    أحياناً arctracker يستخدم تسمية مختلفة عن التسمية في شجرة الحساب.
    بنقرأ الفهرس العام + المحلي (البنود الجديدة اللي اتعرّفنا عليها من الشجرة)."""
    from . import pioneer_tree
    index_files = (pioneer_tree.ASSET_INDEX_FILE, pioneer_tree.ASSET_LOCAL_FILE)
    out = {}
    stamps = []
    for path in index_files:
        try:
            stamps.append(os.path.getmtime(path))
        except OSError:
            stamps.append(None)
    mtime = tuple(stamps)
    with _ids_lock:
        if _ids_cache["mtime"] == mtime and _ids_cache["map"]:
            return _ids_cache["map"]
        for path in index_files:
            try:
                with open(path, "r", encoding="utf-8", newline="") as f:
                    for row in csv.DictReader(f):
                        key = normalize((row.get("display_name") or "").strip())
                        asset_id = str(row.get("game_asset_id") or "").strip()
                        if key and asset_id:
                            out.setdefault(key, []).append(asset_id)
            except OSError:
                pass
        for entry in (load().get("items") or {}).values():
            for variant in entry.get("variants") or []:
                key = normalize(variant.get("name"))
                asset_id = str(variant.get("asset_id") or "")
                if key and asset_id and asset_id not in out.get(key, []):
                    out.setdefault(key, []).append(asset_id)
        for game_name, ar_name in ALIASES.items():
            if ar_name in out and game_name not in out:
                out[game_name] = out[ar_name]
        _ids_cache.update({"mtime": mtime, "map": out})
        return out


def _tier_variant(data, name):
    """أسماء rampart بتحذف رقم النسخة (I..V) — نرجّع نسخة الاسم نفسه، وإلا الأولى الجاهزة."""
    raw = normalize(name)
    if raw.endswith(" blueprint"):
        raw = raw[:-len(" blueprint")].strip()
    match = _ROMAN_TAIL.match(raw)
    base = match.group(1).strip() if match else raw
    candidates = data.get("tiers", {}).get(base) or []
    ready = [it for it in candidates
             if not it.get("is_blueprint")
             and normalize(it.get("type")) != "blueprint"
             and not normalize(it.get("name")).endswith(" blueprint")]
    pool = ready or candidates
    if match:
        for it in pool:
            if normalize(it.get("name")).rsplit(" ", 1)[-1] == match.group(2):
                return it
    return (pool or [None])[0]


def arctracker_lookup(name):
    """بيطابق اسم rampart مع كاش arctracker المحلي (بدون أي طلب خارجي)."""
    data = _arctracker_data()
    raw = normalize(name)
    keys = [raw]
    if raw.endswith(" blueprint"):
        keys.append(raw[:-len(" blueprint")].strip())
    for key in keys:
        item = data["exact"].get(key)
        if item:
            return item
    for key in keys:
        item = data["compact"].get(_compact(key))
        if item:
            return item
    alias = ALIASES.get(raw)
    if alias:
        item = data["exact"].get(alias) or data["compact"].get(_compact(alias))
        if item:
            return item
    for key in keys:
        item = _tier_variant(data, key)
        if item:
            return item
    return None


def icon_of(item):
    """أيقونة العنصر: MetaForge الأساسية وarctracker احتياطي."""
    if not item:
        return ""
    return item.get("metaforge_image") or item.get("image_local") or ""


def _is_blueprint(name, item_type):
    return (str(item_type or "").strip().lower() == "blueprint"
            or normalize(name).endswith(" blueprint"))


def _arctracker_group(item, blueprint):
    kind = normalize(item.get("type"))
    if kind == "design":
        return "Designs"
    if kind == "stencil":
        return "Stencils"
    if blueprint or kind == "blueprint" or item.get("is_blueprint"):
        return "Blueprints"
    if kind in WEAPON_TYPES:
        return "Weapons"
    return AR_TYPE_GROUPS.get(kind, "Misc")


def manual_group(kind):
    """جروب قطعة معرّفة يدوياً من نوع اللعبة — اللي ملهاش نوع بيقع في Misc."""
    low = normalize(kind)
    if low == "design":
        return "Designs"
    if low == "stencil":
        return "Stencils"
    if low == "blueprint":
        return "Blueprints"
    if low in WEAPON_TYPES:
        return "Weapons"
    return AR_TYPE_GROUPS.get(low, "Misc")


def normalize(name):
    text = str(name or "").strip().lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", text)


def clean_wiki(categories):
    out = []
    for raw in categories or []:
        name = str(raw or "").replace("Category:", "").strip()
        low = name.lower()
        if not name or any(noise in low for noise in WIKI_NOISE):
            continue
        if name not in out:
            out.append(name)
    return out


def classify(name="", item_type="", raw_categories=None, wiki_categories=None):
    """يصنّف عنصر لمجموعة واحدة من GROUPS (نفس مجموعات فلاتر الموقع)."""
    low_name = normalize(name)
    t = str(item_type or "").strip().lower()
    raw = {str(c).split("::")[-1].strip().lower() for c in (raw_categories or [])}
    wiki = {str(c).strip().lower() for c in (wiki_categories or [])}

    def wiki_has(*keys):
        return any(k in wiki for k in keys)

    if t == "design" or wiki_has("designs"):
        return "Designs"
    if t == "stencil" or wiki_has("stencils"):
        return "Stencils"
    if t == "blueprint" or low_name.endswith(" blueprint") or wiki_has("blueprints"):
        return "Blueprints"
    if t == "augment" or wiki_has("augments"):
        return "Augments"
    if t in WEAPON_TYPES or wiki_has("weapons"):
        return "Weapons"
    if t == "shield":
        if wiki_has("quick use") or "consumable" in raw:
            return "Quick Use"
        if wiki_has("misc") or (wiki and not wiki_has("shields")):
            return "Misc"
        return "Shields"
    if t in MOD_TYPES or wiki_has("mods", "modifications"):
        return "Weapon Mods"
    if t == "ammunition" or "riflepayload" in raw or wiki_has("ammunition"):
        return "Ammunition"
    if t == "key" or wiki_has("key"):
        return "Keys"
    if t in MATERIAL_TYPES or wiki_has(*MATERIAL_WIKI):
        return "Crafting Materials"
    if t in QUICK_TYPES or wiki_has(*QUICK_WIKI):
        return "Quick Use"
    if "recipe" in raw:
        return "Blueprints"
    if raw & {"throwable", "deployable", "gadget", "consumable"}:
        return "Quick Use"
    if "armor" in raw:
        return "Shields"
    if "augment" in raw:
        return "Augments"
    if "modification" in raw:
        return "Weapon Mods"
    return "Misc"


def load():
    try:
        mtime = os.path.getmtime(CATALOG_FILE)
    except OSError:
        return {"items": {}, "groups": GROUPS}
    with _lock:
        if _cache["data"] is not None and _cache["mtime"] == mtime:
            return _cache["data"]
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _cache["data"] = data
        _cache["mtime"] = mtime
        # تعديلات المستخدم اليدوية بتتجمّل جوه فهرس الاسم نفسه، فأي مطابقة بالاسم
        # (التصنيف/الجروب/الوصف) بتلاقيها الأول قبل أي بيانات تانية في الفهرس.
        items = data.setdefault("items", {})
        for key, rec in item_overrides.all_rows().items():
            name = normalize(rec.get("name"))
            if not name or not any(str(v.get("asset_id") or "") == key
                                   for entry in items.values() for v in entry.get("variants") or []):
                continue
            entry = items.setdefault(name, {"variants": []})
            variants = entry.setdefault("variants", [])
            target = next((v for v in variants if str(v.get("asset_id") or "") == key), None)
            if target is None:
                target = {"asset_id": key}
                variants.insert(0, target)
            for field, value in (("name", rec.get("name")), ("rarity", rec.get("rarity")),
                                 ("type", rec.get("type")), ("value", rec.get("value"))):
                if value not in (None, ""):
                    target[field] = value
        return data


def _entry_for(name):
    items = load().get("items") or {}
    raw = normalize(name)
    blueprint = raw.endswith(" blueprint")
    base = raw[:-len(" blueprint")].strip() if blueprint else raw
    for key in (base, raw):
        entry = items.get(key)
        if entry:
            return entry, blueprint
    match = re.match(r"^(.*?)\s+(i{1,3}|iv|v)$", base)
    if match:
        entry = items.get(match.group(1).strip())
        if entry:
            return entry, blueprint
    return None, blueprint


def _by_asset():
    """فهرس asset_id → variant. الـ asset_id اللي بتديه البوابة أدق من الاسم:
    'Trigger Nade' (اللي في الشنطة) اسمه شبه 'Trigger 'Nade' بتاعته، والفهرس
    بيحط البلوبرنت تحت الاسم من غير الفاصلة — فمطابقة الاسم بتغلّط."""
    try:
        mtime = os.path.getmtime(CATALOG_FILE)
    except OSError:
        return {}
    with _asset_lock:
        if _asset_cache["mtime"] == mtime and _asset_cache["map"]:
            return _asset_cache["map"]
        mapping = {}
        for entry in (load().get("items") or {}).values():
            for variant in entry.get("variants") or []:
                asset_id = str(variant.get("asset_id") or "")
                if asset_id and asset_id not in mapping:
                    mapping[asset_id] = variant
        _asset_cache.update({"mtime": mtime, "map": mapping})
        return mapping


def lookup(name, item_type="", asset_id=""):
    """يرجع variant العنصر من الفهرس؛ الـ asset_id بيكسب لو موجود، وبعدها الاسم."""
    exact = _by_asset().get(str(asset_id or ""))
    if exact:
        return exact
    entry, blueprint = _entry_for(name)
    if not entry:
        return None
    variants = entry.get("variants") or []
    if not variants:
        return None
    if blueprint:
        chosen = [v for v in variants if v.get("is_blueprint") or v.get("group") == "Blueprints"]
    else:
        chosen = [v for v in variants if not v.get("is_blueprint") and v.get("group") != "Blueprints"]
    if item_type:
        exact = [v for v in chosen if normalize(v.get("type")) == normalize(item_type)]
        if exact:
            return exact[0]
    return (chosen or variants)[0]


def group_for(name="", item_type="", raw_categories=None, asset_id=""):
    fixed = asset_meta.get(asset_id)
    if fixed.get("group"):
        return fixed["group"]
    # القطعة المعرّفة يدوياً بتتجمّع بس من نوعها اللي اتسجل (زي Weapon أو Quick Use)،
    # من غير باقي مسار الاسم/الفهرس: القطعة دي أصلاً مش في أي فهرس.
    manual = item_catalog.kind(asset_id)
    if manual:
        return manual_group(manual)
    blueprint = _is_blueprint(name, item_type)
    item = arctracker_lookup(name)
    if item:
        kind = normalize(item.get("type"))
        if kind == "design":
            return "Designs"
        if kind == "stencil":
            return "Stencils"
        if blueprint:
            return "Blueprints"
        return _arctracker_group(item, blueprint)
    exact = _by_asset().get(str(asset_id or ""))
    if exact and not blueprint and exact.get("group") != "Blueprints":
        return exact["group"] or classify(name, item_type, raw_categories)
    if blueprint:
        return "Blueprints"
    info = lookup(name, item_type, asset_id)
    if info:
        return info.get("group") or classify(name, item_type, raw_categories)
    return classify(name, item_type, raw_categories)


def _decorate_attachments(row):
    atts = row.get("attachments")
    if isinstance(atts, str):
        try:
            atts = json.loads(atts or "[]")
        except ValueError:
            atts = []
    if not isinstance(atts, list):
        return
    for att in atts:
        if not isinstance(att, dict):
            continue
        fixed = asset_meta.get(att.get("asset_id"))
        if fixed.get("name"):
            att["name"] = fixed["name"]
            att["display_name"] = fixed["name"]
        if fixed.get("rarity"):
            att["rarity"] = fixed["rarity"]
        item = arctracker_lookup(att.get("display_name") or att.get("name"))
        icon = icon_of(item) or fixed.get("image")
        if icon:
            att["image_filename"] = icon
    row["attachments"] = atts


def decorate(row):
    """يضيف group/type_label/display_name وبيانات الكاش لسطر عرض."""
    fixed = asset_meta.get(row.get("asset_id"))
    name = fixed.get("name") or row.get("name")
    item_type = fixed.get("type") or str(row.get("type") or "")
    blueprint = _is_blueprint(name, item_type)
    item = arctracker_lookup(name)
    kind = normalize(item.get("type")) if item else ""
    design = kind == "design"
    stencil = kind == "stencil"
    if design or stencil:
        blueprint = False
    info = lookup(name, item_type, row.get("asset_id"))
    raw = row.get("category")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    if item:
        row["group"] = "Designs" if design else "Stencils" if stencil else _arctracker_group(item, blueprint)
        if design:
            row["type_label"] = "Design"
        elif stencil:
            row["type_label"] = "Stencil"
        elif blueprint or item.get("is_blueprint"):
            row["type_label"] = "Blueprint"
        else:
            row["type_label"] = item.get("type") or item_type or "Item"
        row["item_kind"] = "design" if design else "stencil" if stencil else "blueprint" if blueprint else ""
        row["display_name"] = item.get("name") if (design or stencil) else name
        row["arctracker_id"] = item.get("id")
        row["arctracker_type"] = item.get("type")
        row["arctracker_rarity"] = item.get("rarity")
        row["arctracker_value"] = item.get("value")
        row["arctracker_weight"] = item.get("weight_kg")
        row["arctracker_stack"] = item.get("stack_size")
        if item.get("effects"):
            row["effects"] = item["effects"]
        row["has_durability"] = bool(item.get("has_durability")) and not blueprint and not design and not stencil
        row["durability_max"] = item.get("durability_max") if row["has_durability"] else None
        row["required_materials"] = item.get("required_materials") or []
        row["compatible_with"] = item.get("compatible_with") or []
        row["stencil_parts_cost"] = item.get("stencil_parts_cost")
        row["description"] = item.get("description") or ""
        if item.get("image_local"):
            row["arctracker_image"] = item["image_local"]
        if item.get("metaforge_image"):
            row["metaforge_image"] = item["metaforge_image"]
        if icon_of(item):
            row["image"] = icon_of(item)
    else:
        row["group"] = "Blueprints" if blueprint else \
            ((info or {}).get("group") or classify(name, row.get("type"), raw))
        if blueprint:
            row["type_label"] = "Blueprint"
        elif info and info.get("wiki_type"):
            row["type_label"] = info["wiki_type"]
        else:
            row["type_label"] = row.get("type") or (info or {}).get("type") or "Item"
        row["item_kind"] = "blueprint" if blueprint else ""
        row["display_name"] = name
        row["required_materials"] = []
        row["compatible_with"] = []
        row["stencil_parts_cost"] = None
        row["description"] = ""
        kind = item_type.strip().lower()
        row["has_durability"] = not blueprint and (kind in WEAPON_TYPES or kind in ("shield", "augment"))
        row["durability_max"] = None
    if info:
        row["catalog_name"] = info.get("name") or ""
        row["catalog_group"] = info.get("group") or ""
    if not str(row.get("rarity") or "").strip():
        # البوابة باتبعت بعض العناصر من غير ندرة (أسلحة metaforge زي Hullcracker IV) —
        # arctracker عنده الندرة لكل نسخة (I..V)، فالكتالوج بعده.
        row["rarity"] = (item or {}).get("rarity") or (info or {}).get("rarity") or ""
    if row.get("value") is None and (item or {}).get("value") is not None:
        row["value"] = item.get("value")
    if row.get("stack_size") is None and (item or {}).get("stack_size") is not None:
        row["stack_size"] = item.get("stack_size")
    art = index_art(row.get("asset_id"), name)
    if art:
        row["image"] = art
        row["index_art"] = True
    # قطعة معرّفة يدوياً أو موجودة في فهرس الأيقونات المحلي: الاسم والأيقونة
    # والندرة بتتغلب على الفهرس العام، من غير أي طلب خارجي.
    local = item_catalog.resolve(row.get("asset_id"))
    if not row.get("image") and local.get("image"):
        row["image"] = local["image"]
        row["catalog_art"] = True
    if not str(row.get("rarity") or "").strip() and local.get("rarity"):
        row["rarity"] = local["rarity"]
    if not row.get("image"):
        # "Unlock Surge Coil Craft" وأمثالها (١٣٣ سطر في الفهرس العام): دي tokens
        # بفتح وصفة التصنيع، ومش موجودة في arctracker خالص، فالصورة بتتقرا من
        # العنصر نفسه اللي بتفتح له. من غيرها البلاطة بتبان علامة استفهام.
        # الندرة والبيانات بتفضل فاضية عشان الكارت مايظهرش كأنه العنصر الأصلي.
        unlock = UNLOCK_CRAFT.match(str(name or "").strip())
        if unlock:
            target = arctracker_lookup(unlock.group(1).strip())
            if target and icon_of(target):
                row["image"] = icon_of(target)
    if fixed:
        # الصف المخزّن ممكن يكون اتكتب قبل تصحيح الأسماء، فالجدول بيكسب وقت العرض
        # لحد ما المزامنة الجاية تثبّت نفس القيم في القاعدة.
        row["display_name"] = fixed["name"]
        row["type"] = item_type
        row["type_label"] = fixed.get("type") or row.get("type_label") or "Item"
        for key in ("group", "rarity", "description", "image"):
            if fixed.get(key):
                row[key] = fixed[key]
        for key in ("value", "stack_size", "weight_kg"):
            if fixed.get(key) is not None:
                row[key] = fixed[key]
    if local.get("manual"):
        # التعريف اليدوي هو الكلمة الأخيرة على الاسم/الندرة: الجدول المخزّن
        # (asset_meta) لسه مش عارف القطعة، فمينفعش يمسح اللي المستخدم كتبه.
        row["display_name"] = local["name"]
        row["name"] = local["name"]
        if local.get("image"):
            row["image"] = local["image"]
            row["catalog_art"] = True
        if local.get("rarity"):
            row["rarity"] = local["rarity"]
        if local.get("type"):
            row["type"] = local["type"]
            row["type_label"] = local["type"]
        row["manual_definition"] = True
    # تعديل المستخدم اليدوي (data/item_overrides.json) هو الكلمة الأخيرة على كل حقل
    item_overrides.apply(row, row.get("asset_id"))
    if not row.get("image"):
        resolved = item_catalog.resolve(row.get("asset_id"))
        if resolved.get("image"):
            row["image"] = resolved["image"]
    bg = row.get("card_bg")
    if bg == "blueprint":
        row["item_kind"] = "blueprint"
        row["is_blueprint"] = True
    elif bg == "design":
        row["item_kind"] = "design"
        row["is_blueprint"] = False
    elif bg == "standard":
        if row.get("item_kind") in ("blueprint", "design"):
            row["item_kind"] = ""
        row["is_blueprint"] = False
    _decorate_attachments(row)
    return row


def group_counts(conn, account=""):
    """عدّاد الجروبات لحساب واحد — من غير اسم محدد مفيش عدّاد."""
    counts = {}
    if not account or account == "ALL":
        return [{"key": g, "label": GROUP_LABELS.get(g, g), "count": 0} for g in GROUPS]
    query = "SELECT DISTINCT name, type, category FROM items WHERE account=?"
    inst_query = "SELECT DISTINCT name, asset_id FROM instances WHERE account=?"
    args = [account]
    inst_args = [account]
    # الـ asset_id على جدول الـ instances (مش على أسماء items) — بيفرق في التصنيف
    asset_ids = {}
    for row in conn.execute(inst_query, inst_args).fetchall():
        asset_ids.setdefault(row["name"], row["asset_id"])
    for row in conn.execute(query, args).fetchall():
        try:
            raw = json.loads(row["category"] or "[]")
        except ValueError:
            raw = []
        group = group_for(row["name"], row["type"], raw, asset_ids.get(row["name"]))
        counts[group] = counts.get(group, 0) + 1
    return [{"key": g, "label": GROUP_LABELS.get(g, g), "count": counts.get(g, 0)} for g in GROUPS]
