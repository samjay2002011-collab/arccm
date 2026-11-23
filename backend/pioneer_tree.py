"""شجرة المخزن الرسمية: الأماكن الحقيقية وخانات النقل.

البوابة بترجع كل الأصول كشجرة — كل عنصر عنده slots فيها instanceId لأولاده.
الموديول ده بيحوّل الشجرة لخريطة أماكن (ستاش / شنطة الـ loadout المفعّل / خانات
التجهيز) وبيستخدمها pioneer_sync للعرض و pioneer_write للنقل.

مفيش أي كتابة هنا: كله قراءة وتحليل للـ payload اللي راجع من GET /v1/pioneer/inventory.
"""
import csv
import os
import re
import threading

from . import config

ASSET_INDEX_FILE = os.path.join(config.DATA_DIR, "catalog", "asset_index.csv")
ASSET_LOCAL_FILE = os.path.join(config.DATA_DIR, "catalog", "asset_index_local.csv")
SLOT_PATTERNS = (
    ("gun_1", ("weapon 1", "firearm 1")),
    ("gun_2", ("weapon 2", "firearm 2")),
    ("shield", ("shield",)),
    ("melee", ("melee",)),
    ("backpack", ("backpack",)),
    ("quick_use", ("quick use",)),
    ("safe_pocket", ("safe pocket",)),
    # خانة الدرع الحقيقية في اللوداوت اسمها "Light Shield Slot" / "Medium Shield Slot"
    # (مش "Shield Slot" زي الحاوية اللي فوقيها)، وخانة السلاح اسمها "Firearm Slot".
    # من غير السطرين دول القسم بيطلع بره الخريطة والخانة تبان «لسه ما اتفعّلتش».
    ("shield", ("shield slot",)),
    ("gun_1", ("firearm slot",)),
    # حاوية «Auxiliary» جوه شجرة اللوداوت = خانات الأتاتشمنت بتاعت الأوجمنت
    # (Looting Mk. 2 مثلا 3 خانات). من غيرها القسم ده بيبان فاضي خالص.
    ("augmented_slots", ("auxiliary",)),
)

_cache = {"key": None, "names": {}}


class TreeError(Exception):
    def __init__(self, code, error, detail):
        Exception.__init__(self, detail)
        self.code = code
        self.error = error
        self.detail = detail


def asset_names():
    """game_asset_id -> صف الفهرس (display_name / game_asset_name).

    الفهرس العام بتاع asset-index متوقّف عند أبريل، فأي بند ينزل في باتش جديد
    بيبقى من غير اسم. بندمج فوقه data/catalog/asset_index_local.csv (نفس الأعمدة)
    وهو اللي بنكتب فيه البنود اللي بنتعرّف عليها من شجرة حسابك.

    الملف المحلي ممكن ميكونش موجود لسه، فمفتاح الكاش لازم يفضل قيمة ثابتة مش None
    (None كانت بتتطابق مع "الكاش فاضي" وترجع خريطة فاضية للأبد)."""
    def stamp(f):
        try:
            return os.path.getmtime(f)
        except OSError:
            return -1.0
    files = [ASSET_INDEX_FILE, ASSET_LOCAL_FILE]
    key = tuple(stamp(f) for f in files)
    if _cache["key"] == key:
        return _cache["names"]
    names = {}
    for path in files:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    asset_id = row.get("game_asset_id")
                    if asset_id:
                        names[asset_id] = row
        except OSError:
            pass
    _cache.update({"key": key, "names": names})
    return names


_lock = threading.Lock()


def remember(asset_id, display_name, hint=""):
    """يسجّل اسم بند جديد في الفهرس المحلي.

    البوابة بترجع أرقام asset ids بس، والفهرس العام متوقّف عند أبريل — أول ما
    نعرف id قطعة نزلت في باتش، السطر ده بيرجعها باسمها وأيقونتها وتصنيفها."""
    asset_id = str(asset_id or "").strip()
    display_name = str(display_name or "").strip()
    if not re.fullmatch(r"-?\d{1,12}", asset_id) or not display_name:
        raise ValueError("asset id must be a numeric string and the name must not be empty")
    with _lock:
        rows, seen = [], False
        if os.path.isfile(ASSET_LOCAL_FILE):
            with open(ASSET_LOCAL_FILE, encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
        for row in rows:
            if row.get("game_asset_id") == asset_id:
                row["display_name"], row["hint"] = display_name, hint
                seen = True
        if not seen:
            rows.append({"game_asset_id": asset_id, "game_asset_name": "",
                         "display_name": display_name, "hint": hint})
        tmp = ASSET_LOCAL_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["game_asset_id", "game_asset_name",
                                                    "display_name", "hint"])
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, ASSET_LOCAL_FILE)
    asset_names()          # يسري فوراً: مفتاح الكاش اتغير
    return {"asset_id": asset_id, "display_name": display_name,
            "local_rows": len(rows)}


class Tree:
    def __init__(self, items):
        self.items = [e for e in (items or []) if isinstance(e, dict) and e.get("instanceId")]
        self.by_id = {str(e["instanceId"]): e for e in self.items}
        self.kids, self.parent = {}, {}
        for entry in self.items:
            iid = str(entry["instanceId"])
            kids = [str(s) for s in (entry.get("slots") or []) if s and str(s) in self.by_id]
            self.kids[iid] = kids
            for kid in kids:
                self.parent[kid] = iid
        self._names = asset_names()

    def copy(self):
        """نسخة مستقلة بنفس المحتوى — للتخطيط على الاحتمالات قبل الكتابة."""
        other = object.__new__(Tree)
        other.items = self.items
        other.by_id = self.by_id
        other.kids = {k: list(v) for k, v in self.kids.items()}
        other.parent = dict(self.parent)
        other._names = self._names
        return other

    def _row(self, iid):
        entry = self.by_id.get(str(iid)) or {}
        return self._names.get(str(entry.get("gameAssetId"))) or {}

    def label(self, iid):
        row = self._row(iid)
        return (row.get("display_name") or row.get("game_asset_name") or str(iid)).strip()

    def name_of(self, iid):
        row = self._row(iid)
        return (row.get("display_name") or row.get("game_asset_name") or "").strip()

    def children(self, iid):
        return list(self.kids.get(str(iid)) or [])

    def first_child(self, iid):
        kids = self.children(iid)
        return kids[0] if kids else ""

    def roots(self):
        return [i for i in self.kids if i not in self.parent]

    def find_child(self, iid, *needles):
        for kid in self.children(iid):
            low = self.label(kid).lower()
            if all(needle in low for needle in needles):
                return kid
        return ""

    def find_descendant(self, iid, *needles):
        stack, seen = [str(iid)], set()
        while stack:
            cur = stack.pop(0)
            if cur in seen:
                continue
            seen.add(cur)
            if cur != str(iid) and all(needle in self.label(cur).lower() for needle in needles):
                return cur
            stack.extend(self.children(cur))
        return ""

    def updated_at(self, iid):
        try:
            return int(self.by_id.get(str(iid), {}).get("updatedAt") or 0)
        except (TypeError, ValueError):
            return 0

    def amount(self, iid):
        """قيمة amount اللي البوابة بتطلبها مع كل update — الخانات دايمًا 1."""
        try:
            value = int(self.by_id.get(str(iid), {}).get("amount") or 1)
        except (TypeError, ValueError):
            return 1
        return value if value > 0 else 1

    def subtree_updated(self, iid):
        best, stack, seen = 0, [str(iid)], set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            best = max(best, self.updated_at(cur))
            stack.extend(self.children(cur))
        return best


def _slot_key(label):
    low = label.lower()
    # أخص أولاً: "Melee Weapon Slot" فيه "weapon" وعشان كده لازم يتقري قبل
    # أي نمط عام للسلاح.
    if "melee" in low:
        return "melee"
    if "backpack" in low:
        return "backpack"
    for key, needles in SLOT_PATTERNS:
        if any(needle in low for needle in needles):
            return key
    return ""


slot_key = _slot_key


def _filled_items(tree, node):
    """عدد الخانات المشغولة داخل عقدة loadout (بدون عدّ الـ wrappers نفسها)."""
    count = 0
    for slot in tree.children(node):
        key = _slot_key(tree.label(slot))
        if not key:
            continue
        container = tree.first_child(slot)
        if key == "backpack":
            for item_slot in tree.children(container):
                if tree.first_child(item_slot):
                    count += 1
            continue
        for content in tree.children(container):
            if tree.first_child(content):
                count += 1
    return count


def _equipment(tree, node):
    out = {}
    for slot in tree.children(node):
        key = _slot_key(tree.label(slot))
        if not key:
            continue
        container = tree.first_child(slot)
        wrappers = tree.children(container) if container else []
        if key != "backpack" and not wrappers:
            wrappers = [slot]
        out[key] = {"container": container,
                    "slots": [{"wrapper": w, "item": tree.first_child(w)} for w in wrappers]}
    return out


BASE_LOADOUT_LABEL = "equipped loadout"


def equipped_augment(tree, inventory_root):
    """عقدة الأوجمنت المجهّز تحت Inventory Root — أو "" لو مفيش أوجمنت في الخانة."""
    slot = tree.find_descendant(inventory_root, "equipped augment slot")
    return (tree.first_child(slot) if slot else "") or ""


def _base_loadout(tree, pointer, inventory_root):
    """لوداوت Equipped Loadout القياسي: الشنطة الأساسية (10 خانات) الي اللعبة
    بتقرأها وهي من غير أوجمنت. بيجي جذر مستقل أو ولد تحت الخانة المجهّزة."""
    if tree.label(pointer).strip().lower() == BASE_LOADOUT_LABEL:
        return pointer
    for node in tree.roots() + tree.children(inventory_root):
        if tree.label(node).strip().lower() == BASE_LOADOUT_LABEL and tree.find_child(node, "backpack slot"):
            return node
    return ""


def _norm_name(text):
    """اسم للمقارنة: حروف وأرقام بس — "Looting MK. 3 (Survivor)" == "Looting Mk. 3 (Survivor)"."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _augment_loadout(tree, inventory_root, augment_id):
    """شجرة اللوداوت الي باسم الأوجمنت المجهّز — واحدة لكل أوجمنت (قياس لايف 2026-11-05).

    الخانة المجهّزة بتفضل شايلة آخر أوجمنت اتلمس: كانت لسه ماسكة
    "Looting Mk. 2" الفاضية بينما الرايد الحيّ في شجرة "Looting Mk. 3 (…)".
    """
    want = _norm_name(tree.name_of(augment_id))
    if not want:
        return ""
    cands = [iid for iid in (str(e["instanceId"]) for e in tree.items)
             if iid != inventory_root and tree.find_child(iid, "backpack slot")]
    for iid in cands:
        if _norm_name(tree.label(iid)) == want:
            return iid
    core = want[:-len("augment")] if want.endswith("augment") and len(want) > 7 else want
    loose = [iid for iid in cands
             if core and (core in _norm_name(tree.label(iid))
                          or _norm_name(tree.label(iid)) in core)]
    if len(loose) > 1:
        # "Free Loadout Augment" يطابق "Free Loadout" و"Tactical Free Loadout"
        # و"Looting Free Loadout" — الاتنين الأولانيين تيمبليتات فاضية، والحية
        # هي الوحيدة اللي فيها قطع (مقيس 2026-11-13: 20 قطعة جواها).
        filled = [iid for iid in loose if _filled_items(tree, iid)]
        loose = filled if len(filled) == 1 else published_loose(tree, loose)
    return loose[0] if len(loose) == 1 else ""


def published_loose(tree, ids):
    """أحدث شجرة في المجموعة — آخر لوداوت لمسته اللعبة (updated_at لأعمق ولد)."""
    scored = sorted(((tree.subtree_updated(iid), iid) for iid in ids), reverse=True)
    if not scored or scored[0][0] <= 0:
        return []
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return []
    return [scored[0][1]]


def _active_loadout(tree, inventory_root):
    """الـ loadout الحي = الحاوية الي اللعبة بتقرأها وبتكتب فيها الرايد.

    القياس لايف 2026-10-29 على تلات حسابات: خانة "equipped loadout container
    slot" بتفضل شايلة آخر أوجمنت اتلمس في اللوحة حتى بعد ما يتفصل — فمتابعة
    المؤشر وحدها كانت بتعرض شنطة فاضية بينما شنطة اللعبة فيها غنائم الرايد
    (Candleberries في الخانة التاسعة كانت في السيرفر واللوحة مافيةاش).
    فالقاعدة: فيه أوجمنت مجهّز → شجرته هي الوجهة، وبنجيبها بالاسم لأن المؤشر
    بيغلط (الحالة اللي فوقا). مفيش أوجمنت → الشجرة القياسية
    "Equipped Loadout" هي الحيّة، حتى لو المؤشر لسه ماسك شجرة أوجمنت قديمة.
    المسار الاحتياطي بيفضل بس للحالة الي مافيهوش أي حاوية معروفة أصلًا.
    """
    equipped_slot = tree.find_child(inventory_root, "equipped loadout container slot")
    equipped = tree.first_child(equipped_slot)
    augment = equipped_augment(tree, inventory_root)
    if augment:
        own = _augment_loadout(tree, inventory_root, augment)
        if own:
            return own, "equipped" if own == equipped else "augment_loadout"
    if equipped:
        if not augment:
            base = _base_loadout(tree, equipped, inventory_root)
            if base:
                return base, "base"
        return equipped, "equipped"
    best = None
    for root in tree.roots():
        if root == inventory_root:
            continue
        if tree.label(root).lower().startswith("da_inventory_lf_raider"):
            continue
        if not tree.find_child(root, "backpack slot"):
            continue
        filled = _filled_items(tree, root)
        if not filled:
            continue
        score = (tree.subtree_updated(root), filled)
        if best is None or score > best[0]:
            best = (score, root)
    if best:
        return best[1], "active_tree"
    return equipped, "empty"


def equipped_container(tree):
    """الحاوية الي اللعبة بتقرأها فعلاً — نفس اختيار layout() بالظبط.

    لازم يفضل مطابق: التحقق بعد أي كتابة للشنطة بيقارن بمكان تاني كان بيرفض
    قطع حطّها اللعبة نفسها في الشنطة الأساسية.
    """
    inv = next((r for r in tree.roots()
                if tree.label(r).strip().lower() == "inventory root"), "")
    if not inv:
        return ""
    return _active_loadout(tree, inv)[0]


def active_containers(tree):
    """الحاويات الي اللعبة بتقرأها: شجرة اللوداوت المفعّلة + خانة الأوجمنت المجهّزة.

    خانة الأوجمنت بتقع برّه شجرة الـ loadout (تحت Equipped Augment Container
    مباشرة) — فالتحقق بعد الكتابة لازم يقبل الحاوية دي بالذات، مش أي عقدة تحت
    Inventory Root، وإلا تجهيز أوجمنت من الموقع بيرفض نفسه ويرجّع القطعة.
    """
    out = [equipped_container(tree)]
    inv = next((r for r in tree.roots()
                if tree.label(r).strip().lower() == "inventory root"), "")
    cur = tree.find_descendant(inv, "equipped augment slot") if inv else ""
    while cur and "augment" in tree.label(cur).lower():
        # بنطلع للأب لحد ما نخرج سلسلة الأوجمنت: حاوية الأوجمنت المجهّزة نفسها
        # مسموحة، أما Inventory Root فبيرفض — لو أضفناه الحارس ملالوش معنى.
        out.append(cur)
        cur = tree.parent.get(cur) or ""
    return [n for n in out if n]


def in_subtree(tree, node, root):
    """عقدة جوا شجرة معينة؟ (بنطلع للأب — الأباء بيفضلوا ثابتين فده أرخص من النزول)."""
    if not node or not root:
        return False
    cur, seen = node, set()
    while cur and cur not in seen:
        if cur == root:
            return True
        seen.add(cur)
        cur = tree.parent.get(cur) or ""
    return False


def layout(tree):
    """خريطة أماكن كاملة: ستاش، شنطة الـ loadout، خانات التجهيز، والأوجمنت."""
    inventory_root = ""
    for root in tree.roots():
        if tree.label(root).lower() == "inventory root":
            inventory_root = root
            break
    if not inventory_root:
        raise TreeError(502, "tree_root_missing", "The official stash tree has no Inventory Root.")
    stash_slot = tree.find_child(inventory_root, "stash container slot")
    stash_node = tree.first_child(stash_slot)
    if not stash_node:
        raise TreeError(502, "stash_missing", "There is no Stash in the official stash tree.")
    loadout_node, mode = _active_loadout(tree, inventory_root)
    eq_slot = tree.find_child(inventory_root, "equipped loadout container slot")
    equipped_node = tree.first_child(eq_slot) if eq_slot else ""
    equipment = _equipment(tree, loadout_node) if loadout_node else {}
    backpack = equipment.get("backpack") or {"container": "", "slots": []}
    augment = None
    augment_slot = tree.find_descendant(inventory_root, "equipped augment slot")
    if augment_slot:
        item = tree.first_child(augment_slot)
        augment = {"wrapper": augment_slot, "item": item}
        # خانة الأوجمنت برّه شجرة الـ loadout (تحت Inventory Root) — لازم تتضاف
        # عشان النقل ليها يبقى ممكن زي أي خانة تجهيز تانية، حتى وهي فاضية.
        equipment["augment"] = {"container": augment_slot,
                                "slots": [{"wrapper": augment_slot, "item": item}]}
    return {
        "inventory_root": inventory_root,
        "stash": {"container": stash_node, "slots": tree.children(stash_node)},
        "backpack": {"container": backpack["container"], "slots": backpack["slots"],
                     "loadout": tree.label(loadout_node) if loadout_node else ""},
        "loadout": {"node": loadout_node,
                    "name": tree.label(loadout_node) if loadout_node else "",
                    "mode": mode,
                    "equipped_node": equipped_node,
                    "equipped_name": tree.label(equipped_node) if equipped_node else "",
                    "pointed": mode != "active_tree",
                    "slots": {k: v["slots"] for k, v in equipment.items() if k != "backpack"}},
        "augment": augment,
    }


def _empty_wrapper(tree, wrappers):
    for wrapper in wrappers:
        if not tree.first_child(wrapper):
            return wrapper
    return ""


def _destinations(tree, wrappers, sources, target_wrapper_id, allow_occupied=False,
                  fallback_if_full=False):
    """خانة فاضية لكل عنصر — كل خانة بتاخد عنصر واحد بس.

    allow_occupied للخانة المجهّزة الأوجمنت: البوابة بتطلب أب واحد للقطعة الجديدة
    وترجّع القديمة لنفس خانتها لوحدها (مقيس لايف 2026-11-04)، فالحركة أمر واحد
    ومش محتاجة خانة فاضية في الستاش — والستاش وهو 280/280 كان بيمنل أي تبديل.

    fallback_if_full للقطعة الناتجة من تقسيم: الطالب مش بيلزقها بخانة معيّنة،
    الخانة دي كانت رايبة وقت القراية بس القطعة المفصولة نزلت فيها فعلاً (البوابة
    بتختار هي)، فبدل ما نرفض بـ slot_occupied بناخد أول خانة فاضية فعلاً.
    """
    if target_wrapper_id:
        if target_wrapper_id not in wrappers:
            raise TreeError(400, "bad_wrapper", "The requested cell does not belong to the destination.")
        # الخانة المليانة هي نفسها الهدف في التبديل: اللي جواها بيرجع لخانته من
        # عند البوابة بنفس الطلب (نفس منطق تبديل الأوجمنت المقيس على البوابة)،
        # فالطلب الواحد بيحط الاتنين في نفس الوقت — وده اللي بيشتغل في الستاش
        # وهو 280/280.
        if not fallback_if_full:
            if len(sources) > 1:
                raise TreeError(400, "one_slot_per_item",
                                "Every move needs one empty cell per item — pick a single item or leave the cell empty.")
            return [target_wrapper_id]
    dests, taken = [], set()
    blocked = set(sources)
    for _ in sources:
        wrapper = _empty_wrapper(tree, [w for w in wrappers if w not in taken and w not in blocked])
        if not wrapper and allow_occupied:
            # خانة الأوجمنت واحدة ومش فاضية: التبديل بنفس الخانة، والقطعة المطرودة
            # بترجع لخانتها في الستاش من عند البوابة (مفيش طلب إضافي ليها).
            wrapper = next((w for w in wrappers if w not in taken and w not in blocked), "")
        if not wrapper:
            raise TreeError(409, "no_empty_target", "Not enough empty cells in the destination.")
        taken.add(wrapper)
        dests.append(wrapper)
    return dests


def merge_plan(tree, asset_id, limit=0, max_moves=40):
    """تحليل كثافة أكوام عنصر واحد + حركات تقريبها من بعضها.

    الدمج نفسه (تغيير كمية كوم) مقفول على بوابة Embark — مقيس لايف 2026-10-28:
    update بأي amount مختلف عن الحالي = INVALID_ARGUMENT، والأنواع combine/split/
    stack_merge اللي بيبعتها مواقع تانية مالهاش وجود في الـenum بتاع بوابة
    Pioneer (الـenum كله: update/create/delete/recycle/scrap/repair). فأكتر حاجة
    تنفع من بره اللعبة: نجيب كل الأكوام على خانات جنب بعضها، فاللمة جوه اللعبة
    تبقى سحب واحد.
    """
    asset = str(asset_id)
    lay = layout(tree)
    cells = [str(c) for c in lay["stash"]["slots"]]
    if not cells:
        raise TreeError(409, "no_stash", "No stash cells in the official tree.")
    index = {c: i for i, c in enumerate(cells)}

    def is_stack(iid):
        row = tree.by_id.get(str(iid)) or {}
        return str(row.get("gameAssetId")) == asset and not row.get("slots")

    stacks = []
    for cell in cells:
        item = tree.first_child(cell)
        if item and is_stack(item):
            stacks.append((cell, str(item), int(tree.amount(item) or 1)))
    loose = [str(i) for i in tree.by_id if is_stack(i) and not tree.parent.get(i)]
    if len(stacks) + len(loose) < 2:
        raise TreeError(409, "nothing_to_gather",
                        "There is only one stack of this item — nothing to gather.")

    # كثافة التغليف: التوزيع اللي اللعبة نفسها بتوصله لما تلمّ كل حاجة.
    amounts = sorted([a for _, _, a in stacks] +
                     [int(tree.amount(i) or 1) for i in loose], reverse=True)
    units = sum(amounts)
    cap = max(int(limit or 0), amounts[0])
    ideal = [cap] * (units // cap)
    if units % cap:
        ideal.append(units % cap)
    packed = amounts == ideal

    anchor_cell = max(stacks, key=lambda s: s[2])[0] if stacks else cells[0]
    anchor = index.get(anchor_cell, 0)
    own = {cell for cell, _, _ in stacks}
    free = [c for c in cells if not tree.first_child(c)]
    # المرشّحين = خانات أكوامنا نفسها + الخانات الفاضية، مرتبة بالأقرب للأكبر.
    # كده الكوم اللي في مكان كويس أصلاً مابيتحركش، واللي بعيد بييجي لأقرب خانة.
    cands = sorted(own | set(free), key=lambda c: (abs(index[c] - anchor), index[c]))
    total = len(stacks) + len(loose)
    targets = cands[:min(total, len(cands))]
    spare = [c for c in targets if c not in own]
    moves = []
    for cell, item, _ in stacks:
        if cell in targets or not spare:
            continue
        moves.append({"target_container": "stash", "target_wrapper_id": spare.pop(0),
                      "instance_ids": [item]})
    for item in loose:
        if not spare:
            break
        moves.append({"target_container": "stash", "target_wrapper_id": spare.pop(0),
                      "instance_ids": [item]})
    if packed:
        detail = ("The stacks are already wrapped to maximum density: %s = %s and the cap is %s per cell. "
                  "No further merge will happen — even inside the game."
                  % (units, " + ".join(str(a) for a in amounts), cap))
    elif moves:
        detail = ("The closest we can do: bring the stacks (%s) onto cells next to each other "
                  "with cap %s, so merging to %s becomes one drag inside the game."
                  % (" + ".join(str(a) for a in amounts), cap,
                     " + ".join(str(a) for a in ideal)))
    else:
        detail = ("The stacks (%s) are already adjacent and the cap is %s — merging to %s only fits inside "
                  "the game: the gateway refuses to change quantities from outside."
                  % (" + ".join(str(a) for a in amounts), cap,
                     " + ".join(str(a) for a in ideal)))
    return {"moves": moves[:max_moves], "anchor": anchor_cell, "stacks": len(stacks),
            "loose": len(loose), "total": total, "amounts": amounts, "units": units,
            "limit": cap, "ideal": ideal, "packed": packed, "detail": detail}


def merge_all_ops(tree, caps=None, max_ops=200):
    """خطة الدمج الحقيقي: أزواج (مصدر ← هدف) توصل كل نوع لتعبئته القصوى.

    كل زوج بيتنفّذ في طلب واحد على البوابة: update لكمية الهدف + delete (أو update
    ناقص) للمصدر — مقيس لايف 2026-10-31 في pioneer_write.combine_attempt. فمفيش
    حاجة اسمها "سحبة جوه اللعبة" ومفيش حاجة لخانة فاضية: الخانة الفاضية بتحصل
    لوحدها لما المصدر يفضى ويتشال.
    """
    caps = dict(caps or {})
    lay = layout(tree)
    in_stash = {str(c) for c in lay["stash"]["slots"]}
    found = {}
    for iid, row in tree.by_id.items():
        if row.get("slots"):
            continue
        aid = str(row.get("gameAssetId") or "")
        if not aid or aid == "None":
            continue
        par = str(tree.parent.get(iid) or "")
        if par and par not in in_stash:
            continue                      # في شنطة/تجهيز/أوجمنت: الزرار مالمسوش
        found.setdefault(aid, []).append({"item": str(iid),
                                          "amount": int(tree.amount(iid) or 1)})
    groups, ops = [], []
    for aid, rows in sorted(found.items()):
        if len(rows) < 2:
            continue
        cap = int(caps.get(aid) or 0)
        if cap < 2:
            continue                      # حدّ مجهول أو أسلحة/دروع: مفيش دمج
        piles = sorted((dict(r) for r in rows), key=lambda p: -p["amount"])
        amounts = [p["amount"] for p in piles]
        units = sum(amounts)
        ideal = [cap] * (units // cap)
        if units % cap:
            ideal.append(units % cap)
        made = 0
        while len(ops) < max_ops:
            # المصدر مش لازم يكون كوم ناقص: سحب units من كوم ممتل بيرجّعها ناقصة
            # تاني، فلو بقى كوم واحد بس تحت السقف يبقى النوع معبّأ على الأكمل.
            open_piles = sorted((p for p in piles if p["amount"] < cap),
                                key=lambda p: -p["amount"])
            if len(open_piles) < 2:
                break
            tgt, src = open_piles[0], open_piles[1]
            take = min(cap - tgt["amount"], src["amount"])
            if take < 1:
                break
            ops.append({"asset_id": aid, "source": src["item"], "target": tgt["item"],
                        "take": take, "cap": cap})
            tgt["amount"] += take
            src["amount"] -= take
            if src["amount"] <= 0:
                piles.remove(src)
            made += 1
        groups.append({"asset_id": aid, "name": tree.name_of(rows[0]["item"]) or aid,
                       "cap": cap, "amounts": amounts, "ideal": ideal, "units": units,
                       "before": len(amounts), "after": len(piles), "ops": made})
    owed = [g for g in groups if g["ops"]]
    summary = {"assets": len(groups), "owed": len(owed), "ops": len(ops),
               "drags": sum(max(g["before"] - g["after"], 0) for g in owed)}
    if not groups:
        detail = "No stackable type has more than one pile — nothing to merge."
    elif not ops:
        detail = "Every type is already wrapped to its cap — nothing was owed."
    else:
        detail = "%s merges across %s types run on the official gateway." % (len(ops), len(owed))
    return {"groups": groups, "owed": owed, "ops": ops, "summary": summary, "detail": detail}


def spread_plan(tree, asset_id, max_moves=40, gap_pref=0):
    """يفرّد أكوام عنصر واحد على خانات ستاش متباعدة — كل كوم في خانة لوحدها.

    دي الحركة المعاكسة لـ merge_plan. تقسيم الكوم نفسه (نصفه في خانة فاضية)
    مرفوض على بوابة Pioneer — أي amount مختلف عن الحالي = INVALID_ARGUMENT،
    فبدل النصف بنفرد الأكوام الموجودة: خانة لكل كوم وأبعد ما يكّون عن جيرانه،
    واللي خاناتهم كويسة أصلاً مابتتحركش.
    """
    asset = str(asset_id)
    lay = layout(tree)
    cells = [str(c) for c in lay["stash"]["slots"]]
    if not cells:
        raise TreeError(409, "no_stash", "No stash cells in the official tree.")
    index = {c: i for i, c in enumerate(cells)}

    def is_stack(iid):
        row = tree.by_id.get(str(iid)) or {}
        return str(row.get("gameAssetId")) == asset and not row.get("slots")

    stacks, loose = [], []
    for cell in cells:
        item = tree.first_child(cell)
        if item and is_stack(item):
            stacks.append((cell, str(item), int(tree.amount(item) or 1)))
    loose = [str(i) for i in tree.by_id if is_stack(i) and not tree.parent.get(i)]
    total = len(stacks) + len(loose)
    if total < 2:
        raise TreeError(409, "nothing_to_spread",
                        "There is only one stack of this item — nothing to spread out.")

    own = {cell for cell, _, _ in stacks}
    amount_of = {cell: a for cell, _, a in stacks}
    free = [c for c in cells if not tree.first_child(c)]
    if len(own) + len(free) < total:
        raise TreeError(409, "not_enough_cells",
                        "Each stack needs its own empty cell: you have %d free cells and %d stacks "
                        "(%d of them coming from overflow), so you are short %d cells. Empty stash "
                        "cells first (sell/recycle inside the game) and retry — overflow has no cells."
                        % (len(free), total, len(loose), total - len(own) - len(free)))

    # تباعد البداية: نظريًا أكتر مسافة ممكنة بين total خانات في الطول ده.
    # gap_pref بيسمح للواجهة تطلب تباعد أضيق عمداً (نمط "قريب لكن لوحده").
    gap_max = max(1, (len(cells) - 1) // max(1, total - 1))
    gap_min = max(1, min(gap_pref, gap_max)) if gap_pref else 1
    chosen = []
    for gap in range(gap_max, gap_min - 1, -1):
        chosen = []
        # الاكبر يفضل في مكانه: الخانات بتُختار بترتيب الحجم ثم الموقع.
        for cell in sorted(own, key=lambda c: (-amount_of[c], index[c])):
            if all(abs(index[cell] - index[d]) >= gap for d in chosen):
                chosen.append(cell)
        for cell in free:
            if len(chosen) >= total:
                break
            if all(abs(index[cell] - index[d]) >= gap for d in chosen):
                chosen.append(cell)
        if len(chosen) >= total:
            break
    chosen = chosen[:total]
    chosen.sort(key=lambda c: index[c])

    keep = {c for c in chosen if c in own}
    spare = [c for c in chosen if c not in own]
    # الأكبر يفضل في مكانه، والأصغر يتحرّك — كده أقل عدد نقلات ممكن.
    movers = sorted([s for s in stacks if s[0] not in keep], key=lambda s: -s[2])
    stranded = sorted(loose, key=lambda i: -int(tree.amount(i) or 1))
    queue = [(item, "move") for _, item, _ in movers] + [(i, "loose") for i in stranded]
    moves = []
    for item, _ in queue:
        if not spare:
            break
        moves.append({"target_container": "stash", "target_wrapper_id": spare.pop(0),
                      "instance_ids": [item]})
    gaps = [abs(index[a] - index[b]) for a, b in zip(chosen, chosen[1:])]
    if not moves:
        detail = ("The stacks (%d) already sit on cells spaced %d apart — nothing "
                  "needs to move. Real splitting (half the stack in its own cell) is refused by the gateway."
                  % (total, gap_max))
    else:
        detail = ("We spread %d stacks over %d cells — each stack is alone in its cell and the nearest neighbour is at least "
                  "%d cells away (%d moves). The gateway does not split the stack itself: what we do "
                  "is spread the stacks that already exist."
                  % (total, len(chosen), min(gaps) if gaps else 0, len(moves)))
    return {"moves": moves[:max_moves], "stacks": len(stacks), "loose": len(loose),
            "total": total, "free": len(free), "kept": len(keep),
            "gap": min(gaps) if gaps else 0, "cells": len(cells),
            "targets": [index[c] for c in chosen], "detail": detail}


def _move_with_unload(tree, lay, ids, unload, target_container, target_slot):
    """خلع الشنطة: طلب واحد بيطلّع المحتوى من خانات اللوداوت وبيطلّع الشنطة من
    خانة AUGMENT في نفس اللحظة — البوابة بتنفّذ العمليات بترتيبها، فمفيش حالة
    وسطى اللوداوت شارشها على الشنطة وهي مش موجودة."""
    steps, moved, labels = [], [], []
    for aug in ids:
        job = unload.get(aug)
        if not job:
            continue
        inner = list(job["ids"])
        if not inner:
            continue
        if job["container"] == "overflow":
            body, dest, got, _lay = plan_move(tree, inner, "overflow", "", "")
        else:
            body, dest, got, _lay = plan_move(tree, inner, "stash", "", "", fallback_if_full=True)
        apply_steps(tree, body["steps"])
        steps.extend(body["steps"])
        moved.extend(got)
        labels.append(dest.get("label") or job["container"].upper())
    for aug in ids:
        body, dest, got, _lay = plan_move(tree, [aug], target_container, target_slot, "")
        apply_steps(tree, body["steps"])
        steps.extend(body["steps"])
        moved.extend(got)
        labels.append(dest.get("label") or target_container.upper())
    return ({"target_container": target_container, "requests": [], "steps": steps},
            {"container": target_container, "wrappers": [], "label": labels[-1] if labels else ""},
            moved, layout(tree))


_DEAD_CELL_DETAIL = ("The gateway accepted the write and the item stayed put — this loadout cell "
                     "is not one the game writes items into.")


def _dead_loadout_cells(tree, lay, key):
    """خانة لوداوت البوابة بتقبل الكتابة عليها وما بتحطش حاجة.

    القياس لايف 2026-11-20 (G21، شجرة Combat Mk. 2): خانة "Auxiliary Grenade Slot"
    اللي اللوداوت موجّه عليها ردت 200 على setParents وما اتغيرتش في القراية،
    وأي أب جديد تحتها رد INVALID_ARGUMENT. نفس المحتوى تحت حاوية الشنطة
    ("Grenade Auxiliary Slot" جوّه "Combat Mk. 2 Auxiliary Slot") هو اللي اللعبة
    بتقراه، فدي الوجهة الحقيقية للخانة.
    """
    slots = lay["loadout"]["slots"].get(key) or []
    if not slots:
        return {}
    cell = str(slots[0].get("wrapper") or "")
    holder = next((h for h, kids in tree.kids.items() if cell in kids), "")
    if not holder:
        return {}
    kids = tree.children(holder)
    if len(kids) > 1:
        return {"owner": holder, "cells": kids}
    tag = str((tree._row(cell) or {}).get("game_asset_name") or tree.label(cell) or "").upper()
    if any(t in tag for t in ("GRENADE", "CONSUMABLE", "MINE")):
        return {"owner": holder, "cells": kids, "detail": _DEAD_CELL_DETAIL}
    return {}


def plan_move(tree, instance_ids, target_container, target_slot="", target_wrapper_id="",
              fallback_if_full=False, source_steps=None):
    """يخطط نقل عناصر بين خانات المخزن الرسمية.

    كل خانة في المخزن (ستاش/شنطة/تجهيز) هي نفسها حاوية بـ slots — النقل بيتم
    بتحديث خانتين في طلب واحد: المصدر بيتفضّى والوجهة بتاخد العنصر.
    """
    lay = layout(tree)
    ids = [str(i) for i in (instance_ids or []) if i]
    if not ids:
        raise TreeError(400, "nothing_selected", "No items selected to move.")
    missing = [i for i in ids if i not in tree.by_id]
    if missing:
        raise TreeError(404, "unknown_instance",
                        "These items are not in the official stash: %s" % ", ".join(missing[:5]))
    target_container = str(target_container or "").lower()
    # خلع الشنطة الملبوسة = ملكشوبة: القطع اللي جواها بتخرج الأول (للأوفر
    # اللي طلبه المستخدم، وإلا لخاناتها)، وبعدها الشنطة نفسها بتخرج من خانة
    # AUGMENT. خانات اللوداوت بقت بتشاور على حاويات الأوجمنت ده، فلو اللوداوت
    # اتساب موجّه عليها وهي اتخلعت، أول نقل جديد للخانة بيرفضه الموضوع.
    worn = set(lay["loadout"]["slots"].get("augment", [])[0].get("item") or "")
    unload = {}
    for iid in ids:
        if iid not in worn:
            continue
        inside, seen = [], set()
        for slot in tree.children(iid):
            for holder in tree.children(slot):
                for cell in tree.children(holder):
                    content = tree.first_child(cell)
                    if content and content not in seen and content not in ids:
                        seen.add(content)
                        inside.append(content)
        if not inside:
            continue
        pending_ids = [r for r in inside if tree.parent.get(r, "")]
        unload[iid] = {"ids": pending_ids,
                       "container": "overflow" if target_container in ("overflow", "stash") else "stash"}
    if unload:
        return _move_with_unload(tree, lay, ids, unload, target_container, target_slot)
    sources = [tree.parent.get(i, "") for i in ids]
    if target_container == "overflow":
        label = "OVERFLOW"
        pending = [(iid, src) for iid, src in zip(ids, sources) if src]
        if not pending:
            raise TreeError(409, "already_there", "The items are already in the overflow stash.")
        if source_steps is not None:
            # طلب خروج خانة بيفضّيها بمحتواها كله. ده مقصود في نقل عادي، لكن اختبار
            # النقل (api_unknown_cover) لازم ينقل قطعة واحدة من أوفر مزدحم — الخروج
            # بيتكتب هنا للقطعة نفسها ولخانتها.
            steps, requests, moved = [], [], []
            for iid, src in [(str(i), str(s)) for i, s in source_steps]:
                requests.append({"mutations": [
                    {"discriminator": "update", "instanceId": src,
                     "slots": [tree.first_child(src)], "amount": tree.amount(src)}],
                    "requestId": ""})
                steps.append({"instance_id": iid, "source": src, "target": ""})
            body = {"target_container": target_container, "requests": requests, "steps": steps}
            dest = {"container": target_container, "wrappers": [], "label": label}
            return body, dest, moved, lay
        steps, requests, moved = [], [], []
        for iid, src in pending:
            requests.append({"mutations": [
                {"discriminator": "update", "instanceId": src,
                 "slots": [""], "amount": tree.amount(src)}], "requestId": ""})
            steps.append({"instance_id": iid, "source": src, "target": ""})
            moved.append({
                "instance_id": iid,
                "name": tree.name_of(iid),
                "from": src,
                "from_label": tree.name_of(src),
                "to": "",
                "to_label": label,
            })
        body = {"target_container": target_container, "requests": requests, "steps": steps}
        dest = {"container": target_container, "wrappers": [], "label": label}
        return body, dest, moved, lay
    if target_container == "stash":
        wrappers = list(lay["stash"]["slots"])
        label = "STASH"
    elif target_container == "backpack":
        wrappers = [s["wrapper"] for s in lay["backpack"]["slots"]]
        if not wrappers:
            raise TreeError(409, "no_backpack", "There is no active backpack in the official stash.")
        label = "BACKPACK"
    elif target_container == "loadout":
        key = str(target_slot or "").lower()
        quirk = _dead_loadout_cells(tree, lay, key)
        if key not in lay["loadout"]["slots"]:
            raise TreeError(400, "bad_slot",
                            "The loadout cell '%s' is not in the active loadout." % key)
        if quirk.get("detail") and ids and ids[0] == str((lay["loadout"]["slots"].get(key) or [{}])[0].get("wrapper") or ""):
            raise TreeError(409, "cell_inactive", _DEAD_CELL_DETAIL)
        holder = quirk.get("owner")
        if holder:
            # خانات AUGMENTED الحقيقية في اللعبة هي خانات الحاوية اللي متعلّقة على
            # الشنطة الملبوسة (شوف _dead_loadout_cells) — مش الخانة الظاهرة.
            wrappers = list(quirk.get("cells") or [])
            label = "AUGMENTED"
        else:
            slots = lay["loadout"]["slots"].get(key) or []
            wrappers = [s["wrapper"] for s in slots]
            label = "LOADOUT"
    elif target_container == "mod_slot":
        # خانة مرفق: نفس منطق النقل بالظبط — الـ wrapper بتاع الخانة بياخد
        # آيد المرفق. بنقبل خانات DA_ModSlot_* بس عشان مفيش كتابة في غيرو.
        wrapper = str(target_wrapper_id or "")
        if not wrapper or wrapper not in tree.by_id:
            raise TreeError(400, "bad_slot", "The attachment cell is not in the official stash.")
        asset = (tree._row(wrapper).get("game_asset_name") or "").upper()
        if not asset.startswith("DA_MODSLOT_"):
            raise TreeError(400, "bad_slot", "The selection is not an attachment cell in the official stash.")
        wrappers = [wrapper]
        label = tree.name_of(wrapper) or "MOD SLOT"
    else:
        raise TreeError(400, "bad_target", "Unknown destination in direct mode: %s" % target_container)

    dests = _destinations(tree, wrappers, sources, target_wrapper_id,
                          allow_occupied=(target_container == "loadout"
                                          and str(target_slot or "").lower() == "augment"),
                          fallback_if_full=fallback_if_full)
    if dests == sources:
        raise TreeError(409, "already_there", "The items are already in the requested destination.")

    steps, requests, moved = [], [], []
    for iid, src, dst in zip(ids, sources, dests):
        mutations = []
        if src:
            mutations.append({"discriminator": "update", "instanceId": src,
                              "slots": [""], "amount": tree.amount(src)})
        mutations.append({"discriminator": "update", "instanceId": dst,
                          "slots": [iid], "amount": tree.amount(dst)})
        requests.append({"mutations": mutations, "requestId": ""})
        steps.append({"instance_id": iid, "source": src, "target": dst})
        moved.append({
            "instance_id": iid,
            "name": tree.name_of(iid),
            "from": src,
            "from_label": tree.name_of(src) or "OVERFLOW",
            "to": dst,
            "to_label": label,
        })
    body = {"target_container": target_container, "requests": requests, "steps": steps}
    dest = {"container": target_container, "wrappers": dests, "label": label}
    return body, dest, moved, lay


def at_destination(tree, ids, dest):
    """هل كل العناصر بقت فعلًا في خانات الوجهة؟ (تحقق بعد الكتابة)."""
    wrappers = dest.get("wrappers") or []
    if not ids or len(wrappers) != len(ids):
        return False
    return all(tree.parent.get(iid) == wrapper for iid, wrapper in zip(ids, wrappers))


def apply_steps(tree, steps):
    """تطبيق النقل على الشجرة في الذاكرة — عشان الخطة التالية تشوف الحالة الجديدة.

    نفس منطق طلب البوابة: خانة المصدر بتفضّى وخانة الوجهة بتاخد العنصر.
    المصدر/الوجهة الفاضيين معناهم عنصر عائم (الأوفر ستاش) — من غير أب.
    """
    for step in steps or []:
        iid = str(step["instance_id"])
        src = str(step.get("source") or "")
        dst = str(step.get("target") or "")
        if src:
            tree.kids[src] = [k for k in (tree.kids.get(src) or []) if k != iid]
        if dst:
            displaced = [k for k in (tree.kids.get(dst) or []) if k != iid]
            tree.kids[dst] = [iid]
            tree.parent[iid] = dst
            for k in displaced:
                # اللي اتطرد من الخانة مابقاش لها أب هنا: البوابة بترجعه لخانتها
                # في الستاش لوحدها، فنبعده عن الخانة دي عشان ميبقاش مكرر فيها.
                if tree.parent.get(k) == dst:
                    tree.parent.pop(k, None)
        else:
            tree.parent.pop(iid, None)
    return tree
