# -*- coding: utf-8 -*-
"""بيطارد جدول المسارات الحقيقي جوه ذاكرة اللعبة — بيفتح شباك كبير حوالين أي طلب معروف
ويطلّع كل المسارات اللي في نفس النطاق.

ليه الطريقة دي: المسار مش نص ثابت في الـexe (grep على PioneerGame.exe وكل الـdlls مالقاش
ولا `/v1/pioneer`)، لكنه موجود وقت التنفيذ — جسم طلب الـmutate اتقّب قبل كده حرفيًا من
الذاكرة (mem_body_catch)، فالطلب ب كامل أجزائه (المسار + الهيدرات + الجسم) بيكون محفوظ في
نفس نطاق الـallocator. فبنلمس أي جزء معروف من طلب حقيقي وبنطبع الـ 128 KB اللي حواليه
وبنستخرج كل شكل `/v1/...` أو `pioneer/...` — أي مسار يطلع من هنا مش تخمين: ده جدول اللعبة
نفسها.

قراءة فقط (PROCESS_VM_READ). مفيش كتابة في اللعبة ولا طلبات شبكية.

    python -m inspection.mem_path_table
    python -m inspection.mem_path_table --needle '"mutations"' --window 262144
"""
import ctypes
import os
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402

NEEDLES = ['"mutations"', '"discriminator"', '"offerId"', "/v1/pioneer",
           "pioneer/inventory", "ClaimScrappyRewards", "FE_ScrappysBoxClaim"]
# النوافذ بتتحفظ للعلامات الضيقة بس (ال bodies بتزحلق المئات وبتغرق الديسك).
DUMP_NEEDLES = {"/v1/pioneer", "pioneer/inventory", "ClaimScrappyRewards",
                "FE_ScrappysBoxClaim"}
MAX_DUMPS = 40
WINDOW = 128 * 1024
CHUNK = 8 << 20
PATH_RE = re.compile(rb"/v[0-9]/[A-Za-z0-9_./{}:\-]{2,80}")
WORD_RE = re.compile(rb"[A-Za-z0-9_./{}\-]*pioneer[A-Za-z0-9_./{}\-]{2,80}", re.I)
MAX_SECONDS = 240.0
OUT = r"C:\Users\Administrator\Desktop\rr\inspection\pf"


def forms(needle):
    return [needle.encode(), needle.encode("utf-16-le")]


def scan(pid, needles, window):
    handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                     False, pid)
    if not handle:
        print("  pid %s: OpenProcess فشل" % pid)
        return []
    buf = ctypes.create_string_buffer(CHUNK)
    done = ctypes.c_size_t(0)
    tokens, dumps = {}, []
    deadline = time.time() + MAX_SECONDS
    try:
        for base, size in mt._iter_readable(handle):
            pos = 0
            while pos < size:
                want = min(CHUNK, size - pos)
                ok = mt.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos),
                                                   buf, want, ctypes.byref(done))
                got = done.value if ok else 0
                if not got:
                    pos += want
                    continue
                data = buf.raw[:got]
                for needle in needles:
                    for form in forms(needle):
                        start = 0
                        while True:
                            i = data.find(form, start)
                            if i < 0:
                                break
                            start = i + len(form)
                            lo = max(0, i - window // 2)
                            hi = min(got, i + window // 2)
                            chunk = data[lo:hi]
                            for regex in (PATH_RE, WORD_RE):
                                for m in regex.finditer(chunk):
                                    tok = m.group().decode("ascii", "ignore")
                                    tokens[tok] = tokens.get(tok, 0) + 1
                            if needle not in DUMP_NEEDLES or len(dumps) >= MAX_DUMPS:
                                continue
                            name = os.path.join(
                                OUT, "pathdump_%s_%x.txt" % (needle.strip('"')[:14],
                                                             base + pos + i))
                            with open(name, "wb") as fh:
                                fh.write(chunk)
                            dumps.append((needle, hex(base + pos + i), name))
                pos += want
                if time.time() > deadline:
                    print("  (وقفة أمان بعد %.0f ث)" % MAX_SECONDS)
                    return tokens, dumps
    finally:
        mt.KERNEL32.CloseHandle(handle)
    return tokens, dumps


def main():
    needles = list(NEEDLES)
    window = WINDOW
    if "--needle" in sys.argv:
        needles = sys.argv[sys.argv.index("--needle") + 1].split(",")
    if "--window" in sys.argv:
        window = int(sys.argv[sys.argv.index("--window") + 1])
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — لازم PioneerGame.exe يكون شغال.")
        return
    print("pid:", pids, "| مساطر:", needles, "| شباك: %d KB" % (window // 1024))
    all_tokens, all_dumps = {}, []
    for pid in pids:
        t, d = scan(pid, needles, window)
        for k, v in t.items():
            all_tokens[k] = all_tokens.get(k, 0) + v
        all_dumps.extend(d)
    paths = sorted(k for k in all_tokens if k.startswith("/v"))
    words = sorted(k for k in all_tokens if "pioneer" in k.lower() and not k.startswith("/v"))
    lines = ["== مسارات (%d) ==" % len(paths)]
    lines += ["  %4dx %s" % (all_tokens[p], p) for p in paths]
    lines += ["", "== سلاسل فيها pioneer (%d) ==" % len(words)]
    lines += ["  %4dx %s" % (all_tokens[w], w[:120]) for w in words[:800]]
    lines += ["", "== نوافذ محفوظة (%d) ==" % len(all_dumps)]
    lines += ["  [%s] @%s -> %s" % (n, a, p) for n, a, p in all_dumps[:200]]
    text = "\n".join(lines)
    print(text[:8000])
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT, "path_table_%s.txt" % stamp)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nالملف:", out)


if __name__ == "__main__":
    main()
