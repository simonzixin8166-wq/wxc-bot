import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provenance_audit as pa
assert pa.classify("2026-10-01 09:31:02", "2026-10-01T23:38:33+00:00")[0] == "near_publication_observed"
assert pa.classify("2026-07-10 13:50:22", "2026-10-02T01:48:13+00:00")[0] == "backfill_proven"
assert pa.classify(None, "2026-10-02T01:48:13+00:00")[0] == "unprovable"
assert pa.classify("2026-10-01", None)[0] == "unprovable"
print("PASS provenance audit")
