"""بحث عن مصدر آلي لاسم اللاعب الحقيقي داخل بيانات بوابة Pioneer.

قراءة فقط: ما بيبعتش أي mutate ولا بيغيّر حاجة في القاعدة.
الهدف نعرف لو في مسار JSON بيرجع "G14 #0847" بدل ما نكتفي بـ RAIDER + آخر 5رقام من الستيم.

    python inspection/find_name_source.py [الحساب]
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import config, pioneer_client, store  # noqa: E402

NAME_KEYS = re.compile(r"(name|nick|label|handle|raider|profil|display|alias|title|motto|clan|squad|tag)", re.I)
VALUE_HINTS = re.compile(r"^[A-Za-z0-9_.\- ]{1,32}(#[0-9]{3,5})?$")


def walk(node, path=""):
    """كل المسارات اللي مفتاحها يشبه الاسم، متكررة تحت بعضها بمسار واحد لكل شكل."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = "%s.%s" % (path, k)
            if isinstance(v, (str, int)) and v != "" and NAME_KEYS.search(str(k)):
                out.append((p, v))
            out.extend(walk(v, p))
    elif isinstance(node, list):
        for i, v in enumerate(node[:50]):
            out.extend(walk(v, "%s[]" % path))
    return out


def schema(node, path="", depth=0, seen=None):
    """خريطة مفاتيح الرد الكاملة (مسار واحد لكل شكل) عشان نتأكد إن مفيش أي حقل اسم مخفي."""
    seen = seen if seen is not None else {}
    if isinstance(node, dict):
        for k, v in node.items():
            p = "%s.%s" % (path, k)
            key = re.sub(r"\[(?:[0-9]|\d+)\]", "[]", p)
            if key not in seen:
                seen[key] = ("<%s>" % type(v).__name__) if isinstance(v, (dict, list)) else str(v)[:40]
            schema(v, p, depth + 1, seen)
    elif isinstance(node, list):
        for v in node[:20]:
            schema(v, path + "[]", depth + 1, seen)
    return seen


def main():
    conn = store.db()
    acc = store.active_account(conn)
    if not acc:
        print("مفيش حساب في القاعدة")
        return
    token = acc["token"]
    manifest = pioneer_client.load_manifest()
    print("الحساب في القاعدة: name=%s display=%s steam=%s embark=%s"
          % (acc["name"], acc.get("display_name"), acc.get("third_party_user_id"), acc.get("embark_id")))
    for path in ("/v1/pioneer/raiders", "/v1/pioneer/inventory"):
        try:
            data = pioneer_client.request(path, token=token, manifest_id=manifest, timeout=25)
        except Exception as e:
            print("%s -> %s: %s" % (path, type(e).__name__, e))
            continue
        blob = json.dumps(data, ensure_ascii=False)
        print("\n=== %s (%d بايت) ===" % (path, len(blob)))
        print("خريطة المفاتيح:")
        for key, sample in sorted(schema(data).items()):
            print("  %-62s %s" % (key[:62], sample))
        collapse = {}
        for p, v in walk(data):
            k = re.sub(r"\[\d+\]", "[]", p)
            collapse.setdefault(k, v)
        print("مفاتيح تشبه الاسم:")
        for k, v in sorted(collapse.items()):
            print("  %-58s = %s" % (k[:58], str(v)[:60]))
        for hint in ("G14", "0847", "SPERANZA"):
            for m in list(re.finditer(re.escape(hint), blob, re.I))[:4]:
                print("  تلميح %r في السياق: …%s…" % (hint, blob[max(0, m.start() - 70):m.end() + 40].replace("\n", "")))
    conn.close()


if __name__ == "__main__":
    main()
