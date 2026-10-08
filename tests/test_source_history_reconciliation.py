"""P2-10: author x month matrix; unscanned history is unknown; seen-not-in-feed surfaced."""
import json, tempfile
from pathlib import Path
import source_history_reconciliation as s

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    w = lambda n, v: (d / n).write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    w("research_feed.json", {"records": [
        {"source_kind": "forum", "author": "A", "published_at": "2026-09-03 10:00:00", "url": "https://x/cfzh/11.html", "excerpt": "e"},
        {"source_kind": "forum", "author": "A", "published_at": "10/02/2026 10:00:00", "url": "https://x/cfzh/12.html", "intake_class_hint": "backfill"},
        {"source_kind": "blog", "author": "B", "published_at": "2026-10-01", "url": "https://b/1.html", "operations": [{"x": 1}]},
        {"source_kind": "video", "author": "V", "published_at": "2026-10-01"}]})
    w("seen_A.json", ["11", "12", "9"])
    w("watch.json", ["A"])
    w("blog_scan_state.json", {"authors": {"B": {"archive_months_ok": ["2026-10"], "archive_failures": [], "unique_article_ids": 1,
                                                  "missing_from_feed": 0, "recovery_days_used": 14}}})
    s.STATE = d
    out = s.build()
    assert out["matrix"]["A"]["2026-09"]["records"] == 1 and out["matrix"]["A"]["2026-10"]["backfill"] == 1
    assert out["matrix"]["A"]["2026-10"]["title_only"] == 1 and out["matrix"]["A"]["2026-09"]["excerpt"] == 1
    assert out["matrix"]["B"]["2026-10"]["structured_view"] == 1 and "V" not in out["matrix"]
    assert out["coverage"]["A"]["forum"]["seen_not_in_feed"] == 1 and out["coverage"]["A"]["forum"]["seen_not_in_feed_examples"] == ["9"]
    assert "unknown" in out["coverage"]["B"]["blog"]["history_before_window"]
print("PASS P2-10 source history reconciliation")
