# -*- coding: utf-8 -*-
"""سطح الـ crates على البوابة: قراءة + مخطط مسارات الكتابة — صفر أثر.

الفرض: قبض Scrappy مش عرض RoundCrafting (كل الصور اترفضت بنفس `400 internal error`
مهما كان الجسم، يعني الرفض شرط سيرفي مش شكل الطلب). الصندوق جوه اللعبة crate،
والcensus لقى `crates/claim` و`crates/open` موجودين (405 على GET) و`GET /v1/pioneer/crates`
بيرد `{"crates": null}`.

الخطوات:
  1) GET crates بمعامل مختلفة — نعرف إيه اللي بيفرّج عن الصناديق المستنّية.
  2) رسم مخطط `crates/claim` و`crates/open` برسائل فك الترميز نفسها (حقل بنوع غلط
     اسمه بيرجع، وحقل مجهول بيتتجاهل). الأجسام كلها أيدي وهمية ومفيش أصلًا أي crate
     عند الحساب، فمفيش ما يُصرف أو يُفتح.
  3) جرد أنواع الكااتalog اللي فيها crate في game-data (ربط الديك بالصندوق).

    python -m inspection.crates_surface G18
"""
import json
import sys

sys.path.insert(0, ".")

from backend import pioneer_client as pc  # noqa: E402

GAME_DATA = "data/pioneer_game_data.json"
GHOST = "00000000-0000-4000-8000-000000000000"
PROBE = {"probe": 1}

READS = [
    "/v1/pioneer/crates", "/v1/pioneer/crates?state=pending", "/v1/pioneer/crates?all=true",
    "/v1/pioneer/crates?type=generator", "/v1/pioneer/crates?category=scrappy",
    "/v1/pioneer/crates/list", "/v1/pioneer/crates/pending", "/v1/pioneer/crates/claimed",
    "/v1/pioneer/generator", "/v1/pioneer/generators", "/v1/pioneer/hideout",
    "/v1/pioneer/hideout/crates", "/v1/pioneer/loot", "/v1/pioneer/drops",
]
WRITE_ROUTES = ["/v1/pioneer/crates/claim", "/v1/pioneer/crates/open"]
CLAIM_FIELDS = ["crateId", "crates", "crateIds", "id", "ids", "instanceId", "instanceIds",
                "transactionId", "type", "amount", "all", "claimAll", "openAll", "keys",
                "keyInstanceId", "gameAssetId", "ownerInstanceId", "slotId", "raiderId",
                "skipAnimation", "dryRun", "reason"]


def ask_post(path, body, token):
    try:
        resp = pc.post_json(path, body, token=token)
        return "200 " + json.dumps(resp, ensure_ascii=False)[:200]
    except Exception as err:
        text = str(err)
        if "cannot unmarshal" in text:
            return "FIELD>> " + text.split("cannot unmarshal", 1)[1][:120]
        return "refusal: " + text.split("->")[-1].strip()[:90]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account)
    print("###GET crates ومجاوراتها")
    for path in READS:
        try:
            payload = pc.request(path, token=token)
            print("  %-46s -> 200 %s" % (path, json.dumps(payload, ensure_ascii=False)[:220]))
        except Exception as err:
            print("  %-46s -> %s" % (path, str(err).split("->")[-1].strip()[:90]))

    print("\n###مخطط مسارات الكتابة")
    for path in WRITE_ROUTES:
        print("  --", path)
        print("     كنترول (فاضي):", ask_post(path, {}, token))
        print("     كنترول (id وهمي):", ask_post(path, {"crateId": GHOST}, token))
        hits = []
        for name in CLAIM_FIELDS:
            verdict = ask_post(path, {name: PROBE}, token)
            if verdict.startswith("FIELD>>"):
                hits.append((name, verdict[7:].strip()))
                print("     +-- %-18s %s" % (name, verdict[7:].strip()))
        print("     الحقول المؤكدة:", [n for n, _ in hits] or "مفيش (كل الأسماء مجهولة)")

    print("\n###أي حاجة في game-data اسمها crate/scrappy/generator")
    d = json.load(open(GAME_DATA, encoding="utf-8"))
    sections = {k: v for k, v in d.items() if isinstance(v, (dict, list))}
    for k in sections:
        text = json.dumps(d[k], ensure_ascii=False)
        for needle in ("Crate", "ResourceGenerator", "Scrappy"):
            if needle in text:
                print("  %-24s %s -> %d مرة" % (k, needle, text.count(needle)))
    items = d["items-description"]["itemDescriptions"]
    print("\n###الآيتمات اللي اسمها فيه Crate")
    from backend import pioneer_tree
    amap = pioneer_tree.asset_names()
    hits = [(a, (r or {}).get("game_asset_name") or "") for a, r in amap.items()
            if "Crate" in ((r or {}).get("game_asset_name") or "")]
    print("  ", len(hits), hits[:12])


if __name__ == "__main__":
    main()
