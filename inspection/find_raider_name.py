"""فحص هل اسم الرايدر الحقيقي (زي "G14 #0847") موجود في ذاكرة اللعبة بشكل ينفع للقراءة الآلية.

قراءة فقط (PROCESS_VM_READ) — نفس أسلوب agent/memtoken.py، من غير أي كتابة أو تعديل.

    python inspection/find_raider_name.py            # وضع الاكتشاف: أي اسم بشكل "كود#رقم" في الذاكرة
    python inspection/find_raider_name.py G14 0847   # بحث عن اسم معروف بالظبط
    python inspection/find_raider_name.py --dump     # قراءة نسخة الكراش المجمّدة بدل الذاكرة الحية

وضع الاكتشاف هو اللي بيجاوب السؤال الحقيقي: الاسم موجود ولا لأ، وبيظهر قرب نسخة التوكن
بتاع الحساب نفسه ولا مختلط مع حسابات تانية. من غير المسافة دي التسمية الآلية بتبقى تخمين.
"""
import json
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
import ctypes  # noqa: E402
import memtoken  # noqa: E402

DUMP = (r"C:\Users\Administrator\AppData\Local\PioneerGame\Saved\Crashes"
        r"\UECC-Windows-CDC9078C4A8A340735D912BF680C90B7_0000\UEMinidump.dmp")
WIDE = re.compile(rb"(?:[\x20-\x7e]\x00){2,24}")


def wide_runs(blob):
    """كل السلاسل المقروءة بصيغة UTF-16 حول البتات المعطاة — كده بنشوف الاسم في سياقه الحقيقي."""
    out = []
    for m in WIDE.finditer(blob):
        text = m.group().decode("utf-16-le", "ignore")
        if len(text.strip()) >= 2:
            out.append(text)
    return out


# شكل اسم الرايدر زي ما بيقوله اللاعبون: "G14 #0847" / "ELCONEJOMALO#7383".
# بنلمس السلسلة المقروءة كاملة الأول وبنقطف منها الاسم — عشان الاسم في الغلاف
# بيبقى ملزق في نص أطول والقطعة الناقصة تدي اسم غلط (وده أسوأ من مفيش اسم).
SHAPE = re.compile(rb"(?:[\x20-\x7e]\x00){2,64}")
RAIDER = re.compile(r"[A-Za-z0-9 ._-]{1,20}[ ]?#[0-9]{3,6}")
# نفس القطف بس على نسخة ANSI: نسخ JSON/protobuf اللي بتخزنها اللعبة بايت واحد لكل حرف.
# المسح الأول كان بيقرا UTF-16 بس، فالنسخة دي لو كانت موجودة كانت هتتفوّت.
ASCII_RUN = re.compile(rb"[\x20-\x7e]{4,128}")

# مفاتيح الحقول اللي ممكن الاسم يتخزن تحتها — بحث بقيمة مجهولة: بنلاقي المفتاح
# وبنطبع بعده النص، فلو الاسم في الذاكرة هيبان قدامنا في نفس السطر.
NAME_KEYS = re.compile(
    b"raidername|raider_name|displayname|display_name|playername|player_name|"
    b"nickname|nick_name|callsign|gamertag|screenname|charactername|"
    b"in_gamename|accountname|pilotname", re.IGNORECASE)


def _ascii_ctx(blob, start, width=170):
    """النص الطباعي اللي بعد موضع المفتاح — بنشوف القيمه مع المفتاح مش المفتاح لوحده."""
    return re.sub(rb"[^\x20-\x7e]", b" ", blob[start:start + width]).decode("ascii", "ignore").strip()


def harvest(window, origin, names, tokens, seen, keys=None, kseen=None):
    """بيقطف أسماء الرايدر ونسخ التوكن من نافذة بايتات واحدة، مع عنوان كل لقطة.

    العنوان هو اللي بيسمح نفهم الاسم بتاع أنهي حساب: بنقيس المسافة بين كل اسم وأقرب
    نسخة توكن كاملة في نفس المنطقة.
    """
    def emit(text, addr, enc, ctx):
        if addr in seen:
            return
        seen.add(addr)
        names.append({"text": text, "addr": addr, "enc": enc, "ctx": ctx})

    for m in SHAPE.finditer(window):
        run = m.group().decode("utf-16-le", "ignore")
        for inner in RAIDER.finditer(run):
            emit(inner.group().strip(), origin + m.start() + 2 * inner.start(), "utf-16",
                 " | ".join(wide_runs(window[max(0, m.start() - 64):m.end() + 64]))[:150])
    for m in ASCII_RUN.finditer(window):
        run = m.group().decode("ascii", "ignore")
        for inner in RAIDER.finditer(run):
            emit(inner.group().strip(), origin + m.start() + inner.start(), "ansi",
                 run[max(0, inner.start() - 40):inner.end() + 60])
    for vi, view in enumerate((window, window[0::2], window[1::2])):
        if keys is not None:
            step, fix = (1, 0) if vi == 0 else (2, vi - 1)
            for km in keys.finditer(view):
                addr = origin + step * km.start() + fix
                if addr in kseen:
                    continue
                kseen.add(addr)
                keys.append({"key": km.group().decode("ascii", "ignore"), "addr": addr,
                             "enc": "ansi" if vi == 0 else "utf-16",
                             "ctx": _ascii_ctx(view, km.start())})
        for m in memtoken.JWT.finditer(view):
            info = memtoken.inspect(m.group().decode("ascii", "ignore"))
            if not info:
                continue
            off = m.start() if vi == 0 else (2 * m.start() + (vi - 1))
            tokens.append({"embark_id": info["embark_id"], "tpuid": info["tpuid"],
                           "addr": origin + off})


def _link(names, tokens):
    for rec in names:
        rec["nearest_token"] = min(
            ({"gap": abs(rec["addr"] - t["addr"]), "embark_id": t["embark_id"]} for t in tokens),
            key=lambda x: x["gap"], default=None)


def sweep(pid, out_path=None, with_keys=False):
    """بيمسح ذاكرة اللعبة الحية وبيجمع كل اسم بشكل "كود#رقم" + عناوين التوكنات."""
    handle = memtoken.KERNEL32.OpenProcess(
        memtoken.PROCESS_VM_READ | memtoken.PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        print("OpenProcess فشل (err=%s) — محتاج تشغيل كـ Administrator." % ctypes.get_last_error())
        return None
    buf = ctypes.create_string_buffer(memtoken.CHUNK)
    done = ctypes.c_size_t(0)
    names, tokens, seen = [], [], set()
    keys, kseen = [], set()
    deadline = time.time() + memtoken.MAX_SECONDS * 3
    try:
        for base, size in memtoken._iter_readable(handle):
            pos, tail = 0, b""
            while pos < size:
                want = min(memtoken.CHUNK, size - pos)
                ok = memtoken.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos),
                                                         buf, want, ctypes.byref(done))
                got = done.value if ok else 0
                if not got:
                    pos += want
                    continue
                window = tail + buf.raw[:got]
                harvest(window, base + pos - len(tail), names, tokens, seen,
                        keys if with_keys else None, kseen)
                tail = window[-memtoken.OVERLAP:]
                pos += got
            if time.time() > deadline:
                print("خلصت الوقت — بكتب اللي لقيته لحد دلوقتي.")
                break
    finally:
        memtoken.KERNEL32.CloseHandle(handle)
    _link(names, tokens)
    payload = {"pid": pid, "names": names, "tokens": tokens, "keys": keys}
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
    return payload


def sweep_file(path):
    """نفس الاكتشاف على نسخة ذاكرة مجمّدة (ملف الكراش) — يشتغل واللعبة مقفولة."""
    blob = open(path, "rb").read()
    names, tokens, seen = [], [], set()
    step = memtoken.CHUNK
    for start in range(0, len(blob), step):
        window = blob[max(0, start - memtoken.OVERLAP):start + step]
        harvest(window, max(0, start - memtoken.OVERLAP), names, tokens, seen)
    _link(names, tokens)
    return {"file": os.path.basename(path), "names": names, "tokens": tokens}


def print_sweep(payload):
    print("توكنات Pioneer كاملة في الذاكرة: %d" % len(payload["tokens"]))
    for t in payload["tokens"][:12]:
        print("   embark=%s steam=%s @%012x" % (t["embark_id"], t["tpuid"], t["addr"]))
    groups = {}
    for rec in payload["names"]:
        g = groups.setdefault(rec["text"], {"n": 0, "recs": []})
        g["n"] += 1
        g["recs"].append(rec)
    print("مرشّحات باسم رايدر: %d موضع / %d اسم مختلف" % (len(payload["names"]), len(groups)))
    for text, g in sorted(groups.items(), key=lambda kv: -kv[1]["n"])[:40]:
        gaps = [r["nearest_token"]["gap"] for r in g["recs"] if r["nearest_token"]]
        owner = Counter(r["nearest_token"]["embark_id"] for r in g["recs"] if r["nearest_token"]).most_common(1)
        print("   %-24s ×%-4d أقرب توكن على بُعد %s  (الحساب: %s)"
              % (text, g["n"], "{:,.0f}".format(min(gaps)) if gaps else "-",
                 owner[0][0] if owner else "-"))
        print("        %s" % (g["recs"][0]["ctx"] or "-"))


def scan_live(pid, name, tag):
    """بيجمع سلاسل UTF-16 اللي بتحتوي الاسم أو الرقم — من ذاكرة اللعبة الحية."""
    needle = name.encode("utf-16-le")
    tagneed = ("#" + tag).encode("utf-16-le")
    handle = memtoken.KERNEL32.OpenProcess(
        memtoken.PROCESS_VM_READ | memtoken.PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        print("OpenProcess فشل (err=%s) — محتاج تشغيل كـ Administrator." % ctypes.get_last_error())
        return
    buf = ctypes.create_string_buffer(memtoken.CHUNK)
    done = ctypes.c_size_t(0)
    hits = []
    try:
        for base, size in memtoken._iter_readable(handle):
            pos, tail = 0, b""
            while pos < size:
                want = min(memtoken.CHUNK, size - pos)
                ok = memtoken.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos),
                                                         buf, want, ctypes.byref(done))
                got = done.value if ok else 0
                if not got:
                    pos += want
                    continue
                window = tail + buf.raw[:got]
                for pat, label in ((needle, "name"), (tagneed, "tag")):
                    for m in list(re.finditer(re.escape(pat), window))[:8]:
                        lo, hi = max(0, m.start() - 48), min(len(window), m.end() + 64)
                        # المحاذاة على زوج بتات: الاسم في الذاكرة بيجي UTF-16 صحيح البداية
                        start = lo if lo % 2 == 0 else lo + 1
                        hits.append((label, base + pos - len(tail) + m.start(),
                                     " | ".join(wide_runs(window[start:hi]))[:170]))
                tail = window[-memtoken.OVERLAP:]
                pos += got
    finally:
        memtoken.KERNEL32.CloseHandle(handle)
    print("لقيت %d موضع في الذاكرة الحية" % len(hits))
    for label, addr, ctx in hits[:40]:
        print("  [%s] @%012x  %s" % (label, addr, ctx))


def main():
    name = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else ""
    tag = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else ""
    pids = memtoken.find_pids()
    if "--dump" in sys.argv and os.path.exists(DUMP):
        print("=== نسخة ذاكرة مجمّدة: %s ===" % os.path.basename(DUMP))
        print_sweep(sweep_file(DUMP))
        if not pids:
            return 0
    if not pids:
        print("اللعبة مقفولة — افتح ARC Raiders وسيبها لحد المنيو، ثم أعد التشغيل.")
        return 2
    if name:
        print("=== ذاكرة حيّة pid %s — بحث عن %s #%s ===" % (pids[0], name, tag))
        scan_live(pids[0], name, tag)
        return 0
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "inspection", "name_sweep.json")
    print("=== ذاكرة حيّة pid %s — اكتشاف أي اسم بشكل كود#رقم ===" % pids[0])
    print_sweep(sweep(pids[0], out_path=out))
    print("التفصيل الكامل: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

