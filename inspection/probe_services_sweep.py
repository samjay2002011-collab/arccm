"""جرد أسماء الخدمات تحت البادئنين اللي توكننا مفتوحين ليه (`/v1/pioneer/` و`/v1/shared/`).

مقياس: GET على الخدمة — 404 = مفيش خدمة، و405/200/401 = فيه حاجة. بنعرف كده
كل الواجهات اللي توكننا شايلها، وبعدين بنفصّص الخدمة اللي تظهر.
قراءة بس (GET)، بتأخير بسيط عشان ما نوطّش الـ rate limit.
"""
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from backend import pioneer_client

SERVICES = [
    "inventory", "item", "items", "stack", "stacks", "split", "merge", "combine",
    "move", "equip", "equipment", "loadout", "loadouts", "stash", "backpack",
    "overflow", "container", "containers", "wrapper", "wrappers", "slot", "slots",
    "offers", "offer", "store", "shop", "market", "trade", "trades", "trader",
    "traders", "exchange", "sell", "buy", "purchase", "purchases", "iap", "payment",
    "payments", "billing", "cart", "checkout", "catalog", "catalogue", "pricing",
    "craft", "crafts", "workshop", "recipe", "recipes", "blueprint", "blueprints",
    "build", "upgrade", "upgrades", "repair", "repairs", "scrap", "recycle",
    "dispose", "delete", "destroy", "quest", "quests", "challenge", "challenges",
    "objective", "objectives", "achievement", "achievements", "progress",
    "profile", "account", "accounts", "user", "users", "identity", "auth", "token",
    "session", "device", "devices", "partner", "companion", "web", "api", "rpc",
    "batch", "bulk", "operation", "operations", "action", "actions", "mutation",
    "mutations", "command", "commands", "task", "tasks", "queue", "job", "jobs",
    "economy", "currency", "wallet", "balance", "coins", "resource", "resources",
    "loot", "drop", "reward", "rewards", "generator", "manifest", "config",
    "settings", "feature", "features", "flags", "telemetry", "report", "reports",
    "notification", "notifications", "message", "messages", "news", "event",
    "events", "match", "matchmaking", "game", "games", "raid", "raids", "team",
    "party", "social", "friends", "clan", "groups", "stats", "statistics",
    "history", "log", "logs", "audit", "health", "status", "version", "debug",
    "internal", "admin", "private", "v2", "v3", "beta", "graphql", "rest", "openapi",
]


def call(path, tok, method="GET"):
    req = urllib.request.Request(pioneer_client.BASE + path, method=method, headers={
        "User-Agent": pioneer_client.UA, "Accept": "application/json",
        "Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(120)
    except urllib.error.HTTPError as e:
        return e.code, e.read(120)
    except Exception as e:
        return None, str(e)[:100].encode()


def main():
    tok = pioneer_client.account_token()
    hits = []
    for prefix in ("/v1/pioneer/", "/v1/shared/"):
        print("\n######## %s" % prefix)
        for i, name in enumerate(SERVICES, 1):
            code, body = call(prefix + name, tok)
            txt = body.decode("utf-8", "replace").replace("\n", " ")[:70]
            if code != 404:
                hits.append(prefix + name)
                print("HIT %-40s %s %s" % (prefix + name, code, txt))
            time.sleep(0.45)
    print("\n======== non-404 summary ========")
    for h in hits:
        print(" ", h)


if __name__ == "__main__":
    main()
