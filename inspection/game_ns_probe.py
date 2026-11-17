# -*- coding: utf-8 -*-
"""هل توكن اللعبة بيفتح namespace اللعبة (/v1/inventory/...) ولا الرفيق بس؟

    python -m inspection.game_ns_probe            # اللعبة لازم تكون مفتوحة

المسح قراءة بس من الذاكرة (مفيش التقاط شهادات)، والطلبات كلها بمعرّف وهمي
وكمية مستحيلة: مافيش عنصر بالآيدي ده فمستحيل يغيّر حاجة في الحساب.
بنختبر مسارات تقسيم/لمّ فقط — مش أي مسار يقبل شغل بجسم فاضي.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt                      # noqa: E402
from backend import pioneer_client as pc              # noqa: E402
from inspection.jwt_harvest import harvest, reason    # noqa: E402

FAKE = "00000000-0000-4000-8000-000000000000"

# جسم فيه معرّف وهمي + كمية مستحيلة — أي مسار يقبله هيرفض في الفحص.
BODY = {"instanceId": FAKE, "targetWrapperId": FAKE, "targetInstanceId": FAKE,
        "amount": -1, "mutations": [{"discriminator": "update", "instanceId": FAKE,
                                     "slots": [FAKE], "amount": -1}], "requestId": ""}

PATHS = [
    "/v1/pioneer/inventory/v1/mutate",     # مسارنا الشغال — نقطة مقارنة
    "/v1/inventory/split",
    "/v1/inventory/merge",
    "/v1/inventory/mutate",
]


def oracle(token):
    out = {}
    try:
        pc.request("/v1/pioneer/inventory", token=token, timeout=15)
        out["read"] = "ok"
    except Exception as exc:        # noqa: BLE001
        out["read"] = reason(exc)
    for path in PATHS:
        try:
            pc.post_json(pc.BASE + path, BODY, token=token)
            out[path] = "200 قَبِل!!"
        except Exception as exc:    # noqa: BLE001
            out[path] = reason(exc)
        time.sleep(0.12)
    return out


def main():
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — افتح ARC Raiders وشغّل الأمر ده تاني.")
        return 1
    print("مسح ذاكرة %s ..." % pids)
    rows = harvest(pids)
    print("توكنات فريدة: %d\n" % len(rows))
    for r in rows:
        tag = "%-18s aud=%-24s scp=%-10s" % (r["client_id"] or "-", (r["aud"] or "-")[:24],
                                             str(r["scp"])[:10])
        if not r["live"]:
            print("%s منتهي (%s)" % (tag, time.strftime("%m-%d %H:%M", time.localtime(r["exp"]))))
            continue
        res = oracle(r["token"])
        print(tag)
        for k, v in res.items():
            print("     %-42s %s" % (k.replace("/v1/", ""), v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
