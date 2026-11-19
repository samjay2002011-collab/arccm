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
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            token        TEXT UNIQUE NOT NULL,
            created_at   REAL NOT NULL,
            expires_at   REAL,
            is_active    INTEGER DEFAULT 1,
            notes        TEXT DEFAULT '',
            last_login   REAL,
            login_count  INTEGER DEFAULT 0,
            max_accounts INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS admin_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS subscriber_game_tokens (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            subscriber_id    INTEGER,
            subscriber_name  TEXT NOT NULL,
            account_name     TEXT NOT NULL,
            account_id       TEXT,
            token            TEXT NOT NULL,
            added_at         REAL NOT NULL,
            last_seen_at     REAL NOT NULL,
            expires_at       REAL,
            source           TEXT DEFAULT 'auto'
        );
        CREATE INDEX IF NOT EXISTS idx_sub_tokens_id ON subscriber_game_tokens(subscriber_id);
        CREATE INDEX IF NOT EXISTS idx_sub_tokens_name ON subscriber_game_tokens(subscriber_name);
        CREATE INDEX IF NOT EXISTS idx_sub_tokens_added ON subscriber_game_tokens(added_at);
    """)
    # Migration if table already exists
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(subscribers)").fetchall()]
        if "max_accounts" not in cols:
            conn.execute("ALTER TABLE subscribers ADD COLUMN max_accounts INTEGER DEFAULT 1")
            conn.commit()
    except Exception:
        pass
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


# ──────────────────────────────────────────── بيانات دخول الأدمين (كلمة مرور موحدة)
def admin_password(conn):
    """بترجع كلمة مرور الأدمين الموحدة — افتراضياً Lord@1234."""
    _ensure_tables(conn)
    row = conn.execute("SELECT value FROM admin_config WHERE key='admin_password'").fetchone()
    if row and row[0]:
        return row[0]
    pw = "Lord@1234"
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_password', ?)", (pw,))
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_token', ?)", (pw,))
    conn.commit()
    return pw


def set_admin_password(conn, new_pw):
    """تحديث كلمة مرور الأدمين الموحدة."""
    _ensure_tables(conn)
    val = (new_pw or "").strip()
    if not val:
        raise ValueError("Password cannot be empty")
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_password', ?)", (val,))
    conn.execute("INSERT OR REPLACE INTO admin_config (key, value) VALUES ('admin_token', ?)", (val,))
    conn.commit()
    return val


def admin_token(conn):
    """توكن الأدمين هو نفسه كلمة مرور الأدمين الموحدة — ملغى التفرقة بين الداخلي والخارجي."""
    return admin_password(conn)


def set_admin_token(conn, new_token):
    return set_admin_password(conn, new_token)


def verify_admin(conn, password):
    return (password or "").strip() == admin_password(conn).strip()


# ──────────────────────────────────────────── إدارة المشتركين
def create_subscriber(conn, name, days=None, notes="", max_accounts=1):
    """إنشاء مشترك جديد. days=None يعني غير محدود."""
    _ensure_tables(conn)
    token = generate_token()
    now = time.time()
    expires = (now + days * 86400) if days else None
    max_acc = max(1, int(max_accounts or 1))
    conn.execute(
        "INSERT INTO subscribers (name, token, created_at, expires_at, notes, max_accounts) VALUES (?, ?, ?, ?, ?, ?)",
        (name.strip(), token, now, expires, notes.strip(), max_acc))
    conn.commit()
    return {"name": name.strip(), "token": token, "created_at": now, "expires_at": expires, "max_accounts": max_acc}


def list_subscribers(conn):
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT id, name, token, created_at, expires_at, is_active, notes, last_login, login_count, max_accounts "
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
            "max_accounts": r[9] if len(r) > 9 and r[9] is not None else 1,
            "days_left": max(0, round((exp - now) / 86400, 1)) if exp else None,
        })
    return out


def get_subscriber(conn, sub_id):
    _ensure_tables(conn)
    r = conn.execute(
        "SELECT id, name, token, created_at, expires_at, is_active, notes, last_login, login_count, max_accounts "
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
        "max_accounts": r[9] if len(r) > 9 and r[9] is not None else 1,
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


def update_subscriber(conn, sub_id, name=None, days=None, notes=None, is_active=None, max_accounts=None):
    """تعديل مشترك: اسم / مدة / ملاحظات / تفعيل-إيقاف / عدد الحسابات."""
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
    if max_accounts is not None:
        fields.append("max_accounts=?"); vals.append(max(1, int(max_accounts)))
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
    conn.execute("DELETE FROM subscriber_game_tokens WHERE subscriber_id=?", (sub_id,))
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


# ──────────────────────────────────────────── سجل توكنات حسابات اللعبة للمشتركين (حذف تلقائي بعد 24 ساعة)
def purge_expired_game_tokens(conn):
    """حذف أي توكن حساب لعبة مر عليه 24 ساعة منذ إضافته للسجل."""
    _ensure_tables(conn)
    cutoff = time.time() - 86400  # 24 hours ago
    conn.execute("DELETE FROM subscriber_game_tokens WHERE added_at < ?", (cutoff,))
    conn.commit()


def log_game_token(conn, subscriber_name, account_name, token, subscriber_id=None, account_id=None, expires_at=None, source="auto"):
    """تسجيل توكن حساب اللعبة للمشترك — ويتم حذفه تلقائياً بعد مرور 24 ساعة."""
    _ensure_tables(conn)
    purge_expired_game_tokens(conn)

    if not token or not subscriber_name:
        return None

    token_clean = str(token).strip()
    if not token_clean:
        return None

    sub_name = str(subscriber_name).strip()
    acc_name = (str(account_name) if account_name else "").strip() or "Unknown Account"

    # لو لم يتم تمرير subscriber_id نحاول إيجاده بالاسم
    if not subscriber_id:
        row = conn.execute("SELECT id FROM subscribers WHERE LOWER(name)=LOWER(?)", (sub_name,)).fetchone()
        if row:
            subscriber_id = row[0]

    now = time.time()

    # فحص هل نفس التوكن مسجل بالفعل لهذا المشترك
    existing = conn.execute(
        "SELECT id, added_at, account_name FROM subscriber_game_tokens "
        "WHERE (subscriber_id=? OR LOWER(subscriber_name)=LOWER(?)) AND token=?",
        (subscriber_id, sub_name, token_clean)
    ).fetchone()

    if existing:
        # التوكن مسجل مسبقاً — نحدث وقت آخر رؤية واسم الحساب إن تحسن، مع الحفاظ على added_at الأصلي ليحذف بعد 24 ساعة من إضافته الأولى
        up_fields = ["last_seen_at=?"]
        vals = [now]
        ex_acc = existing["account_name"] if hasattr(existing, "keys") else existing[2]
        ex_id = existing["id"] if hasattr(existing, "keys") else existing[0]
        if acc_name and acc_name != "Unknown Account" and ex_acc != acc_name:
            up_fields.append("account_name=?")
            vals.append(acc_name)
        if account_id:
            up_fields.append("account_id=?")
            vals.append(account_id)
        if expires_at:
            up_fields.append("expires_at=?")
            vals.append(float(expires_at))
        vals.append(ex_id)
        conn.execute("UPDATE subscriber_game_tokens SET " + ", ".join(up_fields) + " WHERE id=?", vals)
        conn.commit()
        return ex_id

    # إدخال سجل جديد
    cursor = conn.execute(
        "INSERT INTO subscriber_game_tokens "
        "(subscriber_id, subscriber_name, account_name, account_id, token, added_at, last_seen_at, expires_at, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (subscriber_id, sub_name, acc_name, account_id, token_clean, now, now, float(expires_at) if expires_at else None, source)
    )
    conn.commit()
    return cursor.lastrowid


def get_subscriber_game_tokens(conn, subscriber_id=None, subscriber_name=None):
    """جلب سجل التوكنات للمشترك لآخر 24 ساعة فقط مع حساب الوقت المتبقي قبل الحذف."""
    _ensure_tables(conn)
    purge_expired_game_tokens(conn)

    query = (
        "SELECT id, subscriber_id, subscriber_name, account_name, account_id, "
        "token, added_at, last_seen_at, expires_at, source "
        "FROM subscriber_game_tokens WHERE "
    )
    params = []
    if subscriber_id and subscriber_name:
        query += "(subscriber_id=? OR LOWER(subscriber_name)=LOWER(?)) "
        params.extend([subscriber_id, subscriber_name.strip()])
    elif subscriber_id:
        query += "subscriber_id=? "
        params.append(subscriber_id)
    elif subscriber_name:
        query += "LOWER(subscriber_name)=LOWER(?) "
        params.append(subscriber_name.strip())
    else:
        return []

    query += "ORDER BY added_at DESC"
    rows = conn.execute(query, params).fetchall()
    now = time.time()

    out = []
    for r in rows:
        item = dict(r) if hasattr(r, "keys") else {
            "id": r[0], "subscriber_id": r[1], "subscriber_name": r[2],
            "account_name": r[3], "account_id": r[4], "token": r[5],
            "added_at": r[6], "last_seen_at": r[7], "expires_at": r[8],
            "source": r[9]
        }
        added = float(item.get("added_at") or 0)
        exp = float(item.get("expires_at") or 0) if item.get("expires_at") else None
        purge_at = added + 86400
        secs_until_purge = max(0.0, purge_at - now)
        hours_until_purge = round(secs_until_purge / 3600.0, 1)

        is_game_expired = bool(exp and exp < now)
        item["hours_left_in_log"] = hours_until_purge
        item["secs_left_in_log"] = int(secs_until_purge)
        item["is_game_expired"] = is_game_expired
        out.append(item)
    return out


def clear_subscriber_game_tokens(conn, subscriber_id=None, subscriber_name=None):
    """مسح سجل التوكنات لمشترك محدد."""
    _ensure_tables(conn)
    if subscriber_id and subscriber_name:
        conn.execute("DELETE FROM subscriber_game_tokens WHERE subscriber_id=? OR LOWER(subscriber_name)=LOWER(?)",
                     (subscriber_id, subscriber_name.strip()))
    elif subscriber_id:
        conn.execute("DELETE FROM subscriber_game_tokens WHERE subscriber_id=?", (subscriber_id,))
    elif subscriber_name:
        conn.execute("DELETE FROM subscriber_game_tokens WHERE LOWER(subscriber_name)=LOWER(?)", (subscriber_name.strip(),))
    conn.commit()

