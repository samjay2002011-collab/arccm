# -*- coding: utf-8 -*-
"""بيلمع ذاكرة PioneerGame.exe وبيطلع كل سلاسل الـAPI (مسارات/هوستات/أسماء عمليات).

ليه: المنبع الرسمي مابعطيش غير `/v1/pioneer/inventory/v1/mutate` و`/inventory/upgrade`
و`update` هو الـdiscriminator الوحيد اللي بيغيّر خانات — مافيش نوع بيغيّر كمية.
لكن السحبة جوه اللعبة بتغيّر الكميات فعلًا، فالعميل لازم يكون عارف مسار/عملية تانية.
الـexe بتاعهم launcher بس (الكود في حزم مشفرة)، فالمصدر الوحيد هو ذاكرة اللعبة الحية.

قراءة فقط (PROCESS_VM_READ) — مافيش كتابة في اللعبة ولا في الشبكة، واللعبة مفتوحة.

    python -m inspection.mem_api_paths
    python -m inspection.mem_api_paths --grep split
"""
import ctypes
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402

RUN = re.compile(rb"[\x20-\x7e]{6,200}")
HINTS = (b"/v1/", b"/v2/", b"pioneer", b"inventory", b"mutat", b"es-pio", b"es-cf",
         b"embark.net", b"batch", b"stack", b"split", b"combine", b"merge", b"upgrade",
         b"discriminator", b"offer", b"workbench", b"craft", b"grpc", b"Service/",
         b"api.", b"https://",
         # Scrappy/DEAD DROP: أسماء العمليات اللي اللعبة بتبعتها فعليًا
         b"scrappy", b"rooster", b"generator", b"claim", b"collect", b"payout",
         b"forage", b"resource", b"reward", b"consume")
STOPWORDS = (b"steam", b"nvidia", b"d3d", b"dxgi", b"crashpad", b"sentry", b"crashreport",
             b"microsoft", b"globalsign", b"digicert", b"krisp", b"discord", b"epic",
             b"shader", b"texture", b"audio", b"anim", b"mesh", b"niagara")
CHUNK = 1 << 20
OVERLAP = 512
MAX_SECONDS = 300.0


def harvest(pids, want):
    hits = {}
    for pid in pids:
        handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                         False, pid)
        if not handle:
            print("  pid %s: OpenProcess فشل (شغّل كمسؤول؟)" % pid)
            continue
        deadline = time.time() + MAX_SECONDS
        buf = ctypes.create_string_buffer(CHUNK)
        done = ctypes.c_size_t(0)
        read_bytes = 0
        try:
            for base, size in mt._iter_readable(handle):
                pos, tail = 0, b""
                while pos < size:
                    want_len = min(CHUNK, size - pos)
                    ok = mt.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos),
                                                       buf, want_len, ctypes.byref(done))
                    got = done.value if ok else 0
                    if not got:
                        pos += want_len
                        continue
                    window = tail + buf.raw[:got]
                    for view in (window, window[0::2], window[1::2]):
                        for m in RUN.finditer(view):
                            run = m.group()
                            low = run.lower()
                            if not any(h in low for h in HINTS):
                                continue
                            if any(s in low for s in STOPWORDS):
                                continue
                            if want and want.encode() not in low:
                                continue
                            text = run.decode("ascii", "ignore")
                            hits[text] = hits.get(text, 0) + 1
                    read_bytes += got
                    tail = window[-OVERLAP:]
                    pos += want_len
                    if time.time() > deadline:
                        print("  (وقفة أمان بعد %.0f ثانية)" % MAX_SECONDS)
                        return hits, read_bytes
        finally:
            mt.KERNEL32.CloseHandle(handle)
            print("  pid %s: اتقرا %s MB" % (pid, format(read_bytes // 1024 // 1024, ",")))
    return hits, 0


def main():
    want = ""
    if "--grep" in sys.argv:
        want = sys.argv[sys.argv.index("--grep") + 1]
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — افتح PioneerGame.exe (قراءة الذاكرة بس، من غير أي كتابة).")
        return
    print("pid:", pids, "| فلتر:", want or "(الكل)")
    hits, _ = harvest(pids, want)
    paths = sorted(t for t in hits if "/v1/" in t.lower() or "/v2/" in t.lower()
                   or t.startswith("/") or "api" in t.lower())
    hosts = sorted({t for t in hits
                    if re.search(r"[a-z0-9.-]+\.(es-pio|es-cf|embark)\.net", t, re.I)})
    print("\n== هوستات ==")
    for h in hosts[:40]:
        print("   ", h[:150])
    print("\n== مسارات/أسطر فيها /v1/ أو api (%d) ==" % len(paths))
    for p in paths[:200]:
        print("  %4dx %s" % (hits[p], p[:150]))
    others = sorted(t for t in hits if t not in paths and t not in hosts)
    print("\n== سلاسل تانية فيها كلمات مفتاحية (%d) ==" % len(others))
    for o in others[:300]:
        print("  %4dx %s" % (hits[o], o[:150]))


if __name__ == "__main__":
    main()
