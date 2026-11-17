"""Watch what the running game actually does while the user moves items in-game.

Two channels, both read-only and neither touching the game's memory:
  1) the OS TCP table for PioneerGame.exe — every remote address the client talks to, so a
     write endpoint on another host/IP shows up as soon as a move happens;
  2) the official gateway inventory tree, polled, so the moment a cell changes we know the
     move landed on the same gateway we read from.
Everything is appended to game_watch.jsonl for the diff afterwards.
"""
import hashlib
import json
import os
import subprocess
import time

from backend import pioneer_client as pc

ACCOUNT = os.environ.get("WATCH_ACCOUNT", "RAIDER32857")
OUT = "game_watch.jsonl"
CONN_EVERY = 5.0
TREE_EVERY = 3.0


def game_pids():
    try:
        raw = subprocess.run(["tasklist", "/FI", "IMAGENAME eq PioneerGame.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return set()
    pids = set()
    for line in raw.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower().startswith("pioneergame"):
            pids.add(parts[1])
    return pids


def connections(pids):
    raw = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30).stdout
    out = {}
    for line in raw.splitlines():
        cols = line.split()
        if len(cols) < 4 or not cols[0].startswith("TCP"):
            continue
        _, local, remote, state, pid = cols[0], cols[1], cols[2], cols[3], cols[4]
        if pid in pids:
            key = (remote, state)
            out[key] = out.get(key, 0) + 1
    return [{"remote": r, "state": s, "n": n} for (r, s), n in sorted(out.items())]


def tree_fingerprint(account):
    data = pc.fetch_inventory_for(account) or {}
    items = data.get("items") or []
    cells = {}
    for node in items:
        iid = str(node.get("instanceId") or "")
        cells[iid] = [str(s) for s in (node.get("slots") or [])]
    blob = json.dumps(cells, sort_keys=True).encode()
    # خريطة ابن -> (أب، موضع) من قوائم slots: تغيير الأب = نقلة حقيقية، تغيير الموضع لوحده = إعادة ترتيب
    where = {}
    for parent, kids in cells.items():
        for idx, kid in enumerate(kids):
            where[kid] = (parent, idx)
    etags = {str(n.get("instanceId")): str(n.get("etag")) for n in items}
    return {"count": len(items), "hash": hashlib.sha256(blob).hexdigest()[:16],
            "cells": cells, "where": where, "etags": etags}


def move_diff(prev, cur):
    """بينرجع النقلات الحقيقية + إعادة الترتيب + عدد الإتيكات اللي اتغيرت."""
    moved, reordered = [], []
    for iid, (parent, idx) in cur["where"].items():
        old = prev["where"].get(iid)
        if not old:
            continue
        if old[0] != parent:
            moved.append({"instance": iid, "from": old[0], "from_index": old[1],
                          "to": parent, "to_index": idx})
        elif old[1] != idx:
            reordered.append({"instance": iid, "parent": parent, "from_index": old[1], "to_index": idx})
    appeared = [i for i in cur["where"] if i not in prev["where"]]
    gone = [i for i in prev["where"] if i not in cur["where"]]
    bumped = [i for i, e in cur["etags"].items() if prev["etags"].get(i) and prev["etags"][i] != e]
    return {"moved": moved, "reordered_count": len(reordered), "reordered": reordered[:12],
            "appeared": appeared, "gone": gone, "etag_bumped_count": len(bumped),
            "etag_bumped_sample": bumped[:12]}



def main():
    token_present = len(pc.account_token(ACCOUNT) or "")
    print("watching account=%s toklen=%d pids=%s" % (ACCOUNT, token_present, game_pids()))
    prev = None
    last_conns = None
    next_conn = next_tree = 0.0
    deadline = time.time() + float(os.environ.get("WATCH_SECONDS", "900"))
    with open(OUT, "a", encoding="utf-8") as fh:
        while time.time() < deadline:               # ~15 دقيقة متابعة
            now = time.time()
            if now >= next_conn:
                next_conn = now + CONN_EVERY
                pids = game_pids()
                conns = connections(pids) if pids else []
                sig = json.dumps(conns, sort_keys=True)
                if sig != last_conns:               # بنسجّل مرة واحدة عند أي تغيّر في الاتصالات
                    last_conns = sig
                    fh.write(json.dumps({"ts": round(now, 2), "kind": "conn", "pids": sorted(pids),
                                         "remote": conns}) + "\n")
                    fh.flush()
            if now >= next_tree:
                next_tree = now + TREE_EVERY
                try:
                    fp = tree_fingerprint(ACCOUNT)
                except Exception as exc:
                    fh.write(json.dumps({"ts": round(time.time(), 2), "kind": "tree_err",
                                         "detail": str(exc)[:150]}) + "\n")
                    fh.flush()
                    continue
                if prev is None or fp["hash"] != prev["hash"]:
                    rec = {"ts": round(time.time(), 2), "kind": "tree",
                           "count": fp["count"], "hash": fp["hash"]}
                    if prev is not None:
                        rec["diff"] = move_diff(prev, fp)
                        print("tree@%s moved=%d etag_bumped=%d reordered=%d" %
                              (rec["ts"], len(rec["diff"]["moved"]),
                               rec["diff"]["etag_bumped_count"], rec["diff"]["reordered_count"]))
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                prev = fp
            time.sleep(0.4)
    print("watch finished")


if __name__ == "__main__":
    main()
