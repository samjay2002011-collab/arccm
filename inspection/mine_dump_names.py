"""تنقيب `data/craft_offers_raw.json` (طرح قديم لرامبارت محلي) عن pairs (asset_id -> اسم).

الهدف: نعرف حجم الأسماء اللي عندنا بالفعل على القرص ومفيش منها في فهرس الأصول،
قبل ما نقرر مصدر تاني. قراءة فقط.
"""
import collections
import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import pioneer_tree  # noqa: E402

SRC = ROOT / "data" / "craft_offers_raw.json"
OUT = Path(__file__).with_name("_dump_names.json")


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


def walk(x, pairs):
    if isinstance(x, str):
        try:
            for inner in decode_stream(x):
                walk(inner, pairs)
        except ValueError:
            pass
        return
    if isinstance(x, dict):
        aid = x.get("asset_id")
        nm = x.get("display_name")
        if aid is not None and isinstance(nm, str) and nm:
            pairs[str(aid)].add(nm)
        for v in x.values():
            walk(v, pairs)
    elif isinstance(x, list):
        for v in x:
            walk(v, pairs)


def main():
    pairs = collections.defaultdict(set)
    walk(json.load(open(SRC, encoding="utf-8")), pairs)
    names = {k: sorted(v) for k, v in pairs.items()}
    OUT.write_text(json.dumps(names, ensure_ascii=False, indent=1), encoding="utf-8")

    an = pioneer_tree.asset_names()
    missing = {k: v for k, v in names.items()
               if not ((an.get(k) or {}).get("display_name") or (an.get(k) or {}).get("game_asset_name"))}
    print("أسماء في الطرح:", len(names))
    print("منها مش في فهرس الأصول:", len(missing))
    print("955405569 ->", names.get("955405569"))
    for k in list(missing)[:20]:
        print("   ", k, missing[k])


if __name__ == "__main__":
    main()
