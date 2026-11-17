# -*- coding: utf-8 -*-
"""المرور التاني على ذاكرة اللعبة: بحث ASCII + UTF-16LE مع سياق مقروء حول كل ضربة.

اللعبة (Unreal) بتخزن أغلب النصوص UTF-16، فالبحث بالـASCII لوحده بيفوّت المسارات.
الخرج: كل سياق فريد حوالين كل مصطلح، عشان نشوف اللعبة نفسها بتبعت أي paths
وأي أسماء عمليات — وده اللي بيقرر لو split/stack_merge مسار حقيقي عند Embark.

    python -m inspection.mem_context
"""
import re
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken  # noqa: E402

NEEDLES = [
    "stack_merge", "targetWrapperId", "targetInstanceId", "/v1/pioneer",
    "inventory/v1", "mutate", "es-pio.net", "api-gateway", "pioneer",
    "discriminator", "batch", "combine", "split",
]
CHUNK, OVERLAP = 1 << 20, 4096
MAX_BYTES = 14 << 30
PRINTABLE = re.compile(rb"[ -~]{6,}")


def windows(blob, base, seen, out, radius=160):
    """بيستخرج مقاطع طباعية حول كل ضربة (ASCII و UTF-16LE)."""
    for term in NEEDLES:
        for needle in (term.encode(), term.encode("utf-16-le")):
            utf16 = len(needle) == 2 * len(term)
            start = 0
            while True:
                i = blob.find(needle, start)
                if i < 0:
                    break
                start = i + 1
                lo, hi = max(0, i - radius), min(len(blob), i + len(needle) + radius)
                raw = blob[lo:hi]
                if utf16:
                    raw = raw[0::2] + raw[1::2]  # فك ضغط مؤقت لـ UTF-16
                for m in PRINTABLE.finditer(raw):
                    text = m.group().decode("ascii", "ignore")
                    if term not in text or text in seen:
                        continue
                    seen.add(text)
                    out.setdefault(term, []).append((base + i, text))


def main():
    pids = memtoken.find_pids()
    if not pids:
        print("اللعبة مقفولة.")
        return 1
    seen, out = set(), {}
    for pid in pids:
        handle = memtoken.KERNEL32.OpenProcess(0x10 | 0x400, False, pid)
        if not handle:
            print("فتح %s فشل" % pid)
            continue
        read = 0
        try:
            buf = memtoken.ctypes.create_string_buffer(CHUNK)
            done = memtoken.ctypes.c_size_t(0)
            tail = b""
            for base, size in memtoken._iter_readable(handle):
                pos = 0
                while pos < size:
                    want = min(CHUNK, size - pos)
                    ok = memtoken.KERNEL32.ReadProcessMemory(handle, memtoken.ctypes.c_void_p(base + pos),
                                                             buf, want, memtoken.ctypes.byref(done))
                    got = done.value if ok else 0
                    if not got:
                        pos += want
                        continue
                    blob = tail + buf.raw[:got]
                    windows(blob, base + pos - len(tail), seen, out)
                    tail = blob[-OVERLAP:]
                    pos += got
                    read += got
                    if read > MAX_BYTES:
                        break
                if read > MAX_BYTES:
                    break
            print("pid %s: %.1f GB" % (pid, read / 1e9))
        finally:
            memtoken.KERNEL32.CloseHandle(handle)

    for term in NEEDLES:
        hits = out.get(term) or []
        print("\n### %s — %d سياق فريد" % (term, len(hits)))
        for addr, text in hits[:14]:
            print("   0x%x  %s" % (addr, text[:230]))
        if len(hits) > 14:
            print("   ... و%d تانيين" % (len(hits) - 14))
    return 0


if __name__ == "__main__":
    sys.exit(main())
