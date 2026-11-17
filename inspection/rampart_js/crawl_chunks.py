# -*- coding: utf-8 -*-
"""ينزّل chunks بتاعة رامبارت واحدة ورا التانية ويبحث عن زرار UPDATE.

قراءة كود عام بس (assets ثابتة) — مفيش أي توكن ولا طلب متصدّر نيابة عن حد.
"""
import io
import os
import re
import sys

import urllib.request

BASE = "https://rampart.su"
HERE = os.path.dirname(os.path.abspath(__file__))
MAX_FILES = 120
PATTERNS = (r'UPDATE', r'>Update<', r'arrow-up', r'ArrowUp', r'upload')


def fetch(path):
    name = path.replace("/", "_").replace(".", "_")
    local = os.path.join(HERE, name)
    if os.path.exists(local) and os.path.getsize(local) > 0:
        return io.open(local, encoding="utf-8", errors="replace").read()
    try:
        with urllib.request.urlopen(BASE + path, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception as exc:                      # noqa: BLE001
        print("miss %s (%s)" % (path, exc))
        return ""
    io.open(local, "w", encoding="utf-8").write(text)
    return text


def main():
    seen, queue = set(), ["/assets/index-CcWZfx3c.js"]
    texts = {}
    while queue and len(seen) < MAX_FILES:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        text = fetch(path)
        if not text:
            continue
        texts[path] = text
        for ref in re.findall(r'["\'(]\.?/?(assets/[A-Za-z0-9._@-]+\.js)', text):
            if "/" + ref not in seen:
                queue.append("/" + ref)
    print("downloaded %d chunks, %d KB total" %
          (len(texts), sum(len(t) for t in texts.values()) // 1024))
    hits = io.open(os.path.join(HERE, "update_hits.txt"), "w", encoding="utf-8")
    for path, text in texts.items():
        for pat in PATTERNS:
            for m in re.finditer(re.escape(pat), text):
                a = max(0, m.start() - 500)
                b = min(len(text), m.end() + 700)
                hits.write("\n\n### %s :: %s @%d\n%s" % (path, pat, m.start(), text[a:b]))
    hits.close()
    n = open(os.path.join(HERE, "update_hits.txt"), encoding="utf-8").read().count("### ")
    print("hits written:", n)


main()
