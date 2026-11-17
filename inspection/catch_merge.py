# -*- coding: utf-8 -*-
"""اللاقط الشامل: يستنى اللعبة تفتح، يسلّح الآيديات الحقيقية لستاكات مختارة، ويلمس
جسم الطلب اللي اللعبة بتبعتُه وقت ما تعمل دمج/تقسيم جوه اللعبة — ثم يقارن الشجرة.

ليه الشغل ده: البوابة بتدي توكن الرفيق `update/recycle/scrap/repair` بس؛ `split`
و`combine` و`stack_merge` بتردها `400 UNKNOWN` لنفس التوكن (مقيس، والكنترول
`update` بيرد NOT_FOUND في نفس اللحظة). الهيدرات اللي اللعبة تبعتها اتجرّبت واحد
واحد وكومبو (`inspection/probe_split_headers.py`) وما فتحتشي حاجة. فالباقي الوحيد
هو شكل الجسم نفسه — اللعبة بتبعت حاجة إحنا مش بنبعتها.

السنّارة هنا أدق من `mem_body_catch`: بدل كلمة `discriminator` العامة (الأنريل
بيملها في أسماء أصول)، بنلمش على **آيديات الستاكات الحقيقية** اللي اخترناها من
الشجرة الحيّة + آيديات الخانات اللي حواليها — جسم الطلب لازم يحتويها حرفياً.
بنسلّم إن اللعبة اتعمل عليها دمج/تقسيم، وبعدها بنقرا الشجرة تاني وبنطبع الفرق
(اللي اتحذف/اللي اتخلق/الكميات) عشان نعرف الضربة اللي في الذاكرة مطابقة لأي عملية.

قراءة فقط: PROCESS_VM_READ من غير أي كتابة في اللعبة، ولا طلبات شبكة غير GET على
شجرة الحساب اللي إحنا مسجلينه.

    python -m inspection.catch_merge G18
    python -m inspection.catch_merge G18 --asset "gun parts" --passes 4
"""
import ctypes
import re
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from agent import memtoken as mt                       # noqa: E402
from backend import items_db, pioneer_client as pc, pioneer_tree as pt  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "G18"
CHUNK = 4 << 20
OVERLAP = 2048
CONTEXT = 1400
PRINTABLE = re.compile(rb"[^\x20-\x7e]+")
OUT = r"C:\Users\Administrator\Desktop\rr\inspection\pf\catch_merge_%s.txt" % ACCOUNT.lower()


def log(msg):
    print(msg, flush=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(msg.rstrip() + "\n")


def clean(b):
    return PRINTABLE.sub(lambda m: b" " if len(m.group()) == 1 else b" | ",
                         b).decode("ascii", "ignore").strip(" |")


def tree():
    return pt.Tree((pc.fetch_inventory_for(ACCOUNT) or {}).get("items") or [])


def stacks(t, want):
    """أكوام العنصر المطلوب: (آيدي, كمية, الأب). `want` substring على الاسم.

    بنفلتر بالكتالوج المحلي عشان الخانات والحاويات (اسمها "Item Slot" مثلاً) ما
    تدخلش — هنّا نرصد عناصر حقيقية بس.
    """
    out = []
    for entry in t.items:
        iid = str(entry["instanceId"])
        name = (t.name_of(iid) or "").lower()
        if want and want.lower() not in name:
            continue
        if not items_db.find(asset_id=entry.get("gameAssetId")):
            continue
        try:
            amount = int(entry.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            continue
        if t.kids.get(iid):          # حاوية/خانة مش عنصر — بنرصد العناصر الورقة بس
            continue
        out.append((iid, amount, str(t.parent.get(iid) or "")))
    out.sort(key=lambda r: (r[2], -r[1]))
    return out


def pick_target(t, rows):
    """أحسن عنصر نرصد عليه الدمج: أكتر ستاكات في نفس الأب (يقدر يسحب واحدة على التانية)."""
    groups = {}
    for iid, a, p in rows:
        groups.setdefault(t.name_of(iid) or "?", []).append((iid, a, p))
    scored = []
    for name, grp in groups.items():
        per_cell = {}
        for iid, a, p in grp:
            per_cell.setdefault(p, []).append(a)
        same = max((g for g in per_cell.values() if len(g) >= 2), key=len, default=[])
        scored.append((len(same), len(grp), sum(a for _, a, _ in grp), name, grp))
    scored.sort(key=lambda s: (s[0], s[1], s[2]), reverse=True)
    return scored, groups


def snap(t, rows):
    return {iid: (a, p) for iid, a, p in rows}


def diff(before, after, t):
    """الفرق بين لقطة قبل العملية وبعدها — ده اللي يربط جسم الطلب بالحدث."""
    gone = [i for i in before if i not in after]
    new = [i for i in after if i not in before]
    moved = [(i, before[i], after[i]) for i in after
             if i in before and (before[i][0] != after[i][0] or before[i][1] != after[i][1])]
    sb, sa = sum(v[0] for v in before.values()), sum(v[0] for v in after.values())
    for i in gone:
        log("  اتحذف : %s (%s×%s)" % (i, t.name_of(i), before[i][0]))
    for i in new:
        log("  اتخلق: %s (%s×%s)" % (i, t.name_of(i), after[i][0]))
    for i, b, a in moved:
        log("  اتغير: %s %s×%s -> %s×%s | أب %s -> %s"
            % (i, t.name_of(i), b[0], t.name_of(i), a[0], b[1] or "overflow", a[1] or "overflow"))
    log("  المجموع: %d -> %d | عدد الأكوام: %d -> %d" % (sb, sa, len(before), len(after)))


UUID_RE = re.compile(rb"[0-9a-fA-F][0-9a-fA-F\-]{30,40}[0-9a-fA-F]")


def id_hits(window, needles):
    """آيديات المرصودة اللي موجودة في النافذة — بمسح واحد بدل بحث لكل آيدي.

    بنمشّي على الـASCII والـUTF‑16 (الاتنين بيطلعو في أنريل)، وبنقبل الآيدي لو طلع
    ككل أو جوه شط أطول منه.
    """
    out = []
    for view in (window, window[0::2], window[1::2]):
        for m in UUID_RE.finditer(view):
            tok = m.group().lower().decode("ascii", "ignore")
            cands = [tok] if len(tok) <= 36 else [tok[i:i + 36] for i in range(len(tok) - 35)]
            for c in cands:
                if c in needles:
                    out.append((m.start(), c))
    return out


def pass_once(needles, found):
    pids = mt.find_pids()
    if not pids:
        log("  اللعبة اتقفلت وسط المسح.")
        return 0
    nset = {n.lower(): n for n in needles}
    total = 0
    for pid in pids:
        handle = mt.KERNEL32.OpenProcess(mt.PROCESS_VM_READ | mt.PROCESS_QUERY_INFORMATION,
                                         False, pid)
        if not handle:
            log("  pid %s: OpenProcess فشل" % pid)
            continue
        buf = ctypes.create_string_buffer(CHUNK)
        done = ctypes.c_size_t(0)
        read_bytes = 0
        try:
            for base, size in mt._iter_readable(handle):
                pos, tail = 0, b""
                while pos < size:
                    want_len = min(CHUNK, size - pos)
                    ok = mt.KERNEL32.ReadProcessMemory(handle, ctypes.c_void_p(base + pos),
                                                       buf, want_len, ctypes.byref(done))
                    got = done.value if ok else 0
                    if not got:
                        pos += want_len
                        continue
                    window = tail + buf.raw[:got]
                    read_bytes += got
                    for at, tok in id_hits(window, nset):
                        frag = clean(window[max(0, at - 300):at + CONTEXT])
                        key = (tok, frag[:180])
                        if key in found:
                            continue
                        found.add(key)
                        total += 1
                        log("\n--- ضربة [%s] ---\n%s" % (nset[tok], frag[:1600]))
                    tail = window[-OVERLAP:]
                    pos += want_len
        finally:
            mt.KERNEL32.CloseHandle(handle)
            log("  pid %s: اتقرا %s MB | ضربات جديدة في الباس ده: %d"
                % (pid, format(read_bytes // 1024 // 1024, ","), total))
    return total


def wait_game(minutes=240):
    deadline = time.time() + minutes * 60
    while not mt.find_pids():
        if time.time() > deadline:
            return False
        log("  في انتظار PioneerGame.exe… (%d ث باقي)" % max(0, int(deadline - time.time())))
        time.sleep(10)
    return True


def main():
    want = ""
    if "--asset" in sys.argv:
        want = sys.argv[sys.argv.index("--asset") + 1]
    passes = int(sys.argv[sys.argv.index("--passes") + 1]) if "--passes" in sys.argv else 3
    log("== لاقط جسم الدمج/التقسيم | الحساب %s ==" % ACCOUNT)
    if not wait_game():
        log("اللعبة مفتحتش — وقف.")
        return
    log("اللعبة شغال: %s" % mt.find_pids())
    time.sleep(12)                      # نستنى الواجهة تستقر
    t = tree()
    rows = stacks(t, want)
    if not rows:
        log("مافيش أكوام طابقت %r — جرّب --asset \"bandage\"." % want)
        return
    scored, groups = pick_target(t, rows)
    if not want:
        log("أفضل 5 أهداف للدمج (ستاكات في نفس الحاوية):")
        for same, n, total, name, _ in scored[:5]:
            log("   %-28s %d ستاك | %d في نفس الأب | مجموع %d" % (name[:28], n, same, total))
    n_same, n_stacks, total, name, grp = scored[0]
    log("\nالعنصر المرصود: %s | %d ستاك | المجموع %d" % (name, n_stacks, total))
    for iid, a, p in grp[:24]:
        log("   %s ×%-4s أب=%s" % (iid, a, p or "overflow"))
    before = snap(t, grp)
    cell_ids = {p for _, _, p in grp if p}
    parents = [str(t.parent.get(c) or "") for c in cell_ids]
    needles = [i for i in {iid for iid, _, _ in grp} | cell_ids | {p for p in parents if p} if i]
    log("مسّلّح %s آيدي (عناصر + خانات + حاويات)." % len(needles))
    log("\n>> اعمل الدمج/التقسيم جوه اللعبة دلوقتي على العنصر ده، وسيب السكربت يشتغل.")
    found = set()
    for n in range(1, passes + 1):
        log("\n== باس %d/%d ==" % (n, passes))
        pass_once(needles, found)
        t2 = tree()
        after_rows = stacks(t2, name)
        after = snap(t2, after_rows)
        if after != before:
            log("\n== الشجرة اتغيرت (اللي حصل فعلاً) ==")
            diff(before, after, t2)
            before = after
            extra = {i for i, _, _ in after_rows} | {p for _, _, p in after_rows if p}
            grown = extra - set(needles)
            needles = list(set(needles) | extra)
            log("  زوّدنا %s آيدي جديد للسنّارة." % len(grown))
        else:
            log("  مافيش تغيير في الشجرة لسه.")
        if n < passes:
            time.sleep(5)
    log("\nخلصنا. الضربات كلها في: %s" % OUT)
    log("عدد الضربات المجموعة: %d" % len(found))
    log("لو طلع جسم فيه discriminator، ابعتهولي/شوف الملف — بنعيد نفس الشكل بتوكن الرفيق.")


if __name__ == "__main__":
    main()
