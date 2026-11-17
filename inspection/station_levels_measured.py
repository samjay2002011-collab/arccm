"""مستوى كل محطة من سيرفر اللعبة: المحطة عقدة في الشجرة واسمها فيه رقمها.

الفرض القابل للقياس: "Gunsmith I" و"Gunsmith II" أصلان مختلفان، فالعقدة اللي
في شجرة الحساب بتقول اللفل الحالي. المسبار ده:
  1) يطلع من الفهرس كل أسماء الأصول اللي على شكل محطة (workbench/gunsmith/
     refiner/medical/utility/explosives/gear/field bench/anvil/press/…) مع
     رقم الروماني لو موجود،
  2) لكل حساب يطابق عقد الشجرة الخام على دول ويطبع الأصل اللي موجود واللي مفيش،
  3) يكشف أي حساب فيه أكتر من نسخة من نفس المحطة (علشان نعرف القاعدة صح ولا لأ).
قراءة من كاش الأشجار + الفهرس المحلي — مفيش شبكة ولا كتابة.
"""
import gzip
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_tree  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_station_levels_measured_out.txt")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_trees_cache.json.gz")

FAMILIES = {
    "workbench": ("workbench",),
    "equipment_bench": ("gear bench", "equipment bench", "tailor", "sewing"),
    "weapon_bench": ("gunsmith",),
    "med_station": ("medical", "med lab", "health"),
    "utility_bench": ("utility",),
    "explosives_bench": ("explosive", "demolition"),
    "refiner": ("refiner", "refinery"),
    "in_raid": ("field", "portable"),
    "anvil": ("anvil",),
}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
SLOT_NOISE = ("slot", "socket", "wheel", "auxiliary", "container", "blueprint",
              "unlock", "parts", "stick", "kit")


def station_name(text):
    low = (text or "").strip().lower()
    if not low or any(noise in low for noise in SLOT_NOISE):
        return ""
    for fam, words in FAMILIES.items():
        if any(word in low for word in words):
            tail = re.search(r"(?:^|[\s\-])(i{1,3}|iv|v|vi)(?:$|[\s\-])", low)
            level = ROMAN.get(tail.group(1), 0) if tail else 0
            return "%s|%s|%s" % (fam, low, level or "")
    return ""


def main():
    buf = io.StringIO()
    w = buf.write
    names = pioneer_tree.asset_names()

    w("===== أسماء المحطات في فهرس الأصول (كل النسخ) =====\n")
    index_rows = {}
    for aid, row in names.items():
        text = str(row.get("display_name") or row.get("game_asset_name") or "").strip()
        key = station_name(text)
        if key:
            index_rows[str(aid)] = (text, key)
    for aid, (text, key) in sorted(index_rows.items(), key=lambda i: (i[1][0], i[1][1])):
        w("   %-14s %-34s %s\n" % (aid, text[:34], key))
    w("   الإجمالي: %s أصل على شكل محطة\n" % len(index_rows))

    if not os.path.isfile(CACHE):
        w("\nمفيش كاش أشجار.\n")
        open(OUT, "w", encoding="utf-8").write(buf.getvalue())
        return 1
    with gzip.open(CACHE, "rt", encoding="utf-8") as fh:
        trees = json.load(fh)

    w("\n===== لكل حساب: محطات الشجرة الخام =====\n")
    matrix = {}
    for account in sorted(trees):
        items = trees.get(account) or []
        w("\n== %s (%s عقدة)\n" % (account, len(items)))
        found = {}
        for node in items:
            aid = str(node.get("gameAssetId"))
            row = names.get(aid) or {}
            text = str(row.get("display_name") or row.get("game_asset_name") or "").strip()
            key = station_name(text) or station_name(aid if aid in index_rows else "")
            if not key:
                if aid in index_rows:
                    key = index_rows[aid][1]
                    text = index_rows[aid][0]
                else:
                    continue
            fam = key.split("|")[0]
            found.setdefault(fam, []).append((text, aid, node.get("amount"),
                                              str(node.get("instanceId"))[:8]))
        matrix[account] = found
        if not found:
            w("   (ولا محطة)\n")
        for fam in sorted(found):
            for text, aid, amount, iid in sorted(found[fam]):
                w("   %-16s %-30s asset=%-13s amount=%s inst=%s\n" % (
                    fam, text[:30], aid, amount, iid))

    w("\n===== مصفوفة المحطة×الحساب (اللي ظهر عند حساب ومفيش عند التاني) =====\n")
    fams = sorted({f for acc in matrix.values() for f in acc})
    header = "%-18s" % "station" + "".join("%-16s" % a[:15] for a in sorted(matrix))
    w(header + "\n")
    for fam in fams:
        line = "%-18s" % fam[:17]
        for account in sorted(matrix):
            texts = {t for t, _aid, _am, _i in (matrix[account].get(fam) or [])}
            line += "%-16s" % ("/".join(sorted(texts))[:15] or "—")
        w(line + "\n")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
