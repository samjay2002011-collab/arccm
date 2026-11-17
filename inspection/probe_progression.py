"""مسبار قراءة فقط: هل البوابة الرسمية بتكشف البلوبرنتات المفعّلة ومستويات الورشة؟

مفيش أي كتابة هنا: GET بس، ومفيش أي مسار من مسارات mutate. التوكن ما بيطبعش.
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"

PATHS = [
    "/v1/pioneer/inventory",
    "/v1/pioneer/quests",
    "/v1/pioneer/raiders",
    "/v1/pioneer/workshop",
    "/v1/pioneer/blueprints",
    "/v1/pioneer/stations",
    "/v1/pioneer/hideout",
    "/v1/pioneer/crafting",
    "/v1/pioneer/progression",
    "/v1/pioneer/profile",
    "/v1/pioneer/traders",
    "/v1/pioneer/shop",
    "/v1/pioneer/stats",
    "/v1/pioneer/projects",
    "/v1/pioneer/medals",
    "/v1/pioneer/loadout",
    "/v1/pioneer/settings",
    "/v1/pioneer/unlocks",
    "/v1/shared/profile",
]


def shape(value, depth=0, max_depth=3):
    """وصف مختصر للـ JSON من غير ما نطبع حمولة كاملة."""
    pad = "  " * depth
    if isinstance(value, dict):
        if depth >= max_depth:
            return "{%s}" % ",".join(list(value)[:8])
        lines = []
        for k, v in list(value.items())[:40]:
            lines.append("%s  %s: %s" % (pad, k, shape(v, depth + 1, max_depth)))
        return "{\n" + "\n".join(lines) + "\n" + pad + "}"
    if isinstance(value, list):
        head = shape(value[0], depth, max_depth) if value else ""
        return "[%d] %s" % (len(value), head)
    if isinstance(value, str):
        return json.dumps(value[:70])
    return repr(value)


def main():
    token = pc.account_token(ACCOUNT)
    if not token:
        print("مفيش توكن لحساب", ACCOUNT)
        return
    print("### account:", ACCOUNT, "| manifest:", pc.load_manifest()[:12], "\n")
    for path in PATHS:
        try:
            data = pc.request(path, token=token)
        except pc.PioneerError as err:
            print("GET %-28s -> %s" % (path, str(err)[:110]))
            continue
        except Exception as err:  # noqa: BLE001
            print("GET %-28s -> %s: %s" % (path, type(err).__name__, str(err)[:90]))
            continue
        print("GET %-28s -> 200 %s" % (path, shape(data)))
        print()


if __name__ == "__main__":
    main()
