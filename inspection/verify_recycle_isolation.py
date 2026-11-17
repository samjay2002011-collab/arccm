"""إثبات منطق عزل القطع المرفوضة في direct_mutate — من غير أي طلب للشبكة.

post_mutate مستبدل: طلب فيه أكتر من قطعة بيرمي INVALID_ARGUMENT (زي ما البوابة
بتعمل فعلًا مع الطلب الذرّي)، والطلبات الفردية بتنجح إلا على المعرّف المعلّم
muted — وهو اللي بيمثّل قطعة معلقة في الأوفر رفضتها اللعبة.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

GOOD = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
MUTED = "33333333-3333-3333-3333-333333333333"
CELL = "cccccccc-cccc-cccc-cccc-cccccccccccc"

BEFORE = {"items": [
    {"instanceId": CELL, "gameAssetId": 1, "slots": GOOD, "amount": 1},
    {"instanceId": GOOD[0], "gameAssetId": 828947161, "amount": 10, "durability": 1, "maxDurability": 1},
    {"instanceId": GOOD[1], "gameAssetId": 828947161, "amount": 5, "durability": 1, "maxDurability": 1},
    # مرفوضة: من غير أب = عائمة في الأوفر ستاش
    {"instanceId": MUTED, "gameAssetId": -1174500500, "amount": 1, "durability": 63, "maxDurability": 100},
]}
AFTER = {"items": [
    dict(BEFORE["items"][0], slots=[]),
    dict(BEFORE["items"][3]),
]}

CALLS = []
STATE = {"tree": BEFORE}


def fake_post(request, token):
    ops = request.get("mutations") or []
    CALLS.append([o["instanceId"] for o in ops])
    ids = [o["instanceId"] for o in ops]
    if len(ids) > 1 or ids[0] == MUTED:
        raise pc.PioneerError("POST .../batch-operation -> 400: {\"reason\":\"INVALID_ARGUMENT\"}")
    STATE["tree"] = AFTER
    return {"changeset": {"items": {"created": [], "deleted": ids, "updated": [
        {"instanceId": CELL, "gameAssetId": 828947161, "amount": 99, "slots": None}]}}}


pw.post_mutate = fake_post
pw._refresh_data = lambda conn, account, data: {"ok": True}
pw._log = lambda *a, **k: None
pw._pause_block = lambda: None
pc.account_token = lambda *a, **k: "FAKE-TOKEN"
pc.fetch_inventory_for = lambda account=None: STATE["tree"]
pw.VERIFY_RETRIES = 0
pw.VERIFY_WAIT = 0
pw.pioneer_tree.asset_names = lambda: {"828947161": {"display_name": "Heavy Ammo"}}

# --- 1) اختيار مختلط: القطعتين الصالحتين + واحدة مرفوضة ----------------------
out = pw.direct_mutate(None, "G18", "recycle", GOOD + [MUTED])
print("executed=%s changed=%s skipped=%s" % (out["executed"], [c[:4] for c in out["changed"]], out["skipped"]))
print("refused:", [(r["instance_id"][:4], r["detail"][:40]) for r in out.get("refused") or []])
print("detail:", out.get("detail"))
print("calls:", CALLS)
assert out["executed"], out
assert out["changed"] == GOOD, out["changed"]
assert [r["instance_id"] for r in out["refused"]] == [MUTED], out["refused"]
assert CALLS[0] == GOOD + [MUTED] and len(CALLS) == 4, CALLS
assert len(out["gained"]) == 2, out["gained"]

# --- 2) كل الاختيار مرفوض: رسالة واضحة ومفيش تنفيذ ---------------------------
CALLS.clear()
STATE["tree"] = BEFORE
out = pw.direct_mutate(None, "G18", "recycle", [MUTED])
print("\nall-refused -> executed=%s error=%s" % (out["executed"], out.get("error")))
print("detail:", (out.get("detail") or "")[-190:])
assert not out["executed"] and out.get("error") == "invalid_argument", out
assert "overflow stash" in out["detail"], out["detail"]

# --- 3) كله صالح: طلب batch واحد كفاية (السرعة) ------------------------------
CALLS.clear()
STATE["tree"] = BEFORE


def all_good_post(request, token):
    ids = [o["instanceId"] for o in request["mutations"]]
    CALLS.append(ids)
    STATE["tree"] = {"items": [r for r in BEFORE["items"] if r["instanceId"] not in ids]}
    return {"changeset": {"items": {"created": [], "deleted": ids, "updated": []}}}


pw.post_mutate = all_good_post
out = pw.direct_mutate(None, "G18", "recycle", GOOD)
print("\nall-good -> executed=%s changed=%s calls=%s" % (out["executed"], len(out["changed"]), CALLS))
assert out["executed"] and len(CALLS) == 1 and len(CALLS[0]) == 2, (out, CALLS)
assert not out.get("refused"), out

print("\nALL ASSERTIONS PASSED — isolation works and no request left this process.")
