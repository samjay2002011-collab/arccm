"""يجيب رقم المانيفست الجديد من البوابة نفسها — بدون قراءة ذاكرة اللعبة.

1) /v1/shared/manifest بأشكال جسم مختلفة (الbuild المحفوظ / فاضي / من غيره).
2) batch-operation بقائمة عمليات فاضية — صفر أثر — عشان نسمع الرد الخالص.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from backend import config, pioneer_client as pc, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G14"
token = pc.account_token(ACCOUNT)
saved = pc._read_json(pc.MANIFEST_FILE) or {}
build = str(saved.get("build") or "")
print("account %s | saved build %s | manifest %s" % (ACCOUNT, build, saved.get("manifest_id")))

BASE_BODY = {"playtest_id": 0, "artifact_id": "", "store_deployment_target": "Production",
             "manifest_id": 0, "app_id": "2118292977-WinGDK"}
variants = {
    "stored build": dict(BASE_BODY, build_id=build),
    "empty build_id": dict(BASE_BODY, build_id=""),
    "no build_id": dict(BASE_BODY),
    "null build_id": dict(BASE_BODY, build_id=None),
    "UA build CL1430164": dict(BASE_BODY, build_id="CL1430164"),
    "empty everything": {},
}
for name, body in variants.items():
    try:
        r = requests.post(pc.BASE + "/v1/shared/manifest", headers=pc.headers(token),
                          json=body, timeout=config.HTTP_TIMEOUT)
        print("manifest[%-20s] %s %s" % (name, r.status_code, r.text[:300].replace("\n", " ")))
    except Exception as exc:  # noqa: BLE001
        print("manifest[%-20s] ERR %s" % (name, exc))

url = pc.BASE + pw.BATCH_PATH
for style in ("with manifest header", "no manifest header"):
    head = pc.headers(token, pc.load_manifest() if style.startswith("with") else "")
    try:
        r = requests.post(url, headers=head, json={"operations": []}, timeout=config.HTTP_TIMEOUT)
        print("batch[%-20s] %s %s" % (style, r.status_code, r.text[:400].replace("\n", " ")))
    except Exception as exc:  # noqa: BLE001
        print("batch[%-20s] ERR %s" % (style, exc))

for path in ("/v1/pioneer/inventory", "/v1/pioneer/raiders"):
    try:
        r = requests.get(pc.BASE + path, headers=pc.headers(token, pc.load_manifest()),
                         timeout=config.HTTP_TIMEOUT)
        print("read %-22s %s len=%d %s" % (path, r.status_code, len(r.text), r.text[:120].replace("\n", " ")))
    except Exception as exc:  # noqa: BLE001
        print("read %-22s ERR %s" % (path, exc))
