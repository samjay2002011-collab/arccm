"""قارئ توكن Pioneer من ذاكرة اللعبة — بديل عن نسخ التوكن يدوي.

بيدور في ذاكرة PioneerGame.exe على نمط JWT (eyJ….….…)، بيفكّ الـ payload، وبيقبّل
بس التوكنات اللي بتاعة embark-pioneer واللي لسه ما انتتهت. القراءة بس (PROCESS_VM_READ)
من غير أي كتابة في اللعبة أو في الشبكة.

  python agent/memtoken.py            # يفحص ويطبع ملخص مقنّع
  python agent/memtoken.py --paste    # يطبع التوكن الكامل (للتشخيص)
"""
import argparse
import base64
import ctypes
import json
import re
import sys
import time
from ctypes import wintypes

PROCESS_NAME = "PioneerGame.exe"
PIONEER_CLIENT = "embark-pioneer"
JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
RSA_SIG_BYTES = 256          # توقيع RS256 الكامل: 256 بايت = 342 خانة base64url
ENGINE_MARKS = ("binaries", "win64")   # نسخة المحرك جوا PioneerGame\Binaries\Win64

KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
CHUNK = 1 << 20
OVERLAP = 4096
MAX_BYTES = 3 << 30
MAX_SECONDS = 120.0


class MBI(ctypes.Structure):
    """MEMORY_BASIC_INFORMATION على x64 = 48 بايت بالظبط (الحشو الأخير 4 مش 8)."""
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("_pad1", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("_pad2", wintypes.DWORD)]


# من غير الأنواع دي الـ handle بيتقص لـ 32 بت على ويندوز 64 وبتفشل كل القراءات.
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
KERNEL32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                ctypes.POINTER(ctypes.c_wchar),
                                                ctypes.POINTER(wintypes.DWORD)]
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.VirtualQueryEx.restype = ctypes.c_size_t
KERNEL32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.POINTER(MBI), ctypes.c_size_t]
KERNEL32.ReadProcessMemory.restype = wintypes.BOOL
KERNEL32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def find_pids(name=PROCESS_NAME):
    """معرّفات processos اللعبة — بيمشي على Toolhelp من غير أي اعتماد خارجي."""
    SNAP = 0x00000002

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

    KERNEL32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    KERNEL32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    KERNEL32.Process32First.restype = wintypes.BOOL
    KERNEL32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ENTRY)]
    KERNEL32.Process32Next.restype = wintypes.BOOL
    KERNEL32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ENTRY)]
    snap = KERNEL32.CreateToolhelp32Snapshot(SNAP, 0)
    if not snap or int(snap) == ctypes.c_void_p(-1).value:
        return []
    out = []
    try:
        entry = ENTRY()
        entry.dwSize = ctypes.sizeof(ENTRY)
        ok = KERNEL32.Process32First(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.decode("mbcs", "ignore").lower() == name.lower():
                out.append(int(entry.th32ProcessID))
            ok = KERNEL32.Process32Next(snap, ctypes.byref(entry))
    finally:
        KERNEL32.CloseHandle(snap)
    return out


def process_path(pid):
    """المسار الكامل لعملية — من غير صلاحيات كاملة (LIMITEDInformation)."""
    handle = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not KERNEL32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value or ""
    except Exception:
        return ""
    finally:
        KERNEL32.CloseHandle(handle)


def split_pids(pids=None):
    """(لانشر، محرك) — نفس اسم البي exe لكن مسارين مختلفين.

    اللانشر هو PioneerGame.exe اللي في جذع اللعبة: صغير وبيكتب التوكن في رامه وهو
    لسه على شاشته قبل ما نافذة اللعبة تفتح — فمسحه رخيص وما يجمّدش اللعبوة.
    المحرك (جوا مجلد Binaries) جيجاهنز ضخم ومسحه هو اللي بيعطّل اللعبة.
    """
    pids = find_pids() if pids is None else list(pids)
    launcher, engine = [], []
    for pid in pids:
        path = process_path(pid).lower()
        (engine if any(m in path for m in ENGINE_MARKS) else launcher).append(pid)
    return launcher, engine


def _decode(part):
    pad = part + "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(pad).decode("utf-8", "ignore"))


def _b64_bytes(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def inspect(token, strict=True):
    """بيرجع بيانات التوكن لو ده توكن Pioneer صالح، غير كده None.

    strict=True بيرفض النسخ المبتورة: اللعبة بتملّي بافر التوكن على مراحل، فالنسخة
    اللي في الذاكرة ممكن يجي whole الـ payload بتاعها سليم والتوقيع مقطوع — والبوابة
    بترد 401 على أي توكن كهدة. توقيع RS256 الكامل 256 بايت (342 خانة base64url).
    """
    parts = token.split(".")
    if len(parts) < 3:
        return None
    if strict:
        try:
            if len(_b64_bytes(parts[2])) != RSA_SIG_BYTES:
                return None
        except Exception:
            return None
    try:
        head, payload = _decode(parts[0]), _decode(parts[1])
    except Exception:
        return None
    if head.get("alg") != "RS256":
        return None
    ext = payload.get("ext") or {}
    if str(ext.get("client_id") or "") != PIONEER_CLIENT:
        return None
    exp = float(payload.get("exp") or 0)
    if not exp or exp <= time.time():
        return None
    return {"token": token, "iat": float(payload.get("iat") or 0), "exp": exp,
            "jti": str(payload.get("jti") or ""), "sub": str(payload.get("sub") or ""),
            "embark_id": str(ext.get("embark_user_id") or ""), "tpuid": str(ext.get("tpuid") or ""),
            "tenancy": str(ext.get("tenancy_name") or "")}


def truncated(token):
    """True لو ده توكن Pioneer لكن توقيعها مبتور (نسخة ناقصة من بافر اللعبة)."""
    return bool(inspect(token, strict=False)) and not inspect(token)


def _iter_readable(handle):
    mbi = MBI()
    addr = 0
    while addr < (1 << 47):
        if KERNEL32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) \
                != ctypes.sizeof(mbi):
            break
        base, size = int(mbi.BaseAddress or 0), int(mbi.RegionSize)
        protect = int(mbi.Protect) & ~PAGE_GUARD
        if int(mbi.State) == MEM_COMMIT and protect in READABLE and size:
            yield base, size
        addr = base + size if size else addr + CHUNK


def scan(pid, stop_after=None, partial=None, max_bytes=None, max_seconds=None):
    """بيلمع مناطق الذاكرة المقروءة وبيرجع التوكنات الصالحة مرتبة من الأحدث.

    بيقرأ الذاكرة بثلاث صور: البايتات زي ما هي (نسخ ANSI) وصورتين بشريط الفواصل
    (نسخ UTF‑16 اللي بستخدمها الأنريل) — عشان النسخة اللي في بافر ANSI بتيجي مبتورة
    التوقيع في أغلب الأحيان. أي نسخة مبتورة بتتحسب في partial (لو اتداد) وما تخرجش.

    max_bytes / max_seconds بيقطعوا المسح — بنخلّيهم صغار قدام اللانشر عشان أي لمعة
    جوا عملية اللعبة نفسها بتجمّد اللعبوة (قاعدة ثابتة: ما نلمعش رام اللعبوة).
    """
    handle = KERNEL32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        raise OSError("OpenProcess failed (run as administrator?) err=%d" % ctypes.get_last_error())
    budget = max_bytes or MAX_BYTES
    found, seen, read_bytes, deadline = [], set(), 0, time.time() + (max_seconds or MAX_SECONDS)
    try:
        buf = ctypes.create_string_buffer(CHUNK)
        done = ctypes.c_size_t(0)
        for base, size in _iter_readable(handle):
            pos, tail = 0, b""
            while pos < size:
                want = min(CHUNK, size - pos)
                ok = KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos), buf,
                                                want, ctypes.byref(done))
                got = done.value if ok else 0
                if not got:
                    pos += want
                    continue
                window = tail + buf.raw[:got]
                for view in (window, window[0::2], window[1::2]):
                    for match in JWT.finditer(view):
                        text = match.group().decode("ascii", "ignore")
                        if len(text) < 200 or text in seen:
                            continue
                        seen.add(text)
                        info = inspect(text)
                        if info:
                            found.append(info)
                            if stop_after and len(found) >= stop_after:
                                return sorted(found, key=lambda t: -t["iat"])
                        elif partial is not None and truncated(text):
                            partial.append(text)
                tail = window[-OVERLAP:]
                pos += got
                read_bytes += got
                if read_bytes > budget or time.time() > deadline:
                    return sorted(found, key=lambda t: -t["iat"])
    finally:
        KERNEL32.CloseHandle(handle)
    return sorted(found, key=lambda t: -t["iat"])


def best():
    """أفضل توكن Pioneer في ذاكرة اللعبة المفتوحة حاليًا (أو None)."""
    for pid in find_pids():
        try:
            tokens = scan(pid)
        except OSError as exc:
            print("[memtoken] pid %s: %s" % (pid, exc), file=sys.stderr)
            continue
        if tokens:
            return tokens[0]
    return None


def mask(value, keep=6):
    return (value[:keep] + "…" + value[-keep:]) if len(value) > keep * 2 else value


def main():
    ap = argparse.ArgumentParser(description="Read the Pioneer token from game memory")
    ap.add_argument("--paste", action="store_true", help="print the full token")
    ap.add_argument("--all", action="store_true", help="print every candidate")
    args = ap.parse_args()
    pids = find_pids()
    if not pids:
        print("The game is closed — open ARC Raiders and leave it at the menu.")
        return 2
    tokens = []
    broken = []
    for pid in pids:
        tokens += scan(pid, partial=broken)
    if not tokens:
        print("There is no complete Pioneer token in memory right now (pid %s)." % ", ".join(map(str, pids)))
        if broken:
            print("Found %d truncated-signature copies — wait until the game is exactly at the menu, then retry."
                  % len(broken))
        return 1
    for t in (tokens if args.all else tokens[:1]):
        print("token   : %s" % (t["token"] if args.paste else mask(t["token"], 12)))
        print("account : sub=%s embark=%s steam=%s" % (t["sub"], t["embark_id"], t["tpuid"]))
        print("session : jti=%s  live %.1f hours left" % (mask(t["jti"], 8), (t["exp"] - time.time()) / 3600))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
