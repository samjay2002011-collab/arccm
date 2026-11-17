"""أي حساب من المحفوظين هو اللي ظاهر على الشاشة؟ (قراءة فقط، بطباعة الأسماء مش التوكنات)"""
import json

from backend import pioneer_client as pc, pioneer_tree as pt, accounts as acc

ST = json.load(open(r"C:/Users/Administrator/AppData/Roaming/FahmySync/state.json", encoding="utf-8"))
held = ST.get("held") or {}
print("current agent account=%r display=%r game=%s pid=%s" %
      (ST.get("account"), ST.get("display"), ST.get("game"), ST.get("pid")))
print("held keys:", list(held))

AN = pt.asset_names()


def nm(n):
    a = AN.get(str(n.get("gameAssetId")))
    if isinstance(a, dict):
        return a.get("display_name") or a.get("game_asset_name") or "?"
    return str(a or n.get("gameAssetId"))


for key, tok in held.items():
    cl = acc.jwt_claims(tok) or {}
    tpuid = (cl.get("ext") or {}).get("tpuid")
    exp = float(cl.get("exp") or 0)
    try:
        d = pc.request("/v1/pioneer/inventory", token=tok)
    except Exception as exc:
        print("%-16s exp@%s  FETCH FAIL %s" % (key, exp, type(exc).__name__))
        continue
    items = (d or {}).get("items") or []
    kids = {str(n["instanceId"]): [str(x) for x in (n.get("slots") or [])] for n in items}
    by = {str(n["instanceId"]): n for n in items}
    stash = [n for n in items if nm(n).strip().lower() == "stash"]
    scount = len(kids[str(stash[0]["instanceId"])]) if stash else 0
    fab = sorted(int(n.get("amount") or 0) for n in items if "fabric" in nm(n).lower())
    names = []
    try:
        r = pc.request("/v1/pioneer/raiders", token=tok)
        for x in (r or {}).get("raiders") or []:
            names.append("%s#%s" % (x.get("name"), x.get("tag") or x.get("tagline") or ""))
    except Exception as exc:
        names = ["raiders:%s" % type(exc).__name__]
    print("%-16s nodes=%-5d stash_slots=%-4d fabric=%-14s tpuid=%s raiders=%s" %
          (key, len(items), scount, fab, str(tpuid)[:12], names[:4]))
