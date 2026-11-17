# -*- coding: utf-8 -*-
"""قراية quests + ميزان أفعال جديد — قراءة-only بس (GET).

ليه: ميزان 2026-11-01 طلع `/v1/pioneer/quests/complete` بـ 405 = مسار كتابة موجود،
وهو أول مسار كتابة جديد يظهر من وقت `/v1/pioneer/inventory/upgrade`. الشجرة نفسها
بتقول إن صندوق الديك مش فيها (عقدة Scrappy V بلا أب و`slots: null`)، فاللوت لازم
يكون متخمّن في نظام تاني — و`state` + `expiresAt` + `objectives` بتاع الـ quests
هو أقرب شكل لـ "في حاجة مستنية القبض".

    python -m inspection.scrappy_quests G22
"""
import json
import sys

sys.path.insert(0, ".")

import requests  # noqa: E402

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

VERBS = [
    "/v1/pioneer/quests",
    "/v1/pioneer/quests/complete",
    "/v1/pioneer/quests/claim",
    "/v1/pioneer/quests/collect",
    "/v1/pioneer/quests/reward",
    "/v1/pioneer/quests/rewards",
    "/v1/pioneer/quests/activate",
    "/v1/pioneer/quests/abandon",
    "/v1/pioneer/quests/reset",
    "/v1/pioneer/quests/start",
    "/v1/pioneer/quests/update",
    "/v1/pioneer/quests/delete",
    "/v1/pioneer/bonuses/complete",
    "/v1/pioneer/bonuses/use",
    "/v1/pioneer/bonuses/activate",
    "/v1/pioneer/bonuses/consume",
    "/v1/pioneer/bonuses/collectall",
    "/v1/pioneer/inventory/complete",
    "/v1/pioneer/inventory/feed",
    "/v1/pioneer/inventory/generate",
    "/v1/pioneer/inventory/harvest",
    "/v1/pioneer/inventory/upgrade",
    "/v1/pioneer/inventory/v1/complete",
    "/v1/pioneer/zzz-not-a-route",
]

INTEREST = ("scrappy", "rooster", "generat", "resource", "box", "collection", "hideout",
            "poultry", "chicken", "coop")


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    names = pioneer_tree.asset_names()
    payload = pc.request("/v1/pioneer/quests", token=token) or {}
    quests = payload.get("quests") or payload.get("items") or []
    if not quests:
        print("شكل الرد:", json.dumps(payload, ensure_ascii=False)[:600])
        return
    print("### %s — عدد الـ quests: %d | مفاتيح أعلى مستوى: %s"
          % (account, len(quests), sorted(payload.keys())))
    states = {}
    for q in quests:
        states[str(q.get("state"))] = states.get(str(q.get("state")), 0) + 1
    print("حالات:", json.dumps(states, ensure_ascii=False))
    keys = {}
    for q in quests:
        for k in q:
            keys[k] = keys.get(k, 0) + 1
    print("الحقول:", json.dumps(keys, ensure_ascii=False))
    # أي quest اسم أصلها أو اسم objectives فيها كلمة لها علاقة بالديك؟
    interesting = []
    for q in quests:
        row = names.get(str(q.get("gameAssetId"))) or {}
        label = (row.get("display_name") or row.get("game_asset_name") or "").lower()
        blob = json.dumps(q, ensure_ascii=False).lower()
        if any(w in label or w in blob for w in INTEREST):
            interesting.append((label, q))
    print(" quests فيها كلمة ديكية/صندوق/توليد:", len(interesting))
    for label, q in interesting[:8]:
        print("   %-26s %s" % (label or "?", json.dumps(q, ensure_ascii=False)[:520]))
    # نموذج كامل لكل حالة موجودة
    seen = set()
    for q in quests:
        st = str(q.get("state"))
        if st in seen:
            continue
        seen.add(st)
        row = names.get(str(q.get("gameAssetId"))) or {}
        print("نموذج حالة %s [%s]:\n   %s"
              % (st, row.get("display_name") or "?", json.dumps(q, ensure_ascii=False)[:700]))

    sess = pc._session()
    headers = pc.headers(token)
    print("\n### ميزان الأفعال (GET) — 405=موجود / 404=مش موجود / 500=موجود بس محتاج POST")
    for path in VERBS:
        try:
            resp = sess.get(pc.BASE + path, headers=headers, timeout=20, verify=True)
        except Exception as err:
            print("  !! %-42s %s" % (path, str(err)[:110]))
            continue
        mark = "**" if resp.status_code in (200, 405, 500) else "  "
        print("  %s %-44s %s %s" % (mark, path, resp.status_code,
                                    resp.text[:78].replace("\n", " ")))


if __name__ == "__main__":
    main()
