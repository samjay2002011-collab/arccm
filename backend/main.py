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
import base64
import binascii
import json
import gzip
import hashlib
import os
import re
import secrets
import shutil
import threading
import contextvars
import urllib.parse
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Cookie
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse

from . import accounts as accounts_mod
from . import actions, agent_link, agent_release, augments, auth, catalog, config, derive, items_db, loadouts, move_queue, writer
from . import pioneer_client, pioneer_tree, pioneer_write, rampart_client, knowledge, scrappy, store, sync as sync_mod, traders as traders_mod, workshop
from . import item_catalog, item_overrides
from . import subscribers as subs_mod
from .multipart import parsemultipart

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


def _sync_active_name(conn):
    """يخلي المتغير النشط مطابق لجدول الحسابات (المصدر الحقيقي للاسم الحالي).

    مع مشترك: الحساب المقيّد بالطلب هو اللي بيُرجع والقاعدة ما تتلمسش — الحساب
    النشط العام بتاع الأدمين ما يتغيّرش عشان مشترك فتح الصفحة.
    """
    scoped = _SCOPED_ACTIVE.get()
    if scoped is not None:
        return ACTIVE["account"]
    rec = store.active_account_admin(conn)
    if rec:
        ACTIVE["account"] = rec["name"]
    else:
        ACTIVE["account"] = ""
    return ACTIVE["account"]


def _is_real_admin(request) -> bool:
    """هل صاحب الطلب أدمن حقيقي (جلسة أدمن نشطة أو توكن أدمن)؟"""
    session = request.headers.get("X-Admin-Session", "") or request.cookies.get("cm_admin_session", "")
    if session and session in _ADMIN_SESSIONS:
        return True
    if _admin_token_kept(request):
        return True
    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    if token:
        conn = store.db()
        try:
            subs_mod._ensure_tables(conn)
            adm_tok = subs_mod.admin_token(conn)
            if token == adm_tok:
                return True
        finally:
            conn.close()
    return False


def _get_as_subscriber(request) -> str:
    """اسم المشترك المطلوب تصفحه في هذا التبويب (عبر الهيدر أو الباراميتر)."""
    sub = (request.headers.get("X-As-Subscriber") or "").strip()
    if not sub:
        sub = (request.query_params.get("as_subscriber") or request.query_params.get("view_as") or "").strip()
    import urllib.parse
    return urllib.parse.unquote(sub) if sub else ""


def _viewer(request):
    """مين اللي بيقرا دلوقتي: (is_admin, owner_name).

    أدمن (محلي أو admin token) بيشوف كل الحسابات — owner=None مع is_admin=True.
    مشترك عادي بيشوف حسابات بروفايله بس — owner=اسم المشترك.
    التبويب المخصص للمشترك (عبر الهيدر أو الباراميتر) يرى فقط حسابات ذلك المشترك.
    """
    as_sub = _get_as_subscriber(request)
    if as_sub:
        if not _is_real_admin(request):
            raise HTTPException(403, "Admin session required to impersonate subscribers")
        return False, as_sub

    preview = _PREVIEW_SESSIONS.get((request.cookies.get(PREVIEW_COOKIE, "") or "").strip())
    if preview:
        return False, preview

    impersonating = bool((request.cookies.get("cm_viewing_subscriber", "") or "").strip())
    if impersonating:
        import urllib.parse
        view_cookie = urllib.parse.unquote((request.cookies.get("cm_viewing_subscriber", "") or "").strip())
        return False, view_cookie

    adm_sess = request.cookies.get("cm_admin_session", "")
    if adm_sess and adm_sess in _ADMIN_SESSIONS:
        return True, None

    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    if not token:
        return False, ""

    conn = store.db()
    try:
        subs_mod._ensure_tables(conn)
        if token == subs_mod.admin_token(conn):
            return True, None
        row = conn.execute("SELECT name FROM subscribers WHERE token=?", (token,)).fetchone()
    finally:
        conn.close()
    return False, (row["name"] if row else "")


def _subscriber_limit(owner):
    """حد الحسابات اللي حطه الأدمن للمشترك ده — None يعني من غير حد."""
    if not owner:
        return 0
    conn = store.db()
    try:
        subs_mod._ensure_tables(conn)
        row = conn.execute("SELECT account_limit FROM subscribers WHERE name=?", (owner,)).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    return row[0] if row else None


def _owner_of(conn, account_key):
    """اسم مالك الحساب (مفتاح الملكية) أو None لو مش معروف."""
    rec = store.get_account(conn, account_key)
    return (rec or {}).get("owner_username")


def _guard_account(request, account_key):
    """يرفض أي مشترك بيلمس حساب مش بتاعه (404 مخفي). الأدمين والمحلي عدّية."""
    is_admin, owner = _viewer(request)
    if is_admin:
        return
    actual = _with_conn(lambda conn: _owner_of(conn, account_key))
    if not owner or not actual:
        raise HTTPException(404, "unknown account")
    if actual != owner and actual not in store._expand_names(owner):
        raise HTTPException(404, "unknown account")


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
class _ActiveScope(dict):
    """الحساب النشط لكل طلب على حدة.

    الأدمن/المحلي بيقرا/يكتب القيمة العامة (اكتب = يبدّل التاب العام)، والمشترك
    بياخد نسخة خاصة بيه في الـ contextvars — فتبويب مشترك ما يقدرش ينقّل حساب
    حد تاني ولا يورّث الحساب العام.
    """

    KEY = "account"
    DEFAULT = {"account": ""}

    def __init__(self):
        super().__init__(self.DEFAULT)

    def _scoped(self):
        return _SCOPED_ACTIVE.get()

    def get(self, key, default=None):
        if key == self.KEY:
            scoped = self._scoped()
            if scoped is not None:
                return scoped["active"]
        return dict.get(self, key, default)

    def __getitem__(self, key):
        if key == self.KEY:
            scoped = self._scoped()
            if scoped is not None:
                return scoped["active"]
        return dict.__getitem__(self, key)

    def __setitem__(self, key, value):
        if key == self.KEY and self._scoped() is not None:
            # المشترك بيقدر يبدّل لحساب من حساباته بس، والغريب بيترمي لغير المقيّد
            if value in self._scoped()["accounts"]:
                _SCOPED_ACTIVE.set({"active": value, "accounts": self._scoped()["accounts"],
                                    "is_admin": self._scoped().get("is_admin", False)})
            return
        dict.__setitem__(self, key, value)


_SCOPED_ACTIVE = contextvars.ContextVar("scoped_active_account", default=None)
ACTIVE = _ActiveScope()


def _scope_to_subscriber(owner_name):
    """يقيّد الطلب الحالي بحسابات المشترك — والمجموعة فاضية لو مالوش حسابات.

    القيمة {'active': أول حساب, 'accounts': set(أسماء حساباته)}. بتترجع None للأدمن.
    """
    if not owner_name:
        return
    conn = store.db()
    try:
        rows = store.list_accounts_owned(conn, owner_name)
    finally:
        conn.close()
    names = [r["name"] for r in rows]
    _SCOPED_ACTIVE.set({"active": names[0] if names else "", "accounts": set(names), "is_admin": False})


def _scope_to_admin():
    """يقيّد طلب الأدمن العادي بحسابات الأدمن فقط — استبعاد أي حساب يتبع أي مشترك."""
    conn = store.db()
    try:
        rows = store.list_accounts_admin(conn)
    finally:
        conn.close()
    names = [r["name"] for r in rows]
    active = ""
    for r in rows:
        if r.get("is_active"):
            active = r["name"]
            break
    if not active and names:
        active = names[0]
    _SCOPED_ACTIVE.set({"active": active, "accounts": set(names), "is_admin": True})


_ACCOUNT_KEYS = ("account", "name", "account_id", "accounts", "target", "source")


async def _shield_foreign_account(request):
    """أي اسم حساب في الـ query أو جسم الـ JSON بيتقلّب لحساب المشترك لوحده.

    المسارات القديمة بتاخد الاسم من body.get('account') أو من الـ query مباشرة،
    فمشترك يقدر يبعت اسم حساب حد تاني. بدل تعديل كل مسار، بنلمس الطلب نفسه هنا
    عشان كل المسارات تشوف اسم من حساباته بس.
    """
    scoped = _SCOPED_ACTIVE.get()
    if not scoped:
        return
    allowed = scoped["accounts"]
    fallback = scoped["active"]

    def clean(value):
        if isinstance(value, str) and value and value != "ALL" and value not in allowed:
            return fallback
        if isinstance(value, list):
            kept = [v for v in value if v in allowed]
            return kept or ([fallback] if fallback else [])
        return value

    pairs = []
    for k, v in request.query_params.multi_items():
        pairs.append((k, clean(v) if k in _ACCOUNT_KEYS else v))
    request.scope["query_string"] = urllib.parse.urlencode(pairs).encode()
    # Starlette بيستخدم hasattr على _query_params، فـ None بتخلي attribute موجود ومش متحدّث
    if hasattr(request, "_query_params"):
        del request._query_params
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        try:
            raw = await request.body()
        except Exception:
            return
        if not raw:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        if isinstance(data, dict):
            changed = False
            for key in _ACCOUNT_KEYS:
                if key in data:
                    fixed = clean(data[key])
                    if fixed != data[key]:
                        data[key] = fixed
                        changed = True
            if changed:
                request._body = json.dumps(data).encode()


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
    "/login", "/auth/subscriber/login", "/auth/logout", "/auth/subscriber/logout",
    "/favicon.png", "/login.js", "/api/auth/me", "/api/subscriber/verify",
    "/download/cmsync", "/download/CMSync_Setup.exe", "/CMSync_Setup.exe",
    "/api/cmsync/version", "/api/status"
}
_PUBLIC_PREFIXES = ("/auth/subscriber/", "/download/")
# مفتاح جلسة الأدمين — بيتغير مع كل restart
_ADMIN_SESSIONS = set()
ADMIN_TOKEN_COOKIE = "cm_admin_token"
PREVIEW_COOKIE = "cm_test_sub"
# جلسات المعاينة "تجربة كمشترك": توكن الجلسة -> مشترك. بيتصفح تحت جلسة مشترك حقيقية
# والرجوع بيمسحها، فجلسة الأدمين الأساسية (الكوكي cm_admin_session) ما تتلمسش.
_PREVIEW_SESSIONS = {}


def _admin_token_kept(request) -> bool:
    """كوكي توكن الأدمين لو موجودة — بتتحط لما الأدمين بيدخل من /login بتوكنه،
    وبترجّع له صلاحياته لما يخرج من وضع المعاينة."""
    return (request.cookies.get(ADMIN_TOKEN_COOKIE, "") or "").strip() != ""


def _set_name_cookie(resp, name):
    """اسم المشترك في الكوكي لازم يترمّز — الهيدر بينسخ latin-1 والاسم العربي مش فيه."""
    import urllib.parse
    resp.set_cookie("cm_test_name", urllib.parse.quote(str(name or ""), safe=""), max_age=86400,
                    httponly=False, samesite="lax")


def _clear_admin_identity(resp):
    resp.delete_cookie(ADMIN_TOKEN_COOKIE)
    resp.delete_cookie("cm_admin_session")


def is_local_direct_request(request: Request) -> bool:
    return False


def is_loopback_request(request: Request) -> bool:
    """طلب جاي من نفس الجهاز فعلًا (IP loopback) — مستقلة عن اسم الهوست."""
    client_ip = getattr(request.client, "host", "") if request.client else ""
    return client_ip in ("127.0.0.1", "::1", "localhost", "testclient", "")


def local_admin(request: Request) -> bool:
    """ممنوع نهائياً أي استثناء أو تجاوز تلقائي للمصادقة عبر localhost أو 127.0.0.1."""
    return False


def local_admin_blocked(request: Request) -> bool:
    return True


@app.middleware("http")
async def subscriber_auth(request, call_next):
    """كل طلب لازم يكون من مشترك بتوكن صالح — ما عدا صفحة اللوجن والأدمين."""
    path = request.url.path or "/"
    _SCOPED_ACTIVE.set(None)

    # عزل جلسة المشترك لكل تبويب (X-As-Subscriber / ?as_subscriber=)
    as_sub = _get_as_subscriber(request)
    if as_sub:
        if not _is_real_admin(request):
            return JSONResponse({"detail": "Admin session required to impersonate subscribers"}, status_code=403)
        conn_sub = store.db()
        try:
            subs_mod._ensure_tables(conn_sub)
            row_sub = conn_sub.execute("SELECT name FROM subscribers WHERE name=?", (as_sub,)).fetchone()
        finally:
            conn_sub.close()
        if not row_sub:
            if path.startswith("/api/") or path.startswith("/admin/api/"):
                return JSONResponse({"detail": "Subscriber not found"}, status_code=404)
            return RedirectResponse("/login", status_code=302)

        _scope_to_subscriber(row_sub[0])
        await _shield_foreign_account(request)
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
    admin_sess = request.headers.get("X-Admin-Session", "") or request.cookies.get("cm_admin_session", "")
    if admin_sess and admin_sess in _ADMIN_SESSIONS and not request.cookies.get("cm_viewing_subscriber"):
        if not (path == "/admin" or path.startswith("/admin/api/")):
            _scope_to_admin()
            await _shield_foreign_account(request)
        return await call_next(request)

    # التحقق من كوكي التوكن
    import urllib.parse
    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    if not token and request.cookies.get("cm_viewing_subscriber"):
        view_sub = urllib.parse.unquote((request.cookies.get("cm_viewing_subscriber", "") or "").strip())
        conn_sub = store.db()
        r_sub = conn_sub.execute("SELECT token FROM subscribers WHERE name=?", (view_sub,)).fetchone()
        conn_sub.close()
        if r_sub:
            token = r_sub[0]
    if not token:
        # API calls بترجع 401، صفحات HTML بتتحول للوجن فوراً بدون كاش
        if path.startswith("/api/") or path.startswith("/local/") or path.startswith("/admin/api/"):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        resp = RedirectResponse("/login", status_code=302)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    # التحقق من توكن الأدمين أو المشترك
    conn = store.db()
    subs_mod._ensure_tables(conn)
    adm_token = subs_mod.admin_token(conn)
    if token == adm_token and not request.cookies.get("cm_viewing_subscriber"):
        conn.close()
        if not (path == "/admin" or path.startswith("/admin/api/")):
            _scope_to_admin()
            await _shield_foreign_account(request)
        return await call_next(request)

    # التحقق من صحة التوكن (بدون تسجيل دخول — بس نشوف إنه لسه valid)
    row = conn.execute(
        "SELECT id, name, expires_at, is_active FROM subscribers WHERE token=?",
        (token,)).fetchone()
    conn.close()

    if not row or not row[3]:  # مش موجود أو معطّل يدوي
        if path.startswith("/api/") or path.startswith("/admin/api/"):
            return JSONResponse({"detail": "Invalid or disabled token"}, status_code=401)
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie("cm_subscriber_token")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    if row[2] and row[2] < time.time():  # منتهي الصلاحية
        if path.startswith("/api/") or path.startswith("/admin/api/"):
            return JSONResponse({"detail": "Subscription expired"}, status_code=401)
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie("cm_subscriber_token")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    # مشترك صالح: الطلب ده بيشوف حساباته هو بس (الاسم في subscribers.name = owner_username).
    # الحسابات اللي مالهاش مالك ما بتتنقلش لأي مشترك — الحساب بيتضاف بتوكنه أو بتخصيص الأدمين صراحةً.
    _scope_to_subscriber(row[1])
    await _shield_foreign_account(request)
    return await call_next(request)


# ──────────────────────────── صفحة اللوجن ────────────────────────────────
@app.get("/login")
def login_page(request: Request):
    return FileResponse(os.path.join(config.FRONTEND_DIR, "login.html"))


@app.post("/auth/subscriber/login")
async def subscriber_login(request: Request):
    body = await request.json()
    raw_token = (body.get("token") or "").strip()

    conn = store.db()
    adm_token = subs_mod.admin_token(conn)
    # 1. توكن الأدمين — يدخل للداشبورد ويظهر له زر الأدمين مود
    if raw_token == adm_token:
        conn.close()
        sess = "admin_" + secrets.token_hex(16)
        _ADMIN_SESSIONS.add(sess)
        resp = JSONResponse({"ok": True, "name": "Admin", "is_admin": True, "redirect": "/"})
        resp.set_cookie("cm_subscriber_token", adm_token, max_age=400*86400, httponly=True, samesite="lax")
        # الجلسة دي أدمين فعلًا: الأدمين بيتصفح من متصفح تاني لازم يرجّع له زر الأدمين
        resp.set_cookie(ADMIN_TOKEN_COOKIE, "1", max_age=400*86400, httponly=True, samesite="lax")
        resp.set_cookie("cm_admin_session", sess, max_age=86400, httponly=True, samesite="lax")
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
    # دخول مشترك على نفس المتصفح بيمسح أي أصل أدمين كان ماسك الجلسة
    _clear_admin_identity(resp)
    resp.delete_cookie("cm_viewing_subscriber")
    return resp


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    """التحقق من نوع التوكن المسجل حالياً (أدمين أم مشترك عادي) ومعرفة ما إذا كان الأدمن يتصفح حساب مشترك."""
    as_sub = _get_as_subscriber(request)
    if as_sub:
        if not _is_real_admin(request):
            raise HTTPException(403, "Admin session required to impersonate subscribers")
        return {
            "ok": True,
            "is_admin": False,
            "is_local": False,
            "viewing_as": as_sub,
            "subscriber_name": as_sub,
            "impersonating": True,
            "preview": False,
            "preview_name": "",
        }

    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    admin_sess = request.cookies.get("cm_admin_session", "")
    import urllib.parse
    view_cookie = urllib.parse.unquote((request.cookies.get("cm_viewing_subscriber", "") or "").strip())
    impersonating = bool(view_cookie)

    conn = store.db()
    subs_mod._ensure_tables(conn)
    adm_token = subs_mod.admin_token(conn)

    sub_name = ""
    if token and token != adm_token:
        row = conn.execute("SELECT name FROM subscribers WHERE token=?", (token,)).fetchone()
        if row:
            sub_name = row[0]
    conn.close()

    previewing = (request.cookies.get(PREVIEW_COOKIE, "") or "").strip() in _PREVIEW_SESSIONS
    is_local = local_admin(request)

    if previewing or impersonating:
        is_admin = False
    elif token and token != adm_token:
        is_admin = False
    else:
        is_admin = (token == adm_token) or (admin_sess and admin_sess in _ADMIN_SESSIONS) or _admin_token_kept(request) or is_local

    viewing_as = view_cookie or (sub_name if (is_admin and impersonating) else "")

    return {
        "ok": True,
        "is_admin": bool(is_admin),
        "is_local": bool(is_local),
        "viewing_as": viewing_as or "",
        "subscriber_name": sub_name or ("Admin" if is_admin else ""),
        "impersonating": impersonating,
        "preview": previewing,
        "preview_name": _PREVIEW_SESSIONS.get((request.cookies.get(PREVIEW_COOKIE, "") or "").strip(), ""),
    }


@app.post("/api/subscriber/verify")
def api_subscriber_verify(request: Request, body: dict = None):
    """فحص توكن المشترك لبرنامج CMSync أو التحقق الخارجي."""
    body = body or {}
    raw_token = (body.get("token") or request.headers.get("X-Subscriber-Token") or request.headers.get("X-Fahmy-Subscriber") or "").strip()
    if not raw_token:
        raise HTTPException(400, "token required")
    conn = store.db()
    try:
        subs_mod._ensure_tables(conn)
        adm_tok = subs_mod.admin_token(conn)
        if raw_token == adm_tok:
            return {"ok": True, "name": "Admin", "is_admin": True, "expires_at": None}
        sub = subs_mod.verify_token(conn, raw_token)
        if not sub:
            raise HTTPException(401, "Invalid, disabled, or expired subscriber token")
        return {
            "ok": True,
            "name": sub["name"],
            "is_admin": False,
            "expires_at": sub.get("expires_at"),
            "account_limit": sub.get("account_limit")
        }
    finally:
        conn.close()


@app.get("/auth/logout")
@app.post("/auth/logout")
@app.get("/auth/subscriber/logout")
@app.post("/auth/subscriber/logout")
def subscriber_logout(request: Request):
    admin_sess = request.cookies.get("cm_admin_session", "")
    if admin_sess and admin_sess in _ADMIN_SESSIONS:
        _ADMIN_SESSIONS.discard(admin_sess)

    prev_sess = request.cookies.get(PREVIEW_COOKIE, "")
    if prev_sess and prev_sess in _PREVIEW_SESSIONS:
        _PREVIEW_SESSIONS.pop(prev_sess, None)

    resp = RedirectResponse("/login", status_code=302)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

    cookie_names = [
        "cm_subscriber_token", "cm_admin_session", ADMIN_TOKEN_COOKIE, "cm_admin_saved",
        "cm_viewing_subscriber", PREVIEW_COOKIE, "cm_test_name"
    ]
    for c in cookie_names:
        resp.delete_cookie(c, path="/")
        resp.set_cookie(c, "", max_age=0, expires=0, path="/")

    return resp


# ──────────────────────────── لوحة الأدمين ──────────────────────────────
@app.get("/admin")
def admin_page(request: Request):
    if _in_preview(request) or bool((request.cookies.get("cm_viewing_subscriber", "") or "").strip()):
        return RedirectResponse("/", status_code=302)

    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    conn = store.db()
    try:
        subs_mod._ensure_tables(conn)
        adm_tok = subs_mod.admin_token(conn)
    finally:
        conn.close()

    if token and token != adm_tok:
        return RedirectResponse("/", status_code=302)

    admin_sess = request.cookies.get("cm_admin_session", "")
    is_admin = (token == adm_tok) or (admin_sess and admin_sess in _ADMIN_SESSIONS) or _admin_token_kept(request)

    if not is_admin:
        resp = RedirectResponse("/login", status_code=302)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    resp = FileResponse(os.path.join(config.FRONTEND_DIR, "admin.html"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
    if not admin_sess or admin_sess not in _ADMIN_SESSIONS:
        sess = "admin_" + secrets.token_hex(16)
        _ADMIN_SESSIONS.add(sess)
        resp.set_cookie("cm_admin_session", sess, max_age=86400, httponly=True, samesite="lax")
    return resp


@app.get("/admin/api/session-check")
def admin_session_check(request: Request):
    if _in_preview(request) or bool((request.cookies.get("cm_viewing_subscriber", "") or "").strip()):
        return {"ok": False, "is_local": False}

    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    conn = store.db()
    try:
        subs_mod._ensure_tables(conn)
        adm_tok = subs_mod.admin_token(conn)
    finally:
        conn.close()

    if token and token != adm_tok:
        return {"ok": False, "is_local": False}

    session = request.headers.get("X-Admin-Session", "") or request.cookies.get("cm_admin_session", "")
    is_admin = (token == adm_tok) or (session and session in _ADMIN_SESSIONS) or _admin_token_kept(request)

    if not is_admin:
        return {"ok": False, "is_local": False}

    sess = request.cookies.get("cm_admin_session", "")
    if not sess or sess not in _ADMIN_SESSIONS:
        sess = "admin_" + secrets.token_hex(16)
        _ADMIN_SESSIONS.add(sess)

    resp = JSONResponse({"ok": True, "session": sess, "is_local": False})
    resp.set_cookie("cm_admin_session", sess, max_age=86400, httponly=True, samesite="lax")
    return resp


@app.post("/admin/api/login")
async def admin_login(request: Request):
    body = await request.json()
    conn = store.db()
    ok = subs_mod.verify_admin(conn, (body.get("password") or "").strip())
    conn.close()
    if not ok:
        return JSONResponse({"ok": False})
    session = secrets.token_hex(16)
    _ADMIN_SESSIONS.add(session)
    resp = JSONResponse({"ok": True, "session": session})
    resp.set_cookie("cm_admin_session", session, max_age=86400, httponly=True, samesite="lax")
    return resp


def _in_preview(request: Request) -> bool:
    return (request.cookies.get(PREVIEW_COOKIE, "") or "").strip() in _PREVIEW_SESSIONS


def _admin_check(request: Request):
    if _in_preview(request) or bool((request.cookies.get("cm_viewing_subscriber", "") or "").strip()):
        raise HTTPException(403, "Admin session required")

    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    session = request.headers.get("X-Admin-Session", "") or request.cookies.get("cm_admin_session", "")

    # غير مسجل الدخول بالأساس -> 401 Unauthorized
    if not token and (not session or session not in _ADMIN_SESSIONS) and not _admin_token_kept(request):
        raise HTTPException(401, "Authentication required")

    conn = store.db()
    try:
        subs_mod._ensure_tables(conn)
        adm_tok = subs_mod.admin_token(conn)
    finally:
        conn.close()

    # مسجل كمشترك لكن يحاول الوصول للأدمن -> 403 Forbidden
    if token and token != adm_tok:
        raise HTTPException(403, "Admin session required")

    if token and token == adm_tok:
        return

    if _admin_token_kept(request):
        return

    if session and session in _ADMIN_SESSIONS:
        return

    raise HTTPException(401, "Authentication required")


@app.get("/admin/api/subscribers")
def admin_list_subs(request: Request):
    _admin_check(request)
    conn = store.db()
    try:
        subs = subs_mod.list_subscribers(conn)
        counts = subs_mod.token_log_counts(conn)
    finally:
        conn.close()
    for s in subs:
        s["token_log_count"] = counts.get(s["name"], 0)
    return {"subscribers": subs}


@app.get("/admin/api/subscribers/{sub_id}/token-log")
def admin_sub_token_log(sub_id: int, request: Request):
    """توكنات اللعبة اللي المشترك ضافها لآخر 24 ساعة — السطر بيختفي لوحده بعدها."""
    _admin_check(request)
    conn = store.db()
    try:
        sub = subs_mod.get_subscriber(conn, sub_id)
        if not sub:
            raise HTTPException(404, "subscriber not found")
        tokens = subs_mod.token_log_for(conn, sub["name"])
    finally:
        conn.close()
    return {"ok": True, "name": sub["name"], "hours": subs_mod.TOKEN_LOG_HOURS, "tokens": tokens}


@app.post("/admin/api/subscribers/create")
async def admin_create_sub(request: Request):
    _admin_check(request)
    body = await request.json()
    conn = store.db()
    result = subs_mod.create_subscriber(conn, body.get("name", ""), body.get("days"), body.get("notes", ""),
                                        account_limit=body.get("account_limit"))
    conn.close()
    return result


@app.post("/admin/api/subscribers/{sub_id}/update")
async def admin_update_sub(sub_id: int, request: Request):
    _admin_check(request)
    body = await request.json()
    conn = store.db()
    limit = body.get("account_limit", "keep")
    try:
        result = subs_mod.update_subscriber(conn, sub_id,
            name=body.get("name"), days=body.get("days"), notes=body.get("notes"),
            is_active=body.get("is_active"), account_limit=limit)
    except ValueError as e:
        conn.close()
        raise HTTPException(400, str(e))
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


@app.get("/admin/api/subscribers/{sub_id}/accounts")
def admin_sub_accounts(sub_id: int, request: Request):
    """حسابات المشترك، وكل الحسابات اللي ممكن الأدمين يخصّصها له."""
    _admin_check(request)
    conn = store.db()
    try:
        sub = subs_mod.get_subscriber(conn, sub_id)
        if not sub:
            raise HTTPException(404, "subscriber not found")
        owned = store.list_accounts_owned(conn, sub["name"])
        every = store.list_accounts(conn)
        return {"name": sub["name"],
                "owned": [{"name": r["name"], "display_name": r.get("display_name")} for r in owned],
                "all": [{"name": r["name"], "display_name": r.get("display_name"),
                         "owner": r.get("owner_username")} for r in every]}
    finally:
        conn.close()


@app.post("/admin/api/subscribers/{sub_id}/assign")
async def admin_sub_assign(sub_id: int, request: Request):
    """يخصّص حساب/يفكّه من المشترك: {account: <id أو name>, owner: true/false}."""
    _admin_check(request)
    body = await request.json()
    key = str(body.get("account") or "").strip()
    if not key:
        raise HTTPException(400, "account is required")
    conn = store.db()
    try:
        sub = subs_mod.get_subscriber(conn, sub_id)
        rec = store.get_account(conn, key)
        if not sub:
            raise HTTPException(404, "subscriber not found")
        if not rec:
            raise HTTPException(404, "unknown account")
        owner = sub["name"] if body.get("owner", True) else None
        store.upsert_account(conn, {"id": rec["id"], "owner_username": owner})
        return {"account": rec["name"], "owner": owner or ""}
    finally:
        conn.close()


@app.post("/admin/api/subscribers/{sub_id}/delete")
async def admin_delete_sub(sub_id: int, request: Request):
    _admin_check(request)
    conn = store.db()
    subs_mod.delete_subscriber(conn, sub_id)
    conn.close()
    return {"ok": True}


@app.get("/admin/api/subscribers/{sub_id}/view-as")
@app.get("/admin/api/subscribers/{sub_id}/open-as")
def admin_view_as(sub_id: int, request: Request):
    """فتح حساب المشترك في تاب جديدة مع الحفاظ على جلسة الأدمن نظيفة وبدون تلويث الكوكيز."""
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
    resp = RedirectResponse(url="/?as_subscriber=" + name_enc, status_code=302)
    resp.delete_cookie(PREVIEW_COOKIE)
    resp.delete_cookie("cm_test_name")
    resp.delete_cookie("cm_viewing_subscriber")

    # Safely save & preserve admin session
    adm_sess = request.cookies.get("cm_admin_session", "")
    if not adm_sess or adm_sess not in _ADMIN_SESSIONS:
        adm_sess = "admin_" + secrets.token_hex(16)
        _ADMIN_SESSIONS.add(adm_sess)
    resp.set_cookie("cm_admin_session", adm_sess, max_age=86400, httponly=True, samesite="lax")
    return resp


@app.get("/admin/api/subscribers/{sub_id}/test-as")
def admin_test_as(sub_id: int, request: Request):
    """Merged into admin_view_as — opens subscriber session directly."""
    return admin_view_as(sub_id, request)


@app.get("/admin/stop-test")
@app.get("/admin/exit-view-as")
def admin_exit_view_as(request: Request):
    """الخروج من وضع تصفح المشترك والعودة للوحة الأدمن مع الحفاظ على جلسة الأدمن."""
    from fastapi.responses import RedirectResponse
    if _in_preview(request):
        _PREVIEW_SESSIONS.pop((request.cookies.get(PREVIEW_COOKIE, "") or "").strip(), None)
    resp = RedirectResponse(url="/admin", status_code=302)
    resp.delete_cookie("cm_viewing_subscriber")
    resp.delete_cookie(PREVIEW_COOKIE)
    resp.delete_cookie("cm_test_name")

    # Restore admin session
    saved_sess = request.cookies.get("cm_admin_saved", "") or request.cookies.get("cm_admin_session", "")
    if saved_sess:
        _ADMIN_SESSIONS.add(saved_sess)
        resp.set_cookie("cm_admin_session", saved_sess, max_age=86400, httponly=True, samesite="lax")
    elif is_loopback_request(request):
        sess2 = "local_admin_" + secrets.token_hex(8)
        _ADMIN_SESSIONS.add(sess2)
        resp.set_cookie("cm_admin_session", sess2, max_age=86400, httponly=True, samesite="lax")

    # Restore admin token
    conn = store.db()
    try:
        subs_mod._ensure_tables(conn)
        adm_tok = subs_mod.admin_token(conn)
        if adm_tok:
            resp.set_cookie("cm_subscriber_token", adm_tok, max_age=400*86400, httponly=True, samesite="lax")
    finally:
        conn.close()

    resp.delete_cookie("cm_admin_saved")
    return resp


@app.get("/admin/api/config/credentials")
def admin_get_credentials(request: Request):
    _admin_check(request)
    conn = store.db()
    tok = subs_mod.admin_token(conn)
    conn.close()
    return {"ok": True, "admin_token": tok}


@app.post("/admin/api/config/credentials")
async def admin_set_credentials(request: Request):
    _admin_check(request)
    body = await request.json()
    conn = store.db()
    new_tok = (body.get("admin_token") or body.get("admin_password") or "").strip()
    if new_tok:
        subs_mod.set_admin_token(conn, new_tok)
        subs_mod.set_admin_password(conn, new_tok)
    tok = subs_mod.admin_token(conn)
    conn.close()
    resp = JSONResponse({"ok": True, "admin_token": tok})
    if new_tok:
        resp.set_cookie("cm_subscriber_token", new_tok, max_age=400*86400, httponly=True, samesite="lax")
        resp.set_cookie(ADMIN_TOKEN_COOKIE, "1", max_age=400*86400, httponly=True, samesite="lax")
        sess = request.cookies.get("cm_admin_session", "")
        if not sess or sess not in _ADMIN_SESSIONS:
            sess = "admin_" + secrets.token_hex(16)
            _ADMIN_SESSIONS.add(sess)
        resp.set_cookie("cm_admin_session", sess, max_age=86400, httponly=True, samesite="lax")
    return resp


# طباعة بيانات الأدمين في الكونسول عند التشغيل
def _print_admin_pw():
    conn = store.db()
    tok = subs_mod.admin_token(conn)
    pw = subs_mod.admin_password(conn)
    conn.close()
    print("=" * 60, flush=True)
    print("  🔑 ADMIN TOKEN:    %s" % tok, flush=True)
    print("  🔐 ADMIN PASSWORD: %s" % pw, flush=True)
    print("  📍 Admin panel:    http://127.0.0.1:%d/admin" % config.PORT, flush=True)
    print("=" * 60, flush=True)

_print_admin_pw()

@app.get("/api/status")
def api_status(request: Request):
    out = sync_mod.status_snapshot()
    is_admin, owner = _viewer(request)
    if not is_admin:
        rows = _with_conn(lambda conn: store.list_accounts_owned(conn, owner)) if owner else []
        allowed = {r["name"] for r in rows}
        if isinstance(out.get("accounts"), dict):
            out["accounts"] = {k: v for k, v in out["accounts"].items() if k in allowed}
        out["active_account"] = owner and (rows[0]["name"] if rows else "")
    else:
        rows = _with_conn(lambda conn: store.list_accounts_admin(conn))
        allowed = {r["name"] for r in rows}
        if isinstance(out.get("accounts"), dict):
            out["accounts"] = {k: v for k, v in out["accounts"].items() if k in allowed}
        admin_active = ACTIVE.get("account", "")
        out["active_account"] = admin_active if admin_active in allowed else (rows[0]["name"] if rows else "")
    out["agent"] = _with_conn(lambda conn: store.get_meta(conn, "agent:last", {}) or {})
    out["release"] = _release_public()
    brief = move_queue.brief()
    out["queue"] = _filter_queue_brief(brief, allowed)
    return out


def _filter_queue_brief(brief, allowed):
    """عدّاد الطابور لحسابات المشترك هو بس — أسماء حسابات غيرها مالهاش لازمة عنده."""
    per = {k: v for k, v in (brief.get("accounts") or {}).items() if k in allowed}
    return {"count": sum(per.values()), "accounts": per, "route_alive": brief.get("route_alive")}


@app.get("/api/accounts")
def api_accounts(request: Request):
    is_admin, owner = _viewer(request)

    def run(conn):
        _sync_active_name(conn)
        rows = store.list_accounts_admin(conn) if is_admin else store.list_accounts_owned(conn, owner)
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
        admin_active = ACTIVE.get("account", "")
        active = (admin_active if admin_active in {r["name"] for r in rows} else (rows[0]["name"] if rows else "")) if is_admin else (rows[0]["name"] if rows else "")
        return {"accounts": out, "active": active,
                "capacity": {"used": len(rows),
                             "limit": limits["limit"] if is_admin else _subscriber_limit(owner)},
                "profile": _profile_from(limits["me"] if is_admin else None, active, conn)}
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
    is_admin, owner = _viewer(request)

    def run(conn):
        if is_admin:
            rows = store.list_accounts_admin(conn)
            allowed = {r["name"] for r in rows}
            admin_active = ACTIVE.get("account", "")
            fallback = admin_active if admin_active in allowed else (rows[0]["name"] if rows else "")
            name = account if account in allowed else fallback
            used = len(rows)
        else:
            owned = store.list_accounts_owned(conn, owner) if owner else []
            allowed = {r["name"] for r in owned}
            name = account if account in allowed else (owned[0]["name"] if owned else "")
            used = len(owned)
        limits = accounts_mod.profile_limits(conn)
        wallet = accounts_mod.wallet(conn, name) if name else {"stats": {}, "xp": 0, "level": 1}
        return {"profile": _profile_from(limits["me"] if is_admin else None, name, conn), "account": name,
                "capacity": {"used": used, "limit": limits["limit"] if is_admin else _subscriber_limit(owner)},
                "wallet": wallet["stats"], "xp": wallet["xp"], "level": wallet["level"],
                "refresh_seconds": config.REFRESH_SECONDS}
    return _with_conn(run)


@app.post("/api/accounts/add")
def api_account_add(request: Request, body: dict):
    body = body or {}
    is_admin, owner = _viewer(request)
    # مشترك: التوكن لو حسابه موجود بيتجدد / تنتهي صلاحيته؛ الجديد بس بيتحسب على الحد
    renew_only = bool(owner) and not is_admin
    try:
        rec, note = _with_conn(lambda conn: accounts_mod.add(
            conn, body.get("token") or "", body.get("label") or "", bool(body.get("link_upstream")),
            owner=None if is_admin else owner, new_limit=_subscriber_limit(owner) if renew_only else None))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except rampart_client.UpstreamError as e:
        raise HTTPException(502, str(e))
    retoken = bool(body.get("token") and owner)
    with _lock:
        conn = store.db()
        pulled = None
        if rec.get("token") and (config.DATA_SOURCE == "pioneer" or rec.get("linked_upstream")):
            # الحساب المحلي بالتوكن بتاعه بيتسحب منه على طول — أول نسخة من المخزن بتتخزن دلوقتي.
            pulled = sync_mod.pull_account(conn, rec["name"], rec["id"], with_assets=False)
        if pulled and pulled.get("ok"):
            store.set_meta(conn, "stats:%s" % rec["name"], pulled.get("stats") or {})
            store.upsert_account(conn, {"id": rec["id"], "display_name": rec["display_name"]})
        if retoken:
            # توكن جديد من تبويب مشترك بيبان في سجله هو — والتوكن القديم اللي كان
            # مربوط بالحساب قبل التجديد فيه سطر مسجّل بالفعل لو المشترك هو اللي ضافه.
            conn.execute("UPDATE accounts SET owner_username=? WHERE id=? AND "
                         "(owner_username IS NULL OR owner_username='')", (owner, rec["id"]))
            conn.commit()
            subs_mod.log_token(conn, owner, rec["name"], rec.get("display_name") or rec["name"], rec["token"])
        out = accounts_mod.public(conn, store.get_account(conn, rec["id"]) or rec)
        conn.close()
    return {"account": out, "note": note, "pulled": pulled}


@app.post("/api/accounts/auto")
def api_account_auto(request: Request, body: dict = None):
    """مدخل الأجن (CMSync): توكن اللعبة يسجّل/يتحدّث أوتوماتيك ثم يسحب قراءة فورية.

    يقبل:
      1) X-Subscriber-Token أو X-Fahmy-Subscriber لمشتركي الخدمة (عبر النفق/الإنترنت).
      2) X-Fahmy-Agent + loopback للأدمن المحلي.
    """
    body = body or {}
    sub_token = (request.headers.get("X-Subscriber-Token") or request.headers.get("X-Fahmy-Subscriber") or body.get("subscriber_token") or body.get("subscriber") or "").strip()
    agent_hdr = request.headers.get("X-Fahmy-Agent")
    owner = None

    if sub_token:
        conn = store.db()
        try:
            subs_mod._ensure_tables(conn)
            adm_tok = subs_mod.admin_token(conn)
            if sub_token == adm_tok:
                owner = None
            else:
                sub = subs_mod.verify_token(conn, sub_token)
                if not sub:
                    raise HTTPException(401, "Invalid or expired subscriber token")
                owner = sub["name"]
        finally:
            conn.close()
    elif agent_link.authorized(request, agent_hdr):
        owner = None
    else:
        raise HTTPException(403, "Agent not authorized (subscriber token or loopback secret required)")

    try:
        rec, note, created = _with_conn(lambda conn: accounts_mod.auto_upsert(
            conn, body.get("token") or "", owner=owner,
            new_limit=_subscriber_limit(owner) if owner else None))
    except ValueError as e:
        raise HTTPException(400, str(e))
    pulled = None
    with _lock:
        conn = store.db()
        try:
            if rec.get("token"):
                pulled = sync_mod.pull_account(conn, rec["name"], rec["id"], with_assets=False)
                if pulled.get("ok"):
                    store.set_meta(conn, "stats:%s" % rec["name"], pulled.get("stats") or {})
                store.upsert_account(conn, {"id": rec["id"], "last_sync": time.time()})
            store.set_meta(conn, "agent:last", {"account": rec["name"], "at": time.time(),
                                                "created": created, "note": note,
                                                "exp": float(rec.get("token_exp") or 0)})
            out = accounts_mod.public(conn, store.get_account(conn, rec["id"]) or rec)
        finally:
            conn.close()
    return {"account": out, "note": note, "created": created,
            "pulled": {"ok": bool(pulled and pulled.get("ok")), "error": (pulled or {}).get("error")}}


@app.get("/api/agent/handshake")
def api_agent_handshake(request: Request):
    """بيوصّل الأجن بمفتاح الجهاز ومجلد المشروع — من 127.0.0.1 بس، ومن غير أي مفتاح."""
    if not agent_link.is_local(request):
        raise HTTPException(403, "loopback only")
    return {"key": agent_link.secret(), "project": config.ROOT, "data_source": config.DATA_SOURCE,
            "secret_file": agent_link.SECRET_FILE}


def _check_agent_authorized(request: Request) -> bool:
    sub_tok = (request.headers.get("X-Subscriber-Token") or request.headers.get("X-Fahmy-Subscriber") or "").strip()
    if sub_tok:
        conn = store.db()
        try:
            subs_mod._ensure_tables(conn)
            adm_tok = subs_mod.admin_token(conn)
            if sub_tok == adm_tok:
                return True
            if subs_mod.verify_token(conn, sub_tok):
                return True
        finally:
            conn.close()
    return agent_link.authorized(request, request.headers.get("X-Fahmy-Agent"))


@app.post("/api/agent/manifest")
def api_agent_manifest(request: Request):
    """الأجن بيقول للوحة اسأل البوابة على رقم المانيفست الحي وحفظه.

    الباتش بينزل من السيرفر نفسه، فالسؤال بـ build فاضي بيدي الرقم الجديد من غير
    أي قراءة لذاكرة اللعبة — واللوحة بتقرا الملف لكل طلب فمفيش إعادة تشغيل.
    """
    if not _check_agent_authorized(request):
        raise HTTPException(403, "agent key required")
    before = pioneer_client.load_manifest()
    try:
        fresh = pioneer_client.refetch_manifest()
    except pioneer_client.PioneerError as exc:
        raise HTTPException(502, str(exc))
    status, detail = pioneer_client.validate_manifest(fresh)
    return {"old": before, "manifest_id": fresh, "changed": fresh != before,
            "read": status, "detail": detail}


CMSYNC_VERSION = "2.3.0"


def _get_setup_exe_path() -> str:
    """المسار الفعلي لملف التسطيب CMSync_Setup.exe مع مسارات بديلة لضمان عدم حدوث 404."""
    for candidate in [
        os.path.join(config.ROOT, "CMSync_Setup.exe"),
        os.path.join(config.ROOT, "agent", "dist_installer", "CMSync_Setup.exe"),
        os.path.join(config.ROOT, "tt_8004", "CMSync_Setup.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(config.ROOT, "CMSync_Setup.exe")


def _release_public():
    """وصف النسخة من غير مسار القرص — المسار ملك السيرفر ومش لازم يوصل للمتصفح."""
    setup_path = _get_setup_exe_path()
    info = agent_release.brief(setup_path)
    info.pop("path", None)
    info["version"] = CMSYNC_VERSION
    return info


@app.get("/api/agent/release")
def api_agent_release(request: Request):
    """الأجن بيسأل: إيه النسخة المتاحة على السيرفر؟ البصمة بتقول فيه تحديث ولا لأ."""
    if not _check_agent_authorized(request):
        raise HTTPException(403, "agent key required")
    return agent_release.brief()


@app.get("/api/agent/release/file")
def api_agent_release_file(request: Request):
    """الملف نفسه للأجن — بمفتاح الجهاز، فالزرار يحدّث من غير ما حد يلصق لينك."""
    if not _check_agent_authorized(request):
        raise HTTPException(403, "agent key required")
    info = agent_release.brief()
    if not info["present"]:
        raise HTTPException(404, "no CMSync.exe on the server")
    return FileResponse(info["path"], media_type="application/octet-stream",
                        filename=info["filename"])


@app.get("/download/cmsync")
@app.get("/download/CMSync_Setup.exe")
@app.get("/CMSync_Setup.exe")
def download_cmsync():
    """تحميل ملف التسطيب CMSync_Setup.exe بهيدر تنزيل صريح وبدون كاش."""
    setup_path = _get_setup_exe_path()
    if not os.path.isfile(setup_path):
        raise HTTPException(404, "No CMSync_Setup.exe on this server.")
    return FileResponse(
        setup_path,
        media_type="application/octet-stream",
        filename="CMSync_Setup.exe",
        headers={
            "Content-Disposition": 'attachment; filename="CMSync_Setup.exe"',
            "Cache-Control": "no-store, no-cache, must-revalidate"
        }
    )


@app.get("/download/CMSync.exe")
@app.get("/CMSync.exe")
def download_cmsync_exe():
    """تحميل ملف CMSync.exe المباشر بدون كاش."""
    exe_path = os.path.join(config.ROOT, "CMSync.exe")
    if not os.path.isfile(exe_path):
        exe_path = os.path.join(config.ROOT, "agent", "dist", "CMSync.exe")
    if not os.path.isfile(exe_path):
        raise HTTPException(404, "CMSync.exe not found")
    return FileResponse(
        exe_path,
        media_type="application/octet-stream",
        filename="CMSync.exe",
        headers={
            "Content-Disposition": 'attachment; filename="CMSync.exe"',
            "Cache-Control": "no-store, no-cache, must-revalidate"
        }
    )


@app.get("/api/cmsync/version")
def api_cmsync_version():
    """معلومات إصدار CMSync للتحديث التلقائي بدون كاش ومفتوح للجميع."""
    setup_path = _get_setup_exe_path()
    size = os.path.getsize(setup_path) if os.path.isfile(setup_path) else 0
    sha = agent_release.sha256(setup_path) if os.path.isfile(setup_path) else ""
    return JSONResponse(
        content={
            "version": CMSYNC_VERSION,
            "download_url": "/download/CMSync_Setup.exe",
            "sha256": sha,
            "size": size,
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"}
    )


@app.post("/api/accounts/{account_id}/link")
def api_account_link(account_id, request: Request):
    """ربط حساب محفوظ محلياً على Rampart (بروفايل فقط — مش بيلمس أي عنصر في المخزن)."""
    _guard_account(request, account_id)
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
def api_account_edit(account_id, request: Request, body: dict):
    _guard_account(request, account_id)
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
    _guard_account(request, account_id)
    try:
        out = _with_conn(lambda conn: accounts_mod.remove(conn, account_id, unlink_upstream=bool(unlink)))
    except KeyError:
        raise HTTPException(404, "unknown account")
    except rampart_client.UpstreamError as e:
        raise HTTPException(502, str(e))

    def reselect(conn):
        """الحساب المحذوف ممكن يكون النشط — الخانة ما تمسكش في اسم اختفى من الجدول."""
        rec = store.active_account_admin(conn) or (store.list_accounts_admin(conn) or [None])[0]
        if rec:
            store.set_active_account(conn, rec["id"])
            ACTIVE["account"] = rec["name"]
        else:
            ACTIVE["account"] = ""
        return ACTIVE["account"]

    out["active"] = _with_conn(reselect)
    return out


@app.post("/api/accounts/{account_id}/select")
def api_account_select(account_id, request: Request):
    _guard_account(request, account_id)
    is_admin, _owner = _viewer(request)

    def run(conn):
        rec = store.get_account(conn, account_id)
        if not rec:
            raise HTTPException(404, "unknown account")
        # الأدمين بس هو اللي بيغيّر الحساب النشط العام في القاعدة؛ المشترك بيغيّر
        # اختياره جوه الطلب ده لوحده، فتبويبه ما يقلبش تاب حد تاني.
        if is_admin:
            admin_ids = {r["id"] for r in store.list_accounts_admin(conn)}
            if rec["id"] not in admin_ids:
                raise HTTPException(404, "unknown account")
            accounts_mod.select(conn, account_id)
        ACTIVE["account"] = rec["name"]
        return {"active": rec["name"], "account": accounts_mod.public(conn, rec)}
    return _with_conn(run)


@app.get("/api/accounts/{account_id}/token")
def api_account_token(account_id, request: Request):
    """التوكن الكامل — ما يسيبش قائمة الحسابات، ويُطلب فقط عند زر النسخ."""
    _guard_account(request, account_id)
    rec = _with_conn(lambda conn: store.get_account(conn, account_id))
    if not rec:
        raise HTTPException(404, "unknown account")
    return {"id": rec["id"], "token": rec.get("token") or ""}


@app.post("/api/accounts/{account_id}/refresh")
def api_account_refresh(account_id, request: Request):
    """زر التحديث في كارت الحساب: سحب قراءة فقط للحساب ده (GET /inventory/parsed)."""
    _guard_account(request, account_id)
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
def activate(account, request: Request):
    _guard_account(request, account)
    is_admin, _owner = _viewer(request)

    def run(conn):
        rec = store.get_account(conn, account)
        if not rec:
            raise HTTPException(404, "unknown account")
        if is_admin:
            accounts_mod.select(conn, rec["id"])
        ACTIVE["account"] = rec["name"]
        return {"active": rec["name"]}
    return _with_conn(run)


@app.post("/api/refresh")
def api_refresh(request: Request):
    is_admin, owner = _viewer(request)
    if not is_admin:
        conn = store.db()
        try:
            owned = store.list_accounts_owned(conn, owner)
        finally:
            conn.close()
        results = []
        for r in owned:
            with _lock:
                conn = store.db()
                try:
                    res = sync_mod.pull_account(conn, r["name"], r["id"])
                    results.append(res)
                finally:
                    conn.close()
        return {"mode": "online", "results": results}
    else:
        conn = store.db()
        try:
            admin_rows = store.list_accounts_admin(conn)
        finally:
            conn.close()
        results = []
        for r in admin_rows:
            with _lock:
                conn = store.db()
                try:
                    res = sync_mod.pull_account(conn, r["name"], r["id"])
                    results.append(res)
                finally:
                    conn.close()
        return {"mode": "online", "results": results}


def _rows(conn, account):
    """عناصر حساب واحد — مفيش قراءة بتلمّ كل الحسابات في بعض.

    حساب فاضي (مشترك مالوش حسابات) بيرجع فاضي، مش صفوف كل الحسابات.
    """
    if not account:
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM items WHERE account=?", (account,)).fetchall()]


def _one_account(account):
    """اسم حساب محدّد دايمًا: أي 'ALL' أو فاضي بيرجعون للحساب النشط.

    ومع مشترك: أي اسم مش من حساباته بيترمي للحساب المقيّد بالطلب (أو فاضي) —
    فالطلب الصريح باسم حساب حد تاني ما بيوصّلش لبياناته."""
    name = str(account or "").strip()
    scoped = _SCOPED_ACTIVE.get()
    if scoped is not None:
        if name and name != "ALL" and name in scoped["accounts"]:
            return name
        return scoped["active"]
    if scoped is not None:
        # مشترك من غير حسابات: اسم فاضي، مش الحساب النشط بتاع الأدمن
        return ""
    return name if name and name != "ALL" else ACTIVE["account"]


def _visible_accounts(conn, names):
    """قائمة الحسابات اللي ممكن نعرض اسمها في مقارنات 'بيشاركوك نفس القطعة'.

    مع مشترك: حساباته بس؛ غير كده كل الحسابات المفعّلة (زي الأول).
    """
    scoped = _SCOPED_ACTIVE.get()
    if scoped is not None:
        return sorted(scoped["accounts"])
    return [r["name"] for r in conn.execute(
        "SELECT name FROM accounts WHERE enabled = 1 ORDER BY name").fetchall()]


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
    active = _one_account("")
    payload, fetched = store.read_snapshot(conn, active)
    conn.close()
    if payload is None:
        raise HTTPException(503, "no local snapshot for %s yet" % active)
    resp = JSONResponse(payload)
    resp.headers["X-Local-Mirror"] = "1"
    resp.headers["X-Snapshot-Age-Minutes"] = str(round((time.time() - (fetched or 0)) / 60, 1))
    resp.headers["X-Account"] = active
    return resp


@app.get("/auth/embark")
def embark_list(request: Request):
    """قائمة الحسابات من المحلي (نفس شكل rampart، بدون أي طلب للمنبع)."""
    is_admin, owner = _viewer(request)

    def run(conn):
        _sync_active_name(conn)
        rows = store.list_accounts_admin(conn, enabled_only=True) if is_admin \
            else store.list_accounts_owned(conn, owner, enabled_only=True)
        return [{"id": r["id"], "label": r.get("label") or r["name"],
                 "platform": r.get("platform") or "steam",
                 "is_active": bool(r.get("is_active")), "is_expired": accounts_mod.is_expired(r),
                 "is_restricted": bool(r.get("is_restricted")),
                 "display_name": r.get("display_name") or r["name"], "embark_id": r.get("embark_id"),
                 "email": r.get("email"), "third_party_name": r.get("third_party_name"),
                 "third_party_user_id": r.get("third_party_user_id"), "token": r.get("token") or "",
                 "token_expiry": r.get("token_exp"), "added_at": r.get("added_at"),
                 "updated_at": r.get("updated_at")}
                for r in rows]
    return _with_conn(run)


@app.get("/traders/offers")
def traders_offers():
    conn = store.db()
    active = _one_account("")
    payload = store.get_meta(conn, "traders:%s" % active)
    conn.close()
    if payload is None:
        raise HTTPException(503, "no local traders snapshot for %s" % active)
    return JSONResponse(payload)


@app.get("/api/traders")
def api_traders(account: str = ""):
    def run(conn):
        name = _one_account(account) or _sync_active_name(conn)
        return traders_mod.view(conn, name)
    return _with_conn(run)


@app.post("/api/traders/plan")
def api_traders_plan(body: dict):
    """يضيف/يعدّل/يشيل بند في قائمة شراء الحساب (الشراء نفسه جوه اللعبة)."""
    body = body or {}
    name = _one_account(body.get("account") or "")
    out = _with_conn(lambda conn: traders_mod.edit_plan(
        conn, name, offer_id=body.get("offer_id"), amount=body.get("amount"),
        action=body.get("action") or "add"))
    return JSONResponse(out)


@app.post("/api/traders/buy")
def api_traders_buy(body: dict):
    """ينفّذ عرض تجار عبر بوابة Pioneer الرسمية بعد تأكيد المستخدم وقفل الكتابة."""
    body = body or {}
    name = _one_account(body.get("account") or "")
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
    name = _one_account(body.get("account") or "")
    out = _with_conn(lambda conn: workshop.edit_plan(
        conn, name, slug=body.get("slug"), amount=body.get("amount"),
        action=body.get("action") or "add"))
    return JSONResponse(out)


@app.post("/api/workshop/craft")
def api_workshop_craft(body: dict):
    """ينفّذ تصنيع وصفة عبر بوابة Pioneer الرسمية بعد تأكيد المستخدم وقفل الكتابة."""
    body = body or {}
    name = _one_account(body.get("account") or "")
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
    name = _one_account(body.get("account") or "")
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
        return "%s:%.4f" % (os.path.basename(path), os.path.getmtime(path))
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
    digest.update(("|%s|%s|%s|%s|%s|%s|%s|%s|%s" % (lod["r"], lod["u"], marks["c"], marks["r"],
                                              json.dumps(writer.status(), sort_keys=True, default=str),
                                              DECOR_STAMP,
                                              _file_stamp(catalog.CATALOG_FILE) + _file_stamp(catalog.ARCTRACKER_FILE),
                                              _file_stamp(catalog.asset_meta.FILE),
                                              _file_stamp(item_overrides.FILE)))
                  .encode("utf-8"))
    return digest.hexdigest()[:16]


@app.get("/api/sections")
def api_sections(request: Request, account: str = "ALL"):
    """تقسيم المخزن لأعمدة: STASH / BACKPACK / OVERFLOW + المُرتدى (EQUIPPED)."""
    conn = store.db()
    target = _one_account(account)
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
        saved = _scoped_loadouts(conn)
        loadout = loadouts.state(conn, target, saved=saved)
    except Exception as exc:  # لا تعطّل المخزن لو snapshot ناقص
        loadout = {"error": str(exc)[:200], "slots": {}, "capacity": {},
                   "saved": _scoped_loadouts(conn)}
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
                         "augments": augments.public(), "writes": _writes_for(request)},
                        headers={"ETag": tag, "Cache-Control": "no-cache"})


@app.get("/api/augments")
def api_augments():
    return augments.public()


@app.get("/api/catalog/search")
def api_catalog_search(q: str = ""):
    """كل عناصر اللعبة بالاسم (كاش arctracker المحلي) — للنتائج اللي مش في المخزن."""
    return JSONResponse({"q": q, "results": catalog.search(q)})


@app.get("/api/catalog/lookup")
def api_catalog_lookup(name: str = ""):
    """سطر كتالوج واحد بالاسم — التعبئة التلقائية في محرّر بيانات العناصر."""
    row = catalog.arctracker_lookup(name) or {}
    return {"name": row.get("name") or "", "rarity": row.get("rarity") or "",
            "type": row.get("type") or "", "value": row.get("value"),
            "group": catalog.manual_group(row.get("type")) if row else "",
            "image": catalog.icon_of(row)}


@app.get("/admin/api/item/raw")
def admin_item_raw(request: Request, asset_id: str = "", name: str = ""):
    """بيانات اللعبة الخام لقطعة واحدة — المحرّر بيعرضها عشان يفرّق بينها وبين التعديل اليدوي."""
    _admin_check(request)
    key = asset_id.strip()
    if not key:
        raise HTTPException(400, "asset_id is required")
    out = {"asset_id": key, "override": item_overrides.get(key), "inventory": None, "catalog": None}
    conn = store.db()
    try:
        row = conn.execute("SELECT account, name, rarity, type, value FROM instances WHERE asset_id=? LIMIT 1",
                           (key,)).fetchone()
    finally:
        conn.close()
    if not row:
        conn = store.db()
        try:
            row = conn.execute("SELECT account, name, rarity, type, value FROM items WHERE uid=? OR name=? LIMIT 1",
                               (key, name.strip() or key)).fetchone()
        finally:
            conn.close()
    if row and not str(row[1] or "").strip().lower().startswith("item "):
        out["inventory"] = {"account": row[0], "name": row[1], "rarity": row[2] or "",
                            "type": row[3] or "", "value": row[4]}
    play = items_db.find(asset_id=key, name=name.strip() or None)
    if play and name.strip():
        # الاسم اللي في خانة الاسم هو اللي المستخدم اختاره من المكتبة — لازم يغلب
        # الاسم المرتبط بالـ ID القديم
        play = dict(play)
        play["name"] = name.strip()
    if play:
        out["catalog"] = {"name": play.get("name"), "rarity": play.get("rarity") or "",
                          "type": play.get("type") or "", "value": play.get("value"),
                          "image": items_db.icon_for(play)}
    elif name.strip():
        hit = catalog.arctracker_lookup(name)
        if hit:
            out["catalog"] = {"name": hit.get("name"), "rarity": hit.get("rarity") or "",
                              "type": hit.get("type") or "", "value": hit.get("value")}
    known = item_catalog.unknown_status(key)
    out["known"] = known
    return out


@app.get("/admin/api/item/overrides")
def admin_item_overrides(request: Request):
    _admin_check(request)
    rows = item_overrides.all_rows()
    return {"ok": True, "total": len(rows), "items": rows}


@app.post("/admin/api/item/override")
async def admin_item_override_save(request: Request):
    """حفظ تعديل يدوي دائم — أي بيانات اللعبة بعد كده مش بتمسحه."""
    _admin_check(request)
    body = await request.json()
    key = str(body.get("asset_id") or "").strip()
    if not key:
        raise HTTPException(400, "asset id is required")
    image = str(body.get("image") or "").strip()
    if image.startswith("data:image/"):
        head, _, payload = image.partition(",")
        try:
            blob = base64.b64decode(payload)
        except (ValueError, binascii.Error):
            raise HTTPException(400, "the picture data is not valid base64")
        if len(blob) > 4 * 1024 * 1024:
            raise HTTPException(400, "the picture is over 4 MB")
        try:
            image = item_catalog.attach_icon(key, str(body.get("filename") or ""), blob)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    try:
        rec = item_overrides.save(key, {
            "name": body.get("name"), "rarity": body.get("rarity"), "type": body.get("type"),
            "value": body.get("value"), "image": image, "note": body.get("note"),
            "card_bg": body.get("card_bg")})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    rec["image"] = _mirror_icon(rec)
    version.update({"n": int(time.time() * 1000)})
    return {"ok": True, "asset_id": key, "override": rec,
            "known": item_catalog.unknown_status(key),
            # القيمة اللي اللوحة هتعرضها فعلاً بعد التعديل (زي السعر لو مش في المخزون)
            "row": {"name": rec.get("name"), "rarity": rec.get("rarity"), "type": rec.get("type"),
                    "value": rec.get("value"), "image": rec.get("image"),
                    "card_bg": rec.get("card_bg", "standard")}}


@app.get("/admin/api/item/icon")
def admin_item_icon(request: Request, path: str = ""):
    """صورة عنصر من المكتبة المحلية على البلاطة — المسارات المحلية بس (مفيش أي رابط خارجي)."""
    _admin_check(request)
    rel = item_overrides.local_image(path)
    if not rel:
        raise HTTPException(400, "only local library images are accepted")
    for base in (os.path.join(config.FRONTEND_DIR, "static"),
                 os.path.join(config.ITEM_ASSETS_DIR, "arctracker"),
                 os.path.join(config.ITEM_ASSETS_DIR, "metaforge")):
        name = rel.split("/", 1)[1] if "/" in rel else rel
        target = os.path.join(base, os.path.basename(name))
        if os.path.isfile(target):
            media = "image/webp" if target.lower().endswith(".webp") else "image/png"
            return FileResponse(target, media_type=media)
    raise HTTPException(404, "asset not cached locally")


@app.delete("/assets/items/arctracker/asset_{asset_id}.png")
@app.delete("/static/item_icons/asset_{asset_id}.png")
def remove_item_icon(request: Request, asset_id: str):
    """صورة عنصر اتكتبت بمحرّر البيانات — لمّا السطر اليدوي يتشال، صورته الخاصة بتتشال."""
    _admin_check(request)
    stem = re.sub(r"[^0-9A-Za-z_-]+", "_", asset_id)
    removed = False
    for base in (os.path.join(config.ITEM_ASSETS_DIR, "arctracker"),
                 os.path.join(config.FRONTEND_DIR, "static", "item_icons")):
        target = os.path.join(base, "asset_" + stem + ".png")
        if os.path.isfile(target):
            os.remove(target)
            removed = True
    return {"ok": True, "removed": removed}


@app.delete("/admin/api/item/override")
def admin_item_override_delete(request: Request, asset_id: str = ""):
    _admin_check(request)
    if not asset_id.strip():
        raise HTTPException(400, "asset_id is required")
    existed = item_overrides.delete(asset_id)
    version.update({"n": int(time.time() * 1000)})
    return {"ok": True, "asset_id": asset_id, "deleted": existed}


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
        # كميات نفس الـ id في الحسابات المفعّلة — بس دي اللي بتعمل الشارة.
        # المشترك بيشوف بس ضمن حساباته؛ ما تظهرش أسماء حسابات حد تاني.
        visible = _visible_accounts(conn, None)
        marks = ",".join("?" * len(visible)) or "''"
        counts = {}
        for r in conn.execute(
                "SELECT i.instance_id iid, a.name aname, a.label alabel, a.display_name adisplay, "
                "SUM(i.qty) qty, COUNT(*) cells "
                "FROM instances i JOIN accounts a ON a.name = i.account "
                "WHERE a.enabled = 1 AND i.account <> ? AND i.account IN (%s) "
                "AND i.instance_id IN (SELECT instance_id FROM instances WHERE account = ?) "
                "GROUP BY i.instance_id, i.account" % marks, (current,) + tuple(visible) + (current,)):
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
        visible = _visible_accounts(conn, None)
        marks = ",".join("?" * len(visible)) or "''"
        rows = conn.execute(
            "SELECT i.instance_id, a.name, a.label, a.display_name "
            "FROM instances i JOIN accounts a ON a.name = i.account "
            "WHERE a.enabled = 1 AND i.account <> ? AND i.account IN (%s) "
            "AND i.instance_id IN (SELECT instance_id FROM instances WHERE account = ?)" % marks,
            (current,) + tuple(visible) + (current,)).fetchall()
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
        visible = _visible_accounts(conn, None)
        marks = ",".join("?" * len(visible)) or "''"
        rows = conn.execute(
            "SELECT i.account acc_key, a.name acc_name, a.label acc_label, a.display_name acc_display, "
            "i.instance_id iid, i.name iname, i.qty iqty, i.asset_id asset_id, i.rarity rarity, "
            "i.type itype, i.image image, i.level level, i.value value, i.durability durability, "
            "i.max_durability max_durability, i.show_durability show_durability, "
            "i.quality_level quality_level, i.total_count total_count, i.attachments attachments "
            "FROM instances i JOIN accounts a ON a.name = i.account "
            "WHERE a.enabled = 1 AND i.account <> ? AND i.account IN (%s) "
            "AND (lower(i.name) LIKE ? ESCAPE '\\' OR lower(i.type) LIKE ? ESCAPE '\\')" % marks,
            (current,) + tuple(visible) + (like, like)).fetchall()

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
        target = _one_account(account)
        payload, fetched = store.read_snapshot(conn, target)
        if not payload:
            raise HTTPException(503, "no local snapshot for %s yet" % target)
        names = pioneer_tree.asset_names()
        mappings = payload.get("item_mappings") or {}

        def named(aid):
            if item_overrides.get(aid):
                return True
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


@app.get("/api/icons")
def api_icons(q: str = "", limit: int = 24):
    """بحث في مكتبة الأيقونات المحلية — الاسم الإنجليزي + صورة محلية + الندرة."""
    lib = item_catalog.load()
    rows = item_catalog.search(q, limit=max(1, min(int(limit or 24), 60)))
    return {"q": q, "results": rows, "total": len(lib.get("items") or {}),
            "synced_at": lib.get("synced_at") or 0}


@app.get("/api/unknown/item")
def api_unknown_item(asset_id: str = ""):
    """حالة قطعة مجهولة: معروفة ولا لأ، وخصائصها التقنية كما تأتي من بوابة اللعبة."""
    if not asset_id.strip():
        raise HTTPException(400, "asset_id is required")
    return item_catalog.unknown_status(asset_id)


@app.post("/api/unknown/item")
async def api_unknown_item_define(request: Request):
    """تثبيت تعريف قطعة على asset id — ثابت لكل النسخ في كل الحسابات."""
    _admin_check(request)
    ctype = request.headers.get("content-type", "")
    data_url = ""
    if ctype.startswith("multipart/"):
        # python-multipart مش مضمون إنه متسطّب — parsemultipart بيقرا نفس الصيغة بنفسه
        raw = await request.body()
        fields, files = parsemultipart(str(request.headers.get("content-type") or ""), raw)
        body = {k: str(fields.get(k) or "") for k in ("asset_id", "name", "rarity", "note")}
        upload = files.get("file")
        if upload:
            filename, blob = upload
            if len(blob) > 4 * 1024 * 1024:
                raise HTTPException(400, "the picture is over 4 MB")
            try:
                body["image"] = item_catalog.attach_icon(body["asset_id"], filename, blob)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
    else:
        body = await request.json()
        if str(body.get("image") or "").startswith("data:image/"):
            head, _, payload = str(body["image"]).partition(",")
            try:
                blob = base64.b64decode(payload)
            except (ValueError, binascii.Error):
                raise HTTPException(400, "the picture data is not valid base64")
            if len(blob) > 4 * 1024 * 1024:
                raise HTTPException(400, "the picture is over 4 MB")
            try:
                body["image"] = item_catalog.attach_icon(body.get("asset_id"), "", blob)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
    try:
        rec = item_catalog.define(body.get("asset_id"), body.get("name"),
                                  image=str(body.get("image") or ""),
                                  rarity=str(body.get("rarity") or ""),
                                  note=str(body.get("note") or ""))
        # التصنيف والسعر مش خاصية سطحية زي الاسم/الصورة: بيتحفظوا تعديلاً يدوياً
        # دائم عشان أي بيانات لاحقة من اللعبة أو الكتالوج ما تمسحهم.
        extra = {k: body.get(k) for k in ("type", "value") if str(body.get(k) or "").strip()}
        if extra:
            over = item_overrides.save(body.get("asset_id"), extra)
            over["image"] = _mirror_icon(over)
            rec.update({"type": over.get("type") or rec.get("type"), "value": over.get("value")})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    rec["image"] = _mirror_icon(rec)
    # كاش الواجهة (app.js) بيتقفل كل ما التعريفات تتغيّر — من أي تبويب
    version.update({"n": int(time.time() * 1000)})
    return rec


# رقم إصدار المكتبة: الواجهة بتعمل كارت للمكتبة مرة واحدة لكل رقم.
version = {"n": 1}


def _local_asset(path):
    """مسار صورة جاي من بيانات مخزّنة → المسار المحلي (/static أو /assets) بس.

    البلاطة بتحمّل من /assets وأيقونات المكتبة من /static؛ أي شكل تاني (رابط
    خارجي أو تزويق) بيرجع فاضي عشان مفيش طلب خارجي وقت العرض."""
    text = str(path or "").strip()
    static = ("static/", "item_icons/")
    if text.startswith(static):
        return text if text.startswith("static/") else "static/" + text
    # أسماء ملفات التوريد (arctracker/…، metaforge/…) بتتحط تحت items/ — ولو كانت
    # داخلة كمان بـ items/ فالمسار ده هو اللي البلاطة بتقراه أصلاً
    if text.startswith(("arctracker/", "metaforge/")):
        return "items/" + text
    if text.startswith(("items/arctracker/", "items/metaforge/")):
        return text
    if text.startswith("/assets/"):
        return text[len("/assets/"):]
    if text.startswith("/static/"):
        return text[len("/"):]
    if text.startswith("/"):
        return ""
    # اسم ملف مجرّد (مكتبة الأيقونات بترجّع اسمها من غير مجلد) — بنحاول في viewers المحلية
    if "/" not in text and text.rsplit(".", 1)[-1].lower() in ("png", "webp", "jpg"):
        if os.path.isfile(os.path.join(config.FRONTEND_DIR, "static", "item_icons", text)):
            return "static/item_icons/" + text
        if os.path.isfile(os.path.join(config.ITEM_ASSETS_DIR, "arctracker", text)):
            return "items/arctracker/" + text
        if os.path.isfile(os.path.join(config.ITEM_ASSETS_DIR, "metaforge", text)):
            return "items/metaforge/" + text
        return "items/arctracker/" + text
    return ""


def _workshop_preview_icon(asset_id, name):
    """عنصر جديد مش في المخزن: البلاطة بتعرض شكله من أيقونة وصفة الصناعة بتاعته
    لو القاعدة فيها وصفة. ده مسار العنوان الافتراضي — تعديل المستخدم دايمًا فوقه."""
    try:
        recipe = items_db.recipe_for(asset_id=asset_id, name=name) or {}
    except Exception:  # قاعدة مش موجودة أو قديمة — مفيش معاينة
        return ""
    return str(recipe.get("image_filename") or "")


def _mirror_icon(rec):
    """صورة المكتبة بتتنسخ كمان لمسار البلاطات، فأي تعريف جديد بيظهر بدون طلب خارجي."""
    image = _local_asset(str(rec.get("image") or ""))
    if not image and rec.get("asset_id"):
        image = _workshop_preview_icon(str(rec.get("asset_id")), str(rec.get("name") or ""))
    legacy = image.replace(item_catalog.ICON_URL, "arctracker/", 1) if image.startswith(item_catalog.ICON_URL) \
        else image.replace("arctracker/", item_catalog.ICON_URL, 1) if image.startswith("arctracker/") else ""
    if not legacy:
        return image
    src = os.path.join(config.FRONTEND_DIR, image) if image.startswith(item_catalog.ICON_URL) \
        else os.path.join(config.ITEM_ASSETS_DIR, image)
    dst = os.path.join(config.ITEM_ASSETS_DIR, legacy) if image.startswith(item_catalog.ICON_URL) \
        else os.path.join(config.FRONTEND_DIR, legacy)
    try:
        fresh = not os.path.isfile(dst) or (os.path.isfile(src) and os.path.getmtime(src) > os.path.getmtime(dst))
        if fresh:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
    except OSError:
        pass
    return image


@app.get("/admin/api/catalog")
def admin_catalog_status(request: Request):
    _admin_check(request)
    lib = item_catalog.load()
    items = lib.get("items") or {}
    return {"ok": True, "total": len(items),
            "with_icon": sum(1 for r in items.values() if r.get("image")),
            "manual": len(lib.get("manual") or {}),
            "synced_at": lib.get("synced_at") or 0,
            "source_version": lib.get("source_version") or ""}


@app.post("/admin/api/catalog/sync")
def admin_catalog_sync(request: Request):
    """يسحب كاتالوج الموقع المصدر ويضيف الجديد + أيقوناته محلياً."""
    _admin_check(request)
    try:
        return item_catalog.sync()
    except item_catalog.SYNC_LOCK.locked():
        raise HTTPException(429, "a sync is already running")
    except Exception as exc:
        raise HTTPException(502, "the source catalog did not answer: %s" % str(exc)[:160])


def _scoped_loadouts(conn):
    """قوالب الحسابات — لمشترك: قوالب حساباته بس."""
    out = store.list_loadouts(conn)
    scoped = _SCOPED_ACTIVE.get()
    if scoped is not None:
        out = [row for row in out if (row.get("account") or "") in scoped["accounts"]]
    return out


@app.get("/api/loadouts")
def api_loadouts(account: str = ""):
    """القوالب المحفوظة مشتركة بين كل حساباته — `account` للعرض بس.

    المشترك بيشوف قوالب حساباته هو بس؛ مش قوالب حساب حد تاني."""
    conn = store.db()
    out = _scoped_loadouts(conn)
    conn.close()
    return {"account": account, "loadouts": out}


@app.post("/api/loadouts")
def api_loadout_save(body: dict):
    body = body or {}
    account = _one_account(body.get("account") or "")
    try:
        rec, data = _with_conn(lambda conn: loadouts.save(conn, account, body.get("name") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"loadout": rec, "captured": data}


def _guard_loadout(loadout_id):
    """المشترك مايلمسش قالب حساب حد تاني."""
    scoped = _SCOPED_ACTIVE.get()
    if scoped is None:
        return
    rec = _with_conn(lambda conn: store.get_loadout(conn, loadout_id))
    if not rec or (rec.get("account") or "") not in scoped["accounts"]:
        raise HTTPException(404, "unknown loadout")


@app.get("/api/loadouts/{loadout_id}/plan")
def api_loadout_plan(loadout_id: int, account: str):
    _guard_loadout(loadout_id)
    account = _one_account(account)
    try:
        return _with_conn(lambda conn: loadouts.plan(conn, account, loadout_id))
    except KeyError:
        raise HTTPException(404, "unknown loadout")


@app.get("/api/loadouts/{loadout_id}/preview")
def api_loadout_preview(loadout_id: int, account: str):
    """معاينة القالب قبل التنفيذ: كل خانة بحالتها + مسار كل ناقصة (تصنيع/شراء).
    قراءة من الداتا المحلية وشجرة الحساب بس — مفيش أي طلب شبكة ولا كتابة."""
    _guard_loadout(loadout_id)
    account = _one_account(account)
    try:
        return _with_conn(lambda conn: loadouts.preview(conn, account, loadout_id))
    except KeyError:
        raise HTTPException(404, "unknown loadout")


@app.post("/api/loadouts/{loadout_id}/apply")
def api_loadout_apply(loadout_id: int, body: dict):
    _guard_loadout(loadout_id)
    account = _one_account((body or {}).get("account") or "")
    try:
        return _with_conn(lambda conn: loadouts.apply_plan(conn, account, loadout_id))
    except KeyError:
        raise HTTPException(404, "unknown loadout")


@app.patch("/api/loadouts/{loadout_id}")
def api_loadout_rename(loadout_id: int, body: dict):
    """اسم جديد لقالب محفوظ — محلي بالكامل، من غير أي كتابة على حساب اللعبة."""
    _guard_loadout(loadout_id)
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
    _guard_loadout(loadout_id)
    row = _with_conn(lambda conn: store.delete_loadout(conn, loadout_id))
    if not row:
        raise HTTPException(404, "unknown loadout")
    return {"deleted": loadout_id, "account": row["account"], "name": row["name"]}


@app.get("/api/item")
def api_item(account: str, instance_id: str):
    account = _one_account(account)
    conn = store.db()
    row = conn.execute("SELECT * FROM instances WHERE account=? AND instance_id=?",
                       (account, instance_id)).fetchone() if account else None
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


def _writes_for(request: Request):
    """مفتاح الكتابة الحقيقي زي ما هو — "وضع الدعم" مبقاش بيقفله، والكتابة شغالة
    افتراضياً على الحسابات اللي تحت يد المستخدم."""
    return writer.status()


@app.get("/api/writes")
def api_writes_status(request: Request):
    return _writes_for(request)


@app.post("/api/writes/arm")
def api_writes_arm(request: Request):
    _admin_check(request)
    writer.arm()
    return _writes_for(request)


@app.post("/api/writes/disarm")
def api_writes_disarm(request: Request):
    _admin_check(request)
    writer.disarm()
    return _writes_for(request)


@app.post("/api/writes/pause")
def api_writes_pause(request: Request, body: dict = None):
    """تجميد كامل للكتابة على البوابة (الحساب مشغول). body={"on": false} يرفعه."""
    _admin_check(request)
    from . import pioneer_write
    on = (body or {}).get("on", True)
    pioneer_write.set_paused(bool(on))
    return _writes_for(request)


@app.post("/api/actions/move")
def api_action_move(body: dict):
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn_free(lambda conn: actions.move(
        conn, account, body.get("target_container") or "",
        instance_ids=body.get("instance_ids"), name=body.get("name"),
        container=body.get("from_container"), target_wrapper_id=body.get("target_wrapper_id", ""),
        limit=body.get("limit"), target_slot=body.get("target_slot") or "",
        carry_instance_ids=body.get("carry_instance_ids"))))


@app.post("/api/actions/move-batch")
def api_action_move_batch(body: dict):
    """خطة النقل كلها في طلب واحد — أسرع مسار للتبديل والدفعات الكبيرة."""
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn_free(lambda conn: actions.move_batch(
        conn, account, body.get("moves") or [])))


@app.get("/api/moves/queue")
def api_moves_queue(account: str = ""):
    """الخطط المستنىّة مسار الكتابة — للتابض اللي عايز يعرض العداد."""
    rows = move_queue.listing()
    scoped = _SCOPED_ACTIVE.get()
    if scoped is not None:
        items = [r for r in rows["items"] if r.get("account") in scoped["accounts"]]
        return JSONResponse({**rows, "items": items, "count": len(items)})
    if account:
        items = [r for r in rows["items"] if r.get("account") == account]
        return JSONResponse({**rows, "items": items, "count": len(items)})
    return JSONResponse(rows)


@app.post("/api/moves/queue")
def api_moves_queue_add(body: dict):
    """بيلخّط خطة نقل جنب الباب المقفول — الخيط العام بينفّذها لوحدها لما المسار يرجع."""
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(move_queue.enqueue(account, body.get("moves") or [],
                                            body.get("summary") or ""))


@app.delete("/api/moves/queue/{entry_id}")
def api_moves_queue_drop(entry_id: str):
    scoped = _SCOPED_ACTIVE.get()
    if scoped is not None:
        hit = [r for r in move_queue.listing()["items"]
               if str(r.get("id") or "") == entry_id and r.get("account") in scoped["accounts"]]
        if not hit:
            raise HTTPException(404, "unknown entry")
    return JSONResponse(move_queue.remove(entry_id))


@app.post("/api/moves/queue/clear")
def api_moves_queue_clear(body: dict = None):
    account = _one_account(str((body or {}).get("account") or ""))
    if _SCOPED_ACTIVE.get() is not None:
        # للمشترك: حساباته بس — حساب فاضي معناه مفيش حسابات، مش الحساب النشط للأدمين
        return JSONResponse(move_queue.clear(account or "__none__"))
    return JSONResponse(move_queue.clear(account or None))


@app.post("/api/moves/queue/run")
def api_moves_queue_run(request: Request):
    """محاولة فورية واحدة على أول خطة في الطابور — للزرار، مش للحارس العام."""
    _admin_check(request)
    return JSONResponse(move_queue.flush_once())


@app.post("/api/actions/gather")
def api_action_gather(body: dict):
    """لمّ كل أكوام عنصر واحد في خانات متتالية بالستاش (مسار النقل الرسمي)."""
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.gather(
        conn, account, _split_ids(body.get("instance_ids")), asset_id=body.get("asset_id") or "")))


@app.post("/api/actions/spread")
def api_action_spread(body: dict):
    """فرّد أكوام عنصر واحد على خانات ستاش متباعدة — كل كوم في خانة لوحده."""
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.spread(
        conn, account, _split_ids(body.get("instance_ids")),
        asset_id=body.get("asset_id") or "", dry=bool(body.get("dry")))))


@app.post("/api/actions/merge-all")
def api_action_merge_all(body: dict):
    """زرار ⇄: دمج حقيقي في الخلفية — بيرجّع فوراً وحالته من /status."""
    body = body or {}
    account = _one_account(body.get("account") or "")
    only = [str(a) for a in (body.get("only_assets") or []) if a]
    return JSONResponse(_with_conn(lambda conn: actions.merge_all_start(
        conn, account, only=only, max_ops=int(body.get("max_ops") or 400))))


@app.post("/api/actions/merge-all/status")
def api_action_merge_all_status(body: dict):
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn_free(lambda _conn: actions.merge_all_status(account)))


@app.post("/api/actions/merge-all/stop")
def api_action_merge_all_stop(body: dict):
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn_free(lambda _conn: actions.merge_all_stop(account)))


@app.post("/api/actions/touch")
def api_action_touch(body: dict):
    """↑ UPDATE: لمسة محايدة على خانات التجهيز عند Embark — مفيش عنصر بيتحرّك."""
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.touch(
        conn, account, _split_ids(body.get("instance_ids")))))


@app.post("/api/actions/mutate")
def api_action_mutate(body: dict):
    body = body or {}
    account = _one_account(body.get("account") or "")
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
    account = _one_account(body.get("account") or "")
    undo = body.get("undo") if isinstance(body.get("undo"), dict) else {}
    cells = undo.get("cells") or body.get("cells") or {}
    return JSONResponse(_with_conn(lambda conn: pioneer_write.undo_cells(conn, account, cells)))


@app.post("/api/actions/clear-backpack")
def api_action_clear_backpack(body: dict):
    account = _one_account((body or {}).get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.clear_backpack(
        conn, account, scope=(body or {}).get("scope") or "backpack")))


@app.get("/api/scrappy")
def api_scrappy(account: str = ""):
    return _with_conn(lambda conn: scrappy.view(conn, _one_account(account)))


@app.post("/api/scrappy/preview")
def api_scrappy_preview(body: dict):
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: scrappy.preview(
        conn, account, body.get("offer_id"), body.get("amount", 1))))


@app.post("/api/scrappy/feed")
def api_scrappy_feed(body: dict):
    """تحويل زراعي عند الديك — بيتنفّذ بس من نافذة التأكيد (confirmed=true)."""
    body = body or {}
    account = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: scrappy.claim(
        conn, account, body.get("offer_id"), body.get("amount", 1),
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/collect-scrappy")
def api_action_collect_scrappy(body: dict):
    account = _one_account((body or {}).get("account") or "")
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
    name = _one_account(account)
    return _with_conn(lambda conn: actions.marks(conn, name))


@app.post("/api/marks")
def api_marks_add(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    out = _with_conn(lambda conn: actions.mark_add(conn, name, _split_ids(body.get("instance_ids")),
                                                   body.get("color") or ""))
    return JSONResponse(out, status_code=200 if out.get("ok") else 400)


@app.delete("/api/marks")
def api_marks_delete(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    out = _with_conn(lambda conn: actions.mark_remove(
        conn, name, instance_ids=_split_ids(body.get("instance_ids")),
        mark_ids=_split_ids(body.get("mark_ids")), color=body.get("color") or None))
    return JSONResponse(out)


@app.get("/api/attachments/slots")
def api_attachment_slots():
    return actions.attachment_rules()


@app.get("/api/attachments/manager")
def api_attachment_manager(account: str = "", ids: str = ""):
    name = _one_account(account)
    return JSONResponse(_with_conn(lambda conn: actions.attachment_manager(conn, name, _split_ids(ids))))


@app.post("/api/actions/plan")
def api_action_plan(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.plan(
        conn, name, body.get("kind") or "", instance_ids=_split_ids(body.get("instance_ids")),
        targets=body.get("targets") or {})))


@app.post("/api/actions/attachments/paste")
def api_attachments_paste(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.paste(
        conn, name, _split_ids(body.get("weapon_ids")), body.get("setup") or {},
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/attachments/autofill")
def api_attachments_autofill(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.autofill(
        conn, name, _split_ids(body.get("weapon_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/attachments/attach")
def api_attachments_attach(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.attach_one(
        conn, name, body.get("weapon_id"), body.get("slot_wrapper_id"),
        body.get("attachment_id"), body.get("source_wrapper_id"),
        body.get("target_container") or "stash")))


@app.post("/api/actions/attachments/detach")
def api_attachments_detach(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.detach(
        conn, name, _split_ids(body.get("weapon_ids")), _split_ids(body.get("slot_wrapper_ids")),
        target_container=body.get("target_container") or "stash",
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/upgrade")
def api_action_upgrade(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.upgrade(
        conn, name, _split_ids(body.get("instance_ids")), targets=body.get("targets") or {},
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/recycle")
def api_action_recycle(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.recycle(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/sell")
def api_action_sell(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.sell(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/repair")
def api_action_repair(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.repair(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/delete")
def api_action_delete(body: dict):
    """حذف مباشر على بوابة اللعبة — المنبع بيقرّر يقبل أو يرفض ونردّ رفضه نصاً."""
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.delete(
        conn, name, _split_ids(body.get("instance_ids")), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/split")
def api_action_split(body: dict):
    """تقسيم مباشرة على بوابة اللعبة — المنبع بيقرّر ونردّ رفضه نصاً."""
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.split(
        conn, name, str(body.get("instance_id") or ""),
        target_wrapper=str(body.get("target_wrapper_id") or ""),
        amount=body.get("amount"), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/fill")
def api_action_fill(body: dict):
    """كمية بالضبط للشنطة: ينقل الرصّات الكاملة ويفصل الفاضل من رصة تانية على البوابة الرسمية."""
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.fill(
        conn, name, str(body.get("asset_id") or ""), body.get("amount"),
        target_wrapper=str(body.get("target_wrapper_id") or ""),
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/combine")
def api_action_combine(body: dict):
    """دمج رصتين من نفس النوع مباشرة على بوابة اللعبة — المنبع بيقرّر ونردّ رفضه نصاً."""
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.combine(
        conn, name, str(body.get("instance_id") or ""),
        str(body.get("target_instance_id") or ""),
        amount=body.get("amount"), confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/swap")
def api_action_swap(body: dict):
    """تبديل مكان قطعتين على بوابة اللعبة — خانة بخانة، من غير ما أي كمية تتغيّر."""
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.swap(
        conn, name, str(body.get("instance_id") or ""),
        str(body.get("target_instance_id") or ""),
        confirmed=bool(body.get("confirmed")))))


@app.post("/api/actions/sync")
def api_action_sync(body: dict):
    body = body or {}
    name = _one_account(body.get("account") or "")
    return JSONResponse(_with_conn(lambda conn: actions.synchronize(conn, name)))


@app.get("/api/actions/log")
def api_action_log(request: Request, limit: int = 30, account: str = ""):
    name = _one_account(account)
    conn = store.db()
    rows = actions.pending(conn, limit, name)
    conn.close()
    return {"log": rows, "writes": _writes_for(request)}


@app.post("/auth/embark/{account_id}/activate")
def activate_by_id(account_id, request: Request):
    """نفس شكل rampart — التبديل محلي فقط ولا يرسل أي طلب تعديل للمنبع."""
    _guard_account(request, account_id)
    is_admin, _owner = _viewer(request)
    def run(conn):
        rec = store.get_account(conn, account_id)
        if not rec:
            raise HTTPException(404, "unknown account")
        if is_admin:
            admin_ids = {r["id"] for r in store.list_accounts_admin(conn)}
            if rec["id"] not in admin_ids:
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


_ART_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _require_member(request):
    """داخل بأي حساب حقيقي (أدمن/مشترك/جهاز صاحب الموقع) — مش زائر ولا وضع معاينة."""
    if local_admin(request) or _admin_token_kept(request):
        return
    session = request.headers.get("X-Admin-Session", "") or request.cookies.get("cm_admin_session", "")
    if session in _ADMIN_SESSIONS:
        return
    conn = store.db()
    try:
        token = request.cookies.get("cm_subscriber_token", "")
        row = conn.execute("SELECT is_active FROM subscribers WHERE token=?", (token,)).fetchone()             if token else None
    finally:
        conn.close()
    if row and row[0]:
        return
    raise HTTPException(403, "log in first")


def _require_present(request):
    """تعديل فهرس الأيقونات: مشترك داخل أو أدمن من نفس الجهاز — مش أي زائر."""
    conn = store.db()
    try:
        token = request.cookies.get("cm_subscriber_token", "")
        adm_token = subs_mod.admin_token(conn)
        row = conn.execute("SELECT is_active FROM subscribers WHERE token=?", (token,)).fetchone() if token and token != adm_token else None
    finally:
        conn.close()
    if local_admin(request) or token == adm_token or (row and row[0]):
        return
    raise HTTPException(403, "log in first")


def _require_writer(body):
    """تغيير بيانات الفهرس المخزّنة للموقع: للحسابات المفعّلة (أو الأدمين) بس."""
    who = str(body.get("account") or "").strip()
    if not who:
        return
    conn = store.db()
    try:
        rec = store.get_account(conn, who)
    finally:
        conn.close()
    if not rec or not (rec.get("is_active") or rec.get("is_main")):
        raise HTTPException(403, "only an enabled account can change the index")


@app.post("/api/index_art/upload")
def api_index_art_upload(body: dict):
    """صورة من الجهاز لقطعة الفهرس ماعندهاش أرت: الحسابات المفعّلة لوحدها."""
    _require_writer(body or {})
    aid = str((body or {}).get("asset_id") or "").strip()
    name = str((body or {}).get("name") or "").strip()
    if not aid and not name:
        raise HTTPException(400, "asset id or name is required")
    raw = str((body or {}).get("data") or "")
    try:
        blob = base64.b64decode(raw[raw.find(",") + 1:] if raw.startswith("data:") else raw, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(400, "the file is not valid base64")
    head = blob[:12]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif head.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise HTTPException(400, "only PNG, JPG or WEBP pictures are accepted")
    if len(blob) > 4 * 1024 * 1024:
        raise HTTPException(400, "the picture is over 4 MB")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str((body or {}).get("filename") or "").rsplit(".", 1)[0])[:40]
    stem = re.sub(r"[^0-9A-Za-z_-]+", "_", aid or name).strip("_")[:60] or "item"
    if safe:
        stem = "%s_%s" % (stem, safe)
    fname = stem + _ART_EXT[mime]
    folder = os.path.join(config.ITEM_ASSETS_DIR, "arctracker")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, fname), "wb") as fh:
        fh.write(blob)
    catalog.set_index_art(aid, name, "arctracker/" + fname)
    return {"ok": True, "image": "arctracker/" + fname, "asset_id": aid}


@app.post("/api/index_art/link")
def api_index_art_link(body: dict):
    """رابط صورة لقطعة بدون ملف — بيتخدم زي ما هو في البلاطة."""
    _require_writer(body or {})
    aid = str((body or {}).get("asset_id") or "").strip()
    name = str((body or {}).get("name") or "").strip()
    image = str((body or {}).get("image") or "").strip()
    if not image.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "the picture link must start with http:// or https://")
    if not aid and not name:
        raise HTTPException(400, "asset id or name is required")
    catalog.set_index_art(aid, name, image)
    return {"ok": True, "image": image, "asset_id": aid}


_PROBE_LOCK = threading.Lock()


def _probe_steps(who, iid):
    """خطوتين: للخانة المؤقتة وبعدها رجوع لمكانها الأصلي — الكل في طلب واحد.

    الخانة المحجوزة بمحتوى تاني مستبعدة في التخطيط عشان الطلب مايدفنش حاجة.
    """
    _inv, tree = pioneer_write.get_live_tree(who, max_age=0)
    try:
        lay = pioneer_tree.layout(tree)
        cells = [str(c) for c in lay["stash"]["slots"]]
        # الخانات الفاضية "سلاسل" مفيش سطر لها في items، فاختبار `item` مش بيكفي
        # (كانت طلعت صفر فاضي وهو فيه 21).
        bag = [str(s["wrapper"]) for s in lay["backpack"]["slots"] if not tree.first_child(s["wrapper"])]
    except pioneer_tree.TreeError:
        return None
    src = tree.parent.get(iid, "")
    if src:
        kids = [str(k) for k in tree.kids.get(src) or []]
        if kids and iid not in kids:
            return None  # مفيش سطر بيتقرا للأب ده — مكانها مش في شجرة الاستعلام
        if not kids and tree.first_child(src):
            return None  # خانة مخفية/قائمة محجوزة: مش بنخمن على أطفالها
    else:
        kids = []
    start = len(cells) // 2
    order = [c for c in cells[start:] + cells[:start] if c != src and not tree.first_child(c)] + bag
    if not kids and order:
        return [{"instance_id": iid, "source": src, "target": order[0]},
                {"instance_id": iid, "source": order[0], "target": src}]
    if kids == [iid] and src not in order:
        return [{"instance_id": iid, "source": src, "target": ""},
                {"instance_id": iid, "source": "", "target": src}]
    return None


_PROBE_WHY = {}


def _probe_move(who, iid):
    """اختبار نقل: True لو البوابة قبلت، False لو قالت إن القطعة مش في اللعبة
    الحية (412 FAILED_PRECONDITION)، None لو الاختبار مش قابل للتطبيق على القطعة —
    والسبب بيتسجل في _PROBE_WHY بدل ما البلاطة تتجاهل بصمت."""
    try:
        steps = _probe_steps(who, iid)
    except Exception as exc:
        _PROBE_WHY[iid] = "plan error: %s: %s" % (type(exc).__name__, str(exc)[:200])
        return None
    if not steps:
        _PROBE_WHY[iid] = "no free cell for a test move"
        return None
    ops = pioneer_write.to_parent_ops(steps)
    token = pioneer_client.account_token(who)
    if not token:
        raise HTTPException(401, "no saved token for %s" % who)
    try:
        pioneer_client.post_json(pioneer_write._url(), {"operations": ops}, token=token)
        return True
    except pioneer_client.TokenExpired as exc:
        raise HTTPException(401, str(exc))
    except pioneer_client.PioneerError as exc:
        text = str(exc)
        _PROBE_WHY[iid] = text[:200]
        if "FAILED_PRECONDITION" in text:
            return False
        if "NOT_FOUND" in text.upper() or "UNKNOWN" in text.upper():
            return None
        raise HTTPException(502, text[:200])
    finally:
        try:
            pioneer_write.invalidate_live_cache(who)
        except Exception:
            pass


@app.post("/api/unknown/cover")
def api_unknown_cover(body: dict):
    """«؟» بس: القطع اللي عليها ؟ واللعبة نفسها مش عارفاها.

    القطعة الحقيقية (باتش جديد) البوابة بتقبل نقلها، والبقايا (ديكور/أهداف قديمة
    لسه مربوطة بالحساب) بترجع 412 FAILED_PRECONDITION. الاختبار نقل واحدة لخانة
    مؤقتة ورجوع في نفس الطلب، ونقل واحد في المرة كلها (قفل) عشان متتقاطعش.
    """
    body = body or {}
    who = _one_account(body.get("account") or "")
    ids = [str(i) for i in (body.get("probe") or []) if i][:20]
    results = {i: None for i in ids}
    if not ids:
        return JSONResponse({"results": results})
    if not _PROBE_LOCK.acquire(blocking=False):
        raise HTTPException(429, "another move test is running — try again in a moment")
    try:
        for iid in ids:
            try:
                results[iid] = _probe_move(who, iid)
            except HTTPException as exc:
                if exc.status_code in (401, 429):
                    raise
                break
        return JSONResponse({"results": results,
                             "why": {i: _PROBE_WHY.pop(i, "") for i in ids}})
    finally:
        _PROBE_LOCK.release()


@app.get("/assets/items/{tail:path}")
def item_asset(tail: str):
    clean = tail.lstrip("/\\")
    base = os.path.basename(clean)
    candidates = [
        os.path.join(config.ITEM_ASSETS_DIR, clean),
        os.path.join(config.FRONTEND_DIR, clean),
        os.path.join(config.FRONTEND_DIR, "static", clean),
        os.path.join(config.FRONTEND_DIR, "static", "item_icons", base),
        os.path.join(config.ITEM_ASSETS_DIR, base),
        os.path.join(config.ITEM_ASSETS_DIR, "arctracker", base),
        os.path.join(config.ITEM_ASSETS_DIR, "metaforge", base),
    ]
    for p in candidates:
        if os.path.isfile(p):
            media = "image/webp" if p.lower().endswith(".webp") else ("image/jpeg" if p.lower().endswith((".jpg", ".jpeg")) else "image/png")
            return FileResponse(p, media_type=media)
        if p.lower().endswith(".png"):
            wp = os.path.splitext(p)[0] + ".webp"
            if os.path.isfile(wp):
                return FileResponse(wp, media_type="image/webp")
    raise HTTPException(404, "asset not cached locally")


@app.get("/assets/{filename}")
def root_asset(filename):
    path = os.path.join(config.ASSETS_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        raise HTTPException(404, "asset not cached locally")
    return FileResponse(path)


@app.get("/")
def index(request: Request):
    as_sub = _get_as_subscriber(request)
    if as_sub:
        if not _is_real_admin(request):
            raise HTTPException(403, "Admin session required to impersonate subscribers")
        return FileResponse(os.path.join(config.FRONTEND_DIR, "index.html"),
                            headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    token = (request.cookies.get("cm_subscriber_token", "") or "").strip().strip('"')
    admin_sess = request.cookies.get("cm_admin_session", "")
    is_admin = bool((admin_sess and admin_sess in _ADMIN_SESSIONS) or _admin_token_kept(request))
    if not is_admin and not token:
        resp = RedirectResponse("/login", status_code=302)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    return FileResponse(os.path.join(config.FRONTEND_DIR, "index.html"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/{tail:path}")
def ui_files(tail):
    base = os.path.realpath(config.FRONTEND_DIR)
    path = os.path.realpath(os.path.join(base, tail))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
