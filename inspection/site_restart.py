"""يقول مين بيسمع على 127.0.0.1:8000 (السيرفر المحلي) — من غير أي pipe على الشاشة.

    python inspection/site_restart.py            # يعرض الـ PID بس
    python inspection/site_restart.py kill       # يقفل العملية (FahmySync بيرجعها)

الهدف إعادة تشغيل السيرفر بعد تعديل الباكند؛ الحارس بيشغله تاني لوحده.
"""
import os
import subprocess
import sys

PORT = ":8000"


def listeners():
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or "LISTENING" not in line.upper():
            continue
        if parts[1].endswith(PORT) or parts[2].endswith(PORT):
            pid = parts[-1]
            if pid.isdigit() and int(pid) not in pids:
                pids.append(int(pid))
    return pids


def main():
    pids = listeners()
    if not pids:
        print("mawsh la2i 7ada saami3 3ala 127.0.0.1:8000")
        return 1
    for pid in pids:
        try:
            import psutil
            proc = psutil.Process(pid)
            info = "%s | %s" % (proc.name(), " ".join(proc.cmdline()[:4]))
        except Exception:
            info = "(psutil meshgaal)"
        print("PID %s %s" % (pid, info))
    if len(sys.argv) > 1 and sys.argv[1] == "kill":
        for pid in pids:
            subprocess.run(["taskkill", "/PID", str(pid), "/f"], capture_output=True, text=True)
            print("taskkill %s done" % pid)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
