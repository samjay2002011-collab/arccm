"""التعديلات اليدوية على بيانات العناصر — الملف الوحيد اللي إيد المستخدم بتكتب فيه.

data/item_overrides.json:
  {"version": 1, "items": {"<asset_id>": {"manual_override": true, "name", "rarity",
   "type", "value", "image", "note", "at"}}}

قواعد ثابتة:
  - كل سطر جوه items بعلامة "manual_override": true وده معناها "مكتوب بإيد".
  - الأولوية القصوى وقت العرض: أي حقل موجود هنا بيكسب على الكتالوج المحلي،
    وعلى بيانات البوابة/أي نسخة احتياطية (backend/catalog.py → decorate).
  - مزامنة الكتالوج أو أي تحديث للبيانات الافتراضية مابيمسّش الملف ده خالص.
  - حذف سطر بيرجّع العنصر تاني لبيانات اللعبة العادية.
"""
import json
import os
import threading
import time

from . import config

FILE = os.path.join(config.DATA_DIR, "item_overrides.json")
RARITIES = ("Common", "Uncommon", "Rare", "Epic", "Legendary")
CARD_BGS = ("standard", "blueprint", "design")
FIELDS = ("name", "rarity", "type", "value", "image", "note", "card_bg")
_lock = threading.Lock()


def _empty():
    return {"version": 1, "items": {}}


def load():
    try:
        with open(FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return _empty()
    rows = {str(k): v for k, v in data["items"].items() if isinstance(v, dict)}
    return {"version": int(data.get("version") or 1), "items": rows}


def _save(data):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    for attempt in range(8):
        try:
            os.replace(tmp, FILE)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.15 * (attempt + 1))


def get(asset_id):
    """سطر التعديل اليدوي للـ asset id — فاضي لو مفيش تعديل."""
    row = load()["items"].get(str(asset_id or "").strip())
    return row if row and row.get("manual_override") else None


def all_rows():
    return {k: v for k, v in load()["items"].items() if v.get("manual_override")}


def local_image(path):
    """مسار صورة محلي للعرض بس — أي شكل تاني (رابط خارجي) بيرجع فاضي."""
    text = str(path or "").strip()
    if text.startswith(("static/", "arctracker/", "metaforge/")):
        return text
    if text.startswith(("items/arctracker/", "items/metaforge/")):
        return text
    if text.startswith("/assets/items/"):
        return text[len("/assets/items/"):]
    if text.startswith("/static/"):
        return text[len("/"):]
    if "/" not in text and text.rsplit(".", 1)[-1].lower() in ("png", "webp", "jpg"):
        return "static/item_icons/" + text
    return ""


def _clean_value(raw):
    if raw is None or str(raw).strip() == "":
        return None
    num = float(str(raw).replace(",", "").strip())
    if num < 0:
        raise ValueError("sell price cannot be negative")
    return int(num) if num == int(num) else round(num, 2)


def _clean_rarity(raw):
    text = str(raw or "").strip()
    if not text:
        return ""
    for known in RARITIES:
        if known.lower() == text.lower():
            return known
    raise ValueError("rarity must be one of %s" % ", ".join(RARITIES))


def _clean_card_bg(raw):
    text = str(raw or "").strip().lower()
    if not text or text == "standard":
        return "standard"
    if text in ("blueprint", "design"):
        return text
    raise ValueError("card_bg must be one of %s" % ", ".join(CARD_BGS))


def save(asset_id, fields):
    """حفظ/تعديل سطر — بيرجع السطر المحفوظ. الحقول الفاضية بتتشال."""
    key = str(asset_id or "").strip()
    if not key:
        raise ValueError("asset id is required")
    data = load()
    row = dict(data["items"].get(key) or {})
    for name in FIELDS:
        if name not in (fields or {}):
            continue
        raw = fields.get(name)
        if name == "rarity":
            row["rarity"] = _clean_rarity(raw)
        elif name == "card_bg":
            row["card_bg"] = _clean_card_bg(raw)
        elif name == "value":
            row["value"] = _clean_value(raw)
        elif name == "image":
            img = local_image(raw)
            if img:
                row["image"] = img
        else:
            row[name] = str(raw or "").strip()
    if not row.get("name"):
        raise ValueError("name is required")
    if not row.get("image"):
        try:
            from . import item_catalog
            resolved = item_catalog.resolve(key)
            if resolved.get("image"):
                row["image"] = local_image(resolved["image"])
            else:
                target_name = (row.get("name") or "").strip().lower()
                cand = next((r for r in item_catalog.search(row.get("name") or "", limit=5)
                             if (r.get("name") or "").strip().lower() == target_name and r.get("image")), None)
                if cand:
                    row["image"] = local_image(cand["image"])
        except Exception:
            pass
    if "card_bg" not in row or not row.get("card_bg"):
        row["card_bg"] = "standard"
    row["manual_override"] = True
    row["at"] = int(time.time())
    data["items"][key] = row
    with _lock:
        _save(data)
    return row


def delete(asset_id):
    key = str(asset_id or "").strip()
    data = load()
    existed = data["items"].pop(key, None) is not None
    if existed:
        with _lock:
            _save(data)
    return existed


def apply(row, asset_id=""):
    """تطبيق التعديل اليدوي على سطر عرض — الكلمة الأخيرة لأي حقل معدّل يدوياً."""
    key = str(asset_id or (row or {}).get("asset_id") or "").strip()
    rec = get(key)
    if not rec:
        return row
    if rec.get("name"):
        row["name"] = rec["name"]
        row["display_name"] = rec["name"]
    if rec.get("rarity"):
        row["rarity"] = rec["rarity"]
    if rec.get("type"):
        row["type"] = rec["type"]
        row["type_label"] = rec["type"]
    if rec.get("value") is not None:
        row["value"] = rec["value"]
    if rec.get("image"):
        row["image"] = rec["image"]
    if rec.get("card_bg"):
        row["card_bg"] = rec["card_bg"]
    row["manual_override"] = True
    if rec.get("note"):
        row["override_note"] = rec["note"]
    return row