"""P2-9: each seen video lands in exactly one stage; seen is never learning."""
import json, os, tempfile
from pathlib import Path
import youtube_learning_reconciliation as y

with tempfile.TemporaryDirectory() as td:
    s = Path(td)
    w = lambda n, d: (s / n).write_text(json.dumps(d), encoding="utf-8")
    w("seen_youtube.json", {"video_ids": ["a", "b", "c", "d", "e", "f", "g"]})
    w("research_feed.json", {"records": [{"source": "youtube", "url": "https://youtube.com/watch?v=a", "excerpt": "x"}]})
    w("youtube_learning_archive.json", {"records": [
        {"video_id": "b", "quality": "Q2", "lessons": ["l"], "rule_candidate_capable_at_source": True},
        {"video_id": "c", "quality": "Q5"}, {"video_id": "f", "quality": "Q4"}]})
    w("pending_youtube.json", {"records": [{"video_id": "d", "last_status": "discovered_pending"},
                                           {"video_id": "e", "last_status": "metadata_only"},
                                           {"video_id": "c", "last_status": "metadata_only"}]})
    w("youtube_historical_backlog.json", {"records": [{"video_id": "g"}, {"video_id": "b"}]})
    w("youtube_source_status.json", {"content_work_budget": 2})
    y.STATE = s
    out = y.build()
    assert out["seen"] == 7 and out["stages_sum_equals_seen"]
    assert out["stages"] == {"formal_feed_text": 1, "transcript_readable": 1, "partial_text": 1, "metadata_only": 2,
                             "pending_unprobed": 1, "historical_backlog": 1}, out["stages"]
    L = out["learning_layers"]
    assert L["text_available"] == 3 and L["semantically_understood"] == 1 and L["falsifiable_claims_or_rule_capable"] == 1
    assert L["matured_outcomes"] == 0
    assert out["inconsistencies"]["videos_in_multiple_state_files"] == {"archive+pending": 1, "archive+backlog": 1}
    assert out["backlog_eta"]["runs_to_probe_all_pending"] == 1
print("PASS P2-9 YouTube learning reconciliation")
