# -*- coding: utf-8 -*-
"""جرد خام لمسارات القراءة الرسمية: كل مفتاح رجّعته البوابة لكل حساب.

ليه: الشجرة (`items`) وحدها بتخفي أي قسم تاني في الرد — لو البوابة بترجّع
صندوق Scrappy أو عروض أو مهمة في مفتاح جانبي، الجرد ده بيكشّفه من غير أي
تخمين لمسار جديد. قراءة فقط، مفيش ولا طلب كتابة.

    python -m inspection.api_surface_dump            # كل الحسابات
    python -m inspection.api_surface_dump G14        # حساب واحد
"""
import json
import sqlite3
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import config, pioneer_client as pc  # noqa: E402

PATHS = ("/v1/pioneer/inventory", "/v1/pioneer/bonuses", "/v1/pioneer/quests",
         "/v1/pioneer/raiders", "/v1/pioneer/offers", "/v1/pioneer/profile",
         "/v1/pioneer/settings", "/v1/pioneer/progression", "/v1/pioneer/stats")
MAX_JSON = 200


def preview(value):
    if isinstance(value, list):
        return "list(%d) %s" % (len(value), json.dumps(value[:1], ensure_ascii=False)[:MAX_JSON])
    if isinstance(value, dict):
        return "dict%s -> %s" % (sorted(value)[:8], json.dumps(value, ensure_ascii=False)[:MAX_JSON])
    return json.dumps(value)[:MAX_JSON]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    db = sqlite3.connect(config.DB_FILE)
    try:
        rows = db.execute("SELECT name FROM accounts ORDER BY name").fetchall()
    finally:
        db.close()
    names = [r[0] for r in rows if not only or r[0] == only or only.lower() in r[0].lower()]
    print("accounts:", names)
    for name in names:
        token = pc.account_token(name)
        if not token:
            print("== %s: مفيش توكن" % name)
            continue
        print("\n===== %s =====" % name)
        for path in PATHS:
            try:
                data = pc.request(path, token=token)
            except Exception as exc:
                print("  %-24s ERR %s" % (path, str(exc)[:100]))
                continue
            if isinstance(data, dict):
                print("  %-24s keys=%s" % (path, sorted(data)))
                for key, value in sorted(data.items()):
                    if key == "items":
                        print("      items: %d nodes" % len(value or []))
                        continue
                    print("      %-14s %s" % (key, preview(value)))
            else:
                print("  %-24s %s" % (path, preview(data)))


if __name__ == "__main__":
    main()
