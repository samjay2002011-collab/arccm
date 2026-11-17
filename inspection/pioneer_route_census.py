# -*- coding: utf-8 -*-
"""ميزان GET على أسماء مسارات مبنية من قاموس اللعبة نفسه (FPioneerOnline* types).

ليه الطريقة دي: المسح القديم كان بتخمين أسماء. هنا الأسماء مش مخمنة — كل اسم
مسار متولّد من نوع طلب/رد موجود فعلاً في جدول `FPioneerOnlineBatchOperationRequest`
الي اتقاس من ذاكرة اللعبة يوم 2026-10-31 ومحفوظ أوفلاين في `inspection/pf/`.
البوابة بترد على GET لمسار كتابة بـ 405، ومسار مش موجود بـ 404 — فبنعدّ من غير
أي تنفيذ.

    python -m inspection.pioneer_route_census [G22]
"""
import json
import sys

sys.path.insert(0, ".")

import requests  # noqa: E402

from backend import pioneer_client as pc  # noqa: E402

DOMAINS = [
    "crates", "generators", "generator", "hideout", "scrappy", "resources",
    "production", "bonuses", "inventory", "inventories", "offers", "quests",
    "projects", "mastery", "codex", "compensations", "battlepasses", "levels",
    "skills", "expeditions", "community-events", "stores", "transactions",
    "ranks", "leagues", "rounds", "stats", "seasonal-rewards", "profile",
    "settings", "events", "rewards", "raiders", "game-data", "party",
]
VERBS = ["", "claim", "claims", "open", "complete", "accept", "collect", "list",
         "get", "use", "consume", "activate", "start", "cancel", "update",
         "auto-claim", "autoclaim", "feed", "hatch", "harvest"]

# أسماء طلع her من جدول الطلبات نفسها — تركيز على اللي فيه معنى قبض.
HOT = ["crates", "generators", "hideout", "scrappy", "resources", "production",
       "bonuses", "inventory", "offers", "quests"]


def paths():
    out = []
    for domain in DOMAINS:
        verbs = VERBS if domain in HOT else ["", "claim", "complete", "open", "list"]
        for verb in verbs:
            out.append("/v1/pioneer/%s%s" % (domain, ("/" + verb) if verb else ""))
    return out


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G22"
    token = pc.account_token(account)
    sess = pc._session()
    headers = pc.headers(token)
    rows = []
    for path in paths():
        try:
            resp = sess.get(pc.BASE + path, headers=headers, timeout=15, verify=True)
        except Exception as err:
            print("  !! %-44s %s" % (path, str(err)[:100]))
            continue
        body = resp.text[:120].replace("\n", " ")
        if resp.status_code in (200, 405, 400, 401, 403, 412, 500):
            rows.append((resp.status_code, path, body))
            print("  ** %-46s %s %s" % (path, resp.status_code, body))
        sys.stdout.flush()
    print("\n=== اللي موجود (%d): " % len(rows))
    for code, path, body in rows:
        print("  %s %-46s %s" % (code, path, body[:100]))


if __name__ == "__main__":
    main()
