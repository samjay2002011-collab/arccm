"""قراءة ذاكرة ARC Raiders لاستخراج x-embark-manifest-id الحالي (قراءة فقط).

الاستخدام:
  python inspection/mem_manifest.py
  python inspection/mem_manifest.py --process PioneerGame.exe --all --try 30

بيدور على:
  - الهيدر نفسه (ASCII و UTF-16) والرقم القريب منه
  - مفاتيح JSON زي "manifestId": 7516...
  - build id زي CL1430164-XXXXXXXX-BK####
  - توكن JWT (للعرض فقط)
بعدها بيختبر كل مرشح على /v1/pioneer/inventory لحد ما واحد يرجع 200،
ويحفظه في data/pioneer_manifest.json.
"""
import argparse
import ctypes
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import pymem
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import pioneer_client as pc  # noqa: E402

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
MEM_IMAGE = 0x100000
MEM_MAPPED = 0x40000
PAGE_GUARD = 0x100
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}


class MBI64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", ctypes.c_ulong),
        ("_pad1", ctypes.c_ulong),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
        ("_pad2", ctypes.c_ulong),
    ]


HEADER = b"x-embark-manifest-id"
HEADER_W = "x-embark-manifest-id".encode("utf-16le")
WORD_W = "manifest".encode("utf-16le")
DIGITS = re.compile(rb"(?<!\d)(\d{18,20})(?!\d)")
WIDE_DIGITS = re.compile(rb"(?:(?:\d\x00){18,20})")
BUILD_ID = re.compile(rb"CL\d{7}-[0-9A-Fa-f]{8}-BK\d{4}")
JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
WORD_RE = re.compile(rb"manifest", re.IGNORECASE)


def add(cands, value, score, note):
    if not value or not value.isdigit() or not (18 <= len(value) <= 20):
        return
    entry = cands.setdefault(value, {"score": 0, "notes": set()})
    entry["score"] += score
    if note not in entry["notes"]:
        entry["notes"].add(note)


def scan_window(cands, window, boost, note):
    for match in DIGITS.finditer(window):
        add(cands, match.group(1).decode(), boost, note)
    for match in WIDE_DIGITS.finditer(window):
        value = match.group(0).decode("utf-16le", "ignore")
        if value.isdigit():
            add(cands, value, boost, note)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--process", default="PioneerGame.exe")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--all", action="store_true", help="افحص المناطق الملفّاة كمان")
    parser.add_argument("--try", dest="try_limit", type=int, default=25)
    parser.add_argument("--max-gb", type=float, default=12.0)
    parser.add_argument("--chunk-mb", type=float, default=16.0)
    parser.add_argument("--dump", default="", help="احفظ سياقات المشاهدات هنا")
    args = parser.parse_args()

    print("[*] تنبيه سريع: قراءة الرام ممكن anti-cheat يلاحظها — استخدامك على مسؤوليتك.")
    try:
        pm = pymem.Pymem(args.pid or args.process)
    except pymem.exception.ProcessNotFound:
        print("[-] اللعبة مش شغالة. افتح ARC Raiders الأول.")
        return 2
    except Exception as err:  # noqa: BLE001
        print("[-] فشل الاتصال بالعملية: %s" % err)
        print("    جرّب تشغّل الـ terminal كـ Administrator.")
        return 2

    print("[+] متصل بـ %s (PID %d)" % (args.process, pm.process_id))
    handle = pm.process_handle
    chunk_size = int(args.chunk_mb * 1024 * 1024)
    overlap = 2048
    max_bytes = int(args.max_gb * 1024 * 1024 * 1024)
    cands = {}
    builds = set()
    jetons = set()
    dumped = []
    scanned = read_total = 0
    last_report = 0
    started = time.time()

    def virtual_query(addr):
        mbi = MBI64()
        ok = k32.VirtualQueryEx(ctypes.c_void_p(handle), ctypes.c_void_p(addr),
                                ctypes.byref(mbi), ctypes.sizeof(mbi))
        return mbi if ok else None

    def read_mem(addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(ctypes.c_void_p(handle), ctypes.c_void_p(addr),
                                   buf, ctypes.c_size_t(size), ctypes.byref(got))
        if not ok and not got.value:
            return b""
        return buf.raw[:got.value]

    addr = 0
    limit = 0x7FFFFFFFFFFF
    while addr < limit and read_total < max_bytes:
        mbi = virtual_query(addr)
        if not mbi:
            addr += 0x1000
            continue
        base, size, protect, typ = (mbi.BaseAddress, mbi.RegionSize,
                                    mbi.Protect, mbi.Type)
        if base == 0 and size == 0:
            break
        readable = (mbi.State == MEM_COMMIT and (protect & 0xFF) in READABLE
                    and not (protect & PAGE_GUARD))
        wanted = (typ == MEM_PRIVATE) or (args.all and typ in (MEM_IMAGE, MEM_MAPPED))
        if readable and wanted:
            off = 0
            while off < size and read_total < max_bytes:
                want = min(chunk_size, size - off)
                data = read_mem(base + off, want)
                if data:
                    scanned += 1
                    read_total += len(data)
                    scan_chunk(data, cands, builds, jetons, dumped)
                    if read_total - last_report >= 1024 ** 3:
                        last_report = read_total
                        print("    ... %.0f MB" % (read_total / 1048576), flush=True)
                off += max(1, want - overlap)
        addr = base + size

    elapsed = time.time() - started
    print("[+] خلص الفحص: %.1f MB في %.1f ثانية" % (read_total / 1048576, elapsed))

    if builds:
        print("[+] Build IDs: %s" % ", ".join(sorted(b.decode("ascii", "ignore") for b in builds)[:5]))
    if jetons:
        print("[+] لقيت %d توكن JWT في الرام (مش محفوظ)" % len(jetons))

    ranked = sorted(cands.items(), key=lambda kv: (-kv[1]["score"], -len(kv[0])))
    if not ranked and not builds:
        print("[-] مفيش أرقام مرشحة حوالين 'manifest'. جرّب --all أو شغّل اللعبة للمينيو.")
        return 1
    if ranked:
        print("[+] مرشحين: %d — أقواهم:" % len(ranked))
    for value, meta in ranked[:10]:
        print("    %s  score=%d  %s" % (value, meta["score"], ", ".join(sorted(meta["notes"]))))

    if args.dump:
        Path(args.dump).write_text("\n\n".join(dumped), encoding="utf-8", errors="ignore")
        print("[+] السياقات اتحفظت في %s" % args.dump)

    token = active_token()
    if not token:
        print("[-] مفيش توكن نشط في data/rampart_local.db")
        return 1

    build = sorted(builds)[0].decode() if builds else ""
    verified = None
    if build:
        print("[*] بجرب مسار الـ API بالـbuild ID: %s" % build)
        mid = fetch_manifest_via_api(build, token)
        if mid and verify_manifest(mid, token):
            verified = mid
    if not verified:
        attempts = 0
        for value, meta in ranked:
            if attempts >= args.try_limit:
                break
            attempts += 1
            if verify_manifest(value, token):
                verified = value
                break
            time.sleep(0.25)

    if not verified:
        print("[-] ولا مرشح اتحقق. لو اللعبة في المينيو جرّب تعمل refresh للإنفنتوري وبعدها أعد الفحص.")
        return 1

    pc.save_manifest(verified, build)
    print("[✓] المانيفست الصحيح: %s" % verified)
    print("[✓] اتحفظ في %s" % pc.MANIFEST_FILE)
    return 0


def scan_chunk(data, cands, builds, jetons, dumped):
    for match in BUILD_ID.finditer(data):
        builds.add(match.group(0))
    for match in JWT.finditer(data):
        jetons.add(match.group(0))

    seen = 0
    for match in WORD_RE.finditer(data):
        if seen >= 4000:
            break
        seen += 1
        pos = match.start()
        window = data[max(0, pos - 768):pos + 1536]
        low = window.lower()
        score = 3 if (b'"manifest' in low or b"manifestid" in low) else 2
        scan_window(cands, window, score, "json")
        if len(dumped) < 40:
            dumped.append(window.decode("utf-8", "ignore"))

    start = 0
    seen = 0
    while seen < 2500:
        pos = data.find(WORD_W, start)
        if pos < 0:
            break
        start = pos + 2
        seen += 1
        window = data[max(0, pos - 768):pos + 2048]
        scan_window(cands, window, 3, "wide")
        if len(dumped) < 80:
            dumped.append(window.decode("utf-16le", "ignore"))

    for needle, wide in ((HEADER, False), (HEADER_W, True)):
        start = 0
        while True:
            pos = data.find(needle, start)
            if pos < 0:
                break
            start = pos + 1
            window = data[max(0, pos - 64):pos + 4096]
            scan_window(cands, window, 8, "header")
            if len(dumped) < 120:
                dumped.append(window.decode("utf-16le" if wide else "utf-8", "ignore"))


def fetch_manifest_via_api(build, token):
    body = {
        "build_id": build,
        "playtest_id": 0,
        "artifact_id": "",
        "store_deployment_target": "Production",
        "manifest_id": 0,
        "app_id": "2118292977-WinGDK",
    }
    try:
        resp = requests.post(pc.BASE + "/v1/shared/manifest",
                             headers=pc.headers(token), json=body, timeout=20)
    except requests.RequestException as err:
        print("    refetch خطأ شبكة: %s" % str(err)[:80])
        return ""
    if resp.status_code != 200:
        print("    refetch [%s] -> %s" % (build, resp.status_code))
        return ""
    try:
        return str(resp.json().get("id") or "")
    except ValueError:
        return ""


def verify_manifest(mid, token):
    try:
        resp = requests.get(pc.BASE + "/v1/pioneer/inventory",
                            headers=pc.headers(token, mid), timeout=20)
    except requests.RequestException as err:
        print("    [%s] خطأ شبكة: %s" % (mid, str(err)[:80]))
        return False
    state = "OK" if resp.status_code == 200 else resp.text.strip()[:40]
    print("    [%s] %s -> %s" % (mid, resp.status_code, state))
    return resp.status_code == 200


def active_token():
    try:
        db = sqlite3.connect(os.path.join(pc.config.DATA_DIR, "rampart_local.db"))
        row = db.execute("SELECT token FROM accounts WHERE is_active=1").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


if __name__ == "__main__":
    sys.exit(main())
