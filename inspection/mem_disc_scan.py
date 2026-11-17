# -*- coding: utf-8 -*-
"""مسح موجه وسريع: بيعدّ قيم `discriminator` وأي كلمات دمج في ذاكرة اللعبة — قراءة فقط.

ليه: mem_combine_catch بيطلع سياق 1.5 كيلو بايت لكل ضربة لكل كلمة من 9 كلمات — ده بيخلي
الجولة تقيلة جدًا جوه اللعبة. هنا تمرير ريچكس واحد بنمط مركّب، والسياق بيطلع بس للضربة
النادرة. وضع ``--stats`` بيطلع حجم المناطق الخاصة من غير ما يقرأ أي بايت.

    python -m inspection.mem_disc_scan --stats
    python -m inspection.mem_disc_scan --minutes 3
"""
import ctypes
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402
from inspection.mem_combine_catch import regions  # noqa: E402

CHUNK = 8 << 20
CONTEXT = 420
# نمط واحد: قيمة الـ discriminator + أي أثر لشكل الدمج.
PAT = re.compile(rb'"discriminator"\s*:\s*"([A-Za-z_]{0,40})"'
                 rb"|targetInstanceId|stack_merge|sourceInstanceId|[Cc]ombine")
PRINTABLE = re.compile(rb"[\x00-\x08\x0e-\x1f\x7f-\xff]+")


def clean(b):
    return PRINTABLE.sub(b" ", b).decode("ascii", "ignore").strip(" ")


def stats(handle):
    total, count, biggest = 0, 0, (0, 0)
    for base, size in regions(handle):
        total += size
        count += 1
        if size > biggest[1]:
            biggest = (base, size)
    print("مناطق خاصة قابلة للكتابة: %d | حجم إجمالي: %s MB | أكبر منطقة: %s MB @0x%x"
          % (count, format(total // 1024 // 1024, ","),
             format(biggest[1] // 1024 // 1024, ","), biggest[0]))


def scan(handle, minutes):
    buf = ctypes.create_string_buffer(CHUNK)
    done = ctypes.c_size_t(0)
    values, samples, read_bytes = {}, [], 0
    deadline = time.time() + minutes * 60
    for base, size in regions(handle):
        if time.time() > deadline:
            print("انتهت المدة — بقطع.")
            break
        pos, tail = 0, b""
        while pos < size:
            want = min(CHUNK, size - pos)
            ok = mt.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos), buf,
                                               want, ctypes.byref(done))
            got = done.value if ok else 0
            if not got:
                pos += want
                continue
            window = tail + buf.raw[:got]
            read_bytes += got
            views = [window]
            if window.count(b"\x00") * 4 > len(window):
                views.append(window[0::2])
                views.append(window[1::2])
            for view in views:
                for match in PAT.finditer(view):
                    token = match.group(1)
                    key = token.decode("ascii", "ignore") if token is not None else \
                        match.group().decode("ascii", "ignore")
                    values[key] = values.get(key, 0) + 1
                    if len(samples) < 400:
                        lo = max(0, match.start() - 120)
                        samples.append((key, base + pos + match.start(),
                                        clean(view[lo:match.end() + CONTEXT])))
            tail = window[-4096:]
            pos += want
    print("قرأت: %s MB | ضربة: %d" % (format(read_bytes // 1024 // 1024, ","),
                                      sum(values.values())))
    print("\n== القيم ==")
    for key, count in sorted(values.items(), key=lambda kv: -kv[1]):
        print("   %-24s ×%d" % (key, count))
    print("\n== السياقات ==")
    for key, addr, frag in samples:
        print("\n--- [%s] @0x%x\n%s" % (key, addr, frag))
    out = r"C:\Users\Administrator\Desktop\rr\inspection\pf\mem_disc_scan.txt"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("== values ==\n")
        for key, count in sorted(values.items(), key=lambda kv: -kv[1]):
            fh.write("%s x%d\n" % (key, count))
        for key, addr, frag in samples:
            fh.write("\n=== [%s] @0x%x ===\n%s\n" % (key, addr, frag))
    print("\nالملف:", out)


def main():
    args = sys.argv[1:]
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة.")
        return
    minutes = 6.0
    if "--minutes" in args:
        minutes = float(args[args.index("--minutes") + 1])
    handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                     False, pids[0])
    if not handle:
        print("OpenProcess فشل.")
        return
    try:
        print("pid:", pids, flush=True)
        if "--stats" in args:
            stats(handle)
            return
        t0 = time.time()
        scan(handle, minutes)
        print("\nالزمن: %.0f ث" % (time.time() - t0))
    finally:
        mt.KERNEL32.CloseHandle(handle)


if __name__ == "__main__":
    main()
