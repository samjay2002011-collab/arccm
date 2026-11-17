"""يختبر رقم المانيفست الجديد (اللي بترده البوابة من غير build) بكتابة حقيقية، ويرجّع كل حاجة لأصلها.

  python inspection/probe_new_manifest_write.py G14
  python inspection/probe_new_manifest_write.py G14 --keep   # يحفظ الجديد لو الكتابة نجحت
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from backend import config, pioneer_client as pc, pioneer_tree, pioneer_write as pw, store  # noqa: E402

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "G14"
KEEP = "--keep" in sys.argv

old = pc._read_json(pc.MANIFEST_FILE) or {}
token = pc.account_token(ACCOUNT)
r = requests.post(pc.BASE + "/v1/shared/manifest", headers=pc.headers(token),
                  json={"playtest_id": 0, "artifact_id": "", "store_deployment_target": "Production",
                        "manifest_id": 0, "app_id": "2118292977-WinGDK", "build_id": ""},
                  timeout=config.HTTP_TIMEOUT)
new_id = str((r.json() or {}).get("id") or "") if r.status_code == 200 else ""
print("saved  %s (build %s)" % (old.get("manifest_id"), old.get("build")))
print("latest %s" % new_id)
if not new_id:
    raise SystemExit("البوابة ماردتش رقم.")

print("read with new header:", pc.request("/v1/pioneer/inventory", token=token, manifest_id=new_id)
      and "200 ok")

pc.save_manifest(new_id, build=str(old.get("build") or ""))
ok = False
try:
    data = pc.fetch_inventory_for(ACCOUNT)
    tree = pioneer_tree.Tree((data or {}).get("items") or [])
    stash_cells = list(pioneer_tree.layout(tree)["stash"]["slots"])
    item = next((iid for iid in tree.by_id
                 if tree.parent.get(iid) in stash_cells and not tree.children(iid)), "")
    if not item:
        raise SystemExit("مفيش قطعة مفردة في الستاش أختبر عليها.")
    src = tree.parent[item]
    dst = next((c for c in stash_cells if c != src and not tree.first_child(c)), "")
    print("test move %s (%s): %s -> %s" % (item, tree.name_of(item), src, dst))
    if not dst:
        raise SystemExit("الستاش مليان — مفيش خانة فاضية أختبر عليها.")
    out = pw.move(store.db(), ACCOUNT, "stash", [{"instance_id": item}], target_wrapper_id=dst)
    print("MOVE executed=%s error=%s detail=%s" % (out.get("executed"), out.get("error"),
                                                   str(out.get("detail"))[:220]))
    if out.get("executed"):
        back = pw.move(store.db(), ACCOUNT, "stash", [{"instance_id": item}],
                       target_wrapper_id=src)
        print("RESTORE executed=%s detail=%s" % (back.get("executed"), str(back.get("detail"))[:160]))
    ok = bool(out.get("executed"))
finally:
    if not (KEEP and ok):
        pc.save_manifest(old.get("manifest_id") or "", build=str(old.get("build") or ""))
    print("manifest now:", json.loads(open(pc.MANIFEST_FILE, encoding="utf-8").read()))
