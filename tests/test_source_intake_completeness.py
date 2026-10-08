from pathlib import Path
import json,tempfile
import source_intake_completeness as m

with tempfile.TemporaryDirectory() as td:
    old_state,old_out=m.STATE,m.OUT
    m.STATE=Path(td);m.OUT=m.STATE/"source_intake_completeness.json"
    try:
        def w(name,obj):(m.STATE/name).write_text(json.dumps(obj),encoding="utf-8")
        w("forum_source_status.json",{"complete":True,"continuity_proven":True})
        w("blog_scan_state.json",{"authors":{"A":{"scan_complete":True,"missing_from_feed":0}}})
        w("youtube_source_status.json",{"status":"ok"})
        w("youtube_discovery_state.json",{"complete":True})
        w("youtube_historical_backlog.json",{"records":[]})
        w("pending_youtube.json",{"records":[]})
        w("seen_youtube.json",{"video_ids":[]})
        w("youtube_learning_archive.json",{"records":[]})
        w("research_feed.json",{"records":[]})

        out=m.build()
        assert out["complete"] is True
        assert out["coverage_complete"] is True
        assert out["semantic_learning_complete"] is True
        assert out["youtube"]["accounting_balanced"] is True

        # Explicit pending is accounted coverage, but semantic learning remains incomplete.
        w("seen_youtube.json",{"video_ids":["x"]})
        w("pending_youtube.json",{"records":[{"video_id":"x"}]})
        out=m.build()
        assert out["complete"] is True
        assert out["coverage_complete"] is True
        assert out["semantic_learning_complete"] is False
        assert out["youtube"]["pending"]==1
        assert out["youtube"]["unaccounted"]==0
        assert out["youtube"]["unresolved_semantic"]==1

        # A seen ID with no durable feed/archive/pending/backlog record is a true coverage failure.
        w("seen_youtube.json",{"video_ids":["x","lost"]})
        out=m.build()
        assert out["complete"] is False
        assert out["coverage_complete"] is False
        assert out["youtube"]["unaccounted"]==1
        assert out["youtube"]["unaccounted_video_ids"]==["lost"]

        # Historical Q1/Q2 semantic learning closes that video's learning gap.
        w("seen_youtube.json",{"video_ids":["h"]})
        w("pending_youtube.json",{"records":[]})
        w("youtube_learning_archive.json",{"records":[{"video_id":"h","historical_learning_eligible":True}]})
        out=m.build()
        assert out["coverage_complete"] is True
        assert out["semantic_learning_complete"] is True
        assert out["youtube"]["historical_semantic_learned"]==1
    finally:
        m.STATE,m.OUT=old_state,old_out
print("PASS unified source coverage + semantic-learning completeness contract")
