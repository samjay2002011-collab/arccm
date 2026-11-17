# -*- coding: utf-8 -*-
"""آخر محور متفتح: الهيدرات اللي اللعبة بعتها واحنا مش بنبعتها.

ليه: الـ enum بتاع `split/combine/stack_merge` مربوط بنطاق الثقة مش بشكل الجسم
(اتقيس). اللعبة بعتت نفس الـ discriminator ونجح — يبقى الفرق اما توكن او هيدر.
التوكن اتسحب من الذاكرة ومفيش أغنى منه، فالباقي الهيدرات. من مسح FName في ذاكرة
اللعبة طلع إنها تبعت `x-embark-request-id` و`x-toy-client-id` و
`x-embark-client-session-id` و`platform-id` و`x-toy-service-id` و
`nexon-service-id` و`x-embark-trace-id` — واحنا مانبعتش ولا واحد منهم.

أوراكل بصفر أثر: `instanceId` وهمي عنصرياً.
  INVENTORY_ITEM_NOT_FOUND ⇐ الـ discriminator اتفتح (ننتقل لمرحلة التحقق من الآيدي)
  UNKNOWN                  ⇐ لسه مقفول
`update` مع نفس الآيدي الوهمي = كنترول لازم يفضل NOT_FOUND طول التجربة.

    python -m inspection.probe_split_headers
    python -m inspection.probe_split_headers G18
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "RAIDER60766"
FAKE = "00000000-0000-4000-8000-000000000000"
UUID = pc.telemetry_uuid()
TOK = pc.account_token(ACCOUNT)   # ثابت: pc.account_token بقرا قيمة مختلفة كل مرة لو حساب تاني اتحفظ
MANIFEST = pc.load_manifest()

# القيم بأكثر من شكل محتمل لأن مافيش وثيقة تقول الصيغة — الأوراكل بيفرّق لو افتتح.
SESSION_IDS = {
    "x-embark-request-id": [UUID, "1", "probe-%s" % int(time.time())],
    "x-embark-client-session-id": [UUID, str(int(time.time()))],
    "x-toy-client-id": ["embark-pioneer", "pioneer-game", UUID],
    "x-toy-service-id": ["pioneer", "inventory"],
    "platform-id": ["3", "steam", "windows"],
    "nexon-service-id": ["pioneer"],
    "x-embark-trace-id": [UUID, "trace-%s" % int(time.time())],
}
# UA الحرفي اللي اللعبة تبعتة (اتقرا من الذاكرة) — يمكن البوابة تفرّق بين launcher وعميل.
GAME_UA = ("PioneerGame/pioneer_2.03.x-CL-1438640 (http-eventloop) "
           "Windows/10.0.19045.1.256.64bit")


def reason_of(status, text):
    try:
        body = json.loads(text)
        return str(body.get("reason") or body.get("detail") or "?")
    except Exception:
        return "%s %s" % (status, text[:70].replace("\n", " "))


def post(discriminator, extra=None, ua=None, manifest=MANIFEST):
    """urllib بياخد 403 من جوجل فرونت على الـPOST — بنستخدم نفس session بتاع الموقع."""
    h = pc.headers(TOK, manifest if manifest is not None else "")
    if ua:
        h["User-Agent"] = ua
    h.update(extra or {})
    body = {"mutations": [{"discriminator": discriminator, "instanceId": FAKE,
                           "amount": 1}], "requestId": ""}
    r = pc._session().request("POST", pw._url(), headers=h, json=body, timeout=15,
                              verify=True)
    return r.status_code, r.text[:300]


def tag(status, text):
    r = reason_of(status, text)
    return "UNLOCKED" if "NOT_FOUND" in r else ("locked" if "UNKNOWN" in r else r[:24])


def main():
    print("الحساب: %s | الآيدي الوهمي: %s" % (ACCOUNT, FAKE))
    c = post("update")
    print("كنترول update   -> %s  [%s]" % (reason_of(*c), tag(*c)))
    base = post("split")
    print("اساس split      -> %s  [%s]" % (reason_of(*base), tag(*base)))
    if tag(*c) != "UNLOCKED":
        print("\nالكنترول نفسه مابقاش NOT_FOUND — يعني الطلبات مش واصلة للبوابه "
              "أصلاً (رد %s). مافيش معنى لأي نتيجة بعد كده، وقفت." % reason_of(*c))
        return
    print("\n== كل هيدر لوحده (قيم متعددة) ==")
    for name, values in SESSION_IDS.items():
        for val in values:
            s, t = post("split", {name: val})
            r = tag(s, t)
            mark = "  <<<!!!!" if r == "UNLOCKED" else ""
            print("  split + %-28s=%-22s %s%s" % (name, str(val)[:22], r, mark))
            time.sleep(0.35)
    print("\n== كل الهيدرات مع بعض ==")
    all_h = {k: v[0] for k, v in SESSION_IDS.items()}
    s, t = post("split", all_h)
    print("  split + الكومبو            %s%s" % (tag(s, t), "  <<<!!!!" if tag(s, t) == "UNLOCKED" else ""))
    print("\n== يوزر-إجنت اللعبة نفسه ==")
    s, t = post("split", all_h, ua=GAME_UA)
    print("  split + UA اللعبة          %s%s" % (tag(s, t), "  <<<!!!!" if tag(s, t) == "UNLOCKED" else ""))
    s, t = post("stack_merge", all_h, ua=GAME_UA)
    print("  stack_merge + UA اللعبة    %s%s" % (tag(s, t), "  <<<!!!!" if tag(s, t) == "UNLOCKED" else ""))
    print("\n== من غير manifest-id خالص (يمكن يكون هو البوابة) ==")
    s, t = post("split", all_h, manifest="")
    print("  split + بلا manifest       %s%s" % (tag(s, t), "  <<<!!!!" if tag(s, t) == "UNLOCKED" else ""))
    print("\nكل الطلبات بآيدي وهمي — مافيش أي أثر على المخزون.")


if __name__ == "__main__":
    main()
