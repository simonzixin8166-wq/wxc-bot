"""YT-01: Gemini video-understanding fallback - off without a key, budgeted, identity-checked, safety-checked,
admitted only as an experimental Q3 record (never rule-eligible), and only from the forward intake."""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
os.environ["GEMINI_VIDEO_DAILY_CAP"] = "5"
os.environ["GEMINI_VIDEO_RUN_CAP"] = "2"
os.environ.pop("GEMINI_API_KEY", None)
import gemini_video as gv
import transcript_router as tr

TITLE = "美股 SPCX前瞻大幅提振半导体！NFLX蛰伏等待！ISRG加仓计划更新！"
AUTHOR = "RhinoFinance / 视野环球财经"
GOOD = {
    "observed_title": TITLE, "observed_channel": "视野环球财经",
    "summary_zh": "作者认为SPCX前瞻提振半导体板块，NFLX暂时蛰伏等待财报，ISRG在回调时按计划分批加仓。",
    "symbols": ["SPCX", "NFLX", "ISRG", "not a ticker"],
    "claims": [{"claim": "ISRG 回调到 480 附近会继续加仓", "symbol": "ISRG", "stance": "buy", "price": "480",
                "timestamp": "06:12", "evidence_mode": "spoken_explicit", "confidence": "high"},
               {"claim": "x" * 300, "symbol": None, "stance": "other", "price": None, "timestamp": None,
                "evidence_mode": "visual_inference", "confidence": "low"}],
    "methods": [{"name": "分批加仓", "explicit_parameters": {"tranches": 3}, "missing_parameters": [], "timestamp": None}],
    "invalidations": [{"symbol": "ISRG", "condition": "跌破 450 停止加仓", "timestamp": "07:01"}],
    "uncertainties": [],
    "safety": {"historical_only": True, "forward_evidence_eligible": False, "promotion_eligible": False, "production_action": None},
}


class Resp:
    def __init__(self, code, payload=None):
        self.status_code, self._p = code, payload

    def json(self):
        return self._p


def wrap(doc):
    return {"outputs": [{"type": "text", "text": "```json\n" + json.dumps(doc, ensure_ascii=False) + "\n```"}]}


calls = []


def post_with(resp):
    def post(url, json=None, timeout=None, headers=None):
        calls.append(json)
        assert json["input"][0] == {"type": "video", "uri": "https://www.youtube.com/watch?v=vid1"}
        return resp
    return post


def budget():
    return json.loads((Path(tmp) / "gemini_video_budget.json").read_text())["days"][gv._today()]


# 1) off without a key: no call, no budget file
assert gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(200, wrap(GOOD)))) is None and not calls
assert not (Path(tmp) / "gemini_video_budget.json").exists()

os.environ["GEMINI_API_KEY"] = "test-key"
# 2) good answer -> experimental Q3, never rule-eligible, claims bounded
got = gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(200, wrap(GOOD))))
assert got and got["quality"] == "Q3" and got["provider"] == "gemini_video" and got["rule_candidate_allowed"] is False
assert got["content_origin"] == "gemini_video_understanding" and got["timestamp_evidence"] is True
assert all(len(c["claim"]) <= gv.CLAIM_CHARS for c in got["structured"]["claims"])
assert "ISRG 回调到 480" in got["text"] and "跌破 450" in got["text"]
assert budget()["calls"] == 1 and budget()["admitted"] == 1

# 3) identity mismatch (model could not see the video) -> rejected; also counts against the run cap
bad = dict(GOOD, observed_title="How I Retired Early With Dividends", observed_channel="Some Other Channel")
assert gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(200, wrap(bad)))) is None
assert budget()["rejected"] == 1
# 4) run cap reached (2 per run) -> no further call
n = len(calls)
assert gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(200, wrap(GOOD)))) is None and len(calls) == n

# new run: safety violation is rejected; 429 exhausts the day
gv._run_calls = 0
unsafe = dict(GOOD, safety=dict(GOOD["safety"], production_action="buy"))
assert gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(200, wrap(unsafe)))) is None
gv._run_calls = 0
assert gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(429, {}))) is None
assert budget()["exhausted"] is True and gv.budget_ok() is False
# daily cap (5) also holds
doc = json.loads((Path(tmp) / "gemini_video_budget.json").read_text())
doc["days"][gv._today()] = {"calls": 5}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0
assert gv.budget_ok() is False

# identity helper: same title passes, channel-only near match passes, unrelated fails
assert gv.identity_ok({"observed_title": TITLE}, TITLE, AUTHOR)
assert gv.identity_ok({"observed_title": "SPCX前瞻提振半导体 NFLX 等待", "observed_channel": "视野环球财经"}, TITLE, AUTHOR)
assert not gv.identity_ok({"observed_title": None}, TITLE, AUTHOR)

# 5) router: only the forward intake opts in; health probes / archives never spend the budget
doc["days"][gv._today()] = {"calls": 0}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0
saved = (tr._xgoose_native, tr._direct_pickscribe, tr._duckduckgo_links, gv.acquire)
try:
    tr._xgoose_native = tr._direct_pickscribe = lambda *a, **k: None
    tr._duckduckgo_links = lambda *a, **k: []
    seen = []
    gv.acquire = lambda vid, title, author: seen.append(vid) or got
    q5 = tr.acquire("vid1", TITLE, AUTHOR, official_fetcher=lambda v: ("", "unavailable"))
    assert q5["quality"] == "Q5" and not seen
    q3 = tr.acquire("vid1", TITLE, AUTHOR, official_fetcher=lambda v: ("", "unavailable"), allow_gemini=True)
    assert q3["quality"] == "Q3" and q3["provider"] == "gemini_video" and seen == ["vid1"]
    assert "structured" not in tr.public_view(q3)
finally:
    tr._xgoose_native, tr._direct_pickscribe, tr._duckduckgo_links, gv.acquire = saved

# 6) admission: a rule-supply channel admits the Gemini Q3 record as experimental, never as rules
import youtube_research as yr
importlib.reload(yr)
ch = {"handle": "@RhinoFinance", "author": AUTHOR, "role": "rule_supply"}
assert yr._content_ready(ch, q3) is True
assert yr._content_ready(ch, dict(q3, content_origin="structured_summary")) is False  # other Q3 unchanged
row = yr.make_feed_row(ch, {"id": "vid1", "title": TITLE, "upload_date": "20261021"}, q3)
assert row["rule_candidate_allowed"] is False and row["operations"] == [] and row["portfolio_rules"] == []
assert row["claims_status"] == "experimental_unvalidated" and row["validation_status"] == "pending_owner_spot_check"
assert row["forward_evidence_eligible"] is False and row["content_provider"] == "gemini_video"
assert {"SPCX", "NFLX", "ISRG"} <= set(row["symbols"]) and "not a ticker" not in row["symbols"]
assert len(row["excerpt"]) <= 360 and row["video_claims"][0]["timestamp"] == "06:12"
print("PASS YT-01 Gemini video fallback: keyless off, budget/run cap/429, identity + safety gates, forward-intake only, experimental Q3 admission")
