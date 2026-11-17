# -*- coding: utf-8 -*-
"""بيجرب أسماء العمليات اللي اللقطة نفسها بتستخدمها كـ discriminators على mutate.

ليه: كل المسوحات السابقة جرّبت أسماء مخترعة (split/combine/merge/claim/collect…).
دلوقتي إحنا عندنا الأسماء الحقيقية من جدول أسماء UE في ذاكرة اللعبة:
  EPioneerOnlineOperationType + الحقول: MoveItem / MoveItemAmount / SetParents /
  AcceptOffer / Repair / Scrap / Recycle / Upgrade  (و enum تاني: EPioneerOnlineMutateInventoryMutationType::Update/Repair/…)
مفيش واحدة من دول اتجربت على البوابة من قبل.

الأوراك بآيدي وهمي = صفر أثر:
  INVENTORY_ITEM_NOT_FOUND / ZERO_AMOUNT → الاسم في الـenum والسيرفر اشتغل بيه (فوز)
  UNKNOWN                                  → الاسم مش في الـenum بتاع التوكن ده

    python -m inspection.probe_game_ops G22
    python -m inspection.probe_game_ops G22 MoveItem,SetParents,claim_scrappy
"""
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc, pioneer_write as pw  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G22"
FAKE = "00000000-0000-4000-8000-000000000000"

GAME_OPS = ["MoveItem", "MoveItemAmount", "SetParents", "AcceptOffer", "Upgrade",
            "Repair", "Scrap", "Recycle", "ClaimScrappy", "CollectScrappy",
            "ScrappyClaim", "FeedScrappy", "Donate", "Commit", "CommitItems",
            "Collect", "Claim", "Harvest", "moveItem", "move_item", "move_item_amount",
            "setParents", "set_parents", "acceptOffer", "claimScrappy",
            "collectScrappy", "collectResources", "claimResources", "feedScrappy",
            "donate", "commit", "collect", "claim", "harvest", "unstack", "reparent",
            "MOVE_ITEM", "SET_PARENTS", "CLAIM", "COLLECT", "SCRAPPY_CLAIM",
            "EInventoryMutation::MoveItem", "EInventoryMutation::SetParents",
            "EInventoryMutation::ClaimScrappy"]

ITEM_FIELDS = ["instanceId", "instance_id", "targetInstanceId", "targetWrapperId",
               "sourceWrapperId", "assetId", "amount", "slots", "parentId", "etag"]


def ask(token, name, extra=None):
    mut = {"discriminator": name, "instanceId": FAKE}
    mut.update(extra or {})
    try:
        pc.post_json(pw._url(), {"mutations": [mut], "requestId": ""}, token=token)
        return "200"
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        for code in ("INVENTORY_ITEM_NOT_FOUND", "INVENTORY_ITEM_ZERO_AMOUNT",
                     "INVALID_ARGUMENT", "UNKNOWN", "FAILED_PRECONDITION",
                     "RBAC", "FORBIDDEN"):
            if code in text:
                return code
        return text[text.find(": ") + 2:][:90]


def main():
    names = GAME_OPS
    if len(sys.argv) > 2:
        names = [n.strip() for n in sys.argv[2].split(",") if n.strip()]
    token = pc.account_token(ACCOUNT)
    if not token:
        print("مافيش توكن لـ", ACCOUNT)
        return
    print("== الضوابط ==")
    for name in ("update", "recycle", "scrap", "repair", "zzznotathing"):
        print("   %-14s -> %s" % (name, ask(token, name)))
    print("\n== أسماء اللعبة (%d) ==" % len(names))
    wins = []
    for name in names:
        r = ask(token, name)
        flag = "   " if r == "UNKNOWN" else " ***"
        print("%s %-22s -> %s" % (flag, name, r))
        if r != "UNKNOWN":
            wins.append((name, r))
    print("\n== اللي مش UNKNOWN (%d) ==" % len(wins))
    for name, r in wins:
        print("   %-22s -> %s" % (name, r))
        for extra in ({"amount": 1}, {"targetWrapperId": FAKE, "amount": 1},
                      {"parentId": FAKE}, {"slots": [""]}):
            print("       +%-34s -> %s" % (list(extra)[0], ask(token, name, extra)))


if __name__ == "__main__":
    main()
