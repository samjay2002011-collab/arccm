"""فحص ثابت (قراءة فقط) لحزمة rampart المصغّرة: يطبع نص حول كل تطابق نمط."""
import os
import re
import sys

BUNDLE = r"C:\Users\Administrator\Desktop\rr\assets\js\index-0b2rYDqP.js"
SPAN = int(os.environ.get("PROBE_SPAN", "200"))
LIMIT = int(os.environ.get("PROBE_LIMIT", "6"))


def main():
    with open(BUNDLE, encoding="utf-8", errors="replace") as f:
        text = f.read()
    for pat in sys.argv[1:]:
        rx = re.compile(re.escape(pat) if pat.startswith("lit:") else pat, re.I)
        hits = list(rx.finditer(text))[:LIMIT]
        print("\n===== %r  (%d/%d hits) =====" % (pat, len(hits), len(rx.findall(text))))
        for m in hits:
            print("  … %s …" % text[max(0, m.start() - SPAN):m.start() + SPAN].replace("\n", " "))


if __name__ == "__main__":
    main()
