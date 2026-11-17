"""طابور النقل المؤجّل: الخطط اللي بترفضها البوابة لأن مسار الكتابة مقفول بتتخزن هنا،
وبيعيد إرسالها نفسها تلقائياً أول ما أي مسار نقل يرجع تركيبه — من غير ما التابض يفضل مفتوح.

كل خطة بتُحلّل من جديد على شجرة السيرفر لحظة التنفيذ، فالقطعة اللي اتحركت أو اتباعت في
البين بتُسقَط وحدها بدل ما تنفّذ غلط.
"""
import json
import os
import threading
import time
import uuid

from . import config, pioneer_client as pc, pioneer_write as pw, store

FILE = os.path.join(config.DATA_DIR, "pending_moves.json")
LOOP_SECONDS = 15
MAX_TRIES = 120        # ~30 دقيقة محاولات، بعدها بنسجّلها فاشلة وبنشيلها من الطابور

# الخطة خلصت دورها: الوجهة اتشغلت قبل كده أو القطعة مابتعيشش في الشجرة دي.
FINAL_ERRORS = ("already_there", "unknown_instance", "nothing_selected", "bad_target",
                "slot_occupied", "bad_wrapper", "bad_slot")
# البوابة لسه مقفولة أو القراءة نفسها تعبانة: بنوقف الجولة كلها واستنى المسار يرجع.
WAIT_ERRORS = ("gateway_route_down", "gateway_error", "network", "token_expired",
               "read_only", "write_precondition", "tree_root_missing", "stash_missing",
               "no_stash", "no_backpack")
# الخطة مستنية شرط من اللاعب (الوجهة ممتلئة): دي مش غلط في المسار، فبدل ما تحبس
# الخطط اللي وراها لحد ما الخانة تتفضى، بتترجّل لآخر الطابور وتاخد دورها بعدين.
DEFER_ERRORS = ("no_empty_target",)

_lock = threading.Lock()
_stop = threading.Event()


def _read():
    try:
        with open(FILE, encoding="utf-8") as fh:
            rows = json.load(fh)
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _mutate(transform):
    """بنية الملف كلها تحت قفل واحد: قراءة + تعديل + كتابة."""
    with _lock:
        items = transform(_read())
        _save(items)
        return items


def _save(items):
    tmp = FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, FILE)
    except OSError:
        pass


def enqueue(account, moves, summary=""):
    """بيضيف خطة نقل للطابور — بنفس شكل /api/actions/move-batch بالظبط."""
    moves = [m for m in (moves or []) if m and m.get("instance_ids")]
    if not moves:
        return {"ok": False, "error": "nothing_to_queue", "detail": "The plan has no items."}
    entry = {"id": uuid.uuid4().hex[:10], "account": str(account or ""),
             "created_at": time.time(), "tries": 0, "summary": str(summary or "")[:160],
             "moves": moves, "status": "waiting", "detail": ""}
    items = _mutate(lambda rows: rows + [entry])
    return {"ok": True, "entry": entry, "count": len(items)}


def listing():
    items = _read()
    return {"items": items, "count": len(items), "route": pw.route_state()}


def brief():
    """عداد خفيف لـ /api/status: كام خطة مستنية على كل حساب."""
    items = _read()
    per = {}
    for row in items:
        per[str(row.get("account") or "")] = per.get(str(row.get("account") or ""), 0) + 1
    return {"count": len(items), "accounts": per, "route_alive": bool(pw.route_state().get("alive"))}


def remove(entry_id):
    items = _read()
    left = [i for i in items if i.get("id") != entry_id]
    if len(left) == len(items):
        return {"ok": False, "error": "not_found", "count": len(items)}
    _mutate(lambda rows: [i for i in rows if i.get("id") != entry_id])
    return {"ok": True, "count": len(left)}


def clear(account=None):
    items = _read()
    kept = [i for i in items if account and i.get("account") != account]
    _mutate(lambda rows: [i for i in rows if not account or i.get("account") != account])
    return {"ok": True, "removed": len(items) - len(kept), "count": len(kept)}


def _finish(entry_id, detail):
    _mutate(lambda rows: [i for i in rows if i.get("id") != entry_id])
    return str(detail)[:200]


def _retry(entry_id, tries, status, detail):
    def edit(rows):
        for row in rows:
            if row.get("id") == entry_id:
                row["tries"] = tries
                row["status"] = status
                row["detail"] = str(detail)[:200]
        return rows
    _mutate(edit)


def _defer(entry_id, tries, detail):
    """بتعدّل الخطة لآخر الطابور بعد احتساب المحاولة، فاللي وراها تاخد دورها حالاً."""
    def edit(rows):
        for row in rows:
            if row.get("id") == entry_id:
                row["tries"] = tries
                row["status"] = "waiting"
                row["detail"] = str(detail)[:200]
        head = [r for r in rows if r.get("id") == entry_id]
        rest = [r for r in rows if r.get("id") != entry_id]
        return rest + head
    return _mutate(edit)


def flush_once():
    """بينفّذ الطابور بالترتيب — خطة واحدة لكل جولة عشان اللوحة بتتغير بعد كل كتابة."""
    items = _read()
    if not items:
        return {"ran": 0, "left": 0, "result": "empty"}
    if pw.paused():
        return {"ran": 0, "left": len(items), "result": "write_paused"}
    entry = items[0]
    account = entry.get("account") or ""
    if not account:
        _finish(entry["id"], "No account on this plan.")
        return {"ran": 0, "left": len(_read()), "result": "dropped_no_account"}
    token = pc.account_token(account)
    if not pw.route_alive(token):
        return {"ran": 0, "left": len(items), "result": "route_down"}

    conn = store.db()
    try:
        res = pw.move_plan(conn, account, entry.get("moves") or [])
        if res.get("executed"):
            outcome = ("executed", {"items": res.get("items")}, res.get("items") or 0)
        else:
            error = res.get("error") or "blocked"
            detail = res.get("detail") or error
            tries = int(entry.get("tries") or 0) + 1
            final = error in FINAL_ERRORS or tries >= MAX_TRIES
            outcome = ("dropped" if final else "deferred",
                       {"error": error, "detail": str(detail)[:300]}, 0)
        store.log_action(conn, account, "move:queued",
                         {"queued_id": entry["id"], "summary": entry.get("summary"),
                          "moves": len(entry.get("moves") or [])},
                         outcome[0], outcome[1], outcome[2])
    except Exception as exc:                     # أي استثناء ما بيوقفش الخيط
        res = {"executed": False, "error": "gateway_error",
               "detail": "%s: %s" % (type(exc).__name__, exc)}
        outcome = ("deferred", {"detail": str(exc)[:200]}, 0)
    finally:
        conn.close()

    if res.get("executed"):
        _finish(entry["id"], "Moved.")
        return {"ran": 1, "left": len(_read()), "result": "executed", "moved": res.get("moved")}
    error = res.get("error") or "blocked"
    detail = res.get("detail") or error
    tries = int(entry.get("tries") or 0) + 1
    if outcome[0] == "dropped":
        _finish(entry["id"], detail)
        return {"ran": 1, "left": len(_read()), "result": "dropped", "error": error,
                "detail": str(detail)[:200]}
    if error in DEFER_ERRORS:
        _defer(entry["id"], tries, detail)
        return {"ran": 1, "left": len(_read()), "result": error, "detail": str(detail)[:200]}
    _retry(entry["id"], tries, "waiting" if error in WAIT_ERRORS else "retrying", detail)
    return {"ran": 1, "left": len(_read()), "result": error, "detail": str(detail)[:200]}


def stop():
    _stop.set()


def run_loop(interval=LOOP_SECONDS, initial_delay=None):
    if initial_delay:
        time.sleep(initial_delay)
    while not _stop.wait(interval):
        try:
            res = flush_once()
            if res["result"] not in ("empty", "route_down", "write_paused"):
                print("[queue] %s left=%s %s" % (res["result"], res["left"],
                                                 str(res.get("detail") or "")[:120]), flush=True)
        except Exception as exc:                 # الحارس ما بيرضاش يسكت
            print("[queue] error %s: %s" % (type(exc).__name__, str(exc)[:160]), flush=True)
