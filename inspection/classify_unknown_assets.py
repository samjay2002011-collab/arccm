"""فرز العناصر اللي مالهاش اسم: «قطعة باتش تتسم» أو «شبح» مفيش له اسم في اللعبة نفسها.

قراءة بس: `GET /v1/pioneer/inventory` لكل حساب بتوكنه، وبنمرّره لـ build_payload
من غير ما نسيبه يجيب الشجرة بنفسه (الدالة دي لوحدها ممكن تعمل relink للمعدات).

المقياس (موثق في ميموري المشروع arc-raiders-asset-index):
  - الشبح: أيدي بيعدي على أكتر من حساب بنفس الكميات، و`updatedAt` قديم، وعائم في
    الأوفر ستاش من غير أب. اللعبة نفسها بتعرضه «ITEM <رقم>» من غير أيقونة.
  - القابل للتسمية: بلاطة ظاهرة في ستاش/شنطة/تجهيز، فاللاعب بيشوف كارتها في اللعبة
    و يقدر يسمّيها من كليك يمين (NAME NEW ITEM).
"""
import csv
import sys
import time
from collections import defaultdict

from backend import pioneer_client, pioneer_sync, pioneer_tree, store

PATCH_DATE = time.mktime(time.strptime("2026-10-27", "%Y-%m-%d"))


def named_ids():
    ids = set()
    for path in (pioneer_sync.ASSET_INDEX_FILE, pioneer_tree.ASSET_LOCAL_FILE):
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if (row.get("display_name") or "").strip():
                        ids.add(row["game_asset_id"])
        except OSError:
            pass
    return ids


def slots_of(payload):
    for key in ("stash", "overflow", "backpack"):
        for slot in payload.get(key) or []:
            yield key, slot
    for cname, slots in (payload.get("containers") or {}).items():
        for slot in slots or []:
            yield "loadout:" + cname, slot


def main():
    conn = store.db()
    accounts = [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]
    named = named_ids()
    info = defaultdict(lambda: {"places": set(), "qty": 0, "tiles": 0, "kids": 0,
                                "updated": [], "accounts": set()})

    for account in accounts:
        try:
            data = pioneer_client.fetch_inventory_for(account)
            payload = pioneer_sync.build_payload(conn, account, data=data)
        except Exception as exc:
            print("!! %s: %s" % (account, str(exc)[:90]))
            continue
        tree = pioneer_tree.Tree(data.get("items") or [])
        for where, slot in slots_of(payload):
            item = slot.get("item") or {}
            aid = str(item.get("asset_id") or "")
            if not aid or aid in named:
                continue
            iid = str(item.get("instanceId") or "")
            rec = info[aid]
            rec["places"].add(where)
            rec["tiles"] += 1
            rec["qty"] += int(item.get("quantity") or 1)
            rec["kids"] = len(tree.children(iid))
            stamp = tree.updated_at(iid) / 1e9  # البوابة بتدي النانو-ثانية
            if stamp:
                rec["updated"].append(stamp)
            rec["accounts"].add(account)

    ghosts, nameable = [], []
    for aid, rec in info.items():
        newest = max(rec["updated"]) if rec["updated"] else 0
        rec["visible"] = sorted(p for p in rec["places"] if not p.startswith("overflow"))
        shared = len(rec["accounts"]) > 1
        stale = bool(newest) and newest < PATCH_DATE
        if rec["visible"] or not (shared or stale):
            nameable.append((aid, rec))
        else:
            ghosts.append((aid, rec))

    def line(aid, rec):
        seen = time.strftime("%Y-%m-%d", time.localtime(max(rec["updated"]))) if rec["updated"] else "؟"
        vis = "/".join(rec.get("visible") or [])
        return "%12s | %d حساب | %d بلاطة | qty %-5d | أبناء %-2d | %s | %s" % (
            aid, len(rec["accounts"]), rec["tiles"], rec["qty"], rec["kids"],
            (("ظاهرة: " + vis) if vis else "أوفر ستاش بس")[:40], seen)

    print("=== قابل للتسمية (بلاطة شايفها في اللعبة: كليك يمين ← NAME NEW ITEM) ===")
    for aid, rec in sorted(nameable, key=lambda r: (-len(r[1]["accounts"]), -r[1]["tiles"])):
        print(line(aid, rec))
    print()
    print("=== شبح (مش في جدول أسماء اللعبة نفسها — مفيش اسم يتكتب) ===")
    for aid, rec in sorted(ghosts, key=lambda r: (-len(r[1]["accounts"]), -r[1]["qty"]))[:15]:
        print(line(aid, rec))
    print("... إجمالي الأشباح: %d أيدي | %d بلاطة | %d وحدة" % (
        len(ghosts), sum(r["tiles"] for _, r in ghosts), sum(r["qty"] for _, r in ghosts)))
    print()
    print("ملخص: مجهول %d = قابل للتسمية %d + شبح %d" % (len(info), len(nameable), len(ghosts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
