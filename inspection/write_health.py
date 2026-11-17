"""فحص صحة الكتابة على بوابة بايونير — من غير ما تحرّك أي حاجة.

  python inspection/write_health.py [--account G14]

وبيبعت أمر setParents على مسار batch-operation يحط قطعة تحت أبوها اللي هي تحتو
بالأصل، فمافيش أي عنصر اتغير حتى لو الطلب اتقبل. لو البوابة ردّت 412
FAILED_PRECONDITION يبقى المانيفست قديم (غالبًا اللعبة عملت ابديت) — القراءة
بتفضل شغالة والكتابة بس تموت، والحل:

  python inspection/pioneer_manifest.py --refresh   (من غير أي قراءة لذاكرة اللعبة)
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import config, pioneer_client as pc, pioneer_tree, pioneer_write as pw  # noqa: E402

URL = pc.BASE + pw.BATCH_PATH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="")
    args = ap.parse_args()

    with sqlite3.connect(config.DB_FILE) as db:
        accounts = [r[0] for r in db.execute(
            "SELECT name FROM accounts WHERE token IS NOT NULL AND token <> '' "
            "ORDER BY is_active DESC, name")]
    if not accounts:
        print("مفيش حساب بتوكن محفوظ.")
        return 1
    account = args.account or (accounts[0] if accounts else "")
    token = pc.account_token(account)
    saved = pc._read_json(pc.MANIFEST_FILE) or {}
    age_min = (time.time() - int(saved.get("updated_at") or 0)) / 60
    print("الحساب: %s | المانيفست: %s (بناء %s) عمره %.0f دقيقة"
          % (account, saved.get("manifest_id"), saved.get("build"), age_min))

    tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    print("القراءة: ✓ %d عنصر" % len(tree.by_id))
    newest = max((float(it.get("updatedAt") or 0) / 1e9 for it in tree.by_id.values()), default=0)
    if newest and time.time() - newest < 90:
        print("المخزن بيتحرّك دلوقتي (حد بيلعب) — الفحص هيتلخبط معاه، استنى شوية.")
        return 2

    cell = ""
    item = ""
    try:
        for wrapper in pioneer_tree.layout(tree)["stash"]["slots"]:
            kid = tree.first_child(wrapper)
            if kid:
                cell, item = wrapper, str(kid)
                break
    except pioneer_tree.TreeError as exc:
        print("شجرة المخزن مش.complete: %s" % exc.detail)
        return 1
    if not item:
        print("مفيش خانة مليانة في الستاش — الفحص محتاج قطعة واحدة على الأقل.")
        return 1

    # نفس أبو القطعة الحالي بالظبط = حالة نهائية ما بتغيّرش حاجة.
    body = {"operations": [{"discriminator": "setParents", "itemInstanceId": item,
                            "parentInstanceIds": [cell]}]}
    print("كتابة صفرية الأثر على خانة %s (%s)..." % (cell[:8], tree.label(cell)[:24]))
    try:
        pc.post_json(URL, body, token=token)
        print("✓ الكتابة مقبولة — النقل شغال.")
        return 0
    except pc.PioneerError as exc:
        text = str(exc)
        if "FAILED_PRECONDITION" in text:
            print("✗ البوابة بترفض أي كتابة ورفضت تتجدد لوحدها. جرب: "
                  "python inspection/pioneer_manifest.py --refresh")
        else:
            print("✗ %s" % text[:240])
        return 3
    except Exception as exc:  # noqa: BLE001
        print("✗ %s: %s" % (type(exc).__name__, str(exc)[:200]))
        return 4


if __name__ == "__main__":
    sys.exit(main())
