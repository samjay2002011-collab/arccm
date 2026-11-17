"""أنا بدور على مصدر حقيقي لمستوى كل محطة في بيانات السيرفر — مش بتخمين.

بيقرأ آخر سنابشوت لكل حساب (نفس الـ payload الخام اللي رجع من
GET /v1/pioneer/inventory) وبيطبع المحتوى الكامل لمفاتيح
bench_levels / unlocked_blueprints وكل مفتاح تاني قيمته مش list عشان
نبان شكل البيانات. قراءة من القرص وبس — مفيش شبكة ولا كتابة.
"""
import gzip
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_tree, store  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_station_level_probe_out.txt")

INTERESTING = ("bench_levels", "unlocked_blueprints", "allowed_slots", "augment",
               "locations", "source", "stats", "item_mappings", "owned_asset_ids")


def latest(conn, account):
    row = conn.execute("SELECT path, fetched_at FROM snapshots WHERE account=? AND ok=1 "
                       "ORDER BY fetched_at DESC LIMIT 1", (account,)).fetchone()
    return (row["path"], row["fetched_at"]) if row else ("", 0)


def load(path):
    if not path or not os.path.exists(path):
        return None
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def brief(value, limit=900):
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def main():
    conn = store.db()
    buf = io.StringIO()
    w = buf.write
    names = pioneer_tree.asset_names()

    def label(asset_id):
        row = names.get(str(asset_id)) or {}
        return str(row.get("display_name") or row.get("game_asset_name") or "").strip()

    for acc in store.list_accounts(conn):
        account = acc["name"] if isinstance(acc, dict) else acc
        path, when = latest(conn, account)
        data = load(path)
        w("\n===== %s | %s | %s\n" % (account, os.path.basename(path or "?"), when))
        if not isinstance(data, dict):
            w("   السنابشوت مش dict أو مش موجود\n")
            continue

        w("   -- شكل كل مفتاح في الرد --\n")
        for key in sorted(data.keys()):
            val = data[key]
            kind = type(val).__name__
            size = len(val) if isinstance(val, (list, dict, str)) else "-"
            w("      %-22s %-8s حجم=%s\n" % (key, kind, size))

        for key in INTERESTING:
            if key not in data:
                continue
            val = data[key]
            w("\n   ===== %s =====\n" % key)
            if isinstance(val, dict):
                if not val:
                    w("      (فاضي)\n")
                for k in sorted(val, key=str):
                    w("      %-26s %s\n" % (str(k)[:26], brief(val[k], 400)))
            elif isinstance(val, list):
                if not val:
                    w("      (فاضي)\n")
                for item in val:
                    w("      %s\n" % brief(item, 400))
            else:
                w("      %s\n" % brief(val, 400))

        # أي مفتاح تاني فيه كلمة level/bench/station في اسمه أو في قيمته
        w("\n   -- مفاتيح تانية فيها station/bench/level --\n")
        found = False
        for key, val in data.items():
            low = str(key).lower()
            if key in INTERESTING or not any(t in low for t in ("bench", "station", "level", "unlock")):
                continue
            found = True
            w("      %s = %s\n" % (key, brief(val, 600)))
        if not found:
            w("         (مفيش)\n")

        # اسماء المحطات كموجودات في المخزن
        stashed = data.get("stash") or data.get("items") or []
        if isinstance(stashed, list) and stashed:
            w("\n   -- أصول المخزن اللي اسمها محطة --\n")
            hit = 0
            for node in stashed:
                text = label(node.get("gameAssetId")).lower()
                if text and any(t in text for t in ("anvil", "bench", "refiner", "station",
                                                    "workbench", "press", "kiln")):
                    hit += 1
                    w("      %-30s amount=%s dur=%s slots=%s\n" % (
                        text[:30], node.get("amount"), node.get("durability"),
                        bool(node.get("slots"))))
            if not hit:
                w("         (مفيش)\n")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
