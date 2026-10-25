"""YT-01: Gemini video-understanding fallback - off without a key, budgeted, identity-checked, safety-checked,
admitted only as an experimental Q3 record (never rule-eligible), and only from the forward intake."""
import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
os.environ["GEMINI_VIDEO_DAILY_CAP"] = "5"
os.environ["GEMINI_VIDEO_RUN_CAP"] = "2"
os.environ["GEMINI_VIDEO_RETRY_WAIT"] = "0"
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
rec = budget()["recent"]
assert [r["outcome"] for r in rec] == ["admitted", "identity_mismatch"], rec
assert "How I Retired" in rec[-1]["detail"] and "test-key" not in json.dumps(rec)
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
assert [r["outcome"] for r in budget()["recent"]][-2:] == ["safety_contract", "http_429"]
# daily cap (5) also holds
doc = json.loads((Path(tmp) / "gemini_video_budget.json").read_text())
doc["days"][gv._today()] = {"calls": 5}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0
assert gv.budget_ok() is False

# 503 "high demand" is retried once inside the same budgeted call
doc = json.loads((Path(tmp) / "gemini_video_budget.json").read_text())
doc["days"][gv._today()] = {"calls": 0}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0
seq = [Resp(503, {}), Resp(200, wrap(GOOD))]
def flaky(url, json=None, timeout=None, headers=None):
    return seq.pop(0)
got503 = gv.acquire("vid1", TITLE, AUTHOR, post=flaky)
assert got503 and not seq and budget()["calls"] == 1 and got503["structured"]["model"] == gv.MODELS[1]
# every model overloaded -> no admission, call refunded to today's cap
gv._run_calls = 0
assert gv.acquire("vid1", TITLE, AUTHOR, post=lambda *a, **k: Resp(503, {})) is None
assert budget()["calls"] == 1 and budget()["refunded_503"] == 1 and budget()["recent"][-1]["outcome"] == "http_503_all_models"
doc["days"][gv._today()] = {"calls": 5}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0

# identity helper: same title passes, channel-only near match passes, unrelated fails
assert gv.identity_ok({"observed_title": TITLE}, TITLE, AUTHOR)
assert gv.identity_ok({"observed_title": "SPCX前瞻提振半导体 NFLX 等待", "observed_channel": "视野环球财经"}, TITLE, AUTHOR)
assert not gv.identity_ok({"observed_title": None}, TITLE, AUTHOR)
# first live run (DQ0Yn27pdgk): right channel + tickers, misremembered title/date -> accept; prompt never carries the title
T2 = "美股 空头杀红眼5倍加码！META自保，含糊27年资本支出！TSLA、LRCX、GOOG！"
seen = {"observed_title": "多空决战蓄势待发！META、特斯拉、泛林财报深度解析！空头加码5倍做空！| 视野环球财经 20241023",
        "observed_channel": "视野环球财经", "symbols": ["META", "TSLA", "LRCX"]}
assert gv.identity_ok(seen, T2, AUTHOR)
assert not gv.identity_ok(dict(seen, observed_channel="Other Channel"), T2, AUTHOR)
assert not gv.identity_ok(dict(seen, symbols=["META"]), T2, AUTHOR)
assert "T2" not in gv.PROMPT and "{title}" not in gv.PROMPT
# safety: missing block is fine (MyAlpha enforces it), contradicting it is not
assert gv._safe({}) and gv._safe({"safety": GOOD["safety"]})
assert not gv._safe({"safety": dict(GOOD["safety"], production_action="buy")})
assert gv._safe({"safety": dict(GOOD["safety"], forward_evidence_eligible=True)})  # ignored: MyAlpha forces False
assert gv._safe({"safety": dict(GOOD["safety"], production_action="none", historical_only=False)})
assert not gv._safe({"safety": dict(GOOD["safety"], production_action="SELL")})

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
assert row["video_macro"] == [] and row["video_claims"][0]["symbol_check"] == "listed"
assert yr._is_recent("2026-10-20", datetime(2026, 10, 24, tzinfo=timezone.utc)) is True
assert yr._is_recent("2026-10-01", datetime(2026, 10, 24, tzinfo=timezone.utc)) is False
assert yr._is_recent("", datetime(2026, 10, 24, tzinfo=timezone.utc)) is False

# 7) call ledger reconciles: one detail row per billed or refunded call, with model/author/title, never truncated
doc = json.loads((Path(tmp) / "gemini_video_budget.json").read_text())
doc["days"][gv._today()] = {"calls": 0}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
for resp in (lambda *a, **k: Resp(200, wrap(GOOD)), lambda *a, **k: Resp(200, wrap(bad)), lambda *a, **k: Resp(503, {}),
             lambda *a, **k: Resp(500, {}), lambda *a, **k: (_ for _ in ()).throw(TimeoutError()),
             lambda *a, **k: Resp(200, {"outputs": []})):
    gv._run_calls = 0
    gv.acquire("vid1", TITLE, AUTHOR, post=resp)
day = budget()
rec = day["reconciliation"]
assert rec["status"] == "COMPLETE" and rec["calls_billed"] == 5 and rec["calls_refunded_503"] == 1, rec
assert rec["detail_rows"] == 6 and rec["missing_detail_rows"] == 0 and rec["counter_mismatch"] == [], rec
assert [r["outcome"] for r in day["recent"]] == ["admitted", "identity_mismatch", "http_503_all_models", "http_500",
                                                "exception", "no_json"]
assert all(r["author"] == AUTHOR and r["model"] and r["title"] == TITLE[:60] for r in day["recent"]), day["recent"]
assert day["recent"][0]["model"] == gv.MODELS[0] and day["recent"][2]["model"] == ",".join(gv.MODELS)
assert "test-key" not in json.dumps(day)
# a full day (cap calls + refunds) keeps every row; the old last-10 window would have dropped some
assert gv.RECENT_KEEP >= gv.DAILY_CAP * 4
# 2026-10-22 shape: 10 calls billed but only 6 rows (first two runs predate logging) -> INCOMPLETE, 4 missing, never guessed
legacy = {"calls": 10, "admitted": 0, "rejected": 4, "errors": 6, "recent":
          [{"outcome": o} for o in ("http_503", "http_503", "http_503", "safety_contract", "safety_contract", "identity_mismatch")]}
r22 = gv.reconcile(legacy)
assert r22["status"] == "INCOMPLETE" and r22["missing_detail_rows"] == 4 and r22["counter_mismatch"] == ["rejected", "errors"], r22
# a row whose class disagrees with the counters is INCOMPLETE even when the row count matches
assert gv.reconcile({"calls": 1, "admitted": 1, "recent": [{"outcome": "identity_mismatch"}]})["status"] == "INCOMPLETE"
assert gv.reconcile({"calls": 0})["status"] == "COMPLETE"

# 8) 403 permission_denied: that author is skipped for the rest of the day (no call spent); others still run
doc = json.loads((Path(tmp) / "gemini_video_budget.json").read_text())
doc["days"][gv._today()] = {"calls": 0}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0
n = len(calls)
assert gv.acquire("vid1", TITLE, "Andrei Jikh", post=lambda *a, **k: Resp(403, {})) is None
assert budget()["skip_authors_403"] == ["Andrei Jikh"] and budget()["calls"] == 1
gv._run_calls = 0
assert gv.acquire("vid1", TITLE, "Andrei Jikh", post=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call"))) is None
assert budget()["calls"] == 1 and budget()["reconciliation"]["status"] == "COMPLETE"
assert gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(200, wrap(GOOD)))) is not None  # other channels unaffected
# 500 does not block the author
gv._run_calls = 0
assert gv.acquire("vid1", TITLE, "Other Author", post=lambda *a, **k: Resp(500, {})) is None
assert "Other Author" not in budget()["skip_authors_403"]

# 9) extraction: up to 20 claims + macro items; tickers normalised, never guessed; unlisted tickers flagged
rich = dict(GOOD, symbols=["ISRG", "QQQ"], macro=[{"indicator": "密歇根消费者信心", "value": "48", "expectation": "46.3",
                                                   "period": "10月", "timestamp": "02:10"}] * 10,
            claims=[{"claim": f"c{i}", "symbol": s} for i, s in enumerate(["isrg", "$QQQ", "RG", "英伟达", None] * 5)])
cl = gv.claims(rich)
assert len(cl) == 20 and gv.MAX_CLAIMS == 20
assert [c["symbol"] for c in cl[:5]] == ["ISRG", "QQQ", "RG", None, None]
assert [c["symbol_check"] for c in cl[:5]] == ["listed", "listed", "not_in_symbols", None, None]
mc = gv.macro(rich)
assert len(mc) == gv.MAX_MACRO == 8 and mc[0]["value"] == "48" and mc[0]["expectation"] == "46.3"
assert "宏观：密歇根消费者信心 48（预期 46.3）" in gv.render(rich)
assert "at most 20 claims" in gv.PROMPT and "exact US ticker" in gv.PROMPT and '"macro"' in gv.PROMPT

# 10) budget priority: backlog (old/undated) videos cannot use the calls reserved for new videos
doc = json.loads((Path(tmp) / "gemini_video_budget.json").read_text())
doc["days"][gv._today()] = {"calls": gv.DAILY_CAP - gv.RESERVE_NEW}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0
assert gv.budget_ok() is True                       # default priority = new
with gv.priority("backlog"):
    assert gv.budget_ok() is False
    assert gv.acquire("vid1", TITLE, AUTHOR, post=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call"))) is None
assert gv._priority == "new"

# 11) 403 on 3 distinct days within 14 -> author unsupported (no call), lifts once those days age out
hist = {"days": {f"2026-10-{d:02d}": {"skip_authors_403": ["Andrei Jikh"]} for d in (1, 5, 9)}}
assert gv.unsupported_authors(hist) == ["Andrei Jikh"]
hist2 = {"days": {f"2026-10-{d:02d}": {"skip_authors_403": ["Andrei Jikh"] if d in (1, 5) else []} for d in range(1, 20)}}
assert gv.unsupported_authors(hist2) == []                                  # day 1 is outside the last 14 days
doc = json.loads((Path(tmp) / "gemini_video_budget.json").read_text())
doc["days"].update({f"2026-01-0{d}": {"skip_authors_403": ["Andrei Jikh"]} for d in (1, 2, 3)})
doc["days"][gv._today()] = {"calls": 0}
(Path(tmp) / "gemini_video_budget.json").write_text(json.dumps(doc))
gv._run_calls = 0
assert gv.acquire("vid1", TITLE, "Andrei Jikh", post=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call"))) is None
assert gv.acquire("vid1", TITLE, AUTHOR, post=post_with(Resp(200, wrap(GOOD)))) is not None
print("PASS YT-01 Gemini video fallback: keyless off, budget/run cap/429, identity + safety gates, forward-intake only, experimental Q3 admission, call ledger reconciles, 403 author skipped for the day, 20 claims + macro, new-video reserve, unsupported channels")
