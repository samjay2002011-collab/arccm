# -*- coding: utf-8 -*-
"""بيعيل مسار/عملية استلام لوت Scrappy على البوابة الرسمية — من غير أي أثر على الحساب.

الغلطة اللي اتعملت قبل كده: طلعنا أسماء من عندنا، جبنالها 404، وقلنا "التوكن مابعرفش".
404 مش دليل. الأوراكل المعتمدة هنا كلها **دليل موجب**:

1) مسار موجود بس بيستقبل POST = GET بيرد **405 Method Not Allowed**، والمسار الوهمي
   بيرد **404 page not found**. دي نفس الطريقة اللي كشفت `/v1/pioneer/inventory/upgrade`
   (ضبطت 405 وهي الوحيدة تحت `/v1/pioneer/inventory/`). فالمسح بالـ GET آمن تمامًا:
   مافيش كتابة خالص، والـ405 بيقولنا فين الكتابة فعلًا.

2) على `/v1/pioneer/inventory/v1/mutate`: أي discriminator مش في enum التوكن بيرد
   `UNKNOWN`، والاسم المعروف بيكمل لمرحلة البحث عن العنصر ويرد `INVENTORY_ITEM_NOT_FOUND`
   حتى لو الآيدي وهمي. فمسح أسماء "الاستلام" بآيدي وهمي بيفحص الـ enum من غير ما يلمس
   أي عنصر حقيقي.

    python -m inspection.probe_claim_surface G22
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"
FAKE = "00000000-0000-4000-8000-000000000000"

# اسماء العائلات اللي ممكن تغطي "سحب لوت الديك" بأي تسمية.
VERBS = ["claim", "collect", "harvest", "feed", "payout", "withdraw",
         "generate", "generator", "resource", "scrappy", "box", "nest",
         "rooster", "loot", "pickup", "receive", "deliver"]

# الكتابة المعروفة كلها تحت inventory، فالمسح بيت中心化 هناك (كل مسار = طلب GET آمن).
CONTAINERS = ["", "inventory/", "inventory/v1/", "generator/", "scrappy/", "bonuses/"]

# ضوابط بتثبّت إن الأوراكل شغالّة: مسارين كتابة معروفين + مسار وهمي.
CONTROLS = ["/v1/pioneer/inventory/upgrade", "/v1/pioneer/offers/accept",
            "/v1/pioneer/inventory/v1/mutate", "/v1/pioneer/zzz-not-a-route",
            "/v1/pioneer/inventory/v1/zzz"]

# عائلة أسماء الـ discriminator (كل الأشكال).
NOUNS = ["", "All", "Loot", "Rewards", "Box", "Items", "Generator", "Scrappy"]


def candidate_paths():
    out = []
    for verb in VERBS:
        for form in (verb, verb + "s", verb + "All"):
            for holder in CONTAINERS:
                out.append("/v1/pioneer/%s%s" % (holder, form))
    seen = dict.fromkeys(out)
    return [p for p in seen if "//" not in p.replace("://", "")]


def discriminator_names():
    out = []
    for verb in VERBS:
        for noun in NOUNS:
            snake = verb + ("_" + noun.lower() if noun else "")
            camel = verb + noun
            pascal = verb.capitalize() + noun
            out.extend([snake, camel, pascal, verb.upper(),
                        snake.upper(), "EInventoryMutation::" + pascal])
    return list(dict.fromkeys(out))


def reason(exc):
    text = str(exc)
    try:
        body = json.loads(text[text.index("{"):text.rindex("}") + 1])
        return str(body.get("reason") or body.get("detail") or "?")
    except Exception:
        return text[:90]


def get_probe(path, token):
    """405 = المسار موجود (POST-only). 404 = مش لاقي. أي حاجة تانية = مفاجأة مطبوعة."""
    try:
        pc.request(path, token=token, method="GET")
        return "200"
    except pc.PioneerError as exc:
        return reason(exc)
    except Exception as exc:  # noqa: BLE001
        return "ERR " + str(exc)[:70]


def mut_probe(name, token):
    muts = [{"discriminator": name, "instanceId": FAKE}]
    try:
        pc.post_json(pw._url(), {"mutations": muts, "requestId": ""}, token=token)
        return "200"
    except Exception as exc:  # noqa: BLE001
        return reason(exc)


def main():
    token = pc.account_token(ACCOUNT)
    if not token:
        print("مافيش توكن محفوظ لـ", ACCOUNT)
        return
    lines = []

    def say(text):
        print(text)
        lines.append(text)

    say("== الأساس: توكن %s | %s | %s ==" % (ACCOUNT, pc.time.strftime("%H:%M:%S"),
                                            pw._url()))
    say("\n== الضوابط (GET) ==")
    for path in CONTROLS:
        say("   %-42s -> %s" % (path, get_probe(path, token)))

    say("\n== مسح مسارات بالـ GET (%d مرشح) ==" % len(candidate_paths()))
    hits = []
    for path in candidate_paths():
        r = get_probe(path, token)
        if r not in ("404", "page not found") and "404" not in r:
            hits.append((path, r))
            say("   *** %-46s -> %s" % (path, r))
    say("   (المجموع: %d مسار مش 404 من %d)" % (len(hits), len(candidate_paths())))

    names = discriminator_names()
    say("\n== مسح discriminator على mutate (%d اسم، آيدي وهمي) ==" % len(names))
    found = []
    for name in names:
        r = mut_probe(name, token)
        if r != "UNKNOWN":
            found.append((name, r))
            say("   *** %-40s -> %s" % (name, r))
    say("   (المجموع: %d اسم مش UNKNOWN من %d)" % (len(found), len(names)))
    say("\n== ضوابط mutate ==")
    for name in ("update", "recycle", "split"):
        say("   %-12s -> %s" % (name, mut_probe(name, token)))

    out = r"C:\Users\Administrator\Desktop\rr\inspection\pf\claim_surface_%s.txt" % \
        time.strftime("%Y%m%d_%H%M")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\nالملف:", out)


if __name__ == "__main__":
    main()
