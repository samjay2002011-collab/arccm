"""يقرا مستوى محطات كل حساب من البوابة ويرجع اللوحة الجاهزة للواجهة.

    python -m inspection.bench_levels_sync            # كل الحسابات
    python -m inspection.bench_levels_sync G22        # حساب واحد

GET واحد لكل حساب (/v1/pioneer/inventory) + تخزين محلي زي أي مزامنة عادية.
مفيش ولا طلب كتابة على البوابة — build_payload بيستقبل البيانات اللي جت كما هي.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import knowledge, pioneer_client as pc, pioneer_sync, store, sync, workshop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bench_levels_sync_out.txt")


def main():
    only = (sys.argv[1] if len(sys.argv) > 1 else "").strip().upper()
    conn = store.db()
    buf = io.StringIO()
    w = buf.write
    for acc in store.list_accounts(conn):
        account = acc["name"] if isinstance(acc, dict) else acc
        if only and account.upper() != only:
            continue
        w("\n===== %s\n" % account)
        try:
            data = pc.fetch_inventory_for(account)
        except Exception as err:  # noqa: BLE001
            w("   القراءة فشلت: %s\n" % str(err)[:140])
            continue
        try:
            payload = pioneer_sync.build_payload(conn, account, data=data)
        except Exception as err:  # noqa: BLE001
            w("   بناء الـ payload فشل: %s\n" % str(err)[:140])
            continue
        levels = payload.get("bench_levels") or {}
        w("   المقروء من الشجرة: %s\n" % (levels or "(ولا محطة)"))
        result = sync.ingest(conn, account, payload, with_assets=False)
        conn.commit()
        w("   تخزين: ok=%s snapshot=%s\n" % (result.get("ok"), result.get("snapshot")))
        w("   المخزّن دلوقتي: %s | مصدر: %s\n" % (
            knowledge.station_levels(conn, account),
            knowledge.station_level_sources(conn, account)))
        board = workshop.station_board(conn, account)
        for col in board:
            w("   %-16s LV %-2s (%s) الوصفات=%s المسموحة=%s الجاهزة=%s\n" % (
                col["label"], col["level"], col["level_source"] or "بدون قراءة",
                col["count"], col["allowed"], col["ready"]))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
