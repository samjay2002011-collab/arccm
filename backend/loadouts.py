"""تجهيزات الحساب: خانات LOADOUT والشنط + حفظ/تحميل التجهيزات محلياً.

الحفظ بيأخذ الأماكن بالظبط (خانة لكل عنصر في التجهيز + الشنطة)، والتحميل بيرجع
خطة النقل لحد ما الكتابة تتفعّل. العنصر اللي مش موجود بيتتخطى واللي كان في
مكانه بيتنقل للستاش — يعني التحميل يحط الموجود وميقفش على الناقص (زي rampart).
التنفيذ كله في حركة بوابة واحدة من pioneer_write.move_plan، فكل خطوة رجوعها
متسجلة في out["undo"].

`preview()` طبقة فوق الخطة دي: بتدي شكل القالب خانة-بخانة (جاهز / ناقص) وعلى
كل ناقصة مساريها — تصنيع (وصفة + إثبات تفعيل + خامات الستاش) وشراء (عرض تاجر
+ رصيد) — كلهم محسوبين من داتا محلية وشجرة الحساب، من غير أي طلب شبكة.
"""
import json
import math
import time

from . import augments, catalog, items_db, knowledge, store, traders, workshop, writer

EQUIP_KEYS = ("augment", "shield", "gun_1", "gun_2", "quick_use", "safe_pocket", "augmented_slots")
# اللي بيتحفظ في التجهيز: خانات التجهيز + الشنطة بأماكنها بالظبط (زي rampart).
SAVE_KEYS = ("backpack",) + EQUIP_KEYS
ESSENTIAL = ("augment", "shield", "gun_1", "gun_2")
LABELS = {"augment": "AUGMENT", "shield": "SHIELD", "gun_1": "WEAPON 1", "gun_2": "WEAPON 2",
          "quick_use": "QUICK USE", "safe_pocket": "SAFE POCKET", "augmented_slots": "AUGMENTED",
          "backpack": "BACKPACK"}


def _instance_rows(conn, account):
    rows = conn.execute("SELECT * FROM instances WHERE account=?", (account,)).fetchall()
    return {r["instance_id"]: dict(r) for r in rows}


def _slot_list(payload, key, rows):
    raw = (payload.get(key) if key == "backpack" else (payload.get("containers") or {}).get(key)) or []
    out = []
    for slot in raw:
        item = slot.get("item") or {}
        iid = str(item.get("instanceId") or item.get("id") or "")
        row = rows.get(iid)
        out.append({
            "wrapper_id": str(slot.get("wrapper_id") or ""),
            "slot_index": slot.get("slot_index"),
            "item": row,
        })
    out.sort(key=lambda s: (s["slot_index"] if s["slot_index"] is not None else 9999))
    return out


def state(conn, account, saved=None):
    payload, fetched = store.read_snapshot(conn, account)
    payload = payload or {}
    rows = _instance_rows(conn, account)
    augment_asset = (payload.get("augment") or {}).get("asset_id")
    spec = augments.resolve(augment_asset)

    slots = {"backpack": _slot_list(payload, "backpack", rows)}
    for key in EQUIP_KEYS:
        slots[key] = _slot_list(payload, key, rows)

    spec_caps = augments.capacities(spec)
    # السعة = مواصفات الأوجمنت المجهز — البوابة مش بتبني ولا بتمسح حاويات الـ loadout
    # لما الأوجمنت يتبدل، فبنزود العدد بس لو خانة من الخانات الزايدة فيها عنصر.
    def _filled_extent(rows, fallback=0):
        return max([s["slot_index"] + 1 for s in rows if s.get("item")] or [fallback])

    capacity = {"backpack": max(spec_caps["backpack"], _filled_extent(slots["backpack"])),
                "quick_use": max(spec_caps["quick_use"], _filled_extent(slots["quick_use"])),
                "safe_pocket": max(spec_caps["safe_pocket"], _filled_extent(slots["safe_pocket"])),
                "augmented": max(spec_caps["augmented"], _filled_extent(slots["augmented_slots"]))}

    equipped_augment = None
    if augment_asset not in (None, ""):
        item = next((s["item"] for s in slots["augment"] if s["item"]), None)
        cached = catalog.arctracker_lookup(spec.get("name"))
        equipped_augment = {
            "asset_id": str(augment_asset),
            "name": (item or {}).get("name") or spec.get("name"),
            "image": (item or {}).get("image") or catalog.icon_of(cached) or spec.get("image") or "",
            "specs": spec_caps,
            "item": item,
        }

    required = sum(1 for key in ESSENTIAL if not any(s["item"] for s in slots[key]))
    return {
        "slots": slots,
        "capacity": capacity,
        "augment": equipped_augment,
        "base": augments.capacities(augments.resolve(None)),
        "required": required,
        "saved": store.list_loadouts(conn) if saved is None else saved,
        "snapshot_age_minutes": round((time.time() - (fetched or 0)) / 60, 1) if fetched else None,
    }


def capture(conn, account):
    snap = state(conn, account)
    items = {}
    for key in SAVE_KEYS:
        rows = []
        for slot in snap["slots"].get(key) or []:
            item = slot["item"]
            if not item:
                continue
            rows.append({
                "instance_id": item.get("instance_id"), "name": item.get("name"),
                "image": item.get("image") or "", "type": item.get("type") or "",
                "asset_id": item.get("asset_id"), "qty": item.get("qty") or 1,
                "slot_index": slot["slot_index"], "wrapper_id": slot["wrapper_id"],
            })
        if rows:
            items[key] = rows
    return {"account": account, "captured_at": time.time(),
            "augment": snap["augment"], "items": items}


def save(conn, account, name):
    name = (name or "").strip()[:64]
    if not name:
        raise ValueError("Loadout name is required.")
    data = capture(conn, account)
    loadout_id = store.save_loadout(conn, account, name, data)
    return {"id": loadout_id, "name": name, "count": sum(len(v) for v in data["items"].values())}, data


def _container_for(key):
    return "backpack" if key == "backpack" else "loadout"


def _slot_at(slots, wrapper_id, index):
    """الخانة دي في المخزن الحالي؟ بالـ wrapper الأول وبعدين برقمها."""
    wrapper_id = str(wrapper_id or "")
    if wrapper_id:
        found = next((s for s in slots if s["wrapper_id"] == wrapper_id), None)
        if found:
            return found
    return next((s for s in slots if s["slot_index"] == index), None)


def _cell_at(snap, key, item, pos):
    """الخانة اللي القطعة المحفوظة دي عايزاها في الحالة الحالية."""
    return _slot_at(snap["slots"].get(key) or [], item.get("wrapper_id"),
                    item.get("slot_index", pos))


def _stand_in(asset_id, by_id, claimed, blocked_containers=(), prefer=""):
    """أول نسخة من نفس النوع متاحة.

    الترتيب: اللي قاعدة في الخانة نفسها الأول (دي ما بتتحركش، وبتزوّد بس)،
    وبعدين الستاش، وبعدين الشنطة/الأوفر. لو القلبنا العكس بنسحب رصة من خانة
    فاضية ونحطها في الأوفر وبعدين نرجع نقلّب تاني — وده اللي كان بيفرّغ الشنطة.
    خانات التجهيز اللي مالهاش مكان في التجهيز المحفوظ محظورة، عشان التحميل
    ما يسرقش سلاحاً مجهزاً مش جزء من الخطة.
    """
    if not asset_id:
        return None
    blocked = set(blocked_containers)
    want = str(prefer or "")

    def rank(row):
        if str(row["instance_id"]) == want:
            return 0
        return 1 if str(row.get("container") or "") == "stash" else 2

    cands = [r for r in by_id.values()
             if str(r.get("asset_id") or "") == str(asset_id)
             and r["instance_id"] not in claimed
             and str(r.get("container") or "") not in blocked]
    return min(cands, key=rank) if cands else None


def plan(conn, account, loadout_id):
    """خطة تحميل قالب محفوظ على الحساب الحالي.

    القوالب مشتركة بين حساباته: القالب اللي اتحفظ من G14 بيتحمّل على حساب تاني عادي —
    الآيدز المتخزنة مالهاش وجود هنا فبتنزل لمطابقة النوع (`_stand_in`)، وده مقصود:
    هو عايز نفس التشكيل، مش نفس القطع بالذات."""
    rec = store.get_loadout(conn, loadout_id)
    if not rec:
        raise KeyError("unknown loadout")
    saved = json.loads(rec["data"] or "{}")
    snap = state(conn, account)
    by_id = _instance_rows(conn, account)
    claimed, taken, skipped = set(), {}, []
    saved_entries = [(key, item, pos)
                     for key, items in (saved.get("items") or {}).items() if key in SAVE_KEYS
                     for pos, item in enumerate(items)]
    protected = set(EQUIP_KEYS) - {key for key, _, _ in saved_entries}
    # مرة بمطابقة الآيد ومرة تانية بمطابقة النوع: اللي لسه ملوش بديل بيتتخطى.
    for ref in (0, 1):
        for key, item, pos in saved_entries:
            iid = str(item.get("instance_id") or "")
            if iid in taken:
                continue
            if ref == 0:
                row = by_id.get(iid)
            else:
                cell = _cell_at(snap, key, item, pos) or {}
                row = _stand_in(item.get("asset_id"), by_id, claimed, protected,
                                prefer=(cell.get("item") or {}).get("instance_id") or "")
            if row is None or row["instance_id"] in claimed:
                continue
            claimed.add(row["instance_id"])
            taken[iid] = (key, item, row, pos)
    for key, item, pos in saved_entries:
        if str(item.get("instance_id") or "") not in taken:
            skipped.append({"name": item.get("name") or "?", "slot": LABELS.get(key, key),
                            "reason": "missing", "saved_instance_id": str(item.get("instance_id") or "")})

    steps, evict = [], []
    in_place = {}
    for iid, (key, item, row, pos) in taken.items():
        slots = snap["slots"].get(key) or []
        label = item.get("name") or row.get("name") or iid
        target = _slot_at(slots, item.get("wrapper_id"), item.get("slot_index", pos))
        if target is None or not target.get("wrapper_id"):
            skipped.append({"name": label, "slot": LABELS.get(key, key), "reason": "no_slot",
                            "saved_instance_id": iid})
            continue
        occupant = target.get("item") or {}
        if occupant.get("instance_id") == row["instance_id"]:
            # القطعة في مكانها بالظبط: مفيش حركة، بس المعاينة لازم تفرق بينها
            # وبين اللي في المخزن ومستنياها الحركة.
            in_place[iid] = {"slot": key, "slot_index": target["slot_index"],
                             "instance_id": row["instance_id"], "name": row.get("name") or label}
            continue
        if occupant.get("instance_id"):
            evict.append({"instance_id": occupant["instance_id"],
                          "name": occupant.get("name") or "", "slot": LABELS.get(key, key)})
        steps.append({
            "instance_id": row["instance_id"], "name": row.get("name") or label,
            "image": row.get("image") or "", "asset_id": row.get("asset_id") or "",
            "substituted": iid != row["instance_id"],
            "saved_instance_id": iid,
            "slot": key, "slot_label": LABELS.get(key, key),
            "slot_index": target["slot_index"], "from": row.get("container"),
            "target_container": _container_for(key), "target_wrapper_id": target["wrapper_id"],
        })
    seen, evict_clean = set(), []
    for e in evict:
        if e["instance_id"] in seen:
            continue
        seen.add(e["instance_id"])
        evict_clean.append(e)

    # الفضلة: أي حاجة قاعدة في منطقة التجهيز والبروفيل مالهاش عليها بند —
    # بما فيها الجيب الآمن والشنطة. القالب بيتعمل وهو فاضي من المكان ده، فـ
    # «التنفيذ بالظبط» معناه ترجع المخزن (الأوفر لما المخزن يقفل).
    extras = []
    for key in SAVE_KEYS:
        for slot in snap["slots"].get(key) or []:
            occupant = slot.get("item") or {}
            oid = occupant.get("instance_id")
            if not oid or oid in claimed or oid in seen:
                continue
            seen.add(oid)
            extras.append({"instance_id": oid, "name": occupant.get("name") or "",
                           "slot": LABELS.get(key, key), "extra": True})

    # العجز الكمي: نفس القطعة في نفس الخانة بس أقل عدد من اللي اتحفظ. المطابقة
    # بتتم بالقطعة نفسها، فالخانة دي كانت بتقول "في مكانها" وهي ناقصة.
    # النقص ده بيتحلّ بنفس ترتيب اللعبة: units من الستاش/الأوفر الأول (نفس مسار
    # ⇄ المتقيس لايف)، والباقي تصنيع أو شراء — فبنحسب `takes` دلوقتي عشان
    # `apply_plan` ينفّذها، و`preview` تبني مساريها على اللي فضل فعلاً.
    from . import actions
    spare, pools = {}, {}
    for r in by_id.values():
        if r["instance_id"] in claimed or r["instance_id"] in seen:
            continue
        if str(r.get("container") or "") not in ("stash", "overflow", "backpack"):
            continue
        key_asset = str(r.get("asset_id") or "")
        qty = int(r.get("qty") or 0)
        spare[key_asset] = spare.get(key_asset, 0) + qty
        if qty > 0:
            pools.setdefault(key_asset, []).append({"instance_id": r["instance_id"], "amount": qty})
    short = {}
    for iid, (key, item, row, pos) in taken.items():
        need = max(1, int(item.get("qty") or 1))
        have = max(1, int(row.get("qty") or 1))
        if need <= have:
            continue
        asset = str(row.get("asset_id") or item.get("asset_id") or "")
        cap = max(int(row.get("stack_size") or 0), actions._stack_cap(conn, account, asset))
        # سعة الرصة بيقولكم قد إيه الخانة تستقبل: لو المحفوظ أكبر من السقف
        # (اتقاس قبل ما السقف يتغيّر) بنوصل للسقف وبس ونقولّه.
        goal = min(need, cap) if cap > 0 else need
        by = goal - have
        if by < 1:
            continue
        takes = actions.fill_takes(pools.get(asset) or [], by, cap) or []
        units = sum(int(t["amount"]) for t in takes)
        short[iid] = {"slot": key, "slot_label": LABELS.get(key, key), "need": need, "have": have,
                      "by": by, "goal": goal, "cap": cap, "asset_id": asset,
                      "spare": spare.get(asset, 0), "takes": takes, "from_stash": units,
                      "still": by - units, "over_cap": need > goal,
                      "instance_id": row["instance_id"], "name": row.get("name") or item.get("name") or ""}
    for step in steps:
        gap = short.get(str(step.get("saved_instance_id") or ""))
        if gap:
            step["short_by"] = gap["by"]
    topups = _topup_gaps(short)
    evict_all = evict_clean + extras
    return {"loadout": {"id": rec["id"], "name": rec["name"]}, "steps": steps,
            "evict": evict_all, "extras": extras, "skipped": skipped, "in_place": in_place,
            "short": short,
            "conflicts": [], "missing": skipped,
            # الخطة قابلة للتنفيذ لو فيها قطعة تتنقل، أو وحدات في المخزن تُزوّد
            # خانة، أو فضلة في منطقة التجهيز لازم ترجع المخزن.
            "executable": bool(steps) or bool(topups) or bool(extras),
            "already": not steps and not skipped and not short and not extras,
            "writes": writer.status()}


def _moves_for(steps, evict):
    """قائمة حركات move_plan: تفريغ أصحاب الأماكن الأول، وبعدين كل قطعة لخانتها."""
    moves = []
    if evict:
        moves.append({"target_container": "stash", "target_slot": "", "target_wrapper_id": "",
                      "instance_ids": [e["instance_id"] for e in evict]})
    for step in steps:
        moves.append({"target_container": step["target_container"],
                      "target_slot": step["slot"],
                      "target_wrapper_id": step["target_wrapper_id"],
                      "instance_ids": [step["instance_id"]]})
    return moves


def _topup_gaps(short):
    """الخانات الناقصة اللي لها وحدات في المخزن — دي اللي `_run_topups` هتنفذها."""
    return [g for g in (short or {}).values() if g.get("takes")]


def _run_topups(conn, account, short):
    """يزوّد الخانة الناقصة بوحداتها من الستاش/الأوفر: نفس ⇄ المتقيس لايف —
    `update` بيزوّد الوجهة + `update`/`delete` بينقص المصدر، والمجموع ثابت."""
    from . import pioneer_write
    done, failed = [], []
    for gap in (short or {}).values():
        for take in gap.get("takes") or []:
            res = pioneer_write.combine_attempt(conn, account, instance_id=take["instance_id"],
                                                target_instance_id=gap["instance_id"],
                                                amount=int(take["amount"]), cap=gap.get("cap") or 0)
            row = {"name": gap["name"], "slot_label": gap["slot_label"],
                   "amount": int(take["amount"]), "source": take["instance_id"],
                   "cell": gap["instance_id"], "executed": bool(res.get("executed")),
                   "error": str(res.get("error") or ""), "detail": str(res.get("detail") or "")}
            (done if row["executed"] else failed).append(row)
    return done, failed


def _moved_count(value):
    """`move_plan` بيرجّع `moved` قائمة الحركات نفسها، والعدّاد هنا عايز رقم."""
    if isinstance(value, (list, tuple)):
        return len(value)
    return int(value or 0)


def _finish_topups(conn, account, loadout_id, res):
    """تعبئة العدد الناقصة بعد النقل — بتتقري من خطة جديدة لأن النقل حدّث الsnapshot.

    كده اللي اتصنّع أو اتشرى في خطوة التعبئة اللي قبل APPLY بيشيل النقص ده
    تلقائياً، والخانة اللي في نص الشنطة ما بتتحركش عشان حد زوّدها.
    """
    if not (res.get("executed") or not _moved_count(res.get("moved"))):
        return res
    done, failed = _run_topups(conn, account, plan(conn, account, loadout_id).get("short"))
    res["topups"] = done + failed
    res["topped"] = sum(r["amount"] for r in done)
    if failed:
        res["topup_failed"] = sum(int(r["amount"]) for r in failed)
        res["topup_detail"] = failed[0]["detail"] or failed[0]["error"] or "the merge was refused"
    return res


def _plan_out(out, res):
    res["loadout"] = out["loadout"]
    res["steps"] = out["steps"]
    res["evict"] = out["evict"]
    res["extras"] = out.get("extras") or []
    res["skipped"] = out["skipped"]
    if res.get("executed"):
        bits = []
        if res.get("moved"):
            bits.append("moved %d item(s) into place" % res["moved"])
        if res.get("topped"):
            bits.append("pulled %d unit(s) from your stash" % res["topped"])
        if res.get("cleared"):
            bits.append("returned %d extra item(s) to the stash" % res["cleared"])
        if out["skipped"]:
            bits.append("skipped %d unavailable" % len(out["skipped"]))
        res["detail"] = ("Loaded the profile — " + ", ".join(bits)) if bits else \
            "The profile already matches your board."
    return res


def _execute_pass(conn, account, loadout_id, out):
    """محاولة واحدة: الأوجمنت لوحده الأول، باقي الحركة، وبعدين تزويد الناقص.

    الأوجمنت لوحده لأنه بيبدّل الحاوية الحيّة — كل خانات التجهيز والشنطة بتبقى
    خانات الأوجمنت بآيدز تانية، فباقي الخطة المحسوب على الحاوية القديمة بيرفضوه
    النقل (bad_wrapper). الكتابة الأولى بتحدّث الـ snapshot، فالخطة اللي بعدها
    بتتحسب على الواقع الجديد.
    """
    from . import pioneer_write

    aug_steps = [s for s in out["steps"] if s["slot"] == "augment"]
    if aug_steps:
        aug_evict = [e for e in out["evict"] if e.get("slot") == LABELS["augment"]]
        first = pioneer_write.move_plan(conn, account, _moves_for(aug_steps, aug_evict))
        first["augment_first"] = True
        if not first.get("executed"):
            return first
        out = plan(conn, account, loadout_id)

    moved = 0
    if out["steps"] or out["evict"]:
        res = pioneer_write.move_plan(conn, account, _moves_for(out["steps"], out["evict"]))
        if not res.get("executed"):
            return res
        moved = _moved_count(res.get("moved"))
    else:
        res = {"executed": True, "detail": "Nothing to move."}
    res = _finish_topups(conn, account, loadout_id, res)
    res["moved"] = moved
    return res


def apply_plan(conn, account, loadout_id):
    out = plan(conn, account, loadout_id)
    topups = _topup_gaps(out.get("short"))
    if not out["executable"]:
        detail = ("This loadout already matches the current state." if out["already"] else
                  "Nothing from this loadout is available now — there is nothing to execute.")
        if out.get("short"):
            detail = ("%d cell(s) are short on count and you have none of them in the stash — "
                      "craft or buy the missing units first." % len(out["short"]))
        out.update({"executed": False, "error": "already_loaded", "detail": detail})
        return out
    status = writer.status()
    if not status.get("move_armed"):
        from . import pioneer_write
        if status.get("gateway_route_down"):
            detail = pioneer_write.ROUTE_DOWN_DETAIL
        elif status.get("write_paused"):
            detail = "Read-only mode is enabled — the plan is shown only."
        else:
            detail = "Writing is locked for this run — the plan is shown only."
        out.update({"executed": False, "error": "read_only",
                    "detail": detail,
                      "preview": {"steps": out["steps"], "evict": out["evict"], "topups": topups}})
        return out

    # البروفيل بيتنفّذ لحد ما اللوحة تطابقه حرفياً: كل جولة بتعيد الخطة من
    # الواقع الجديد (الكتابة نفسها بتحدّث الـ snapshot)، فلو النقل خلّى خانة
    # تانية ناقصة أو طلعت فضلة جديدة الجولة الجاية تشيلها. ثلاث جولات سقف
    # مانع لأي مبادلة تلف بين قطعتين لهما نفس النوع.
    totals = {"executed": True, "moved": 0, "topped": 0, "cleared": 0, "topups": []}
    for _ in range(3):
        cur = plan(conn, account, loadout_id)
        if not cur["steps"] and not cur["extras"] and not _topup_gaps(cur["short"]):
            break
        res = _execute_pass(conn, account, loadout_id, cur)
        out = cur
        if not res.get("executed"):
            totals.update({"executed": False, "error": res.get("error") or "refused",
                           "detail": res.get("detail") or ""})
            break
        totals["moved"] += _moved_count(res.get("moved"))
        totals["topped"] += int(res.get("topped") or 0)
        totals["cleared"] += len(cur["extras"])
        totals["topups"] += res.get("topups") or []
        if res.get("topup_failed"):
            totals["topup_failed"] = int(totals.get("topup_failed") or 0) + int(res["topup_failed"])
            totals["topup_detail"] = res.get("topup_detail")
    left = plan(conn, account, loadout_id)
    totals["remaining"] = {"steps": len(left["steps"]), "extras": len(left["extras"]),
                           "short": len(left["short"] or {}), "skipped": len(left["skipped"])}
    if totals.get("executed") and any(totals["remaining"].values()):
        totals["detail_note"] = ("The board is still not an exact match — %d cell(s) move, "
                                 "%d short, %d extra left." % (totals["remaining"]["steps"],
                                                               totals["remaining"]["short"],
                                                               totals["remaining"]["extras"]))
    return _plan_out(out, totals)


# ترتيب المعاينة: نفس شكل الشبكة — التجهيز الكبير، ثم السريع والمعزّز والجيب
# الآمن، وبعدهم الشنطة.
PREVIEW_ORDER = ("augment", "shield", "gun_1", "gun_2", "quick_use",
                 "augmented_slots", "safe_pocket", "backpack")


def _card_face(item):
    """شكل عنصر محفوظ: القالب بيخزن الاسم والصورة بس، فالندرة والمجموعة والتوع
    بتتقري من الفهرس المحلي — نفس مصدر تلوين بلاطات المخزن."""
    face = {"name": item.get("name") or "", "type": item.get("type") or "",
            "asset_id": item.get("asset_id") or ""}
    try:
        catalog.decorate(face)
    except Exception:
        pass
    image = face.get("arctracker_image") or item.get("image") or ""
    return {"name": face.get("display_name") or face.get("name") or "?",
            "image": image,
            "rarity": face.get("arctracker_rarity") or "Common",
            "group": face.get("group") or "",
            "type": face.get("arctracker_type") or face.get("type") or ""}


def _craft_option(conn, item, gate, claimed):
    """مسار التصنيع للناقص: الوصفة + إثبات التفعيل + خامات الستاش الحقيقية.

    الخامات بتتحجز واحدة ورا التانية (`claimed`) عشان لو القالب ناقص أكتر من
    بند بيستهلك نفس الخامة، التاني ما يقولش "ممكن" على كمية صرفت في الأول.
    """
    recipe = items_db.recipe_for(asset_id=item.get("asset_id"), name=item.get("name"))
    if not recipe or not recipe.get("materials"):
        return {"possible": False, "reason": "no_recipe",
                "detail": "No crafting recipe for this item — it comes from loot or a trader."}
    slug = str(recipe.get("slug") or "")
    station = workshop._station(recipe.get("stations") or [])
    required = int(recipe.get("station_level") or 0)
    current = int((gate.get("levels") or {}).get(station) or 0)
    out = {"slug": slug, "station": station, "station_label": workshop.station_label(station),
           "level_required": required, "level_current": current,
           "per_craft": max(1, int(recipe.get("quantity") or 1)),
           "materials": [], "short": []}
    if not (gate.get("access") or {}).get(slug):
        out.update({"possible": False, "reason": "not_unlocked",
                    "detail": "This recipe needs a blueprint you have not activated — "
                              "your account tree has no Unlock Craft node for it."})
        return out
    if required and current and current < required:
        out.update({"possible": False, "reason": "level",
                    "detail": "%s is level %d — the recipe needs %d." % (out["station_label"], current, required)})
        return out
    want = max(1, int(item.get("qty") or 1))
    crafts = max(1, math.ceil(want / out["per_craft"]))
    mats, short = [], []
    for mat in recipe.get("materials") or []:
        need = int(mat.get("qty") or 1) * crafts
        key = workshop.material_key(mat.get("slug"), mat.get("name"))
        ids = [str(a) for a in workshop.material_ids(conn, mat)]
        have = sum(int((gate["owned"] or {}).get(a, 0) or 0) for a in ids)
        free = max(0, have - int(claimed.get(key, 0)))
        take = min(free, need)
        if take < need:
            short.append({"name": mat.get("name") or key, "need": need, "have": free})
        claimed[key] = int(claimed.get(key, 0)) + take
        mats.append({"name": mat.get("name") or "?", "slug": mat.get("slug") or "",
                     "image_filename": mat.get("image_filename") or "",
                     "need": need, "have": free, "rarity": (items_db.by_slug(mat.get("slug")) or {}).get("rarity") or ""})
    out.update({"materials": mats, "short": short, "crafts": crafts, "want": want,
                "possible": not short, "reason": "" if not short else "materials",
                "detail": "" if not short else
                          "Not enough: " + ", ".join("%s (%d/%d)" % (s["name"], s["have"], s["need"]) for s in short)})
    return out


def _buy_index(conn, account):
    """gameAssetId -> عروض التجار اللي بتديه، الأرخص أولاً."""
    by_asset = {}
    try:
        idx = traders._offer_index(conn, account)
    except Exception:
        return {}
    for trader, offer in idx.values():
        asset_id = str((offer.get("reward") or {}).get("asset_id") or "")
        if asset_id:
            by_asset.setdefault(asset_id, []).append((trader, offer))
    for hits in by_asset.values():
        hits.sort(key=lambda pair: int(((pair[1].get("cost") or {}).get("amount") or 0)))
    return by_asset


def _buy_option(conn, account, item, index):
    """أرخص عرض بيدي القطعة الناقصة + الرصيد الكافي لكميتهاش."""
    ids = {str(a) for a in workshop.asset_ids_for(conn, "", str(item.get("name") or ""),
                                                  [item.get("asset_id") or ""])}
    ids.discard("")
    hits = []
    for asset_id in ids:
        hits.extend(index.get(asset_id) or [])
    if not hits:
        return {"possible": False, "reason": "no_offer",
                "detail": "No trader on your account sells this item."}
    want = max(1, int(item.get("qty") or 1))
    cands = []
    for trader, offer in hits:
        reward = offer.get("reward") or {}
        cost = offer.get("cost") or {}
        per = max(1, int(reward.get("amount") or 1))
        buys = max(1, math.ceil(want / per))
        unit = int(cost.get("amount") or 0)
        total = unit * buys
        remaining = offer.get("remaining")
        have = traders.balance_of(conn, account, cost)
        reason = ""
        if isinstance(remaining, int) and remaining < buys:
            reason = "limit"
        elif have < total:
            reason = "coins"
        cands.append({"possible": not reason, "reason": reason,
                      "offer_id": offer.get("offer_id"), "trader": (trader or {}).get("name") or "",
                      "title": offer.get("title") or reward.get("name") or "",
                      "image": reward.get("image") or "", "reward_amount": per,
                      "buys": buys, "want": want, "unit": unit, "total": total, "have": have,
                      "remaining": remaining,
                      "currency": {"name": cost.get("name") or "Coins", "image": cost.get("image") or "",
                                   "asset_id": str(cost.get("asset_id") or "")},
                      "detail": "" if not reason else
                                ("%s: you have %s %s and %d are needed." %
                                 (cost.get("name") or "Coins", format(have, ","),
                                  cost.get("name") or "Coins", total) if reason == "coins" else
                                 "Only %s left in the offer today." % remaining)})
    cands.sort(key=lambda c: (0 if c["possible"] else 1, c["total"]))
    return cands[0]


def preview(conn, account, loadout_id):
    """معاينة قالب قبل ما يتنفذ: كل خانة بحالها، والناقص بمساريه.

    الحالة `ready` = نفس القطعة، `substituted` = نسخة تانية من نفس النوع اتحلت
    محلها، `blocked` = القطعة عندك بس الخانة نفسها مش مبنيّة في شجرة الحساب،
    `missing` = مش عندك — ودي اللي التصنيع أو الشراء بيشيلها،
    `short` = القطعة في الخانة نفسها بس بعدد أقل من المحفوظ. النقص ده بيتحلّ
    بالترتيب ده وقت APPLY: `from_stash` وحدة بتسحبها الخطة من الستاش/الأوفر
    (`takes`، ونفس مسار ⇄)، والباقي `need_to_get` هو اللي التصنيع أو الشراء
    بيشيله. لو `over_cap` صح فالعدد المحفوظ أكبر من سعة الرصة فالخانة بتملى للسقف بس.
    """
    rec = store.get_loadout(conn, loadout_id)
    if not rec:
        raise KeyError("unknown loadout")
    saved = json.loads(rec["data"] or "{}")
    moved = plan(conn, account, loadout_id)
    steps = {str(s.get("saved_instance_id") or ""): s for s in moved["steps"]}
    in_place = moved.get("in_place") or {}
    short = moved.get("short") or {}
    blocked = {str(s.get("saved_instance_id") or ""): s for s in moved["skipped"]
               if s.get("reason") == "no_slot"}
    gate = workshop._craft_gate(conn, account)
    index = _buy_index(conn, account)
    claimed, cards = {}, []
    for key in PREVIEW_ORDER:
        for pos, item in enumerate((saved.get("items") or {}).get(key) or []):
            iid = str(item.get("instance_id") or "")
            face = _card_face(item)
            card = {"slot": key, "slot_label": LABELS.get(key, key),
                    "slot_index": item.get("slot_index", pos),
                    "name": face["name"], "image": face["image"], "rarity": face["rarity"],
                    "group": face["group"], "type": face["type"],
                    "asset_id": str(item.get("asset_id") or ""),
                    "qty": int(item.get("qty") or 1)}
            step = steps.get(iid)
            gap = short.get(iid)
            if step:
                card["status"] = "substituted" if step.get("substituted") else "ready"
                card["current"] = {"instance_id": step["instance_id"], "name": step.get("name"),
                                   "container": step.get("from")}
            elif iid in in_place:
                card["status"] = "ready"
                card["in_place"] = True
                card["current"] = {"instance_id": in_place[iid]["instance_id"],
                                   "name": in_place[iid]["name"], "container": "its cell"}
            elif iid in blocked:
                card["status"] = "blocked"
                card["detail"] = "The item is yours — that cell is not built in your account tree yet."
            else:
                card["status"] = "missing"
                card["fill"] = {"craft": _craft_option(conn, item, gate, claimed),
                                "buy": _buy_option(conn, account, item, index)}
            if gap and card["status"] in ("ready", "substituted"):
                # الخانة صاحبةها بس عدد أنقص من المحفوظ: اللي في الستاش بيتسحب
                # وقت APPLY، ومسار التعبئة بيتبني على اللي فضل بعد السحب ده.
                card["status"] = "short"
                card["short_by"] = gap["by"]
                card["short_need"] = gap["need"]
                card["short_have"] = gap["have"]
                card["spare"] = gap["spare"]
                card["from_stash"] = gap["from_stash"]
                card["takes"] = gap["takes"]
                card["cap"] = gap["cap"]
                card["over_cap"] = gap["over_cap"]
                card["in_place"] = iid in in_place
                want = gap["still"]
                card["need_to_get"] = want
                card["fill"] = ({"craft": _craft_option(conn, dict(item, qty=want), gate, claimed),
                                 "buy": _buy_option(conn, account, dict(item, qty=want), index)}
                                if want > 0 else None)
            cards.append(card)
    missing = [c for c in cards if c["status"] == "missing"]
    short_cards = [c for c in cards if c["status"] == "short"]
    fillable = [c for c in short_cards if c["fill"]]
    summary = {"total": len(cards), "ready": len(cards) - len(missing) -
                            sum(1 for c in cards if c["status"] == "blocked") - len(short_cards),
               "blocked": sum(1 for c in cards if c["status"] == "blocked"),
               "missing": len(missing),
               "short": len(short_cards),
               "short_units": sum(c["short_by"] for c in short_cards),
               "short_covered": sum(int(c.get("from_stash") or 0) for c in short_cards),
               "topup_cells": sum(1 for c in short_cards if c.get("from_stash")),
               "short_covered_cells": sum(1 for c in short_cards if not c["fill"]),
               "short_needing": len(fillable),
               "craftable": sum(1 for c in missing if c["fill"]["craft"]["possible"])
                            + sum(1 for c in fillable if c["fill"]["craft"]["possible"]),
               "buyable": sum(1 for c in missing if c["fill"]["buy"]["possible"])
                          + sum(1 for c in fillable if c["fill"]["buy"]["possible"]),
               "unfillable": sum(1 for c in missing if not c["fill"]["craft"]["possible"]
                                 and not c["fill"]["buy"]["possible"])
                             + sum(1 for c in fillable if not c["fill"]["craft"]["possible"]
                                   and not c["fill"]["buy"]["possible"]),
               "moves": len(moved["steps"]),
               "evict": sum(1 for e in moved["evict"] if not e.get("extra")),
               "extras": len(moved["extras"])}
    return {"account": account, "loadout": {"id": rec["id"], "name": rec["name"],
                                            "owner_account": rec["account"]},
            "cards": cards, "summary": summary,
            "steps": moved["steps"], "evict": moved["evict"], "skipped": moved["skipped"],
            "already": moved["already"], "writes": writer.status()}
