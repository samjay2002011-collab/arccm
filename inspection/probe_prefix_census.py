"""جرد مسارات على البوابة بمقياس 404 مقابل 405 (بدون أي كتابة).

المنطق: البوابة بتعرف بادئين فقط لتوكننا — `/v1/pioneer/` و`/v1/shared/` —
وأي حاجة بره دي بترد 403 شاملة، فجرد 403 مافيش منه فايدة. هنا بنجرب أسماء
خدمات جوه البادئنين: 404 = مفيش المسار، 405 = المسار موجود ولیس GET.
جزء تاني: مستندات OAuth العامة على نطاقات Embark (بدون توكن).
"""
import json
import sys
import urllib.request
import urllib.error

sys.path.insert(0, ".")
from backend import pioneer_client

PIONEER = [
    "iap", "iap/v1/mutate", "store", "store/v1/mutate", "offers", "offers/v1/mutate",
    "shop", "purchases", "catalogue", "catalog", "trade", "market", "traders",
    "auth", "identity", "token", "account", "accounts", "profile", "shared",
    "inventory/v1/mutate", "inventory/v1/batch-mutate", "inventory/v1/split",
    "inventory/batch-mutate", "inventory/v1/stacks", "inventory/stacks/split",
    "inventory/v1/split", "inventory/v1/merge", "inventory/v1/combine",
    "inventory/v1/upgrade", "inventory/v1/mutate/batch", "inventory/v2/mutate",
    "inventory/v1/mutate-all", "inventory/v1/mutations", "inventory/v1/operations",
    "inventory/v1/batch", "inventory/v1/bulk", "inventory/v1/actions",
    "inventory/v1/items/split", "inventory/v1/items/merge", "inventory/v1/consolidate",
    "inventory/v1/organize", "inventory/v1/sort",
]
SHARED = [
    "profile", "manifest", "inventory", "inventory/v1/mutate", "inventory/v1/upgrade",
    "inventory/v1/batch-mutate", "inventory/v1/split", "inventory/v1/stacks",
    "store", "offers", "iap", "auth", "account", "trade", "traders", "shop",
    "openapi.json", "pioneer", "v1/pioneer", "v1/pioneer/inventory/v1/mutate",
]
PUBLIC = [
    "https://pioneer.embark.net/.well-known/openid-configuration",
    "https://auth.embark.net/.well-known/openid-configuration",
    "https://embark.net/.well-known/openid-configuration",
    "https://api.embark.net/.well-known/openid-configuration",
    "https://pioneer.embark.net/",
    "https://pioneer.embark.net/.well-known/oauth-authorization-server",
    "https://id.embark.net/.well-known/openid-configuration",
    "https://iap.embark.net/",
    "https://store.embark.net/",
]


def call(url, token=None, method="GET"):
    h = {"User-Agent": pioneer_client.UA, "Accept": "application/json",
         "Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(200)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200)
    except Exception as e:
        return None, str(e)[:120].encode()


def main():
    tok = pioneer_client.account_token()
    for prefix, names in (("/v1/pioneer/", PIONEER), ("/v1/shared/", SHARED)):
        print("\n######## %s" % prefix)
        for name in names:
            path = prefix + name
            code, body = call(pioneer_client.BASE + path, tok)
            print("%-46s GET=%-5s %s" % (path, code,
                                         body.decode("utf-8", "replace").replace("\n", " ")[:60]))
    print("\n######## Embark public (no token)")
    for url in PUBLIC:
        code, body = call(url)
        print("%-58s %s %s" % (url, code, body.decode("utf-8", "replace").replace("\n", " ")[:90]))


if __name__ == "__main__":
    main()
