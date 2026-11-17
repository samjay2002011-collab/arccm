"""مراقبة نقلة واحدة معزولة: بنتignor الدوران تلقائياً لأننا بنطلب ثبات التغيير 3 عينات ورا بعض.

الاستخدام: شغّل السكربت، اعمل نقلة واحدة في اللعبة (قطعة من مكان لمكان)، وسب الصفحة مفتوحة.
"""
import json
import os
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")
from backend import pioneer_client as pc, pioneer_tree as pt  # noqa: E402

ACCOUNT = os.environ.get("WATCH_ACCOUNT", "RAIDER32857")
SECONDS = float(os.environ.get("WATCH_SECONDS", "180"))
POLL = 1.5

NAMES = pt.asset_names()


def label(node_id, by):
    n = by.get(str(node_id))
    if not n:
        return "?" + str(node_id)[:8]
    row = NAMES.get(str(n.get("gameAssetId"))) or {}
    nm = row.get("display_name") if isinstance(row, dict) else str(row)
    return "%s#%s" % ((nm or "asset%s" % n.get("gameAssetId"))[:26], str(node_id)[:6])


def snapshot():
    items = (pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or []
    by = {str(n.get("instanceId")): n for n in items}
    where, kids = {}, {}
    for n in items:
        iid = str(n.get("instanceId"))
        slots = [str(s) for s in (n.get("slots") or [])]
        kids[iid] = slots
        for idx, kid in enumerate(slots):
            where[kid] = (iid, idx)
    return {"by": by, "where": where, "kids": kids, "n": len(items)}


def main():
    base = snapshot()
    print("baseline nodes=%s  اعمل نقلة واحدة في اللعبة دلوقتي (%ds)" % (base["n"], SECONDS), flush=True)
    prev, pending = base, {}
    seen_swaps = 0
    samples = 0
    end = time.time() + SECONDS
    while time.time() < end:
        time.sleep(POLL)
        try:
            cur = snapshot()
        except Exception as exc:  # noqa: BLE001
            print("read failed:", type(exc).__name__, flush=True)
            continue
        samples += 1
        # النقلة الحقيقية = الأب اتغير وفضل متغير. فالعبرة*Dوام* الأب الجديد
        # لـ 3 عينات، مش تكرار نفس الفرق 3 مرات (فرق واحد ثابت ما بيتكررش).
        for iid, (parent, idx) in cur["where"].items():
            old = prev["where"].get(iid)
            if old and old[0] != parent:
                seen_swaps += 1
                pending[iid] = {"from": old[0], "to": parent, "hits": 1, "last": samples}
                print("move? @%s: %s  %s -> %s" % (
                    time.strftime("%H:%M:%S"), label(iid, cur["by"]),
                    label(old[0], cur["by"]), label(parent, cur["by"])), flush=True)
            elif iid in pending:
                p = pending[iid]
                if parent == p["to"]:
                    p["hits"] += 1
                    if p["hits"] == 3:
                        print("REAL MOVE @%s: %s  %s -> %s (stable %s samples)" % (
                            time.strftime("%H:%M:%S"), label(iid, cur["by"]),
                            label(p["from"], cur["by"]), label(p["to"], cur["by"]), p["hits"]),
                            flush=True)
                elif parent == p["from"]:
                    print("reverted: %s %s -> %s (rotation artifact)" % (
                        label(iid, cur["by"]), label(p["to"], cur["by"]),
                        label(p["from"], cur["by"])), flush=True)
                    pending.pop(iid, None)
        new_nodes = set(cur["by"]) - set(prev["by"])
        gone_nodes = set(prev["by"]) - set(cur["by"])
        if new_nodes or gone_nodes:
            print("nodes changed +%s -%s (total %s)" % (len(new_nodes), len(gone_nodes), cur["n"]),
                  flush=True)
        if samples % 20 == 0:                   # نبضة كل ~30 ثانية عشان نكون متأكدين إنه حي
            print("alive @%s samples=%s swaps_seen=%s nodes=%s" %
                  (time.strftime("%H:%M:%S"), samples, seen_swaps, cur["n"]), flush=True)
        prev = cur
    print("watch over — swaps=%s over %s samples" % (seen_swaps, samples), flush=True)


if __name__ == "__main__":
    main()
