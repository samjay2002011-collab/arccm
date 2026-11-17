# -*- coding: utf-8 -*-
"""لاقط طلب الدمج الحقيقي من ذاكرة اللعبة — قراءة فقط.

اللي بنعرفه: بوابة Embark بترفض `combine` لتوكن الرفيق بـ reason=UNKNOWN، ورامبارت
بتبعت نفس الجسم على سيرفرها بس بتوكن أعلى. يبقى السؤال: إيه الاسم/الجسم اللي بترسله
**اللعبة نفسها** وقت الدمج؟ لو اللعبة بتسمّيه حاجة تانية (أو بتقسّمه لـ mutations
عادية) بنعرف إن المشكلة اسم مش صلاحيات.

بيبحث في المناطق الخاصة القابلة للكتابة (MEM_PRIVATE + PAGE_READWRITE) بس — يعني
بيستثني صور الـ DLL والملفات المعيّنة — عشان يقلل زمن اللمسة على عملية اللعبة.
مفيش أي كتابة في الذاكرة ومفيش أي طلب شبكي.

    python -m inspection.mem_combine_catch --baseline      # جولة قبل السحب
    python -m inspection.mem_combine_catch --seconds 90    # المراقبة بعد ما أقول لك
"""
import ctypes
import os
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402

MEM_PRIVATE = 0x20000
MEM_MAPPED = 0x40000
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08

CHUNK = 4 << 20
OVERLAP = 4096
CONTEXT = 1500
HEADROOM = 260

# الضربات اللي بتفرز جسم طلب حقيقي من زحمة النصوص.
NEEDLES = ("discriminator", "targetInstanceId", "targetWrapperId", "stack_merge",
           "combine", "Combine", "mutations", "sourceInstanceId", "amount")
# أي قيمة بتتحط قدام "discriminator" — ده الجواب اللي بندور عليه.
DISC_VALUE = re.compile(rb'"discriminator"\s*:\s*"([A-Za-z_]{2,32})"')
PRINTABLE = re.compile(rb"[\x00-\x08\x0e-\x1f\x7f-\xff]+")
# كل الضربات في نمط واحد: تمرير ريچكس واحد لكل نافذة (تمريرات كتير = جولة بتextend
# لدقايق، وده بيزوّد زمن لمس ذاكرة اللعبة).
NEEDLE_PAT = re.compile(b"|".join(re.escape(n.encode("ascii")) for n in NEEDLES))
OUT_DIR = r"C:\Users\Administrator\Desktop\rr\inspection\pf"


def clean(b):
    return PRINTABLE.sub(lambda m: b" " if len(m.group()) == 1 else b" | ",
                         b).decode("ascii", "ignore").strip(" |")


def views(window):
    """البايتات زي ما هي، وكمان صورتين لفك UTF‑16LE بس لو النافذة فيها صفر كل حرفين.

    الشرط ده بيوفر نسخة الـ 4 ميجا (حيلة memtoken) للمناطق اللي كلها ASCII — وده
    اللي بيخلي الجولةWhole دقيقة بدل دقايق.
    """
    yield window
    if window.count(b"\x00") * 4 > len(window):
        yield window[0::2]
        yield window[1::2]


def regions(handle):
    """المناطق الخاصة المقروءة/القابلة للكتابة فقط — أقل عبء على اللعبة."""
    mbi = mt.MBI()
    addr = 0
    while addr < (1 << 47):
        if mt.KERNEL32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi),
                                      ctypes.sizeof(mbi)) != ctypes.sizeof(mbi):
            break
        base, size = int(mbi.BaseAddress or 0), int(mbi.RegionSize)
        protect = int(mbi.Protect) & ~mt.PAGE_GUARD
        kind = int(mbi.Type)
        if (int(mbi.State) == mt.MEM_COMMIT and size and protect in mt.READABLE
                and kind in (MEM_PRIVATE, MEM_MAPPED) and protect in (PAGE_READWRITE,
                                                                      PAGE_WRITECOPY)):
            yield base, size
        addr = base + size if size else addr + mt.CHUNK


def harvest(handle, hits, discs, budget_mb=0):
    """جولة كاملة: بتضيف الضربات الجديدة للـ hits وبتعدّ أسماء الـ discriminator."""
    buf = ctypes.create_string_buffer(CHUNK)
    done = ctypes.c_size_t(0)
    read_bytes = 0
    limit = budget_mb * 1024 * 1024
    for base, size in regions(handle):
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
            read_bytes += got
            for view in views(window):
                for name in DISC_VALUE.findall(view):
                    key = name.decode("ascii", "ignore")
                    discs[key] = discs.get(key, 0) + 1
                for match in NEEDLE_PAT.finditer(view):
                    lo = max(0, match.start() - HEADROOM)
                    frag = clean(view[lo:match.end() + CONTEXT])
                    if len(frag) < 24 or "{" not in frag:
                        continue
                    key = (match.group().decode("ascii", "ignore"), frag[:200])
                    if key in hits:
                        continue
                    hits[key] = (key[0], time.time(), base + pos + match.start(), frag)
            tail = window[-OVERLAP:]
            pos += want
        if limit and read_bytes >= limit:
            break
    return read_bytes


def report(hits, discs, tag):
    print("\n== أسماء discriminator اللي ظهرت (%d) ==" % len(discs))
    for name, count in sorted(discs.items(), key=lambda kv: -kv[1]):
        print("   %-22s ×%d" % (name, count))
    interesting = [h for h in hits.values()
                   if any(k in h[3] for k in ("targetInstanceId", "combine", "Combine",
                                              "stack_merge", "mutations"))]
    print("\n== مشتبه أنها أجسام طلب (%d من %d) ==" % (len(interesting), len(hits)))
    for needle, _, addr, frag in sorted(interesting, key=lambda h: h[1])[-40:]:
        print("\n*** [%s] @0x%x\n%s" % (needle, addr, frag[:1800]))
    return interesting


def dump(hits, interesting, discs):
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    out = os.path.join(OUT_DIR, "mem_combine_catch_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("== discriminator values ==\n")
        for name, count in sorted(discs.items(), key=lambda kv: -kv[1]):
            fh.write("%s x%d\n" % (name, count))
        for needle, stamp, addr, frag in sorted(hits.values(), key=lambda h: h[1]):
            fh.write("\n=== [%s] t=%.1f @0x%x ===\n%s\n" % (needle, stamp, addr, frag))
    print("\nالملف الكامل:", out)
    return out


def main():
    args = sys.argv[1:]
    seconds = 90.0
    if "--seconds" in args:
        seconds = float(args[args.index("--seconds") + 1])
    baseline_only = "--baseline" in args
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — المسح محتاج PioneerGame.exe شغال.")
        return
    print("pid:", pids, "| مدة: %.0f ث | baseline_only: %s" % (seconds, baseline_only))
    hits, discs = {}, {}
    handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                     False, pids[0])
    if not handle:
        print("OpenProcess فشل — شغّل كمسؤول.")
        return
    try:
        if baseline_only:
            read = harvest(handle, hits, discs)
            print("جولة أساس: %s MB | ضربات: %d | أسماء: %s"
                  % (format(read // 1024 // 1024, ","), len(hits), sorted(discs)))
            dump(hits, [], discs)
            return
        print("== جولة الأساس (قبل ما تسحب) ==")
        before = harvest(handle, hits, discs)
        print("   %s MB | ضربات: %d | أسماء: %s"
              % (format(before // 1024 // 1024, ","), len(hits), sorted(discs)))
        marks = dict(discs)
        deadline = time.time() + seconds
        passes = 0
        while time.time() < deadline:
            time.sleep(2)
            passes += 1
            since = dict((k, v) for k, v in hits.items())
            read = harvest(handle, hits, discs)
            new = len(hits) - len(since)
            new_names = [n for n, c in discs.items() if n not in marks]
            if new_names:
                print("!! أسماء discriminator جديدة: %s" % ", ".join(new_names))
                marks.update(discs)
            print("جولة %d: %s MB | ضربات جديدة: %d | الإجمالي: %d"
                  % (passes, format(read // 1024 // 1024, ","), new, len(hits)))
            if len(hits) > 6000:
                print("كفاية — بوقف عشان الزحمة.")
                break
    finally:
        mt.KERNEL32.CloseHandle(handle)
    interesting = report(hits, discs, "final")
    dump(hits, interesting, discs)


if __name__ == "__main__":
    main()
