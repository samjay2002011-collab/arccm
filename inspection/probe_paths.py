# -*- coding: utf-8 -*-
"""بيختبر وجود مسار على البوابة الرسمية من غير ما ينفّذه: GET على مسار كتابة بيرد
405 Method Not Allowed، والمسار مش الموجود بيرد 404 page not found.
(403 RBAC معناه إن المسار بره الـACL بتاع التوكن — وده مش دليل على وجوده.)

ده نفس الميزان اللي كشف `/v1/pioneer/inventory/upgrade` و`/v1/pioneer/offers/accept`.
الأسماء هنا مش تخمين حر: طلعت من جدول أسماء اللعبة نفسه (FPioneerOnline*Request و
EPioneerOnlineOperationType::MoveItem/SetParents/…) اللي اتلمّ من الذاكرة.

    python -m inspection.probe_paths batch G22
    python -m inspection.probe_paths claim G22
    python -m inspection.probe_paths "/v1/pioneer/inventory/v1/batch,/v1/pioneer/batch"
"""
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402

RES = ["inventory", "inventories", "items", "item", "batch", "operation", "operations",
       "offers", "generators", "generator", "resource-generators", "resource_generator",
       "scrappy", "rooster", "collect", "claims"]

ACTS = ["mutate", "batch-mutate", "batch", "batch-operation", "batch-operations",
        "operation", "operations", "claim", "collect", "harvest", "feed", "donate",
        "commit", "deposit", "withdraw", "claim-scrappy", "collect-scrappy",
        "scrappy-claim", "claim-rewards", "rewards", "open", "apply", "run",
        "execute", "sync", "refresh", "generate", "payout", "claim-all", "collect-all"]

PRESETS = {
    "batch": ["/v1/pioneer/%s/%s" % (r, a) for r in RES for a in ACTS]
             + ["/v1/pioneer/%s/v1/%s" % (r, a) for r in RES for a in ACTS],
    "claim": ["/v1/pioneer/%s/%s" % (r, a) for r in RES for a in
              ["claim", "collect", "harvest", "feed", "donate", "commit", "deposit",
               "claim-scrappy", "collect-scrappy", "claim-rewards", "rewards", "payout"]]
             + ["/v1/pioneer/%s/v1/%s" % (r, a) for r in RES for a in
                ["claim", "collect", "harvest", "donate"]],
}
CONTROLS = ["/v1/pioneer/inventory/v1/mutate", "/v1/pioneer/inventory/upgrade",
            "/v1/pioneer/offers/accept", "/v1/pioneer/zzz-not-a-route"]


def probe(path, token):
    try:
        pc.request(path, token=token, method="GET")
        return "200"
    except pc.PioneerError as exc:
        text = str(exc)
        for code in ("405", "404", "403", "401", "412", "400", "500"):
            if " -> %s" % code in text:
                return code
        return text[:60]
    except Exception as exc:  # noqa: BLE001
        return "ERR " + str(exc)[:60]


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "batch"
    account = sys.argv[2] if len(sys.argv) > 2 else "G22"
    if which in PRESETS:
        paths = PRESETS[which]
    else:
        paths = [p.strip() for p in which.split(",") if p.strip()]
    token = pc.account_token(account)
    if not token:
        print("مافيش توكن لـ", account)
        return
    print("== ضوابط ==")
    for path in CONTROLS:
        print("   %-42s -> %s" % (path, probe(path, token)))
    print("\n== %d مرشح ==" % len(paths))
    alive = []
    for path in dict.fromkeys(paths):
        r = probe(path, token)
        if r != "404":
            alive.append((path, r))
            print("   *** %-52s -> %s" % (path, r))
    print("\nالنتيجة: %d مسار مش 404 من %d" % (len(alive), len(paths)))


if __name__ == "__main__":
    main()
