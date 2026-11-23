"""نظام المشتركين: إنشاء توكنات + اشتراكات بمدة + تحقق دخول.

الجداول:
  subscribers   — كل مشترك: اسم + توكن فريد + تاريخ إنشاء + تاريخ انتهاء + حالة
  admin         — كلمة مرور الأدمين (بتتولّد تلقائي أول مرة)
  token_log     — كل توكن لعبة ضافه المشترك لحسابه: التاريخ والآخر ظهور؛ السطر
                  بيتمسح بعد 24 ساعة من أول إضافة للتوكن ده
"""
import datetime
import hashlib
import os
import secrets
import string
import time

_DB_SETUP_DONE = False

# حروف وأرقام ورموز التوكن
TOKEN_CHARS = string.ascii_letters + string.digits + "!@#$%*-_=+"


def _ensure_tables(conn):
    """إنشاء الجداول مرة واحدة + ترحيل الأعمدة الجديدة لو القاعدة قديمة."""
    global _DB_SETUP_DONE
    if _DB_SETUP_DONE:
        _ensure_limit_column(conn)
        return
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            token       TEXT UNIQUE NOT NULL,
            created_at  REAL NOT NULL,
            expires_at  REAL,
            is_active   INTEGER DEFAULT 1,
            notes       TEXT DEFAULT '',
            last_login  REAL,
            login_count INTEGER DEFAULT 0,
            account_limit INTEGER
        );
        CREATE TABLE IF NOT EXISTS admin_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS token_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            subscriber  TEXT NOT NULL,
            account     TEXT NOT NULL,
            account_name TEXT DEFAULT '',
            token       TEXT NOT NULL,
            added_at    REAL NOT NULL,
            seen_at     REAL,
            UNIQUE(subscriber, account, token)
        );
        CREATE INDEX IF NOT EXISTS token_log_subscriber ON token_log(subscriber);
    """)
    conn.commit()
    _DB_SETUP_DONE = True
    _ensure_limit_column(conn)


def _ensure_limit_column(conn):
    """عمود حد الحسابات — بيتأكد منه كل مرة عشان قاعدة قديمة ما تفضلش من غير العمود."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(subscribers)").fetchall()}
    if "account_limit" not in cols:
        conn.execute("ALTER TABLE subscribers ADD COLUMN account_limit INTEGER")
        conn.commit()


# ──────────────────────────────────────────── توليد التوكنات
def generate_token(length=50):
    """توكن عشوائي طويل (50 حرف ورمز ورقم) — معقد وصعب التخمين جداً."""
    # نضمن وجود مزيج من حروف وأرقام ورموز
    parts = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%*-_=+"),
    ]
    parts += [secrets.choice(TOKEN_CHARS) for _ in range(length - len(parts))]
    # خلط الترتيب
    secrets.SystemRandom().shuffle(parts)
    return "".join(parts)


def hash_token(raw):
    """بصمة sha256 للتوكن — اللي بيتخزن في الكوكي للمقارنة السريعة."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ──────────────────────────────────────────── بيانات دخول الأدمين
def admin_password(conn):
    """بترجع كلمة مرور الأدمين — افتراضياً Lord@1234."""
    _ensure_tables(conn)
    row = conn.execute("SELECT value FROM admin_config WHERE key='admin_password'").fetchone()
    if row and row[0]:
        return row[0]
    pw = "Lord@1234"
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_password', ?)", (pw,))
    conn.commit()
    return pw


def set_admin_password(conn, new_pw):
    """تحديث كلمة مرور الأدمين."""
    _ensure_tables(conn)
    val = (new_pw or "").strip()
    if not val:
        raise ValueError("Password cannot be empty")
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_password', ?)", (val,))
    conn.commit()
    return val


def admin_token(conn):
    """بترجع توكن دخول الأدمين من الخارج — افتراضياً Lord@12345."""
    _ensure_tables(conn)
    row = conn.execute("SELECT value FROM admin_config WHERE key='admin_token'").fetchone()
    if row and row[0]:
        return row[0]
    tok = "Lord@12345"
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_token', ?)", (tok,))
    conn.commit()
    return tok


def set_admin_token(conn, new_token):
    """تحديث توكن دخول الأدمين من الخارج."""
    _ensure_tables(conn)
    val = (new_token or "").strip()
    if not val:
        raise ValueError("Token cannot be empty")
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_token', ?)", (val,))
    conn.commit()
    return val


def verify_admin(conn, password):
    return password == admin_password(conn)


# ──────────────────────────────────────────── إدارة المشتركين
def _limit(value):
    """حد الحسابات اللي المشترك يقدر يضيفها: رقم صحيح من 0 لفوق، أو None (من غير حد)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0, int(text))
    except ValueError:
        raise ValueError("account limit must be a whole number")


def create_subscriber(conn, name, days=None, notes="", account_limit=None):
    """إنشاء مشترك جديد. days=None يعني غير محدود."""
    _ensure_tables(conn)
    token = generate_token()
    now = time.time()
    expires = (now + days * 86400) if days else None
    conn.execute(
        "INSERT INTO subscribers (name, token, created_at, expires_at, notes, account_limit) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name.strip(), token, now, expires, notes.strip(), _limit(account_limit)))
    conn.commit()
    return {"name": name.strip(), "token": token, "created_at": now, "expires_at": expires,
            "account_limit": _limit(account_limit)}


def list_subscribers(conn):
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT id, name, token, created_at, expires_at, is_active, notes, last_login, login_count, account_limit "
        "FROM subscribers ORDER BY created_at DESC").fetchall()
    now = time.time()
    out = []
    for r in rows:
        exp = r[4]
        expired = bool(exp and exp < now)
        out.append({
            "id": r[0], "name": r[1], "token": r[2],
            "created_at": r[3], "expires_at": r[4],
            "is_active": bool(r[5]) and not expired,
            "is_expired": expired,
            "manually_disabled": not bool(r[5]),
            "notes": r[6] or "",
            "last_login": r[7],
            "login_count": r[8] or 0,
            "days_left": max(0, round((exp - now) / 86400, 1)) if exp else None,
            "account_limit": r[9],
        })
    return out


def get_subscriber(conn, sub_id):
    _ensure_tables(conn)
    r = conn.execute(
        "SELECT id, name, token, created_at, expires_at, is_active, notes, last_login, login_count, account_limit "
        "FROM subscribers WHERE id=?", (sub_id,)).fetchone()
    if not r:
        return None
    now = time.time()
    exp = r[4]
    expired = bool(exp and exp < now)
    return {
        "id": r[0], "name": r[1], "token": r[2],
        "created_at": r[3], "expires_at": r[4],
        "is_active": bool(r[5]) and not expired,
        "is_expired": expired,
        "manually_disabled": not bool(r[5]),
        "notes": r[6] or "",
        "last_login": r[7], "login_count": r[8] or 0,
        "days_left": max(0, round((exp - now) / 86400, 1)) if exp else None,
        "account_limit": r[9],
    }


def verify_token(conn, raw_token):
    """تحقق من التوكن: موجود + فعّال + لسه ما انتهاش. بيرجع dict المشترك أو None."""
    _ensure_tables(conn)
    raw_token = (raw_token or "").strip()
    if not raw_token:
        return None
    r = conn.execute(
        "SELECT id, name, expires_at, is_active FROM subscribers WHERE token=?",
        (raw_token,)).fetchone()
    if not r:
        return None
    if not r[3]:  # manually disabled
        return None
    if r[2] and r[2] < time.time():  # expired
        return None
    # تسجيل الدخول
    conn.execute("UPDATE subscribers SET last_login=?, login_count=login_count+1 WHERE id=?",
                 (time.time(), r[0]))
    conn.commit()
    return {"id": r[0], "name": r[1], "expires_at": r[2]}


def update_subscriber(conn, sub_id, name=None, days=None, notes=None, is_active=None, account_limit="keep"):
    """تعديل مشترك: اسم / مدة / ملاحظات / تفعيل-إيقاف."""
    _ensure_tables(conn)
    fields, vals = [], []
    if name is not None:
        fields.append("name=?"); vals.append(name.strip())
    if days is not None:
        if days == 0:
            fields.append("expires_at=NULL")
        else:
            fields.append("expires_at=?"); vals.append(time.time() + days * 86400)
    if notes is not None:
        fields.append("notes=?"); vals.append(notes.strip())
    if is_active is not None:
        fields.append("is_active=?"); vals.append(1 if is_active else 0)
    if account_limit != "keep":
        fields.append("account_limit=?"); vals.append(_limit(account_limit))
    if not fields:
        return get_subscriber(conn, sub_id)
    vals.append(sub_id)
    conn.execute("UPDATE subscribers SET %s WHERE id=?" % ", ".join(fields), vals)
    conn.commit()
    return get_subscriber(conn, sub_id)


def reset_token(conn, sub_id):
    """توليد توكن جديد (المشترك محتاج التوكن الجديد — القديم بيبطل)."""
    _ensure_tables(conn)
    new_token = generate_token()
    conn.execute("UPDATE subscribers SET token=? WHERE id=?", (new_token, sub_id))
    conn.commit()
    return new_token


def delete_subscriber(conn, sub_id):
    _ensure_tables(conn)
    row = conn.execute("SELECT name FROM subscribers WHERE id=?", (sub_id,)).fetchone()
    if row:
        conn.execute("DELETE FROM token_log WHERE subscriber=?", (row[0],))
    conn.execute("DELETE FROM subscribers WHERE id=?", (sub_id,))
    conn.commit()


# ──────────────────────────────────────────── سجل التوكنات
TOKEN_LOG_HOURS = 24


def log_token(conn, subscriber, account, account_name, token):
    """بيتسجل من لحظة أول إضافة للتوكن ده — وإعادة إرسال نفس التوكن ما بتمدّدش عمره."""
    if not subscriber or not token:
        return
    _ensure_tables(conn)
    conn.execute("INSERT OR IGNORE INTO token_log(subscriber,account,account_name,token,added_at,seen_at) "
                 "VALUES(?,?,?,?,?,?)",
                 (subscriber, account or "", account_name or "", token, time.time(), time.time()))
    conn.execute("UPDATE token_log SET seen_at=?, account_name=? "
                 "WHERE subscriber=? AND account=? AND token=?",
                 (time.time(), account_name or "", subscriber, account or "", token))
    conn.commit()


def prune_token_log(conn):
    """السجل بيتمسح لوحده: أي توكن عدّى عليه 24 ساعة من أول إضافته بيطلع."""
    _ensure_tables(conn)
    conn.execute("DELETE FROM token_log WHERE added_at <= ?",
                 (time.time() - TOKEN_LOG_HOURS * 3600,))
    conn.commit()


def token_log_for(conn, subscriber, purge=True):
    """توكنات المشترك اللي لسه في الـ24 ساعة — الأحدث الأول."""
    if purge:
        prune_token_log(conn)
    else:
        _ensure_tables(conn)
    rows = conn.execute("SELECT id, account, account_name, token, added_at, seen_at FROM token_log "
                        "WHERE subscriber=? ORDER BY added_at DESC", (subscriber,)).fetchall()
    now = time.time()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "account": r[1], "account_name": r[2] or r[1], "token": r[3],
            "added_at": r[4], "added_text": _clock(r[4]), "seen_at": r[5],
            "seen_text": _clock(r[5]) if r[5] else "",
            "hours_left": max(0.0, round((r[4] + TOKEN_LOG_HOURS * 3600 - now) / 3600, 1)),
        })
    return out


def token_log_counts(conn):
    """{اسم المشترك: عدد التوكنات اللي لسه في سجله} للوحة الأدمن."""
    prune_token_log(conn)
    rows = conn.execute("SELECT subscriber, COUNT(*) FROM token_log GROUP BY subscriber").fetchall()
    return {r[0]: r[1] for r in rows}


def _clock(ts):
    return datetime.datetime.fromtimestamp(float(ts or 0)).strftime("%Y-%m-%d %H:%M")


def extend_subscriber(conn, sub_id, extra_days):
    """يضيف أيام على الاشتراك الحالي (لو منتهي بيبدأ من دلوقتي)."""
    _ensure_tables(conn)
    r = conn.execute("SELECT expires_at FROM subscribers WHERE id=?", (sub_id,)).fetchone()
    if not r:
        return None
    now = time.time()
    base = max(r[0] or now, now)  # لو منتهي ابدأ من دلوقتي
    new_exp = base + extra_days * 86400
    conn.execute("UPDATE subscribers SET expires_at=?, is_active=1 WHERE id=?", (new_exp, sub_id))
    conn.commit()
    return get_subscriber(conn, sub_id)
