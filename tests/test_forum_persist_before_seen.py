"""Forum entries are acknowledged (seen) only after their feed row is durably persisted.

Also: the Telegram watcher is notification-only (no second feed writer), and
author backfills carry non-forward provenance.
"""
from pathlib import Path
import inspect, json, tempfile
import daily_close_research as d
import research_feed as rf
import wxc_tg_agent as agent

ENTRY = {"entry_key": "k1", "entry_kind": "post", "parent_post_id": "114200",
         "published_at": "10/08/2026 08:00:00"}
POST = {"source_entry_key": "k1", "id": "114200", "title": "LITE 加仓理由", "text": "我今天加仓 LITE。",
        "url": "https://bbs.wenxuecity.com/cfzh/114200.html", "date": "2026-10-08 08:00:00"}
PAGES = ['<a href="/cfzh/114200.html">x</a><a href="114162.html">anchor</a>']

def seen(root):
    p = root / "seen_forum_entries_A.json"
    return set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()

def feed_ids():
    doc = rf._read(rf.FEED_PATH, {"records": []})
    return {r.get("id") for r in doc.get("records", [])}

saved = (d.FORUM_SCAN_STATE, d.FORUM_STATUS, rf.FEED_PATH, rf.append_records, d.agent.load_watch,
         d.agent.load_seen, d.agent.list_pages, d.agent.entries_for, d.agent.fetch_entries)
real_append = rf.append_records
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    try:
        d.FORUM_SCAN_STATE = root / "scan.json"
        d.FORUM_STATUS = root / "status.json"
        rf.FEED_PATH = root / "research_feed.json"
        d.agent.load_watch = lambda: ["A"]
        d.agent.load_seen = lambda author: {"114162"}
        d.agent.list_pages = lambda n, state: PAGES * n
        d.agent.entries_for = lambda author, htmls: {"k1": dict(ENTRY)}
        d.agent.fetch_entries = lambda entries, state: [dict(POST)]
        d._write(d.FORUM_SCAN_STATE, {"version": 3, "anchor_id": "114162", "complete": True, "next_scan_pages": 8})

        # 1. Feed write fails: nothing acknowledged, anchor untouched, error is visible.
        def boom(rows):
            raise OSError("disk full")
        rf.append_records = boom
        try:
            d.collect_forum()
            raise AssertionError("feed write failure must propagate")
        except OSError:
            pass
        assert "k1" not in seen(root), seen(root)
        assert json.loads(d.FORUM_SCAN_STATE.read_text(encoding="utf-8"))["anchor_id"] == "114162"

        # 2. Write "succeeds" but the row is not on disk: stay retryable and partial.
        rf.append_records = lambda rows: 0
        _, scan = d.collect_forum()
        assert "k1" not in seen(root)
        assert scan["complete"] is False and scan["processing_complete"] is False
        assert scan["anchor_id"] == "114162"
        status = json.loads(d.FORUM_STATUS.read_text(encoding="utf-8"))
        assert status["unresolved_entries_by_author"]["A"] == 1 and status["status"] == "partial"

        # 3. Retry with a working writer: persisted first, then acknowledged, anchor advances.
        rf.append_records = real_append
        added, scan = d.collect_forum()
        row_id = rf.normalize("forum", "A", dict(POST))["id"]
        assert added == 1 and row_id in feed_ids()
        assert "k1" in seen(root)
        assert scan["complete"] is True and scan["anchor_id"] == "114200"

        # 4. Idempotent: the acknowledged entry is not re-fetched or duplicated.
        d.agent.fetch_entries = lambda entries, state: (_ for _ in ()).throw(AssertionError("re-fetched")) if entries else []
        added, _ = d.collect_forum()
        assert added == 0 and len([i for i in feed_ids() if i == row_id]) == 1

        # 5. Author backfill rows are explicitly non-forward.
        rf.add_forum_posts("B", [dict(POST, source_entry_key="kb", url="https://bbs.wenxuecity.com/cfzh/9.html")],
                           provenance={"intake_class_hint": "backfill", "capture_mode": "forum_author_backfill",
                                       "forward_evidence_eligible": False})
        b = [r for r in rf._read(rf.FEED_PATH, {})["records"] if r.get("author") == "B"][0]
        assert b["intake_class_hint"] == "backfill" and b["forward_evidence_eligible"] is False
    finally:
        (d.FORUM_SCAN_STATE, d.FORUM_STATUS, rf.FEED_PATH, rf.append_records, d.agent.load_watch,
         d.agent.load_seen, d.agent.list_pages, d.agent.entries_for, d.agent.fetch_entries) = saved

# 6. Telegram watcher keeps notifying but is not a feed writer.
src = inspect.getsource(agent.check_watch)
assert "add_forum_posts" not in src and "append_records" not in src
assert "say(" in src
backfill_src = Path(__file__).resolve().parents[1].joinpath("backfill_forum_author.py").read_text(encoding="utf-8")
assert '"capture_mode": "forum_author_backfill"' in backfill_src
wf = Path(__file__).resolve().parents[1].joinpath(".github/workflows/tg-bot.yml").read_text(encoding="utf-8")
assert ":!state/research_feed.json" in wf and "pull --rebase" in wf

print("PASS forum persist-then-seen / notify-only tg watcher / backfill provenance")
