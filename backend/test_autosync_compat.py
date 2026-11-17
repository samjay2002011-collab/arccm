"""اختبار التوافق: نفس دالة القراءة في auto_sync_v2.py، مرة على rampart الحقيقي ومرة على المرآة.

مفيش أي تعديل على auto_sync_v2.py نفسه، ومفيش أي طلب كتابة على المتجر أو على rampart
(اللي بيحصل بس: GET /inventory/parsed + POST /auth/embark/{id}/activate لتبديل الحساب).
"""
import importlib.util as importlib_util
import json
import os
import sys

LOCAL = os.environ.get("RAMPART_LOCAL_URL", "http://127.0.0.1:8000")
LIVE = os.environ.get("RAMPART_LIVE_URL", "https://api.rampart.su")
AUTOSYNC = os.environ.get("AUTOSYNC_PATH", r"C:\Users\Administrator\Desktop\ll\auto_sync_v2.py")

spec = importlib_util.spec_from_file_location("autosync_probe", AUTOSYNC)
A = importlib_util.module_from_spec(spec)
spec.loader.exec_module(A)


def read(base):
    A.RAMPART_BASE_API = base
    A.RAMPART_PARSED_URL = base + "/inventory/parsed"
    return A.fetch_game_inventory()


print("=== reading through the FROZEN auto_sync reader, pointed at rampart.su ===")
live = read(LIVE)
print("=== same reader, pointed at the local mirror ===")
local = read(LOCAL)

if live is None or local is None:
    print("[FAIL] reader returned None (live=%s local=%s)" % (live is None, local is None))
    sys.exit(1)

only_live = {k: live[k] for k in live if k not in local}
only_local = {k: local[k] for k in local if k not in live}
diff = {k: (live[k], local[k]) for k in local if k in live and local[k] != live[k]}
print("live unique=%d total=%d | local unique=%d total=%d" % (len(live), sum(live.values()),
                                                              len(local), sum(local.values())))
print("only_live:%d only_local:%d qty_diff:%d" % (len(only_live), len(only_local), len(diff)))
if only_live:
    print("   sample only_live:", json.dumps(dict(list(only_live.items())[:5]), ensure_ascii=False))
if only_local:
    print("   sample only_local:", json.dumps(dict(list(only_local.items())[:5]), ensure_ascii=False))
if diff:
    print("   sample qty diffs:", json.dumps(dict(list(diff.items())[:5]), ensure_ascii=False))
    print("   (فروق بسيطة واردة لو المخزن اتغيّر في اللعبة بين القراءتين)")

identical = not only_live and not only_local and not diff
print("[RESULT]", "IDENTICAL" if identical else "DIVERGED")
sys.exit(0 if identical else 2)
