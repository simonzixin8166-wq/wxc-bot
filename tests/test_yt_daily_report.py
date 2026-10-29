"""YT-01 daily digest: once per Pacific quota day, lists read / failed videos with reasons and links, retries after a failed
send, never blocks the bot, carries no keys or positions."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
import yt_daily_report as rep

budget = {"days": {"2026-10-24": {
    "calls": 4, "admitted": 1, "rejected": 0, "errors": 3, "skip_authors_403": ["Andrei Jikh"],
    "reconciliation": {"status": "COMPLETE"},
    "recent": [
        {"video_id": "b_ZVO8_QfJ0", "outcome": "admitted", "author": "RhinoFinance / 视野环球财经", "title": "美股 对冲基金8天7减"},
        {"video_id": "w0a504L8fgs", "outcome": "http_403", "author": "Andrei Jikh", "detail": "permission_denied"},
        {"video_id": "TNQ2PuDLiOg", "outcome": "http_403", "author": "Andrei Jikh"},
        {"video_id": "SbZltIBvi7M", "outcome": "exception", "author": "RhinoFinance / 视野环球财经", "detail": "ReadTimeout"},
    ]}}}
status = {"pending_total": 109}
text = rep.build("2026-10-24", budget, status, ["Andrei Jikh"])
assert "调用 4 次 · 收录 1 · 拒收 0 · 错误 3（对账 COMPLETE）" in text
assert "https://youtu.be/b_ZVO8_QfJ0" in text and "403 无权限 https://youtu.be/w0a504L8fgs" in text
assert "超时或网络异常（ReadTimeout）" in text and "待处理积压：109" in text
assert "暂停调用，改为手动" in text and "当天已跳过（403）：Andrei Jikh" in text
assert "没有调用" in rep.build("2026-10-20", budget, status)

with tempfile.TemporaryDirectory() as d:
    (Path(d) / "gemini_video_budget.json").write_text(json.dumps(budget, ensure_ascii=False))
    (Path(d) / "youtube_source_status.json").write_text(json.dumps(status))
    sent = []
    # budget days are Pacific quota days: 10/25 09:00Z = 02:00 PDT -> previous quota day is 10/24
    now = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
    m = rep.maybe_send({}, sent.append, now=now, data_dir=d)
    assert m["yt_report_day"] == "2026-10-24" and len(sent) == 1
    assert "美西时间日" in sent[0] and "（UTC）" not in sent[0]
    # Beijing morning (10/26 01:30Z = 10/25 18:30 PDT): the latest complete quota day is still 10/24 -> no repeat
    assert rep.maybe_send(m, sent.append, now=datetime(2026, 10, 26, 1, 30, tzinfo=timezone.utc), data_dir=d) is m
    assert rep.maybe_send(m, sent.append, now=now, data_dir=d) is m and len(sent) == 1        # once per day
    assert rep.maybe_send({}, sent.append, now=datetime(2026, 10, 25, 7, 30, tzinfo=timezone.utc), data_dir=d) == {}  # 00:30 PDT: wait
    def boom(_):
        raise ConnectionError()
    m2 = rep.maybe_send({}, boom, now=now, data_dir=d)                                         # failure: unmarked, no raise
    assert "yt_report_day" not in m2
    assert "key" not in sent[0].lower() and "AIza" not in sent[0]

actions = (REPO / "wxc_actions.py").read_text(encoding="utf-8")
assert "yt_daily_report.maybe_send(meta, a.say)" in actions
print("PASS YT-01 daily digest: once per Pacific quota day, reasons + links, retry after failed send, never blocks")
