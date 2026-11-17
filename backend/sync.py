"""ساحب البيانات: يقرأ المخزن من Rampart ويخزنه محلياً، ومعاه حاصد أيقونات.

لو المنبع واقع/التوكن منتهي: البيانات القديمة تفضل مقروءة من آخر snapshot،
والوضع بيتسجل offline_cached عشان الواجهة تعرض مؤشر الحالة.
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import accounts, config, derive, knowledge, pioneer_sync, rampart_client, repair_costs, store

DIRECT = config.DATA_SOURCE == "pioneer"

# آخر محاولة سحب قام بها هذا التشغيل بالذات (عشان الوضع المعروض ما يخلطش بين عميلين على نفس القاعدة).
LAST_PULL = {}


def account_pairs(conn):
    """كل الحسابات المفعّلة القابلة للسحب من جدول accounts."""
    pairs = accounts.enabled_pairs(conn)
    if DIRECT:
        # في الوضع المباشر لازم يكون للسحب توكن Embark خاص بيه (الحسابات القديمة المرتبطة برامبيرت ملهاش توكن).
        return [(name, aid) for name, aid in pairs if (store.get_account(conn, aid) or {}).get("token")]
    return pairs


def collect_image_names(node, depth=0, out=None):
    """يجمع كل أسماء الصور من أي payload (عناصر/تجار/إحصاءات) عبر مفتاح image_filename/image/image_wide."""
    if out is None:
        out = set()
    if depth > 10:
        return out
    if isinstance(node, dict):
        for key, val in node.items():
            if key in ("image_filename", "image", "image_wide") and isinstance(val, str) and val.endswith((".webp", ".png", ".jpg")):
                out.add(val)
            else:
                collect_image_names(val, depth + 1, out)
    elif isinstance(node, list):
        for val in node:
            collect_image_names(val, depth + 1, out)
    return out


def harvest_assets(payload, force=False):
    """ينزّل أيقونات العناصر الجديدة فقط (GET /assets/{file}) — قراءة فقط."""
    names = collect_image_names(payload)

    conn = store.db()
    known = {r["filename"] for r in conn.execute("SELECT filename FROM assets")}
    todo = sorted(n for n in names if force or n not in known)
    if not todo:
        conn.close()
        return {"downloaded": 0, "already_local": len(names & known), "failed": 0}

    headers = rampart_client.headers()

    def one(filename):
        dest = os.path.join(config.ITEM_ASSETS_DIR, filename)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return filename, os.path.getsize(dest), True
        try:
            res = requests.get(config.ASSET_URL.format(filename=filename), headers=headers, timeout=20)
            if res.status_code == 200 and res.content:
                with open(dest, "wb") as f:
                    f.write(res.content)
                return filename, len(res.content), True
        except Exception:
            pass
        return filename, 0, False

    done = failed = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for filename, size, ok in pool.map(one, todo):
            if ok:
                done += 1
                conn.execute("INSERT OR REPLACE INTO assets(filename,size,fetched_at) VALUES(?,?,?)",
                             (filename, size, time.time()))
            else:
                failed += 1
    conn.commit()
    conn.close()
    return {"downloaded": done, "already_local": len(names & known), "failed": failed}


def pull_traders(conn, account, account_id):
    """قراءة عروض التجار (GET فقط) وتخزينها مع آخر سحب لنفس الحساب."""
    if DIRECT:
        return {"ok": False, "skipped": "pioneer_source",
                "detail": "Trader offers are not published on the direct gateway — the last saved copy is what is shown."}
    try:
        payload = rampart_client._get(config.TRADERS_PATH)
        store.set_meta(conn, "traders:%s" % account, payload)
        conn.commit()
        harvest_assets(payload)
        return {"ok": True, "traders": len(payload) if isinstance(payload, dict) else 0}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def ingest(conn, account, payload, with_assets=True):
    """يخزّن payload مخزن جاهز في الـ snapshot بدون أي طلب شبكة.

    بستخدمه النقل المباشر بعد التحقق عشان يوفّر الـ GET التاني.
    """
    totals, details = derive.flatten_payload(payload)
    summary = {}
    for name, rows in details.items():
        total = sum(r["qty"] for r in rows)
        summary[name] = dict(rows[0], qty=total)
    # جدول الـ instances للوحة الإدارة: يشمل التالف والمُرتدى (أرقام auto_sync ما تتأثرش)
    _, inventory_all = derive.flatten_payload(payload, keep_damaged=True)
    instances = {name: list(rows) for name, rows in inventory_all.items()}
    for name, rows in derive.equipped_instances(payload).items():
        instances.setdefault(name, []).extend(rows)
    prev_snapshot = store.latest_snapshot_path(conn, account)
    path = store.save_snapshot(conn, account, payload, summary, details=instances)
    knowledge.observe(conn, account)
    try:
        repair_costs.observe(account, payload, prev_snapshot)
    except Exception as exc:  # التعلم مش سبب إن المزامنة تفشل
        print("repair-cost observe skipped: %s" % str(exc)[:120])
    if payload.get("unlocked_blueprints") is not None:
        knowledge.remember_unlocked(conn, account, payload["unlocked_blueprints"])
    if payload.get("bench_levels") is not None:
        knowledge.remember_bench_levels(conn, account, payload["bench_levels"])
        conn.commit()
    assets = harvest_assets(payload) if (with_assets and not DIRECT) else {}
    return {"account": account, "ok": True, "items": len(summary), "instances": sum(len(v) for v in details.values()),
            "snapshot": os.path.basename(path), "assets": assets, "stats": (payload.get("stats") or {})}


def pull_account(conn, account, account_id, with_assets=True, data=None):
    try:
        from . import pioneer_write
        pioneer_write.invalidate_live_cache(account)
    except Exception:
        pass
    try:
        payload = (pioneer_sync.build_payload(conn, account, data=data) if DIRECT
                   else rampart_client.fetch_inventory(account_id))
    except Exception as e:
        store.record_failure(conn, account, e)
        return {"account": account, "ok": False, "error": str(e)[:200]}
    return ingest(conn, account, payload, with_assets=with_assets)


def pull_all(with_assets=True, only=None):
    """يسحب كل الحسابات المفعّلة، أو حساب واحد (اسم/معرّف) لو only اتحددت."""
    conn = store.db()
    started = time.time()
    results = []
    for account, account_id in account_pairs(conn):
        if only and only not in (account, account_id):
            continue
        res = pull_account(conn, account, account_id, with_assets=with_assets)
        if res.get("ok"):
            res["traders"] = pull_traders(conn, account, account_id)
            conn.execute("UPDATE accounts SET last_sync=? WHERE id=?", (time.time(), account_id))
            conn.commit()
        results.append(res)
        if res.get("ok") and res.get("stats"):
            store.set_meta(conn, "stats:%s" % account, res["stats"])
    if only and not results:
        conn.close()
        raise KeyError("unknown account: %s" % only)
    online = sum(1 for r in results if r.get("ok"))
    total = len(results) if only else len(account_pairs(conn))
    status = {
        "generated_at": started,
        "duration_sec": round(time.time() - started, 1),
        "mode": "online" if online == total and online else ("degraded" if online else "offline_cached"),
        "accounts_online": online,
        "accounts_total": total,
        "results": [{k: v for k, v in r.items() if k != "stats"} for r in results],
    }
    store.set_meta(conn, "last_pull", status)
    conn.commit()
    LAST_PULL.clear()
    LAST_PULL.update(status)
    try:
        with open(config.STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    conn.close()
    return status


def status_snapshot():
    """حالة السيرفر المحلي: أي حساب متاح، ومن أين ستُقرأ البيانات (حي/مخزن)."""
    conn = store.db()
    out = {"mode": "unknown", "accounts": {}, "token": {}, "data_source": config.DATA_SOURCE}
    if DIRECT:
        active = store.active_account(conn)
        token = (active or {}).get("token") or ""
        exp = rampart_client.token_expiry(token) if token else 0
    else:
        token = rampart_client.read_token()
        exp = rampart_client.token_expiry(token) if token else 0
    out["token"] = {"present": bool(token), "expires_at": exp,
                    "expires_in_hours": round((exp - time.time()) / 3600, 1) if exp else None}
    for account, _ in account_pairs(conn):
        last = store.last_success(conn, account)
        out["accounts"][account] = {
            "last_success": last,
            "age_minutes": round((time.time() - last) / 60, 1) if last else None,
            "snapshot_available": bool(store.latest_snapshot_path(conn, account)),
            "items": conn.execute("SELECT COUNT(*) c FROM items WHERE account=?", (account,)).fetchone()["c"],
        }
    last_pull = dict(LAST_PULL or store.get_meta(conn, "last_pull") or {})
    age = time.time() - float(last_pull.get("generated_at") or 0)
    cached = any(a["snapshot_available"] for a in out["accounts"].values())
    if last_pull.get("mode") == "online" and age < max(config.REFRESH_SECONDS * 3, 600):
        out["mode"] = "online"
    elif cached:
        out["mode"] = "offline_cached"
    else:
        out["mode"] = "no_data"
    out["last_attempt_age_minutes"] = round(age / 60, 1) if last_pull else None
    out["accounts_online"] = last_pull.get("accounts_online")
    out["accounts_total"] = last_pull.get("accounts_total")
    out["last_pull"] = {k: v for k, v in last_pull.items() if k != "results"}
    out["assets_local"] = conn.execute("SELECT COUNT(*) c FROM assets").fetchone()["c"]
    conn.close()
    return out


def run_loop(interval=None, initial_delay=None):
    interval = interval or config.REFRESH_SECONDS
    if initial_delay:
        time.sleep(initial_delay)
    while True:
        status = pull_all()
        print("[sync] %s -> %s (%s)" % (time.strftime("%H:%M:%S"), status["mode"],
                                        ", ".join("%s:%s" % (r["account"], r.get("items", r.get("error"))) for r in status["results"])),
              flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one pull then exit")
    ap.add_argument("--loop", action="store_true", help="keep running on the interval set in RAMPART_LOCAL_REFRESH")
    ap.add_argument("--assets-only", action="store_true", help="redownload the icons only")
    args = ap.parse_args()

    if args.assets_only and DIRECT:
        print("[assets] skipped: direct sync mode — pulling from rampart.su is stopped.")
    elif args.assets_only:
        conn = store.db()
        total = {"downloaded": 0, "failed": 0}
        for account, _ in account_pairs(conn):
            payload, _ = store.read_snapshot(conn, account)
            if payload:
                got = harvest_assets(payload, force=True)
                total["downloaded"] += got["downloaded"]
                total["failed"] += got["failed"]
        conn.close()
        print("[assets]", total)
    elif args.loop:
        run_loop()
    else:
        print(json.dumps(pull_all(), ensure_ascii=False, indent=1))
