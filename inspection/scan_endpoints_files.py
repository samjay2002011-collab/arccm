"""استخراج عناوين ومسارات الـ API من ملفات اللعبة نفسها (بدون تشغيل اللعبة).

بنمشي على كل DLL/EXE/INI/JSON في مجرى التنصيب ونطلّع النصوص المطبوعة
بترميزتين (ASCII وUTF‑16) لأن Unreal بيستخدم الاتنين، ونفلتر اللي فيه
إشارة لخدمة شبكية: embark / pio / pioneer / inventory / mutate / split.
القراءة بس — مافيش أي كتابة ولا طلبات شبكة.
"""
import os
import re
import sys

ROOT = r"C:\Program Files (x86)\Steam\steamapps\common\Arc Raiders"
HINTS = (b"embark", b"pio", b"pioneer", b"inventory", b"mutate", b"split",
         b"gateway", b"stack", b"http", b"/v1/", b"service", b"endpoint")
STOP = (b"libpng", b"zlib", b"openssl", b"microsoft", b"windows", b"unity")

RUN = re.compile(rb"[\x20-\x7e]{6,}")
HOST = re.compile(r"\bhttps?://[a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{6,120}", re.I)
PATH = re.compile(r"/v[0-9]+/[a-z0-9_./-]{3,60}", re.I)


def views(data):
    yield data
    yield data[1::2]
    yield data[0::2]


def runs(data):
    out = []
    for view in views(data):
        for m in RUN.finditer(view):
            s = m.group()
            if any(h in s.lower() for h in HINTS) and not any(t in s.lower() for t in STOP):
                out.append(s.decode("ascii", "ignore"))
    return out


def main():
    hosts, paths, misc = {}, {}, {}
    for dirpath, _, files in os.walk(ROOT):
        for fn in files:
            low = fn.lower()
            if not low.endswith((".dll", ".exe", ".ini", ".json", ".txt", ".uplugin", ".bin", ".cfg")):
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 400 * 1024 * 1024:
                    print("skip big", p)
                    continue
                with open(p, "rb") as f:
                    data = f.read()
            except OSError as e:
                print("unreadable", p, e)
                continue
            found = runs(data)
            if not found:
                continue
            print("#### %s  (%d runs)" % (p.replace(ROOT, "."), len(found)))
            for s in found:
                for h in HOST.findall(s):
                    hosts[h.lower()] = hosts.get(h.lower(), 0) + 1
                for pa in PATH.findall(s):
                    paths[pa.lower()] = paths.get(pa.lower(), 0) + 1
                if len(s) < 160:
                    misc.setdefault(s[:160], 0)
                    misc[s[:160]] += 1
    print("\n======== HOSTS ========")
    for h, n in sorted(hosts.items(), key=lambda kv: -kv[1])[:60]:
        print("%-4d %s" % (n, h))
    print("\n======== VERSIONED PATHS ========")
    for pa, n in sorted(paths.items(), key=lambda kv: -kv[1])[:80]:
        print("%-4d %s" % (n, pa))
    print("\n======== SHORT RUNS (first 120) ========")
    for s, n in sorted(misc.items(), key=lambda kv: -kv[1])[:120]:
        print("%-4d %s" % (n, s))


if __name__ == "__main__":
    sys.exit(main())
