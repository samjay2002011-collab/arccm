"""خطة البروفيل بعد إصلاح المطابقة + الفضلة — على نسخة معزولة من الداتابيز.

    python inspection/exact_apply_probe.py

مفيش ولا كتابة على البوابة: بنقرا الخطة وبس، والداتابيز الحي ما بيتلمسش.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import config  # noqa: E402

LIVE = os.path.join(ROOT, "data", "rampart_local.db")
tmp = os.path.join(tempfile.mkdtemp(), "probe.db")
shutil.copyfile(LIVE, tmp)
config.DB_FILE = tmp
print("isolated db:", tmp, "| live db untouched:", LIVE)

from backend import loadouts, store  # noqa: E402

conn = store.db()
account = sys.argv[1] if len(sys.argv) > 1 else "G22"
loadout_id = int(sys.argv[2]) if len(sys.argv) > 2 else 68

out = loadouts.plan(conn, account, loadout_id)
print("\n=== plan for %s / loadout %s ===" % (account, loadout_id))
print("executable", out["executable"], "| already", out["already"])
for s in out["steps"]:
    print("  MOVE  %-18s -> %-14s[%s] from %-9s sub=%s" %
          (s["name"], s["slot"], s["slot_index"], s["from"], s["substituted"]))
for e in out["evict"]:
    print("  %-7s %-18s from %s" % ("EXTRA" if e.get("extra") else "EVICT", e["name"], e["slot"]))
for iid, g in (out["short"] or {}).items():
    print("  SHORT %-16s %s have %s need %s -> takes %s, still %s" %
          (g["name"], g["slot"], g["have"], g["need"],
           [(t["instance_id"][:8], t["amount"]) for t in g["takes"]], g["still"]))
print("  skipped", json.dumps(out["skipped"], ensure_ascii=False))

snap = loadouts.state(conn, account)
print("\n=== live board ===")
for key in loadouts.PREVIEW_ORDER:
    filled = [(sl["slot_index"], (sl.get("item") or {}).get("name"), (sl.get("item") or {}).get("qty"))
              for sl in snap["slots"].get(key) or [] if sl.get("item")]
    if filled:
        print("  %-16s %s" % (key, filled))

print("\n=== what the profile asks for ===")
rec = store.get_loadout(conn, loadout_id)
saved = json.loads(rec["data"] or "{}")
for key, rows in (saved.get("items") or {}).items():
    print("  %-16s %s" % (key, [(r.get("name"), r.get("qty")) for r in rows]))


def simulate(out):
    """يقلّب مكان القطع في نسخة من الـ snapshot — نفس اللي البوابة بتعمله،
    من غير ولا طلب شبكة: الخانات بتتقري من الشجرة، فالشجرة هي اللي بتتعدّل."""
    payload, fetched = store.read_snapshot(conn, account)
    tree = json.loads(json.dumps(payload or {}))
    db = sqlite3.connect(tmp)

    def slots(key):
        return (tree.get("backpack") if key == "backpack"
                else (tree.get("containers") or {}).get(key)) or []

    def detach(iid):
        for key in list(tree.get("containers") or {}) + ["backpack"]:
            for sl in slots(key):
                it = sl.get("item") or {}
                if str(it.get("instanceId") or it.get("id") or "") == str(iid):
                    sl["item"] = None
                    sl["is_empty"] = True

    for s in out["steps"]:
        detach(s["instance_id"])
        target = next((sl for sl in slots(s["slot"])
                       if str(sl.get("wrapper_id")) == str(s["target_wrapper_id"])), None)
        if target is not None:
            target["item"] = {"instanceId": s["instance_id"]}
            target["is_empty"] = False
    for e in out["evict"]:
        detach(e["instance_id"])
    for g in (out["short"] or {}).values():
        for t in g["takes"]:
            db.execute("UPDATE instances SET qty=qty-? WHERE instance_id=?", (t["amount"], t["instance_id"]))
        db.execute("UPDATE instances SET qty=qty+? WHERE instance_id=?",
                   (sum(int(t["amount"]) for t in g["takes"]), g["instance_id"]))
        db.execute("DELETE FROM instances WHERE qty<=0")
    db.commit()
    db.close()
    return tree, fetched


print("\n=== simulated APPLY rounds (isolated copy only) ===")
seed_payload, seed_fetched = store.read_snapshot(conn, account)
box = {"tree": seed_payload, "fetched": seed_fetched}
store.read_snapshot = lambda conn_, account_: (box["tree"], box["fetched"])
for rnd in range(4):
    cur = loadouts.plan(conn, account, loadout_id)
    todo = bool(cur["steps"] or cur["extras"] or loadouts._topup_gaps(cur["short"]))
    print("  round %d: %d move(s), %d extra, %d top-up(s), already=%s" %
          (rnd + 1, len(cur["steps"]), len(cur["extras"]), len(loadouts._topup_gaps(cur["short"])),
           cur["already"]))
    if not todo:
        break
    box["tree"], box["fetched"] = simulate(cur)
final = loadouts.plan(conn, account, loadout_id)
print("  settled: already=%s executable=%s steps=%d extras=%d short=%d" %
      (final["already"], final["executable"], len(final["steps"]), len(final["extras"]),
       len(final["short"] or {})))


def board(tree):
    rows = loadouts._instance_rows(conn, account)
    for key in loadouts.PREVIEW_ORDER:
        raw = (tree.get("backpack") if key == "backpack"
               else (tree.get("containers") or {}).get(key)) or []
        filled = []
        for sl in raw:
            it = sl.get("item") or {}
            iid = str(it.get("instanceId") or it.get("id") or "")
            if iid and rows.get(iid):
                filled.append((sl["slot_index"], rows[iid]["name"], rows[iid]["qty"]))
        if filled:
            print("  %-16s %s" % (key, filled))


print("\n=== board after the simulated apply ===")
board(box["tree"])

conn.close()


