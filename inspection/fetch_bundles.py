"""Download rampart.su's own JS/CSS bundles into rr/assets (GET only, read-only).

Vite lazy-loads chunks, so this walks the import graph a couple of hops deep.
No mutating request is ever made; only static asset GETs from rampart.su.
"""
import os
import re
import sys
import urllib.request

SITE = "https://rampart.su"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "js")
SEEDS = [
    "/assets/index-0b2rYDqP.js",
    "/assets/utils-CDJn-J59.js",
    "/assets/card-TiZJYwcp.js",
    "/assets/x-BonIiAQC.js",
    "/assets/createBaseUIEventDetails-Bujkqo4G.js",
    "/assets/useOpenInteractionType-C4Y9vRIx.js",
]
CHUNK = re.compile(r'["\'](\.?/?(?:\.\./)?assets/[A-Za-z0-9._-]+\.(?:js|mjs))["\']')


def fetch(path):
    url = SITE + (path if path.startswith("/") else "/" + path)
    name = os.path.basename(url.split("?")[0])
    dest = os.path.join(OUT, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest, "cached"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as res:
        data = res.read()
    os.makedirs(OUT, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return dest, "%d bytes" % len(data)


def main():
    queue, seen, failed = list(SEEDS), set(), []
    hops = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    for _ in range(hops):
        pending = [p for p in queue if p not in seen]
        queue = []
        for p in pending:
            seen.add(p)
            try:
                dest, how = fetch(p)
                print("OK   %-52s %s" % (os.path.basename(p), how))
                text = open(dest, encoding="utf-8", errors="replace").read()
                for ref in CHUNK.findall(text):
                    clean = "/" + ref.split("/")[-1] if "assets/" in ref else ref
                    key = clean if clean.startswith("/") else "/" + clean
                    if key not in seen:
                        queue.append(key)
            except Exception as exc:
                failed.append((p, str(exc)))
                print("FAIL %-52s %s" % (os.path.basename(p), exc))
        if not queue:
            break
    print("\nfiles on disk: %d | failed: %d" % (len(os.listdir(OUT)), len(failed)))


if __name__ == "__main__":
    main()
