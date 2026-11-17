# -*- coding: utf-8 -*-
"""بيستخرج أسماء العمليات (FName table) بتاعة خدمة Embark أونلاين من ذاكرة اللعبة.

السبب: المسح السابق لقى في جدول أسماء الأنريل `PioneerOnlineCommitItemByInstanceId` —
وده معناه إن العميل نفسه فيه دالة "commit" للعنصر، و`upgrade` كان مسار مستقل في
البوابة (`/v1/pioneer/inventory/upgrade`) مش discriminator. فلو لقينا كل أسماء
`PioneerOnline*` و`*ItemStack*` هنعرف إيه العمليات اللي اللعبة بتبعتها سيرفر وندرّج
قايمة المسارات المرشّحة.

الأداة بتطبع كمان السياق الخام حوالين كل ضربة عشان نقرأ أي جسم طلب/ردّ لسه في الذاكرة.
قراءة فقط (PROCESS_VM_READ).

    python -m inspection.mem_fnames
    python -m inspection.mem_fnames --context 4000
"""
import ctypes
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402

NEEDLES = ("PioneerOnline", "CommitItem", "SplitStack", "MergeStack", "CombineItem",
           "StackItem", "SplitItem", "MutateInventory", "InventoryMutation", "MoveItem",
           "TransferItem", "x-embark", "targetWrapperId", "discriminator")
KEEP = re.compile(r"(?i)^(pioneer|commit|split|merge|combine|stack|mutat|inventory|item|"
                  r"transfer|wrapper|amount|quantity|etag|discriminator|consolidat|slot)")
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,60}")
CHUNK = 4 << 20
OVERLAP = 4096
CONTEXT = 2500
MAX_SECONDS = 600.0


def sweep(pids, context):
    names, raws = {}, []
    deadline = time.time() + MAX_SECONDS
    for pid in pids:
        handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                         False, pid)
        if not handle:
            print("  pid %s: OpenProcess فشل" % pid)
            continue
        buf = ctypes.create_string_buffer(CHUNK)
        done = ctypes.c_size_t(0)
        read_bytes, timed_out = 0, False
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
                    read_bytes += got
                    for needle in NEEDLES:
                        for form in (needle.encode(), needle.encode("utf-16-le")):
                            start = 0
                            while True:
                                i = window.find(form, start)
                                if i < 0:
                                    break
                                start = i + 1
                                lo = max(0, i - 200)
                                frag = window[lo:i + context]
                                text = re.sub(rb"[^\x20-\x7e]+", b" ", frag).decode("ascii", "ignore")
                                for tok in TOKEN.findall(text):
                                    if KEEP.match(tok):
                                        names[tok] = names.get(tok, 0) + 1
                                if len(raws) < 60:
                                    raws.append((needle, re.sub(r"\s{2,}", " ", text).strip()))
                    tail = window[-OVERLAP:]
                    pos += want_len
                    if time.time() > deadline:
                        timed_out = True
                        break
                if timed_out:
                    break
        finally:
            mt.KERNEL32.CloseHandle(handle)
            print("  pid %s: اتقرا %s MB%s" % (
                pid, format(read_bytes // 1024 // 1024, ","),
                " (وقفة أمان)" if timed_out else ""))
        if timed_out:
            break
    return names, raws


if __name__ == "__main__":
    context = CONTEXT
    if "--context" in sys.argv:
        context = int(sys.argv[sys.argv.index("--context") + 1])
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة.")
        sys.exit(1)
    print("pid:", pids, "| سياق: %d بايت" % context)
    names, raws = sweep(pids, context)
    print("\n== أسماء المرشّحين (%d) ==" % len(names))
    for n in sorted(names, key=lambda k: (-names[k], k)):
        print("  %5dx %s" % (names[n], n))
    out = r"C:\Users\Administrator\Desktop\rr\inspection\pf\mem_fnames.txt"
    with open(out, "w", encoding="utf-8") as fh:
        for needle, frag in raws:
            fh.write("\n=== [%s] ===\n%s\n" % (needle, frag))
    print("\nالسياقات الخام:", out)
