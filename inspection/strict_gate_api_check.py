"""تحقق لايف من الفلترة الصارمة من غير أي كتابة: يقرأ ردود الموقع نفسها.

    python inspection/strict_gate_api_check.py

بيستنى السيرفر يرجع، وبعدين ياخد /api/workshop و/api/workshop/blueprints لكل حساب
ويطبع: عدد الوصفات الظاهرة، كام مخفية، وهل العناصر المشكوك فيها (Tether Launcher
وZipline وSnap Hook) موجودة ولا اختفت، وعدادات شاشة المخطوطات، وعدد الأصول اللي
بتاخد ✔ في المخزن.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_strict_gate_api_out.txt")
SUSPECT = ["tether_launcher", "snap_hook", "zipline", "grappling_hook", "advanced_camera",
           "showstopper", "explosive_mine", "light_ammo", "bandage", "energy_clip"]


def get(path, tries=40):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(BASE + path, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(1.5)
    raise SystemExit("السيرفر ما رجعش على %s" % BASE)


def main():
    lines = []
    accounts = get("/api/accounts")
    names = [a.get("name") for a in (accounts.get("accounts") if isinstance(accounts, dict) else accounts) or []]
    lines.append("حسابات الموقع: %s" % names)
    for name in names:
        data = get("/api/workshop?account=%s" % urllib.parse.quote(name))
        if data.get("pick_account"):
            continue
        rows = data.get("recipes") or []
        slugs = {str(r.get("slug")) for r in rows}
        totals = data.get("totals") or {}
        know = data.get("knowledge") or {}
        lines.append("")
        lines.append("== %s" % name)
        lines.append("   totals: %s" % json.dumps(totals, ensure_ascii=False))
        lines.append("   knowledge: %s" % json.dumps(know, ensure_ascii=False))
        lines.append("   أول 6 وصفات بالاسم: %s" % [r.get("name") for r in rows[:6]])
        for slug in SUSPECT:
            if slug in slugs:
                row = next(r for r in rows if str(r.get("slug")) == slug)
                lines.append("      ظاهرة:  %-22s مخطوطة=%-12s قفل=%s" % (slug, row.get("blueprint") or "-", row.get("lock") or "-"))
            else:
                lines.append("      مخفية:  %s" % slug)
        bad = [r.get("slug") for r in rows if r.get("lock") == "blueprint"]
        lines.append("   وصفات لسه بتستخدم القفل القديم 'blueprint' (%s): %s" % (len(bad), bad))
        bp = get("/api/workshop/blueprints?account=%s" % urllib.parse.quote(name))
        bt = bp.get("totals") or {}
        lines.append("   مخطوطات: cards=%s totals=%s" % (len(bp.get("blueprints") or []),
                                                        json.dumps(bt, ensure_ascii=False)))
        states = {}
        for card in bp.get("blueprints") or []:
            states[card.get("state")] = states.get(card.get("state"), 0) + 1
        lines.append("   توزيع الحالات: %s" % json.dumps(states, ensure_ascii=False))
        lines.append("   كروت craftable=true: %s" % sum(1 for c in bp.get("blueprints") or [] if c.get("craftable")))
        sec = get("/api/sections?account=%s" % urllib.parse.quote(name))
        unlocked = (sec.get("unlocked") or {}) if isinstance(sec, dict) else {}
        lines.append("   ✔ في المخزن: count=%s assets=%s" % (unlocked.get("count"), len(unlocked.get("assets") or [])))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("written: %s (%s lines)" % (OUT, len(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
