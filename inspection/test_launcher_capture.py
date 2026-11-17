"""اختبار صناعي لوتيرة الالتقاط في شاشة اللانشر — من غير لمس الذاكرة ولا الشبكة ولا البوابة.

الحالة اللي كانت بتضرب: اللانشر يبان، التوكن لسه ما اتكتبش في الذاكرة، فالأجن كان
بيدخل في "مفيش توكن" ويستنى 5 دقايق قبل ما يلمع تاني — وهو بيعدّل في اللعبة ويضغط
"حدّث دلوقتي" بيده. هنا بنثبّت إن اللمعة التانية بتحصل على طول وإن المحرك مااتلمعش
واللانشر أعطى توكن.

  python inspection/test_launcher_capture.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
import fahmy_agent as agent  # noqa: E402
import memtoken  # noqa: E402

LAUNCHER, ENGINE = 1000, 2000
CALLS = []


def make_cfg():
    return {"base_url": "http://127.0.0.1:0", "project": "", "python": "", "port": 0,
            "idle_seconds": 30, "token_file": "", "boot_gap": 15, "pull_seconds": 120,
            "rescan_seconds": 300, "launcher_scan_seconds": 60}


def stub(monkey_pids, scan_results):
    """يستبدل الذاكرة والشبكة بسجل calls — scan_results بتتاكل واحدة ورا التانية."""
    del CALLS[:]
    # السجل والحالة في مجلد مؤقت: الاختبار ما يلمسش ملف FahmySync الحقيقي
    tmp = os.path.join(tempfile.mkdtemp(prefix="fahmy-test-"))
    agent.CONFIG_DIR = tmp
    agent.LOG_FILE = os.path.join(tmp, "agent.log")
    agent.STATE_FILE = os.path.join(tmp, "state.json")
    memtoken.split_pids = lambda pids=None: monkey_pids()
    memtoken.find_pids = lambda name=None: sum(monkey_pids(), [])

    def fake_scan(pid, stop_after=None, partial=None, max_bytes=None, max_seconds=None):
        CALLS.append(("scan", pid))
        out = scan_results.pop(0) if scan_results else []
        return list(out)

    memtoken.scan = fake_scan
    agent.site_status = lambda cfg: (200, {})
    agent.agent_key = lambda cfg: "test-key"
    agent.panel_names = lambda cfg, key: {"RAIDER99999", "G99#9999"}
    agent.write_token_file = lambda cfg, name, token: True
    agent.save_state = lambda state: None

    def fake_push(cfg, key, token):
        CALLS.append(("push", token[:12]))
        return 200, {"account": {"name": "RAIDER99999", "display_name": "G99#9999"},
                     "pulled": {"ok": True}, "note": "token refresh"}

    agent.push = fake_push


def token(age=0):
    return [{"token": "eyJhbGciOiJSUzI1NiIs" + "x" * 200, "iat": time.time() - age,
             "exp": time.time() + 86000, "jti": "jti-new", "sub": "s", "embark_id": "e",
             "tpuid": "t", "tenancy": "pioneer-live"}]


def fresh_state():
    return {"game": False, "exp": 0, "held": {}, "pushed": {}, "account": "RAIDER74888"}


def main():
    cfg = make_cfg()

    # 1) اللانشر بان والتوكن لسه مكتوبش: بنلمع تاني بعد الـ boot_gap ومن غير ما نلمس المحرك
    stub(lambda: ([LAUNCHER], []), [[], [], token()])
    st = fresh_state()
    first = agent.sync_once(cfg, st)
    assert st["boot_poll"] is True, st
    assert agent.scan_gap(cfg, st, [LAUNCHER]) == 15, agent.scan_gap(cfg, st, [LAUNCHER])
    assert "مستني التوكن" in first, first
    second = agent.sync_once(cfg, st)          # نفس الثواني: مفيش لمعة جديدة
    assert [c for c in CALLS if c[0] == "scan"] == [("scan", LAUNCHER)], CALLS
    st["last_scan"] -= 16                      # بنمضي الدورة التانية بعد الـ boot_gap
    second = agent.sync_once(cfg, st)
    st["last_scan"] -= 16
    third = agent.sync_once(cfg, st)
    assert [c for c in CALLS if c[0] == "scan"] == [("scan", LAUNCHER)] * 3, CALLS
    assert "اتحدّث" in third, (first, second, third)
    assert st["has_token"] is True and st["boot_poll"] is False, st
    assert st["account"] == "RAIDER99999", st["account"]

    # 2) بعد ما التوكن اتلمّ: الدورات السريعة بتسحب بالتوكن المحفوظ من غير لمعة تانية
    del CALLS[:]
    fourth = agent.sync_once(cfg, st)
    assert [c for c in CALLS if c[0] == "scan"] == [], CALLS
    assert CALLS and CALLS[0][0] == "push", CALLS
    assert "اتحدّث تلقائياً" in fourth, fourth

    # 3) اللعبوة فتحت جوا المحرك والتوكن في اللانشر: المحرك مايتلمعش خالص
    stub(lambda: ([LAUNCHER], [ENGINE]), [token(1)])
    st = fresh_state()
    out = agent.sync_once(cfg, st)
    assert CALLS[0] == ("scan", LAUNCHER), CALLS
    assert ("scan", ENGINE) not in CALLS, CALLS
    assert "اتحدّث" in out, out

    # 4) اللانشر ساكت والمحرك هو اللي فيه التوكن: بنلمع المحرك بميزانية صغيرة
    stub(lambda: ([], [ENGINE]), [token(2)])
    st = fresh_state()
    out = agent.sync_once(cfg, st)
    assert ("scan", ENGINE) in CALLS and "اتحدّث" in out, (CALLS, out)

    # 5) قفل اللعبة = سحب فوري بالتوكن المحفوظ (بعد الرايد)
    del CALLS[:]
    stub(lambda: ([], []), [])
    st["game"] = True
    out = agent.sync_once(cfg, st)
    assert not [c for c in CALLS if c[0] == "scan"], CALLS
    assert "اتحدّث تلقائياً" in out, out

    print("OK — اللانشر بيلتقط التوكن تلقائيًا والمحرك مايتلمعش وهو مش محتاج")


if __name__ == "__main__":
    main()
