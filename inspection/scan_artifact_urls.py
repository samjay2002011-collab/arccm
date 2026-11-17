# -*- coding: utf-8 -*-
"""استخراج روابط artifacts من ثنائيات اللعبة (PioneerGame.exe وأقراصه).

الهدف: نعرف من أين البوابة/الـ CDN بتجيب الـ artifacts (زي p2ItemRecycleArtifact)
اللي فيها جدول إعادة التدوير الرسمي. مفيش أي طلب شبكة — قراءة بايتات فقط.
"""
import re
import sys
from pathlib import Path

GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Arc Raiders\PioneerGame")

TARGETS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Arc Raiders\PioneerGame\Binaries\Win64\PioneerGame.exe",
]

PRINTABLE = re.compile(rb"[\x20-\x7e]{6,}")
URLISH = re.compile(rb"(https?://[\x21-\x7e]{4,120})")
KEY = re.compile(rb"(?i)(artifact|partitioning|contenthost|cdn|es-pio)")


def scan(path):
    hits, urls = [], set()
    size = path.stat().st_size
    with open(path, "rb") as fh:
        offset, tail = 0, b""
        while True:
            chunk = fh.read(32 * 1024 * 1024)
            if not chunk:
                break
            buf = tail + chunk
            for m in PRINTABLE.finditer(buf):
                blob = m.group(0)
                if KEY.search(blob) and len(blob) < 400:
                    hits.append((offset - len(tail) + m.start(), blob))
                for u in URLISH.findall(blob):
                    urls.add(u.decode("ascii", "ignore"))
            tail = buf[-256:]
            offset += len(chunk)
    print("== %s (%.0f MB)" % (path.name, size / 1048576))
    seen = set()
    for pos, blob in hits:
        text = blob.decode("ascii", "ignore")
        if text in seen:
            continue
        seen.add(text)
        print("   @%-12d %s" % (pos, text[:220]))
    for u in sorted(urls):
        if any(k in u.lower() for k in ("es-pio", "artifact", "manifest", "cdn", "embark")):
            print("   URL %s" % u[:200])


def main():
    paths = [Path(p) for p in TARGETS]
    extra = GAME / "Binaries" / "Win64"
    for name in ("platform_core.dll", "Cerebro.dll", "preloader.dll"):
        p = extra / name
        if p.exists():
            paths.append(p)
    for path in paths:
        if path.exists():
            scan(path)
        else:
            print("missing:", path)


if __name__ == "__main__":
    sys.exit(main())
