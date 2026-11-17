"""يحمّل أيقونات محطات الورشة من arctracker.io ويصغّرها محليًا.

المصدر: data/hideout.json (نسخة رسمية من /api/hideout) — كل محطة ليها رسم لكل
مستوى، وده بالظبط اللي بيظهر في شريط الورشة جوه اللعبة. الصور بتتخزن في
frontend/assets/hideout/ عشان الموقع يقراها بدون أي اتصال.

استعمال: python inspection/build_hideout_assets.py
"""
import io
import json
import os
import sys
import urllib.request

from PIL import Image

sys.path.insert(0, ".")

from backend import config  # noqa: E402

BASE = "https://arctracker.io"
HIDEOUT = os.path.join(config.DATA_DIR, "hideout.json")
OUT_DIR = os.path.join(config.FRONTEND_DIR, "assets", "hideout")
BASE_ICONS = ["scrappy", "gunsmith", "gear_bench", "utility_station", "explosives_station",
              "refiner", "medical_lab", "workbench", "research_station", "stash"]
MAX_EDGE = 320


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fahmy-local-asset-cache"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read()


def save(raw, name):
    img = Image.open(io.BytesIO(raw))
    img.load()
    if max(img.size) > MAX_EDGE:
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    path = os.path.join(OUT_DIR, name + ".webp")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.save(path, "WEBP", quality=82, method=6)
    return os.path.getsize(path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    data = json.load(open(HIDEOUT, encoding="utf-8"))
    modules = data.get("hideoutModules") or {}
    manifest = {}
    done = skipped = failed = 0
    for name in BASE_ICONS:
        target = os.path.join(OUT_DIR, "base_" + name + ".webp")
        if os.path.exists(target):
            manifest.setdefault("_base", {})["base_" + name] = "/assets/hideout/base_%s.webp" % name
            skipped += 1
            continue
        url = "%s/images/hideout/%s.png" % (BASE, name)
        try:
            size = save(fetch(url), "base_" + name)
            manifest.setdefault("_base", {})["base_" + name] = "/assets/hideout/base_%s.webp" % name
            print("OK   base/%-18s %6.1f KB" % (name, size / 1024))
            done += 1
        except Exception as err:  # noqa: BLE001
            print("FAIL base/%s %s" % (name, err))
            failed += 1
    for module_id, module in sorted(modules.items()):
        levels = {}
        for level in module.get("levels") or []:
            image = str(level.get("image") or "")
            if not image:
                continue
            key = "%s/%s" % (module_id, level.get("level"))
            if os.path.exists(os.path.join(OUT_DIR, key + ".webp")):
                skipped += 1
                levels[str(level.get("level"))] = "/assets/hideout/%s.webp" % key
                continue
            try:
                size = save(fetch(BASE + image), key)
                levels[str(level.get("level"))] = "/assets/hideout/%s.webp" % key
                print("OK   %-18s L%s %6.1f KB" % (module_id, level.get("level"), size / 1024))
                done += 1
            except Exception as err:  # noqa: BLE001
                print("FAIL %s L%s %s" % (module_id, level.get("level"), err))
                failed += 1
        if levels:
            manifest[module_id] = levels
    out = os.path.join(config.DATA_DIR, "hideout_icons.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print("\nمحمول %d، متجاهل %d، فاشل %d -> %s" % (done, skipped, failed, out))


if __name__ == "__main__":
    main()
