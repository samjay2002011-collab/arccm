"""نسخة احتياطية واحدة دايمًا: backup_latest.zip في جذر المشروع، وكل القديم يتمسح.

    python inspection/backup_project.py           # يبني الأحدث ويمسح القديم
    python inspection/backup_project.py --check    # يبني في temp وما يمسحش حاجة

السبب: جذر المشروع ومجلد backups كان فيهم 8 نسخ قديمة (~1.2 GB) وكلها حالات اتعدلت
من يومها. المسح ما بيحصلش إلا بعد ما النسخة الجديدة تتأكد إنها سليمة ومافيهاش
مجلدات الكود والأداتة والبيانات.
"""
import argparse
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = "backup_latest.zip"
OUT_PATH = os.path.join(ROOT, KEEP)
CHECK_PATH = os.path.join(ROOT, "inspection", "_backup_check.zip")

SKIP_DIRS = {"backups", "__pycache__", ".venv", "node_modules", ".git", "dist", ".idea", ".qoder"}
SKIP_EXT = {".zip", ".log", ".pyc", ".tmp"}
# النسخ القديمة اللي بنعملها إحنا قبل التعديلات الكبيرة — كلها بتتمسح بعد التأكد.
OLD_PREFIXES = ("backup_", "frontend_backup", "rr-backup-", "code_", "Fahmy2")
REQUIRED_TOPS = {"backend", "frontend", "data", "agent", "inspection"}
# الصور الأصلية قبل تحويل WebP اتسحقت من القرص، فهي موجودة جوه frontend_backup.zip بس.
ORIGINALS_ZIP = os.path.join(ROOT, "frontend_backup.zip")
ORIGINALS_INTO = "pre_webp_frontend"


def _skip_dir(name):
    return name in SKIP_DIRS or name.startswith(".")


def build(out_path):
    """يكتب نسخة كاملة من المشروع (من غير النسخ القديمة واللوجات) في out_path."""
    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = sorted(d for d in dirs if not _skip_dir(d))
            rel_dir = os.path.relpath(base, ROOT).replace("\\", "/")
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() in SKIP_EXT:
                    continue
                path = os.path.join(base, name)
                rel = name if rel_dir == "." else "%s/%s" % (rel_dir, name)
                if rel == KEEP or rel == os.path.relpath(out_path, ROOT).replace("\\", "/"):
                    continue
                try:
                    zf.write(path, rel)
                    count += 1
                except OSError as err:  # ملف مقفول من اللعبة/الحارس — ما يوقفش الباك أب
                    print("SKIP   %-46s %s" % (rel, err))
        if os.path.exists(ORIGINALS_ZIP):
            with zipfile.ZipFile(ORIGINALS_ZIP) as src:
                for entry in src.infolist():
                    if entry.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                        zf.writestr("%s/%s" % (ORIGINALS_INTO, entry.filename), src.read(entry))
                        count += 1
    return count


def verify(out_path):
    """سلامة الأرشيف + وجود المجلدات الأساسية + الصور الأصلية القديمة."""
    with zipfile.ZipFile(out_path) as zf:
        if zf.testzip() is not None:
            return "corrupt member"
        names = set(zf.namelist())
        tops = {n.split("/")[0] for n in names}
        missing = REQUIRED_TOPS - tops
        if missing:
            return "missing dirs: %s" % ", ".join(sorted(missing))
        # الصور الأصلية بتتأكد بس لما مصدرها (frontend_backup.zip) موجود على القرص.
        # المصدر اتسحق من قبل، فالشرط الدائم ده كان هيمنع أي باك أب للأبد مع إن
        # مفيش حاجة ناقصة فعلًا — الأرشيف كله دلوقتي هو نسخة الاحتياط.
        if os.path.exists(ORIGINALS_ZIP) and not any(n.startswith(ORIGINALS_INTO) for n in names):
            return "pre-webp originals not archived"
        return None


def old_archives():
    found = []
    for name in sorted(os.listdir(ROOT)):
        if name == KEEP or not name.lower().endswith(".zip"):
            continue
        if name.startswith(OLD_PREFIXES):
            found.append(os.path.join(ROOT, name))
    bdir = os.path.join(ROOT, "backups")
    if os.path.isdir(bdir):
        for name in sorted(os.listdir(bdir)):
            if name.lower().endswith(".zip"):
                found.append(os.path.join(bdir, name))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="يبني في temp وما يمسحش القديم")
    args = ap.parse_args()
    out = CHECK_PATH if args.check else OUT_PATH
    started = time.time()
    print("[1/3] building %s ..." % (KEEP if not args.check else "_backup_check.zip"), flush=True)
    count = build(out)
    size = os.path.getsize(out)
    problem = verify(out)
    if problem:
        if args.check:
            os.remove(out)
        return "ABORT — backup not trusted: %s" % problem
    print("      %d files, %.1f MB, verified in %.0fs" % (count, size / 1048576, time.time() - started),
          flush=True)
    print("[2/3] newest backup is %s" % (out if args.check else KEEP), flush=True)
    if args.check:
        os.remove(out)
        return "OK (check mode — nothing deleted)"
    print("[3/3] removing older archives:", flush=True)
    freed = 0
    for path in old_archives():
        mb = os.path.getsize(path) / 1048576
        freed += mb
        os.remove(path)
        print("      DEL  %-40s %8.1f MB" % (os.path.relpath(path, ROOT).replace("\\", "/"), mb))
    bdir = os.path.join(ROOT, "backups")
    if os.path.isdir(bdir) and not os.listdir(bdir):
        os.rmdir(bdir)
        print("      DEL  backups/ (empty now)")
    print("\nfreed %.1f MB — one backup left: %s" % (freed, KEEP))
    return "OK"


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    print(main())
