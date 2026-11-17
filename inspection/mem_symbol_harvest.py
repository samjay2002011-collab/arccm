# -*- coding: utf-8 -*-
"""بيجمع كل رموز الـAPI (أنواع العمليات + الحقول + المسارات) من ذاكرة اللعبة الحية.

ليه: اتضح إن اللعبة مش بتبعت "discriminator" زي ما بنبعته إحنا — هي بتبعت
FPioneerOnlineBatchOperationRequest وفيه oneof اسمه operation قيمته واحدة من
EPioneerOnlineOperationType (لحد دلوقتي شفنا: AcceptOffer / MoveItem /
MoveItemAmount / Recycle / Repair / Scrap / SetParents / Upgrade). دي تسمية
rambart بتاعتهم (combine/split/stack_merge) مش تسمية Embark. فالخطوة دي بتلمّ
القائمة الكاملة من جدول أسماء UE نفسه — من غير أي تخمين أسماء.

قراءة فقط (PROCESS_VM_READ). بنعمل regex على كل نطاق مقروء وبنجمّع الرموز.

    python -m inspection.mem_symbol_harvest
"""
import ctypes
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402

PATTERNS = {
    "operation_type": re.compile(rb"EPioneerOnlineOperationType::[A-Za-z0-9_]{2,40}"),
    "mutate_enum": re.compile(rb"E[A-Za-z0-9_]*Mutate[A-Za-z0-9_]*::[A-Za-z0-9_]{2,40}"),
    "pioneer_type": re.compile(rb"F[A-Za-z0-9_]*Pioneer[A-Za-z0-9_]{3,70}"),
    "pioneer_enum": re.compile(rb"E[A-Za-z0-9_]*Pioneer[A-Za-z0-9_]{3,60}::[A-Za-z0-9_]{2,40}"),
    "generator": re.compile(rb"[A-Za-z0-9_\.]{0,40}(ResourceGenerator|Scrappy)[A-Za-z0-9_\.]{0,50}"),
    "path": re.compile(rb"/v[0-9]/[A-Za-z0-9_./{}:\-]{2,70}"),
    "mutation_field": re.compile(rb"[A-Za-z0-9_]*Mutation[A-Za-z0-9_]{0,40}"),
}
CHUNK = 8 << 20
OVERLAP = 4096
MAX_SECONDS = 420.0
OUT = r"C:\Users\Administrator\Desktop\rr\inspection\pf\symbol_harvest_%s.txt"


def harvest(pids):
    buckets = {k: {} for k in PATTERNS}
    for pid in pids:
        handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                         False, pid)
        if not handle:
            print("  pid %s: OpenProcess فشل" % pid)
            continue
        buf = ctypes.create_string_buffer(CHUNK)
        done = ctypes.c_size_t(0)
        total = 0
        deadline = time.time() + MAX_SECONDS
        try:
            for base, size in mt._iter_readable(handle):
                pos, tail = 0, b""
                while pos < size:
                    want = min(CHUNK, size - pos)
                    ok = mt.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos),
                                                       buf, want, ctypes.byref(done))
                    got = done.value if ok else 0
                    if not got:
                        pos += want
                        continue
                    window = tail + buf.raw[:got]
                    total += got
                    for key, regex in PATTERNS.items():
                        for m in regex.findall(window):
                            tok = m.decode("ascii", "ignore")
                            b = buckets[key]
                            b[tok] = b.get(tok, 0) + 1
                    tail = window[-OVERLAP:]
                    pos += want
                    if time.time() > deadline:
                        print("  (وقفة أمان بعد %.0f ث)" % MAX_SECONDS)
                        return buckets, total
        finally:
            mt.KERNEL32.CloseHandle(handle)
            print("  pid %s: اتقرا %s MB" % (pid, format(total // 1024 // 1024, ",")))
    return buckets, 0


def main():
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — الحصاد محتاج PioneerGame.exe شغال.")
        return
    print("pid:", pids)
    buckets, _ = harvest(pids)
    lines = []
    for key in PATTERNS:
        items = sorted(buckets[key].items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append("\n== %s (%d فريد) ==" % (key, len(items)))
        for tok, n in items[:1500]:
            lines.append("  %4dx %s" % (n, tok))
    text = "\n".join(lines)
    print(text[:9000])
    path = OUT % time.strftime("%Y%m%d_%H%M%S")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nالملف:", path)


if __name__ == "__main__":
    main()
