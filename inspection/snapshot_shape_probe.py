"""شكل ملف الـ snapshot المحفوظ: مفتاح علوي ورا قائمة الـ instances الخام."""
import builtins
import glob
import gzip
import json
import os

SNAP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "snapshots")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_snapshot_shape_out.txt")

paths = {}
for p in glob.glob(os.path.join(SNAP_DIR, "*.json.gz")):
    acc = os.path.basename(p).rsplit("_2026", 1)[0]
    if acc not in paths or p > paths[acc]:
        paths[acc] = p

lines = []
for acc in sorted(paths):
    with gzip.open(paths[acc], "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    lines.append(f"== {acc} {os.path.basename(paths[acc])}")
    lines.append("   top keys: " + ", ".join(sorted(data.keys())))
    for key in ("raw", "items", "instances", "tree", "loadout"):
        v = data.get(key)
        if isinstance(v, list):
            lines.append(f"   {key}: list[{len(v)}] first={json.dumps(v[0], ensure_ascii=False)[:300] if v else ''}")
        elif isinstance(v, dict):
            lines.append(f"   {key}: dict keys={sorted(v.keys())[:20]}")
    if "unlocked_blueprints" in data:
        lines.append(f"   unlocked_blueprints n={len(data['unlocked_blueprints'])} "
                     f"first={json.dumps(data['unlocked_blueprints'][:2], ensure_ascii=False)}")
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
builtins.print("wrote", OUT)
