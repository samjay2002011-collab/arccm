"""يعرض طبقة المعرفة المخزّنة لكل حساب — قراءة بس.

    python inspection/knowledge_meta_dump.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import knowledge, store  # noqa: E402


def main():
    conn = store.db()
    for row in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'knowledge:%' ORDER BY key"):
        data = json.loads(row["value"])
        print(row["key"])
        print("   learned=%s never_found=%s stations=%s"
              % (len(data.get("learned") or []),
                 len(data.get("never_found") or []), data.get("stations")))
    for row in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'unlocked:%' ORDER BY key"):
        print(row["key"], "->", str(row["value"])[:80])
    print("accounts:")
    for row in conn.execute("SELECT name, token FROM accounts ORDER BY name"):
        print("   %-14s token=%s" % (row["name"], "***" if row["token"] else "MISSING"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
