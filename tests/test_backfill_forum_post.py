"""Single-post research backfill: backfill provenance, author check, no comments, dedup."""
import json, tempfile
from pathlib import Path
import research_feed as rf
import backfill_forum_post as b

URL = "https://bbs.wenxuecity.com/tzlc/2138962.html"
class R: text = "<html/>"
POST = {"id": "2138962", "url": URL, "title": "长持倍数基金的方法探讨", "author": "jenning",
        "date": "07/19/2025 10:00:00", "text": "LRS 与 HFEA 对比……", "images": [], "comments": [{"author": "x"}]}

with tempfile.TemporaryDirectory() as td:
    old = rf.FEED_PATH
    rf.FEED_PATH = Path(td) / "research_feed.json"
    try:
        out = b.ingest(URL, "jenning", "quant-dashboard#133", fetch=lambda u: R(), parse=lambda h, u: dict(POST))
        assert out["feed_records_added"] == 1 and out["author"] == "jenning"
        rec = rf._read(rf.FEED_PATH, {})["records"][0]
        assert rec["intake_class_hint"] == "backfill" and rec["forward_evidence_eligible"] is False
        assert rec["capture_mode"] == "single_post_research_backfill" and rec["content_scope"] == "author_original_post_only"
        assert "comments" not in rec
        again = b.ingest(URL, "jenning", "quant-dashboard#133", fetch=lambda u: R(), parse=lambda h, u: dict(POST))
        assert again["deduplicated"] is True  # same post twice -> one record
        for bad_url in ("https://example.com/x.html", "https://bbs.wenxuecity.com/tzlc/abc.html"):
            try:
                b.ingest(bad_url, "jenning", "", fetch=lambda u: R(), parse=lambda h, u: dict(POST)); raise AssertionError(bad_url)
            except SystemExit:
                pass
        try:
            b.ingest(URL, "someone_else", "", fetch=lambda u: R(), parse=lambda h, u: dict(POST)); raise AssertionError("author")
        except SystemExit as e:
            assert "author mismatch" in str(e)
    finally:
        rf.FEED_PATH = old
print("PASS single-post research backfill")
