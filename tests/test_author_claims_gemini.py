"""Understanding switch (Owner 2026-11-21, effective 11/25): with UNDERSTANDING_SOURCE=gemini, Owner forum/forward
records that Gemini labelled contribute Gemini labels (latest shadow row wins), everything else keeps ce-5; the
consumer's required fields are present; UNDERSTANDING_SOURCE=ce5 restores the old output. Synthetic data only."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import author_claims_daily as ac  # noqa: E402

NOW = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)
day = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
recs = [
    {"id": "f1", "intake_provenance": "owner_forum_export", "author": "zm", "source_kind": "forum", "url": "u1",
     "published_at": day + " 10:00:00", "captured_at": day + "T12:00:00Z", "title": "我加仓了 NVDA", "excerpt": "",
     "content_sha256": "a" * 64},
    {"id": "f2", "intake_provenance": "owner_forum_export", "author": "zm", "source_kind": "forum", "url": "u2",
     "published_at": day + " 11:00:00", "captured_at": day + "T12:00:00Z", "title": "我加仓了 AMD", "excerpt": "",
     "content_sha256": "b" * 64},                                                    # Gemini failed -> ce-5
    {"id": "v1", "intake_provenance": None, "author": "yt", "source_kind": "video", "url": "u3",
     "published_at": day, "captured_at": day + "T12:00:00Z", "title": "我加仓了 TSLA", "excerpt": ""},  # not forum -> ce-5
]
rows = [
    {"record_id": "f1", "understood_by": "ce4_fallback", "labels": [{"symbol": "NVDA", "stance": "add"}]},
    {"record_id": "f1", "understood_by": "gemini", "labels": [{"symbol": "nvda", "stance": "add", "status": "executed"},
                                                             {"symbol": "TSM", "stance": "bullish", "status": "opinion"},
                                                             {"symbol": "TSM", "stance": "bullish", "status": "opinion"}]},
    {"record_id": "f2", "understood_by": "ce4_fallback", "labels": []},
]
with tempfile.TemporaryDirectory() as t:
    feed, shadow = Path(t) / "feed.json", Path(t) / "rows.jsonl"
    feed.write_text(json.dumps({"records": recs}, ensure_ascii=False), encoding="utf-8")
    shadow.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    ac.FEED, ac.FLAGS, ac.SHADOW_ROWS = feed, Path(t) / "none.json", shadow

    os.environ["UNDERSTANDING_SOURCE"] = "gemini"
    rep = ac.build(NOW)
    by = {}
    for c in rep["claims"]:
        by.setdefault(c["record_id"], []).append(c)
    assert rep["understanding_source"] == "gemini" and rep["extractor"].startswith("gemini-claims-0.2+")
    assert rep["records_by_extractor"] == {"gemini": 1, "ce5": 2}, rep["records_by_extractor"]
    g = by["f1"]
    assert [(c["symbol"], c["stance"], c["status"]) for c in g] == [("NVDA", "add", "executed"), ("TSM", "bullish", "opinion")]
    assert all(c["extractor"] == "gemini-claims-0.2" and c["hp_gate"] == "gemini_label" and c["sentence_sha256"] == "a" * 64 for c in g)
    for c in rep["claims"]:   # fields the quant-dashboard research job indexes directly
        for k in ("record_id", "author", "stance", "status", "hp_gate", "sentence_sha256", "symbol", "first_seen", "extractor"):
            assert k in c, (k, c)
    assert all(c["extractor"] != "gemini-claims-0.2" for c in by.get("f2", []) + by.get("v1", []))

    os.environ["UNDERSTANDING_SOURCE"] = "ce5"
    rep2 = ac.build(NOW)
    assert rep2["records_by_extractor"]["gemini"] == 0 and all(c["extractor"] != "gemini-claims-0.2" for c in rep2["claims"])
    os.environ.pop("UNDERSTANDING_SOURCE")
    assert ac.source() == "ce5"          # default without the workflow variable: previous behaviour

wf = (ROOT / ".github" / "workflows" / "research-close.yml").read_text(encoding="utf-8")
assert "UNDERSTANDING_SOURCE: ${{ vars.UNDERSTANDING_SOURCE || 'gemini' }}" in wf
print("PASS understanding switch: Gemini labels for labelled forum/forward records, ce-5 otherwise, one-variable revert")
