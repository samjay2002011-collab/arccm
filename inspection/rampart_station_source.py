"""شغال القراءة: رامبارت بتجيب مستوى المحطة منين؟

بيلفّ على ملفات JS المحفوظة وبيطبع كل سياقaround كلمة stationLevel/bench
(120 حرف قبل وبعد) — عشان نشوف هل هي قيمة بترجع من الـ API بتاعهم ولا
قائمة صلبة مكتوبة جوه الكود.
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_rampart_station_source_out.txt")
FILES = ("rampart_js/index-CcWZfx3c.js", "rampart_js/_assets_AdminItems-B3z0ClYo_js")
WORDS = ("stationLevel", "benchLevel", "bench_level", "station_level", "hideoutLevel",
         "stationExperience", "upgradeStation", "craftingStation")


def main():
    buf = io.StringIO()
    w = buf.write
    for rel in FILES:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            w("== %s: مش موجود\n" % rel)
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        w("\n===== %s (%s حرف)\n" % (rel, len(text)))
        for word in WORDS:
            positions = [m.start() for m in re.finditer(re.escape(word), text)]
            w("   -- %s: %s موضع\n" % (word, len(positions)))
            for pos in positions[:12]:
                w("      ...%s...\n" % text[max(0, pos - 160):pos + 220].replace("\n", " "))
        # أي مسار API بذكر stations/bench
        for m in re.finditer(r'"/[^"]{0,80}(?:station|bench|hideout|unlock|progress)[^"]{0,40}"', text):
            w("   API-ish: %s\n" % m.group(0))
    open(OUT, "w", encoding="utf-8").write(buf.getvalue())
    print("wrote", OUT)


if __name__ == "__main__":
    main()
