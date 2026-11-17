# -*- coding: utf-8 -*-
"""كل عقدة اتلمست بعد لحظة القبول (updatedAt) — من غير الحاجة لسنابشوت قبلي."""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

CLAIM_AT = 1793497477  # ثواني: لحظة قبول عرض الليمون على G22


def label(names, aid):
    n = names.get(str(aid))
    if isinstance(n, dict):
        return n.get("display_name") or n.get("game_asset_name") or str(aid)
    return str(n or aid)


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    data = pc.fetch_inventory_for(account)
    names = pioneer_tree.asset_names()
    touched = [n for n in (data.get("items") or [])
               if int(n.get("updatedAt") or 0) // 10**9 >= CLAIM_AT]
    print("%s: %d عقدة متلمسة بعد القبول" % (account, len(touched)))
    for n in sorted(touched, key=lambda x: x.get("updatedAt") or 0):
        print("  %-26s amount=%-6s dt=%s | %s" %
              (label(names, n.get("gameAssetId")), n.get("amount"),
               int(n.get("updatedAt") or 0) // 10**9, json.dumps(n, ensure_ascii=False)[:200]))
    mx = max((int(n.get("updatedAt") or 0) // 10**9 for n in data.get("items") or []), default=0)
    print("\nآخر تحديث في الشجرة كلها: %s (القبول كان %s)" % (mx, CLAIM_AT))


if __name__ == "__main__":
    main()
