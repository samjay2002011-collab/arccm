"""فرق حسابات على عقد التفعيل: إيه العائم اللي عند حساب ومفيش عند التاني؟

الطريقة (قياس بس، GET واحد لكل حساب):
  - U = أصول عقد "Unlock Craft" المعروفة في الفهرس المحلي (اسمها بيبدأ بالقافية دي).
  - لكل حساب: Ck = العائم اللي مفيش له slots (ورقة واحدة).
  - Ck - عقدة معروفة = مرشحون عقد تفعيل مجهولة الاسم (دي اللي بتضيع منّا).
  - الفرق بين حساب مفعل كتير (RAIDER38830/G22) وحساب صفر (G18) = الأدلة المجهولة.
"""
import builtins
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, pioneer_client as pc, pioneer_tree, store  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_node_assetdiff_out.txt")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_trees_cache.json.gz")
ACCOUNTS = ["RAIDER38830", "G22", "RAIDER74888", "G18"]
PREFIX = "Unlock Craft "


def load_trees():
    if os.path.isfile(CACHE):
        with gzip.open(CACHE, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    conn = store.db()
    out = {}
    for acc in ACCOUNTS:
        try:
            data = pc.fetch_inventory_for(acc)
        except Exception as exc:  # noqa: BLE001
            out[acc] = None
            continue
        out[acc] = (data or {}).get("items") or []
    with gzip.open(CACHE, "wt", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


def main():
    names = pioneer_tree.asset_names()
    unlock_assets = {}
    for aid, row in names.items():
        label = str(row.get("display_name") or row.get("game_asset_name") or "").strip()
        if label.startswith(PREFIX):
            unlock_assets[str(aid)] = label[len(PREFIX):].strip()
    trees = load_trees()
    lines = []
    say = lambda *a: lines.append(" ".join(str(x) for x in a))  # noqa: E731
    say(f"أصول عقد Unlock Craft في الفهرس: {len(unlock_assets)}")

    leaf_sets, info = {}, {}
    for acc in ACCOUNTS:
        items = trees.get(acc)
        if not items:
            say(f"\n== {acc}: مفيش قراءة ({'توكن ميت' if acc in trees else 'فشل'})")
            continue
        tree = pioneer_tree.Tree(items)
        leaves = {}
        for iid, entry in tree.by_id.items():
            if entry.get("slots"):
                continue
            if tree.parent.get(iid):
                continue
            aid = str(entry.get("gameAssetId"))
            leaves.setdefault(aid, []).append(iid)
        leaf_sets[acc] = set(leaves)
        known = {a for a in leaves if a in unlock_assets}
        unknown = {a for a in leaves if a not in unlock_assets}
        named_other = {a for a in unknown if str(a) in names}
        info[acc] = (leaves, known, unknown, named_other)
        say(f"\n== {acc}: عائم بلا slots={len(leaves)} منها عقد تفعيل معروفة={len(known)} "
            f"غير معروفة={len(unknown)} (ليها اسم تاني في الفهرس={len(named_other)})")

    base = leaf_sets.get("G18") or set()
    say("\n== الأصول العائمة الموجودة عند حسابات مفعةلة ومفيضة عند G18 (صفر تفعيل) ==")
    merged = {}
    for acc in ACCOUNTS:
        if acc == "G18" or acc not in leaf_sets:
            continue
        for aid in leaf_sets[acc] - base:
            merged.setdefault(aid, []).append(acc)
    for aid, accs in sorted(merged.items(), key=lambda i: (-len(i[1]), i[0])):
        row = names.get(str(aid)) or {}
        label = str(row.get("display_name") or row.get("game_asset_name") or "")
        say(f"  {aid:>13} في={','.join(accs):28s} اسم الفهرس={label!r}")
    say(f"\nالإجمالي: {len(merged)} أصل عائم جديد على G18")
    say(f"منها معروفة كعقدة تفعيل: {sum(1 for a in merged if a in unlock_assets)}")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    builtins.print("wrote", OUT, "| cache:", CACHE)


if __name__ == "__main__":
    main()
