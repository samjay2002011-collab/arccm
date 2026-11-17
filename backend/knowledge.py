"""معرفة الحساب بالتصنيع: أي مخطط متفعّل يقيناً، وأي وصفة أساسية من أول اللعبة.

**حالتان بس، مفيش تخمين (2026-11-02):** الوصفة بتطلع `True` لو اتحقق واحد من اتنين:
(1) هي في `default_recipes()` — أي وصفة علمتها arctracker `blueprint_locked=false`،
 يعني ملهاش مخطوطة تتلقّط أصلاً وبتنزل مفتوحة مع أي حساب جديد — أو
(2) الحساب نفسه فيه عقدة التفعيل بتاعته في شجرته (أو الرايدر علّمها ✓ بإيده).
غير كده `False` والوصفة بتختفي من المصنع خالص. مفيش `unknown`، مفيش `assume`،
ومفيش «مخطوطة مش في الستاش = متفعّلة».

**المصدر الرسمي:** شجرة `GET /v1/pioneer/inventory` فيها عقدة عائمة (بره أي حاوية)
 لكل مخطط اتفعّل. الفهرس المحلي فيه 99 أصل من النوع ده وبصيغتين، ودي كانت غلطتنا:
  • 96 باسم `Unlock Craft X`
  • 3 باسم معكوس `Unlock X Craft` — `Unlock Surge Coil Craft` و`Unlock Canto Craft`
    و`Unlock Dolabra Craft` — دول كانو بيضيعوا من الفلترة القديمة اللي كانت بتقرأ
    بادئة واحدة بس.
العقدة ليها نفس رقم الأصل عند كل الحسابات (Showstopper `466149401` عند RAIDER74888
وG22)، فاللي عند الحساب = حالة مقروءة من الرد الرسمي، مش استنتاج.

**`default_recipes()` بتتقري من arctracker:** من 166 وصفة في items_db، 70 علمتها
`blueprint_locked = false` — و**صفر** من الـ70 دول ليهم مخطوطة في قايمة الـ91، يعني
مفيش حاجة تتلقّط أصلاً فالوصفة مفتوحة مع أي حساب من أول يوم (حساب G18 مثلاً: شجرته
فيها 0 عقدة تفعيل وبيصنع منهم).
القاعدة القديمة كانت بتضيف شرط «وملهاش عقدة تفعيل في الفهرس» وده كان غلط: اللعبة
بتوزّع أصل `Unlock Craft X` حتى للوصفات المتاحة أساسًا، فـ14 وصفة اتسحبت بالغلط —
منها Shield Recharger و Energy Clip و Zipline و Power Rod و Mod Components.
القياس العكسي (2026-11-02، G22): Shield Recharger في MEDICAL LAB مستوى 3 بزرار
CRAFT شغال وخاماته 1,281/5 و12/1، وشجرته مفيهاش عقدة تفعيل له خالص.

**اللي مالهمش مصدر قرار:** 18 وصفة `blueprint_locked=true` ومفيش ليها عقدة في الفهرس
(Tether Launcher، Advanced Camera، Banjo، Bantam I، Crash Mat، Emperor Gateway
Conduit، Grappling Hook، Powered Descender، Rascal I، Stiletto I، White Flag، Yank
Grenade، Tactical Mk. 3 (Smoke)، فخاخ الرمانات الأربعة، Mountaineer's Detector).
اللعبة بفتحهم بطريقة تانية (مهمة/تاجر/حدث) والعقدة مالهاش وجود، بيفضلوا `False` غير
لو الرايدر علّمهم ✓ بإيده من شاشة المخطوطات.

بيانات اللعبة واسمها على arctracker بيتكتبوا مختلف أحيانًا ("Blue Glowstick" مقابل
"Blue Light Stick"، "Combat Augment T3" مقابل "Combat Mk. 3")، فمطابقة الاسم بتتعمل
بـ `_core()` تحت — وكل عقدة بترجّع `slug` (دليل واحد أكيد للتفعيل و✔) و`gates`.
العقدة اللي بتغطّي أكتر من عنصر (زي `Unlock Craft Extended Barrel` اللي ملهاش نسخة
بتقول II ولا III) بتفضل **بدون إثبات**: ما نرميش ✔ لعنصرين ونكون غلطانين في واحد.

**مستويات المحطات بقت مقروءة (2026-10-31):** محطة الهايدأوت نفسها أصل في شجرة
`GET /v1/pioneer/inventory` — «Gunsmith III» و«Refiner I»… — جوه حاوية
«Workshop Slot»، وكل عائلة ليها نسخة واحدة في الحساب، فالاسم بيقول المستوى.
الـ Workbench جسمه واحد ملوش نسخ طبقات (كل وصفاته مطلوبة مستوى 1) فوجوده = مستوى 1.
اللي مالهاش جسم في الشجرة خالص (Field Bench — دي طاولة الميدان وبتتحسب مستوى 0)
بتفضل على إدخال الرايدر اليدوي.
"""
import os
import re
import time

from . import items_db, pioneer_tree, store

KEY = "knowledge:%s"
# قائمة المخططات المفعلة المقروءة من الشجرة — بتتحدّث مع كل مزامنة.
UNLOCK_KEY = "unlocked:%s"
# مستويات المحطات المقروءة من الشجرة — بتتحدّث مع كل مزامنة.
BENCH_KEY = "bench:%s"

# أجسام محطات الهايدأوت في شجرة البوابة: اسم الأصل -> (المحطة عندنا، المستوى).
# الأسماء دي مقاسة من أشجار 4 حسابات + فهرس الأصول (2848 أصل) — مش أسماء مخترعة.
# المطابقة بالاسم الكامل بالظبط: «Anvil I..IV» أصناف ليها وصفة تصنيع وبتتكرر في
# الحساب، ولو فتحنا الباب على كلمة «anvil» كنا قرينا مستوى من صنف في المخزن.
BENCH_OBJECTS = {
    # الـ Workbench أصل واحد في الفهرس وملوش نسخ طبقات، وكل وصفاته (23) مطلوبة
    # مستوى 1 — يعني المحطة دي مالهاش ترقية أصلاً، وجود الجسم = مستوى 1.
    "workbench": ("workbench", 1),
    "gear bench i": ("equipment_bench", 1),
    "gear bench ii": ("equipment_bench", 2),
    "gear bench iii": ("equipment_bench", 3),
    "gunsmith i": ("weapon_bench", 1),
    "gunsmith ii": ("weapon_bench", 2),
    "gunsmith iii": ("weapon_bench", 3),
    "medical lab i": ("med_station", 1),
    "medical lab ii": ("med_station", 2),
    "medical lab iii": ("med_station", 3),
    "utility station i": ("utility_bench", 1),
    "utility station ii": ("utility_bench", 2),
    "utility station iii": ("utility_bench", 3),
    "explosives station i": ("explosives_bench", 1),
    "explosives station ii": ("explosives_bench", 2),
    "explosives station iii": ("explosives_bench", 3),
    "refiner i": ("refiner", 1),
    "refiner ii": ("refiner", 2),
    "refiner iii": ("refiner", 3),
}
# المحطات اللي بتقرا من السيرفر (الباقي — workbench وin_raid — يدوي).
BENCH_STATIONS = tuple(sorted({key for key, _lv in BENCH_OBJECTS.values()}))
UNLOCK_PREFIX = "Unlock Craft "
UNLOCK_OPEN = "Unlock "
UNLOCK_CLOSE = " Craft"
# آخر أحداث التفعيل/اللقط اللي بنحتفظ بيهم للواجهة.
LOG_MAX = 40

# الوصفات اللي تنزل مفتوحة مع أي حساب جديد = اللي ملهاش مخطوطة خام عند arctracker
# (`blueprint_locked=false`). القياس (2026-11-02): من 166 وصفة، 70 علمتها false،
# و**صفر** من الـ70 دول ليهم مخطوطة في قايمة الـ91 — يعني مفيش حاجة تتلقّط أصلاً.
#
# الشرط القديم كان بيزيد «وملهاش عقدة تفعيل في الفهرس» وده كان غلط: اللعبة بتوزّع
# أصل `Unlock Craft X` حتى للوصفات المتاحة من أول يوم، فـ14 وصفة اتسحبت من القائمة
# بالغلط — منها Shield Recharger، والمستخدم قاسها لايف على G22 (MEDICAL LAB مستوى 3
# وزرار CRAFT شغال) من غير ما تكون العقدة في شجرته.
_RECIPES_CACHE = {"stamp": None, "slugs": frozenset()}


def default_recipes():
    """slugs الوصفات اللي بتيجي مفتوحة مع أي حساب — مقروءة من items_db، مش قايمه مكتوبة."""
    try:
        stamp = os.path.getmtime(items_db.DB_FILE)
    except OSError:
        stamp = -1.0
    if _RECIPES_CACHE["stamp"] != stamp:
        _RECIPES_CACHE.update(stamp=stamp, slugs=frozenset(
            str(row.get("slug") or "") for row in items_db.craftable_rows()
            if row.get("slug") and not row.get("blueprint_locked")))
    return _RECIPES_CACHE["slugs"]


def _default():
    return {"learned": [], "never_found": [], "stations": {}, "seen": [], "events": []}


def _get(conn, account):
    data = dict(_default())
    data.update(store.get_meta(conn, KEY % account) or {})
    return data


def _put(conn, account, data):
    store.set_meta(conn, KEY % account, data)


def unlock_target(label):
    """اسم عقدة التفعيل -> اسم العنصر، أو "" لو العقدة دي مش بتاعة تصنيع.

    الصيغتين المقاستين من الفهرس: "Unlock Craft Zipline" و"Unlock Surge Coil Craft".
    أسماء تانية ب word unlock ("Unlock Level 20"، "OI Unlock Spaceport Rounds"،
    "Unlock Mastery") بتاعة تقدم عام مش مخطوطة، فبتترفض.
    """
    text = str(label or "").strip()
    if text.startswith(UNLOCK_PREFIX):
        return text[len(UNLOCK_PREFIX):].strip()
    if text.startswith(UNLOCK_OPEN) and text.endswith(UNLOCK_CLOSE):
        inner = text[len(UNLOCK_OPEN):-len(UNLOCK_CLOSE)].strip()
        if inner and not inner.startswith("Craft "):
            return inner
    return ""


def scrolls_in_stash(owned_assets, owned_names=None):
    """{target_slug: عدد النسخ في المخزن} للمخطوطات اللي بنعرف أصولها."""
    rows = items_db.blueprint_rows()
    out = {}
    for row in rows:
        target = row.get("target")
        if not target:
            continue
        count = sum(int(owned_assets.get(a, 0) or 0) for a in row.get("asset_ids") or [])
        if not count and owned_names and row.get("name"):
            count = int(owned_names.get(items_db.norm(row["name"]), 0) or 0)
        if count:
            out[target] = out.get(target, 0) + count
    return out


_BP_CACHE = {"stamp": None, "targets": set(), "core": {}, "family": {}}
_RECIPE_CACHE = {"stamp": None, "core": {}, "family": {}, "exact": {}}
_NODE_CACHE = {}


def _core(text, keep_level=True):
    """اسم العنصر -> مجموعة كلمات متساوية مهما اختلفت كتابة اللعبة عن arctracker.

    القياس (٢٠٢٦-١٠-٣١): اسم البوابة بيقول "Combat Augment T3 (Aggressive)" و
    "Blue Glowstick" و"Trigger Nade"، وarctracker بيقول "Combat Mk. 3 (Aggressive)"
    و"Blue Light Stick" و"Trigger 'Nade" — فنوحّد: رقم روماني <-> رقم، "t3" <-> "3"،
    وكلمة augment/mark محذوفة، وglowstick = light stick.
    """
    s = re.sub(r"[^a-z0-9]+", " ", items_db.norm(str(text or "")))
    toks = []
    for tok in s.split():
        if tok in ("augment", "mark", "mk"):
            continue
        if tok == "glowstick":
            toks += ["light", "stick"]
            continue
        tier = re.fullmatch(r"t([1-5])", tok)
        if tier:
            tok = tier.group(1)
        else:
            num = items_db.ROMAN_TO_NUM.get(tok.upper())
            if num and len(tok) <= 3:
                tok = str(num)
        if not keep_level and re.fullmatch(r"[1-5]", tok):
            continue
        toks.append(tok)
    return frozenset(toks)


def _bp_maps():
    """فهارس أسماء الـ ٩١ هدف: تطابق كامل + تطابق عائلة (من غير طبقة)."""
    try:
        stamp = os.path.getmtime(items_db.DB_FILE)
    except OSError:
        stamp = -1.0
    if _BP_CACHE["stamp"] == stamp and _BP_CACHE["targets"]:
        return _BP_CACHE
    targets, core, family = set(), {}, {}
    for row in items_db.blueprint_rows():
        target = row.get("target")
        if not target:
            continue
        targets.add(target)
        label = row.get("target_name") or row.get("name") or ""
        core.setdefault(_core(label), set()).add(target)
        family.setdefault(_core(label, keep_level=False), set()).add(target)
    _BP_CACHE.update(stamp=stamp, targets=targets, core=core, family=family)
    return _BP_CACHE


def _recipe_maps():
    """فهارس أسماء وصفات التصنيع نفسها — للعقد اللي عنصرها مش في قايمة المخطوطات
    (Zipline، Energy Clip، ARC Circuitry…) والاسم هو الدليل الوحيد."""
    try:
        stamp = os.path.getmtime(items_db.DB_FILE)
    except OSError:
        stamp = -1.0
    if _RECIPE_CACHE["stamp"] == stamp and _RECIPE_CACHE["core"]:
        return _RECIPE_CACHE
    exact, core, family = {}, {}, {}
    for row in items_db.craftable_rows():
        slug = str(row.get("slug") or "")
        name = row.get("name") or ""
        if not slug or not name:
            continue
        exact.setdefault(items_db.norm(name), set()).add(slug)
        core.setdefault(_core(name), set()).add(slug)
        family.setdefault(_core(name, keep_level=False), set()).add(slug)
    _RECIPE_CACHE.update(stamp=stamp, exact=exact, core=core, family=family)
    return _RECIPE_CACHE


def _single(lookup, key):
    """العنصر الوحيد اللي المفتاح بيطابقه، أو [] لو غامض أو ملوش مقابل."""
    cands = set((lookup or {}).get(key) or ())
    return sorted(cands) if len(cands) == 1 else []


def _resolve_target(name):
    """اسم عقدة التفعيل -> العنصر اللي بتفتحه.

    "slug" بيتحدّد لما الدليل يكون عنصر واحد بس (ده اللي بيثبت التفعيل وبيحط ✔).
    "gates" بتقول أي مخطوطة العقدة دي مسؤولة عنها — وكتير من أسماء اللعبة بتلمّ
    الطبقات في اسم واحد ("Unlock Craft Extended Barrel" = II و III)، ودي بتسيب
    slug فاضي عشان ما نديش ✔ لعنصرين ونكون غلطانين في واحد.
    """
    key = items_db.norm(name)
    if key in _NODE_CACHE:
        return _NODE_CACHE[key]
    maps = _bp_maps()
    recipes = _recipe_maps()
    row = items_db.find(name=name) or {}
    slug, gates = "", set()
    # الأصول بتفضل محفوظة حتى لو العنصر مش من الـ ٩١ (زي Zipline وSnap Blast):
    # دي اللي بتدي ✔ لبلاطتها في المخزن.
    assets = [str(a) for a in (row.get("asset_ids") or [])]
    found = str(row.get("slug") or "")
    if found in maps["targets"]:
        slug, gates = found, {found}
    else:
        cands = set(maps["core"].get(_core(name)) or ())
        if len(cands) != 1:
            cands |= set(maps["family"].get(_core(name, keep_level=False)) or ())
        if len(cands) != 1:
            # مخطوطة خارج الـ ٩١؟ نطابق الوصفة نفسها بالاسم الكاملة أو الطبقة.
            cands = set(recipes["exact"].get(key) or ())
            if len(cands) != 1:
                cands = set(_single(recipes["core"], _core(name))) or \
                    set(_single(recipes["family"], _core(name, keep_level=False)))
        gates = cands
        if not slug and len(cands) == 1:
            slug = next(iter(cands))
            tgt = items_db.by_slug(slug) or {}
            assets = assets or [str(a) for a in (tgt.get("asset_ids") or [])]
    out = {"slug": slug, "gates": sorted(gates), "assets": assets}
    _NODE_CACHE[key] = out
    return out


def unlocked_rows(tree):
    """قائمة المخططات المفعلة للحساب من شجرة البوابة: عقدة تفعيل واحدة لكل عنصر.

    البوابة بترجّع أرقام أصول بس، فالاسم بييجي من الفهرس المحلي (نفس مصدر الأسماء
    في اللوحة). العقد دي عائمة في الشجرة — مش في خانة — فمفيش نسخة منها بتاعت
    مخزن ولا بتتقل على العرض.
    """
    out, seen = [], set()
    for iid in tree.by_id:
        label = (tree.name_of(iid) or "").strip()
        target = unlock_target(label)
        if not target:
            continue
        key = items_db.norm(target)
        if key in seen:
            continue
        seen.add(key)
        ref = _resolve_target(target)
        out.append({"name": target, "slug": ref["slug"],
                    "gates": list(ref["gates"]), "assets": ref["assets"]})
    return sorted(out, key=lambda r: r["name"].lower())


_UNIVERSE_CACHE = {"key": None, "slugs": set()}


def _universe_stamp():
    """أي سطر جديد في الفهرس = عقد قفل جديدة، فلازم الكاش يتبني من جديد."""
    return (len(pioneer_tree.asset_names()),
            os.path.getmtime(pioneer_tree.ASSET_INDEX_FILE)
            if os.path.isfile(pioneer_tree.ASSET_INDEX_FILE) else 0,
            os.path.getmtime(pioneer_tree.ASSET_LOCAL_FILE)
            if os.path.isfile(pioneer_tree.ASSET_LOCAL_FILE) else 0)


def unlock_universe():
    """كل أسماء عقد التفعيل الموجودة في الفهرس المحلي (عالم اللعبة كامل).

    دي مش حالة حساب — دي بتقول إن للعبة نفسها سجل تفعيل للعنصر ده. اللي ملهوش
    اسم هنا مالوش دليل تفعيل عند أي حساب، حتى لو arctracker قال إنه محتاج مخطوطة.
    """
    out = {}
    for row in pioneer_tree.asset_names().values():
        label = str(row.get("display_name") or row.get("game_asset_name") or "").strip()
        target = unlock_target(label)
        if not target:
            continue
        key = items_db.norm(target)
        if not key or key in out:
            continue
        ref = _resolve_target(target)
        out[key] = {"name": target, "slug": ref["slug"],
                    "gates": list(ref["gates"]), "assets": ref["assets"]}
    return out


def gated_slugs():
    """slugs بتوع العناصر اللي ليها عقدة تفعيل معروفة: البوابة بتفصل في حالتها."""
    stamp = _universe_stamp()
    if _UNIVERSE_CACHE["key"] != stamp:
        slugs = set()
        for ref in unlock_universe().values():
            slugs |= {str(s) for s in ref["gates"] if s}
        _UNIVERSE_CACHE.update(key=stamp, slugs=slugs)
    return _UNIVERSE_CACHE["slugs"]


def remember_unlocked(conn, account, rows):
    """بتتخزّن مع طابع زمني: "قِسنا وطلع صفر" حالة غير "لسه ما قِسناش للحساب ده"."""
    store.set_meta(conn, UNLOCK_KEY % account,
                   {"at": int(time.time()), "rows": list(rows or [])})


def _unlock_meta(conn, account):
    if not account or account == "ALL":
        return None
    return store.get_meta(conn, UNLOCK_KEY % account)


def unlocked(conn, account):
    """قائمة المخططات المفعلة للحساب: العقد اللي قِسناها من الشجرة + حل اسمه دلوقتي.

    الدليل المخزّن هو **اسم العقدة** — و`slug` بتاعها بيتحل من الفهرس المحلي وقت
    القراءة، مش وقت المزامنة. كده أي تحسين في المطابقة (زي "Energy Clip" اللي ما
    كانتش بتتحل) بيشيل أثره على الحسابات القديمة من غير ما نستنى مزامنة جديدة.
    """
    raw = _unlock_meta(conn, account)
    rows = raw.get("rows") if isinstance(raw, dict) else raw
    out = []
    for row in rows or []:
        name = str((row or {}).get("name") or "").strip()
        if not name:
            continue
        ref = _resolve_target(name)
        out.append({"name": name, "slug": ref["slug"],
                    "gates": list(ref["gates"]), "assets": ref["assets"]})
    return out


def node_only_slugs():
    """عناصر ليها عقدة تفعيل في الفهرس بس ملهاش مخطوطة في قايمة الـ 91.

    دي بتاعة اللعبة نفسها (Zipline، Energy Clip، Shield Recharger، ARC Circuitry،
    خامات الريفينر…) — بتتفتح ببحث/محطة/مهمة مش بورقة مخطوطة، فمفيش ليها كارت في
    قايمة المخطوطات. بنضيفها للشاشة عشان التحديد اليدوي ✓ يوصلها: من غيرها لو اللعبة
    فتحت عنصر بالحقيقي ومش معروف بعقدة، بيضل مختفي خالص من غير مخرج.

    الوصفات المفتوحة أساسًا (`default_recipes()`) مستثناة: أصل `Unlock Craft` بتاعها
    موجود في الفهرس رغم إن مفيش مخطوطة ولا حاجة تتفتح — Shield Recharger مثال، فلو
    دخلت هنا الشاشة بتعرضها «مش متفعّلة» وهي شغالة في اللعبة.
    """
    targets = {str(row.get("target") or "") for row in items_db.blueprint_rows()}
    defaults = default_recipes()
    out = []
    for slug in sorted(gated_slugs()):
        if slug and slug not in targets and slug not in defaults and items_db.by_slug(slug):
            out.append(slug)
    return out


def unlock_measured(conn, account):
    """هل قرأنا عقد القفل للحساب ده من البوابة فعلاً؟ الشكل القديم (قائمة) = قِسنا."""
    if not account or account == "ALL":
        return False
    return isinstance(_unlock_meta(conn, account), (dict, list))


def unlocked_index(conn, account):
    """شكل للفرونت: الأصول المفعلة + أسماءها المطبّعة، عشان البلاطة تتعلّم بـ ✔.

    الاسم بيتضاف من المصدرين: اللي كتبه الفهرس على عقدة القفل ("Blue Glowstick")
    واللي كتبه arctracker على العنصر نفسه ("Blue Light Stick") — البلاطة بتتطابق
    بأيّهم.
    """
    rows = unlocked(conn, account)
    assets, names = set(), set()
    for row in rows:
        assets |= {str(a) for a in (row.get("assets") or [])}
        names.add(items_db.norm(row.get("name") or ""))
        slug = str(row.get("slug") or "")
        tgt = items_db.by_slug(slug) if slug else None
        if tgt:
            names.add(items_db.norm(tgt.get("name") or ""))
            assets |= {str(a) for a in (tgt.get("asset_ids") or [])}
    return {"assets": sorted(assets), "names": sorted(names - {""}), "count": len(rows)}


def proven_keys(conn, account):
    """الدليل القطعي للتفعيل عند الحساب ده: {slugs, أسماء, أنوية} — عنصر واحد للعقدة.

    العقدة اللي بيلفّ أكتر من طبقة (زي `Unlock Craft Extended Barrel` = II و III) ما
    بتثبت ولا واحد منهم: البوابة بتدي اسم واحد، فنحسبها غامضة ونسيبها من غير إثبات
    أحسن ما نرميش ✔ لعنصرين ونكون غلطانين في واحد.
    التحديد اليدوي ✓ بيجااز الدليل نفسه — ده قرار الرايدر مش استنتاج من الموقع.
    التطابق بيحصل بالاسم الكامل أو بالنواة الحساسة للرقم (من غير طبقة) عشان طبقة
    غلط ما تتفعّلش مع الطبقة الصح.
    """
    slugs, names, cores = set(), set(), set()

    def add_proof(slug, *labels):
        slugs.add(slug)
        for label in labels:
            text = str(label or "")
            if text:
                names.add(items_db.norm(text))
                cores.add(_core(text))

    for row in unlocked(conn, account):
        gates = [str(g) for g in (row.get("gates") or []) if g]
        slug = str(row.get("slug") or "") or (gates[0] if len(gates) == 1 else "")
        if not slug:
            continue
        add_proof(slug, row.get("name"), (items_db.by_slug(slug) or {}).get("name"))
    for slug in (_get(conn, account).get("learned") or []):
        slug = str(slug or "")
        if slug:
            add_proof(slug, (items_db.by_slug(slug) or {}).get("name"))
    return {"slugs": slugs, "names": names, "cores": cores}


def craft_access(conn, account, owned_assets=None, owned_names=None):
    """{recipe_slug: True/False} لكل وصفات التصنيع — الشرط الصارم للورك شوب.

    True لو: ملهاش مخطوطة خام عند arctracker (`default_recipes()`) أو الحساب عنده
    عقدة تفعيلها (أو علّمها ✓).
    False لأي حاجة تانية — والوصفة بتختفي من المصنع، مش بتتحول لـ "مقفولة".
    """
    proven = proven_keys(conn, account)
    defaults = default_recipes()
    out = {}
    for row in items_db.craftable_rows():
        slug = str(row.get("slug") or "")
        name = str(row.get("name") or "")
        out[slug] = bool(slug in defaults or slug in proven["slugs"]
                        or items_db.norm(name) in proven["names"]
                        or _core(name) in proven["cores"])
    return out


def blueprint_state(conn, account, owned_assets, owned_names=None):
    """{target_slug: "learned"/"in_stash"/"not_learned"} لكل عنصر للعبة سجل تفعيل له.

    حالتان حقيقيتان بس: `learned` = عند الحساب عقدة التفعيل بتاعته (أو الرايدر
    علّمها ✓). `in_stash` = المخطوطة لسه في المخزن — دي بالظبط علامة «متفعّلش».
    `not_learned` = مفيش أي إثبات. مفيش `unknown` ولا افتراض: اللي مالهاش عقدة
    تفعيل في الفهرس بتتحسب مش متفعّلة، وده اللي بيخلي Tether Launcher يختفي من
    حساب ما فتحهاش.
    """
    data = _get(conn, account)
    forced = set(data.get("learned") or [])
    missing = set(data.get("never_found") or [])
    in_stash = scrolls_in_stash(owned_assets or {}, owned_names)
    rows = unlocked(conn, account)
    proven_slugs = {str(r.get("slug") or "") for r in rows} - {""}
    proven_assets = {str(a) for r in rows for a in (r.get("assets") or [])}
    proven_names = {items_db.norm(str(r.get("name") or "")) for r in rows} - {""}
    out = {}
    targets = [(row.get("target"), row) for row in items_db.blueprint_rows() if row.get("target")]
    targets += [(slug, None) for slug in node_only_slugs()]
    for target, row in targets:
        if target in out:
            continue
        tgt = items_db.by_slug(target) or {}
        tgt_assets = {str(a) for a in (tgt.get("asset_ids") or [])}
        name_proof = items_db.norm(tgt.get("name") or "") in proven_names
        if (target in proven_slugs or (tgt_assets & proven_assets) or name_proof
                or target in forced) and target not in missing:
            out[target] = "learned"
        elif row and in_stash.get(target):
            out[target] = "in_stash"
        else:
            out[target] = "not_learned"
    return out


def owned_map(conn, account):
    """{asset_id: كمية} لكل اللي في مخزن الحساب (ستاش + شنطة + لوداوت + أوفر فلو)."""
    if not account or account == "ALL":
        return {}
    rows = conn.execute("SELECT asset_id, SUM(qty) q FROM instances "
                        "WHERE account=? AND asset_id IS NOT NULL AND asset_id <> '' GROUP BY asset_id",
                        (account,)).fetchall()
    return {str(r["asset_id"]): int(r["q"] or 0) for r in rows}


def observe(conn, account):
    """بتتنادى بعد كل مزامنة: تلاحظ المخطوطات اللي اختفت (اتفعّلت) أو ظهرت جديد.

    الحفظ ده بقى سجل أحداث للعرض بس — صانع القرار الوحيد هو عقدة التفعيل في الشجرة.
    """
    if not account or account == "ALL":
        return {}
    data = _get(conn, account)
    now = set(scrolls_in_stash(owned_map(conn, account)))
    before = set(data.get("seen") or [])
    activated = sorted(before - now)
    discovered = sorted(now - before)
    events = data.get("events") or []
    for target in activated:
        events.append({"target": target, "kind": "activated", "at": int(time.time())})
    for target in discovered:
        events.append({"target": target, "kind": "discovered", "at": int(time.time())})
    if events:
        data["events"] = events[-LOG_MAX:]
    data["seen"] = sorted(now)
    data["never_found"] = [t for t in (data.get("never_found") or []) if t not in now]
    _put(conn, account, data)
    return {"activated": activated, "discovered": discovered}


def mark(conn, account, target, state):
    """تحديد يدوي من شاشة المخطوطات: learned / not_learned / auto (يشيل التحديد).

    اليد دي قرار من الرايدر نفسها، فما تتعاملش كتخمين: `learned` بتدي الوصفة،
    و`not_learned` بتثبّت إنها مش متفعّلة حتى لو المخطوطة طلعت من المخزن.
    """
    if not account or account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account first."}
    data = _get(conn, account)
    learned = set(data.get("learned") or [])
    missing = set(data.get("never_found") or [])
    learned.discard(target)
    missing.discard(target)
    if state == "learned":
        learned.add(target)
    elif state in ("never_found", "not_learned"):
        missing.add(target)
    elif state not in ("auto", "", None):
        return {"ok": False, "error": "bad_state", "detail": "Unknown state."}
    data["learned"] = sorted(learned)
    data["never_found"] = sorted(missing)
    _put(conn, account, data)
    return {"ok": True, "account": account, "target": target, "state": state or "auto"}


def station_levels(conn, account):
    """مستوى كل محطة: اللي قريناه من الشجرة أولاً، واللي الرايدر كتبه بإيده بعدين."""
    measured = bench_levels(conn, account)
    manual = dict(_get(conn, account).get("stations") or {})
    out = dict(manual)
    out.update(measured)
    return out


def station_level_sources(conn, account):
    """منين جه كل مستوى: server = مقروء من البوابة، manual = إدخال الرايدر."""
    measured = bench_levels(conn, account)
    manual = _get(conn, account).get("stations") or {}
    out = {}
    for key in set(list(measured) + list(manual)):
        out[key] = "server" if key in measured else "manual"
    return out


def bench_object(name):
    """اسم أصل في الشجرة -> (المحطة، مستواها) | None.

    المطابقة بالاسم الكامل بالظبط (مش بكلمة مفتاحية): «Crude Explosives» و
    «Explosive Mine» أصناف مش محطات، و«Anvil I..IV» أصناف ليها وصفة تصنيع وبتتكرر
    في الحساب، فلو فتحنا المطابقة على كلمة «explosive» أو «anvil» هنقرأ مستوى غلط.
    """
    return BENCH_OBJECTS.get(items_db.norm(name or ""))


def bench_levels_from_tree(tree):
    """مستويات المحطات المقروءة من شجرة الحساب: جسم المحطة عقدة واحدة لكل عائلة.

    القياس على 4 حسابات (inspection/bench_debug.py): كل عائلة محطة ليها نسخة واحدة
    بس في الشجرة، وأبوها حاوية اسمها «Workshop Slot» — يعني دي أجسام الهايدأوت نفسها
    مش أصناف في المخزن (malهاش وصفة تصنيع في arctracker خالص). بنشيل الفلتر على
    الأب لأن الشجرة القديمة كانت بتوهمنا إنها طافية، وبنكتفي بالمطابقة بالاسم
    الكامل: «Anvil I..IV» أصناف حقيقية وموجودة في نفس الحسابات، فاسمها مش في
    الجدول. لو ظهرت أكتر من نسخة بنأخذ الأعلى (ما نفترضش إن الأدنى هو الجاري).
    """
    out = {}
    for iid in tree.by_id:
        hit = bench_object(tree.name_of(iid))
        if not hit:
            continue
        key, level = hit
        if level > int(out.get(key) or 0):
            out[key] = level
    return out


def remember_bench_levels(conn, account, levels):
    """بنخزّن القياس بطابع زمني: صفر مقاس غير «لسه ما قِسناش»."""
    if not account or account == "ALL":
        return
    store.set_meta(conn, BENCH_KEY % account,
                   {"at": int(time.time()), "levels": dict(levels or {})})


def bench_levels(conn, account):
    if not account or account == "ALL":
        return {}
    meta = store.get_meta(conn, BENCH_KEY % account)
    if isinstance(meta, dict):
        return {str(k): int(v) for k, v in (meta.get("levels") or {}).items()}
    return {}


def bench_measured_at(conn, account):
    meta = store.get_meta(conn, BENCH_KEY % account) if account and account != "ALL" else None
    return int(meta.get("at") or 0) if isinstance(meta, dict) else 0


def set_station_level(conn, account, station, level):
    if not account or account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account first."}
    data = _get(conn, account)
    stations = dict(data.get("stations") or {})
    try:
        value = int(level)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_level", "detail": "Invalid level."}
    if value < 0:
        return {"ok": False, "error": "bad_level", "detail": "Invalid level."}
    if value:
        stations[station] = value
    else:
        stations.pop(station, None)
    data["stations"] = stations
    _put(conn, account, data)
    return {"ok": True, "account": account, "stations": stations}


def summary(conn, account, owned_assets, owned_names=None):
    """أرقام شاشة المخطوطات: كام متفعّل باليقين، كام في الستاش، كام مش متفعّلة."""
    state = blueprint_state(conn, account, owned_assets, owned_names)
    counts = {"learned": 0, "in_stash": 0, "not_learned": 0}
    for value in state.values():
        counts[value] = counts.get(value, 0) + 1
    counts["total"] = len(state)
    counts["measured"] = unlock_measured(conn, account)
    counts["default_recipes"] = len(default_recipes())
    return counts


def cards(conn, account, owned_assets, owned_names=None):
    """كروت شاشة المخطوطات: اسم العنصر + حالته + رسمه + هل الوصفة بتظهر ولا لأ.

    قايمة الـ 91 فيها كل عنصر ليها اللعبة مخطوطة، ووراها نضيف عناصر «عقدة بس»
    (ملهاش مخطوطة في اللعبة لكن ليها سجل تفعيل) عشان التحديد اليدوي يوصلها.
    """
    state = blueprint_state(conn, account, owned_assets, owned_names)
    in_stash = scrolls_in_stash(owned_assets, owned_names)
    access = craft_access(conn, account, owned_assets, owned_names)
    out = []
    seen = set()
    for row in items_db.blueprint_rows():
        target = row.get("target")
        if not target:
            continue
        seen.add(target)
        out.append({
            "blueprint": row.get("slug"), "target": target,
            "name": row.get("target_name") or row.get("name"), "image": row.get("target_image") or row.get("image"),
            "rarity": row.get("target_rarity"), "state": state.get(target), "copies": in_stash.get(target, 0),
            "craftable": bool(access.get(target)), "has_blueprint": True,
            "stations": row.get("stations") or [], "station_level": row.get("station_level"),
        })
    for slug in node_only_slugs():
        if slug in seen:
            continue
        tgt = items_db.by_slug(slug) or {}
        out.append({
            "blueprint": None, "target": slug, "name": tgt.get("name") or slug,
            "image": items_db.icon_for(tgt), "rarity": tgt.get("rarity"),
            "state": state.get(slug), "copies": 0, "craftable": bool(access.get(slug)),
            "has_blueprint": False,
            "stations": tgt.get("craft_bench") or [], "station_level": tgt.get("station_level"),
        })
    return out
