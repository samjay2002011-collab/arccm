"""السيرفر المحلي: واجهة مطابقة + API يقرأ من آخر نسخة محفوظة لو Rampart واقع.

المسارات:
  /                       اللوحة (frontend) — بتفتح مباشرة لكل من يدخل على البورت
  /assets/items/{f}       أيقونة مخزنة محلياً
  /api/status             online / offline_cached + عمر آخر سحب
  /api/items              شبكة العناصر (بحث/فلترة/ترتيب/تجميع)
  /api/inventory          {اسم: كمية} بنفس دمج auto_sync (max عبر الحسابات)
  /inventory/parsed       إعادة تقديم لـ payload rampart الخام للحساب النشط
  /local/activate/{acc}   تبديل الحساب النشط محلياً (بدون أي طلب تعديل للمنبع)
  /api/refresh            يشغّل سحب جديد (قراءة فقط من المنبع)

المسارات الإدارية (بتكتب على حساب اللعبة — مقفولة افتراضياً لحد الـ ARM):
  /api/sections           أعمدة STASH/BACKPACK/OVERFLOW/EQUIPPED
  /api/item               تفاصيل نسخة واحدة (متانة/ندرة/سعر/ريسيبي)
  /api/writes             حالة قفل الكتابة + الإجراءات التدميرية الممنوعة
  /api/writes/arm         يفتح الكتابة بعد تأكيد مكتوب صريح
  /api/actions/move       نقل نسخة/مجموعة لنقسم تاني (batch-move)
  /api/actions/mutate     split / combine / recycle / scrap / repair (batch-mutate)
  /api/catalog/search     بحث في كل عناصر اللعبة (كاش arctracker المحلي)
  /api/items/db           كل بيانات عنصر من قاعدة arctracker: ريسايكل/كرافت/ترقية
  /api/items/db/meta      إصدار قاعدة البيانات وعدد العناصر
  /api/assets/unknown     كل asset id مملوك من غير اسم (بنود الباتش الجديد)
  /api/assets/name        تسجيل اسم بند جديد في الفهرس المحلي (قراءة فقط من المنبع)
  /api/accounts/add       إضافة حساب بالتوكن (نسخ/لصق يدوي)
  /api/accounts/auto      تسجيل آلي من أجن اللعبة المحلي (loopback + مفتاح مشترك)
  /api/actions/log        سجل كل الإجراءات المرسلة أو المرفوضة
  /api/agent/handshake    بيوصل الأجن بمفتاح الجهاز ومجلد المشروع (loopback فقط)

الباب: مفتوح — مفيش كلمة مرور ولا كوكي جلسة. اللي محتاج حماية لوحده هو الأجن
المحلي بس (/api/agent/* و /api/accounts/auto) وده بيتحقق بـ loopback صافي + مفتاح
data/agent_secret.txt، فمش متأثر بإلغاء الباب.
"""
import json
import gzip
import hashlib
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Cookie
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse

from . import accounts as accounts_mod
from . import actions, agent_link, agent_release, augments, auth, catalog, config, derive, items_db, loadouts, move_queue, writer
from . import pioneer_client, rampart_client, knowledge, scrappy, store, sync as sync_mod, traders as traders_mod, workshop
from . import subscribers as subs_mod

_lock = threading.Lock()


def _with_conn(fn):
    """يشغّل fn(conn) تحت القفل نفسه بتاع السحب، ويقفل القاعدة في كل الأحوال."""
    conn = store.db()
    try:
        with _lock:
            return fn(conn)
    finally:
        conn.close()


def _with_conn_free(fn):
    """زي _with_conn بس من غير القفل العام — لمسارات النقل.

    النقل بيقعد ثانية على الشبكة (قراءة + كتابة + تحقق)، والقفل العام كان
    بيوقف معاه كل قراءات اللوحة والتابات التانية. القاعدة نفسها بتستحمل
    الاتصالات المتزامنة (timeout=30) والكتابة بتتم في معاملة واحدة."""
    conn = store.db()
    try:
        return fn(conn)
    finally:
        conn.close()


def _refresh_guarded():
    with _lock:
        return sync_mod.pull_all()


def _sync_active_name(conn, owner=None):
    """يخلي المتغير النشط مطابق لجدول الحسابات (المصدر الحقيقي للاسم الحالي)."""
    rec = store.active_account(conn, owner=owner)
    if rec:
        ACTIVE["account"] = rec["name"]
    return ACTIVE["account"]


@asynccontextmanager
async def lifespan(_app):
    conn = store.db()
    seeded = accounts_mod.seed(conn, pull_upstream=(config.DATA_SOURCE != "pioneer"))
    _sync_active_name(conn)
    fresh = any(store.last_success(conn, a) > time.time() - config.REFRESH_SECONDS for a, _ in sync_mod.account_pairs(conn))
    conn.close()
    print("[accounts] %s" % seeded, flush=True)
    if not fresh:
        _refresh_guarded()
    worker = threading.Thread(target=sync_mod.run_loop,
                              kwargs={"initial_delay": config.REFRESH_SECONDS}, daemon=True)
    worker.start()
    # الطابور بيحيّط كل 15 ثانية: لو Embark رجّعت مسار الكتابة، الخطط المستنىّة بتنّفّذ نفسها
    # من غير ما أي تابض يكون مفتوح.
    queue_worker = threading.Thread(target=move_queue.run_loop, kwargs={"initial_delay": 8},
                                    daemon=True)
    queue_worker.start()
    yield


# ── إخفاء docs الـ API عشان ما حدش يشوف المسارات ──
app = FastAPI(title="CM — Inventory & Loadout Manager", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
# ردا /api/sections حجمه ميجابايتات، والضغط بيخلص الاختناق اللي كان بيوقف الطلبات الصغيرة وراه
app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=6)
ACTIVE = {"account": ""}


# مفيش باب بكلمة مرور: / والـ API كلهم مفتوحين من غير أي كوكي.


# الصور والخطوط والـ JS/CSS (كلها بتتبعت بـ ?v= الرقم بيتغير مع أي تعديل) بتتحمّل
# مرة واحدة وتقعد في المتصفح سنة. بيانات المخزن مبيتكاش عنها حاجة.
FOREVER = "public, max-age=31536000, immutable"
STATIC_EXT = {".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
              ".ttf", ".otf", ".eot", ".css", ".js"}


@app.middleware("http")
async def cache_headers(request, call_next):
    """كاش سنة للثابت، no-store لكل API/JSON + Security Headers لحماية الكود."""
    response = await call_next(request)
    path = request.url.path or "/"
    ext = os.path.splitext(path)[1].lower()
    if path in ("/login.js", "/admin.js", "/shield.js", "/admin_mode.js"):
        response.headers["Cache-Control"] = "no-cache"
    elif ext in STATIC_EXT:
        response.headers.setdefault("Cache-Control", FOREVER)
    elif path == "/" or ext in (".html", ".htm"):
        response.headers.setdefault("Cache-Control", "no-cache")
    else:
        response.headers.setdefault("Cache-Control", "no-store")

    # ── Security Headers: حماية ضد سرقة الكود ──
    # CSP: يمنع أي script خارجي
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https://cdn.discordapp.com data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    # يمنع تحميل الموقع في iframe (ضد clickjacking + ضد تضمين الكود في موقع تاني)
    response.headers.setdefault("X-Frame-Options", "DENY")
    # يمنع المتصفح من تخمين نوع الملف
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # يمنع إرسال الـ referrer لمواقع تانية
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # يمنع APIs الخطيرة (camera, microphone, etc.)
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    return response


# ══════════════════════════════════════════════════════════════════════════════
# نظام الاشتراكات: التحقق من التوكن + صفحة اللوجن + لوحة الأدمين
# ══════════════════════════════════════════════════════════════════════════════

# مسارات مفتوحة بدون توكن مشترك
_PUBLIC_PATHS = {
    "/login", "/auth/subscriber/login", "/admin", "/favicon.png",
    "/login.js", "/admin.js", "/admin_mode.js",
    "/api/status", "/api/subscriber/verify", "/download/CMSync.exe", "/CMSync.exe"
}
_PUBLIC_PREFIXES = ("/admin/api/", "/auth/subscriber/", "/download/")
# مفتاح جلسة الأدمين — بيتغير مع كل restart
_ADMIN_SESSIONS = set()


def is_local_direct_request(request: Request) -> bool:
    """التحقق إذا كان الطلب قادماً مباشرة من الجهاز المحلي على البورت 8001 (وليس نفق كلاودفلير)."""
    # 1. إذا كان فيه هيدرز كلاودفلير — يبقى أكيد طلب خارجي عبر النفق
    cf_headers = ("cf-ray", "cf-connecting-ip", "cf-visitor", "cdn-loop")
    if any(h in request.headers for h in cf_headers):
        return False

    # 2. فحص الـ Host header — هل هو localhost:8001 أو 127.0.0.1:8001؟
    host_hdr = (request.headers.get("host") or "").lower().split(":")[0]
    if host_hdr not in ("127.0.0.1", "localhost", "::1"):
        return False

    # 3. فحص عنوان العميل IP
    client_ip = getattr(request.client, "host", "") if request.client else ""
    if client_ip not in ("127.0.0.1", "::1", "localhost", "testclient", ""):
        return False

    return True


@app.middleware("http")
async def subscriber_auth(request, call_next):
    """كل طلب لازم يكون من مشترك بتوكن صالح — ما عدا صفحة اللوجن والأدمين."""
    path = request.url.path or "/"

    # 0. الوصول المباشر من نفس الجهاز على البورت 8001 — دخول فوري كامل بدون أي قيود أو باسوردات
    if is_local_direct_request(request):
        return await call_next(request)

    # المسارات المفتوحة
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    # الملفات الثابتة بتاعة صفحة اللوجن
    if path.endswith((".css", ".png", ".webp", ".svg", ".ico", ".woff", ".woff2")):
        return await call_next(request)

    # الأجن المحلي (CMSync) — loopback بمفتاح مشترك، مش محتاج توكن مشترك
    if path.startswith("/api/agent/") or path.startswith("/api/accounts/auto"):
        return await call_next(request)

    # التحقق من جلسة الأدمين — الأدمين يقدر يتصفح أي صفحة وأي API بدون توكن مشترك
    admin_sess = request.cookies.get("cm_admin_session", "")
    if admin_sess and admin_sess in _ADMIN_SESSIONS:
        return await call_next(request)

    # التحقق من كوكي أو هيدر التوكن
    token = request.cookies.get("cm_subscriber_token") or request.headers.get("X-Subscriber-Token") or ""
    if not token:
        # API calls بترجع 401، صفحات HTML بتتحول للوجن
        if path.startswith("/api/") or path.startswith("/local/"):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=302)

    # التحقق من توكن الأدمين أو المشترك
    conn = store.db()
    subs_mod._ensure_tables(conn)
    adm_token = subs_mod.admin_token(conn)
    if token == adm_token:
        conn.close()
        return await call_next(request)

    # التحقق من صحة التوكن (بدون تسجيل دخول — بس نشوف إنه لسه valid)
    row = conn.execute(
        "SELECT id, name, expires_at, is_active FROM subscribers WHERE token=?",
        (token,)).fetchone()
    conn.close()

    if not row or not row[3]:  # مش موجود أو معطّل يدوي
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Invalid or disabled token"}, status_code=401)
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie("cm_subscriber_token")
        return resp

    if row[2] and row[2] < time.time():  # منتهي الصلاحية
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Subscription expired"}, status_code=401)
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie("cm_subscriber_token")
        return resp

    return await call_next(request)


# ──────────────────────────── صفحة اللوجن ────────────────────────────────
@app.get("/login")
def login_page(request: Request):
    if is_local_direct_request(request) and not request.query_params.get("preview"):
        return RedirectResponse("/", status_code=302)
    return FileResponse(os.path.join(config.FRONTEND_DIR, "login.html"))


@app.post("/auth/subscriber/login")
async def subscriber_login(request: Request):
    body = await request.json()
    raw_token = (body.get("token") or "").strip()

    conn = store.db()
    adm_pw = subs_mod.admin_password(conn)
    # 1. باسورد الأدمين الموحد — دخول مباشر كأدمن إلى لوحة الأدمن وقائمة المشتركين
    if raw_token == adm_pw:
        conn.close()
        session = secrets.token_hex(16)
        _ADMIN_SESSIONS.add(session)
        resp = JSONResponse({"ok": True, "name": "Admin", "is_admin": True, "redirect": "/admin"})
        resp.set_cookie("cm_admin_session", session, max_age=86400, httponly=True, samesite="lax")
        resp.set_cookie("cm_subscriber_token", adm_pw, max_age=400*86400, httponly=True, samesite="lax")
        resp.delete_cookie("cm_viewing_subscriber")
        return resp

    # 2. فحص الدخول كمشترك عادي من قاعدة البيانات
    sub = subs_mod.verify_token(conn, raw_token)
    conn.close()
    if not sub:
        return JSONResponse({"ok": False, "detail": "Invalid or expired access token."})
    resp = JSONResponse({"ok": True, "is_admin": False, "name": sub["name"], "expires_at": sub.get("expires_at"), "redirect": "/"})
    # الكوكي بتعيش 400 يوم — التحقق الحقيقي بيتم من الداتابيز كل طلب
    resp.set_cookie("cm_subscriber_token", raw_token, max_age=400*86400, httponly=True, samesite="lax")
    resp.delete_cookie("cm_viewing_subscriber")
    return resp


def _caller_identity(request: Request, conn):
    """استخراج هوية المتصل: أدمن، أو مشترك محدد، أو أدمن يتصفح مشتركاً."""
    import urllib.parse
    is_local = is_local_direct_request(request)
    token = request.cookies.get("cm_subscriber_token") or request.headers.get("X-Subscriber-Token") or ""
    admin_sess = request.cookies.get("cm_admin_session", "")
    view_cookie = request.cookies.get("cm_viewing_subscriber", "")
    if view_cookie:
        view_cookie = urllib.parse.unquote(view_cookie)

    subs_mod._ensure_tables(conn)
    adm_pw = subs_mod.admin_password(conn)

    sub_name = ""
    if token and token != adm_pw:
        row = conn.execute("SELECT name FROM subscribers WHERE token=?", (token,)).fetchone()
        if row:
            sub_name = row[0]

    is_admin = is_local or (token == adm_pw) or (admin_sess and admin_sess in _ADMIN_SESSIONS)
    url_view = (request.query_params.get("view_as") or request.query_params.get("subscriber") or request.query_params.get("owner") or "").strip()
    if url_view:
        url_view = urllib.parse.unquote(url_view)
    viewing_as = (url_view or view_cookie or "") if is_admin else ""
    # إذا كان أدمن ومش بيتصفح مشترك معين: filter_owner فاضي تماماً حتى لا تظهر أي حسابات
    filter_owner = viewing_as if is_admin else (sub_name if not is_admin else "")

    return {
        "is_admin": bool(is_admin),
        "is_local": bool(is_local),
        "subscriber_name": sub_name or ("Admin" if is_admin else ""),
        "viewing_as": viewing_as if is_admin else "",
        "filter_owner": (filter_owner or "").strip()
    }


SUBSCRIBER_ALIASES = {
    "youseif": {"youseif", "yousef", "youssef", "yousif", "يوسف"},
    "يوسف": {"youseif", "yousef", "youssef", "yousif", "يوسف"},
    "af": {"af", "ahmed", "ahmad", "احمد"},
    "احمد": {"af", "ahmed", "ahmad", "احمد"},
    "ahmed": {"af", "ahmed", "ahmad", "احمد"},
    "فهمي": {"فهمي", "fahmy", "fahmi"},
    "fahmy": {"فهمي", "fahmy", "fahmi"},
}


def is_account_accessible(rec, filter_owner: str = "", is_admin: bool = False) -> bool:
    """صلاحية الوصول للحساب:
    - الأدمن إذا لم يكن يتصفح مشتركاً محدداً: لا يرى أي حساب نهائياً (مخصص لعرض لوحة التحكم وقائمة المشتركين فقط).
    - إذا كان هناك filter_owner: الحساب يظهر في بروفايل المشترك الخاص به فقط.
    """
    if is_admin and not filter_owner:
        return False
    clean_filter = (filter_owner or "").strip().lower()
    if not clean_filter:
        return False
    owner_str = (rec.get("owner_username") or "").strip().lower()
    if not owner_str:
        return False
    owners = set(o.strip() for o in owner_str.split(",") if o.strip())
    filter_set = SUBSCRIBER_ALIASES.get(clean_filter, {clean_filter})
    return bool(filter_set & owners) or "all" in owners or "public" in owners


def _one_account(account):
    """اسم حساب محدّد دايمًا: أي 'ALL' أو فاضي بيرجعون للحساب النشط."""
    name = str(account or "").strip()
    return name if name and name != "ALL" else ACTIVE["account"]


def _accessible_account(account, request: Request, conn):
    """اسم حساب صالح للمتصل الحالي. يدعم المرونة والمشاركة عبر البروفايلات."""
    ident = _caller_identity(request, conn)
    filter_owner = ident["filter_owner"]
    is_admin = ident["is_admin"]
    if is_admin and not filter_owner:
        return ""
    rows = [r["name"] for r in store.list_accounts(conn)
            if is_account_accessible(r, filter_owner, is_admin)]
    name = str(account or "").strip()
    if name and name in rows:
        return name
    return rows[0] if rows else ""


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    """التحقق من نوع التوكن المسجل حالياً (أدمين أم مشترك عادي) ومعرفة ما إذا كان الأدمن يتصفح حساب مشترك."""
    conn = store.db()
    try:
        ident = _caller_identity(request, conn)
    finally:
        conn.close()

    return {
        "ok": True,
        "is_admin": ident["is_admin"],
        "is_local": ident["is_local"],
        "viewing_as": ident["viewing_as"],
        "subscriber_name": ident["subscriber_name"]
    }


@app.post("/api/subscriber/verify")
def api_subscriber_verify(request: Request, body: dict = None):
    """فحص توكن المشترك لبرنامج CMSync أو التحقق الخارجي."""
    body = body or {}
    raw_token = (body.get("token") or request.headers.get("X-Subscriber-Token") or "").strip()
    if not raw_token:
        raise HTTPException(400, "token required")
    conn = store.db()
    subs_mod._ensure_tables(conn)
    adm_tok = subs_mod.admin_token(conn)
    if raw_token == adm_tok:
        conn.close()
        return {"ok": True, "name": "Admin", "is_admin": True, "expires_at": None}
    sub = subs_mod.verify_token(conn, raw_token)
    conn.close()
    if not sub:
        raise HTTPException(401, "Invalid, disabled, or expired subscriber token")
    return {"ok": True, "name": sub["name"], "is_admin": False, "expires_at": sub.get("expires_at")}


@app.get("/download/CMSync.exe")
@app.get("/CMSync.exe")
def download_cmsync():
    """تحميل برنامج CMSync للمشتركين."""
    paths = [
        os.path.join(config.ROOT, "CMSync.exe"),
        os.path.join(config.ROOT, "agent", "dist", "CMSync.exe"),
        os.path.join(config.ROOT, "agent", "CMSync.exe"),
    ]
    target = next((p for p in paths if os.path.isfile(p)), None)
    if not target:
        raise HTTPException(404, "CMSync.exe not found on server")
    return FileResponse(target, filename="CMSync.exe", media_type="application/octet-stream")


@app.get("/auth/logout")
@app.get("/auth/subscriber/logout")
def subscriber_logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("cm_subscriber_token")
    resp.delete_cookie("cm_admin_session")
    return resp


# ──────────────────────────── لوحة الأدمين ──────────────────────────────
@app.get("/admin")
def admin_page(request: Request):
    if is_local_direct_request(request):
        resp = FileResponse(os.path.join(config.FRONTEND_DIR, "admin.html"))
        sess = request.cookies.get("cm_admin_session", "")
        if not sess or sess not in _ADMIN_SESSIONS:
            sess = "local_admin_" + secrets.token_hex(8)
            _ADMIN_SESSIONS.add(sess)
            resp.set_cookie("cm_admin_session", sess, max_age=86400, httponly=True, samesite="lax")
        return resp

    # التحقق من وجود جلسة أدمين أو توكن/باسورد الأدمين الموحد
    admin_sess = request.cookies.get("cm_admin_session", "")
    token = request.cookies.get("cm_subscriber_token", "")
    conn = store.db()
    adm_pw = subs_mod.admin_password(conn)
    conn.close()

    resp = FileResponse(os.path.join(config.FRONTEND_DIR, "admin.html"))
    if token and token == adm_pw and (not admin_sess or admin_sess not in _ADMIN_SESSIONS):
        sess = secrets.token_hex(16)
        _ADMIN_SESSIONS.add(sess)
        resp.set_cookie("cm_admin_session", sess, max_age=86400, httponly=True, samesite="lax")
    return resp


@app.get("/admin/api/session-check")
def admin_session_check(request: Request):
    if is_local_direct_request(request):
        sess = request.cookies.get("cm_admin_session", "")
        if not sess or sess not in _ADMIN_SESSIONS:
            sess = "local_admin_" + secrets.token_hex(8)
            _ADMIN_SESSIONS.add(sess)
        resp = JSONResponse({"ok": True, "session": sess, "is_local": True})
        resp.set_cookie("cm_admin_session", sess, max_age=86400, httponly=True, samesite="lax")
        return resp

    session = request.headers.get("X-Admin-Session", "") or request.cookies.get("cm_admin_session", "")
    token = request.cookies.get("cm_subscriber_token", "")
    conn = store.db()
    adm_pw = subs_mod.admin_password(conn)
    conn.close()

    if (session and session in _ADMIN_SESSIONS) or (token and token == adm_pw):
        if not session or session not in _ADMIN_SESSIONS:
            session = secrets.token_hex(16)
            _ADMIN_SESSIONS.add(session)
        resp = JSONResponse({"ok": True, "session": session, "is_local": False})
        resp.set_cookie("cm_admin_session", session, max_age=86400, httponly=True, samesite="lax")
        return resp
    return {"ok": False, "is_local": False}


@app.post("/admin/api/login")
async def admin_login(request: Request):
    body = await request.json()
    conn = store.db()
    pw = (body.get("password") or "").strip()
    ok = subs_mod.verify_admin(conn, pw)
    if ok:
        conn.close()
        session = secrets.token_hex(16)
        _ADMIN_SESSIONS.add(session)
        resp = JSONResponse({"ok": True, "session": session, "is_admin": True, "redirect": "/admin"})
        resp.set_cookie("cm_admin_session", session, max_age=86400, httponly=True, samesite="lax")
        resp.set_cookie("cm_subscriber_token", pw, max_age=400*86400, httponly=True, samesite="lax")
        return resp

    # فحص إذا كان المُدخل هو توكن مشترك وليس باسورد الأدمن — تسجيل دخوله وتحويله للداشبورد مباشرة
    sub = subs_mod.verify_token(conn, pw)
    conn.close()
    if sub:
        resp = JSONResponse({
            "ok": True,
            "is_subscriber": True,
            "name": sub["name"],
            "redirect": "/",
            "message": f"مرحباً {sub['name']}! جاري نقلك لحسابك..."
        })
        resp.set_cookie("cm_subscriber_token", pw, max_age=400*86400, httponly=True, samesite="lax")
        return resp

    return JSONResponse({"ok": False, "detail": "كلمة المرور أو التوكن غير صحيح"})


def _admin_check(request: Request):
    if is_local_direct_request(request):
        return
    session = request.headers.get("X-Admin-Session", "") or request.cookies.get("cm_admin_session", "")
    if session and session in _ADMIN_SESSIONS:
        return
    conn = store.db()
    try:
        adm_pw = subs_mod.admin_password(conn)
    finally:
        conn.close()
    token = request.cookies.get("cm_subscriber_token") or request.headers.get("X-Subscriber-Token") or ""
    if token and token == adm_pw:
        if session:
            _ADMIN_SESSIONS.add(session)
        return
    raise HTTPException(403, "Admin session required")


@app.get("/admin/api/subscribers")
def admin_list_subs(request: Request):
    _admin_check(request)
    conn = store.db()
    subs = subs_mod.list_subscribers(conn)
    all_rows = store.list_accounts(conn)
    for s in subs:
        s_accs = [r for r in all_rows if is_account_accessible(r, s["name"], False)]
        s["accounts_count"] = len(s_accs)
    conn.close()
    return {"subscribers": subs}


@app.post("/admin/api/subscribers/create")
async def admin_create_sub(request: Request):
    _admin_check(request)
    body = await request.json()
    conn = store.db()
    result = subs_mod.create_subscriber(
        conn,
        body.get("name", ""),
        body.get("days"),
        body.get("notes", ""),
        max_accounts=body.get("max_accounts", 1)
    )
    conn.close()
    return result


@app.post("/admin/api/subscribers/{sub_id}/update")
async def admin_update_sub(sub_id: int, request: Request):
    _admin_check(request)
    body = await request.json()
    conn = store.db()
    result = subs_mod.update_subscriber(conn, sub_id,
        name=body.get("name"), days=body.get("days"), notes=body.get("notes"),
        is_active=body.get("is_active"), max_accounts=body.get("max_accounts"))
    conn.close()
    if not result:
        raise HTTPException(404, "subscriber not found")
    return result


@app.post("/admin/api/subscribers/{sub_id}/extend")
async def admin_extend_sub(sub_id: int, request: Request):
    _admin_check(request)
    body = await request.json()
    conn = store.db()
    result = subs_mod.extend_subscriber(conn, sub_id, body.get("days", 0))
    conn.close()
    if not result:
        raise HTTPException(404, "subscriber not found")
    return result


@app.post("/admin/api/subscribers/{sub_id}/reset-token")
async def admin_reset_token(sub_id: int, request: Request):
    _admin_check(request)
    conn = store.db()
    new_token = subs_mod.reset_token(conn, sub_id)
    conn.close()
    return {"new_token": new_token}


@app.post("/admin/api/subscribers/{sub_id}/delete")
async def admin_delete_sub(sub_id: int, request: Request):
    _admin_check(request)
    conn = store.db()
    subs_mod.delete_subscriber(conn, sub_id)
    conn.close()
    return {"ok": True}


@app.get("/admin/api/subscribers/{sub_id}/view-as")
def admin_view_as(sub_id: int, request: Request):
    """Impersonate a subscriber — sets their token as the browser cookie and redirects to homepage."""
    _admin_check(request)
    conn = store.db()
    subs = subs_mod.list_subscribers(conn)
    conn.close()
    sub = next((s for s in subs if s["id"] == sub_id), None)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    from fastapi.responses import RedirectResponse
    import urllib.parse
    name_enc = urllib.parse.quote(sub["name"])
    resp = RedirectResponse(url="/?view_as=" + name_enc, status_code=302)
    resp.set_cookie("cm_subscriber_token", sub["token"], max_age=400*86400, httponly=True, samesite="lax")
    resp.set_cookie("cm_viewing_subscriber", name_enc, max_age=400*86400, httponly=False, samesite="lax")
    return resp


@app.get("/admin/exit-view-as")
def admin_exit_view_as(request: Request):
    """الخروج من وضع تصفح المشترك والعودة للوحة الأدمن وقائمة المشتركين (للأدمن فقط)."""
    from fastapi.responses import RedirectResponse
    admin_sess = request.cookies.get("cm_admin_session", "")
    token = request.cookies.get("cm_subscriber_token") or ""
    conn = store.db()
    adm_pw = subs_mod.admin_password(conn)
    conn.close()
    is_admin = is_local_direct_request(request) or (admin_sess and admin_sess in _ADMIN_SESSIONS) or (token == adm_pw)
    if not is_admin:
        # حماية أمنية صارمة: أي محاولة دخول لغير الأدمن يتم رفضها فوراً وتوجيهه للرئيسية
        return RedirectResponse(url="/", status_code=302)

    target = request.query_params.get("to") or "/admin"
    resp = RedirectResponse(url=target, status_code=302)
    resp.delete_cookie("cm_viewing_subscriber")
    if not is_local_direct_request(request):
        resp.set_cookie("cm_subscriber_token", adm_pw, max_age=400*86400, httponly=True, samesite="lax")
    return resp


@app.get("/admin/api/config/credentials")
def admin_get_credentials(request: Request):
    _admin_check(request)
    conn = store.db()
    pw = subs_mod.admin_password(conn)
    conn.close()
    return {"ok": True, "admin_password": pw}


@app.post("/admin/api/config/credentials")
async def admin_set_credentials(request: Request):
    _admin_check(request)
    body = await request.json()
    conn = store.db()
    new_pw = (body.get("admin_password") or "").strip()
    if new_pw:
        subs_mod.set_admin_password(conn, new_pw)
    pw = subs_mod.admin_password(conn)
    conn.close()
    resp = JSONResponse({"ok": True, "admin_password": pw})
    if new_pw:
        resp.set_cookie("cm_subscriber_token", new_pw, max_age=400*86400, httponly=True, samesite="lax")
    return resp


# طباعة بيانات الأدمين في الكونسول عند التشغيل
def _print_admin_pw():
    conn = store.db()
    pw = subs_mod.admin_password(conn)
    conn.close()
    print("=" * 60, flush=True)
    print("  🔐 ADMIN PASSWORD: %s" % pw, flush=True)
    print("  📍 Admin panel:    http://127.0.0.1:%d/admin" % config.PORT, flush=True)
    print("=" * 60, flush=True)

_print_admin_pw()

@app.get("/api/status")
def api_status():
    out = sync_mod.status_snapshot()
    out["active_account"] = ACTIVE["account"]
    out["agent"] = _with_conn(lambda conn: store.get_meta(conn, "agent:last", {}) or {})
    out["release"] = _release_public()
    out["queue"] = move_queue.brief()
    return out


@app.get("/api/accounts")
def api_accounts(request: Request):
    def run(conn):
        ident = _caller_identity(request, conn)
        filter_owner = ident["filter_owner"]
        is_admin = ident["is_admin"]
        all_rows = store.list_accounts(conn)

        # تحضير قائمة الحسابات الكلية للنظام (تستخدم للأدمن للربط السريع بالمشتركين)
        all_system_accounts = []
        if is_admin:
            for r in all_rows:
                all_system_accounts.append({
                    "id": r["id"],
                    "name": r["name"],
                    "display_name": r.get("display_name") or r.get("label") or r["name"],
                    "owners": r.get("owner_username") or ""
                })

        if is_admin and not filter_owner:
            # للأدمن بدون تصفح مشترك: لا يتم عرض أي حسابات نهائياً (مخصص لعرض لوحة التحكم وقائمة المشتركين فقط)
            rows = []
            active_name = ""
        else:
            # للمشترك أو الأدمن أثناء تصفح مشترك محدد: حساباته الخاصة بالإضافة للحسابات المشتركة
            rows = [r for r in all_rows if is_account_accessible(r, filter_owner, is_admin)]
            active_rec = store.active_account(conn, owner=filter_owner)
            active_name = active_rec["name"] if active_rec else (rows[0]["name"] if rows else "")

        if active_name:
            ACTIVE["account"] = active_name

        stats_map = {}
        for rec in rows:
            last = store.last_success(conn, rec["name"])
            stats_map[rec["name"]] = {
                "items": conn.execute("SELECT COUNT(*) c FROM items WHERE account=?", (rec["name"],)).fetchone()["c"],
                "last_success": last,
                "age_minutes": round((time.time() - last) / 60, 1) if last else None,
                "stats": store.get_meta(conn, "stats:%s" % rec["name"], {}),
            }
        limits = accounts_mod.profile_limits(conn)
        out = []
        mains = _main_accounts(conn)
        for rec in rows:
            entry = accounts_mod.public(conn, rec, stats_map)
            entry["is_main"] = rec["name"] in mains
            entry.update(stats_map.get(rec["name"], {}))
            out.append(entry)

        profile_info = _profile_from(limits["me"], active_name, conn)
        if filter_owner:
            profile_info["username"] = ident["subscriber_name"] or filter_owner
            profile_info["plan"] = "VIP SUBSCRIBER"
        elif is_admin:
            profile_info["username"] = "Admin"
            profile_info["plan"] = "ADMINISTRATOR"

        sub_limit = None
        if filter_owner:
            s_row = conn.execute("SELECT max_accounts FROM subscribers WHERE LOWER(name)=LOWER(?)", (filter_owner,)).fetchone()
            if s_row:
                sub_limit = s_row[0] or 1

        subscribers_summary = []
        if ident["is_admin"]:
            subs = subs_mod.list_subscribers(conn)
            for s in subs:
                s_accs = [r for r in all_rows if is_account_accessible(r, s["name"], False)]
                subscribers_summary.append({
                    "id": s["id"],
                    "name": s["name"],
                    "accounts_count": len(s_accs),
                    "max_accounts": s.get("max_accounts", 1),
                    "accounts": [a["display_name"] or a["name"] for a in s_accs]
                })

        return {"accounts": out, "active": active_name,
                "capacity": {"used": len(out), "limit": sub_limit if sub_limit is not None else limits["limit"]},
                "profile": profile_info,
                "subscriber": filter_owner or None,
                "viewing_as": (ident["viewing_as"] or "") if ident["is_admin"] else "",
                "is_admin": bool(ident["is_admin"]),
                "subscribers": subscribers_summary,
                "all_system_accounts": all_system_accounts}
    return _with_conn(run)


def _profile_from(me, account=None, conn=None):
    """شكل بلوك المستخدم في الهيدر. من غير Rampart: الهوية محلية باسم الحساب النشط.

    المفتاح الداخلي في القاعدة (RAIDERxxxxx) بيستخدم للصفوف والعزل، لكن الهيدر بيعرض
    الاسم الحقيقي اللي اتسجّل (display_name) لو موجود — عشان ما تظهرش تسمية مشتقة مكان الاسم.
    """
    label = account or "LOCAL"
    if conn is not None and account:
        rec = store.get_account(conn, account)
        if rec:
            label = rec.get("display_name") or rec.get("label") or account
    if not me:
        return {"username": label, "plan": "PIONEER DIRECT", "avatar": None,
                "role": "local", "has_access": True, "unnamed": bool(
                    re.match(r"^(RAIDER|ACCOUNT)\s*[0-9]+$", str(label).replace(" ", "")))}
    plan = (me.get("plan") or {}).get("name") or ""
    label = "FREE" if me.get("is_free_tier") else ("LIFETIME" if not me.get("plan_expires_at") and me.get("has_access")
                                                   else plan.upper() or "BASIC")
    did, avatar = str(me.get("discord_id") or ""), me.get("avatar")
    avatar_url = ("https://cdn.discordapp.com/avatars/%s/%s.png" % (did, avatar)) if (did and avatar) \
        else "https://cdn.discordapp.com/embed/avatars/%d.png" % (int(did or 0) % 5)
    return {"username": me.get("username"), "plan": label, "avatar": avatar_url, "role": me.get("role"),
            "has_access": bool(me.get("has_access")), "status": me.get("status"),
            "account_limit": me.get("account_limit"), "current_account_count": me.get("current_account_count")}


@app.get("/api/profile")
def api_profile(request: Request, account: str = ""):
    """بيانات الهيدر: الهوية + العملات الثلاثة + المستوى، للحساب اللي في التاب ده."""
    def run(conn):
        ident = _caller_identity(request, conn)
        filter_owner = ident["filter_owner"]
        is_admin = ident["is_admin"]
        if is_admin and not filter_owner:
            return {
                "profile": {"username": "Admin", "plan": "ADMINISTRATOR", "avatar": None, "role": "admin", "has_access": True},
                "account": "",
                "capacity": {"used": 0, "limit": None},
                "wallet": {}, "xp": 0, "level": 1,
                "refresh_seconds": config.REFRESH_SECONDS
            }
        name = _accessible_account(account, request, conn)
        limits = accounts_mod.profile_limits(conn)
        wallet = accounts_mod.wallet(conn, name) if name else {"stats": {}, "xp": 0, "level": 1}
        profile = _profile_from(limits["me"], name, conn)
        if filter_owner:
            profile["username"] = ident["subscriber_name"] or filter_owner
            profile["plan"] = "VIP SUBSCRIBER"
        return {"profile": profile, "account": name,
                "capacity": {"used": limits["count"], "limit": limits["limit"]},
                "wallet": wallet.get("stats") or {}, "xp": wallet.get("xp") or 0, "level": wallet.get("level") or 1,
                "refresh_seconds": config.REFRESH_SECONDS}
    return _with_conn(run)


@app.post("/api/accounts/add")
def api_account_add(request: Request, body: dict = None):
    body = body or {}
    conn = store.db()
    try:
        ident = _caller_identity(request, conn)
    finally:
        conn.close()

    owner = (ident.get("filter_owner") or "").strip() or None
    # If the caller is admin and provided owner in body or query, respect it
    if ident.get("is_admin"):
        override = (body.get("owner") or body.get("subscriber") or request.query_params.get("view_as") or request.query_params.get("subscriber") or "").strip()
        if override:
            owner = override

    if owner:
        conn = store.db()
        s_row = conn.execute("SELECT max_accounts FROM subscribers WHERE LOWER(name)=LOWER(?)", (owner,)).fetchone()
        if s_row:
            max_acc = s_row[0] or 1
            all_current = [r for r in store.list_accounts(conn) if is_account_accessible(r, owner, False)]
            token_norm = accounts_mod.normalize_token((body.get("token") or "").strip())
            already_has = any(r.get("token") == token_norm for r in all_current)
            if not already_has and len(all_current) >= max_acc:
                conn.close()
                raise HTTPException(400, f"عفواً، لقد تم الوصول للحد الأقصى لعدد الحسابات المسموح به لهذا المشترك ({len(all_current)}/{max_acc} حساب). يرجى زيادة الحد من لوحة الأدمن أولاً.")
        conn.close()

    try:
        rec, note = _with_conn(lambda conn: accounts_mod.add(
            conn, body.get("token") or "", body.get("label") or "", bool(body.get("link_upstream")), owner=owner))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except rampart_client.UpstreamError as e:
        raise HTTPException(502, str(e))
    with _lock:
        conn = store.db()
        pulled = None
        if rec.get("token") and (config.DATA_SOURCE == "pioneer" or rec.get("linked_upstream")):
            # الحساب المحلي بالتوكن بتاعه بيتسحب منه على طول — أول نسخة من المخزن بتتخزن دلوقتي.
            pulled = sync_mod.pull_account(conn, rec["name"], rec["id"], with_assets=False)
        if pulled and pulled.get("ok"):
            store.set_meta(conn, "stats:%s" % rec["name"], pulled.get("stats") or {})
            store.upsert_account(conn, {"id": rec["id"], "display_name": rec["display_name"]})
        out = accounts_mod.public(conn, store.get_account(conn, rec["id"]) or rec)
        conn.close()
    return {"account": out, "note": note, "pulled": pulled}


def _is_agent_authorized(request: Request) -> bool:
    sub_tok = (request.headers.get("X-Subscriber-Token") or "").strip()
    if sub_tok:
        conn = store.db()
        subs_mod._ensure_tables(conn)
        sub = subs_mod.verify_token(conn, sub_tok)
        adm_tok = subs_mod.admin_token(conn)
        conn.close()
        if sub or sub_tok == adm_tok:
            return True
    return agent_link.authorized(request, request.headers.get("X-Fahmy-Agent"))


@app.post("/api/accounts/auto")
def api_account_auto(request: Request, body: dict = None):
    """مدخل الأجن (CMSync): توكن اللعبة يسجّل/يتحدّث أوتوماتيك ثم يسحب قراءة فورية.

    يقبل:
      1) X-Subscriber-Token لمشتركي الخدمة (برنامج CMSync لدى المشترك).
      2) X-Fahmy-Agent + loopback للأدمن المحلي.
    """
    body = body or {}
    sub_token = (request.headers.get("X-Subscriber-Token") or body.get("subscriber_token") or "").strip()
    agent_hdr = request.headers.get("X-Fahmy-Agent")
    owner = None

    if sub_token:
        conn = store.db()
        subs_mod._ensure_tables(conn)
        adm_tok = subs_mod.admin_token(conn)
        if sub_token == adm_tok:
            owner = None
        else:
            sub = subs_mod.verify_token(conn, sub_token)
            if not sub:
                conn.close()
                raise HTTPException(401, "Invalid or expired subscriber token")
            owner = sub["name"]
        conn.close()
    elif agent_link.authorized(request, agent_hdr):
        owner = None
    else:
        raise HTTPException(403, "Agent not authorized (subscriber token or loopback secret required)")

    game_token = body.get("token") or ""
    try:
        rec, note, created = _with_conn(lambda conn: accounts_mod.auto_upsert(conn, game_token, owner=owner))
    except ValueError as e:
        raise HTTPException(400, str(e))
    pulled = None
    with _lock:
        conn = store.db()
        try:
            if rec.get("token"):
                pulled = sync_mod.pull_account(conn, rec["name"], rec["id"], with_assets=False)
                if pulled and pulled.get("ok"):
                    store.set_meta(conn, "stats:%s" % rec["name"], pulled.get("stats") or {})
                store.upsert_account(conn, {"id": rec["id"], "last_sync": time.time()})
            store.set_meta(conn, "agent:last", {"account": rec["name"], "at": time.time(),
                                                "created": created, "note": note,
                                                "owner": owner,
                                                "exp": float(rec.get("token_exp") or 0)})
            out = accounts_mod.public(conn, store.get_account(conn, rec["id"]) or rec)
        finally:
            conn.close()
    return {"account": out, "note": note, "created": created, "owner": owner,
            "pulled": {"ok": bool(pulled and pulled.get("ok")), "error": (pulled or {}).get("error")}}


@app.get("/api/agent/handshake")
def api_agent_handshake(request: Request):
    """بيوصّل الأجن بمفتاح الجهاز ومجلد المشروع — من 127.0.0.1 بس، ومن غير أي مفتاح."""
    if not agent_link.is_local(request):
        raise HTTPException(403, "loopback only")
    return {"key": agent_link.secret(), "project": config.ROOT, "data_source": config.DATA_SOURCE,
            "secret_file": agent_link.SECRET_FILE}


@app.post("/api/agent/manifest")
def api_agent_manifest(request: Request):
    """الأجن بيقول للوحة اسأل البوابة على رقم المانيفست الحي وحفظه.

    الباتش بينزل من السيرفر نفسه، فالسؤال بـ build فاضي بيدي الرقم الجديد من غير
    أي قراءة لذاكرة اللعبة — واللوحة بتقرا الملف لكل طلب فمفيش إعادة تشغيل.
    """
    if not _is_agent_authorized(request):
        raise HTTPException(403, "agent authorization required")
    before = pioneer_client.load_manifest()
    try:
        fresh = pioneer_client.refetch_manifest()
    except pioneer_client.PioneerError as exc:
        raise HTTPException(502, str(exc))
    status, detail = pioneer_client.validate_manifest(fresh)
    return {"old": before, "manifest_id": fresh, "changed": fresh != before,
            "read": status, "detail": detail}


def _release_public():
    """وصف النسخة من غير مسار القرص — المسار ملك السيرفر ومش لازم يوصل للمتصفح."""
    info = agent_release.brief()
    info.pop("path", None)
    return info


@app.get("/api/agent/release")
def api_agent_release(request: Request):
    """الأجن بيسأل: إيه النسخة المتاحة على السيرفر؟ البصمة بتقول فيه تحديث ولا لأ."""
    if not _is_agent_authorized(request):
        raise HTTPException(403, "agent authorization required")
    return agent_release.brief()


@app.get("/api/agent/release/file")
def api_agent_release_file(request: Request):
    """الملف نفسه للأجن — بمفتاح الجهاز، فالزرار يحدّث من غير ما حد يلصق لينك."""
    if not _is_agent_authorized(request):
        raise HTTPException(403, "agent authorization required")
    info = agent_release.brief()
    if not info["present"]:
        raise HTTPException(404, "no CMSync.exe on the server")
    return FileResponse(info["path"], media_type="application/octet-stream",
                        filename=info["filename"])


@app.get("/download/cmsync")
def download_cmsync():
    """لينك التحميل اللي في الإعدادات — مقفول بكوكي الدخول، فبيتنقل للحسابات اللوجِن."""
    info = agent_release.brief()
    if not info["present"]:
        raise HTTPException(404, "No CMSync.exe on this server.")
    return FileResponse(info["path"], media_type="application/octet-stream",
                        filename=info["filename"])


@app.post("/api/accounts/{account_id}/link")
def api_account_link(account_id):
    """ربط حساب محفوظ محلياً على Rampart (بروفايل فقط — مش بيلمس أي عنصر في المخزن)."""
    try:
        rec, note = _with_conn(lambda conn: accounts_mod.link(conn, account_id))
    except KeyError:
        raise HTTPException(404, "unknown account")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except rampart_client.UpstreamError as e:
        raise HTTPException(502, str(e))
    with _lock:
        conn = store.db()
        pulled = sync_mod.pull_account(conn, rec["name"], rec["id"], with_assets=False)
        if pulled.get("ok"):
            store.set_meta(conn, "stats:%s" % rec["name"], pulled.get("stats") or {})
        out = accounts_mod.public(conn, store.get_account(conn, rec["id"]) or rec)
        conn.close()
    return {"account": out, "note": note, "pulled": pulled}


@app.patch("/api/accounts/{account_id}")
def api_account_edit(account_id, body: dict):
    body = body or {}
    try:
        rec, note = _with_conn(lambda conn: accounts_mod.edit(
            conn, account_id, label=body.get("label"), raw_token=body.get("token"),
            push_upstream=bool(body.get("push_upstream"))))
    except KeyError:
        raise HTTPException(404, "unknown account")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except rampart_client.UpstreamError as e:
        raise HTTPException(502, str(e))
    return {"account": _with_conn(lambda conn: accounts_mod.public(conn, rec)), "note": note}


@app.delete("/api/accounts/{account_id}")
def api_account_delete(account_id, request: Request, unlink: int = 0):
    conn = store.db()
    try:
        ident = _caller_identity(request, conn)
        rec = store.get_account(conn, account_id)
        if not rec:
            raise HTTPException(404, "unknown account")

        filter_owner = ident.get("filter_owner") or ""
        # لو الحذف جاي من وضع تصفح مشترك أو من مشترك: بنشيل الحساب من بروفايله فقط، ويفضل شغال عند الباقيين!
        if filter_owner:
            existing_owners_raw = (rec.get("owner_username") or "").strip()
            owners_list = [o.strip() for o in existing_owners_raw.split(",") if o.strip()]
            new_owners = [o for o in owners_list if o.lower() != filter_owner.lower()]
            if len(new_owners) != len(owners_list):
                new_owner_str = ", ".join(new_owners)
                store.upsert_account(conn, {"id": rec["id"], "owner_username": new_owner_str})
                conn.commit()
                return {
                    "ok": True,
                    "removed": rec["id"],
                    "name": rec["name"],
                    "note": f"تمت إزالة الحساب من بروفايل ({filter_owner}) — الحساب ما زال متاحاً في باقي البروفايلات",
                    "active": ""
                }
            else:
                return {
                    "ok": True,
                    "removed": rec["id"],
                    "name": rec["name"],
                    "note": f"تمت إزالة الحساب من قائمة ({filter_owner})",
                    "active": ""
                }

        # لو أدمن عام خارج تصفح أي مشترك: حذف كلي من القاعدة
        out = accounts_mod.remove(conn, account_id, unlink_upstream=bool(unlink))
        conn.commit()
        return out
    finally:
        conn.close()


@app.post("/api/accounts/{account_id}/assign-owner")
async def api_account_assign_owner(account_id: str, request: Request):
    """ربط حساب لعبة مسجل مسبقاً في النظام ببروفايل مشترك محدد."""
    conn = store.db()
    try:
        ident = _caller_identity(request, conn)
        if not ident["is_admin"]:
            raise HTTPException(403, "Admin access required")
        body = await request.json()
        target_owner = (body.get("owner") or ident.get("filter_owner") or "").strip()
        if not target_owner:
            raise HTTPException(400, "owner is required")

        rec = store.get_account(conn, account_id)
        if not rec:
            raise HTTPException(404, "Account not found")

        s_row = conn.execute("SELECT max_accounts FROM subscribers WHERE LOWER(name)=LOWER(?)", (target_owner,)).fetchone()
        if s_row:
            max_acc = s_row[0] or 1
            all_current = [r for r in store.list_accounts(conn) if is_account_accessible(r, target_owner, False)]
            already_has = any(r["id"] == rec["id"] for r in all_current)
            if not already_has and len(all_current) >= max_acc:
                raise HTTPException(400, f"عفواً، لقد تم الوصول للحد الأقصى لعدد الحسابات المسموح به لهذا المشترك ({len(all_current)}/{max_acc} حساب). يرجى زيادة الحد من لوحة الأدمن أولاً.")

        existing_owners_raw = (rec.get("owner_username") or "").strip()
        owners_list = [o.strip() for o in existing_owners_raw.split(",") if o.strip()]
        if not any(o.lower() == target_owner.lower() for o in owners_list):
            owners_list.append(target_owner)
            new_owner_str = ", ".join(owners_list)
            store.upsert_account(conn, {"id": rec["id"], "owner_username": new_owner_str, "is_active": 1})
            conn.commit()
        return {"ok": True, "account_id": rec["id"], "name": rec["name"], "owners": rec.get("owner_username")}
    finally:
        conn.close()


@app.post("/api/accounts/{account_id}/select")
def api_account_select(account_id):
    def run(conn):
        try:
            rec = accounts_mod.select(conn, account_id)
        except KeyError:
            raise HTTPException(404, "unknown account")
        ACTIVE["account"] = rec["name"]
        return {"active": rec["name"], "account": accounts_mod.public(conn, rec)}
    return _with_conn(run)


@app.get("/api/accounts/{account_id}/token")
def api_account_token(account_id):
    """التوكن الكامل — ما يسيبش قائمة الحسابات، ويُطلب فقط عند زر النسخ."""
    rec = _with_conn(lambda conn: store.get_account(conn, account_id))
    if not rec:
        raise HTTPException(404, "unknown account")
    return {"id": rec["id"], "token": rec.get("token") or ""}


@app.post("/api/accounts/{account_id}/refresh")
def api_account_refresh(account_id):
    """زر التحديث في كارت الحساب: سحب قراءة فقط للحساب ده (GET /inventory/parsed)."""
    rec = _with_conn(lambda conn: store.get_account(conn, account_id))
    if not rec:
        raise HTTPException(404, "unknown account")
    if config.DATA_SOURCE == "pioneer":
        if not rec.get("token"):
            raise HTTPException(400, "No Embark token is saved for this account — update the token first.")
    elif not rec.get("linked_upstream"):
        return {"account": rec["name"], "ok": False, "error": "not_linked",
                "detail": "This account is local only — link it on Rampart first so it can be pulled."}
    with _lock:
        conn = store.db()
        res = sync_mod.pull_account(conn, rec["name"], rec["id"])
        if res.get("ok"):
            store.set_meta(conn, "stats:%s" % rec["name"], res.get("stats") or {})
            conn.execute("UPDATE accounts SET last_sync=? WHERE id=?", (time.time(), rec["id"]))
            conn.commit()
        conn.close()
    return res


@app.post("/local/activate/{account}")
def activate(account):
    def run(conn):
        rec = store.get_account(conn, account)
        if not rec:
            raise HTTPException(404, "unknown account")
        accounts_mod.select(conn, rec["id"])
        ACTIVE["account"] = rec["name"]
        return {"active": rec["name"]}
    return _with_conn(run)


@app.post("/api/refresh")
def api_refresh():
    return _refresh_guarded()


def _rows(conn, account):
    """عناصر حساب واحد — مفيش قراءة بتلمّ كل الحسابات في بعض."""
    return [dict(r) for r in conn.execute("SELECT * FROM items WHERE account=?", (account,)).fetchall()]


@app.get("/api/filters")
def api_filters(account: str = Query("ALL")):
    account = _one_account(account)
    conn = store.db()
    rows = _rows(conn, account)
    groups = catalog.group_counts(conn, account)
    conn.close()
    cats, rar, typ = {}, {}, {}
    for r in rows:
        for c in (json.loads(r["category"] or "[]")):
            cats[c] = cats.get(c, 0) + 1
        rar[r["rarity"]] = rar.get(r["rarity"], 0) + 1
        typ[r["type"]] = typ.get(r["type"], 0) + 1
    return {"categories": sorted(cats), "rarities": sorted(rar), "types": sorted(typ),
            "counts": {"categories": cats, "rarities": rar, "types": typ},
            "groups": groups}


@app.get("/api/items")
def api_items(q: str = "", account: str = "ALL", category: str = "", rarity: str = "", item_type: str = "",
              stacked: bool = True, sort: str = "name", limit: int = 0, offset: int = 0):
    account = _one_account(account)
    conn = store.db()
    rows = _rows(conn, account)
    conn.close()

    merged = {}
    for r in rows:
        entry = merged.setdefault(r["name"], {
            "name": r["name"], "qty": 0, "rarity": r["rarity"], "type": r["type"],
            "category": json.loads(r["category"] or "[]"), "value": r["value"] or 0,
            "image": r["image"], "level": r["level"], "instances": 0, "per_account": {}, "containers": set()})
        entry["per_account"][account] = entry["per_account"].get(account, 0) + r["qty"]
        entry["instances"] += 1
        entry["containers"].add(r["container"])

    out = []
    needle = q.strip().lower()
    for name, e in merged.items():
        e["qty"] = max(e["per_account"].values()) if e["per_account"] else 0
        e["sum_qty"] = sum(e["per_account"].values())
        e["total_value"] = (e["value"] or 0) * e["qty"]
        e["label"] = ("%s %s" % (e["rarity"], e["type"])).strip().upper()
        e["containers"] = sorted(e["containers"])
        if needle and needle not in name.lower():
            continue
        if category and category not in e["category"]:
            continue
        if rarity and e["rarity"].lower() != rarity.lower():
            continue
        if item_type and e["type"].lower() != item_type.lower():
            continue
        out.append(e)

    key = {"name": lambda e: e["name"].lower(), "qty": lambda e: -e["qty"],
           "value": lambda e: -(e["total_value"] or 0), "rarity": lambda e: e["rarity"]}.get(sort, lambda e: e["name"].lower())
    out.sort(key=key)
    total = len(out)
    if limit:
        out = out[offset:offset + limit]
    return {"total": total, "returned": len(out), "account": account, "stacked": stacked, "items": out}


@app.get("/api/inventory")
def api_inventory(account: str = "ALL"):
    """{اسم: كمية} للحساب المطلوب — حساب واحد بس، بدون دمج عبر الحسابات."""
    account = _one_account(account)
    conn = store.db()
    rows = _rows(conn, account)
    conn.close()
    merged = {}
    for r in rows:
        merged[r["name"]] = merged.get(r["name"], 0) + r["qty"]
    return {"account": account, "count": len(merged), "quantities": merged}


@app.get("/inventory/parsed")
def inventory_parsed():
    """إعادة تقديم الـ payload الخام للحساب النشط — نفس شكل rampart بالحرف."""
    conn = store.db()
    payload, fetched = store.read_snapshot(conn, ACTIVE["account"])
    conn.close()
    if payload is None:
        raise HTTPException(503, "no local snapshot for %s yet" % ACTIVE["account"])
    resp = JSONResponse(payload)
    resp.headers["X-Local-Mirror"] = "1"
    resp.headers["X-Snapshot-Age-Minutes"] = str(round((time.time() - (fetched or 0)) / 60, 1))
    resp.headers["X-Account"] = ACTIVE["account"]
    return resp


@app.get("/auth/embark")
def embark_list():
    """قائمة الحسابات من المحلي (نفس شكل rampart، بدون أي طلب للمنبع)."""
    def run(conn):
        _sync_active_name(conn)
        return [{"id": r["id"], "label": r.get("label") or r["name"],
                 "platform": r.get("platform") or "steam",
                 "is_active": bool(r.get("is_active")), "is_expired": accounts_mod.is_expired(r),
                 "is_restricted": bool(r.get("is_restricted")),
                 "display_name": r.get("display_name") or r["name"], "embark_id": r.get("embark_id"),
                 "email": r.get("email"), "third_party_name": r.get("third_party_name"),
                 "third_party_user_id": r.get("third_party_user_id"), "token": r.get("token") or "",
                 "token_expiry": r.get("token_exp"), "added_at": r.get("added_at"),
                 "updated_at": r.get("updated_at")}
                for r in store.list_accounts(conn, enabled_only=True)]
    return _with_conn(run)


@app.get("/traders/offers")
def traders_offers():
    conn = store.db()
    payload = store.get_meta(conn, "traders:%s" % ACTIVE["account"])
    conn.close()
    if payload is None:
        raise HTTPException(503, "no local traders snapshot for %s" % ACTIVE["account"])
    return JSONResponse(payload)


@app.get("/api/traders")
def api_traders(account: str = ""):
    def run(conn):
        name = account or _sync_active_name(conn)
        return traders_mod.view(conn, name)
    return _with_conn(run)


@app.post("/api/traders/plan")
def api_traders_plan(body: dict):
    """يضيف/يعدّل/يشيل بند في قائمة شراء الحساب (الشراء نفسه جوه اللعبة)."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    out = _with_conn(lambda conn: traders_mod.edit_plan(
        conn, name, offer_id=body.get("offer_id"), amount=body.get("amount"),
        action=body.get("action") or "add"))
    return JSONResponse(out)


@app.post("/api/traders/buy")
def api_traders_buy(body: dict):
    """ينفّذ عرض تجار عبر بوابة Pioneer الرسمية بعد تأكيد المستخدم وقفل الكتابة."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    out = _with_conn(lambda conn: traders_mod.buy(
        conn, name, body.get("offer_id"), body.get("amount"),
        confirmed=bool(body.get("confirmed"))))
    return JSONResponse(out)


@app.get("/api/workshop")
def api_workshop(account: str = ""):
    """وصفات الصناعة + حالة خامات مخزن الحساب + قائمة التصنيع المحفوظة."""
    def run(conn):
        name = account or _sync_active_name(conn)
        return workshop.view(conn, name)
    return _with_conn(run)


@app.post("/api/workshop/plan")
def api_workshop_plan(body: dict):
    """يضيف/يعدّل/يشيل بند في قائمة تصنيع الحساب (للوصفات اللي مالهاش رقم عرض رسمي)."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    out = _with_conn(lambda conn: workshop.edit_plan(
        conn, name, slug=body.get("slug"), amount=body.get("amount"),
        action=body.get("action") or "add"))
    return JSONResponse(out)


@app.post("/api/workshop/craft")
def api_workshop_craft(body: dict):
    """ينفّذ تصنيع وصفة عبر بوابة Pioneer الرسمية بعد تأكيد المستخدم وقفل الكتابة."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    out = _with_conn(lambda conn: workshop.craft(
        conn, name, body.get("slug"), body.get("amount"),
        confirmed=bool(body.get("confirmed"))))
    return JSONResponse(out)


@app.get("/api/workshop/blueprints")
def api_workshop_blueprints(account: str = ""):
    """شاشة المخطوطات الـ 91: حالة التفعيل المستنتجة من مخزن الحساب + مستويات المحطات."""
    def run(conn):
        name = account or _sync_active_name(conn)
        return workshop.blueprint_board(conn, name)
    return _with_conn(run)


@app.post("/api/workshop/knowledge")
def api_workshop_knowledge(body: dict):
    """تحديد يدوي لمخطوطة أو مستوى محطة — محلي بالكامل وبدون بوابة."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    if body.get("station"):
        out = _with_conn(lambda conn: knowledge.set_station_level(
            conn, name, body.get("station"), body.get("level")))
    else:
        out = _with_conn(lambda conn: knowledge.mark(
            conn, name, body.get("target"), body.get("state")))
    return JSONResponse(out)


@app.get("/api/traders/catalog")
def api_traders_catalog(rebuild: int = 0):
    """الكتالوج المحلي (data/traders_catalog.json) — rebuild=1 يعيد بناءه من snapshots الحالية."""
    def run(conn):
        data = traders_mod.build_catalog(conn) if rebuild else traders_mod.load_catalog(conn)
        return {"file": traders_mod.CATALOG_FILE, "version": data.get("version"),
                "generated_at": data.get("generated_at"),
                "traders": [{"name": t["name"], "trades": t["trades"]} for t in data.get("traders") or []]}
    return _with_conn(run)


# ------------------------------------------------------------------ إدارة تفاعلية
EQUIPPED_CONTAINERS = ("gun_1", "gun_2", "shield", "augment", "quick_use", "safe_pocket")


DECOR_STAMP = "rarity-fallback-2"


def _file_stamp(path):
    try:
        return "%s:%s" % (os.path.basename(path), int(os.path.getmtime(path)))
    except OSError:
        return ""


def _sections_tag(conn, account):
    """بصمة نسخة ردّ المخزن. بنhash السنابشوت نفسه (مش طابعه الزمني) عشان السينك
    الدوري اللي ما يتغيرش فيه حاجة يفضل بنفس البصمة فيرجّع 304 بدل الميجابايتات،
    ومع أي نقل أو تعديل تجهيز أو ماركة البصمة بتتغير."""
    digest = hashlib.sha1()
    path = store.latest_snapshot_path(conn, account)
    if path:
        try:
            with gzip.open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(b"unreadable-snapshot")
    # القوالب مشتركة بين الحسابات، فأي حفظ/تعديل اسم في تاب يكسر كاش التابات التانية.
    lod = conn.execute("SELECT COALESCE(MAX(rowid), 0) AS r, COALESCE(MAX(updated_at), 0) AS u FROM loadouts"
                       ).fetchone()
    marks = conn.execute("SELECT COUNT(*) AS c, COALESCE(MAX(rowid), 0) AS r FROM marks WHERE account=?",
                         (account,)).fetchone()
    # الرد مبيبناش على حالة الداتابيس بس: أي تغيير في طريقة التزيين أو في الكتالوج
    # لازم يكسر الكاش، غير كده المتصفح يفضل ماسك نسخة 304 قديمة.
    digest.update(("|%s|%s|%s|%s|%s|%s|%s|%s" % (lod["r"], lod["u"], marks["c"], marks["r"],
                                              json.dumps(writer.status(), sort_keys=True, default=str),
                                              DECOR_STAMP,
                                              _file_stamp(catalog.CATALOG_FILE) + _file_stamp(catalog.ARCTRACKER_FILE),
                                              _file_stamp(catalog.asset_meta.FILE)))
                  .encode("utf-8"))
    return digest.hexdigest()[:16]


@app.get("/api/sections")
def api_sections(request: Request, account: str = "ALL"):
    """تقسيم المخزن لأعمدة: STASH / BACKPACK / OVERFLOW + المُرتدى (EQUIPPED)."""
    conn = store.db()
    target = _accessible_account(account, request, conn)
    tag = '"%s"' % _sections_tag(conn, target)
    client_tag = str(request.headers.get("if-none-match") or "").replace("W/", "").strip()
    if client_tag == tag:
        conn.close()
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "no-cache"})
    groups = actions.sections(conn, target)
    payload, _ = store.read_snapshot(conn, target)
    empties = actions.empty_wrappers(payload)
    capacity = {"stash": len((payload or {}).get("stash") or []),
                "overflow": len((payload or {}).get("overflow") or []),
                "backpack": len((payload or {}).get("backpack") or []),
                "equipped": sum(len(v or []) for k, v in ((payload or {}).get("containers") or {}).items()
                                if k not in ("stash", "backpack"))}
    try:
        loadout = loadouts.state(conn, target)
    except Exception as exc:  # لا تعطّل المخزن لو snapshot ناقص
        loadout = {"error": str(exc)[:200], "slots": {}, "capacity": {},
                   "saved": store.list_loadouts(conn)}
    for slots in (loadout.get("slots") or {}).values():
        for slot in slots or []:
            if slot.get("item"):
                catalog.decorate(slot["item"])
    # لو الربط التلقائي حدّث السنابشوت أثناء البناء، البصمة بتتاع آخر لحظة هي الصحيحة
    tag = '"%s"' % _sections_tag(conn, target)
    unlocked = knowledge.unlocked_index(conn, target)
    conn.close()
    out = {}
    for key, bucket in groups.items():
        bucket["equipped"] = key in EQUIPPED_CONTAINERS
        bucket["capacity"] = capacity.get(key)
        bucket["empty_wrappers"] = empties.get(key) or []
        out[key] = bucket
    return JSONResponse({"account": target, "sections": out, "loadout": loadout,
                         "unlocked": unlocked,
                         "locations": (payload or {}).get("locations") or {},
                         "augments": augments.public(), "writes": writer.status()},
                        headers={"ETag": tag, "Cache-Control": "no-cache"})


@app.get("/api/augments")
def api_augments():
    return augments.public()


@app.get("/api/catalog/search")
def api_catalog_search(q: str = ""):
    """كل عناصر اللعبة بالاسم (كاش arctracker المحلي) — للنتائج اللي مش في المخزن."""
    return JSONResponse({"q": q, "results": catalog.search(q)})


def _acc_short(rec):
    """G18 من G18#8940 — الاسم المختصر اللي بيتكتب على البلاطة، من غير الهاشتاج."""
    text = str(rec["display_name"] or rec["label"] or rec["name"] or "").strip()
    return (text.split("#")[0].strip() or text)


@app.post("/api/item/cross")
def api_item_cross(body: dict):
    """قطعك **إنت** اللي نفس الـ instance id بتاعها موجود في حساب تاني — بشارات الحسابات.

    القسم ده مش بلاطات أجنبية: بنرجّع سطور حسابك النشطة (بتشبه البحث) اللي `instance_id`
    بتاعها موجود في حساب مفعّل واحد على الأقل غيره، ومعاها في كل سطر `others` — عدد
    القطع/الخانات من نفس الـ id في كل حساب تاني. يعني اللي بيترسم في الواجهة بيبقى
    قطعه هو: تتحدد وتسحب للشنطة وتبيعها، والشارة بتقول «موجودين كام وفي كام حساب».
    مفيش `wrapper_id` ولا توكن ولا مفتاح حساب محذوف/مقفل بيطلع من هنا."""
    body = body or {}
    needle = str(body.get("q") or "").strip()
    current = _one_account(body.get("account") or "")
    limit = min(int(body.get("limit") or 400), 1000)
    if not needle:
        return JSONResponse({"account": current, "rows": [], "total": 0, "shown": 0})

    def run(conn):
        like = "%" + needle.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        mine = conn.execute(
            "SELECT * FROM instances WHERE account = ? AND (lower(name) LIKE ? ESCAPE '\\' "
            "OR lower(type) LIKE ? ESCAPE '\\') ORDER BY name LIMIT ?",
            (current, like, like, limit)).fetchall()
        # كميات نفس الـ id في الحسابات التانية المفعّلة — بس دي اللي بتعمل الشارة.
        counts = {}
        for r in conn.execute(
                "SELECT i.instance_id iid, a.name aname, a.label alabel, a.display_name adisplay, "
                "SUM(i.qty) qty, COUNT(*) cells "
                "FROM instances i JOIN accounts a ON a.name = i.account "
                "WHERE a.enabled = 1 AND i.account <> ? "
                "AND i.instance_id IN (SELECT instance_id FROM instances WHERE account = ?) "
                "GROUP BY i.instance_id, i.account", (current, current)):
            who = _acc_short({"name": r["aname"], "label": r["alabel"],
                              "display_name": r["adisplay"]})
            if not who:
                continue  # حساب محذوف/مقفل — ما نعرضش مفتاحه الخام
            counts.setdefault(r["iid"], []).append(
                {"label": who, "qty": int(r["qty"] or 0), "cells": int(r["cells"] or 0)})
        out = []
        for r in mine:
            others = counts.get(r["instance_id"])
            if not others:
                continue  # القطعة دي وحيدة — مكانها القسم الأول بس
            row = dict(r)
            try:
                row["attachments"] = json.loads(row.get("attachments") or "[]")
            except (TypeError, ValueError):
                row["attachments"] = []
            catalog.decorate(row)
            row["others"] = sorted(others, key=lambda x: x["label"].lower())
            out.append(row)
        return {"account": current, "q": needle, "rows": out, "total": len(out),
                "shown": len(out)}

    return JSONResponse(_with_conn(run))


@app.post("/api/item/dupes")
def api_item_dupes(body: dict):
    """قطع حسابك إنت اللي نفس الـ instance id بتاعها موجود في حساب تاني.

    دي القائمة الخطرة: القطعة دي لو اتنقلت لحساب تاني بتختفي (الـ id بيتكرر).
    بنرجّع آيدز حسابك انت بس + أسماء الحسابات التانية اللي بيشاركوك نفس الـ id،
    فالواجهة تقدر تفلترها وتحددها وتنقلها للشنطة — توكنك بيقدر على قطعك إنت."""
    current = _one_account((body or {}).get("account") or "")

    def run(conn):
        rows = conn.execute(
            "SELECT i.instance_id, a.name, a.label, a.display_name "
            "FROM instances i JOIN accounts a ON a.name = i.account "
            "WHERE a.enabled = 1 AND i.account <> ? "
            "AND i.instance_id IN (SELECT instance_id FROM instances WHERE account = ?)",
            (current, current)).fetchall()
        labels = {}
        for r in rows:
            who = _acc_short(r)
            if who:
                labels.setdefault(r["instance_id"], set()).add(who)
        return {"account": current,
                "map": {k: sorted(v, key=str.lower) for k, v in labels.items()}}

    return JSONResponse(_with_conn(run))


MAIN_ACCOUNTS_FILE = os.path.join(config.DATA_DIR, "main_accounts.json")


def _main_accounts(conn):
    """الحسابات الأساسية اللي بنفضّي الباقي عليها — data/main_accounts.json.
    الحساب المحذوف أو المقفل بيسقط تلقائياً، فمفيش قائمة بتتكلم عن حساب مش موجود."""
    try:
        with open(MAIN_ACCOUNTS_FILE, encoding="utf-8") as fh:
            wanted = [str(x).strip() for x in (json.load(fh) or {}).get("mains") or []]
    except (OSError, ValueError):
        wanted = []
    live = {r["name"] for r in conn.execute("SELECT name FROM accounts WHERE enabled = 1")}
    return [n for n in wanted if n in live][:1]


def _identity(asset_id, name):
    """هوية النوع: الـ asset id لو موجود، والاسم الصغير بديلًا لقطع الباتش اللي
    بتوصل من غير asset id — نفس المنطق اللي بيقارن بيه FIND ME."""
    text = str(asset_id or "").strip()
    return text if text else str(name or "").strip().lower()


@app.put("/api/accounts/{account_id}/main")
def api_account_main(account_id: str, body: dict):
    if not isinstance(body.get("is_main"), bool):
        raise HTTPException(400, "is_main must be a boolean")

    def run(conn):
        rec = store.get_account(conn, account_id)
        if not rec or not rec["enabled"]:
            raise HTTPException(404, "unknown or disabled account")
        mains = [rec["name"]] if body["is_main"] else [name for name in _main_accounts(conn) if name != rec["name"]]
        temporary = MAIN_ACCOUNTS_FILE + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"mains": mains}, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, MAIN_ACCOUNTS_FILE)
        return {"mains": mains}

    return _with_conn(run)


@app.post("/api/item/transfer-candidates")
def api_transfer_candidates(body: dict):
    current = _one_account((body or {}).get("account") or "")

    def run(conn):
        groups = []
        for target in _main_accounts(conn):
            if target == current:
                continue
            rec = conn.execute("SELECT name, label, display_name FROM accounts WHERE name = ?", (target,)).fetchone()
            ids = [row["instance_id"] for row in conn.execute(
                "SELECT DISTINCT source.instance_id FROM instances source "
                "WHERE source.account = ? AND source.instance_id <> '' "
                "AND NOT EXISTS (SELECT 1 FROM instances dest WHERE dest.account = ? "
                "AND dest.instance_id = source.instance_id)", (current, target))]
            last_success = store.last_success(conn, target)
            if not last_success or not store.last_success(conn, current):
                ids = []
            groups.append({"account": target, "label": _acc_short(rec), "ids": ids,
                           "last_success": last_success})
        return {"account": current, "groups": groups,
                "last_success": store.last_success(conn, current)}

    return JSONResponse(_with_conn(run))


@app.post("/api/item/tomain")
def api_item_tomain(body: dict):
    """قطع الحساب المفتوح اللي نوعها مش موجود في أي حساب أساسي.

    دي قائمة "افاضي الحساب الفرعي": كل قطعة فيها مالهاش بديل عند الأساسي، فالأحسن
    تتنقل قبل ما الحساب الفرعي يتقفل ويروح مكانه حساب بلوت جديد. النقل نفسه يدوي
    (توكن الحساب الفرعي ما بيقدرش على الأساسي)، فالواجهة بتعرضها وبتحددها بس.
    الحساب الأساسي بيرجع is_main=true ومفيش قائمة."""
    current = _one_account((body or {}).get("account") or "")

    def run(conn):
        mains = _main_accounts(conn)
        if current in mains:
            return {"account": current, "mains": mains, "is_main": True, "map": {}}
        if not mains:
            return {"account": current, "mains": [], "is_main": False, "no_mains": True, "map": {}}
        have = set()
        for m in mains:
            for r in conn.execute("SELECT asset_id, name FROM instances WHERE account = ?", (m,)):
                have.add(_identity(r["asset_id"], r["name"]))
        out = {}
        for r in conn.execute("SELECT instance_id, asset_id, name FROM instances WHERE account = ?",
                              (current,)):
            if _identity(r["asset_id"], r["name"]) not in have:
                out[r["instance_id"]] = True
        return {"account": current, "mains": mains, "is_main": False, "map": out}

    return JSONResponse(_with_conn(run))


@app.post("/api/item/findme")
def api_item_findme(body: dict):
    """FIND ME — كمية النوع ده من البحث في كل حساب تاني عندك، مكرر أو مش مكرر.

    ده مقارنة كميات باردة: سطر لكل حساب مفعّل (حسابك مستثنى — بلاطاته الحية بتترسم
    فوق في عمود الستاش)، وفيه بلاطة لكل (اسم + صحة) بكميتها ومعاها `ids` وسطر نموذجي
    كامل (مرفقات/قيمة/درجة) عشان كارت التفاصيل يفتح بالهوفر حتى على قطع حساب تاني.
    البلاطات ميتة: لا سحب ولا تحديد، لأن توكنك ما بيقدرش على حساب تاني. مفيش سطر من
    حساب محذوف/مقفل بيطلع من هنا، ولا `wrapper_id`/توكن أجنبي."""
    body = body or {}
    needle = str(body.get("q") or "").strip()
    current = _one_account(body.get("account") or "")
    limit = min(int(body.get("limit") or 400), 1200)
    if not needle:
        return JSONResponse({"account": current, "groups": [], "total": 0, "shown": 0})

    def run(conn):
        like = "%" + needle.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = conn.execute(
            "SELECT i.account acc_key, a.name acc_name, a.label acc_label, a.display_name acc_display, "
            "i.instance_id iid, i.name iname, i.qty iqty, i.asset_id asset_id, i.rarity rarity, "
            "i.type itype, i.image image, i.level level, i.value value, i.durability durability, "
            "i.max_durability max_durability, i.show_durability show_durability, "
            "i.quality_level quality_level, i.total_count total_count, i.attachments attachments "
            "FROM instances i JOIN accounts a ON a.name = i.account "
            "WHERE a.enabled = 1 AND i.account <> ? "
            "AND (lower(i.name) LIKE ? ESCAPE '\\' OR lower(i.type) LIKE ? ESCAPE '\\')",
            (current, like, like)).fetchall()

        def pct(r):
            m = float(r["max_durability"] or 0)
            return (float(r["durability"] or 0) / m) if m > 0 else 1.0

        def row_pct(r):
            m = float(r.get("max_durability") or 0)
            return (float(r.get("durability") or 0) / m) if m > 0 else 1.0

        groups, buckets = {}, {}
        for r in rows:
            who = _acc_short({"name": r["acc_name"], "label": r["acc_label"],
                              "display_name": r["acc_display"]})
            if not who:
                continue  # حساب محذوف/مقفل — ما نعرضش مفتاحه الخام
            host = groups.setdefault(who, {"account_label": who, "pieces": 0,
                                           "cells": 0, "rows": []})
            key = (who, str(r["iname"]), round(pct(r), 3))
            b = buckets.get(key)
            if b is None:
                b = buckets[key] = {"host": host, "ids": [], "qty": 0, "cells": 0,
                                    "rep": r, "rep_pct": pct(r)}
            b["ids"].append(r["iid"])
            b["qty"] += int(r["iqty"] or 1)
            b["cells"] += 1
            if pct(r) < b["rep_pct"]:
                b["rep"], b["rep_pct"] = r, pct(r)

        for b in buckets.values():
            rep, host = b["rep"], b["host"]
            try:
                atts = json.loads(rep["attachments"] or "[]")
            except (TypeError, ValueError):
                atts = []
            row = {"instance_id": rep["iid"], "ids": b["ids"],
                   "name": rep["iname"], "type": rep["itype"], "asset_id": rep["asset_id"],
                   "rarity": rep["rarity"], "image": rep["image"], "level": rep["level"],
                   "value": rep["value"], "durability": rep["durability"],
                   "max_durability": rep["max_durability"],
                   "show_durability": rep["show_durability"],
                   "quality_level": rep["quality_level"],
                   "total_count": rep["total_count"], "attachments": atts,
                   "qty": b["qty"], "cells": b["cells"], "account_label": host["account_label"]}
            catalog.decorate(row)
            host["rows"].append(row)
            host["pieces"] += row["qty"]
            host["cells"] += row["cells"]

        out = sorted(groups.values(), key=lambda g: g["account_label"].lower())
        for g in out:
            g["rows"].sort(key=lambda x: (str(x.get("display_name") or x["name"]).lower(),
                                          -row_pct(x), -x["qty"]))
        shown = sum(len(g["rows"]) for g in out)
        if shown > limit:
            kept, trimmed = 0, []
            for g in out:
                room = limit - kept
                if room <= 0:
                    break
                g["rows"] = g["rows"][:room]
                kept += len(g["rows"])
                trimmed.append(g)
            out = [g for g in trimmed if g["rows"]]
        return {"account": current, "q": needle, "groups": out,
                "total": shown, "shown": sum(len(g["rows"]) for g in out)}

    return JSONResponse(_with_conn(run))


PLACEHOLDER_NAME = re.compile(r"^Item -?\d+$")


@app.get("/api/assets/unknown")
def api_assets_unknown(account: str = ""):
    """كل asset id مملوك ومفيش ليه اسم في الفهارس — دي بنود الباتش الجديد.

    الـ ID بيجي من شجرة الحساب نفسها فالقيمة صح حتى لو الاسم ناقص؛ بنرجّع كمان
    عدد النسخ وأماكنها (ستاش/أوفر/شنطة/خانات تجهيز) عشان نعرف إنت ماسكها فعلاً
    ولا مجرد مفتوح في الحساب. الاسم اللي تعرفه يتكتب في
    data/catalog/asset_index_local.csv فيختفي من القائمة دي."""
    from . import pioneer_tree

    def run(conn):
        target = account or ACTIVE["account"]
        payload, fetched = store.read_snapshot(conn, target)
        if not payload:
            raise HTTPException(503, "no local snapshot for %s yet" % target)
        names = pioneer_tree.asset_names()
        mappings = payload.get("item_mappings") or {}

        def named(aid):
            row = names.get(aid) or {}
            if (row.get("display_name") or row.get("game_asset_name") or "").strip():
                return True
            # الاسم المشتق «Item <رقم>» إحنا اللي بنعمله لما الفهرس ما يعرفش —
            # لو حسبناه اسم حقيقي القطعة المجهولة مش هتظهر في القائمة دي خالص.
            nm = str((mappings.get(aid) or {}).get("name") or "").strip()
            return bool(nm) and not PLACEHOLDER_NAME.match(nm)

        def slot_iter():
            for key in ("stash", "overflow", "backpack"):
                for slot in (payload.get(key) or []):
                    yield key, slot
            for cname, slots in (payload.get("containers") or {}).items():
                for slot in (slots or []):
                    yield "loadout:" + cname, slot

        held = {}
        for place, slot in slot_iter():
            item = slot.get("item") or {}
            aid = str(item.get("asset_id") or "")
            if not aid or named(aid):
                continue
            rec = held.setdefault(aid, {"asset_id": aid, "count": 0, "places": set(),
                                        "instance_id": item.get("instanceId") or "",
                                        "qty": item.get("quantity") or item.get("amount") or 1})
            rec["count"] += 1
            rec["places"].add(place)

        out = []
        for rec in sorted(held.values(), key=lambda r: -r["count"]):
            rec["places"] = sorted(rec["places"])
            out.append(rec)
        gaps = sorted({str(i) for i in (payload.get("owned_asset_ids") or [])} -
                      {str(i) for i in (payload.get("owned_asset_ids") or []) if named(str(i))})
        return JSONResponse({"account": target,
                             "snapshot_age_minutes": round((time.time() - (fetched or 0)) / 60, 1),
                             "in_inventory": out, "index_gaps": gaps,
                             "patch_candidates": catalog.patch_candidates(),
                             "index_file": pioneer_tree.ASSET_LOCAL_FILE})
    return _with_conn(run)


@app.post("/api/assets/name")
def api_assets_name(body: dict):
    """تعريف اسم لـ asset id مجهول (بنود الباتش الجديد) وكتابته في الفهرس المحلي.

    القراءة بس من المنبع: مفيش أي طلب تعديل بيخرج للببوابة هنا."""
    from . import pioneer_tree
    body = body or {}
    try:
        rec = pioneer_tree.remember(body.get("asset_id"), body.get("name"),
                                    body.get("hint") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(rec)


@app.get("/api/loadouts")
def api_loadouts(account: str = ""):
    """القوالب المحفوظة مشتركة بين كل حساباته — `account` للعرض بس."""
    conn = store.db()
    out = store.list_loadouts(conn)
    conn.close()
    return {"account": account, "loadouts": out}


@app.post("/api/loadouts")
def api_loadout_save(body: dict):
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    try:
        rec, data = _with_conn(lambda conn: loadouts.save(conn, account, body.get("name") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"loadout": rec, "captured": data}


@app.get("/api/loadouts/{loadout_id}/plan")
def api_loadout_plan(loadout_id: int, account: str):
    try:
        return _with_conn(lambda conn: loadouts.plan(conn, account, loadout_id))
    except KeyError:
        raise HTTPException(404, "unknown loadout")


@app.get("/api/loadouts/{loadout_id}/preview")
def api_loadout_preview(loadout_id: int, account: str):
    """معاينة القالب قبل التنفيذ: كل خانة بحالتها + مسار كل ناقصة (تصنيع/شراء).
    قراءة من الداتا المحلية وشجرة الحساب بس — مفيش أي طلب شبكة ولا كتابة."""
    try:
        return _with_conn(lambda conn: loadouts.preview(conn, account, loadout_id))
    except KeyError:
        raise HTTPException(404, "unknown loadout")


@app.post("/api/loadouts/{loadout_id}/apply")
def api_loadout_apply(loadout_id: int, body: dict):
    account = (body or {}).get("account") or ACTIVE["account"]
    try:
        return _with_conn(lambda conn: loadouts.apply_plan(conn, account, loadout_id))
    except KeyError:
        raise HTTPException(404, "unknown loadout")


@app.patch("/api/loadouts/{loadout_id}")
def api_loadout_rename(loadout_id: int, body: dict):
    """اسم جديد لقالب محفوظ — محلي بالكامل، من غير أي كتابة على حساب اللعبة."""
    name = str((body or {}).get("name") or "").strip()[:64]
    if not name:
        raise HTTPException(400, "Loadout name is required.")
    row = _with_conn(lambda conn: store.rename_loadout(conn, loadout_id, name))
    if row is None:
        raise HTTPException(404, "unknown loadout")
    if row is False:
        raise HTTPException(409, "That name is already taken in the same account.")
    return {"loadout": {"id": row["id"], "name": row["name"], "account": row["account"]}}


@app.delete("/api/loadouts/{loadout_id}")
def api_loadout_delete(loadout_id: int):
    row = _with_conn(lambda conn: store.delete_loadout(conn, loadout_id))
    if not row:
        raise HTTPException(404, "unknown loadout")
    return {"deleted": loadout_id, "account": row["account"], "name": row["name"]}


@app.get("/api/item")
def api_item(account: str, instance_id: str):
    conn = store.db()
    row = conn.execute("SELECT * FROM instances WHERE account=? AND instance_id=?",
                       (account, instance_id)).fetchone()
    payload, _ = store.read_snapshot(conn, account)
    conn.close()
    if not row:
        raise HTTPException(404, "unknown instance")
    d = dict(row)
    catalog.decorate(d)
    d["total_value"] = (d.get("value") or 0) * (d.get("qty") or 0)
    d["condition"] = (round(100.0 * d["durability"] / d["max_durability"])
                      if d.get("durability") is not None and d.get("max_durability") else None)
    mapping = ((payload or {}).get("item_mappings") or {}).get(str(d.get("asset_id") or ""), {}) or {}
    d["mapping"] = {k: mapping.get(k) for k in ("craft_bench", "recipe", "recycle_info", "repair_cost",
                                                 "backpack_slots_count", "safe_pocket_slots_count",
                                                 "quick_use_slots_count", "augmented_slots_count",
                                                 "station_level_required")
                    if mapping.get(k) is not None}
    d["db"] = items_db.dossier(d.get("asset_id"), d.get("name"))
    return d


@app.get("/api/items/db")
def api_items_db(name: str = "", asset_id: str = ""):
    """كل المعروف عن عنصر من قاعدة arctracker (ريسايكل/كرافت/ترقية) — حتى لو مش مملوك."""
    row = items_db.dossier(asset_id or None, name or None)
    if not row:
        raise HTTPException(404, "unknown item")
    return row


@app.get("/api/items/db/meta")
def api_items_db_meta():
    return items_db.meta()


@app.get("/api/writes")
def api_writes_status():
    return writer.status()


@app.post("/api/writes/arm")
def api_writes_arm():
    writer.arm()
    return writer.status()


@app.post("/api/writes/disarm")
def api_writes_disarm():
    writer.disarm()
    return writer.status()


@app.post("/api/writes/pause")
def api_writes_pause(body: dict = None):
    """تجميد كامل للكتابة على البوابة (الحساب مشغول). body={"on": false} يرفعه."""
    from . import pioneer_write
    on = (body or {}).get("on", True)
    pioneer_write.set_paused(bool(on))
    return writer.status()


@app.post("/api/actions/move")
def api_action_move(body: dict):
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn_free(lambda conn: actions.move(
        conn, account, body.get("target_container") or "",
        instance_ids=body.get("instance_ids"), name=body.get("name"),
        container=body.get("from_container"), target_wrapper_id=body.get("target_wrapper_id", ""),
        limit=body.get("limit"), target_slot=body.get("target_slot") or "")))


@app.post("/api/actions/move-batch")
def api_action_move_batch(body: dict):
    """خطة النقل كلها في طلب واحد — أسرع مسار للتبديل والدفعات الكبيرة."""
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn_free(lambda conn: actions.move_batch(
        conn, account, body.get("moves") or [])))


@app.get("/api/moves/queue")
def api_moves_queue(account: str = ""):
    """الخطط المستنىّة مسار الكتابة — للتابض اللي عايز يعرض العداد."""
    rows = move_queue.listing()
    if account:
        items = [r for r in rows["items"] if r.get("account") == account]
        return JSONResponse({**rows, "items": items, "count": len(items)})
    return JSONResponse(rows)


@app.post("/api/moves/queue")
def api_moves_queue_add(body: dict):
    """بيلخّط خطة نقل جنب الباب المقفول — الخيط العام بينفّذها لوحدها لما المسار يرجع."""
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(move_queue.enqueue(account, body.get("moves") or [],
                                            body.get("summary") or ""))


@app.delete("/api/moves/queue/{entry_id}")
def api_moves_queue_drop(entry_id: str):
    return JSONResponse(move_queue.remove(entry_id))


@app.post("/api/moves/queue/clear")
def api_moves_queue_clear(body: dict = None):
    account = str((body or {}).get("account") or "")
    return JSONResponse(move_queue.clear(account or None))


@app.post("/api/moves/queue/run")
def api_moves_queue_run():
    """محاولة فورية واحدة على أول خطة في الطابور — للزرار، مش للحارس العام."""
    return JSONResponse(move_queue.flush_once())


@app.post("/api/actions/gather")
def api_action_gather(body: dict):
    """لمّ كل أكوام عنصر واحد في خانات متتالية بالستاش (مسار النقل الرسمي)."""
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.gather(
        conn, account, _split_ids(body.get("instance_ids")), asset_id=body.get("asset_id") or "")))


@app.post("/api/actions/spread")
def api_action_spread(body: dict):
    """فرّد أكوام عنصر واحد على خانات ستاش متباعدة — كل كوم في خانة لوحده."""
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.spread(
        conn, account, _split_ids(body.get("instance_ids")),
        asset_id=body.get("asset_id") or "", dry=bool(body.get("dry")))))


@app.post("/api/actions/merge-all")
def api_action_merge_all(body: dict):
    """زرار ⇄: دمج حقيقي لكل أكوام الحساب (ستاش + أوفر فلو) على الحد الأقصى لكل نوع."""
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.merge_all(
        conn, account, dry=not bool(body.get("execute")),
        max_ops=int(body.get("max_ops") or 200))))


@app.post("/api/actions/touch")
def api_action_touch(body: dict):
    """↑ UPDATE: لمسة محايدة على خانات التجهيز عند Embark — مفيش عنصر بيتحرّك."""
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.touch(
        conn, account, _split_ids(body.get("instance_ids")))))


@app.post("/api/actions/mutate")
def api_action_mutate(body: dict):
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.mutate(
        conn, account, body.get("action") or "",
        instance_ids=body.get("instance_ids"), name=body.get("name"),
        container=body.get("from_container"),
        target_wrapper_id=body.get("target_wrapper_id", ""),
        target_instance_id=body.get("target_instance_id", ""),
        amount=body.get("amount"), limit=body.get("limit"))))


@app.post("/api/actions/undo")
def api_action_undo(body: dict):
    """ترجع الخانات لحالتها قبل آخر حركة مسجلة في سجل الواجهة (خطوة خطوة)."""
    from . import pioneer_write
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    undo = body.get("undo") if isinstance(body.get("undo"), dict) else {}
    cells = undo.get("cells") or body.get("cells") or {}
    return JSONResponse(_with_conn(lambda conn: pioneer_write.undo_cells(conn, account, cells)))


@app.post("/api/actions/clear-backpack")
def api_action_clear_backpack(body: dict):
    account = (body or {}).get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.clear_backpack(
        conn, account, scope=(body or {}).get("scope") or "backpack")))


@app.get("/api/scrappy")
def api_scrappy(account: str = ""):
    return _with_conn(lambda conn: scrappy.view(conn, account or ACTIVE["account"]))


@app.post("/api/scrappy/preview")
def api_scrappy_preview(body: dict):
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: scrappy.preview(
        conn, account, body.get("offer_id"), body.get("amount", 1))))


@app.post("/api/scrappy/feed")
def api_scrappy_feed(body: dict):
    """تحويل زراعي عند الديك — بيتنفّذ بس من نافذة التأكيد (confirmed=true)."""
    body = body or {}
    account = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: scrappy.claim(
        conn, account, body.get("offer_id"), body.get("amount", 1),
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/collect-scrappy")
def api_action_collect_scrappy(body: dict):
    account = (body or {}).get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: scrappy.collect(conn, account)))


# ------------------------------------------------------------------ Phase 10: ماركس + مرفقات + عمليات
def _split_ids(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [part.strip() for part in str(value).split(",") if part.strip()]


@app.get("/api/marks")
def api_marks_get(account: str = ""):
    name = account or ACTIVE["account"]
    return _with_conn(lambda conn: actions.marks(conn, name))


@app.post("/api/marks")
def api_marks_add(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    out = _with_conn(lambda conn: actions.mark_add(conn, name, _split_ids(body.get("instance_ids")),
                                                   body.get("color") or ""))
    return JSONResponse(out, status_code=200 if out.get("ok") else 400)


@app.delete("/api/marks")
def api_marks_delete(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    out = _with_conn(lambda conn: actions.mark_remove(
        conn, name, instance_ids=_split_ids(body.get("instance_ids")),
        mark_ids=_split_ids(body.get("mark_ids")), color=body.get("color") or None))
    return JSONResponse(out)


@app.get("/api/attachments/slots")
def api_attachment_slots():
    return actions.attachment_rules()


@app.get("/api/attachments/manager")
def api_attachment_manager(account: str = "", ids: str = ""):
    name = account or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.attachment_manager(conn, name, _split_ids(ids))))


@app.post("/api/actions/plan")
def api_action_plan(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.plan(
        conn, name, body.get("kind") or "", instance_ids=_split_ids(body.get("instance_ids")),
        targets=body.get("targets") or {})))


@app.post("/api/actions/attachments/paste")
def api_attachments_paste(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.paste(
        conn, name, _split_ids(body.get("weapon_ids")), body.get("setup") or {},
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/attachments/autofill")
def api_attachments_autofill(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.autofill(
        conn, name, _split_ids(body.get("weapon_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/attachments/attach")
def api_attachments_attach(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.attach_one(
        conn, name, body.get("weapon_id"), body.get("slot_wrapper_id"),
        body.get("attachment_id"), body.get("source_wrapper_id"),
        body.get("target_container") or "stash")))


@app.post("/api/actions/attachments/detach")
def api_attachments_detach(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.detach(
        conn, name, _split_ids(body.get("weapon_ids")), _split_ids(body.get("slot_wrapper_ids")),
        target_container=body.get("target_container") or "stash",
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/upgrade")
def api_action_upgrade(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.upgrade(
        conn, name, _split_ids(body.get("instance_ids")), targets=body.get("targets") or {},
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/recycle")
def api_action_recycle(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.recycle(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/sell")
def api_action_sell(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.sell(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/repair")
def api_action_repair(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.repair(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/delete")
def api_action_delete(body: dict):
    """حذف مباشر على بوابة اللعبة — المنبع بيقرّر يقبل أو يرفض ونردّ رفضه نصاً."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.delete(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/split")
def api_action_split(body: dict):
    """تقسيم مباشرة على بوابة اللعبة — المنبع بيقرّر ونردّ رفضه نصاً."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.split(
        conn, name, str(body.get("instance_id") or ""),
        target_wrapper=str(body.get("target_wrapper_id") or ""),
        amount=body.get("amount"), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/fill")
def api_action_fill(body: dict):
    """كمية بالضبط للشنطة: ينقل الرصّات الكاملة ويفصل الفاضل من رصة تانية على البوابة الرسمية."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.fill(
        conn, name, str(body.get("asset_id") or ""), body.get("amount"),
        target_wrapper=str(body.get("target_wrapper_id") or ""),
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/combine")
def api_action_combine(body: dict):
    """دمج رصتين من نفس النوع مباشرة على بوابة اللعبة — المنبع بيقرّر ونردّ رفضه نصاً."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.combine(
        conn, name, str(body.get("instance_id") or ""),
        str(body.get("target_instance_id") or ""),
        amount=body.get("amount"), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/swap")
def api_action_swap(body: dict):
    """تبديل مكان قطعتين على بوابة اللعبة — خانة بخانة، من غير ما أي كمية تتغيّر."""
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.swap(
        conn, name, str(body.get("instance_id") or ""),
        str(body.get("target_instance_id") or ""),
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/sync")
def api_action_sync(body: dict):
    body = body or {}
    name = body.get("account") or ACTIVE["account"]
    return JSONResponse(_with_conn(lambda conn: actions.synchronize(conn, name)))


@app.get("/api/actions/log")
def api_action_log(limit: int = 30, account: str = ""):
    conn = store.db()
    rows = actions.pending(conn, limit, account or "")
    conn.close()
    return {"log": rows, "writes": writer.status()}


@app.post("/auth/embark/{account_id}/activate")
def activate_by_id(account_id):
    """نفس شكل rampart — التبديل محلي فقط ولا يرسل أي طلب تعديل للمنبع."""
    def run(conn):
        rec = store.get_account(conn, account_id)
        if not rec:
            raise HTTPException(404, "unknown account")
        accounts_mod.select(conn, rec["id"])
        ACTIVE["account"] = rec["name"]
        return {"active": rec["name"], "local": True}
    return _with_conn(run)


@app.get("/assets/items/metaforge/{filename}")
def metaforge_asset(filename):
    base = os.path.basename(filename)
    path = os.path.join(config.ITEM_ASSETS_DIR, "metaforge", base)
    if not os.path.isfile(path) and base.lower().endswith(".png"):
        path = os.path.join(config.ITEM_ASSETS_DIR, "metaforge", os.path.splitext(base)[0] + ".webp")
    if not os.path.isfile(path):
        raise HTTPException(404, "asset not cached locally")
    media = "image/webp" if path.lower().endswith(".webp") else "image/png"
    return FileResponse(path, media_type=media)


@app.get("/assets/items/arctracker/{filename}")
def arctracker_asset(filename):
    base = os.path.basename(filename)
    path = os.path.join(config.ITEM_ASSETS_DIR, "arctracker", base)
    if not os.path.isfile(path) and base.lower().endswith(".png"):
        path = os.path.join(config.ITEM_ASSETS_DIR, "arctracker", os.path.splitext(base)[0] + ".webp")
    if not os.path.isfile(path):
        raise HTTPException(404, "asset not cached locally")
    media = "image/webp" if path.lower().endswith(".webp") else "image/png"
    return FileResponse(path, media_type=media)


@app.get("/assets/items/{filename}")
def item_asset(filename):
    base = os.path.basename(filename)
    path = os.path.join(config.ITEM_ASSETS_DIR, base)
    if not os.path.exists(path) and base.lower().endswith(".png"):
        path = os.path.join(config.ITEM_ASSETS_DIR, os.path.splitext(base)[0] + ".webp")
    if not os.path.exists(path):
        raise HTTPException(404, "asset not cached locally")
    media = "image/webp" if path.lower().endswith(".webp") else "image/png"
    return FileResponse(path, media_type=media)


@app.get("/assets/{filename}")
def root_asset(filename):
    path = os.path.join(config.ASSETS_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        raise HTTPException(404, "asset not cached locally")
    return FileResponse(path)


@app.get("/")
def index(request: Request):
    conn = store.db()
    try:
        ident = _caller_identity(request, conn)
    finally:
        conn.close()

    # إذا كان أدمن ومش بيتصفح مشترك معين: توجيهه مباشرة للوحة الأدمن (قائمة التحكم والمشتركين)
    if ident["is_admin"] and not ident["viewing_as"]:
        return RedirectResponse("/admin", status_code=302)

    return FileResponse(os.path.join(config.FRONTEND_DIR, "index.html"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/{tail:path}")
def ui_files(tail):
    base = os.path.realpath(config.FRONTEND_DIR)
    path = os.path.realpath(os.path.join(base, tail))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)
