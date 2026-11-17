"""ليه عقدة "Unlock Craft Energy Clip" ما بتحلش على energy_clip؟

    python inspection/energy_clip_resolve_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import items_db, knowledge  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_energy_clip_resolve_out.txt")

NAME = "Energy Clip"


def main():
    lines = []
    maps = knowledge._bp_maps()
    recipes = knowledge._recipe_maps()
    core = knowledge._core(NAME)
    fam = knowledge._core(NAME, keep_level=False)
    key = items_db.norm(NAME)
    lines.append("norm=%r core=%s family=%s" % (key, sorted(core), sorted(fam)))
    lines.append("items_db.find(name)=%s" % (items_db.find(name=NAME) or {}).get("slug"))
    lines.append("bp targets فيها؟ exact=%s core=%s family=%s"
                 % (key in (recipes["exact"] or {}), maps["core"].get(core), maps["family"].get(fam)))
    lines.append("recipes exact=%s" % sorted(recipes["exact"].get(key) or ()))
    lines.append("recipes core=%s" % sorted(recipes["core"].get(core) or ()))
    lines.append("recipes family=%s" % sorted(recipes["family"].get(fam) or ()))
    lines.append("_single(core)=%s _single(family)=%s"
                 % (knowledge._single(recipes["core"], core),
                    knowledge._single(recipes["family"], fam)))
    lines.append("_resolve_target=%s" % knowledge._resolve_target(NAME))
    lines.append("exact map keys فيها clip: %s"
                 % [k for k in recipes["exact"] if "clip" in k][:20])
    lines.append("craftable rows فيها clip: %s"
                 % [(r.get("slug"), r.get("name")) for r in items_db.craftable_rows()
                    if "clip" in items_db.norm(str(r.get("name") or ""))])
    lines.append("blueprint_rows targets فيها clip: %s"
                 % [(r.get("slug"), r.get("target"), r.get("target_name"))
                    for r in items_db.blueprint_rows() if "clip" in items_db.norm(str(r.get("target_name") or ""))])
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("written: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
