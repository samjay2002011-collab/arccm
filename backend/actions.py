"""طبقة التنسيق بين اللوحة المحلية وحساب اللعبة: بتحدد العناصر، بتبني الطلب، وبتنفذه.

كل إجراء بيرجع نفس الشكل:
  {"executed": bool, "preview": {request...}, "result": {...}, "refreshed": {...}}
لو الكتابة مش مفعّلة: بيرجع preview بس (مفيش أي طلب خارجي).
"""
import json
import time

from . import (catalog, config, gearops, items_db, pioneer_client as pc, pioneer_tree,
               pioneer_write, store, sync, weapon_tiers, writer)

MARK_COLORS = ("#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4", "#3b82f6", "#a855f7", "#ec4899")
DIRECT_BLOCK_DETAIL = ("What the Embark gateway executes literally: moves + attachments + recycle "
                       ", scrap and repair + weapon upgrades. "
                       "Splitting and trader buys have no mutate kind — those exist in-game only.")
ATTACH_TARGETS = ("stash", "overflow")
SLOT_ORDER = {"muzzle": 1, "grip": 2, "stock": 3, "light_mag": 4, "medium_mag": 5,
              "shotgun_mag": 6, "shotgun_muzzle": 7, "anvil_splitter": 8}


def _rows_for(conn, account, instance_ids=None, name=None, container=None, limit=None):
    sql = "SELECT * FROM instances WHERE account=?"
    args = [account]
    if instance_ids:
        sql += " AND instance_id IN (%s)" % ",".join("?" * len(instance_ids))
        args += [str(i) for i in instance_ids]
    if name:
        sql += " AND name=?"
        args.append(name)
    if container:
        sql += " AND container=?"
        args.append(container)
    sql += " ORDER BY container, slot_index"
    if limit:
        sql += " LIMIT %d" % int(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def sections(conn, account):
    """تجميع العناصر لكل قسم على حدة (STASH / BACKPACK / OVERFLOW / EQUIPPED).

    حساب واحد في المرة — القراءة بتجميع حسابات مع بعضها بتطلع عناصر مش موجودة في الحساب.
    """
    if not account or account == "ALL":
        return {}
    rows = _rows_for(conn, account)
    cats = {}
    for item in conn.execute("SELECT DISTINCT name, category FROM items WHERE account=?",
                             (account,)).fetchall():
        try:
            cats[item["name"]] = json.loads(item["category"] or "[]")
        except ValueError:
            cats[item["name"]] = []
    groups = {}
    for r in rows:
        key = r["container"] or "other"
        r["category"] = cats.get(r["name"], [])
        try:
            r["attachments"] = json.loads(r.get("attachments") or "[]")
        except (TypeError, ValueError):
            r["attachments"] = []
        catalog.decorate(r)
        bucket = groups.setdefault(key, {"container": key, "count": 0, "qty": 0, "slots": [],
                                         "rarity": {}, "value": 0, "accounts": {}})
        bucket["count"] += 1
        bucket["qty"] += r["qty"] or 0
        bucket["value"] += (r["value"] or 0) * (r["qty"] or 0)
        bucket["rarity"][r["rarity"] or "?"] = bucket["rarity"].get(r["rarity"] or "?", 0) + 1
        bucket["accounts"][r["account"]] = bucket["accounts"].get(r["account"], 0) + 1
        bucket["slots"].append(r)
    for bucket in groups.values():
        bucket["slots"].sort(key=lambda s: (s["slot_index"] if s["slot_index"] is not None else 9999, s["name"]))
    return groups


def empty_wrappers(payload):
    """خريطة الخانات الفاضية لكل قسم (تحتاجها عملية تقسيم الـ stack)."""
    out = {}
    if not payload:
        return out
    for key in ("stash", "overflow", "backpack"):
        out[key] = [s.get("wrapper_id") for s in (payload.get(key) or [])
                    if (s.get("is_empty") or not s.get("item")) and s.get("wrapper_id")]
    for key, slots in (payload.get("containers") or {}).items():
        if key in ("stash", "backpack") or not isinstance(slots, list):
            continue
        out[key] = [s.get("wrapper_id") for s in slots
                    if (s.get("is_empty") or not s.get("item")) and s.get("wrapper_id")]
    return out


def _account_id(conn, account):
    """المعرّف المحفوظ للحساب (للتسجيل وللسحب في الوضع القديم)."""
    return (store.get_account(conn, account) or {}).get("id")


SLOT_RULES = ("augment", "shield", "gun_1", "gun_2", "quick_use", "safe_pocket", "augmented_slots")


def _finish(conn, account, kind, request, outcome, count):
    store.log_action(conn, account, kind, request,
                     "executed" if outcome.get("ok") and outcome.get("code") else outcome.get("error", "preview"),
                     outcome.get("response") or outcome.get("detail"), count)
    refreshed = None
    if outcome.get("ok"):
        acc_id = _account_id(conn, account)
        refreshed = sync.pull_account(conn, account, acc_id, with_assets=False) if acc_id else None
    return {"executed": bool(outcome.get("ok")), "preview": request, "result": outcome, "refreshed": refreshed}


def _direct_block(kind, allow=()):
    """في الوضع المباشر المسار الوحيد هو بوابة اللعبة: النقل + الأنواع اللي بتعرفها.

    الأنواع اللي بتعدي هنا مقيسة لايف على البوابة (recycle/scrap/repair) — أي إجراء
    تاني لسه بيترفض صراحةً برسالة واضحة بدل ما يتنفذ على مصدر تاني."""
    if config.DATA_SOURCE != "pioneer":
        return None
    if kind in allow:
        return None
    return {"executed": False, "error": "direct_read_only", "detail": DIRECT_BLOCK_DETAIL, "kind": kind}


def move(conn, account, target_container, instance_ids=None, name=None, container=None,
         target_wrapper_id="", limit=None, target_slot=""):
    if target_container not in writer.CONTAINERS:
        return {"executed": False, "error": "bad_target", "detail": "Unknown destination: %s" % target_container}
    if target_slot and target_slot not in SLOT_RULES:
        return {"executed": False, "error": "bad_slot", "detail": "Unknown loadout slot: %s" % target_slot}
    rows = _rows_for(conn, account, instance_ids, name, container, limit)
    if not rows:
        return {"executed": False, "error": "nothing_selected", "detail": "No items match the selection."}
    if config.DATA_SOURCE == "pioneer":
        if account == "ALL":
            return {"executed": False, "error": "pick_account", "detail": "Pick one account before moving."}
        return pioneer_write.move(conn, account, target_container, rows,
                                  target_wrapper_id=target_wrapper_id, target_slot=target_slot)
    if target_container == "loadout" and not target_wrapper_id:
        return {"executed": False, "error": "no_wrapper", "detail": "The loadout cell is not bound to a wrapper."}
    body = writer.build_move(rows, target_container, target_wrapper_id)
    preview = {"method": "POST", "url": config.UPSTREAM_API + writer.BATCH_MOVE, "body": body,
               "items": [{"name": r["name"], "qty": r["qty"], "from": r["container"]} for r in rows][:40]}
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account before moving.", "preview": preview}
    outcome = writer.execute("move", body, _account_id(conn, account))
    outcome = dict(outcome, request=None)
    out = _finish(conn, account, "move:%s" % target_container, body, outcome, len(rows))
    out["preview"] = preview
    out["moved"] = [{"name": r["name"], "qty": r["qty"], "from": r["container"]} for r in rows]
    return out


def move_batch(conn, account, moves):
    """خطة نقل كاملة في نداء واحد — قراءة شجرة واحدة وطلب بوابة واحد.

    الواجهة بتبعت خطة التبديل/النقل كلها هنا بدل ما تعمل نداء لكل قطعة،
    فالتبديل بين مكانين بقى طلب واحد بدل 3، ونقل 10 قطع بقى طلب واحد بدل 10.
    """
    moves = [m for m in (moves or []) if isinstance(m, dict)]
    if not moves:
        return {"executed": False, "error": "nothing_selected", "detail": "No moves in the plan."}
    if config.DATA_SOURCE == "pioneer":
        if account == "ALL":
            return {"executed": False, "error": "pick_account", "detail": "Pick one account before moving."}
        prepared = []
        for item in moves:
            target = item.get("target_container") or ""
            if target not in writer.CONTAINERS:
                return {"executed": False, "error": "bad_target", "detail": "Unknown destination: %s" % target}
            slot = item.get("target_slot") or ""
            if slot and slot not in SLOT_RULES:
                return {"executed": False, "error": "bad_slot", "detail": "Unknown loadout slot: %s" % slot}
            ids = [str(i) for i in (item.get("instance_ids") or []) if i]
            rows = _rows_for(conn, account, ids, item.get("name"), item.get("from_container"),
                             item.get("limit"))
            if len(rows) != len(ids):
                return {"executed": False, "error": "unknown_instance",
                        "detail": "Some items are not in the local copy — run SYNCHRONIZE."}
            prepared.append({"target_container": target, "target_slot": slot,
                             "target_wrapper_id": item.get("target_wrapper_id") or "",
                             "instance_ids": [r["instance_id"] for r in rows]})
        return pioneer_write.move_plan(conn, account, prepared)
    results = []
    for item in moves:
        out = move(conn, account, item.get("target_container") or "",
                   instance_ids=item.get("instance_ids"), name=item.get("name"),
                   container=item.get("from_container"),
                   target_wrapper_id=item.get("target_wrapper_id") or "",
                   limit=item.get("limit"), target_slot=item.get("target_slot") or "")
        results.append({"executed": bool(out.get("executed")), "error": out.get("error"),
                        "detail": out.get("detail")})
        if not out.get("executed"):
            return {"executed": False, "moves": results, "error": out.get("error"),
                    "detail": out.get("detail")}
    return {"executed": True, "moves": results}


def _stack_cap(conn, account, asset_id):
    """السقف الأقصى للأكوم من النوع ده: أعمق مصدرين محليين، ومفيش أي طلب للبوابة."""
    aid = str(asset_id or "")
    if not aid:
        return 0
    try:
        cap = int(conn.execute("select max(stack_size) from instances "
                               "where account=? and asset_id=?", (account, aid)).fetchone()[0] or 0)
    except Exception:
        cap = 0
    if not cap:
        # الصفوف الجديدة بتدخل قبل ما يتعبّى عمود stack_size — الحد من كتالوج arctracker.
        try:
            cap = int((items_db.dossier(asset_id=aid) or {}).get("stack_size") or 0)
        except Exception:
            cap = 0
    return cap


def gather(conn, account, instance_ids=None, asset_id=""):
    """يكشّف كثافة أكوام عنصر واحد ويقرّبها من بعضها في خانات متتالية.

    الدمج الفعلي (تغيير كمية كوم) مش متاح على بوابة Embark — الأقيس لايف
    2026-10-28: أي amount مختلف عن الحالي = INVALID_ARGUMENT، ومفيش نوع
    combine/split في الـenum بتاع Pioneer. فبنقرّب الأكوام بس، واللمة نفسها
    تتم جوه اللعبة بسحب واحد (الدمج الحقيقي له مساره في combine).
    """
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account first."}
    rows = _rows_for(conn, account, instance_ids)
    aid = str(asset_id or (rows[0].get("asset_id") if rows else "") or "")
    if not aid:
        return {"executed": False, "error": "nothing_selected",
                "detail": "Select one item or type its name in the search first."}
    names = {str(r.get("name") or "") for r in rows if r.get("name")}
    limit = _stack_cap(conn, account, aid)
    try:
        tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
        plan = pioneer_tree.merge_plan(tree, aid, limit=limit)
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "detail": exc.detail, "kind": "gather"}
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "detail": str(exc)[:200], "kind": "gather"}
    out = {"kind": "gather", "merge": plan, "gather": plan,
           "item": (list(names)[0] if len(names) == 1 else "%s stacks" % plan["total"])}
    if not plan["moves"]:
        # مفيش حركة لازمة — بنرجع التحليل لوحده من غير ما نبعت أي طلب للبوابة.
        out.update({"executed": False, "reason": "already_together",
                    "detail": plan["detail"]})
        return out
    out.update(pioneer_write.move_plan(conn, account, plan["moves"]))
    out["merge"] = plan
    return out


def spread(conn, account, instance_ids=None, asset_id="", dry=False):
    """يفرّد أكوام عنصر واحد على خانات ستاش متباعدة — كل كوم في خانة لوحده.

    عكس gather وبينفس مسار النقل الرسمي. تقسيم الكوم نفسه (نصفه في خانة فاضية)
    مرفوض على البوابة: أي amount مختلف = INVALID_ARGUMENT، فالحركة دي بتفرد
    الأكوام الموجودة مش بتولّد أكوام جديدة.
    """
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account first."}
    rows = _rows_for(conn, account, instance_ids)
    aid = str(asset_id or (rows[0].get("asset_id") if rows else "") or "")
    if not aid:
        return {"executed": False, "error": "nothing_selected",
                "detail": "Select one item or type its name in the search first."}
    names = {str(r.get("name") or "") for r in rows if r.get("name")}
    try:
        tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
        plan = pioneer_tree.spread_plan(tree, aid)
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "detail": exc.detail, "kind": "spread"}
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "detail": str(exc)[:200], "kind": "spread"}
    out = {"kind": "spread", "spread": plan,
           "item": (list(names)[0] if len(names) == 1 else "%s stacks" % plan["total"])}
    if not plan["moves"]:
        out.update({"executed": False, "reason": "already_spread", "detail": plan["detail"]})
        return out
    if dry:
        # معاينة قبل الكتابة: بنرجع الخطة نفسها من غير ما نبعت أي طلب للبوابة.
        out.update({"executed": False, "reason": "preview", "detail": plan["detail"]})
        return out
    out.update(pioneer_write.move_plan(conn, account, plan["moves"]))
    out["spread"] = plan
    return out


def merge_all(conn, account, dry=True, max_ops=200):
    """زرار ⇄: يلمّ كل أكوام الحساب (الستاش + الأوفر فلو) على الحد الأقصى لكل نوع.

    الدمج هنا حقيقي على البوابة الرسمية، مش ترتيب خانات: كل عملية طلب واحد فيه
    update لكمية الهدف + delete (أو update ناقص) للمصدر، والمجموع بيتحقق بعد كل
    عملية (مقيس لايف 2026-10-31 في pioneer_write.combine_attempt). مفيش سحبة
    جوه اللعبة ومفيش حاجة لخانة فاضية — الخانة بتفضى لوحدها لما المصدر يتشال.
    """
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account first."}
    caps, names = {}, {}
    try:
        for r in conn.execute("SELECT asset_id, max(stack_size) ss, name FROM instances "
                              "WHERE account=? AND asset_id IS NOT NULL GROUP BY asset_id",
                              (account,)).fetchall():
            aid = str(r["asset_id"])
            caps[aid] = int(r["ss"] or 0)
            names[aid] = str(r["name"] or "")
    except Exception:
        pass
    try:
        tree = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
        for aid in {str(e.get("gameAssetId") or "") for e in tree.items}:
            if not aid or aid == "None":
                continue
            if int(caps.get(aid) or 0) < 2:
                row = items_db.find(asset_id=aid) or {}
                if row.get("stack_size"):
                    caps[aid] = int(row["stack_size"])
                if row.get("name") and not names.get(aid):
                    names[aid] = str(row["name"])
        plan = pioneer_tree.merge_all_ops(tree, caps=caps, max_ops=max_ops)
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "detail": exc.detail, "kind": "merge_all"}
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "detail": str(exc)[:200], "kind": "merge_all"}
    for g in plan["groups"]:
        g["name"] = g.get("name") or names.get(g["asset_id"]) or g["asset_id"]
    out = {"kind": "merge_all", "merge_all": plan, "summary": plan["summary"],
           "detail": plan["detail"], "names": names}
    if not plan["ops"]:
        out.update({"executed": False, "reason": "already_merged", "preview": True})
        return out
    if dry:
        out.update({"executed": False, "reason": "preview"})
        return out
    results, done, refused = [], 0, None
    for op in plan["ops"]:
        r = pioneer_write.combine_attempt(conn, account, op["source"], op["target"],
                                          amount=op["take"], cap=op["cap"])
        row = {"asset_id": op["asset_id"], "name": names.get(op["asset_id"]) or op["asset_id"],
               "source": op["source"], "target": op["target"], "take": op["take"],
               "ok": bool(r.get("executed"))}
        results.append(row)
        if row["ok"]:
            done += 1
            continue
        row["detail"] = str(r.get("detail") or r.get("error") or "refused")
        refused = row
        if r.get("lost"):
            out["lost"] = True
        break
    out.update({"executed": done > 0, "merged": done, "results": results})
    if refused:
        out["refused"] = refused
        out["detail"] = ("%s merges ran, then the gateway refused %s: %s"
                         % (done, refused["name"], refused["detail"])) if done else \
                        ("The gateway refused the merge: " + refused["detail"])
    else:
        out["detail"] = "%s merges ran on the official gateway." % done
    return out


def touch(conn, account, instance_ids=None):
    """زرار ↑ UPDATE: لمسة محايدة على خانات التجهيز عند Embark.

    بتحدّث سجل التحديث (updatedAt) من غير ما أي عنصر يتحرّك أو كمية تتغيّر —
    محطوطة عشان الكلاينت اللي ماسك نسخة قديمة من الشنطة يسحبها من جديد، فالحاجة
    اللي تتحط في الشنطة من الموقع تظهر في الماتش الجاي مش بعدها.
    """
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account first."}
    out = pioneer_write.touch_loadout(conn, account, instance_ids)
    out["kind"] = "touch"
    return out


def mutate(conn, account, action, instance_ids=None, name=None, container=None,
           target_wrapper_id="", target_instance_id="", amount=None, limit=None):
    blocked = _direct_block("mutate")
    if blocked:
        return blocked
    if action not in writer.MUTATE_ACTIONS:
        return {"executed": False, "error": "bad_action", "detail": "Unsupported action: %s" % action}
    denied = [b for b in writer.HARD_BLOCKED if b in str(action).lower()]
    if denied:
        return {"executed": False, "error": "destructive_blocked",
                "detail": "The action '%s' is destructive and blocked in the local mirror." % action}
    rows = _rows_for(conn, account, instance_ids, name, container, limit)
    if not rows:
        return {"executed": False, "error": "nothing_selected", "detail": "No items match the selection."}
    body = writer.build_mutate(action, rows, target_wrapper_id, target_instance_id, amount)
    preview = {"method": "POST", "url": config.UPSTREAM_API + writer.BATCH_MUTATE, "body": body,
               "items": [{"name": r["name"], "qty": r["qty"], "container": r["container"]} for r in rows][:40]}
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account before executing.", "preview": preview}
    outcome = writer.execute("mutate", body, _account_id(conn, account), action=action)
    out = _finish(conn, account, "mutate:%s" % action, body, outcome, max(1, len(rows)))
    out["preview"] = preview
    return out


def _wrapper_rows(payload, container):
    """Wrapper rows لقسم معيّن من الـ snapshot (stash/backpack/loadout slots)."""
    lists = []
    if container in ("stash", "backpack", "overflow"):
        lists.append(payload.get(container) or [])
    lists.append((payload.get("containers") or {}).get(container) or [])
    out, seen = [], set()
    for entries in lists:
        for slot in entries or []:
            wrapper = slot.get("wrapper_id") or slot.get("wrapperId")
            if not wrapper or wrapper in seen:
                continue
            seen.add(wrapper)
            out.append(slot)
    return out


def _is_empty_slot(slot):
    return bool(slot.get("is_empty")) or not slot.get("item")


def _empty_wrappers(payload, container, exclude=""):
    return [s.get("wrapper_id") or s.get("wrapperId")
            for s in _wrapper_rows(payload, container)
            if _is_empty_slot(s) and (s.get("wrapper_id") or s.get("wrapperId")) != exclude]


def _wrapper_is_empty(payload, container, wrapper):
    if not wrapper:
        return False
    return any((s.get("wrapper_id") or s.get("wrapperId")) == wrapper and _is_empty_slot(s)
               for s in _wrapper_rows(payload, container))


def _find_split_result(conn, account, split_wrapper, name, amount):
    rows = _rows_for(conn, account)
    matches = [r for r in rows if r.get("wrapper_id") == split_wrapper and r.get("name") == name]
    exact = [r for r in matches if int(r.get("qty") or 0) == amount]
    return (exact or matches or [None])[0]


def _split_preview(row, split_target, amount, split_body, move_body=None):
    preview = {
        "instance_id": row.get("instance_id"), "name": row.get("name"),
        "qty": row.get("qty"), "amount": amount, "source": row.get("container"),
        "steps": [{"action": "split", "target_wrapper_id": split_target,
                   "request": {"method": "POST", "url": config.UPSTREAM_API + writer.BATCH_MUTATE,
                               "body": split_body}}],
    }
    if move_body:
        preview["steps"].append({"action": "move", "request": {
            "method": "POST", "url": config.UPSTREAM_API + writer.BATCH_MOVE, "body": move_body}})
    return preview


def split_stack(conn, account, instance_id, amount, mode="split",
                split_wrapper_id="", target_wrapper_id=""):
    """تقسيم stack مع نقل اختياري: batch-mutate(split) ثم batch-move للقطعة الجديدة.

    mode=split       : تقسيم داخل نفس القسم (BACKPACK / SAFE POCKET / QUICK USE).
    mode=to_backpack : من STASH/OVERFLOW إلى BACKPACK (split مباشر للـ wrapper لو مفيش فاضي).
    mode=to_stash    : من BACKPACK/SAFE POCKET/QUICK USE إلى STASH (split ثم move).
    """
    blocked = _direct_block("split")
    if blocked:
        return blocked
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account first."}
    if not instance_id:
        return {"executed": False, "error": "nothing_selected", "detail": "No item selected."}
    rows = _rows_for(conn, account, [str(instance_id)])
    if not rows:
        return {"executed": False, "error": "unknown_instance", "detail": "The item is not in the account snapshot."}
    row = rows[0]
    qty = int(row.get("qty") or 0)
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    if qty < 2:
        return {"executed": False, "error": "not_stack", "detail": "This item is not stacked (quantity = 1)."}
    if amount < 1 or amount >= qty:
        return {"executed": False, "error": "bad_amount",
                "detail": "The quantity must be between 1 and %d." % (qty - 1)}
    if mode not in ("split", "to_backpack", "to_stash"):
        return {"executed": False, "error": "bad_mode", "detail": "Unknown split mode: %s" % mode}

    source = row.get("container") or ""
    if mode == "split" and source not in ("backpack", "safe_pocket", "quick_use"):
        return {"executed": False, "error": "bad_source", "detail": "Splitting from this container is not supported."}
    if mode == "to_backpack" and source not in ("stash", "overflow"):
        return {"executed": False, "error": "bad_source", "detail": "Moving to BACKPACK is only available from STASH/OVERFLOW."}
    if mode == "to_stash" and source not in ("backpack", "safe_pocket", "quick_use"):
        return {"executed": False, "error": "bad_source", "detail": "Moving to STASH is only available from BACKPACK/SAFE POCKET/QUICK USE."}

    payload = _payload(conn, account)
    dest_container = "backpack" if mode == "to_backpack" else ("stash" if mode == "to_stash" else source)
    split_target = ""
    move_body = None
    target_wrapper = ""

    if mode == "to_backpack":
        target_wrapper = target_wrapper_id or next(iter(_empty_wrappers(payload, "backpack")), "")
        if not target_wrapper:
            return {"executed": False, "error": "no_empty_target", "detail": "There is no empty cell in the BACKPACK."}
        if not _wrapper_is_empty(payload, "backpack", target_wrapper):
            return {"executed": False, "error": "bad_target", "detail": "The BACKPACK cell is not empty."}
        same_empties = _empty_wrappers(payload, source, exclude=row.get("wrapper_id") or "")
        split_target = split_wrapper_id or (same_empties[0] if same_empties else "")
        if split_target:
            if split_target not in same_empties:
                return {"executed": False, "error": "bad_split_wrapper",
                        "detail": "The split cell is not empty or does not belong to the same section."}
            move_body = {"item_ids": ["<new split instance>"], "source_wrapper_ids": [split_target],
                         "target_container": "backpack", "target_wrapper_id": target_wrapper}
        else:
            split_target = target_wrapper  # split مباشر للخانة الهدف (atomic)
    else:
        same_empties = _empty_wrappers(payload, source, exclude=row.get("wrapper_id") or "")
        split_target = split_wrapper_id or (same_empties[0] if same_empties else "")
        if not split_target or split_target not in same_empties:
            return {"executed": False, "error": "no_empty_split",
                    "detail": "No empty cell inside %s for the split." % source.upper()}
        if mode == "to_stash":
            target_wrapper = ""
            move_body = {"item_ids": ["<new split instance>"], "source_wrapper_ids": [split_target],
                         "target_container": "stash", "target_wrapper_id": None}

    split_body = writer.build_mutate("split", [row], split_target, "", amount)
    preview = _split_preview(row, split_target, amount, split_body, move_body)
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account", "detail": "Pick one account.", "preview": preview}

    outcome1 = writer.execute("mutate", split_body, acc_id, action="split")
    if not outcome1.get("ok"):
        store.log_action(conn, account, "split:%s" % mode, split_body,
                         outcome1.get("error", "blocked"), outcome1.get("detail"), 1)
        return {"executed": False, "error": outcome1.get("error"), "detail": outcome1.get("detail"),
                "result": outcome1, "preview": preview}

    refreshed = sync.pull_account(conn, account, acc_id, with_assets=False)
    steps = [{"action": "split", "status": "executed", "target_wrapper_id": split_target}]
    if not move_body:
        store.log_action(conn, account, "split:%s" % mode, split_body, "executed",
                         outcome1.get("response"), 1)
        return {"executed": True, "result": outcome1, "preview": preview, "steps": steps,
                "refreshed": refreshed}

    new_row = _find_split_result(conn, account, split_target, row.get("name"), amount)
    if not new_row:
        store.log_action(conn, account, "split:%s" % mode, split_body, "failed",
                         "split succeeded but the new stack was not found after sync", 1)
        return {"executed": False, "error": "split_unresolved",
                "detail": "The split succeeded but the new piece could not be identified after the sync.",
                "result": outcome1, "preview": preview, "steps": steps,
                "refreshed": refreshed, "partial": True}

    move_body = writer.build_move([new_row], dest_container, target_wrapper)
    outcome2 = writer.execute("move", move_body, acc_id)
    store.log_action(conn, account, "split:%s" % mode, split_body, "executed",
                     outcome1.get("response"), 1)
    store.log_action(conn, account, "move:%s" % dest_container, move_body,
                     "executed" if outcome2.get("ok") else outcome2.get("error", "failed"),
                     outcome2.get("response") or outcome2.get("detail"), 1)
    refreshed = sync.pull_account(conn, account, acc_id, with_assets=False)
    steps.append({"action": "move", "status": "executed" if outcome2.get("ok") else "failed",
                  "target_container": dest_container, "target_wrapper_id": target_wrapper or None,
                  "instance_id": new_row.get("instance_id")})
    return {"executed": bool(outcome2.get("ok")), "result": outcome2,
            "error": None if outcome2.get("ok") else outcome2.get("error"),
            "detail": None if outcome2.get("ok") else outcome2.get("detail"),
            "preview": preview, "steps": steps, "refreshed": refreshed}


def clear_backpack(conn, account, scope="backpack"):
    """CLEAR: يرجّع محتوى الشنطة للستاش أولاً وأي فايض يروح Overflow — المنبع بيعمل التوزيع في طلب واحد.

    scope="all" = CLEAR ALL: التجهيز كله (أسلحة/درع/كويك يوز/سيف بوكيت/أوجمنت) + الشنطة.
    """
    if config.DATA_SOURCE == "pioneer":
        if account == "ALL":
            return {"executed": False, "error": "pick_account", "detail": "Pick one account before executing."}
        try:
            rows = pioneer_write.backpack_items(account)
            if scope == "all":
                rows = pioneer_write.equipped_items(account) + rows
        except pc.TokenExpired as exc:
            return {"executed": False, "error": "token_expired", "code": 401, "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"executed": False, "error": "gateway_error", "code": 502,
                    "detail": str(exc)[:300]}
        if not rows:
            return {"executed": True, "result": {"ok": True}, "moved": [],
                    "note": "The backpack is already empty." if scope != "all" else "The loadout and the backpack are already empty."}
        out = pioneer_write.move(conn, account, "stash", rows)
        if out.get("executed"):
            out["note"] = ("Returned %d items from the loadout and the backpack to the stash through the game gateway." % len(rows)
                           if scope == "all" else
                           "Returned %d items from the backpack to the stash through the game gateway." % len(rows))
        return out
    blocked = _direct_block("clear_backpack")
    if blocked:
        return blocked
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account", "detail": "Pick one account."}
    preview = {"method": "POST", "url": config.UPSTREAM_API + writer.MOVE_ALL_TO_OVERFLOW, "body": None}
    outcome = writer.execute("overflow_all", None, acc_id)
    out = _finish(conn, account, "move_all_to_overflow", preview, outcome, 0)
    out["preview"] = preview
    if out.get("executed"):
        out["note"] = "Returned the backpack contents to the stash, and the overflow to Overflow."
    return out


def pending(conn, limit=30, account=""):
    return store.action_log(conn, limit, account)


# ------------------------------------------------------------------ ماركس محلية
def marks(conn, account):
    return {"account": account, "marks": store.list_marks(conn, account), "palette": list(MARK_COLORS)}


def mark_add(conn, account, instance_ids, color):
    if color not in MARK_COLORS:
        return {"ok": False, "error": "bad_color", "detail": "Unknown color — pick one from the eight-color palette."}
    ids = [str(i) for i in (instance_ids or []) if i]
    if not ids:
        return {"ok": False, "error": "nothing_selected", "detail": "No items selected."}
    if account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account."}
    known = {r["instance_id"] for r in _rows_for(conn, account, ids)}
    ids = [i for i in ids if i in known]
    if not ids:
        return {"ok": False, "error": "unknown_instance", "detail": "The items are not in the account snapshot."}
    added = store.add_marks(conn, account, ids, color)
    return {"ok": True, "added": added, "color": color,
            "marks": store.list_marks(conn, account), "palette": list(MARK_COLORS)}


def mark_remove(conn, account, instance_ids=None, mark_ids=None, color=None):
    if account == "ALL":
        return {"ok": False, "error": "pick_account", "detail": "Pick one account."}
    removed = store.delete_marks(conn, account, instance_ids=instance_ids, mark_ids=mark_ids, color=color)
    return {"ok": True, "removed": removed, "marks": store.list_marks(conn, account), "palette": list(MARK_COLORS)}


# ------------------------------------------------------------------ المرفقات
def _payload(conn, account):
    payload, _ = store.read_snapshot(conn, account)
    return payload or {}


def _attachment_public(slot):
    return {
        "instance_id": slot.get("instanceId") or slot.get("instance_id"),
        "wrapper_id": slot.get("wrapperId") or slot.get("wrapper_id"),
        "slot_name": slot.get("slot_name"),
        "slot_label": gearops.slot_label(slot.get("slot_name")),
        "slot_asset_id": str(slot.get("slot_asset_id")) if slot.get("slot_asset_id") is not None else None,
        "asset_id": str(slot.get("asset_id")) if slot.get("asset_id") is not None else None,
        "display_name": slot.get("display_name") or slot.get("name") or "Empty Slot",
        "rarity": slot.get("rarity"),
        "image_filename": slot.get("image_filename") or slot.get("image") or "",
        "level": slot.get("level"),
        "type": slot.get("type"),
        "is_stencil": gearops.is_stencil(slot),
        "is_empty": bool(slot.get("is_empty", not slot.get("asset_id"))),
    }


def _stencils(row):
    """Stencils المرفقة بالسلاح: لون تجميلي بيتعرض بس ومش بينفك."""
    return [_attachment_public(a) for a in gearops.parse_attachments(row) if gearops.is_stencil(a)]


def _weapon_card(row):
    slots = [_attachment_public(a) for a in gearops.parse_attachments(row) if not gearops.is_stencil(a)]
    level = gearops.level_of(row)
    return {
        "instance_id": row.get("instance_id"), "name": row.get("name"),
        "display_name": row.get("name"), "type": row.get("type"),
        "rarity": row.get("rarity"), "image": row.get("image"),
        "image_filename": row.get("image"), "level": level, "level_label": gearops.roman(level),
        "health": gearops.health_of(row), "slots": slots,
        "stencils": _stencils(row),
        "equipped": sum(1 for s in slots if not s["is_empty"]), "total_slots": len(slots),
        "container": row.get("container"),
    }


def _rules_groups(weapons, inventory, rules):
    groups = gearops.manager_slots(weapons, inventory, rules)
    groups.sort(key=lambda g: (SLOT_ORDER.get(g.get("slot_name"), 99), g.get("label") or ""))
    return groups


def attachment_manager(conn, account, instance_ids=None):
    """لوحة MANAGE: أسلحة محددة + خاناتها + المتاح في المخزن (قراءة فقط)."""
    if account == "ALL":
        return {"error": "pick_account", "detail": "Pick one account."}
    rows = _rows_for(conn, account, instance_ids)
    for row in rows:
        catalog.decorate(row)
    weapons = [r for r in rows if gearops.is_weapon(r)]
    if not weapons:
        return {"error": "no_weapons", "detail": "No selected weapons can manage attachments."}
    rules = gearops.slot_rules()
    all_rows = _rows_for(conn, account)
    for row in all_rows:
        catalog.decorate(row)
    inventory = gearops.inventory_attachments(all_rows, rules)
    groups = _rules_groups(weapons, inventory, rules)
    cards = [_weapon_card(r) for r in weapons]
    return {
        "account": account, "weapons": cards, "groups": groups, "inventory": inventory,
        "counts": {
            "weapons": len(cards),
            "slots": sum(c["total_slots"] for c in cards),
            "empty": sum(c["total_slots"] - c["equipped"] for c in cards),
            "available": len(inventory),
        },
    }


def attachment_rules():
    return {"slots": [dict(rule, slot_asset_id=key) for key, rule in gearops.slot_rules().items()]}


def _paste_context(conn, account, weapon_ids):
    rows = _rows_for(conn, account, weapon_ids)
    for row in rows:
        catalog.decorate(row)
    weapons = [r for r in rows if gearops.is_weapon(r)]
    rules = gearops.slot_rules()
    all_rows = _rows_for(conn, account)
    for row in all_rows:
        catalog.decorate(row)
    inventory = gearops.inventory_attachments(all_rows, rules)
    return weapons, inventory, rules


def _slot_state(conn, account, weapon_ids):
    """حالة خانات مرفقات الأسلحة دي من آخر مزامنة: {wrapper: {weapon_id, attachment_id}}."""
    wanted = set(str(w) for w in (weapon_ids or []) if w)
    out = {}
    rows = _rows_for(conn, account, sorted(wanted) or None)
    for r in rows:
        if wanted and r["instance_id"] not in wanted:
            continue
        try:
            atts = json.loads(r.get("attachments") or "[]")
        except (TypeError, ValueError):
            atts = []
        for a in atts:
            if gearops.is_stencil(a):
                continue
            wrapper = str(a.get("wrapper_id") or a.get("wrapperId") or "")
            if not wrapper:
                continue
            out[wrapper] = {"weapon_id": r["instance_id"], "slot_name": a.get("slot_name"),
                            "slot_asset_id": str(a.get("slot_asset_id") or ""),
                            "attachment_id": None if a.get("is_empty") else str(a.get("instance_id") or "")}
    return out


def _installed_attachments(conn, account):
    """كل المرفقات المركّبة فعلياً: [{slot_wrapper_id, attachment_id, weapon_id}]

    الـ Stencil بيتشال من هنا: البوابة بترفض أمر فك فيه ستينسل، فوجوده في نفس
    الدفعة كان بيرجّع INVALID_ARGUMENT ويضيّع فك الملحقات الحقيقية كلها.
    """
    out = []
    for r in _rows_for(conn, account):
        try:
            atts = json.loads(r.get("attachments") or "[]")
        except (TypeError, ValueError):
            atts = []
        for a in atts:
            if a.get("is_empty") or gearops.is_stencil(a):
                continue
            wrapper = str(a.get("wrapper_id") or a.get("wrapperId") or "")
            instance = str(a.get("instance_id") or "")
            if wrapper and instance:
                out.append({"slot_wrapper_id": wrapper, "attachment_id": instance,
                            "weapon_id": r["instance_id"], "name": a.get("name")})
    return out


def _log_direct(conn, account, kind, body, out, count):
    store.log_action(conn, account, kind, body,
                     "executed" if out.get("executed") else out.get("error", "failed"),
                     out.get("detail") or out.get("result"), count)
    return out


def _direct_detach(conn, account, slot_wrapper_ids, target_container, kind):
    slot_wrapper_ids = set(str(s) for s in (slot_wrapper_ids or []) if s)
    batches = {}
    for item in _installed_attachments(conn, account):
        if not slot_wrapper_ids or item["slot_wrapper_id"] in slot_wrapper_ids:
            batches.setdefault(item["weapon_id"], []).append(item["attachment_id"])
    pick = [iid for batch in batches.values() for iid in batch]
    if not pick:
        return {"executed": False, "error": "nothing_installed",
                "detail": "No removable attachment is installed in the selected slots."}
    results = []
    for index, batch in enumerate(batches.values()):
        if index:
            time.sleep(0.8)
        out = pioneer_write.move_plan(conn, account, [
            {"target_container": target_container, "instance_ids": batch}])
        results.append(out)
        if not out.get("executed"):
            done = sum(int(r.get("items") or 0)
                       for r in results[:-1] if r.get("executed"))
            if done:
                out["detail"] = "%s %d attachments were moved before this batch failed." % (
                    out.get("detail") or "Detach stopped.", done)
                out["partial"] = True
            return out
    moved = sum(int(r.get("items") or 0) for r in results)
    return _log_direct(
        conn, account, kind, {"attachments": pick},
        {"executed": True, "items": moved,
         "batches": len(results), "results": results}, moved)


def _direct_attach(conn, account, ops, kind, replace_to="stash"):
    """تركيب المرفقات عبر البوابة الرسمية في طلب واحد.

    الخانة لازم تفضى الأول: لو فيها مرفق تاني بتفكه للوجهة المختارة (ستاش/أوفر
    ستاش) في طلب منفصل وبعدين بتركّ الجديد — نفس ما اللعبة بتعمل بالظبط.
    """
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account."}
    clean = []
    for op in ops or []:
        wrapper = str(op.get("slot_wrapper_id") or "")
        att = str(op.get("attachment_id") or "")
        if wrapper and att:
            clean.append({"slot_wrapper_id": wrapper, "attachment_id": att,
                          "weapon_id": str(op.get("weapon_id") or "")})
    if not clean:
        return {"executed": False, "error": "nothing_to_attach",
                "detail": "No attachment matches an empty slot."}
    if replace_to not in ("stash", "overflow"):
        replace_to = "stash"
    slots = _slot_state(conn, account, [o["weapon_id"] for o in clean])
    # "بياخد أتاتش إيه": البوابة بتقبل أي آيد في أي خانة، فالمطابقة بنفرضها هنا
    # بقواعد الخانات (attachment_slots.json) قبل ما نكتب أي حاجة.
    rules = gearops.slot_rules()
    asset_of = {r["instance_id"]: str(r.get("asset_id") or "")
                for r in _rows_for(conn, account, sorted({o["attachment_id"] for o in clean}))}
    usable = []
    for o in clean:
        slot = slots.get(o["slot_wrapper_id"]) or {}
        rule = rules.get(slot.get("slot_asset_id") or "")
        allowed = set((rule or {}).get("allowed_ids") or [])
        asset_id = asset_of.get(o["attachment_id"]) or ""
        if allowed and asset_id and asset_id not in allowed:
            continue
        usable.append(o)
    if not usable:
        return {"executed": False, "error": "incompatible",
                "detail": "These attachments do not match the selected slot types."}
    clean = usable
    occupied = [o for o in clean
                if (slots.get(o["slot_wrapper_id"]) or {}).get("attachment_id")
                and slots[o["slot_wrapper_id"]]["attachment_id"] != o["attachment_id"]]
    if occupied:
        removed = _direct_detach(conn, account, [o["slot_wrapper_id"] for o in occupied],
                                 replace_to, kind + ":replace")
        if not removed.get("executed"):
            return removed
    already = {o["slot_wrapper_id"] for o in clean
               if (slots.get(o["slot_wrapper_id"]) or {}).get("attachment_id") == o["attachment_id"]}
    wanted, seen = [], set()
    for o in clean:
        if o["slot_wrapper_id"] in already or o["slot_wrapper_id"] in seen:
            continue
        seen.add(o["slot_wrapper_id"])
        wanted.append({"target_container": "mod_slot", "target_wrapper_id": o["slot_wrapper_id"],
                       "instance_ids": [o["attachment_id"]]})
    if not wanted:
        return {"executed": False, "error": "already_there",
                "detail": "These attachments are already installed in those slots."}
    out = pioneer_write.move_plan(conn, account, wanted)
    return _log_direct(conn, account, kind, {"slots": len(wanted)}, out, len(wanted))


def paste_plan(conn, account, weapon_ids, setup):
    if account == "ALL":
        return {"error": "pick_account", "detail": "Pick one account."}
    weapons, inventory, rules = _paste_context(conn, account, weapon_ids)
    if not weapons:
        return {"error": "no_weapons", "detail": "No weapons selected."}
    plan = gearops.plan_paste(weapons, setup or {}, inventory, rules)
    return {"account": account, "weapons": [w.get("name") for w in weapons], **plan}


def paste(conn, account, weapon_ids, setup, confirmed=False):
    plan = paste_plan(conn, account, weapon_ids, setup)
    if config.DATA_SOURCE == "pioneer":
        if plan.get("error"):
            return {"executed": False, **plan}
        if not plan["operations"]:
            return {"executed": False, "error": "nothing_to_paste",
                    "detail": "No matching attachments in the stash for the copied setup.", "plan": plan}
        return _direct_attach(conn, account, plan["operations"], "attachments:paste")
    blocked = _direct_block("attachments")
    if blocked:
        return blocked
    if not plan["operations"]:
        return {"executed": False, "error": "nothing_to_paste",
                "detail": "No matching attachments in the stash for the copied setup.", "plan": plan}
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account", "plan": plan}
    body = {"operations": plan["operations"]}
    outcome = writer.execute("batch_attach", body, acc_id)
    out = _finish(conn, account, "attachments:paste", body, outcome, plan["matchedCount"])
    out["preview"] = {"method": "POST", "url": config.UPSTREAM_API + writer.BATCH_ATTACH, "body": body,
                      "plan": plan}
    out["plan"] = plan
    return out


def autofill(conn, account, weapon_ids, confirmed=False):
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account."}
    weapons, inventory, rules = _paste_context(conn, account, weapon_ids)
    if not weapons:
        return {"executed": False, "error": "no_weapons", "detail": "No weapons selected."}
    plan = gearops.plan_auto_fill(weapons, inventory, rules)
    if config.DATA_SOURCE == "pioneer":
        if not plan["operations"]:
            return {"executed": False, "error": "nothing_to_fill",
                    "detail": "No available attachments fit the empty slots.", "plan": plan}
        out = _direct_attach(conn, account, plan["operations"], "attachments:autofill")
        out["plan"] = plan
        return out
    blocked = _direct_block("attachments")
    if blocked:
        return blocked
    if not plan["operations"]:
        return {"executed": False, "error": "nothing_to_fill",
                "detail": "No available attachments fit the empty slots.", "plan": plan}
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account", "plan": plan}
    body = {"operations": plan["operations"]}
    outcome = writer.execute("batch_attach", body, acc_id)
    out = _finish(conn, account, "attachments:autofill", body, outcome, plan["filled"])
    out["preview"] = {"method": "POST", "url": config.UPSTREAM_API + writer.BATCH_ATTACH, "body": body,
                      "plan": plan}
    out["plan"] = plan
    return out


def attach_one(conn, account, weapon_id, slot_wrapper_id, attachment_id, source_wrapper_id=None,
               target_container="stash"):
    if not (weapon_id and slot_wrapper_id and attachment_id):
        return {"executed": False, "error": "bad_request",
                "detail": "weapon_id, slot_wrapper_id and attachment_id are required."}
    if config.DATA_SOURCE == "pioneer":
        return _direct_attach(conn, account, [{
            "weapon_id": weapon_id, "slot_wrapper_id": slot_wrapper_id,
            "attachment_id": attachment_id}], "attachments:attach", target_container)
    blocked = _direct_block("attachments")
    if blocked:
        return blocked
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account"}
    body = {"weapon_id": weapon_id, "slot_wrapper_id": slot_wrapper_id,
            "attachment_id": attachment_id, "source_wrapper_id": source_wrapper_id or None}
    outcome = writer.execute("attach", body, acc_id)
    out = _finish(conn, account, "attachments:attach", body, outcome, 1)
    out["preview"] = {"method": "POST", "url": config.UPSTREAM_API + writer.ATTACH, "body": body}
    return out


def detach(conn, account, weapon_ids, slot_wrapper_ids=None, target_container="stash", confirmed=False):
    weapon_ids = [str(w) for w in (weapon_ids or []) if w]
    if not weapon_ids:
        return {"executed": False, "error": "nothing_selected", "detail": "No weapons selected."}
    if target_container not in ATTACH_TARGETS:
        return {"executed": False, "error": "bad_target",
                "detail": "The detach destination must be stash or overflow."}
    slot_wrapper_ids = [str(s) for s in (slot_wrapper_ids or []) if s]
    if config.DATA_SOURCE == "pioneer":
        removable = set(_slot_state(conn, account, weapon_ids))
        slots = slot_wrapper_ids or list(removable)
        # الستينسل لون مش مرفق: لو رقم خانته اتطلب، البوابة هترفض الدفعة كلها.
        slots = [s for s in slots if s in removable]
        return _direct_detach(conn, account, slots, target_container, "attachments:detach")
    blocked = _direct_block("attachments")
    if blocked:
        return blocked
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account"}
    body = {"weapon_ids": weapon_ids, "target_container": target_container}
    if slot_wrapper_ids:
        body["slot_wrapper_ids"] = slot_wrapper_ids
    outcome = writer.execute("detach", body, acc_id)
    out = _finish(conn, account, "attachments:detach", body, outcome, len(weapon_ids))
    out["preview"] = {"method": "POST", "url": config.UPSTREAM_API + writer.DETACH, "body": body}
    return out


# ------------------------------------------------------------------ خطط الترقية/الإصلاح/التفكيك/البيع
def plan(conn, account, kind, instance_ids=None, targets=None):
    if account == "ALL":
        return {"error": "pick_account", "detail": "Pick one account.", "kind": kind}
    # بدون تحديد صريح ممنوع — otherwise an empty list means "every item in the account".
    if not instance_ids:
        return {"error": "nothing_selected", "detail": "No items selected.", "kind": kind}
    rows = _rows_for(conn, account, instance_ids)
    if not rows:
        return {"error": "nothing_selected", "detail": "No matching items.", "kind": kind}
    for row in rows:
        catalog.decorate(row)
    payload = _payload(conn, account)
    if config.DATA_SOURCE == "pioneer" and kind in ("recycle", "repair", "sell"):
        # البوابة نفسها هي اللي بتقرر — مفيش بوابة تانية بتدي recycle_info/repair_cost،
        # فلو اعتمدنا على الخطة التقليدية كان هيرفض كل حاجة رغم إن المنبع شغال.
        return {"account": account, "kind": kind, "count": len(rows), "direct": True,
                **gearops.direct_plan(kind, rows, payload)}
    if kind == "upgrade":
        rows = [r for r in rows if gearops.is_weapon(r)]
        if not rows:
            return {"error": "no_weapons", "detail": "No upgradable weapons.", "kind": kind}
        if config.DATA_SOURCE == "pioneer":
            # في الوضع المباشر الدرجة من الـ asset id نفسه (أدق من الاسم المخزّن).
            patched = []
            for r in rows:
                row = dict(r)
                tier = weapon_tiers.level_of_asset(r.get("asset_id"))
                if tier:
                    row["quality_level"] = tier - 1
                patched.append(row)
            rows = patched
        data = gearops.upgrade_plan(rows, payload, targets or {})
    elif kind == "repair":
        data = gearops.repair_plan(rows, payload)
    elif kind == "recycle":
        data = gearops.recycle_plan(rows, payload)
    elif kind == "sell":
        data = gearops.sell_plan(rows)
    else:
        return {"error": "bad_kind", "detail": "Unknown plan kind: %s" % kind, "kind": kind}
    return {"account": account, "kind": kind, "count": len(rows), **data}


def _mutation_flow(conn, account, kind, action, rows, plan_data, confirmed, total=None):
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account."}
    if not rows:
        return {"executed": False, "error": "nothing_selected", "detail": "No matching items."}
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account"}
    body = writer.build_mutate(action, rows)
    preview = {"method": "POST", "url": config.UPSTREAM_API + writer.BATCH_MUTATE, "body": body,
               "items": plan_data.get("items") or [], "materials": plan_data.get("materials") or [],
               "total": total if total is not None else plan_data.get("total")}
    outcome = writer.execute("mutate", body, acc_id, action=action, confirmed=confirmed)
    out = _finish(conn, account, "%s:%s" % (kind, action), body, outcome, len(rows))
    out["preview"] = preview
    out["kind"] = kind
    out["plan"] = plan_data
    return out


def upgrade(conn, account, instance_ids, targets=None, confirmed=False):
    if config.DATA_SOURCE == "pioneer":
        return _pioneer_upgrade(conn, account, instance_ids, targets or {}, confirmed)
    blocked = _direct_block("upgrade")
    if blocked:
        return blocked
    built = plan(conn, account, "upgrade", instance_ids, targets)
    if built.get("error"):
        return {"executed": False, **built}
    steps = []
    for item in built["items"]:
        for level in range(item["current"] + 1, item["target"] + 1):
            steps.append({"instance_id": item["instance_id"], "target_level": level,
                          "name": item["name"], "from": gearops.roman(level - 1),
                          "to": gearops.roman(level)})
    preview = {"method": "POST", "url": config.UPSTREAM_API + writer.UPGRADE,
               "steps": steps, "materials": built["materials"]}
    if not steps:
        return {"executed": False, "error": "max_level",
                "detail": "All selected weapons already reached the maximum level (IV).", "preview": preview, "plan": built}
    if not built["can_upgrade"]:
        return {"executed": False, "error": "insufficient_materials",
                "detail": "Materials are not enough — check the requirements list.", "preview": preview, "plan": built}
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "preview": preview, "plan": built}
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account", "preview": preview, "plan": built}
    if not confirmed:
        return {"executed": False, "error": "confirmation_required",
                "detail": "The upgrade must be confirmed from the dedicated UPGRADE window.", "preview": preview, "plan": built}

    current_ids = {item["instance_id"]: item["instance_id"] for item in built["items"]}
    results, done, first_error = [], 0, None
    for step in steps:
        body = {"instance_id": current_ids.get(step["instance_id"], step["instance_id"]),
                "target_level": step["target_level"]}
        outcome = writer.execute("upgrade", body, acc_id, action="upgrade", confirmed=True)
        results.append({"step": step, "ok": bool(outcome.get("ok")), "code": outcome.get("code"),
                        "error": outcome.get("error"), "detail": outcome.get("detail")})
        if not outcome.get("ok"):
            first_error = outcome
            break
        response = outcome.get("response") or {}
        if response.get("instance_id"):
            current_ids[step["instance_id"]] = response["instance_id"]
        done += 1
        if done < len(steps):
            time.sleep(0.45)

    status = "executed" if done == len(steps) else ("partial" if done else (first_error or {}).get("error", "failed"))
    store.log_action(conn, account, "upgrade", {"steps": steps, "materials": built["materials"]},
                     status, {"done": done, "total": len(steps), "results": results}, len(built["items"]))
    refreshed = None
    if done:
        refreshed = sync.pull_account(conn, account, acc_id, with_assets=False)
    out = {"executed": done > 0, "done": done, "total": len(steps), "steps": results,
           "preview": preview, "plan": built, "refreshed": refreshed}
    if first_error:
        out["error"] = first_error.get("error")
        out["detail"] = first_error.get("detail")
        out["result"] = first_error
    return out


def _pioneer_upgrade(conn, account, instance_ids, targets, confirmed):
    """ترقية الأسلحة على بوابة Embark الرسمية.

    البوابة بترفع درجة واحدة في كل نداء على /v1/pioneer/inventory/upgrade،
    فبناديها لحد ما نوصل للفل المطلوب (4) من غير ما نطلب تأكيد لكل درجة.
    جدول المواد المحلي تقريبي، والبوابة هي المرجع الأخير — فمبنمنعش التنفيذ
    على أساسه."""
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account."}
    ids = [str(i) for i in (instance_ids or []) if i]
    if not ids:
        return {"executed": False, "error": "nothing_selected", "detail": "No weapons selected."}
    built = plan(conn, account, "upgrade", ids, targets)
    if built.get("error"):
        return {"executed": False, **built}
    if not confirmed:
        return {"executed": False, "error": "confirmation_required",
                "detail": "The upgrade must be confirmed from the UPGRADE window.", "plan": built}
    results, done, failed = [], 0, None
    for iid in ids:
        target = int((targets or {}).get(iid) or 4)
        target = min(4, max(2, target))
        out = pioneer_write.upgrade_item(conn, account, iid, target)
        results.append(out)
        if out.get("executed"):
            done += 1
        elif failed is None:
            failed = out
    status = "executed" if done == len(ids) else ("partial" if done else "failed")
    store.log_action(conn, account, "upgrade",
                     {"ids": ids, "targets": targets},
                     status, {"done": done, "total": len(ids),
                              "levels": [(r.get("current"), r.get("target")) for r in results]},
                     len(ids))
    out = {"executed": done > 0, "done": done, "total": len(ids), "results": results,
           "plan": built, "kind": "upgrade"}
    if failed:
        out["error"] = failed.get("error")
        out["detail"] = failed.get("detail")
    return out


def _pioneer_mutation(conn, account, kind, instance_ids, confirmed):
    """recycle/scrap/repair على بوابة اللعبة نفسها.

    مفيش تراجع بعد التنفيذ — فالـ confirmed ده مش شكل، الواجهة بتبعتاه بعد ما
    المستخدم يضغط الزرار نفسه في كليك يمين."""
    if not confirmed:
        return {"executed": False, "error": "confirm_required", "kind": kind,
                "detail": "This action is final and cannot be undone — explicit confirmation required."}
    return pioneer_write.direct_mutate(conn, account, kind, instance_ids)


def recycle(conn, account, instance_ids, confirmed=False):
    if config.DATA_SOURCE == "pioneer":
        return _pioneer_mutation(conn, account, "recycle", instance_ids, confirmed)
    blocked = _direct_block("recycle")
    if blocked:
        return blocked
    built = plan(conn, account, "recycle", instance_ids)
    if built.get("error"):
        return {"executed": False, **built}
    keep = {i["instance_id"] for i in built["items"]}
    rows = [r for r in _rows_for(conn, account, instance_ids) if r["instance_id"] in keep]
    if not rows:
        return {"executed": False, "error": "not_recyclable",
                "detail": "None of the selected items has recycle_info.", "plan": built}
    return _mutation_flow(conn, account, "recycle", "recycle", rows, built, confirmed)


def sell(conn, account, instance_ids, confirmed=False):
    if config.DATA_SOURCE == "pioneer":
        # مفيش عملية "sell" في البوابة — الإعدام (scrap) هو اللي بيرجّع كرديت،
        # وده اللي بيحصل بالظبط لما تبيع للتاجر جوه اللعبة.
        return _pioneer_mutation(conn, account, "scrap", instance_ids, confirmed)
    blocked = _direct_block("sell")
    if blocked:
        return blocked
    built = plan(conn, account, "sell", instance_ids)
    if built.get("error"):
        return {"executed": False, **built}
    rows = _rows_for(conn, account, instance_ids)
    if not rows:
        return {"executed": False, "error": "nothing_selected", "plan": built}
    return _mutation_flow(conn, account, "sell", "scrap", rows, built, confirmed, total=built.get("total"))


def repair(conn, account, instance_ids, confirmed=False):
    if config.DATA_SOURCE == "pioneer":
        return _pioneer_mutation(conn, account, "repair", instance_ids, confirmed)
    blocked = _direct_block("repair")
    if blocked:
        return blocked
    built = plan(conn, account, "repair", instance_ids)
    if built.get("error"):
        return {"executed": False, **built}
    keep = {i["instance_id"] for i in built["items"]}
    rows = [r for r in _rows_for(conn, account, instance_ids) if r["instance_id"] in keep]
    if not rows:
        return {"executed": False, "error": "nothing_to_repair",
                "detail": "No damaged items have a repair cost.", "plan": built}
    return _mutation_flow(conn, account, "repair", "repair", rows, built, confirmed)


def delete(conn, account, instance_ids, confirmed=False):
    """الحذف المباشر: بنبعت discriminator=delete للمنبع ونردّ رفضه حرفياً لو رفض.

    مقيس لايف: عناصر الستاش بترجع INVENTORY_ITEM_DELETE_FORBIDDEN أو INVALID_ARGUMENT،
    فالزرار ده مش مقفول من ناحيتنا — القرار قرار المنبع نفسه."""
    if config.DATA_SOURCE == "pioneer":
        return _pioneer_mutation(conn, account, "delete", instance_ids, confirmed)
    return {"executed": False, "error": "direct_read_only", "kind": "delete",
            "detail": DIRECT_BLOCK_DETAIL}


def split(conn, account, instance_id, target_wrapper="", amount=1, confirmed=False):
    """تقسيم حقيقي على بوابة اللعبة: على batch-operation بأمر moveAmount واحد يفصل
    الكمية وينزلها في الخانة الفاضية، وعلى مسار mutate القديم بـ update + create.

    بينقص لحد سقف الرصة بالظبط زي اللعبة، ولو مالقاش خانة فاضية بيرفض نصاً.
    للتراجع: ادمج الرصتين تاني بزرار COMBINE.
    """
    if config.DATA_SOURCE == "pioneer":
        if not confirmed:
            return {"executed": False, "error": "confirm_required", "kind": "split",
                    "detail": "This writes to the live source — explicit confirmation required."}
        rows = _rows_for(conn, account, [str(instance_id)])
        aid = str((rows[0].get("asset_id") if rows else "") or "")
        return pioneer_write.split_attempt(conn, account, instance_id, target_wrapper, amount,
                                           cap=_stack_cap(conn, account, aid))
    return split_stack(conn, account, instance_id, amount,
                       split_wrapper_id=target_wrapper, target_wrapper_id=target_wrapper)


def combine(conn, account, instance_id, target_instance_id, amount=None, confirmed=False):
    """دمج رصتين من نفس النوع على المسار الرسمي: على batch بأمر moveAmount لخانة
    الوجهة، وعلى مسار mutate القديم بـ update للهدف + تجهيز المصدر.

    السحب على الوجهة بيملاها للحد الأقصى والفضل يفضل في مكانه (نفس سلوك اللعبة) — الحالتين
    متقيستين لايف 2026-10-31، والمجمول بيفضل ثابت. لو المصدر اتفضى بالكامل بيتشال وده
    رجوعه مفيش ليه مسار رسمي (out["undone"]=False).
    """
    if config.DATA_SOURCE != "pioneer":
        return {"executed": False, "error": "direct_read_only", "kind": "combine",
                "detail": DIRECT_BLOCK_DETAIL}
    if not confirmed:
        return {"executed": False, "error": "confirm_required", "kind": "combine",
                "detail": "This writes to the live source — explicit confirmation required."}
    rows = _rows_for(conn, account, [instance_id, target_instance_id])
    aid = str((rows[0].get("asset_id") if rows else "") or "")
    return pioneer_write.combine_attempt(conn, account, instance_id, target_instance_id,
                                         amount=amount, cap=_stack_cap(conn, account, aid))


def swap(conn, account, instance_id, target_instance_id, confirmed=False):
    """تبديل مكان قطعتين على البوابة الرسمية — من غير أي تغيير في الكمية أو المتانة."""
    if config.DATA_SOURCE != "pioneer":
        return {"executed": False, "error": "direct_read_only", "kind": "swap",
                "detail": DIRECT_BLOCK_DETAIL}
    if not confirmed:
        return {"executed": False, "error": "confirm_required", "kind": "swap",
                "detail": "This writes to the live source — explicit confirmation required."}
    return pioneer_write.swap_items(conn, account, instance_id, target_instance_id)


# ------------------------------------------------------------------ كمية بالضبط للشنطة
def fill_takes(stacks, want, cap=0):
    """الخطة اللي توصلّل الرقم بالضبط: رصّات كاملة الأول، والفاضل ينفصل من أقرب رصة أكبر.

    بترجّع [{"instance_id", "amount", "partial"}] أو None لو المتاح كله أقل من الرقم.
    السقف بيقسّم الفاضل chunks ما بتعديش حجم الأكوم، فالشنطة تستقبل رصّتين زي اللعبة
    بالظبط (15 + 2 للرقم 17) بدل ما ترفض قطعة أكبر من الحد.
    """
    pool = [{"instance_id": str(s.get("instance_id") or ""), "amount": int(s.get("amount") or 0)}
            for s in (stacks or []) if str(s.get("instance_id") or "")]
    pool = [s for s in pool if s["amount"] > 0]
    left = int(want or 0)
    if left < 1 or not pool or sum(s["amount"] for s in pool) < left:
        return None
    pool.sort(key=lambda s: (-s["amount"], s["instance_id"]))
    takes = []
    for s in pool:
        if left <= 0:
            break
        if s["amount"] <= left:
            takes.append({"instance_id": s["instance_id"], "amount": s["amount"], "partial": False})
            left -= s["amount"]
            s["amount"] = 0     # الرصة اتنقلت كلها: مابقاش فيها حاجة تتفصل
    while left > 0:
        chunk = min(left, cap) if cap and cap > 1 else left
        # أقرب رصة للقطعة المطلوبة: بنفضّي أصغر رصة ممكنة عشان الكبيرة تفضل سليمة
        cands = [s for s in pool if s["amount"] > chunk]
        if not cands:
            return None
        s = min(cands, key=lambda x: (x["amount"], x["instance_id"]))
        takes.append({"instance_id": s["instance_id"], "amount": chunk, "partial": True})
        s["amount"] -= chunk
        left -= chunk
    return takes


def _merge_undo(dst, cells):
    """حالة الخانات الأصلية من خطوات كتابة كتير: أول قراية لكل خانة هي الصح."""
    for cell, kids in (cells or {}).items():
        dst.setdefault(cell, kids)
    return dst


def _merge_backpack(conn, account, asset_id, cap, keep_id="", max_rounds=8):
    """يجمع قطع النوع الواحد اللي في الشنطة في كومة واحدة على البوابة.

    السحب بيفصل القطع في خانات ورا بعضها (الرصّات الكاملة الأول والقطعة المفصولة
    بعدها)، فلو الطلب 2 بيوصلوا قطعتين 1 + 1. الدمج الحقيقي مفتوح على مسار
    batch-operation (moveAmount لمعرّف كومة موجودة) — نفس اللي في زر MERGE —
    فبنستخدمه على اللي وصل للشنطة بدل ما نستنى اللعبة تلمّها.

    بيرجّع {"merged": عدد الدمجات الناجحة, "id": معرّف الكومة النهائية,
            "amount": كميتها, "detail": آخر رسالة} — ومابيرميش استثناء أبداً:
    فشل الدمج مش فشل للسحبة، القطع موجودة بس في خانات منفصلة.
    """
    merged, last_id, last_amount, detail = 0, "", 0, ""
    aid = str(asset_id or "")
    for _ in range(max(1, int(max_rounds))):
        try:
            data = pc.fetch_inventory_for(account) or {}
            tree = pioneer_tree.Tree(data.get("items") or [])
            lay = pioneer_tree.layout(tree)
        except Exception:
            break
        bag_cells = set(str(s.get("wrapper") if isinstance(s, dict) else s)
                        for s in lay["backpack"]["slots"])
        piles = []
        for iid, node in tree.by_id.items():
            if str(node.get("gameAssetId")) != aid or node.get("slots"):
                continue
            if tree.parent.get(iid, "") not in bag_cells:
                continue
            piles.append({"id": iid, "amount": int(node.get("amount") or 0)})
        piles = [p for p in piles if p["amount"] > 0]
        if len(piles) < 2:
            if piles:
                last_id, last_amount = piles[0]["id"], piles[0]["amount"]
            break
        piles.sort(key=lambda p: (-p["amount"], p["id"] != keep_id, p["id"]))
        tgt, src = piles[0], piles[1]
        take = src["amount"]
        if cap and cap > 1:
            take = min(take, int(cap) - tgt["amount"])
        if take < 1:
            # الكومة الكبيرة مليانة للسقف: الدمج التالي على أحدث كومة أقل من السقف.
            rest = [p for p in piles[1:] if not cap or p["amount"] < int(cap)]
            if len(rest) < 2:
                last_id, last_amount = tgt["id"], tgt["amount"]
                break
            rest.sort(key=lambda p: (-p["amount"], p["id"]))
            tgt, src = rest[0], rest[1]
            take = min(src["amount"], int(cap) - tgt["amount"]) if cap else src["amount"]
            if take < 1:
                last_id, last_amount = tgt["id"], tgt["amount"]
                break
        out = pioneer_write.combine_attempt(conn, account, src["id"], tgt["id"],
                                            amount=take, cap=cap)
        detail = out.get("detail") or ""
        if not out.get("executed"):
            break
        merged += 1
        last_id = tgt["id"]
        last_amount = int((out.get("after") or {}).get("target") or (tgt["amount"] + take))
    if not last_id:
        try:
            data = pc.fetch_inventory_for(account) or {}
            tree = pioneer_tree.Tree(data.get("items") or [])
            lay = pioneer_tree.layout(tree)
            bag_cells = set(str(s.get("wrapper") if isinstance(s, dict) else s)
                            for s in lay["backpack"]["slots"])
            best = [i for i, n in tree.by_id.items()
                    if str(n.get("gameAssetId")) == aid
                    and tree.parent.get(i, "") in bag_cells]
            if best:
                last_id = best[0]
                last_amount = int(tree.by_id[last_id].get("amount") or 0)
        except Exception:
            pass
    return {"merged": merged, "id": last_id, "amount": last_amount, "detail": detail}


def fill(conn, account, asset_id, want, target_wrapper="", confirmed=False):
    """يوصلّل الرقم المطلوب للشنطة بالضبط، ويفصل أي فاضل من رصة تانية لو لزم.

    الأرقام بتتقرا من الشجرة الحية مش من الكاش المحلي، والحركة بتتم بالترتيب ده:
      1) ينقل الرصّات الكاملة — ده اللي بيفضّي خانات في الستاش تحط فيها البوابة
         القطعة المفصولة (الستاش وهو مليان مابيسيبش مكان للرصة الجديدة).
      2) يفصل الفاضل من رصة أكبر منه.
      3) ينقل القطعة المفصولة للشنطة.
    كل خطوة كتابة متحقق منها وبتراجع نفسها لو فشلت، فالرفض بيرجع نص البوابة.
    """
    if config.DATA_SOURCE != "pioneer":
        return {"executed": False, "error": "direct_read_only", "kind": "fill",
                "detail": DIRECT_BLOCK_DETAIL}
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account first."}
    try:
        want = int(want)
    except (TypeError, ValueError):
        want = 0
    if want < 1:
        return {"executed": False, "error": "bad_amount", "kind": "fill",
                "detail": "Type a number in the QTY field first."}
    aid = str(asset_id or "")
    if not aid:
        return {"executed": False, "error": "nothing_selected", "kind": "fill",
                "detail": "Select one item type in the search first."}

    try:
        data = pc.fetch_inventory_for(account)
    except pc.TokenExpired as exc:
        return {"executed": False, "error": "token_expired", "kind": "fill", "detail": str(exc)}
    except pc.PioneerError as exc:
        return {"executed": False, "error": "gateway_error", "kind": "fill",
                "detail": str(exc)[:300]}
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    try:
        lay = pioneer_tree.layout(tree)
    except pioneer_tree.TreeError as exc:
        return {"executed": False, "error": exc.error, "kind": "fill", "detail": exc.detail}

    # المصادر: رصّات النوع ده في الستاش + الأوفر (من غير أب = عائمة في الأوفر).
    # رصة حقيقية = عنصر واحد بكمية أكبر من 1 ومفيش تحته حاجة بتتفصل.
    # القطع المستقلة (سلاح/شيلد/أوجمنت) كمية كل واحدة 1 وليها بنات (خانات
    # مرفقات/نص) — متجمعة بصرياً في STACKED بس، ومفيش فيها حاجة تتقسم: بناخد
    # أول N نسخة بالترتيب اللي وصل بيه السحب.
    stash_cells = set(lay["stash"]["slots"])
    bag_cells = set(str(s.get("wrapper") if isinstance(s, dict) else s)
                    for s in lay["backpack"]["slots"])
    stacks, pieces = [], []
    for iid, node in tree.by_id.items():
        if str(node.get("gameAssetId")) != aid:
            continue
        par = tree.parent.get(iid, "")
        if par and par not in stash_cells:
            # اللي في الشنطة أصلاً بنحسبه للرقم المتاح بس: الكمية المطلوبة بتتقاس
            # على اللي في الشنطة، وزيادة القطع كانت بتخلي الطلب 2 يجيب 3.
            continue
        qty = int(node.get("amount") or 0)
        if qty < 1:
            continue
        stack = qty > 1 and not node.get("slots")
        entry = {"instance_id": iid, "amount": qty,
                 "container": "stash" if par else "overflow",
                 "name": tree.name_of(iid)}
        (stacks if stack else pieces).append(entry)
    in_bag = 0
    for iid, node in tree.by_id.items():
        if str(node.get("gameAssetId")) == aid and tree.parent.get(iid, "") in bag_cells:
            in_bag += int(node.get("amount") or 0)
    if not stacks and not pieces and in_bag < want:
        return {"executed": False, "error": "not_in_stash", "kind": "fill",
                "detail": "This item is not in the stash or the overflow."}
    name = ((stacks or pieces)[0]["name"] or aid) if (stacks or pieces) else aid
    total = sum(s["amount"] for s in stacks) + sum(p["amount"] for p in pieces) + in_bag
    cap = _stack_cap(conn, account, aid)
    # رصة فيها قطعة واحدة (qty 1) مش رصة حقيقية: نقلها للشنطة بياخد slot كامل
    # والرقم المفروض جايب من القطع المستقلة أو من فصل رصة أكبر. لو حسبناها رصة
    # كانت بتتنقل مع الحاجة المفصولة والطلب 1 بيوصل 2.
    single = [s for s in stacks if s["amount"] <= 1]
    stacks = [s for s in stacks if s["amount"] > 1]
    # الرقم اللي بينزل للنقل = المطلوب ناقص اللي في الشنطة أصلاً.
    want_need = max(0, want - in_bag)
    # القطع المستقلة (كمية 1) بتاخد من الرقم أولاً — واحدة واحدة زي ما بتتعرض
    # في البطاقة. الباقي بس هو اللي بينزل للرصّات، فالطلب 2 مع قطعة مستقلة
    # واحدة بيسحب 1 من الرصة مش 2 (كان بيوصل 3).
    loose_picks, want_left = [], want_need
    for p in pieces:
        if want_left <= 0:
            break
        loose_picks.append(p)
        want_left -= p["amount"]
    takes = fill_takes(stacks, want_left, cap) or []
    short = want_need - sum(t["amount"] for t in takes) - sum(p["amount"] for p in loose_picks)
    if short > 0 and single:
        # رصّات الـ 1 مش مصادر فصل: chunk لازم يكون أصغر من الكومة (amount > chunk)
        # فبتتاخد هي نفسها كقطعة كاملة من أكبرها.
        single.sort(key=lambda s: (-s["amount"], s["instance_id"]))
        for s in single[:short]:
            takes.append({"instance_id": s["instance_id"], "amount": s["amount"], "partial": False})
    planned = sum(t["amount"] for t in takes) + sum(p["amount"] for p in loose_picks)
    plan = {"asset_id": aid, "name": name, "want": want, "available": total, "cap": cap,
            "in_backpack": in_bag, "takes": takes, "stacks": len(stacks),
            "pieces": len(loose_picks),
            "moves": len([t for t in takes if not t["partial"]]),
            "splits": len([t for t in takes if t["partial"]])}
    if planned + in_bag < want:
        return {"executed": False, "error": "not_enough", "kind": "fill", "plan": plan,
                "detail": "All you have of %s in the stash and overflow is %d — %d is impossible, "
                          "and no stack can be split." % (name, total, want)}
    if planned < 1 and in_bag >= want:
        return {"executed": False, "error": "already_in_backpack", "kind": "fill", "plan": plan,
                "detail": "The backpack already holds %d %s — nothing to move." % (in_bag, name)}
    if not confirmed:
        return {"executed": False, "error": "confirm_required", "kind": "fill", "plan": plan,
                "detail": "This writes to the live source — explicit confirmation required."}
    if pioneer_write.paused():
        return {"executed": False, "error": "write_paused", "code": 423, "kind": "fill",
                "plan": plan, "detail": pioneer_write.PAUSE_DETAIL}

    steps, undo_cells, delivered = [], {}, 0
    whole = [t for t in takes if not t["partial"]]
    if whole:
        # خانة محددة من السحبة ليها معنى لما القطعة واحدة بس؛ غير كده البوابة
        # بتوزّاع على الخانات الفاضية بنفسها.
        out = pioneer_write.move(conn, account, "backpack",
                                 [{"instance_id": t["instance_id"]} for t in whole],
                                 target_wrapper_id=target_wrapper if len(takes) == 1 else "")
        steps.append({"action": "move", "items": len(whole), "amount": sum(t["amount"] for t in whole),
                      "executed": bool(out.get("executed")), "error": out.get("error"),
                      "detail": out.get("detail")})
        if not out.get("executed"):
            return {"executed": False, "error": out.get("error") or "move_failed", "kind": "fill",
                    "detail": out.get("detail") or "The gateway did not answer the move.",
                    "plan": plan, "steps": steps, "refreshed": out.get("refreshed")}
        _merge_undo(undo_cells, (out.get("undo") or {}).get("cells"))
        delivered += sum(t["amount"] for t in whole)

    # القطع المستقلة: مفيش استدعاء split خالص — نفس اللي اتخصم من الرقم في
    # الخطة (loose_picks) بيتنقل مرة واحدة للشنطة.
    loose = 0
    if want_need - delivered > 0 and loose_picks:
        need = want_need - delivered
        picked = []
        for p in loose_picks:
            if need <= 0:
                break
            picked.append(p)
            need -= p["amount"]
        loose = len(picked)
        out = pioneer_write.move(conn, account, "backpack",
                                 [{"instance_id": p["instance_id"]} for p in picked],
                                 target_wrapper_id=target_wrapper if len(picked) == 1 else "")
        steps.append({"action": "move", "items": loose, "amount": loose,
                      "executed": bool(out.get("executed")), "error": out.get("error"),
                      "detail": out.get("detail")})
        if not out.get("executed"):
            return {"executed": delivered > 0, "error": out.get("error") or "move_failed",
                    "kind": "fill", "detail": out.get("detail") or "The gateway did not answer the move.",
                    "plan": plan, "steps": steps, "refreshed": out.get("refreshed")}
        _merge_undo(undo_cells, (out.get("undo") or {}).get("cells"))
        # خانة القطعة المستقلة بقت مشغولة فعلاً؛ القراية الجديدة هي اللي بتحكي
        # للخطة اللي بعدها إنها محجوزة، وإلا التقسيم بينزل فيها ويطرد القطعة.
        try:
            fresh = pc.fetch_inventory_for(account)
            tree = pioneer_tree.Tree((fresh or {}).get("items") or [])
            lay = pioneer_tree.layout(tree)
        except Exception:
            pass
        delivered += loose

    created, homed = [], []
    free_cells = []
    for slot in lay["backpack"]["slots"]:
        cell = str(slot.get("wrapper") if isinstance(slot, dict) else slot)
        if cell and not tree.first_child(cell):
            free_cells.append(cell)
    for t in takes:
        if not t["partial"]:
            continue
        # التقسيم هنا مش محتاج خانة في الستاش: القطعة بتطلع في الأوفر لحظة
        # فصلها، والخطوة اللي بعدها بتنقلها للشنطة على طول. قبل كده كان الموقع
        # بيرفض قبل ما يسأل البوابة ("A split needs a free cell") والستاش مليان
        # 280/280، فالرقم كان بيوصل ناقص (10 → 9).
        # لو فيه خانة فاضية في الشنطة، القطعة بتنزل فيها من نفس الطلب (setParents)
        # بدل ما تطلع عائمة في الأوفر وتحتاج حركة تانية.
        home = ""
        if target_wrapper and not tree.first_child(target_wrapper):
            home = target_wrapper
        elif free_cells:
            home = free_cells[0]
        sp = pioneer_write.split_attempt(conn, account, t["instance_id"], "", t["amount"],
                                         cap=cap, into_cell=False, dest_cell=home)
        steps.append({"action": "split", "instance_id": t["instance_id"], "amount": t["amount"],
                      "executed": bool(sp.get("executed")), "error": sp.get("error"),
                      "detail": sp.get("detail")})
        if not sp.get("executed"):
            return {"executed": delivered > 0, "error": sp.get("error") or "split_failed",
                    "kind": "fill", "partial": True, "delivered": delivered,
                    "detail": sp.get("detail") or "The split did not execute.",
                    "plan": plan, "steps": steps, "undo": {"cells": undo_cells},
                    "refreshed": sp.get("refreshed")}
        if not sp.get("created"):
            continue
        # القطعة اللي نزلت خانة الشنطة من نفس طلب التقسيم مش محتاجة حركة تانية.
        if sp.get("cell") and sp["cell"] in free_cells:
            free_cells = [c for c in free_cells if c != sp["cell"]]
            homed.append({"instance_id": sp["created"], "amount": t["amount"], "cell": sp["cell"]})
            delivered += t["amount"]
            continue
        created.append({"instance_id": sp["created"], "amount": t["amount"]})

    if created:
        # القطعة المفصولة مش مختارة من المستخدم بخانة معيّنة: الشنطة بتحطها في
        # الخانة اللي كانت فاضية وقت التقسيم، والخانة دي بتبقى مشغولة في القراية
        # الجديدة. fallback_if_full بيخلّي الخطة تاخد أول خانة فاضية فعلاً بدل
        # ما ترمي "The requested cell is occupied."
        out = pioneer_write.move(conn, account, "backpack",
                                 [{"instance_id": c["instance_id"]} for c in created],
                                 target_wrapper_id=target_wrapper if len(takes) == 1 and not homed else "",
                                 fallback_if_full=True)
        steps.append({"action": "move", "items": len(created),
                      "amount": sum(c["amount"] for c in created),
                      "executed": bool(out.get("executed")), "error": out.get("error"),
                      "detail": out.get("detail")})
        if not out.get("executed"):
            return {"executed": delivered > 0, "error": out.get("error") or "move_failed",
                    "kind": "fill", "partial": True, "delivered": delivered,
                    "detail": "The split piece was created but the move to the backpack stopped: %s"
                              % (out.get("detail") or out.get("error") or "The gateway did not answer"),
                    "plan": plan, "steps": steps, "undo": {"cells": undo_cells},
                    "refreshed": out.get("refreshed")}
        _merge_undo(undo_cells, (out.get("undo") or {}).get("cells"))
        delivered += sum(c["amount"] for c in created)

    total_in_bag = delivered + in_bag
    if total_in_bag < want:
        return {"executed": delivered > 0, "error": "not_enough", "kind": "fill",
                "partial": delivered > 0, "delivered": delivered, "plan": plan, "steps": steps,
                "undo": {"cells": undo_cells},
                "detail": "All you have of %s in the stash and overflow is %d — only %d went to the "
                          "backpack." % (name, total, total_in_bag)}

    parts = [str(t["amount"]) + ("*" if t["partial"] else "") for t in takes]
    if loose:
        parts += ["1"] * loose
    shape = " + ".join(parts) or "already there"
    # النقل بيسيب القطع كل واحدة في خانتها، فالطلب 2 بيطلّع 1 + 1. الدمـج الحقيقي
    # مساره مفتوح (moveAmount على رصة موجودة) فبنلمّهم في كومة واحدة بدل ما
    # نستنى اللعبة.
    merged = {"merged": 0, "id": "", "amount": 0}
    landed = len(takes) + loose + (1 if in_bag else 0)
    if cap >= 2 and (landed > 1 or in_bag > 1):
        merged = _merge_backpack(conn, account, aid, cap, keep_id=target_wrapper)
        if merged["merged"]:
            steps.append({"action": "merge", "merges": merged["merged"],
                          "amount": merged["amount"], "detail": merged.get("detail")})
    store.log_action(conn, account, "fill:backpack", {"asset_id": aid, "want": want,
                                                     "takes": takes, "pieces": loose,
                                                     "merges": merged["merged"]},
                     "executed", {"delivered": delivered, "in_backpack": in_bag},
                     len(takes) + loose + merged["merged"])
    stack_note = (", merged into one stack: %d" % merged["amount"]
                  if merged["merged"] else "")
    detail = "%d %s in the backpack (%s), %d moved in this run%s. * = split piece." % (
        total_in_bag, name, shape, delivered, stack_note)
    out = {"executed": True, "kind": "fill", "delivered": delivered,
           "already_in_backpack": in_bag, "plan": plan,
           "steps": steps, "pieces": shape, "undo": {"cells": undo_cells},
           "merge": merged, "detail": detail}
    if merged["merged"]:
        out["refreshed"] = None
    return out


# ------------------------------------------------------------------ مزامنة المنبع
def synchronize(conn, account):
    if config.DATA_SOURCE == "pioneer":
        if account == "ALL":
            return {"executed": False, "error": "pick_account", "detail": "Pick one account to sync."}
        pulled = sync.pull_account(conn, account, None, with_assets=False)
        store.log_action(conn, account, "sync:direct", {"source": "pioneer"},
                         "executed" if pulled.get("ok") else "failed",
                         pulled.get("error") or {"items": pulled.get("items")}, 0)
        return {"executed": bool(pulled.get("ok")), "result": {"ok": True, "mode": "pioneer"},
                "refreshed": pulled, "note": "Sync came straight from the game gateway — no data went through rampart."}
    if account == "ALL":
        return {"executed": False, "error": "pick_account", "detail": "Pick one account to sync."}
    acc_id = _account_id(conn, account)
    if not acc_id:
        return {"executed": False, "error": "pick_account", "detail": "This account is not linked on Rampart."}
    try:
        outcome = writer.sync_upstream(acc_id)
    except Exception as exc:
        outcome = {"ok": False, "code": 502, "error": "upstream_error", "detail": str(exc)[:300]}
    store.log_action(conn, account, "synchronize",
                     {"method": "POST", "url": config.UPSTREAM_API + writer.SYNC},
                     "executed" if outcome.get("ok") else outcome.get("error", "failed"),
                     outcome.get("response") or outcome.get("detail"), 0)
    pulled = None
    if outcome.get("ok"):
        pulled = sync.pull_account(conn, account, acc_id, with_assets=False)
        if pulled and pulled.get("ok"):
            store.set_meta(conn, "stats:%s" % account, pulled.get("stats") or {})
            conn.execute("UPDATE accounts SET last_sync=? WHERE id=?", (time.time(), acc_id))
            conn.commit()
    return {"executed": bool(outcome.get("ok")), "result": outcome, "refreshed": pulled}
