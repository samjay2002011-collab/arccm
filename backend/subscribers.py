"""نظام المشتركين: إنشاء توكنات + اشتراكات بمدة + تحقق دخول.

الجداول:
  subscribers   — كل مشترك: اسم + توكن فريد + تاريخ إنشاء + تاريخ انتهاء + حالة
  admin         — كلمة مرور الأدمين (بتتولّد تلقائي أول مرة)
"""
import hashlib
import os
import secrets
import string
import time

_DB_SETUP_DONE = False

# حروف وأرقام ورموز التوكن
TOKEN_CHARS = string.ascii_letters + string.digits + "!@#$%*-_=+"


def _ensure_tables(conn):
    """بتتنادى مرة واحدة عند أول استخدام — بتعمل الجداول لو مش موجودة."""
    global _DB_SETUP_DONE
    if _DB_SETUP_DONE:
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
            login_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS admin_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()
    _DB_SETUP_DONE = True


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
def create_subscriber(conn, name, days=None, notes=""):
    """إنشاء مشترك جديد. days=None يعني غير محدود."""
    _ensure_tables(conn)
    token = generate_token()
    now = time.time()
    expires = (now + days * 86400) if days else None
    conn.execute(
        "INSERT INTO subscribers (name, token, created_at, expires_at, notes) VALUES (?, ?, ?, ?, ?)",
        (name.strip(), token, now, expires, notes.strip()))
    conn.commit()
    return {"name": name.strip(), "token": token, "created_at": now, "expires_at": expires}


def list_subscribers(conn):
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT id, name, token, created_at, expires_at, is_active, notes, last_login, login_count "
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
        })
    return out


def get_subscriber(conn, sub_id):
    _ensure_tables(conn)
    r = conn.execute(
        "SELECT id, name, token, created_at, expires_at, is_active, notes, last_login, login_count "
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


def update_subscriber(conn, sub_id, name=None, days=None, notes=None, is_active=None):
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
    conn.execute("DELETE FROM subscribers WHERE id=?", (sub_id,))
    conn.commit()


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
