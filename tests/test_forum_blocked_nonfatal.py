"""A refused forum (fetcher SystemExit after consecutive HTTP failures) is recorded as blocked, keeps the anchor,
lets the blog step run, and still ends the job red."""
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["FORUM_STATUS"] = str(tmp / "forum_source_status.json")
import wxc_access_policy  # noqa: E402
wxc_access_policy.PAUSE_UNTIL = "2000-01-01"  # covers behaviour when access is allowed (after the Owner's pause)
import daily_close_research as d  # noqa: E402

d.FORUM_STATUS = tmp / "forum_source_status.json"
d.FORUM_STATUS.write_text(json.dumps({"version": 3, "anchor_id": "118755", "complete": True, "status": "complete"}), encoding="utf-8")


def refused():
    raise SystemExit("连续请求失败 5 次,疑似被限制,已停止。请稍后再试。")


now = datetime(2026, 11, 2, 1, 43, tzinfo=timezone.utc)
added, scan, reason = d._collect_forum_or_blocked(refused, now)
assert added == 0 and scan["blocked"] is True and scan["complete"] is False and reason
st = json.loads(d.FORUM_STATUS.read_text(encoding="utf-8"))
assert st["status"] == "blocked" and st["complete"] is False and st["anchor_id"] == "118755"
assert st["first_blocked_at"] == now.isoformat() and st["feed_records_added"] == 0

later = datetime(2026, 11, 2, 13, 10, tzinfo=timezone.utc)
d._collect_forum_or_blocked(refused, later)
st = json.loads(d.FORUM_STATUS.read_text(encoding="utf-8"))
assert st["first_blocked_at"] == now.isoformat() and st["blocked_at"] == later.isoformat()  # first block kept

ok = d._collect_forum_or_blocked(lambda: (3, {"complete": True}), later)
assert ok == (3, {"complete": True}, None)  # normal path unchanged

# main(): blog step runs after a blocked forum, then the job still exits non-zero
calls = []
d._collect_forum_or_blocked = lambda: (0, {"complete": False, "blocked": True}, "refused")
d.BLOG_SCAN_STATE = tmp / "blog_scan_state.json"
d.rf.BLOG_PROFILES = {"BrightLine": {}}
d.rf.capture_blog_profile = lambda name, days, return_report: calls.append(name) or {"fresh": [], "report": {"scan_complete": True}}
d.rf.daily_digest_text = lambda day: "digest"
sent = []
d.agent.say = lambda text: sent.append(text)
_probed = d._already_probed_today
d._already_probed_today = lambda now=None: False  # first try of the day
try:
    d.main()
    raise AssertionError("main must stay red when the forum is blocked")
except SystemExit as exc:
    assert "forum blocked" in str(exc)
assert calls == ["BrightLine"] and (tmp / "blog_scan_state.json").exists()
assert "blocked" in sent[0]
print("PASS forum blocked is recorded, anchor kept, blog still collected, run stays red")
d._already_probed_today = _probed

# second run on the same day: no forum/blog request at all, ends without a new failure
calls.clear()
d.FORUM_STATUS.write_text(json.dumps({"status": "blocked", "blocked_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
d._collect_forum_or_blocked = lambda: (_ for _ in ()).throw(AssertionError("must not touch the forum twice a day"))
d.main()
assert calls == []

# Owner 11/2: while blocked, wenxuecity is tried once per UTC day
d.FORUM_STATUS.write_text(json.dumps({"status": "blocked", "blocked_at": "2026-11-02T01:43:00+00:00",
                                      "first_blocked_at": "2026-11-01T01:22:00+00:00"}), encoding="utf-8")
assert d._already_probed_today(datetime(2026, 11, 2, 22, 30, tzinfo=timezone.utc)) is True
assert d._already_probed_today(datetime(2026, 11, 3, 13, 10, tzinfo=timezone.utc)) is False
d.FORUM_STATUS.write_text(json.dumps({"status": "complete", "blocked_at": "2026-11-02T01:43:00+00:00"}), encoding="utf-8")
assert d._already_probed_today(datetime(2026, 11, 2, 22, 30, tzinfo=timezone.utc)) is False  # not blocked -> normal runs
print("PASS blocked wenxuecity is tried once per UTC day")
