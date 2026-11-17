"""مدير الحسابات — الجدول المحلي هو المرجع، والبوابة الرسمية هي الحكم على التوكن.

تسلسل الإضافة في "+ Add":
  1) التوكن بيتطبيع (Bearer … أو خام) وبيتفك كـ JWT (الصلاحية/الهوية من الـ claims).
  2) البوابة الرسمية بتسأل "التوكن ده شغال؟" قبل أي كتابة في السجل (validate_token_live).
  3) الاسم الحقيقي للاعب البوابة ما بترجعهش، فـ name_book.json هو اللي بيفتكره لكل
     embark_user_id/SteamID — وأي حساب بيتسجل من اللعبة بياخد اسمه القديم مش اسم مشتق.

ممنوع: أي نداء هنا يمس حالة عنصر في المخزن. الكتابة الوحيدة هي على قائمة الحسابات في البروفايل.
"""
import base64
import json
import os
import re
import time
import uuid

from . import config, pioneer_client, rampart_client, store, xp

ME_CACHE_SECONDS = 600  # /auth/me بيحدد حد الحسابات بس في الهيدر — مفيش لازمة ندفع 330ms كل دقيقتين
STALE_AFTER = 24 * 3600  # نفس قاعدة rampart: الحساب بيتاعت منتهي لو آخر تحديث أقدم من 24 ساعة


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def normalize_token(raw):
    """يقبل 'Bearer eyJ...' أو التوكن الخام، ويرجعه بدون أي بادئة.

    بيشيل كمان المسافات من جوه: النسخ من التيرمنال بيجيب التوكن مقطوع على أسطر
    والـ base64 بيفشل فكّ الـ payload ويطلع "token not valid" على طول.
    """
    tok = str(raw or "").strip().strip('"').strip("'")
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    return re.sub(r"\s+", "", tok)


def jwt_claims(token):
    """يفك جزء الـ payload من JWT. بيرجع {} لو مش JWT صحيح."""
    try:
        parts = token.split(".")
        if len(parts) < 3:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


def token_expiry(token):
    return int(jwt_claims(token).get("exp") or 0)


def is_expired(record, token_exp=None):
    exp = token_exp if token_exp is not None else record.get("token_exp")
    if record.get("is_expired"):
        return True
    return bool(exp) and float(exp) <= time.time()


def short_name(display_name, label, taken):
    """اسم قصير محلي يُستخدم كمفتاح للـ snapshot والـ queries (زي G21 / G22)."""
    seed = (display_name or label or "").split("#")[0]
    base = re.sub(r"[^A-Za-z0-9_-]", "", seed) or ("acc_" + uuid.uuid4().hex[:6])
    name, i = base, 2
    while name in taken:
        name = "%s_%d" % (base, i)
        i += 1
    return name


NAME_BOOK_FILE = os.path.join(config.DATA_DIR, "name_book.json")


def _name_book():
    """معرّف الحساب (embark_user_id / SteamID) → اسمه الحقيقي زي ما ظهر مرة في اللوحة.

    البوابة ما بترجعش اسم اللاعب، فالاسم الحقيقي وحيد المصدر: أي حساب اتسمى قبل كده
    (بالإضافة اليدوية أو من اللوحة). بدون الدفتر ده، أي حذف وإعادة تسجيل بالتوكن
    بيطلع اسم مشتق غريب زي "RAIDER 98197" بدل "G18".
    """
    try:
        with open(NAME_BOOK_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _save_name_book(book):
    try:
        with open(NAME_BOOK_FILE, "w", encoding="utf-8") as fh:
            json.dump(book, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError:
        pass


def remember_name(ident, display):
    """يسمّي المعرّفات باسم حقيقي — بيتم استدعاؤه عند أي تسمية أو تعديل."""
    display = str(display or "").strip()
    if not display or display.upper().startswith("RAIDER"):
        return
    book = _name_book()
    keys = [str(ident.get(k) or "") for k in ("embark_id", "tpuid", "sub")]
    changed = False
    for key in keys:
        if key and book.get(key) != display:
            book[key] = display
            changed = True
    if changed:
        _save_name_book(book)


def lookup_name(ident):
    book = _name_book()
    for key in ("embark_id", "tpuid", "sub"):
        found = book.get(str(ident.get(key) or ""))
        if found:
            return found
    return ""


def _deleted_ids(conn):
    return set(store.get_meta(conn, "accounts:deleted", []) or [])


def _remember_deleted(conn, account_id):
    ids = _deleted_ids(conn)
    ids.add(str(account_id))
    store.set_meta(conn, "accounts:deleted", sorted(ids))


def _record_from_upstream(conn, acc):
    """يحوّل عنصر /auth/embark بتاع rampart لسطر محلي (نفس الحقول بالحرف)."""
    token = normalize_token(acc.get("token") or "")
    exp = acc.get("token_expiry") or token_expiry(token)
    display = acc.get("display_name") or acc.get("label") or "Account"
    taken = {r["name"] for r in store.list_accounts(conn) if r["id"] != acc.get("id")}
    existing = store.get_account(conn, acc.get("id"))
    return {
        "id": acc.get("id"),
        "name": (existing or {}).get("name") or short_name(display, acc.get("label"), taken),
        "label": acc.get("label"),
        "display_name": display,
        "platform": acc.get("platform") or "steam",
        "token": token or (existing or {}).get("token") or "",
        "token_exp": float(exp) if exp else None,
        "embark_id": acc.get("embark_id"),
        "email": acc.get("email"),
        "third_party_name": acc.get("third_party_name"),
        "third_party_user_id": acc.get("third_party_user_id"),
        "owner_username": acc.get("owner_username"),
        "is_active": (existing or {}).get("is_active", 1 if acc.get("is_active") else 0),
        "is_expired": 1 if acc.get("is_expired") else 0,
        "is_restricted": 1 if acc.get("is_restricted") else 0,
        "linked_upstream": 1,
        "added_at": acc.get("added_at") or (existing or {}).get("added_at") or now_iso(),
        "updated_at": acc.get("updated_at") or (existing or {}).get("updated_at"),
    }


def upstream_accounts():
    """قائمة الحسابات من Rampart (GET فقط). بترجع [] لو المنبع واقع أو التوكن منتهي."""
    try:
        return [a for a in rampart_client.list_accounts() if a.get("id")]
    except Exception as e:
        print("[accounts] upstream list unavailable: %s" % e)
        return []


def seed(conn, pull_upstream=True):
    """يتأكد إن الحسابات النشطة في القاعدة ليها سجل، ويجلب الأسماء من Rampart لوConnected."""
    if not (pull_upstream and config.RAMPART_ENABLED):
        active = store.active_account(conn)
        if active:
            store.set_active_account(conn, active["id"])
        return {"seeded": len(store.list_accounts(conn)), "upstream": 0}
    deleted = _deleted_ids(conn)
    imported = 0
    for acc in upstream_accounts():
        if acc["id"] in deleted:
            continue
        store.upsert_account(conn, _record_from_upstream(conn, acc))
        imported += 1
    active = store.active_account(conn)
    if active:
        store.set_active_account(conn, active["id"])
    return {"seeded": len(store.list_accounts(conn)), "upstream": imported}


def match_upstream(token, label="", upstream=None):
    """يدوّر الحساب ده في قائمة rampart بالتوكن أو المعرّف الخارجي أو الاسم."""
    upstream = upstream if upstream is not None else upstream_accounts()
    for acc in upstream:
        if normalize_token(acc.get("token") or "") == token:
            return acc
    claims = jwt_claims(token)
    sub = str(claims.get("sub") or claims.get("player_id") or "")
    if sub:
        for acc in upstream:
            if sub in (str(acc.get("third_party_user_id") or ""), str(acc.get("embark_id") or "")):
                return acc
    needle = (label or "").strip().lower()
    if needle:
        for acc in upstream:
            if needle in ((acc.get("display_name") or "") + " " + (acc.get("label") or "")).lower():
                return acc
    return None


def add(conn, raw_token, label="", link_upstream=False):
    """يضيف حساب. بيرجع (record, note). بيرفع ValueError لو التوكن مش JWT مقبول."""
    token = normalize_token(raw_token)
    claims = jwt_claims(token)
    if not claims:
        raise ValueError("Not a valid JWT token (make sure you copied the whole token, from the first eyJ to the last character)")
    if config.DATA_SOURCE == "pioneer":
        ok, why = pioneer_client.validate_token_live(token)
        if not ok:
            raise ValueError("The gateway rejected the token: %s" % why)
    if any((r.get("token") or "") == token for r in store.list_accounts(conn)):
        raise ValueError("this token is already linked")
    limit = profile_limits(conn)
    if limit.get("limit") and limit.get("count", 0) >= limit["limit"]:
        raise ValueError("limit capacity reached (%s/%s)" % (limit.get("count"), limit.get("limit")))
    if link_upstream and not config.RAMPART_ENABLED:
        link_upstream = False

    match = match_upstream(token, label)
    if match:
        rec = store.upsert_account(conn, _record_from_upstream(conn, match))
        return rec, "imported from rampart (read-only)"
    if link_upstream:
        created = rampart_client.embark_add(token, label)
        created.setdefault("id", str(uuid.uuid4()))
        if not created.get("token"):
            created["token"] = token
        rec = store.upsert_account(conn, _record_from_upstream(conn, created))
        return rec, "linked on rampart"
    taken = {r["name"] for r in store.list_accounts(conn)}
    display = label.strip() or ("ACCOUNT " + (str(claims.get("sub") or claims.get("player_id") or ""))[-6:] or "ACCOUNT")
    rec = store.upsert_account(conn, {
        "id": str(uuid.uuid4()), "name": short_name(display, label, taken), "label": label.strip() or None,
        "display_name": display, "platform": "manual", "token": token,
        "token_exp": float(claims.get("exp") or 0) or None, "is_active": 0, "is_expired": 0,
        "is_restricted": 0, "linked_upstream": 0, "added_at": now_iso(), "updated_at": now_iso(),
    })
    if label.strip():
        remember_name(token_identity(token), label.strip())
    return rec, "saved locally (not linked on rampart yet)"


PIONEER_CLIENT = "embark-pioneer"


def token_identity(token):
    """معرّفات الحساب اللي جوه التوكن: embark_user_id / sub / SteamID — بتستخدم للمطابقة الآلية."""
    claims = jwt_claims(token)
    ext = claims.get("ext") or {}
    return {
        "embark_id": str(ext.get("embark_user_id") or ""),
        "sub": str(claims.get("sub") or ""),
        "tpuid": str(ext.get("tpuid") or ""),
        "client_id": str(ext.get("client_id") or ""),
        "tenancy": str(ext.get("tenancy_name") or ""),
    }


def _identity_match(conn, ident):
    """بيدوّر على حساب بنفس الهوية — بيقارن الأعمدة المحفوظة وفكّ توكنات الحسابات القديمة."""
    for rec in store.list_accounts(conn):
        stored = {
            "embark_id": str(rec.get("embark_id") or ""),
            "sub": "",
            "tpuid": str(rec.get("third_party_user_id") or ""),
        }
        stored["sub"] = str(token_identity(rec.get("token") or "").get("sub") or "")
        for key in ("embark_id", "sub", "tpuid"):
            if ident.get(key) and stored.get(key) and ident[key] == stored[key]:
                return rec
    return None


def auto_upsert(conn, raw_token, owner=None):
    """نقطة دخول الأجن المحلي أو المشتركين: توكن جديد من اللعبة → تسجيل أو تحديث من غير أي لصق.

    بيرجع (record, note, created). بيرفض أي توكن مش بتاع Pioneer أو منتهي.
    لو تم تمرير owner يتم ربط الحساب بـ owner_username الخاص بالمشترك.
    """
    token = normalize_token(raw_token)
    claims = jwt_claims(token)
    if not claims:
        raise ValueError("not a valid authorization token (expected the Pioneer JWT)")
    ident = token_identity(token)
    if ident["client_id"] != PIONEER_CLIENT:
        raise ValueError("token is for %r, not %s" % (ident["client_id"] or "?", PIONEER_CLIENT))
    exp = float(claims.get("exp") or 0)
    if not exp or exp <= time.time():
        raise ValueError("token already expired")

    for rec in store.list_accounts(conn):
        if (rec.get("token") or "") == token:
            patch = {"id": rec["id"]}
            if owner and rec.get("owner_username") != owner:
                patch["owner_username"] = owner
            if not rec.get("embark_id") and ident["embark_id"]:
                patch["embark_id"] = ident["embark_id"]
            if not rec.get("third_party_user_id") and ident["tpuid"]:
                patch["third_party_user_id"] = ident["tpuid"]
            if float(rec.get("token_exp") or 0) != exp or rec.get("is_expired"):
                patch.update({"token_exp": exp, "is_expired": 0, "updated_at": now_iso()})
            if len(patch) > 1:
                rec = store.upsert_account(conn, patch)
            return rec, "token unchanged", False

    # البوابة هي اللي بتقول التوكن ده شغال ولا لا: نسخة مبتورة من الذاكرة بتفكّ صح وبتاخد 401.
    # لو مفيش ضوء أخضر مفيش أي كتابة في السجل — لا حساب جديد ولا توكن بيمسح الشغال.
    ok, why = pioneer_client.validate_token_live(token)
    if not ok:
        raise ValueError("The gateway rejected the token: %s" % why)

    rec = _identity_match(conn, ident)
    if rec:
        stored_exp = float(rec.get("token_exp") or token_expiry(rec.get("token") or "") or 0)
        patch = {"id": rec["id"]}
        if owner and rec.get("owner_username") != owner:
            patch["owner_username"] = owner
        if stored_exp >= exp:
            if len(patch) > 1:
                rec = store.upsert_account(conn, patch)
            return rec, "a newer token is already stored", False
        remembered = lookup_name(ident)
        current = rec.get("display_name") or rec.get("label") or ""
        patch.update({"token": token, "token_exp": exp, "is_expired": 0,
                      "embark_id": ident["embark_id"] or rec.get("embark_id"),
                      "third_party_user_id": ident["tpuid"] or rec.get("third_party_user_id"),
                      "updated_at": now_iso()})
        if owner:
            patch["owner_username"] = owner
        # اسم مشتق ("RAIDER 98197") أحسن حاجة نتخلص منها لو الدفتر يعرف اسمه الحقيقي
        if remembered and (not current or current.upper().startswith("RAIDER")):
            # الاسم الداخلي مفتاح صفوف المخزن: بنغيّر display_name الظاهر بس
            patch["display_name"] = remembered
        updated = store.upsert_account(conn, patch)
        return updated, "token refreshed for existing account", False

    display = lookup_name(ident) or (
        ("RAIDER " + ident["tpuid"][-5:]) if ident["tpuid"] else (
            ("RAIDER " + ident["embark_id"][-5:]) if ident["embark_id"] else "RAIDER NEW"))
    taken = {r["name"] for r in store.list_accounts(conn)}
    created = store.upsert_account(conn, {
        "id": str(uuid.uuid4()), "name": short_name(display, display, taken),
        "label": None, "display_name": display,
        "platform": "steam" if ident["tpuid"].startswith("765611") else "pioneer",
        "token": token, "token_exp": exp, "embark_id": ident["embark_id"] or None,
        "third_party_user_id": ident["tpuid"] or None,
        "owner_username": owner,
        "is_active": 0, "is_expired": 0, "is_restricted": 0, "linked_upstream": 0,
        "added_at": now_iso(), "updated_at": now_iso(), "enabled": 1,
    })
    return created, "registered automatically from the game", True


def link(conn, account_id):
    """يربط حساب محفوظ محلياً على Rampart (POST /auth/embark) — بضغطة صريحة فقط."""
    rec = store.get_account(conn, account_id)
    if not rec:
        raise KeyError("unknown account")
    if rec.get("linked_upstream"):
        return rec, "already linked"
    if not config.RAMPART_ENABLED:
        raise ValueError("Account linking on rampart.su is off — the account is pulled directly from the Embark gateway with the stored token.")
    token = normalize_token(rec.get("token") or "")
    if not token:
        raise ValueError("no token stored for this account")
    created = rampart_client.embark_add(token, rec.get("label") or "")
    new_id = str(created.get("id") or rec["id"])
    created.setdefault("id", new_id)
    if not created.get("token"):
        created["token"] = token
    record = _record_from_upstream(conn, created)
    record["name"] = rec["name"]
    record["label"] = rec.get("label")
    record["is_active"] = rec.get("is_active", 0)
    if new_id != rec["id"]:
        conn.execute("DELETE FROM accounts WHERE id=?", (rec["id"],))
        conn.commit()
    return store.upsert_account(conn, record), "linked on rampart"


def edit(conn, account_id, label=None, raw_token=None, push_upstream=False):
    rec = store.get_account(conn, account_id)
    if not rec:
        raise KeyError("unknown account")
    patch = {"id": rec["id"]}
    token = normalize_token(raw_token) if raw_token else ""
    if token:
        claims = jwt_claims(token)
        if not claims:
            raise ValueError("Not a valid JWT token (make sure you copied the whole token, from the first eyJ to the last character)")
        if config.DATA_SOURCE == "pioneer":
            ok, why = pioneer_client.validate_token_live(token)
            if not ok:
                raise ValueError("The gateway rejected the token: %s" % why)
        patch["token"] = token
        patch["token_exp"] = float(claims.get("exp") or 0) or None
        patch["is_expired"] = 0
        patch["updated_at"] = now_iso()
    if label is not None:
        patch["label"] = label.strip() or None
        # التسمية اليدوية هي المرجع: display_name لو سايبها الاسم القديم بيغطي على التعديل
        patch["display_name"] = label.strip() or (rec.get("display_name") or rec["name"])
        if not token:
            patch["updated_at"] = now_iso()
    if label and str(label).strip():
        remember_name(token_identity(token or rec.get("token") or ""), str(label).strip())
    if token and push_upstream and rec.get("linked_upstream") and config.RAMPART_ENABLED:
        updated = rampart_client.embark_patch(rec["id"], token=token, label=(label or "").strip() or None)
        if updated:
            updated.setdefault("id", rec["id"])
            return store.upsert_account(conn, _record_from_upstream(conn, updated)), "updated on rampart"
    if (push_upstream and config.RAMPART_ENABLED and rec.get("linked_upstream")
            and label is not None and not token):
        rampart_client.embark_patch(rec["id"], label=label.strip() or None)
        return store.upsert_account(conn, patch), "label updated on rampart"
    return store.upsert_account(conn, patch), "updated locally"


def remove(conn, account_id, unlink_upstream=False):
    rec = store.get_account(conn, account_id)
    if not rec:
        raise KeyError("unknown account")
    note = "removed locally"
    if unlink_upstream and rec.get("linked_upstream") and config.RAMPART_ENABLED:
        rampart_client.embark_delete(rec["id"])
        note = "unlinked from rampart"
    _remember_deleted(conn, rec["id"])
    # المعرّفات بتاعت الحساب بتفضل في الدفتر: لو اتسجل تاني بالتوكن بيرجع بنفس اسمه الحقيقي
    remember_name({"embark_id": rec.get("embark_id"), "tpuid": rec.get("third_party_user_id"),
                   "sub": token_identity(rec.get("token") or "").get("sub")},
                  rec.get("display_name") or rec.get("label"))
    name = store.delete_account(conn, rec["id"])
    for row in conn.execute("SELECT path FROM snapshots WHERE account=?", (name,)):
        try:
            os.remove(row["path"])
        except OSError:
            pass
    conn.execute("DELETE FROM snapshots WHERE account=?", (name,))
    conn.execute("DELETE FROM items WHERE account=?", (name,))
    conn.execute("DELETE FROM instances WHERE account=?", (name,))
    conn.execute("DELETE FROM loadouts WHERE account=?", (name,))
    conn.execute("DELETE FROM marks WHERE account=?", (name,))
    # أي بقايا تانية بالحساب ده (إحصاءات/تجار) — الحساب لازم يختفي أثره كله.
    for key in [r["key"] for r in conn.execute("SELECT key FROM meta").fetchall()
                if r["key"].endswith(":" + name)]:
        conn.execute("DELETE FROM meta WHERE key=?", (key,))
    conn.commit()
    return {"removed": rec["id"], "name": name, "note": note}


def select(conn, account_id):
    rec = store.get_account(conn, account_id)
    if not rec:
        raise KeyError("unknown account")
    store.set_active_account(conn, rec["id"])
    return rec


def enabled_pairs(conn):
    """[(اسم قصير, معرّف)] للحسابات المفعّلة اللي تقدر تتسحب.

    في الوضع المباشر (بوابة Embark) التكفيء هو توكن الحساب نفسه، ومعرف rampart ما بيدخلش
    في أي حساب محلي، فالحسابات المحلية بتسحب عادي حتى لو linked_upstream=0.
    """
    direct = config.DATA_SOURCE == "pioneer"
    out = []
    for r in store.list_accounts(conn, enabled_only=True):
        if direct:
            if r.get("token"):
                out.append((r["name"], r["id"]))
        elif r.get("linked_upstream"):
            out.append((r["name"], r["id"]))
    return out


def names(conn):
    return {r["name"]: r["id"] for r in store.list_accounts(conn)}


def profile_limits(conn):
    """حد الحسابات وعدد المسجلين. في الوضع المحلي مفيش حد من Rampart — limit=None."""
    if not config.RAMPART_ENABLED:
        return {"limit": None, "count": len(store.list_accounts(conn)), "me": None}
    cached = store.get_meta(conn, "auth:me") or {}
    fresh = float(cached.get("_cached_at") or 0) > time.time() - ME_CACHE_SECONDS
    if not fresh:
        try:
            cached = rampart_client.me()
            cached["_cached_at"] = time.time()
            store.set_meta(conn, "auth:me", cached)
        except Exception as e:
            print("[accounts] /auth/me unavailable: %s" % e)
            cached = {}
    return {"limit": int(cached.get("account_limit") or config.ACCOUNT_LIMIT),
            "count": len(store.list_accounts(conn)),
            "me": cached}


def wallet(conn, account_name):
    """الإحصاءات الثلاثة + المستوى من XP، من آخر snapshot للحساب ده."""
    stats = store.get_meta(conn, "stats:%s" % account_name, {}) or {}
    out = {}
    for key, title, color in (("coins", "Coins", "#ffffff"), ("cred", "Cred", "#60a5fa"),
                              ("tokens", "Raider Tokens", "#eab14c")):
        entry = stats.get(key) or {}
        out[key] = {"value": entry.get("value") or 0, "image": entry.get("image") or "",
                    "title": title, "color": color}
    level = xp.level_from_xp((stats.get("xp") or {}).get("value"))
    return {"stats": out, "xp": (stats.get("xp") or {}).get("value") or 0, "level": level}


def public(conn, rec, stats_map=None):
    """شكل الحساب للواجهة — التوكن نفسه ما يطلعش في القوائم."""
    stats_map = stats_map or {}
    exp = float(rec.get("token_exp") or 0)
    updated = rec.get("updated_at")
    stale = False
    try:
        stale = updated and (time.time() - time.mktime(time.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S"))) > STALE_AFTER
    except (ValueError, TypeError):
        pass
    return {
        "id": rec["id"], "name": rec["name"], "label": rec.get("label"),
        "display_name": rec.get("display_name") or rec.get("label") or rec["name"],
        "platform": (rec.get("platform") or "steam").lower(),
        "is_active": bool(rec.get("is_active")), "is_expired": is_expired(rec, exp),
        "is_stale": bool(stale), "is_restricted": bool(rec.get("is_restricted")),
        "linked_upstream": bool(rec.get("linked_upstream")),
        "token_exp": exp or None, "token_hours_left": round((exp - time.time()) / 3600, 1) if exp else None,
        "token_preview": (rec.get("token") or "")[:10],
        "added_at": rec.get("added_at"), "updated_at": rec.get("updated_at"),
        "last_sync": rec.get("last_sync"), "items": stats_map.get(rec["name"], {}).get("items", 0),
        "email": rec.get("email"), "third_party_name": rec.get("third_party_name"),
        "embark_id": rec.get("embark_id"),
    }
