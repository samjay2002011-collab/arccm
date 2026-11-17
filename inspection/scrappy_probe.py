"""ينقل صندوق جمع Scrappy من شجرة المخزن الرسمية — فين اللوت المتجمّع فعلًا؟

قراءة فقط: مفيش أي كتابة في السكريبت ده.
  python inspection/scrappy_probe.py G18
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import pioneer_client as pc, pioneer_tree as pt

GEN_RE = re.compile(r"ResourceGenerator", re.I)
KEY_RE = re.compile(r"haul|collection|reward|claim|feed|queue|box|crate|generator", re.I)


def main(account="G18"):
    data = pc.fetch_inventory_for(account) or {}
    tree = pt.Tree(data.get("items") or [])
    print("nodes:", len(tree.by_id), " roots:", len(tree.roots()))

    def asset(iid):
        return tree._row(iid).get("game_asset_name") or ""

    def label(iid):
        return tree.label(iid) or ""

    print("\n== عقد ResourceGenerator / Scrappy ==")
    for e in tree.items:
        iid = str(e["instanceId"])
        if not (GEN_RE.search(asset(iid)) or "scrappy" in label(iid).lower()):
            continue
        p = tree.parent.get(iid) or ""
        print("%s | %s | %s" % (iid[:8], label(iid), asset(iid)))
        print("   parent=%s (%s)" % (p[:8] or "None", label(p) or "-"))
        print("   slots=%s amount=%s children=%s" % (e.get("slots"), e.get("amount"),
                                                     [label(k) for k in tree.children(iid)]))
        print("   extra=%s" % {k: v for k, v in e.items()
                               if k not in ("instanceId", "gameAssetId", "slots")})

    print("\n== Roots ==")
    for r in tree.roots():
        print("  %s | %s | kids=%d | amount=%s | parent=%s" % (
            r[:8], label(r), len(tree.children(r)), tree.amount(r),
            (tree.parent.get(r) or "None")[:8]))

    print("\n== أي عقدة اسمها haul/collection/reward/feed/box ==")
    hits = 0
    for e in tree.items:
        iid = str(e["instanceId"])
        if not KEY_RE.search(label(iid) + " " + asset(iid)):
            continue
        hits += 1
        p = tree.parent.get(iid) or ""
        print("  %s | %s | %s | kids=%d | parent=%s (%s)" % (
            iid[:8], label(iid)[:40], asset(iid)[:44], len(tree.children(iid)),
            p[:8] or "None", label(p)[:32]))
    if not hits:
        print("  (مفيش)")

    print("\n== أكبر 15 حاوية (عدد الأطفال) ==")
    for iid, kids in sorted(tree.kids.items(), key=lambda kv: -len(kv[1]))[:15]:
        p = tree.parent.get(iid) or ""
        print("  %s | %s | %d kids | parent=%s (%s)" % (
            iid[:8], label(iid)[:44], len(kids), p[:8] or "None", label(p)[:30]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "G18")
