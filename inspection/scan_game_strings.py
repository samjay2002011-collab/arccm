# -*- coding: utf-8 -*-
"""بحث داخل ملفات اللعبة (ucas/pak) عن مسارات البوابة وأي كلمة ابجريد.

الملفات بتabytes خام (Unreal), فلو بيقرأ البايتات على طول. الهدف: نعرف
البوابة الرسمية بتقبل مسار ابجريد ولا لأ — من غير أي طلب شبكة.
"""
import re
import sys
from pathlib import Path

PAKS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Arc Raiders\PioneerGame\Content\Paks")

WORDS = ["v1/pioneer", "inventory/v1", "x-embark", "manifest-id", "weapon/upgrade",
         "upgrade", "workbench", "forge", "craft", "mutate", "api-gateway", "es-pio"]

PATTERNS = {}
for w in WORDS:
    PATTERNS[(w, "ascii")] = w.encode()
    PATTERNS[(w, "utf16")] = w.encode("utf-16le")

PRINTABLE = re.compile(rb"[\x20-\x7e]{5,}")


def context(data, idx, width=200):
    lo = max(0, idx - width)
    hi = min(len(data), idx + width)
    chunk = data[lo:hi]
    out = []
    for m in PRINTABLE.finditer(chunk):
        out.append((lo + m.start(), m.group(0).decode("ascii", "ignore")))
    return out


def main():
    files = sorted(PAKS.glob("*.ucas")) + sorted(PAKS.glob("*.pak"))
    found = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        hits = {}
        with open(path, "rb") as fh:
            offset = 0
            overlap = 64
            tail = b""
            while True:
                chunk = fh.read(64 * 1024 * 1024)
                if not chunk:
                    break
                buf = tail + chunk
                for key, pat in PATTERNS.items():
                    idx = 0
                    while True:
                        i = buf.find(pat, idx)
                        if i < 0:
                            break
                        absolute = offset - len(tail) + i
                        hits.setdefault(key, []).append(absolute)
                        idx = i + 1
                tail = buf[-overlap:]
                offset += len(chunk)
        if hits:
            print("[hit] %s" % path.name, flush=True)
            for (word, enc), positions in sorted(hits.items()):
                print("   %-14s %-6s x%d" % (word, enc, len(positions)), flush=True)
                for pos in positions[:4]:
                    found.append((path.name, word, enc, pos))
        else:
            print("[.. ] %s (%.0f MB) clean" % (path.name, size / 1048576), flush=True)

    print("\n=== dump contexts ===")
    for name, word, enc, pos in found[:60]:
        path = PAKS / name
        with open(path, "rb") as fh:
            fh.seek(max(0, pos - 400))
            blob = fh.read(800)
        printable = re.sub(rb"[^\x20-\x7e]{1,}", b" ", blob).decode("ascii", "ignore")
        print("\n-- %s @%d (%s/%s): %s" % (name, pos, word, enc, printable[:400]))


if __name__ == "__main__":
    sys.exit(main())
