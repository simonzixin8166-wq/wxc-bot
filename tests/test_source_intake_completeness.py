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
        out=m.build();assert out["complete"] is True
        w("pending_youtube.json",{"records":[{"video_id":"x"}]})
        out=m.build();assert out["complete"] is False and out["youtube"]["pending"]==1
    finally:
        m.STATE,m.OUT=old_state,old_out
print("PASS unified source intake completeness contract")
