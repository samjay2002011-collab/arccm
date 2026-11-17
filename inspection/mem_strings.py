# -*- coding: utf-8 -*-
"""قارئ نصوص من ذاكرة اللعبة الحيّة — بحث عن مسارات البوابة وأسماء العمليات.

بيستخدم نفس قارئ الذاكرة بتاع الفا (ReadProcessMemory على المناطق المقروءة بس)،
فمالوش أي أثر على اللعبة: مافيش اعتراض شبكة ولا حقن ولا تعديل.

الهدف: نعرف اللعبة نفسها بتبعت أي paths وأي أسماء عمليات (discriminators)
للبوابة، عشان نعرف هل split/combine متاح من توكن العميل ولا لأ.

    python -m inspection.mem_strings
    python -m inspection.mem_strings --terms split,combine,stack_merge
"""
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken  # noqa: E402

# كلمات مفتاحية: مسارات، أسماء عمليات، حقول أجسام الطلبات.
TERMS = [
    "stack_merge", "combine", "split", "discriminator", "targetWrapperId",
    "instanceId", "mutate", "batch-mutate", "move-all", "consolidate",
    "inventory/v1", "/v1/pioneer", "api-gateway", "es-pio.net",
    "embark-pioneer", "pioneer.embark", "INVALID_ARGUMENT", "FAILED_PRECONDITION",
    "stack_size", "gameAssetId", "etag", "overflow", "stash",
]
URL = re.compile(rb"https://[A-Za-z0-9._~:/?#@!$&'*+;=%-]{8,140}")
CHUNK, OVERLAP = 1 << 20, 512
MAX_BYTES = 14 << 30
MAX_SECONDS = 420


def main():
    terms = TERMS + [t for t in ",".join(
        a.split("=", 1)[1] for a in sys.argv if a.startswith("--terms=")).split(",") if t]
    needles = [t.encode() for t in dict.fromkeys(terms) if t]
    pids = memtoken.find_pids()
    if not pids:
        print("اللعبة مقفولة — اقفلها الأول لو عايز البحث.")
        return 1
    hits, urls = {}, {}
    started = time.time()
    for pid in pids:
        handle = memtoken.KERNEL32.OpenProcess(0x10 | 0x400, False, pid)  # VM_READ|QUERY
        if not handle:
            print("فتح العملية %s فشل" % pid)
            continue
        read = 0
        try:
            buf = memtoken.ctypes.create_string_buffer(CHUNK)
            done = memtoken.ctypes.c_size_t(0)
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
                    blob = buf.raw[:got]
                    for url in URL.findall(blob):
                        urls.setdefault(url.decode("ascii", "ignore"), 0)
                        urls[url.decode("ascii", "ignore")] += 1
                    for needle in needles:
                        n = blob.count(needle)
                        if n:
                            hits.setdefault(needle.decode(), [0, 0])
                            hits[needle.decode()][0] += n
                            hits[needle.decode()][1] = base + pos
                    pos += got
                    read += got
                    if read > MAX_BYTES or time.time() - started > MAX_SECONDS:
                        break
                if read > MAX_BYTES or time.time() - started > MAX_SECONDS:
                    break
        finally:
            memtoken.KERNEL32.CloseHandle(handle)
        print("pid %s: قرينا %.1f GB" % (pid, read / 1e9))

    print("\n== المصطلحات اللي ظهرت ==")
    for term in sorted(hits, key=lambda t: -hits[t][0]):
        print("  %-22s %6d نسخة   آخر موقع 0x%x" % (term, hits[term][0], hits[term][1]))
    missing = [t for t in terms if t not in hits]
    print("  --- مفيش أثر لـ: %s" % ", ".join(missing) if missing else "")

    print("\n== روابط https في الذاكرة ==")
    for url, n in sorted(urls.items(), key=lambda kv: -kv[1])[:40]:
        print("  %5d  %s" % (n, url))
    print("\nالمدة: %.0f ثانية" % (time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
