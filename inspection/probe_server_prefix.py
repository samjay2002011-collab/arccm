# -*- coding: utf-8 -*-
"""جرد المسارات تحت الـprefixes الجديدة اللي طلعت من ذاكرة اللعبة.

اللعبة herself فيها الـbase URLs دي (مش مجرد فضول: لو surface تاني بيقبل توكن
الرفيق، ممكن يكون عليه العمليات اللي `/v1/pioneer` بترفضها):
    https://api-gateway.europe.es-pio.net/v1/server/pioneer
    https://api-gateway.europe.es-pio.net/v1/admin/pioneer
    https://api-gateway.europe.es-pio.net/v1/server/shared
    https://api-gateway.europe.es-pio.net/v1/admin/shared
    https://api-gateway.europe.es-pio.net/v1/admin/discovery

قراءة فقط: GET وحده. 404 = مفيش مسار؛ 401/403 = المسار موجود بس التوكن مرفوض
(مفيد نعرفه)؛ 200/405 = مسار شغال.

    python -m inspection.probe_server_prefix G18
"""
import json
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\rr")

from backend import pioneer_client as pc  # noqa: E402

NAMES = ["inventory", "inventory/v1", "inventory/v1/mutate", "inventory/v1/batch-mutate",
         "batch-operations", "inventory/batch-operations", "items", "stacks",
         "inventory/stacks/merge", "inventory/v1/combine", "inventory/v1/stack-merge",
         "manifest", "config", "offers", "traders", "raiders", "players", "me"]

PREFIXES = [
    "/v1/server/pioneer/", "/v1/admin/pioneer/", "/v1/server/", "/v1/admin/",
    "/v1/server/shared/", "/v1/admin/shared/", "/v1/server/discovery/",
    "/v1/admin/discovery/", "/v1/pioneer/server/", "/v1/pioneer/admin/",
]


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "G18"
    token = pc.account_token(account or None)
    if not token:
        print("مفيش توكن جاهز.")
        return
    print("حساب:", account or "(النشيط)")
    interesting = []
    for pre in PREFIXES:
        for name in [""] + NAMES:
            path = pre + name
            try:
                out = pc.request(path, token=token, method="GET")
                print("%-52s 200 %s" % (path, json.dumps(out, ensure_ascii=False)[:120]))
                interesting.append(path)
            except Exception as exc:
                msg = str(exc)
                if "404 page not found" in msg:
                    continue
                if "401" in msg:
                    print("%-52s 401 (موجود + التوكن مرفوض)" % path)
                    interesting.append(path)
                elif "403" in msg:
                    print("%-52s 403 (%s)" % (path, msg[:90]))
                    interesting.append(path)
                elif "405" in msg:
                    print("%-52s 405 => مسار POST موجود" % path)
                    interesting.append(path)
                elif "MANIFEST" in msg:
                    print("%-52s manifest-required (%s)" % (path, msg[:80]))
                    interesting.append(path)
    print("\n== اللي مش 404 ==")
    for p in interesting:
        print("  ", p)
    if not interesting:
        print("   مفيش — كل الـprefixes دي مالهاش مسارات لتوكن الرفيق.")


if __name__ == "__main__":
    main()
