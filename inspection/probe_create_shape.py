"""تنبيه شكل أمر create على بوابة mutate — بأسلوب تضارب الأنواع (بدون أي كتابة حقيقية).

الفكرة: نبعث حقل بقيمة من نوع غلط (كائن بدل string) فالـ Go unmarshaller بيرجع رسالة
بتقول اسم الحقل ونوعه داخل الهيكل: cannot unmarshal object into Go struct field
<StructName>.<field> of type string. كده بنعرف أسماء الحقول المقبولة من غير ما نخمّن.

مسار: python inspection/probe_create_shape.py [RAIDER38830]
"""
import sys, os, json, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import pioneer_client as pc, pioneer_write as pw, pioneer_tree as pt, store

FAKE = "00000000-0000-4000-8000-000000000000"
BAD = {"__probe__": 1}          # كائن بدل أي نوع متوقع
conn = store.db()


def post(account, mutations, label):
    """مسبار بلا أثر: amount=0 مرفوض قبل أي تنفيذ، وكل محاولة بتتسجل."""
    request = {"mutations": mutations, "requestId": ""}
    try:
        response = pc.post_json(pw._url(), request, token=pc.account_token(account))
        print("   [%s] 200 %s" % (label, json.dumps(response, ensure_ascii=False)[:200]))
        outcome, detail = "probe_ok", response or {}
    except pc.PioneerError as exc:
        print("   [%s] %s" % (label, str(exc)[:300]))
        outcome, detail = "probe_refused", {"error": str(exc)[:400]}
    _log_probe(account, request, outcome, detail)


def _log_probe(account, request, outcome, detail):
    try:
        pw._log(conn, account, {"kind": "probe", "ids": [], "amount": 0,
                                "mutations": request["mutations"]}, outcome, detail, 1)
    except Exception as exc:
        print("   (تسجيل فشل:", str(exc)[:80], ")")


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "RAIDER38830"
    print("الحساب:", account, "| البوابة:", pw._url())

    print("\n== 1) هل create نفسه في القاموس؟ (التحكم: update باسم وهمي) ==")
    post(account, [{"discriminator": "create", "amount": 0}], "create amount=0")
    post(account, [{"discriminator": "update", "instanceId": FAKE, "amount": 0}], "update fake")
    post(account, [{"discriminator": "zzz-not-real", "instanceId": FAKE}], "control bogus")

    print("\n== 2) أسماء الحقول المقبولة جوه create (كائن بدل النوع الصحيح) ==")
    for field in ("instanceId", "parentId", "targetWrapperId", "targetInstanceId", "wrapperId",
                  "slotIndex", "slot", "gameAssetId", "assetId", "amount", "etag", "slots",
                  "durability", "maxDurability", "quantity", "itemInstanceId", "cellId",
                  "containerId", "targetSlot", "targetSlotIndex"):
        post(account, [{"discriminator": "create", "amount": 0, field: BAD}],
             "create.%s" % field)
        time.sleep(0.25)

    print("\n== 3) هل create بيتحقق من الأب الحقيقي؟ (آيدي خانة حقيقي + amount=0) ==")
    data = pc.fetch_inventory_for(account) or {}
    tree = pt.Tree(data.get("items") or [])
    cells = [iid for iid, node in tree.by_id.items() if not node.get("slots")
             and str(node.get("amount") or 1) == "1" and tree.parent.get(iid)]
    print("   عقد أبوية بكمية 1 (عيّنة):", [c[:8] for c in cells[:3]])
    if cells:
        post(account, [{"discriminator": "create", "amount": 0, "parentId": cells[0]}],
             "create parentId=حقيقي")
        post(account, [{"discriminator": "create", "amount": 0, "targetWrapperId": cells[0]}],
             "create targetWrapperId=حقيقي")


if __name__ == "__main__":
    main()
