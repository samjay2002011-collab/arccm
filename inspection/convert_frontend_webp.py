"""يحوّل صور مجلد الواجهة إلى WebP مع الحفاظ على الشفافية، ويطبع اللي اتوفر.

    python inspection/convert_frontend_webp.py            # تحويل + تقرير
    python inspection/convert_frontend_webp.py --check     # قياس من غير ما يلمس حاجة

الأصل بيتمسح بس بعد ما النسخة الجديدة تتأكد إنها أصغر وبتتفتح؛ النسخة القديمة
محفوظة في frontend_backup.zip اللي اتعمل قبل التعديل.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
QUALITY = 82
EXTS = (".png", ".jpg", ".jpeg")


def convert(path, keep=False):
    from PIL import Image

    with Image.open(path) as im:
        im.load()
        has_alpha = (im.mode in ("RGBA", "LA", "PA")) or (
            im.mode == "P" and "transparency" in im.info)
        frame = im.convert("RGBA") if has_alpha else im.convert("RGB")
        if not has_alpha and frame.size[0] * frame.size[1] > 4_000_000:
            return None                       # صورة ضخمة بلا شفافية: مش هدفنا
        target = os.path.splitext(path)[0] + ".webp"
        frame.save(target, "WEBP", quality=QUALITY, method=6)
    before, after = os.path.getsize(path), os.path.getsize(target)
    if after >= before:                       # WebP طلع أكبر: مفيش لازمة منه
        os.remove(target)
        return None
    if not keep:
        os.remove(path)
    return {"src": os.path.relpath(path, ROOT), "out": os.path.relpath(target, ROOT),
            "before": before, "after": after, "alpha": has_alpha}


def main():
    check = "--check" in sys.argv
    keep = "--keep-originals" in sys.argv
    rows, skipped = [], []
    for dirpath, _dirs, files in os.walk(FRONTEND):
        for name in sorted(files):
            if not name.lower().endswith(EXTS):
                continue
            path = os.path.join(dirpath, name)
            if check:
                rows.append({"src": os.path.relpath(path, ROOT), "before": os.path.getsize(path),
                             "after": 0, "alpha": None})
                continue
            try:
                row = convert(path, keep=keep)
            except Exception as err:            # صورة واحدة وحشة ما توقفش الحملة
                skipped.append("%s: %s" % (os.path.relpath(path, ROOT), err))
                continue
            (rows if row else skipped).append(row or os.path.relpath(path, ROOT))
    mb = lambda n: n / 1048576.0
    before = sum(r["before"] for r in rows if isinstance(r, dict))
    after = sum(r["after"] for r in rows if isinstance(r, dict))
    print("%d images converted" % len(rows))
    for r in rows:
        if isinstance(r, dict) and r["after"]:
            print("  %8.1f KB -> %7.1f KB  %s" % (r["before"] / 1024.0, r["after"] / 1024.0, r["out"]))
    print("total: %.2f MB -> %.2f MB  (saved %.2f MB, %.1f%%)"
          % (mb(before), mb(after), mb(before - after), 100.0 * (before - after) / max(1, before)))
    if skipped:
        print("left as-is (%d):" % len(skipped))
        for s in skipped:
            print("  %s" % (s if isinstance(s, str) else s["src"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
