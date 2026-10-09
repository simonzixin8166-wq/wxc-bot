import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import correct_provenance as cp, research_feed as rf
recs = [{"id": "a", "author": "麻你", "published_at": "2026-07-10", "captured_at": "2026-10-09T07:06:11Z", "intake_class_hint": "live_candidate", "capture_mode": "scheduled_blog_scan_complete"},
        {"id": "b", "author": "麻你", "published_at": "2026-10-08 21:00:00", "captured_at": "2026-10-09T07:06:11Z", "intake_class_hint": "live_candidate", "capture_mode": "x"},
        {"id": "c", "author": "bogbog", "published_at": "2026-07-10", "captured_at": "2026-10-09T07:06:11Z", "intake_class_hint": "live_candidate", "capture_mode": "x"}]
old = [dict(r) for r in recs]
ids = cp.downgrade(recs, "麻你", "test")
assert ids == ["a"], ids
a = recs[0]
assert a["intake_class_hint"] == "backfill" and a["forward_evidence_eligible"] is False and a["revision"]["prior"]["intake_class_hint"] == "live_candidate"
assert recs[1]["intake_class_hint"] == "live_candidate" and recs[2]["intake_class_hint"] == "live_candidate"
lost, changed = rf.immutable_violations(old, recs)
assert not lost and not changed, changed      # declared revision is accepted by the append-only guard
# never upgrades
recs[0]["intake_class_hint"] = "backfill"; assert cp.downgrade(recs, "麻你", "t") == []
print("PASS correct_provenance")
