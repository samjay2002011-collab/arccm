# -*- coding: utf-8 -*-
"""مسح موجه لذاكرة اللعبة الحيّة: قوالب مسارات الـAPI وأسماء العمليات.

السبب: المسح العام (mem_api_paths) لقي قالب gRPC واحد — `/IAuthenticationService/RevokeToken/v1/` —
وده معناه إن البوابة بتخدم خدمات بنمط `/<IService>/<Method>/vN/`. لو فيه خدمة مخفية
(zeroing/splitting/trade) لازم تبقى ظاهرة بنفس النمط جوه الذاكرة.

قراءة فقط (PROCESS_VM_READ) من غير أي كتابة في اللعبة ولا طلبات شبكية.

    python -m inspection.mem_api_focus
"""
import ctypes
import os
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402

RUN = re.compile(rb"[\x20-\x7e]{5,240}")
# أي حاجة شكلها مسار/هوست/عملية — مشكل معقولة عشان المسح يخلص قبل المهلة.
INTEREST = re.compile(
    rb"(?:/[A-Za-z][A-Za-z0-9_.-]{2,40}){1,}/v\d"
    rb"|/v\d/[A-Za-z0-9_./-]{3,80}"
    rb"|[a-z0-9.-]+\.(?:es-pio|es-cf|embark)\.net[a-zA-Z0-9_:./-]{0,80}"
    rb"|x-embark[a-z0-9_-]{0,30}"
    rb"|(?:discriminat|mutat|wrapper|etag|stack_merge|split|combine|merge|transfer|exchange|"
    rb"purchase|trade|vendor|workbench|craft|upgrade|oauth|prelude|refreshtoken|refresh_token|"
    rb"grpc)[A-Za-z0-9_./-]{0,40}",
    re.I)
# نفايات: ويندوز/أنريل/ستيموركس/شهادات + أصول اللعبة
JUNK = re.compile(
    rb"(?:^|[/\\])(?:Game|Windows|System32|Program|ENGINE|Engine|CoreUObject|Core|Niagara|"
    rb"Shader|Audio|Anim|Mesh|UMG|Slate|Content|Saved|Binaries|x64|vc|cuda|nvngx|vulkan|d3d|dxgi)|"
    rb"\.(?:uasset|umap|dll|exe|sys|crl|ocsp|png|dds|wav)|"
    rb"(?:^|/)(?:MI_|SM_|M_|MM_|T_|NE_|SKM_|SK_|FBX_|DA_OI_|BP_|AB_|W_|PP_|NS_)",
    re.I)
STEAM = re.compile(r"C(?:Inventory|Econ|Client|Player|Cloud|PublishedFile|Video|UGC|Badge|Msg)"
                   r"|IClient|steam", re.I)
CHUNK = 1 << 20
OVERLAP = 512
MAX_SECONDS = 900.0


def sweep(pids):
    hits = {}
    deadline = time.time() + MAX_SECONDS
    for pid in pids:
        handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                         False, pid)
        if not handle:
            print("  pid %s: OpenProcess فشل (شغّل كمسؤول؟)" % pid)
            continue
        buf = ctypes.create_string_buffer(CHUNK)
        done = ctypes.c_size_t(0)
        read_bytes = 0
        timed_out = False
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
                    views = [window]
                    # نسخ UTF‑16 (الأنريل) بس في المناطق اللي فيها نوافذ صفر كثيفة
                    if window.count(b"\x00") * 3 > len(window):
                        views += [window[0::2], window[1::2]]
                    for view in views:
                        for m in INTEREST.finditer(view):
                            run = m.group()
                            if JUNK.search(run):
                                continue
                            text = run.decode("ascii", "ignore")
                            hits[text] = hits.get(text, 0) + 1
                    read_bytes += got
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
                " (وقفة أمان بعد %.0f ث)" % MAX_SECONDS if timed_out else ""))
        if timed_out:
            break
    return hits


def show(title, rows, cap=120):
    print("\n== %s (%d) ==" % (title, len(rows)))
    for t in rows[:cap]:
        print("  %4dx %s" % (hits[t], t[:170]))


GRPC = re.compile(r"/I[A-Z][A-Za-z0-9]+/[A-Za-z0-9_]+/v\d")
ROUTE = re.compile(r"^/[a-z0-9_]+(/[a-z0-9_.-]+){1,}", re.I)
HOST = re.compile(r"[a-z0-9.-]+\.(?:es-pio|es-cf|embark)\.net|https?://", re.I)

if __name__ == "__main__":
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة.")
        sys.exit(1)
    print("pid:", pids)
    hits = sweep(pids)
    print("إجمالي السلاسل:", len(hits))
    keys = sorted(hits)
    dump = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pf", "mem_focus_all.txt")
    with open(dump, "w", encoding="utf-8") as fh:
        for k in keys:
            fh.write("%4d\t%s\n" % (hits[k], k))
    print("الملف الكامل:", dump)
    show("قوالب خدمات gRPC", [k for k in keys if GRPC.search(k)])
    show("هوستات/روابط", [k for k in keys if HOST.search(k) and not GRPC.search(k)])
    show("مسارات relative", [k for k in keys
                          if ROUTE.match(k) and not GRPC.search(k) and "/Game/" not in k])
    show("أسماء عمليات/حقول (discriminator/mutate/stack/…)",
         [k for k in keys if re.search(r"discriminat|mutat|stack|split|combine|merge|transfer|"
                                       r"exchange|purchase|trade|offer|vendor|craft|workbench|"
                                       r"upgrade|oauth|token", k, re.I)
          and not HOST.search(k) and not k.startswith("/") and not STEAM.search(k)])
    show("رسائل ستيموركس (بتاعة steamclient.dll مش Embark)",
         [k for k in keys if STEAM.search(k)][:40])
