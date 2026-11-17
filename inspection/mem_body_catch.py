# -*- coding: utf-8 -*-
"""بيمسك جسم طلب الـmutate اللي اللعبة نفسها بعتته من ذاكرتها الحية.

ليه: البوابة بتدينا نفس التوكن اللي بتستخدمه اللعبة (مقيس من الذاكرة) وبتقبل منها
update/recycle/scrap/repair بس؛ التقسيم اللي اللعبة بتعمله بيرفضه توكننا بنفس الشكل
اللي بنعرفه. يبقى الفرق مش في التوكن ولا في المسار — الفرق في الجسم نفسه.
اللعبة بتبني الجسم من حقول ASCII/UTF‑16 جوه الذاكرة، فالنسخة اللي اتبعتة لسه موجودة
بعد العملية بثواني. بنلمس `"discriminator"` و`"mutations"` و`targetWrapperId` وبنطبع
السياق حوالين كل ضربة — وده بيطلع أسماء الحقول الحقيقية اللي ما جربناهاش.

قراءة فقط (PROCESS_VM_READ). مفيش كتابة في اللعبة ولا طلبات شبكية.

    python -m inspection.mem_body_catch
    python -m inspection.mem_body_catch --seconds 60      # مراقبة بعد ما تعمل التقسيم
"""
import ctypes
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402

NEEDLES = ("discriminator", "mutations", "targetWrapperId", "instanceId", "stack_merge",
           "assetId", "requestId", "x-embark-manifest-id",
           "craft", "Craft", "recipe", "Recipe", "bench", "workbench", "offerId",
           "itemsToConsume", "offers/accept", "progression", "hideout")
CONTEXT = 900          # بايت قبل وبعد كل ضربة
# العلامات اللي بتفرز طلب تصنيع محتمل من زحمة النصوص جوه الذاكرة.
CRAFT_MARKS = ("craft", "Craft", "recipe", "Recipe", "offerId", "itemsToConsume",
               "offers/accept", "workbench", "bench_id")
CHUNK = 4 << 20
OVERLAP = 2048
MAX_SECONDS = 300.0
PRINTABLE = re.compile(rb"[^\x20-\x7e]+")


def clean(b):
    return PRINTABLE.sub(lambda m: b" " if len(m.group()) == 1 else b" | ",
                         b).decode("ascii", "ignore").strip(" |")


def find_in(window, needle):
    """مواضع needle بالحالتين: ASCII وUTF‑16LE (اللي الأنريل ببتّستخدمه)."""
    out = []
    for form in (needle.encode(), needle.encode("utf-16-le")):
        start = 0
        while True:
            i = window.find(form, start)
            if i < 0:
                break
            out.append(i)
            start = i + 1
    return out


def pass_once(hits, pids):
    seen = set()
    for pid in pids:
        handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                         False, pid)
        if not handle:
            print("  pid %s: OpenProcess فشل" % pid)
            continue
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
                    read_bytes += got
                    for needle in NEEDLES:
                        for i in find_in(window, needle):
                            lo = max(0, i - 240)
                            frag = clean(window[lo:i + CONTEXT])
                            key = (needle, frag[:220])
                            if key in seen:
                                continue
                            seen.add(key)
                            hits.append((needle, frag))
                    tail = window[-OVERLAP:]
                    pos += want_len
        finally:
            mt.KERNEL32.CloseHandle(handle)
            print("  pid %s: اتقرا %s MB | ضربات جديدة: %d"
                  % (pid, format(read_bytes // 1024 // 1024, ","), len(hits)))


def main():
    seconds = MAX_SECONDS
    if "--seconds" in sys.argv:
        seconds = float(sys.argv[sys.argv.index("--seconds") + 1])
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — المسح محتاج PioneerGame.exe شغال.")
        return
    print("pid:", pids, "| مدة: %.0f ث" % seconds)
    hits, deadline = [], time.time() + seconds
    while time.time() < deadline:
        pass_once(hits, pids)
        if len(hits) >= 400:
            break
        if time.time() + 30 > deadline:
            break
        time.sleep(3)
    jsony = [h for h in hits if "{" in h[1] or "http" in h[1].lower() or "/" in h[1]]
    crafty = [h for h in jsony if any(k in h[1] for k in CRAFT_MARKS)]
    print("\n== مشتبه أنها طلب تصنيع (%d) ==" % len(crafty))
    for needle, frag in crafty[:25]:
        print("\n*** [%s]\n%s" % (needle, frag[:1600]))
    print("\n== ضربات بشكل طلب/JSON (%d من %d) ==" % (len(jsony), len(hits)))
    for needle, frag in jsony[:80]:
        print("\n--- [%s]\n%s" % (needle, frag[:1200]))
    out = r"C:\Users\Administrator\Desktop\rr\inspection\pf\mem_body_catch.txt"
    with open(out, "w", encoding="utf-8") as fh:
        for needle, frag in hits:
            fh.write("\n=== [%s] ===\n%s\n" % (needle, frag))
    print("\nالملف الكامل:", out)


if __name__ == "__main__":
    main()
