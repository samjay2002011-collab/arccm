"""أداة تحديث/فحص رقم مانيفست البوابة الرسمية.

  python inspection/pioneer_manifest.py --check
  python inspection/pioneer_manifest.py --refresh    # يسأل البوابة عن رقم الباتش الحي
  python inspection/pioneer_manifest.py --set 6393983602370192963
  python inspection/pioneer_manifest.py --raiders      # اختبار الاتصال بدون مانيفست

`--set` بيرفض أي رقم السيرفر مش متأكد منه (403/409) وبيحفظ بس لو المخزن رجع 200.
`--refresh` بيطلب `/v1/shared/manifest` بـ build فاضي — البوابة بترد برقم المانيفست
الحالي، فمفيش حاجة بتقرا ذاكرة اللعبة (مقيس 2026-11-05 بعد الباتش مباشرة).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc  # noqa: E402


def show_current():
    mid = pc.load_manifest()
    print("manifest:", mid or "(غير محفوظ)")
    return mid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", metavar="ID")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--raiders", action="store_true")
    args = ap.parse_args()

    if args.raiders:
        data = pc.fetch_raiders()
        print("raiders ok:", data)
        return 0

    if args.refresh:
        before = pc.load_manifest()
        try:
            fresh = pc.refetch_manifest()
        except pc.PioneerError as err:
            print("refetch failed:", err)
            return 1
        status, detail = pc.validate_manifest(fresh)
        print("gateway says %s (was %s) -> read %s: %s" % (fresh, before, status, detail))
        if fresh == before:
            print("الرقم هو المحفوظ: مفيش باتش جديد.")
        return 0 if status == "ok" else 1

    if args.set:
        status, detail = pc.validate_manifest(args.set)
        print("validate %s -> %s (%s)" % (args.set, status, detail))
        if status != "ok":
            print("مش هحفظ الرقم: السيرفر رفضه.")
            return 2
        saved = pc.save_manifest(args.set)
        print("saved:", saved)
        return 0

    mid = show_current()
    if args.check or not mid:
        status, detail = pc.validate_manifest(mid)
        print("status:", status, "|", detail)
        return 0 if status == "ok" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
