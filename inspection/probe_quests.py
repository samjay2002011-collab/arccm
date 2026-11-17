"""قراءة كاملة لـ /v1/pioneer/quests: هل فيها أي إشارة لبلوبرنت أو مستوى محطة؟"""
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
from backend import pioneer_client as pc  # noqa: E402

account = sys.argv[1] if len(sys.argv) > 1 else "G22"
data = pc.request("/v1/pioneer/quests", token=pc.account_token(account))
quests = data.get("quests") or []
print("account:", account, "| quests:", len(quests), "| top keys:", sorted(data))
print("item keys:", sorted({k for q in quests for k in q}))
print("states:", Counter(str(q.get("state")) for q in quests))
print("with objectives:", sum(1 for q in quests if q.get("objectives")),
      "| with edges:", sum(1 for q in quests if q.get("edges")))
print("distinct gameAssetId:", len({q.get("gameAssetId") for q in quests}))
print("\nعيينة 6:")
print(json.dumps(quests[:6], indent=1, ensure_ascii=False)[:1200])
raw = json.dumps(data, ensure_ascii=False).lower()
for word in ("blueprint", "craft", "workshop", "bench", "station", "unlock", "level", "learn"):
    print("كلمة %r: %s" % (word, raw.count(word)))
