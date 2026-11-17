# -*- coding: utf-8 -*-
"""صندوق سكرابي في كل حساب: عقد الجيلدا + كل اللي تحته (اللوت المستلم) — قراءة فقط."""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree, store  # noqa: E402

GEN = {"1657228973": "I", "2041317243": "II", "1434069496": "III",
       "2080275953": "IV", "1781867314": "V"}
ROUNDS = "-1869396984"


def label(names, aid):
    n = names.get(str(aid))
    if isinstance(n, dict):
        return n.get("display_name") or n.get("game_asset_name") or str(aid)
    return str(n or aid)


def walk(tree, iid, names, depth=0, out=None):
    out = out if out is not None else []
    for kid in tree.children(iid):
        node = tree._row(kid)
        out.append((depth, str(kid), label(names, node.get("gameAssetId")),
                    int(node.get("amount") or 0), node.get("slots")))
        walk(tree, kid, names, depth + 1, out)
    return out


def main():
    conn = store.db()
    accounts = [a["name"] if isinstance(a, dict) else a for a in store.list_accounts(conn)]
    for account in accounts:
        try:
            data = pc.fetch_inventory_for(account)
        except Exception as err:
            print("%-14s فشل الجلب: %s" % (account, str(err)[:90]))
            continue
        names = pioneer_tree.asset_names()
        tree = pioneer_tree.Tree(data.get("items") or [])
        gens = [str(i) for i, n in tree.by_id.items() if str(n.get("gameAssetId")) in GEN]
        rounds = sum(int(n.get("amount") or 0) for n in (data.get("items") or [])
                     if str(n.get("gameAssetId")) == ROUNDS)
        print("\n%s | Rounds=%s | عقد=%d" % (account, rounds, len(tree.by_id)))
        for g in gens:
            node = tree._row(g)
            kids = walk(tree, g, names)
            print("  Scrappy %s (%s) أب=%s | تحتها %d عقدة" %
                  (GEN.get(str(node.get("gameAssetId"))), g[:8],
                   tree.parent.get(g) or "—", len(kids)))
            for depth, kid, nm, amount, slots in kids[:20]:
                print("      %s%-30s x%s slots=%s" % ("  " * depth, str(nm)[:30], amount, slots))


if __name__ == "__main__":
    main()
