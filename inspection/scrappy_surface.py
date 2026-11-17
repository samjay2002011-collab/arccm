# -*- coding: utf-8 -*-
"""مسح قراءة-only لسطح Scrappy على بوابة Embark الرسمية.

مفيش أي كتابة: GET بس، ومفيش POST على مسار قَبول العروض (ممكن يصرف حاجة فعلًا).

الأسئلة بالترتيب:
  1) رد /v1/pioneer/inventory الخام فيه مفاتيح فوق `items`؟ (لو فيه، هنا اللوت)
  2) عقدة الديك (DA_Item_ResourceGenerator_01..05 / DA_OI_Scrappy_Rooster) موجودة
     في الشجرة؟ وإيه كل الحقول اللي جواها بالظبط؟
  3) /v1/pioneer/bonuses بيرجّع إيه لحساب فيه الديك مركّب؟
  4) ميزان 404-ضد-405: أي مسار تحت /v1/pioneer/ موجود فعلًا للتوكن ده.

    python -m inspection.scrappy_surface            # كل الحسابات
    python -m inspection.scrappy_surface G22        # حساب واحد
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc, store  # noqa: E402

# أرقام الأصول مقاسة من data/catalog/asset_index.csv — مش تخمين.
GEN_ASSETS = {
    "1657228973": "Scrappy I (DA_Item_ResourceGenerator_01)",
    "2041317243": "Scrappy II (DA_Item_ResourceGenerator_02)",
    "1434069496": "Scrappy III (DA_Item_ResourceGenerator_03)",
    "2080275953": "Scrappy IV (DA_Item_ResourceGenerator_04)",
    "1781867314": "Scrappy V (DA_Item_ResourceGenerator_05)",
    "-684951495": "Hideout rooster object (DA_OI_Scrappy_Rooster)",
}

ROUTES = [
    "/v1/pioneer/zzz-not-a-route",          # كنترول: 404
    "/v1/pioneer/inventory",                # كنترول: 200
    "/v1/pioneer/inventory/v1/mutate",      # كنترول: 405 (مسار كتابة موجود)
    "/v1/pioneer/bonuses",
    "/v1/pioneer/bonuses/claim",
    "/v1/pioneer/bonuses/collect",
    "/v1/pioneer/bonuses/accept",
    "/v1/pioneer/offers",
    "/v1/pioneer/offers/accept",
    "/v1/pioneer/offers/claim",
    "/v1/pioneer/offers/collect",
    "/v1/pioneer/offers/list",
    "/v1/pioneer/offers/pending",
    "/v1/pioneer/offers/active",
    "/v1/pioneer/generator",
    "/v1/pioneer/generators",
    "/v1/pioneer/generators/claim",
    "/v1/pioneer/scrappy",
    "/v1/pioneer/scrappy/claim",
    "/v1/pioneer/scrappy/collect",
    "/v1/pioneer/hideout",
    "/v1/pioneer/hideout/bonuses",
    "/v1/pioneer/hideout/objects",
    "/v1/pioneer/production",
    "/v1/pioneer/production/claim",
    "/v1/pioneer/resources",
    "/v1/pioneer/inventory/claim",
    "/v1/pioneer/inventory/v1/claim",
    "/v1/pioneer/inventory/v1/collect",
    "/v1/pioneer/inventory/generators",
    "/v1/pioneer/quests/claim",
    "/v1/pioneer/quests/complete",
    "/v1/pioneer/progression",
    "/v1/pioneer/events",
    "/v1/pioneer/profile",
]


def brief(value, limit=900):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:limit]
    except Exception:
        return str(value)[:limit]


def rooster_subtree(items, hits):
    """افرش شجرة جسم الديك بالظبط: كل خانة وكل قطعة تحتها — الأسماء من الفهرس المحلي."""
    from backend import pioneer_tree
    names = pioneer_tree.asset_names()
    by_id = {str(n.get("instanceId")): n for n in items}
    parents = {}
    for node in items:
        for kid in (node.get("slots") or []):
            parents[str(kid)] = str(node.get("instanceId"))

    def label(node):
        row = names.get(str(node.get("gameAssetId"))) or {}
        return (row.get("display_name") or row.get("game_asset_name")
                or "asset %s" % node.get("gameAssetId"))

    def walk(iid, depth):
        node = by_id.get(iid)
        if not node:
            print("    %s؟ %s (مش في الرد)" % ("  " * depth, iid[:8]))
            return
        kids = [str(k) for k in (node.get("slots") or [])]
        print("    %s%s ×%s  [%s] etag=%s" % ("  " * depth, label(node), node.get("amount"),
                                              iid[:8], node.get("etag")))
        for kid in kids:
            walk(kid, depth + 1)

    for node in hits:
        if str(node.get("gameAssetId")) != "-684951495":
            continue
        iid = str(node.get("instanceId"))
        chain, cur, guard = [], iid, 0
        while cur in parents and guard < 12:
            cur = parents[cur]
            chain.append(label(by_id[cur]) if cur in by_id else cur[:8])
            guard += 1
        print("  مكان جسم الديك في الشجرة: %s" % (" ← ".join(chain) or "parentless (أوفر ستاش)"))
        print("  شجرة جسم الديك:")
        walk(iid, 1)


def account_rows():
    conn = store.db()
    return [r for r in store.list_accounts(conn) if r.get("token")]


def scan_account(name):
    print("\n" + "=" * 78)
    print("### %s" % name)
    token = pc.account_token(name)
    if not token:
        print("  مفيش توكن — اتخطّى")
        return
    try:
        data = pc.fetch_inventory_for(name)
    except Exception as err:
        print("  فشل قراية المخزون: %s" % str(err)[:200])
        return
    items = (data or {}).get("items") or []
    print("  مفاتيح رد /v1/pioneer/inventory:", sorted((data or {}).keys()))
    for key, value in (data or {}).items():
        if key == "items":
            continue
        print("    %-22s %s" % (key, brief(value, 400)))
    print("  عدد العقد:", len(items))
    hits = [n for n in items if str(n.get("gameAssetId")) in GEN_ASSETS]
    if not hits:
        print("  ⛔ مفيش ولا عقدة ديكية في الشجرة")
    for node in hits:
        print("  ✔ %s" % GEN_ASSETS[str(node.get("gameAssetId"))])
        print("     %s" % brief(node, 1200))
    rooster_subtree(items, hits)
    # أي مفتوح في أي عقدة فيه كلمة generat/scrappy/claim/offer/box؟
    words = ("generat", "scrappy", "claim", "offer", "collect", "box", "chicken", "reward")
    found = {}
    for node in items:
        for key, value in node.items():
            text = str(key).lower()
            if any(w in text for w in words) and value not in (None, [], {}, "", 0):
                found.setdefault(key, []).append(brief(value, 120))
    for key, samples in sorted(found.items()):
        print("  حقل مثير: %-20s (%d نسخة) مثال: %s" % (key, len(samples), samples[0]))
    # bonuses كامل
    for path in ("/v1/pioneer/bonuses", "/v1/pioneer/raiders"):
        try:
            payload = pc.request(path, token=token)
            print("  GET %s -> %s" % (path, brief(payload, 700)))
        except Exception as err:
            print("  GET %s -> خطأ %s" % (path, str(err)[:160]))


def route_census(name):
    token = pc.account_token(name)
    sess = pc._session()
    headers = pc.headers(token)
    print("\n" + "-" * 78)
    print("### ميزان المسارات (GET) على %s — 405=موجود / 404=مش موجود" % name)
    for path in ROUTES:
        try:
            resp = sess.get(pc.BASE + path, headers=headers, timeout=20, verify=True)
        except Exception as err:
            print("  !! %-40s %s" % (path, str(err)[:120]))
            continue
        try:
            code = (json.loads(resp.text).get("code") or "")
        except Exception:
            code = ""
        mark = "**" if resp.status_code in (200, 405) else "  "
        print("  %s GET %-42s %s %-28s %s" % (mark, path, resp.status_code, code,
                                              resp.text[:90].replace("\n", " ")))


def main():
    wanted = {w.lower() for w in sys.argv[1:]}
    rows = account_rows()
    picked = [r for r in rows
              if not wanted or wanted & {str(r.get(k) or "").lower()
                                         for k in ("name", "display_name", "label")}]
    print("الحسابات:", ", ".join("%s(%s)" % (r.get("name"), r.get("display_name") or "-")
                                 for r in picked))
    for row in picked:
        scan_account(row["name"])
    if picked:
        route_census(picked[0]["name"])


if __name__ == "__main__":
    main()
