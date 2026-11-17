"""بنسأل الموقع نفسه: ترتيب الأعمدة ومستوى كل محطة ومصدرها لكل حساب.

    python inspection/workshop_board_check.py

قراءة من الـ API المحلي بس — مفيش طلب للشبكة الخارجية ولا كتابة.
"""
import io
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc, store  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_workshop_board_out.txt")
SITE = "http://127.0.0.1:8000/api/workshop"


def main():
    buf = io.StringIO()
    w = buf.write
    conn = store.db()
    accounts = [a["name"] if isinstance(a, dict) else a for a in store.list_accounts(conn)]
    token = pc.account_token() or "probe"
    for _ in range(24):
        try:
            requests.get(SITE, params={"account": accounts[0], "t": token}, timeout=5)
            break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    for account in accounts:
        try:
            resp = requests.get(SITE, params={"account": account, "t": token}, timeout=25)
        except Exception as err:  # noqa: BLE001
            w("\n===== %s: الموقع رافض (%s)\n" % (account, str(err)[:90]))
            continue
        if resp.status_code != 200:
            w("\n===== %s: HTTP %s\n" % (account, resp.status_code))
            continue
        data = resp.json()
        w("\n===== %s\n" % account)
        for col in data.get("stations") or []:
            w("   %-18s LV %-2s مصدر=%-7s الجاي=%s الوصفات=%s المسموحة=%s\n" % (
                col.get("label"), col.get("level"), col.get("level_source") or "-",
                (col.get("next") or {}).get("level", "-"), col.get("count"), col.get("allowed")))
        totals = data.get("totals") or {}
        w("   الإجمالي: الوصفات=%s مسموحة=%s جاهزة=%s مقفولة بلفل=%s\n" % (
            totals.get("recipes"), totals.get("allowed"), totals.get("ready"),
            totals.get("locked_level")))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
