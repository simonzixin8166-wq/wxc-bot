"""Owner 2026-11-11: Wenxuecity paused (no request at all) + long-running bot loop. Mocked, no network."""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

td = tempfile.mkdtemp()
os.environ["DATA_DIR"] = td
os.environ["FORUM_STATUS"] = str(Path(td) / "forum_source_status.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests  # noqa: E402
import wxc_access_policy as ap  # noqa: E402
import wxc_scraper as w  # noqa: E402
import wxc_blog as blog  # noqa: E402

# ---- policy
assert ap.paused("https://bbs.wenxuecity.com/cfzh/1.html", today=date(2026, 11, 11))
assert ap.paused("https://blog.wenxuecity.com/myblog/82458/x.html", today=date(2027, 5, 10))
assert not ap.paused("https://bbs.wenxuecity.com/cfzh/1.html", today=date(2027, 5, 11))   # ends on PAUSE_UNTIL
assert not ap.paused("https://api.telegram.org/x", today=date(2026, 11, 11))
assert not ap.paused("https://notwenxuecity.com/x", today=date(2026, 11, 11))
print("PASS policy: Wenxuecity hosts only, until 2027-05-11")

# ---- no request leaves the helpers or the sessions
if ap.paused():
    calls = []
    real = requests.adapters.HTTPAdapter.send
    requests.adapters.HTTPAdapter.send = lambda self, req, **k: calls.append(req.url)  # would be a network call
    try:
        assert w.get("https://bbs.wenxuecity.com/cfzh/") is None
        assert blog.get("https://blog.wenxuecity.com/myblog/82458/") is None
        assert blog.ACCESS_LOG[-1]["status"] == "paused_by_owner"
        for s in (w.sess, blog.sess):
            try:
                s.get("https://bbs.wenxuecity.com/cfzh/1.html", timeout=5)
                raise AssertionError("session reached wenxuecity")
            except ap.PausedError:
                pass
        assert calls == [], calls
    finally:
        requests.adapters.HTTPAdapter.send = real
    print("PASS helpers and guarded sessions make no Wenxuecity request")

    import daily_close_research as dcr  # noqa: E402
    dcr.FORUM_STATUS = Path(os.environ["FORUM_STATUS"])
    dcr.FORUM_STATUS.write_text(json.dumps({"anchor_id": "118755", "status": "blocked"}))
    dcr.collect_forum = lambda: (_ for _ in ()).throw(AssertionError("forum must not be collected"))
    dcr.main()
    st = json.loads(dcr.FORUM_STATUS.read_text())
    assert st["status"] == "paused_by_owner" and st["anchor_id"] == "118755" and st["complete"] is False
    import forum_board_scan as fbs  # noqa: E402
    fbs.scan_board = lambda *a, **k: (_ for _ in ()).throw(AssertionError("board scan must not run"))
    assert fbs.main() == 0
    print("PASS research-close forum/blog and board scan skip while paused; anchor kept; run stays green")

# ---- long-running bot loop
os.environ.update(TG_BOT_TOKEN="t", TG_CHAT_ID="1")
import importlib  # noqa: E402
import wxc_tg_agent  # noqa: E402
importlib.reload(wxc_tg_agent)
import wxc_actions as wa  # noqa: E402
wa.META = str(Path(td) / "meta.json")
seq = [[{"update_id": 5, "message": {"chat": {"id": 1}, "text": "/help"}}], [], []]
polls, handled, periodic, saved = [], [], [], []


class R:
    def __init__(self, result):
        self._r = result

    def json(self):
        return {"ok": True, "result": self._r}


wa.requests.get = lambda url, params=None, timeout=None: (polls.append(params), R(seq.pop(0) if seq else []))[1]
wa.a.handle = lambda text, sync=False: handled.append(text)
wa._periodic = lambda meta: (periodic.append(1), meta)[1]
wa.save_state = lambda reason: saved.append(reason)
wa.POLL_SECONDS = 0
clock = [1000.0]
wa.time.time = lambda: clock[0]
orig_poll = wa._poll


def tick(meta, timeout):
    clock[0] += 60
    return orig_poll(meta, timeout)


wa._poll = tick
wa.RUN_MINUTES = 3
wa.main()
assert handled == ["/help"] and saved == ["bot handled messages"], (handled, saved)
assert polls[1]["offset"] == 6 and len(periodic) == 1, (polls, periodic)   # offset advanced; periodic at most every 30 min
assert json.loads(Path(wa.META).read_text())["offset"] == 6
wa.RUN_MINUTES, seq[:], polls[:] = 0, [[]], []
wa.main()
assert len(polls) == 1 and polls[0]["timeout"] == 0                         # BOT_RUN_MINUTES=0: one round as before
print("PASS bot loop: long-poll until the deadline, save after handling, periodic throttled; default single round")
