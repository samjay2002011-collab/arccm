"""قياس حقيقي: هل البوابة بتدمج ستاكين لنفس العنصر في خانة واحدة؟

السؤال اللي بيجاوبه السكربت ده: لو حطيت آيتم اتنين من نفس الـ gameAssetId في
نفس الخانة (slots=[A, B] وسبت المصدر فاضي) — البوابة تدمجهم، ترفض، ولا تسيب
البند يتيتّم؟ كل حركة بنرجّعها بالحالة الأصلية في نفس التشغيل.

    python -m inspection.probe_merge ELCONEJOMALO
"""
import sys

from backend import pioneer_client as pc, pioneer_tree, pioneer_write


def stacks(tree, lay):
    """خانات الستاش اللي فيها أكتر من ستاك لنفس الـ asset."""
    by_asset = {}
    for cell in lay["stash"]["slots"]:
        item = tree.first_child(cell)
        if not item:
            continue
        node = tree.by_id.get(str(item)) or {}
        if node.get("slots"):          # حاوية، مش ستاك
            continue
        by_asset.setdefault(str(node.get("gameAssetId")), []).append((cell, item))
    return {k: v for k, v in by_asset.items() if len(v) > 1}


def show(tree, pairs, tag):
    for wrapper, item in pairs:
        cell_kids = tree.kids.get(str(wrapper)) or []
        print("   %s cell=%s kids=%s | item=%s amount=%s parent=%s" %
              (tag, str(wrapper)[:8], [k[:8] for k in cell_kids], str(item)[:8],
               tree.by_id.get(str(item), {}).get("amount"),
               str(tree.parent.get(str(item)) or "")[:8]))


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "ELCONEJOMALO"
    data = pc.fetch_inventory_for(account)
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    lay = pioneer_tree.layout(tree)
    found = stacks(tree, lay)
    if not found:
        print("مفيش عنصر متكرر في الستاش — مفيش حاجة تدمجها.")
        return
    asset, pairs = sorted(found.items(), key=lambda kv: -len(kv[1]))[0]
    (cell_a, item_a), (cell_b, item_b) = pairs[0], pairs[1]
    print("asset %s (%s) | خانتان: %s/%s و %s/%s" %
          (asset, tree.label(item_a), str(cell_a)[:8], str(item_a)[:8],
           str(cell_b)[:8], str(item_b)[:8]))
    show(tree, pairs, "قبل")

    original = {str(cell_a): [str(item_a)], str(cell_b): [str(item_b)]}
    request = {"mutations": [
        {"discriminator": "update", "instanceId": str(cell_a),
         "slots": [str(item_a), str(item_b)], "amount": tree.amount(cell_a)},
        {"discriminator": "update", "instanceId": str(cell_b),
         "slots": [""], "amount": tree.amount(cell_b)},
    ], "requestId": ""}
    print("الطلب:", request["mutations"])
    token = pc.account_token(account)
    try:
        resp = pc.post_json(pioneer_write._url(), request, token=token)
    except Exception as exc:
        print("⛔ البوابة رفضت:", str(exc)[:300])
        err = pioneer_write._gateway_error(exc, "merge")
        print("   ", err)
        return
    print("✔ اتقبلت — changeset:", str(resp.get("changeset"))[:400])

    after_data = pc.fetch_inventory_for(account)
    after = pioneer_tree.Tree((after_data or {}).get("items") or [])
    show(after, pairs, "بعد")
    still = str(item_b) in after.by_id
    print("البند التاني لسه موجود؟", still, "| أبوه:", str(after.parent.get(str(item_b)) or "")[:8])
    print("إجمالي amount لنفس الـ asset:",
          sum(int(n.get("amount") or 0) for n in after.items if str(n.get("gameAssetId")) == asset))

    # رجوع للحالة الأصلية دايماً
    back = pioneer_write._state_mutations(after, original)
    if back:
        try:
            pc.post_json(pioneer_write._url(), {"mutations": back, "requestId": ""}, token=token)
            print("↩ رجّعنا الأصل:", back)
        except Exception as exc:
            print("⛔ الرجوع فشل:", str(exc)[:200])
    final = pioneer_tree.Tree((pc.fetch_inventory_for(account) or {}).get("items") or [])
    show(final, pairs, "نهائي")


if __name__ == "__main__":
    main()
