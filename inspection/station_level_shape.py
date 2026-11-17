"""كل محطة ومطلوب لها كام مستوى من الوصفات (بيانات arctracker المحلية).

    python inspection/station_level_shape.py
"""
import io
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_station_level_shape_out.txt")


def main():
    buf = io.StringIO()
    w = buf.write
    per_station = defaultdict(Counter)
    for row in items_db.craftable_rows():
        for st in (row.get("stations") or []):
            per_station[st][int(row.get("station_level") or 0)] += 1

    w("===== توزيع مستويات الوصفات على المحطات =====\n")
    for key, label in workshop.STATIONS:
        levels = per_station.get(key) or Counter()
        w("   %-16s (%-18s) الوصفات=%-4s المستويات المطلوبة=%s  بتقرا من السيرفر=%s\n" % (
            key, label, sum(levels.values()), dict(sorted(levels.items())) or "-",
            key in knowledge.BENCH_STATIONS))

    w("\n===== بيانات hideout لكل محطة (أقصى مستوى + الجاي) =====\n")
    from backend import hideout
    for key, label in workshop.STATIONS:
        station = hideout.station(key, 1) if key != "in_raid" else {}
        w("   %-16s label=%-20s max_level=%s next=%s\n" % (
            key, station.get("label") or label, station.get("max_level"),
            (station.get("next") or {}).get("level")))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
