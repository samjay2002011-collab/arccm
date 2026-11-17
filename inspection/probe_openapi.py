# -*- coding: utf-8 -*-
"""بيجرب يطلّع وصف الـOpenAPI للـpioneer API من البوابة نفسها — أي مسار حقيقي بنمسكه
هنا يبقى دليل مش تخمين.

قبل كده `/v1/pioneer/openapi.json` رجع 401 "IAP credentials" بالتوكن بتاعنا.
المحاولات دي بتنوّق الاعتماد: بدون توكن خالص (الكثير من البوابات بتسيب مواصفات عامة
عامة للجمهور)، بالتوكن، وبالمستندات المفتوحة الشائعة (swagger/redoc/api-docs)، وبنطبع
كل رد حرفيًا (الحالة + أول نص) عشان نعرف المطلوب بالظبط.

    python -m inspection.probe_openapi G22
"""
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

import requests  # noqa: E402
from backend import pioneer_client as pc  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"

PATHS = [
    "/v1/pioneer/openapi.json", "/v1/pioneer/openapi.yaml", "/v1/pioneer/swagger.json",
    "/v1/pioneer/api-docs", "/v1/pioneer/docs", "/v1/pioneer/redoc",
    "/openapi.json", "/swagger.json", "/v1/openapi.json", "/v1/pioneer/service.json",
    "/v1/pioneer/discovery", "/v1/pioneer/operations", "/v1/shared/openapi.json",
    "/v1/pioneer/inventory/openapi.json",
]


def show(label, resp):
    text = (resp.text or "").strip()
    print("  %-34s %-24s %s -> %s" % (label, resp.url.split(".net", 1)[-1],
                                      resp.status_code, text[:160].replace("\n", " ")))
    if resp.status_code == 200 and len(text) > 200:
        out = r"C:\Users\Administrator\Desktop\rr\inspection\pf\openapi_hit.json"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("     *** حفظناه في", out)


def main():
    token = pc.account_token(ACCOUNT) or ""
    sess = requests.Session()
    for path in PATHS:
        url = pc.BASE + path
        try:
            show("بدون اعتماد", sess.get(url, timeout=12,
                                        headers={"User-Agent": pc.UA}))
            if token:
                show("بالتوكن", sess.get(url, timeout=12, headers=pc.headers(
                    token, pc.load_manifest())))
        except Exception as err:  # noqa: BLE001
            print("  %-34s %s -> ERR %s" % ("", path, str(err)[:80]))


if __name__ == "__main__":
    main()
