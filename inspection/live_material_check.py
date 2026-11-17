"""فحص حي لعدّاد الخامات من الـ API بعد إعادة التشغيل (قراءة وبس).

بيطلب /api/workshop لكل حساب وبيطبع: الخامات اللي كانت غلطانة، ورقم العرض بتاع
Anvil I، وأي خامة لسه عدّها صفر مع إن اسمها موجود في شجرة الحساب.
"""
import io
import json
import os
import sys
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_live_material_check_out.txt")
BASE = "http://127.0.0.1:8000"
WATCH = {"anvil_i": "Hand Drill", "arc_circuitry": None, "zippline": None}
ACCOUNTS = ("RAIDER38830", "G14", "G18", "G22", "RAIDER74888")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    buf = io.StringIO()
    w = buf.write
    for name in ACCOUNTS:
        data = get("/api/workshop?" + urllib.parse.urlencode({"account": name}))
        rows = data.get("recipes") or []
        zero_named = [(r["slug"], m["name"], m["need"]) for r in rows for m in r["materials"]
                      if m["owned"] == 0 and not m.get("asset_ids")]
        w("\n== %s == وصفات=%s | جاهزة=%s | أرقام عروض=%s | خامات بلا رقم=%s\n"
          % (name, data["totals"]["recipes"], data["totals"]["ready"],
             sum(1 for r in rows if r.get("offer_id")), len(zero_named)))
        anvil = next((r for r in rows if r["slug"] == "anvil_i"), None)
        if anvil:
            w("   Anvil I: offer_id=%s can_craft=%s max_now=%s\n"
              % (anvil.get("offer_id"), anvil.get("can_craft"), anvil.get("max_now")))
            for m in anvil["materials"]:
                w("      %-34s %s/%s  ids=%s\n" % (m["name"], m["have"], m["need"], m["asset_ids"]))
        else:
            w("   Anvil I مش في مصنع الحساب ده (طبيعي لو ملوش عقدة تفعيل).\n")
        for slug, mat, need in zero_named:
            w("   ! %-22s %-30s مطلوب %s وملهاش أي رقم مقاس\n" % (slug, mat, need))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
