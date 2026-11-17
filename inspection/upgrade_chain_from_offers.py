"""يدوّر في طرح العروض القديم على أي عرض **بيستهلك** قطعة ويطلع قطعة تانية.

الهدف: إثبات رقم Stiletto II و III من غير تخمين. الطرح فيه لكل عرض:
  `cost[]` (asset_id + meta) و `reward.asset_id` + `reward_meta` (فيه `quality_level`).
لو طلع عرض ترقية بيبلع Stiletto (quality_level 0) ويرجع قطعة تانية، فالرقم المرجّع
هو مستوى السلاح الجاي بالظبط — وبنفس المنطق نقدر نطلّع سلسلة كاملة.

  python inspection/upgrade_chain_from_offers.py [asset_id ...]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUMP = ROOT / "data" / "craft_offers_raw.json"


def decode_stream(text):
    dec = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \r\n\t":
            i += 1
        if i >= n:
            return
        obj, end = dec.raw_decode(text, i)
        yield obj
        i = end


def offers(node, out):
    """أي dict شكله عرض: فيه reward (أو reward_meta) و cost."""
    if isinstance(node, str):
        try:
            for inner in decode_stream(node):
                offers(inner, out)
        except ValueError:
            pass
        return
    if isinstance(node, dict):
        if "reward" in node or "reward_meta" in node:
            out.append(node)
        for value in node.values():
            offers(value, out)
    elif isinstance(node, list):
        for value in node:
            offers(value, out)


def aid(v):
    return str(v).strip() if v is not None else ""


def cost_ids(off):
    return [aid(c.get("asset_id")) for c in (off.get("cost") or []) if isinstance(c, dict)]


def meta_name(meta):
    return str((meta or {}).get("display_name") or "").strip()


def main():
    wanted = [str(a) for a in sys.argv[1:]]
    text = DUMP.read_text(encoding="utf-8")
    found = []
    offers(text, found)
    print("عروض في الطرح:", len(found))

    # 1) أي عرض بيستهلك القطعة اللي بنسأل عنها؟
    for target in wanted:
        hits = [o for o in found if target in cost_ids(o)]
        print("\n=== عروض بتستهلك %s: %d" % (target, len(hits)))
        for o in hits:
            rm = o.get("reward_meta") or {}
            print("   reward -> %s (%s) quality_level=%s rarity=%s" %
                  (aid(o.get("reward") or rm.get("asset_id")), meta_name(rm) or "؟",
                   rm.get("quality_level"), rm.get("rarity")))
            for c in cost_ids(o):
                row = next((x for x in (o.get("cost") or [])
                            if isinstance(x, dict) and aid(x.get("asset_id")) == c), {})
                print("      cost %s = %s ×%s" % (c, meta_name(row.get("meta")) or "؟",
                                                  row.get("amount")))

    # 2) أي سلاح في الطرح ليه سلسلة مستويات (نفس الاسم بـ quality_level مختلفة)؟
    by_name = {}
    for o in found:
        rm = o.get("reward_meta") or {}
        nm = meta_name(rm)
        if nm and rm.get("quality_level") is not None:
            by_name.setdefault(nm, set()).add((str(rm.get("quality_level")),
                                              aid(o.get("reward") or rm.get("asset_id"))))
    chains = {k: sorted(v) for k, v in by_name.items() if len(v) > 1}
    print("\n=== أسماء ليها أكتر من quality_level في الطرح: %d" % len(chains))
    for k, v in list(chains.items())[:12]:
        print("   ", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
