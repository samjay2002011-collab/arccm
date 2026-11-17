"""كل أسماء الفهرس اللي فيها 'unlock' — عشان نكشف كل أشكال تسمية عقدة التفعيل.

القياس اللي فتح الملف ده: في أصل عند G22 اسمه 'Unlock Surge Coil Craft' (العكس!)،
فالفلترة السابقة كانت بتقرأ "Unlock Craft X" بس وبتضيع أي عقدة مكتوبة بشكل تاني.
"""
import builtins
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pioneer_tree  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_unlock_names_all_out.txt")


def main():
    names = pioneer_tree.asset_names()
    rows = []
    for aid, row in names.items():
        for field in ("display_name", "game_asset_name"):
            label = str(row.get(field) or "").strip()
            if label and "unlock" in label.lower():
                rows.append((str(aid), field, label,
                             str(row.get("game_asset_name") or ""),
                             str(row.get("display_name") or "")))
                break
    lines = [f"اجمالي صفوف الفهرس={len(names)}  وفيها 'unlock'={len(rows)}"]
    pats = {}
    for aid, field, label, gname, dname in rows:
        shape = re.sub(r"[A-Za-z0-9'’\.\-\(\)]+", "%s", label)
        pats.setdefault(shape, []).append(label)
    lines.append("\n== أشكال الأسماء ==")
    for shape, labels in sorted(pats.items(), key=lambda i: -len(i[1])):
        lines.append(f"  {shape!r:24s} n={len(labels)}  أمثلة={labels[:6]}")
    lines.append("\n== اللي مش 'Unlock Craft ...' بالظبط ==")
    for aid, field, label, gname, dname in sorted(rows, key=lambda r: r[2]):
        if not label.startswith("Unlock Craft "):
            lines.append(f"  {aid:>13} | display={dname!r} | asset_name={gname!r}")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    builtins.print("wrote", OUT, "| rows with unlock:", len(rows))


if __name__ == "__main__":
    main()
