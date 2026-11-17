# -*- coding: utf-8 -*-
"""بيكشف الطرق التانية على المسارات اللي أصلًا بتقبل GET — ده الكفيف اللي مابقاش
باقي مسح الأسماء.

الحاجة اللي اتعلمتها: `/v1/pioneer/inventory` بيقبل GET (بيرجّع الشجرة). لو نفس
المسار بيقبل POST/PATCH/PUT كمان، الـ405 اللي بنطارد بيها المسارات الجديدة مش هيشوفه
خلصانة، لأن GET بيرد 200 قبل ما نوصل. فبنعدّي على كل مسار معروف بكل الـverbs وبنقرأ
الرد:
  405 → الطريقة مش مسجلة
  404 → مفيش حاجة
  400/412/422 + `cannot unmarshal …` → الطريقة موجودة فعلاً والجسم بيتحلل في نوع
     Go معروف — وده بيعطينا اسم الـRequest وحقله (نفس الحيلة اللي كشفت /inventory/upgrade)

الأجسام كلها خاطئة النوع بالعمد (شيء/كائن مكان نص) عشان ما تنفذش حاجة: بقتل قبل ما
تلمس أي عنصر.

    python -m inspection.probe_methods G22
"""
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

import requests  # noqa: E402
from backend import pioneer_client as pc  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"
METHODS = ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
PATHS = ["/v1/pioneer/inventory", "/v1/pioneer/bonuses", "/v1/pioneer/quests",
         "/v1/pioneer/raiders", "/v1/pioneer/inventory/v1", "/v1/pioneer/offers",
         "/v1/pioneer/progression", "/v1/pioneer/character", "/v1/pioneer/hideout",
         "/v1/pioneer/generators", "/v1/pioneer/scrappy", "/v1/pioneer/rewards",
         "/v1/pioneer/batch", "/v1/pioneer/operations", "/v1/pioneer/sessions",
         "/v1/shared/profile"]
BODIES = [{"instanceId": {"zzz": 1}}, {"items": {"zzz": 1}}, {"amount": "abc"}, {}]


def call(sess, url, method, headers, body):
    try:
        r = sess.request(method, url, headers=headers,
                         json=body if body is not None else None, timeout=15)
    except Exception as exc:  # noqa: BLE001
        return "ERR " + str(exc)[:70]
    text = (r.text or "").strip().replace("\n", " ")
    return "%s %s" % (r.status_code, text[:170])


def main():
    token = pc.account_token(ACCOUNT)
    if not token:
        print("مافيش توكن لـ", ACCOUNT)
        return
    headers = pc.headers(token, pc.load_manifest())
    sess = requests.Session()
    print("== verbs على مسارات بتقبل GET أصلًا ==")
    for path in PATHS:
        url = pc.BASE + path
        line = []
        for method in METHODS:
            r = call(sess, url, method, headers, BODIES[0])
            if not r.startswith("405") and not r.startswith("404"):
                line.append("%s->%s" % (method, r[:120]))
        base = call(sess, url, "GET", headers, None)
        print("   %-30s GET=%s%s" % (path, base[:3],
                                     ("\n       " + "\n       ".join(line)) if line else ""))

    print("\n== تنويع الأجسام على /v1/pioneer/inventory (POST) ==")
    for body in BODIES:
        print("   %-28s -> %s" % (str(body)[:26],
                                  call(sess, pc.BASE + "/v1/pioneer/inventory", "POST",
                                       headers, body)))


if __name__ == "__main__":
    main()
