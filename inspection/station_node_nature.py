"""المحطة في الشجرة: جسم الهايدأوت ولا صنف بيتصنع؟

عشان نكتب لفل قدام اسم المحطة ونكون مصدّقين من السيرفر، لازم نعرف طبيعة
العقدة دي. المسبار بيرد على 3 أسئلة بكل أصول المحطات:
  1) items_db (arctracker): هل الأصل ده ليه وصفة تصنيع؟ بلوبرنته مقفول؟
     ما هو أصلًا في قاعدة العناصر ولا لأ؟
  2) مكان العقدة في الشجرة: أبها إيه؟ جوّه الستاش/الشنطة ولا طافية بلا أب
     (لو كانت صنف كنت لاقيها في الخانات، ولو جسم محطة بتكون برّا).
  3) عدد النسخ عند كل حساب (جسم المحطة واحد، الصنف يتكرر).
قراءة من الكاش + البيانات المحلية — مفيش شبكة ولا كتابة.
"""
import gzip
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, pioneer_tree  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_station_node_nature_out.txt")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_trees_cache.json.gz")

# أصول المحطات اللي طلعت من شجرة الحسابات في المسبار اللي قبل ده
STATION_ASSETS = {
    "workbench": [(-834400146, "Workbench")],
    "equipment_bench": [(1415022693, "Gear Bench I"), (-92567848, "Gear Bench II"),
                        (-1093740163, "Gear Bench III")],
    "weapon_bench": [(291196846, "Gunsmith I"), (348416871, "Gunsmith II"),
                     (-1091338374, "Gunsmith III")],
    "med_station": [(-1840090314, "Medical Lab I"), (-1409422086, "Medical Lab II"),
                    (1157010858, "Medical Lab III")],
    "utility_bench": [(1140794731, "Utility Station I"), (1553081706, "Utility Station II"),
                      (1160802326, "Utility Station III")],
    "explosives_bench": [(-518683794, "Explosives Station I"), (-44778840, "Explosives Station II"),
                         (-815789211, "Explosives Station III")],
    "refiner": [(-935249204, "Refiner I"), (1517102401, "Refiner II"), (81797988, "Refiner III")],
    "anvil": [(1951118983, "Anvil I"), (-1974459892, "Anvil II"), (-39940538, "Anvil III"),
              (-163859490, "Anvil IV"), (-2130292638, "Anvil Splitter")],
}


def main():
    buf = io.StringIO()
    w = buf.write
    names = pioneer_tree.asset_names()
    with gzip.open(CACHE, "rt", encoding="utf-8") as fh:
        trees = json.load(fh)

    w("===== (1) طبيعة كل أصل محطة في items_db =====\n")
    for fam, rows in STATION_ASSETS.items():
        w("\n-- %s --\n" % fam)
        for aid, text in rows:
            row = items_db.find(aid) or {}
            recipe = row.get("recipe") or []
            w("   %-20s في القاعدة=%s وصفة=%s بلوبرنت مقفول=%s محطات=%s لفل=%s\n" % (
                text, bool(row), len(recipe), row.get("blueprint_locked"),
                row.get("craft_bench") or row.get("stations"), row.get("station_level")))
            if recipe:
                w("      الوصفة: %s\n" % json.dumps(recipe, ensure_ascii=False)[:220])

    w("\n===== (2)+(3) مكان العقدة في شجرة كل حساب وعدد النسخ =====\n")
    for account in sorted(trees):
        items = trees.get(account) or []
        by_id = {str(n.get("instanceId")): n for n in items}
        parent = {}
        for node in items:
            for slot in (node.get("slots") or []):
                if isinstance(slot, dict):
                    child = slot.get("instanceId") or slot.get("childInstanceId")
                    if child:
                        parent[str(child)] = str(node.get("instanceId"))

        def chain(iid, depth=8):
            out = []
            cur = iid
            while cur in parent and depth > 0:
                cur = parent[cur]
                depth -= 1
                out.append((names.get(str((by_id.get(cur) or {}).get("gameAssetId"))) or {})
                           .get("display_name") or "?")
            return " < ".join(out[:3]) or "(بلا أب — طافية)"

        w("\n== %s\n" % account)
        for fam, rows in STATION_ASSETS.items():
            for aid, text in rows:
                nodes = [n for n in items if str(n.get("gameAssetId")) == str(aid)]
                if not nodes:
                    continue
                for node in nodes:
                    iid = str(node.get("instanceId"))
                    kids = len(node.get("slots") or [])
                    w("   %-20s %-20s عدد=%s أب=%s أبناه=%s %s\n" % (
                        fam, text, len(nodes),
                        (chain(iid))[:48], kids,
                        "updatedAt=%s" % node.get("updatedAt")))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
