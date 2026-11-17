"""شجرة اللعبة الخام فيها مستوى لأي محطة؟ (قياس من كاش الأشجار الخام)

الكاش فيه رد GET /v1/pioneer/inventory الخام (عقد `items`) لكل حساب.
بيطبع:
  1) كل أسماء الحقول اللي بتيجي في العقدة الخام،
  2) أي عقدة اسمها في الفهرس فيه كلمة محطة/بنش/رفاينر/أنفل..،
  3) أي عقدة ليها حقل اسمو level/tier/stage/rank،
  4) الجذور اللي بلا أب وأسمائها،
  5) أي أصل موجود عند حساب ومفيش عند التاني واسمه محطة.
قراءة من القرص وبس — مفيش شبكة ولا كتابة.
"""
import gzip
import io
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_tree  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_station_raw_tree_out.txt")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_trees_cache.json.gz")

STATION_WORDS = ("workbench", "bench", "refiner", "anvil", "kiln", "press", "station",
                 "medical", "utility", "explosive", "gunsmith", "sewing", "chem",
                 "fabricator", "terminal", "forge", "printer", "assembler", "hideout")


def main():
    buf = io.StringIO()
    w = buf.write
    names = pioneer_tree.asset_names()

    def label(asset_id):
        row = names.get(str(asset_id)) or {}
        return str(row.get("display_name") or row.get("game_asset_name") or "").strip()

    if not os.path.isfile(CACHE):
        w("مفيش كاش أشجار في %s\n" % CACHE)
        open(OUT, "w", encoding="utf-8").write(buf.getvalue())
        return 1
    with gzip.open(CACHE, "rt", encoding="utf-8") as fh:
        trees = json.load(fh)

    per_account_assets = {}
    for account in sorted(trees):
        items = trees.get(account) or []
        w("\n===== %s | %s عقدة خام\n" % (account, len(items)))
        if not items:
            w("   (الشجرة فاضية — الحساب ده مالوش قراءة محفوظة)\n")
            continue

        fields = Counter()
        for node in items:
            if isinstance(node, dict):
                fields.update(node.keys())
        w("   -- حقول العقدة الخام --\n")
        for key, cnt in sorted(fields.items()):
            w("      %-24s %s\n" % (key, cnt))

        w("   -- عقد أسماء المحطات --\n")
        seen = 0
        for node in items:
            text = label(node.get("gameAssetId")).lower()
            if text and any(word in text for word in STATION_WORDS):
                seen += 1
                if seen <= 40:
                    w("      %-32s %s\n" % (text[:32], json.dumps(
                        {k: v for k, v in node.items() if k != "slots"},
                        ensure_ascii=False, default=str)[:200]))
        w("      الإجمالي: %s\n" % seen)

        w("   -- عقد ليها حقل level/tier/stage/rank --\n")
        hits = 0
        for node in items:
            for key, val in node.items():
                if any(t in str(key).lower() for t in ("level", "tier", "stage", "rank")):
                    hits += 1
                    if hits <= 30:
                        w("      %-32s %s=%s\n" % (label(node.get("gameAssetId"))[:32], key, val))
        w("      الإجمالي: %s\n" % hits)

        w("   -- الجذور (عقد بلا أب) --\n")
        child_ids = set()
        for node in items:
            for slot in (node.get("slots") or []):
                if isinstance(slot, dict):
                    iid = slot.get("instanceId") or slot.get("childInstanceId")
                    if iid:
                        child_ids.add(str(iid))
        roots = [n for n in items if str(n.get("instanceId")) not in child_ids]
        w("      عدد الجذور: %s\n" % len(roots))
        for node in roots[:60]:
            w("      %-34s asset=%s amount=%s slots=%s\n" % (
                (label(node.get("gameAssetId")) or "(بلا اسم)")[:34],
                node.get("gameAssetId"), node.get("amount"),
                len(node.get("slots") or [])))

        per_account_assets[account] = {str(n.get("gameAssetId")) for n in items
                                       if n.get("gameAssetId") is not None}

    w("\n===== أصول موجودة عند حساب ومفيضة عند حساب تاني (بالاسم) =====\n")
    all_ids = set()
    for s in per_account_assets.values():
        all_ids |= s
    rows = 0
    for asset_id in sorted(all_ids, key=lambda a: (label(a).lower(), a)):
        text = label(asset_id)
        if not text:
            continue
        has = tuple(acc for acc in sorted(per_account_assets)
                    if asset_id in per_account_assets[acc])
        if len(has) < len(per_account_assets) and 0 < len(has):
            rows += 1
            tagged = "محطة" if any(word in text.lower() for word in STATION_WORDS) else ""
            if tagged or rows <= 120:
                w("   %-36s في=%-40s %s\n" % (text[:36], ",".join(has), tagged))
    w("   الإجمالي: %s أصل مشترك بشكل متفاوت\n" % rows)

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
