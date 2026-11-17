# -*- coding: utf-8 -*-
"""حصاد كل توكنات JWT في ذاكرة اللعبة (مش Pioneer بس) واختبار أيّها بيفتح الدمج.

ليه: المتجسّس على تاب Rampart مسك `{discriminator:"split"}` بتاعتهم، والقراءة الرسمية
بعدها لقت كوم 100 بقى 8 كومات مجموعها 100 — يعني الكتابة دي وصلت Embark فعلاً.
لكن توكن الرفيق بتاعنا الـ enum بترفض split/combine تحت 66 اسم مختلف (UNKNOWN)،
بينما update/recycle بيردّوا INVENTORY_ITEM_NOT_FOUND. الفرق يبقى في التوكن نفسه:
رامبرت بتطالب المستخدم يلصق "Embark token" — وده على الأرجح توكن نطاق اللعبة،
و `memtoken.inspect` بيرمي أي JWT مش client_id بتاعه Pioneer.de

الطلبات كلها أوراكل بآيدي وهمي: مافيش عنصر بالآيدي ده، فمستحيل يغيّر حاجة في الحساب.

    python -m inspection.jwt_harvest              # اللعبة لازم تكون مفتوحة
    python -m inspection.jwt_harvest --no-probe   # يفكّ ويطبع الـ claims بس
"""
import base64
import ctypes
import json
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402
from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
FAKE = "00000000-0000-4000-8000-000000000000"
PROBE_ACCOUNT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "RAIDER60766"


def _decode(part):
    pad = part + "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(pad).decode("utf-8", "ignore"))


def claims(token):
    """يفكّ أي JWT ويرجّع ملخصه. --loose بيقبل أي alg وأي طول توقيع (توكنات الخدمات التانية)."""
    parts = token.split(".")
    if len(parts) < 3:
        return None
    loose = "--loose" in sys.argv
    try:
        if not loose:
            if len(base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))) != mt.RSA_SIG_BYTES:
                return None
        head, payload = _decode(parts[0]), _decode(parts[1])
    except Exception:
        return None
    if not loose and head.get("alg") != "RS256":
        return None
    if not isinstance(payload, dict):
        return None
    exp = float(payload.get("exp") or 0)
    ext = payload.get("ext") or {}
    return {"token": token, "alg": head.get("alg"), "kid": head.get("kid"),
            "iss": str(payload.get("iss") or ""), "aud": str(payload.get("aud") or ""),
            "sub": str(payload.get("sub") or ""), "scp": payload.get("scp"),
            "client_id": str(ext.get("client_id") or ""), "tenancy": str(ext.get("tenancy_name") or ""),
            "embark_id": str(ext.get("embark_user_id") or ""),
            "iat": float(payload.get("iat") or 0), "exp": exp, "live": exp > time.time(),
            "keys": sorted(k for k in payload if k not in
                           ("iss", "aud", "sub", "scp", "ext", "iat", "exp", "jti")),
            "ext_keys": sorted(ext.keys()) if isinstance(ext, dict) else []}


def harvest(pids):
    found, seen = {}, set()
    for pid in pids:
        handle = None
        try:
            handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                             False, pid)
            if not handle:
                print("  pid %s: OpenProcess فشل (شغّل كمسؤول؟)" % pid)
                continue
            buf = ctypes.create_string_buffer(mt.CHUNK)
            done = ctypes.c_size_t(0)
            deadline = time.time() + mt.MAX_SECONDS * 3
            read_bytes = 0
            for base, size in mt._iter_readable(handle):
                pos, tail = 0, b""
                while pos < size:
                    want = min(mt.CHUNK, size - pos)
                    ok = mt.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos), buf,
                                                       want, ctypes.byref(done))
                    got = done.value if ok else 0
                    if not got:
                        pos += want
                        continue
                    window = tail + buf.raw[:got]
                    for view in (window, window[0::2], window[1::2]):
                        for match in JWT.finditer(view):
                            text = match.group().decode("ascii", "ignore")
                            if len(text) < 200 or text in seen:
                                continue
                            seen.add(text)
                            info = claims(text)
                            if not info:
                                continue
                            key = (info["client_id"], info["aud"], str(info["scp"]),
                                   info["sub"], info["tenancy"])
                            old = found.get(key)
                            if not old or info["iat"] > old["iat"]:
                                found[key] = info
                    tail = window[-mt.OVERLAP:]
                    pos += got
                    read_bytes += got
                    if time.time() > deadline:
                        raise KeyboardInterrupt("انتهت مهلة المسح")
        except KeyboardInterrupt as exc:
            print("  %s" % exc)
        except OSError as exc:
            print("  pid %s: %s" % (pid, exc))
        finally:
            if handle:
                mt.KERNEL32.CloseHandle(handle)
    return sorted(found.values(), key=lambda t: -t["iat"])


def reason(exc):
    text = str(exc)
    try:
        body = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception:
        return text[:110]
    return str(body.get("reason") or body.get("detail") or "?")


def probe(token):
    """أوراكل على توكن واحد: بيقول لو الـ split معروف ليه ولا لأ — من غير أي أثر."""
    out = {}
    try:
        pc.request("/v1/pioneer/inventory", token=token, timeout=15)
        out["read"] = "ok"
    except Exception as exc:
        out["read"] = reason(exc)
    for name in ("update", "split", "combine"):
        try:
            pc.post_json(pw._url(), {"mutations": [{"discriminator": name, "instanceId": FAKE,
                                                    "targetInstanceId": FAKE,
                                                    "targetWrapperId": FAKE, "amount": 1}],
                                     "requestId": ""}, token=token)
            out[name] = "200"
        except Exception as exc:
            out[name] = reason(exc)
        time.sleep(0.15)
    return out


def main():
    pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — افتح ARC Raiders وشغّل الأمر ده تاني.")
        return 1
    print("مسح ذاكرة %s ..." % pids)
    rows = harvest(pids)
    print("لقيت %d توكن (مجموع فريد):\n" % len(rows))
    for r in rows:
        print("  alg=%-7s client_id=%-18s aud=%-26s scp=%-14s sub=%s exp=%s"
              % (r["alg"], r["client_id"] or "-", (r["aud"] or "-")[:26], str(r["scp"])[:14],
                 (r["sub"] or "-")[:12], time.strftime("%Y-%m-%d %H:%M", time.localtime(r["exp"]))))
        if r["keys"]:
            print("     حقول: %s" % ",".join(r["keys"][:10]))
        if r["ext_keys"]:
            print("     ext : %s" % ",".join(r["ext_keys"][:14]))
        if "--no-probe" in sys.argv:
            continue
        if not r["live"]:
            print("     منتهي — متخطّيه")
            continue
        print("     %s" % json.dumps(probe(r["token"]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
