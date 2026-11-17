"""سويس قراءة فقط على أسماء خدمات محتملة في بوابة Pioneer — GET بس، بلا أي كتابة."""
import sys

sys.path.insert(0, ".")
from backend import pioneer_client as pc  # noqa: E402

CANDIDATES = [
    "/v1/pioneer/knowledge", "/v1/pioneer/recipes", "/v1/pioneer/crafting",
    "/v1/pioneer/craft", "/v1/pioneer/station", "/v1/pioneer/stations",
    "/v1/pioneer/bench", "/v1/pioneer/benches", "/v1/pioneer/modules",
    "/v1/pioneer/outpost", "/v1/pioneer/base", "/v1/pioneer/hideout",
    "/v1/pioneer/collections", "/v1/pioneer/compendium", "/v1/pioneer/journal",
    "/v1/pioneer/character", "/v1/pioneer/characters", "/v1/pioneer/raider",
    "/v1/pioneer/skills", "/v1/pioneer/skill", "/v1/pioneer/xp", "/v1/pioneer/level",
    "/v1/pioneer/progress", "/v1/pioneer/progression", "/v1/pioneer/state",
    "/v1/pioneer/flags", "/v1/pioneer/settings", "/v1/pioneer/config",
    "/v1/pioneer/unlocks", "/v1/pioneer/unlocked", "/v1/pioneer/loadouts",
    "/v1/pioneer/instances", "/v1/pioneer/items", "/v1/pioneer/templates",
    "/v1/pioneer/tutorials", "/v1/pioneer/challenges", "/v1/pioneer/contracts",
    "/v1/pioneer/events", "/v1/pioneer/medals", "/v1/pioneer/stats",
    "/v1/pioneer/quests/active", "/v1/pioneer/quests/completed",
    "/v1/pioneer/traders", "/v1/pioneer/vendor", "/v1/pioneer/vendors",
    "/v1/pioneer/market", "/v1/pioneer/shop", "/v1/pioneer/purchases",
    "/v1/pioneer/orders", "/v1/pioneer/blueprint", "/v1/pioneer/workshop",
    "/v1/pioneer/inventory/upgrade", "/v1/pioneer/inventory/blueprints",
    "/v1/pioneer/inventory/stations", "/v1/pioneer/inventory/knowledge",
    "/v1/pioneer/inventory/state", "/v1/pioneer/inventory/full",
    "/v1/shared/progression", "/v1/shared/settings", "/v1/shared/progress",
    "/v1/shared/services", "/v1/shared/config", "/v1/shared/version",
    "/v1/pioneer", "/v1/pioneer/", "/v1/", "/",
]

account = sys.argv[1] if len(sys.argv) > 1 else "G22"
token = pc.account_token(account)
manifest = pc.load_manifest()
hits = []
for path in CANDIDATES:
    try:
        data = pc.request(path, token=token, manifest_id=manifest)
        kind = "JSON" if data else "EMPTY"
        keys = ",".join(list(data)[:6]) if isinstance(data, dict) else type(data).__name__
        print("HIT  %-38s 200 %s {%s}" % (path, kind, keys))
        hits.append(path)
    except pc.PioneerError as err:
        text = str(err)
        if "404" in text:
            continue
        print("NOTE %-38s %s" % (path, text[:90]))
        hits.append(path)
    except Exception as err:  # noqa: BLE001
        print("BAD  %-38s %s %s" % (path, type(err).__name__, str(err)[:70]))
print("\n=== غير 404:", len(hits))
for h in hits:
    print("   ", h)
