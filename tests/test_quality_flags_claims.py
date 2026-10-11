import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import source_quality_flags as sq
import author_claims_daily as ac
nav = "Get Chrome Extension Popular Videos Recent Videos Video Subtitle Downloader Free Tools All Channels"
f = sq.flags_for({"source_kind": "video", "title": "x", "excerpt": nav}, None)
assert f["exclude"] and "invalid_transcript" in f["flags"] and f["provenance"] == "unaudited"
assert not sq.flags_for({"source_kind": "forum", "title": "VGT", "excerpt": ""}, {"derived_provenance": "backfill_proven"})["exclude"]
rep = ac.build(datetime.now(timezone.utc))
assert rep["claims_status"] == "experimental_unvalidated"
assert all(len(c["sentence_sha256"]) == 64 and "text" not in c for c in rep["claims"])
print("PASS quality flags + daily claims")
