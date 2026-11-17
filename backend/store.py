"""تخزين محلي: SQLite للمفهرس + ملفات snapshot مضغوطة للـ payload الخام.

الـ payload الخام مهم: إعادة تقديمه حرفياً في /inventory/parsed تخلي أي سكربت موجود
(زي auto_sync_v2.py) يشتغل من غير ما يغيّر منطق قراءة الكميات بتاعه.
"""
import glob
import gzip
import json
import os
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS snapshots (
  account TEXT, fetched_at REAL, path TEXT, item_count INTEGER, ok INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS items (
  account TEXT, name TEXT, qty INTEGER, rarity TEXT, type TEXT, category TEXT,
  value INTEGER, image TEXT, level INTEGER, container TEXT, uid TEXT
);
CREATE INDEX IF NOT EXISTS items_name ON items(name);
CREATE INDEX IF NOT EXISTS items_account ON items(account);
CREATE TABLE IF NOT EXISTS assets (filename TEXT PRIMARY KEY, size INTEGER, fetched_at REAL);
CREATE TABLE IF NOT EXISTS instances (
  account TEXT, instance_id TEXT, wrapper_id TEXT, etag TEXT, name TEXT, qty INTEGER,
  container TEXT, slot_index INTEGER, rarity TEXT, type TEXT, value INTEGER, image TEXT,
  level INTEGER, asset_id TEXT, stack_size INTEGER, durability REAL, max_durability REAL,
  show_durability INTEGER, quality_level INTEGER, is_blueprint INTEGER, damaged INTEGER, uid TEXT,
  attachments TEXT, total_count INTEGER
);
CREATE INDEX IF NOT EXISTS instances_account ON instances(account);
CREATE INDEX IF NOT EXISTS instances_name ON instances(name);
CREATE INDEX IF NOT EXISTS instances_container ON instances(container);
CREATE TABLE IF NOT EXISTS actions (
  ts REAL, account TEXT, kind TEXT, request TEXT, status TEXT, response TEXT, items INTEGER
);
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, name TEXT UNIQUE, label TEXT, display_name TEXT, platform TEXT,
  token TEXT, token_exp REAL, embark_id TEXT, email TEXT, third_party_name TEXT,
  third_party_user_id TEXT, owner_username TEXT, is_active INTEGER DEFAULT 0,
  is_expired INTEGER DEFAULT 0, is_restricted INTEGER DEFAULT 0, linked_upstream INTEGER DEFAULT 0,
  added_at TEXT, updated_at TEXT, last_sync REAL, enabled INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS loadouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, name TEXT NOT NULL,
  data TEXT NOT NULL, created_at REAL, updated_at REAL, UNIQUE(account, name)
);
CREATE TABLE IF NOT EXISTS marks (
  account TEXT, instance_id TEXT, color TEXT, created_at REAL,
  UNIQUE(account, instance_id, color)
);
CREATE INDEX IF NOT EXISTS marks_account ON marks(account);
"""


def db():
    for path in (config.DATA_DIR, config.SNAPSHOT_DIR, config.ITEM_ASSETS_DIR):
        os.makedirs(path, exist_ok=True)
    conn = sqlite3.connect(config.DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """أعمدة إضافية لجداول قديمة — بلا أي تغيير على الأعمدة الموجودة."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(instances)")}
    for name, decl in (("attachments", "TEXT"), ("total_count", "INTEGER")):
        if name not in cols:
            conn.execute("ALTER TABLE instances ADD COLUMN %s %s" % (name, decl))
    conn.commit()


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value, ensure_ascii=False)))
    # من غير commit الكتابة بتترجع لما الاتصال يتقفل — وكاش auth:me كان بيفضل قديم للأبد
    conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def save_snapshot(conn, account, payload, item_count, details=None):
    ts = time.time()
    path = os.path.join(config.SNAPSHOT_DIR, "%s_%s.json.gz" % (account, time.strftime("%Y%m%d-%H%M%S", time.localtime(ts))))
    with gzip.open(path, "wb") as f:
        f.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    conn.execute("DELETE FROM items WHERE account=?", (account,))
    for name, detail in item_count.items():
        conn.execute("INSERT INTO items(account,name,qty,rarity,type,category,value,image,level,container,uid) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (account, name, detail.get("qty", 0), detail.get("rarity", ""), detail.get("type", ""),
                      json.dumps(detail.get("category") or [], ensure_ascii=False), detail.get("value"),
                      detail.get("image", ""), detail.get("level", 0), detail.get("container", ""), detail.get("uid", "")))
    _replace_instances(conn, account, details)
    conn.execute("INSERT INTO snapshots(account,fetched_at,path,item_count,ok,error) VALUES(?,?,?,?,1,'')",
                 (account, ts, path, len(item_count)))
    conn.commit()
    prune_snapshots(conn, account)
    return path


def _replace_instances(conn, account, details):
    """كل نسخة عنصر (instance) بسطر واحد — مطلوبة لإرسال أوامر النقل/التقسيم للمنبع."""
    conn.execute("DELETE FROM instances WHERE account=?", (account,))
    if not details:
        return
    rows = []
    for name, instances in details.items():
        for d in instances:
            rows.append((
                account, d.get("instance_id") or d.get("uid") or "", d.get("wrapper_id", ""), d.get("etag", ""),
                name, d.get("qty", 0), d.get("container", ""), d.get("slot_index"),
                d.get("rarity", ""), d.get("type", ""), d.get("value"), d.get("image", ""),
                d.get("level", 0), d.get("asset_id", ""), d.get("stack_size"),
                _as_num(d.get("durability")), _as_num(d.get("max_durability")),
                1 if d.get("show_durability") else 0, _as_int(d.get("quality_level")),
                1 if d.get("is_blueprint") else 0, 1 if d.get("damaged") else 0, d.get("uid", ""),
                json.dumps(d.get("attachments") or [], ensure_ascii=False),
                _as_int(d.get("total_count")),
            ))
    conn.executemany(
        "INSERT INTO instances(account,instance_id,wrapper_id,etag,name,qty,container,slot_index,rarity,type,"
        "value,image,level,asset_id,stack_size,durability,max_durability,show_durability,quality_level,"
        "is_blueprint,damaged,uid,attachments,total_count) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def _as_int(val):
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _as_num(val):
    """يحافظ على كسور المتانة (durability في rampart نسبة 0..1 مش عدد صحيح)."""
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def log_action(conn, account, kind, request, status, response, items=0):
    conn.execute("INSERT INTO actions(ts,account,kind,request,status,response,items) VALUES(?,?,?,?,?,?,?)",
                 (time.time(), account, kind, json.dumps(request, ensure_ascii=False)[:4000],
                  status, json.dumps(response, ensure_ascii=False)[:4000] if response else "", items))
    conn.commit()


def action_log(conn, limit=50, account=""):
    """آخر سجل الإجراءات — لو account متسجل بيفلتر بيه (كل تاب شايف حسابه)."""
    if account:
        rows = conn.execute("SELECT * FROM actions WHERE account=? ORDER BY ts DESC LIMIT ?",
                            (account, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def prune_snapshots(conn, account, keep=config.MAX_SNAPSHOT_KEEP):
    rows = conn.execute("SELECT path FROM snapshots WHERE account=? AND ok=1 ORDER BY fetched_at DESC",
                        (account,)).fetchall()[keep:]
    for row in rows:
        try:
            os.remove(row["path"])
        except OSError:
            pass
        conn.execute("DELETE FROM snapshots WHERE path=?", (row["path"],))
    conn.commit()


def record_failure(conn, account, error):
    conn.execute("INSERT INTO snapshots(account,fetched_at,path,item_count,ok,error) VALUES(?,?,?,0,0,?)",
                 (account, time.time(), "", str(error)[:300]))
    conn.commit()


def latest_snapshot_path(conn, account):
    row = conn.execute("SELECT path FROM snapshots WHERE account=? AND ok=1 ORDER BY fetched_at DESC LIMIT 1",
                       (account,)).fetchone()
    if row and os.path.exists(row["path"]):
        return row["path"]
    fallback = sorted(glob.glob(os.path.join(config.SNAPSHOT_DIR, "%s_*.json.gz" % account)))
    return fallback[-1] if fallback else None


_SNAPSHOT_CACHE = {}  # account -> (path, mtime, data)


def read_snapshot(conn, account):
    path = latest_snapshot_path(conn, account)
    if not path:
        return None, None
    try:
        mtime = os.path.getmtime(path)
        cached = _SNAPSHOT_CACHE.get(account)
        if cached and cached[0] == path and cached[1] == mtime:
            return cached[2], mtime
        with gzip.open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        _SNAPSHOT_CACHE[account] = (path, mtime, data)
        return data, mtime
    except Exception:
        with gzip.open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8")), os.path.getmtime(path)


def last_success(conn, account):
    row = conn.execute("SELECT fetched_at FROM snapshots WHERE account=? AND ok=1 ORDER BY fetched_at DESC LIMIT 1",
                       (account,)).fetchone()
    return float(row["fetched_at"]) if row else 0.0


# ------------------------------------------------------------------ الحسابات
ACCOUNT_COLUMNS = ("id", "name", "label", "display_name", "platform", "token", "token_exp", "embark_id",
                   "email", "third_party_name", "third_party_user_id", "owner_username", "is_active",
                   "is_expired", "is_restricted", "linked_upstream", "added_at", "updated_at",
                   "last_sync", "enabled")


def upsert_account(conn, rec):
    """أدرج/حدّث سطر حساب — الأعمدة غير المذكورة بتفضل زي ما هي."""
    cols = [c for c in ACCOUNT_COLUMNS if c in rec]
    if "id" not in cols:
        raise ValueError("upsert_account needs an id")
    conn.execute("INSERT INTO accounts(%s) VALUES(%s) ON CONFLICT(id) DO UPDATE SET %s"
                 % (",".join(cols), ",".join("?" * len(cols)),
                    ",".join("%s=excluded.%s" % (c, c) for c in cols if c != "id")),
                 [rec.get(c) for c in cols])
    conn.commit()
    return get_account(conn, rec["id"])


def list_accounts(conn, enabled_only=False):
    query = "SELECT * FROM accounts" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY added_at DESC, name"
    return [dict(r) for r in conn.execute(query)]


def get_account(conn, key):
    if not key:
        return None
    row = conn.execute("SELECT * FROM accounts WHERE id=? OR name=? OR display_name=? OR label=?",
                       (key, key, key, key)).fetchone()
    return dict(row) if row else None


def delete_account(conn, account_id):
    row = conn.execute("SELECT name FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    conn.commit()
    return row["name"] if row else None


def set_active_account(conn, account_id):
    row = conn.execute("SELECT owner_username FROM accounts WHERE id=?", (account_id,)).fetchone()
    if row:
        owner = (row["owner_username"] if isinstance(row, dict) else row[0]) or ""
        owner_clean = owner.strip().lower()
        if owner_clean and owner_clean != "admin":
            conn.execute("UPDATE accounts SET is_active=(id=?) WHERE LOWER(COALESCE(owner_username, '')) = ?", (account_id, owner_clean))
        else:
            conn.execute("UPDATE accounts SET is_active=(id=?) WHERE owner_username IS NULL OR owner_username = '' OR LOWER(owner_username) = 'admin'", (account_id,))
        conn.commit()


def active_account(conn, owner=None):
    if owner and str(owner).strip().lower() != "admin":
        owner_clean = str(owner).strip().lower()
        row = conn.execute("SELECT * FROM accounts WHERE LOWER(COALESCE(owner_username, '')) = ? AND is_active=1 LIMIT 1", (owner_clean,)).fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM accounts WHERE LOWER(COALESCE(owner_username, '')) = ? AND enabled=1 ORDER BY added_at LIMIT 1", (owner_clean,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM accounts WHERE (owner_username IS NULL OR owner_username = '' OR LOWER(owner_username) = 'admin') AND is_active=1 LIMIT 1").fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM accounts WHERE (owner_username IS NULL OR owner_username = '' OR LOWER(owner_username) = 'admin') AND enabled=1 ORDER BY added_at LIMIT 1").fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------------ التجهيزات المحفوظة
def save_loadout(conn, account, name, data):
    ts = time.time()
    conn.execute(
        "INSERT INTO loadouts(account,name,data,created_at,updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(account,name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (account, name, json.dumps(data, ensure_ascii=False), ts, ts))
    conn.commit()
    row = conn.execute("SELECT id FROM loadouts WHERE account=? AND name=?", (account, name)).fetchone()
    return int(row["id"]) if row else None


def list_loadouts(conn):
    """التجهيزات المحفوظة مشتركة بين حساباتك كلها — مع اسم الحساب صاحب التجهيز.

    دي قوالب هو اللي بيكتبها (مش بيانات مخزن)، فمفيش عليها قيد العزل: تجهيز اتعمل
    في حساب يبان ويتحمّل في الباقي. صاحب القالب بيتعرض باسم الحساب، والسطور بتتمسح
    مع حذف الحساب (accounts.remove) — عشان ما تفضلش قوالب بلا أصل."""
    rows = conn.execute(
        "SELECT l.id, l.name, l.account, l.created_at, l.updated_at, "
        "COALESCE(NULLIF(TRIM(a.display_name), ''), NULLIF(TRIM(a.label), ''), l.account) AS owner "
        "FROM loadouts l LEFT JOIN accounts a ON a.name = l.account "
        "ORDER BY l.updated_at DESC, l.name").fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        rec["owner"] = str(rec["owner"] or "").split("#")[0].strip() or rec["account"]
        out.append(rec)
    return out


def get_loadout(conn, loadout_id):
    row = conn.execute("SELECT * FROM loadouts WHERE id=?", (loadout_id,)).fetchone()
    return dict(row) if row else None


def rename_loadout(conn, loadout_id, name):
    """تغيير اسم تجهيز — بترجّع None لو مش موجود، False لو الاسم محجوز في نفس الحساب."""
    if not conn.execute("SELECT 1 FROM loadouts WHERE id=?", (loadout_id,)).fetchone():
        return None
    if conn.execute("SELECT 1 FROM loadouts WHERE id <> ? AND name = ? "
                    "AND account = (SELECT account FROM loadouts WHERE id=?)",
                    (loadout_id, name, loadout_id)).fetchone():
        return False
    conn.execute("UPDATE loadouts SET name=?, updated_at=? WHERE id=?",
                 (name, time.time(), loadout_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM loadouts WHERE id=?", (loadout_id,)).fetchone())


def delete_loadout(conn, loadout_id):
    row = conn.execute("SELECT account,name FROM loadouts WHERE id=?", (loadout_id,)).fetchone()
    conn.execute("DELETE FROM loadouts WHERE id=?", (loadout_id,))
    conn.commit()
    return dict(row) if row else None


# ------------------------------------------------------------------ ماركس العناصر (محلي)
def list_marks(conn, account):
    rows = conn.execute("SELECT rowid AS mark_id, instance_id, color, created_at FROM marks "
                        "WHERE account=? ORDER BY created_at", (account,)).fetchall()
    return [dict(r) for r in rows]


def add_marks(conn, account, instance_ids, color):
    ts = time.time()
    added = []
    for instance_id in instance_ids:
        cur = conn.execute("INSERT OR IGNORE INTO marks(account,instance_id,color,created_at) VALUES(?,?,?,?)",
                           (account, str(instance_id), color, ts))
        if cur.rowcount:
            added.append(str(instance_id))
    conn.commit()
    return added


def delete_marks(conn, account, instance_ids=None, mark_ids=None, color=None):
    """حذف انتقائي فقط: لازم يتحدد mark_ids أو instance_ids — ممنوع تفريغ الكل بالخطأ."""
    if not mark_ids and not instance_ids:
        return 0
    sql = "DELETE FROM marks WHERE account=?"
    args = [account]
    if mark_ids:
        sql += " AND rowid IN (%s)" % ",".join("?" * len(mark_ids))
        args += [int(m) for m in mark_ids]
    if instance_ids:
        sql += " AND instance_id IN (%s)" % ",".join("?" * len(instance_ids))
        args += [str(i) for i in instance_ids]
    if color:
        sql += " AND color=?"
        args.append(color)
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.rowcount
