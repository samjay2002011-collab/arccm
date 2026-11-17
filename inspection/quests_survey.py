# -*- coding: utf-8 -*-
"""جرد `/v1/pioneer/quests` البحثي: كل الأعمدة الموجودة + أي مهمة اسمها له صلة بالديك.

ليه: البوابة بتكشف عن مسارين للكتابة (`inventory/v1/mutate` و`offers/accept`) والتوكن
بتاعنا بيقرا quests بجدارة. لو صندوق Scrappy متmodell كـ quest (objective بحالة
ومكافأة) فالقبض لازم يبقى عملية على نفس الـ instanceId ده — والجرد ده بيطلع الأسماء
والحقول الحقيقية بدل ما نخمن أسماء مسارات.

    python -m inspection.quests_survey G14
    python -m inspection.quests_survey G14 --kw scrappy,rooster,generator,feed,nest,collect
"""
import json
import re
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

DEFAULT_KW = ("scrappy", "rooster", "generator", "feed", "nest", "collect", "chicken",
              "bird", "forage", "resource", "stash", "workshop", "hideout")


def names_by_asset():
    names = pioneer_tree.asset_names()
    return {str(k): (v.get("display_name") or v.get("game_asset_name") or "")
            for k, v in names.items()}


def walk_keys(obj, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out[prefix + k] = out.get(prefix + k, 0) + 1
            walk_keys(v, prefix + k + ".", out)
    elif isinstance(obj, list):
        for v in obj[:200]:
            walk_keys(v, prefix, out)
    return out


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G14"
    kw = DEFAULT_KW
    for i, a in enumerate(sys.argv):
        if a == "--kw" and i + 1 < len(sys.argv):
            kw = tuple(x.strip().lower() for x in sys.argv[i + 1].split(",") if x.strip())
    token = pc.account_token(account)
    data = pc.request("/v1/pioneer/quests", token=token) or {}
    quests = data.get("quests") or []
    names = names_by_asset()
    print("== %s | quests=%d ==" % (account, len(quests)))
    print("الحقول الموجودة:")
    for key, count in sorted(walk_keys(quests).items()):
        print("   %-46s %d" % (key, count))
    print("\nأمثلة قيمة الحقول من أول مهمة:")
    print(json.dumps(quests[0], ensure_ascii=False, indent=1)[:1200] if quests else " none")

    print("\n== مهام بأسماء فيها الكلمات المفتاحية (%d) ==" % len(kw))
    pat = re.compile("|".join(re.escape(k) for k in kw), re.I)
    hits = []
    for q in quests:
        asset = str(q.get("gameAssetId") or "")
        label = names.get(asset) or ""
        blob = json.dumps(q, ensure_ascii=False)
        if pat.search(label) or pat.search(blob):
            hits.append((label, q))
    for label, q in hits[:12]:
        print("\n  [%s] %s" % (label or "؟", json.dumps(q, ensure_ascii=False)[:700]))
    if not hits:
        print("  مفيش ولا ضربة — يبقى الصندوق مش مهمة في المسار ده.")


if __name__ == "__main__":
    main()
