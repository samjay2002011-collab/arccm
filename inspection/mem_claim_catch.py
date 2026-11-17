# -*- coding: utf-8 -*-
"""لاقط طلب الـ CLAIM بتاع Scrappy من ذاكرة اللعبة الحية (قراءة فقط).

الفكرة: اللعبة نفسها بتكلّم نفس البوابة وبنفس توكن embark-pioneer، فالطلب اللي
بتبعته عند الضغط على CLAIM موجود حرفيًا في ذاكرتها (سطر الطلب + الهيدرات + الجسم
JSON) لثواني بعد العملية. السبق اللي فات مسكنا مسار التصنيع بنفس الطريقة.

بنلمس حاجة محددة مش كلمات عامة: سطور HTTP (`POST /v1`، `GET /v1`، `Host:`) ومسار
البوابة وحقول الأجسام المعروفة (`instanceId` / `mutations` / `offerId` /
`requestId`) + ids العقد الحقيقية للحساب اللي هندوس فيه CLAIM (اللي داخل الجسم).
وبنقرا شجرة البوابة قبل وبعد عشان نعرف الطلب اللي مسكناه هو اللي نفّذ فعلًا.

    python -m inspection.mem_claim_catch --account G14 --seconds 90
    python -m inspection.mem_claim_catch --account G14 --press    # يستنى ثم يمسح

قراءة ذاكرة بـ PROCESS_VM_READ بس — مفيش كتابة في اللعبة ولا طلبات على البوابة.
"""
import argparse
import ctypes
import json
import os
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt  # noqa: E402
from backend import pioneer_client as pc, pioneer_tree  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pf")
CHUNK = 4 << 20
OVERLAP = 4096
CONTEXT = 1100
HEAD = 260

# سطور/حقول الطلب نفسها — العامة منها (POST/GET) هي اللي بتكشف المسار الجديد.
NEEDLES = ("POST /v1", "PUT /v1", "PATCH /v1", "GET /v1", "es-pio.net", "pioneer/inventory",
           "pioneer/quests", "pioneer/offers", "pioneer/bonuses",
           '"discriminator"', '"mutations"', '"instanceId"', '"requestId"', '"offerId"',
           '"itemsToConsume"', "x-embark-manifest-id",
           # أسماء حيّة اتلمست من ذاكرة اللعبة نفسها (جرد 31 أكتوبر)
           "ApiGateway", "Scrappy", "ScrapysBox", "BoxClaim", "FeedScrappy",
           "ResourceGenerator", "ClaimScrappy", "ScrappyLoot")
# كلمات دالة على الصندوق نفسه (بنفلترها لاحقًا بالسياق المفيد)
BOX_WORDS = ("scrappy", "Scrappy", "ResourceGenerator", "resourceGenerator", "generator",
             "claim", "Claim", "collect", "Collect", "feed", "Feed", "nest", "Nest",
             "haul", "Haul", "reward", "Reward", "payout")
PRINTABLE = re.compile(rb"[^\x20-\x7e]+")
GEN_RE = re.compile(r"^DA_Item_ResourceGenerator_", re.I)


def clean(b):
    return PRINTABLE.sub(lambda m: b" " if len(m.group()) == 1 else b" | ",
                         b).decode("ascii", "ignore").strip(" |")


def find_in(window, needle):
    out, start = [], 0
    for form in (needle.encode(), needle.encode("utf-16-le")):
        while True:
            i = window.find(form, start)
            if i < 0:
                break
            out.append(i)
            start = i + 1
    return out


def generator_ids(account):
    """ids عقدة الديك + الحاوية اللي فوقها — دي اللي هتكون داخل جسم الطلب."""
    data = pc.fetch_inventory_for(account) or {}
    tree = pioneer_tree.Tree(data.get("items") or [])
    names = pioneer_tree.asset_names()
    ids = []
    for iid, node in tree.by_id.items():
        asset = str(node.get("gameAssetId") or "")
        if GEN_RE.match((names.get(asset) or {}).get("game_asset_name") or ""):
            ids.append(str(iid))
            parent = tree.parent.get(str(iid))
            if parent:
                ids.append(str(parent))
    return ids, tree


def amounts(tree):
    return {str(i): int(n.get("amount") or 0) for i, n in tree.by_id.items()}


def baseline(accounts):
    """ids العقد + كمية كل خانة قبل الضغط، لكل حساب مطلوب."""
    out = {}
    for name in accounts:
        try:
            ids, tree = generator_ids(name)
        except Exception as exc:
            print("  %s: فشل القراءة (%s)" % (name, str(exc)[:90]))
            continue
        out[name] = {"ids": ids, "amounts": amounts(tree)}
        print("  %s | عقدة الديك: %s" % (name, ids or "مفيش"))
    return out


def sweep(pids, needles, hits, seen):
    new = 0
    for pid in pids:
        handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                         False, pid)
        if not handle:
            print("  pid %s: OpenProcess فشل" % pid)
            continue
        buf = ctypes.create_string_buffer(CHUNK)
        done = ctypes.c_size_t(0)
        total = 0
        try:
            for base, size in mt._iter_readable(handle):
                pos, tail = 0, b""
                while pos < size:
                    want = min(CHUNK, size - pos)
                    ok = mt.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos),
                                                      buf, want, ctypes.byref(done))
                    got = done.value if ok else 0
                    if not got:
                        pos += want
                        continue
                    window = tail + buf.raw[:got]
                    total += got
                    for needle in needles:
                        for i in find_in(window, needle):
                            frag = clean(window[max(0, i - HEAD):i + CONTEXT])
                            key = frag[:200]
                            if key in seen:
                                continue
                            seen.add(key)
                            hits.append((needle, frag))
                            new += 1
                    tail = window[-OVERLAP:]
                    pos += want
        finally:
            mt.KERNEL32.CloseHandle(handle)
        print("  pid %s: اتقرا %s MB | ضربات جديدة %d" %
              (pid, format(total // 1024 // 1024, ","), new))
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="G14", help="اسم أو أكثر مفصولين بفاصلة")
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--press", action="store_true", help="يستنى لحد ما اللعبة تظهر ثم يمسح")
    ap.add_argument("--extra", default="", help="كلمة إضافية للتلمس (لو عارفها)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(OUT_DIR, "mem_claim_catch_%s.txt" % stamp)

    accounts = [a.strip() for a in args.account.split(",") if a.strip()]
    print("== الأساس قبل الضغط ==")
    base = baseline(accounts)
    needles = list(NEEDLES)
    for info in base.values():
        needles += info["ids"]
    if args.extra:
        needles += [x.strip() for x in args.extra.split(",") if x.strip()]
    needles = [n for n in dict.fromkeys(needles) if n]

    pids = mt.find_pids()
    if not pids and args.press:
        print("في انتظار PioneerGame.exe…")
        deadline = time.time() + 900
        while not pids and time.time() < deadline:
            time.sleep(3)
            pids = mt.find_pids()
    if not pids:
        print("اللعبة مقفولة — اللاقط محتاجها شغالة.")
        return

    print("pid:", pids, "| مدة المسح: %.0f ث — دوس CLAIM جوه اللعبة دلوقتي" % args.seconds)
    hits, seen = [], set()
    deadline = time.time() + args.seconds
    while time.time() < deadline:
        sweep(pids, needles, hits, seen)
        time.sleep(2)

    after_grew = {}
    for name, info in base.items():
        try:
            after = amounts(pioneer_tree.Tree((pc.fetch_inventory_for(name) or {})
                                              .get("items") or []))
        except Exception as exc:
            print("  %s: قراءة ما بعد الضغط فشل (%s)" % (name, str(exc)[:80]))
            continue
        grew = {k: after[k] - info["amounts"].get(k, 0) for k in after
                if k in info["amounts"] and after[k] > info["amounts"].get(k, 0)}
        after_grew[name] = grew
        print("\n== أثر %s على الشجرة الرسمية: %d خانة زادت، مجموع +%d ==" %
              (name, len(grew), sum(grew.values()) or 0))

    useful = [h for h in hits if ("/v1/" in h[1] or "{" in h[1] or "Host:" in h[1]) and len(h[1]) > 60]
    boxy = [h for h in useful if any(w.lower() in h[1].lower() for w in BOX_WORDS)]
    # رموز عميل ApiGateway/أسماء عمليات الديك — بتوجّهنا لإسم العملية حتى لو سطر الطلب طار
    symbols = [h for h in hits if any(w in h[1] for w in
                                      ("ApiGateway", "Scrappy", "ResourceGenerator", "Claim"))]
    with open(out_file, "w", encoding="utf-8") as fh:
        fh.write("accounts=%s\n" % json.dumps(
            {k: {"ids": v["ids"], "grew": after_grew.get(k, {})} for k, v in base.items()},
            ensure_ascii=False))
        fh.write("\n\n===== رموز/أسماء عمليات (%d) =====\n" % len(symbols))
        for needle, frag in symbols:
            fh.write("\n### [%s]\n%s\n" % (needle, frag))
        fh.write("\n\n===== مفيد (%d) =====\n" % len(useful))
        for needle, frag in useful:
            fh.write("\n--- [%s]\n%s\n" % (needle, frag))
        fh.write("\n\n===== فيها كلمة صندوق (%d) =====\n" % len(boxy))
        for needle, frag in boxy:
            fh.write("\n*** [%s]\n%s\n" % (needle, frag))
    print("الملف الكامل:", out_file)
    print("\n== المشتبه الأقوى (%d) ==" % len(boxy))
    for needle, frag in boxy[:12]:
        print("\n*** [%s]\n%s" % (needle, frag[:1400]))


if __name__ == "__main__":
    main()
