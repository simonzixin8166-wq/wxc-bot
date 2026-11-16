"""S2 Gemini challenger: mocked network only."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["GEMINI_API_KEY"] = "k"
os.environ["GEMINI_CLAIMS_PAUSE"] = "0"
import gemini_claims as gc  # noqa: E402

gc.PAUSE = 0


class R:
    def __init__(self, status, payload=None):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p


def reply(obj):
    return R(200, {"outputs": [{"type": "text", "text": "```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```"}]})


sent = []


def post_ok(url, json=None, timeout=None, headers=None):
    sent.append(json)
    assert url == gc.ENDPOINT and headers["x-goog-api-key"] == "k"
    return reply({"labels": [{"symbol": "$nbis", "stance": "buy", "status": "conditional"},
                             {"symbol": "NBIS", "stance": "buy", "status": "conditional"},
                             {"symbol": "IREN", "stance": "moon", "status": "opinion"},
                             {"symbol": "谷歌", "stance": "buy", "status": "executed"}], "note": "free text"})


ans, meta = gc.label_post("标题", "NBIS 第一档 150", post=post_ok)
assert ans["labels"] == [{"symbol": "NBIS", "stance": "buy", "status": "conditional", "instrument": "stock",
                          "holder": "author", "ticker_source": "text"}], ans
assert ans["note"] is None and meta["dropped_labels"] == 2 and meta["status"] == 200
assert "NBIS 第一档 150" in sent[0]["input"][0]["text"]
print("PASS schema validation, dedupe, invalid labels dropped")

try:
    gc.label_post("t", "x", post=lambda *a, **k: R(429))
    raise AssertionError("429 must stop")
except RuntimeError as e:
    assert str(e) == "quota"
print("PASS 429 stops the run")

calls = []


def post_503_then_ok(url, json=None, timeout=None, headers=None):
    calls.append(json["model"])
    return R(503) if len(calls) == 1 else reply({"labels": [], "note": None})


ans, meta = gc.label_post("t", "x", post=post_503_then_ok)
assert calls == gc.MODELS[:2] and ans["labels"] == [] and meta["model"] == gc.MODELS[1]
print("PASS busy model falls back")

def post_timeout(url, json=None, timeout=None, headers=None):
    raise gc.requests.exceptions.ReadTimeout("slow")


ans, meta = gc.label_post("t", "x", post=post_timeout)
assert ans["note"] == "unavailable" and meta == {"model": None, "status": "ReadTimeout"}
calls.clear()


def post_timeout_then_ok(url, json=None, timeout=None, headers=None):
    calls.append(json["model"])
    if len(calls) == 1:
        raise gc.requests.exceptions.ConnectionError("reset")
    return reply({"labels": [], "note": None})


ans, meta = gc.label_post("t", "x", post=post_timeout_then_ok)
assert meta["model"] == gc.MODELS[1] and meta["status"] == 200
print("PASS timeout falls back, never kills the run")

assert gc._budget()["calls"] >= 4
s = gc.score({"a": {"labels": [{"symbol": "NBIS", "stance": "buy"}, {"symbol": "X", "stance": "sell"}]}},
             {"a": {"labels": [{"symbol": "NBIS", "stance": "add"}]}})
assert s == {"gold_pairs": 1, "pred_pairs": 2, "matched": 1, "precision": 0.5, "recall": 1.0, "direction_agree": 1}
print("PASS budget, scoring")

# forum mode: several utterances per call, REPLYING TO passed as context, a skipped id becomes unavailable
sent.clear()


def post_batch(url, json=None, timeout=None, headers=None):
    sent.append(json)
    return reply({"answers": [{"id": "a1", "labels": [{"symbol": "AMD", "stance": "hold", "status": "opinion",
                                                       "instrument": "sell_put", "ticker_source": "context"}], "note": None},
                              {"id": "zz", "labels": [{"symbol": "X", "stance": "buy", "status": "executed"}]}]})


got, meta = gc.label_batch([{"id": "a1", "text": "That is my long hold", "context": "路人: AMD Jan 400 put 关吗？"},
                            {"id": "a2", "text": "哈哈", "context": None}], post=post_batch)
prompt = sent[0]["input"][0]["text"]
assert "REPLYING TO: 路人: AMD Jan 400 put" in prompt and "id: a2" in prompt
assert got["a1"]["labels"][0]["ticker_source"] == "context" and got["a2"]["note"] == "unavailable" and meta["missing"] == 1
assert "zz" not in got
print("PASS forum batch: context passed, ids matched, missing ids unavailable, foreign ids ignored")

# resume: answered posts are kept, 'unavailable' ones retried, a different set or version is ignored
assert gc.MODELS[0] == "gemini-3.5-flash"
d = tempfile.mkdtemp()
gc.load_set = lambda which: [{"item_id": i, "source": "A", "title": "t", "text": "x"} for i in ("p1", "p2", "p3")]
called = []
gc.label_post = lambda title, text: (called.append(1) or ({"labels": [], "ambiguous": False, "note": None, "reply_role": None},
                                                         {"model": "gemini-3.5-flash", "dropped_labels": 0}))
prev = Path(d) / "prev.json"
prev.write_text(json.dumps({"version": gc.VERSION, "set": "test", "answers": {
    "p1": {"labels": [{"symbol": "NBIS", "stance": "buy"}], "note": None},
    "p2": {"labels": [], "note": "unavailable"}}}))
out = Path(d) / "out.json"
assert gc.main(["--set", "test", "--resume", str(prev), "--out", str(out)]) == 0
r = json.loads(out.read_text())
assert len(called) == 2 and r["meta"]["resumed"] == 1 and r["answered"] == 3 and r["complete"], r
assert r["answers"]["p1"]["labels"][0]["symbol"] == "NBIS" and r["gold"] == "claims_gold_test_v5.jsonl"
called.clear()
prev.write_text(json.dumps({"version": "gemini-claims-0.1", "set": "test", "answers": {"p1": {"labels": [], "note": None}}}))
gc.main(["--set", "test", "--resume", str(prev), "--out", str(out)])
assert len(called) == 3, "an older version must not be resumed"
called.clear()
gc.main(["--set", "dev", "--resume", str(out), "--out", str(Path(d) / "dev.json")])
assert len(called) == 3, "a report of another set must not be resumed"
print("PASS resume keeps answered posts, retries unavailable, ignores other set/version")

# forum test v1 (frozen 2026-11-16): the loader rebuilds all 150 utterances from the public feed, the same text the
# three labellers saw; the gold carries labels and ids only and covers exactly the seeded sample
fg = [json.loads(x) for x in (gc.GOLD / gc.GOLD_FILES["forum_test"]).read_text(encoding="utf-8").splitlines() if x.strip()]
smp = json.loads((gc.ROOT / "research" / "forum" / "claims_gold_forum_test_v1_sample.json").read_text(encoding="utf-8"))
assert {g["post_id"] for g in fg} == {x["post_id"] for x in smp["items"]} and len(fg) == 150
assert all(set(g) <= {"post_id", "owner_subset", "labels", "ambiguous", "provenance", "adjudication", "set", "guideline"} for g in fg)
ft = gc.load_forum_dev("forum_test")
assert len(ft) == 150 and all(x["text"] for x in ft) and "forum_test" in gc.FORUM_SETS
print("PASS forum test v1: loader rebuilds 150 utterances from the feed; gold is labels and ids only")

# quota window (Owner 2026-11-16): claims label right after the 08:00 UTC free-tier reset; video calls pause 08-12 UTC
wfc = (gc.ROOT / ".github" / "workflows" / "gemini-claims.yml").read_text(encoding="utf-8")
wfy = (gc.ROOT / ".github" / "workflows" / "youtube-forward-intake.yml").read_text(encoding="utf-8")
assert 'cron: "5 8 * * *"' in wfc and "for s in test forum_test" in wfc and "gemini-claims-${{ env.SET }}" in wfc
assert '"$h" -ge 8 ] && [ "$h" -lt 12' in wfy and "GEMINI_VIDEO_RUN_CAP: ${{ env.VIDEO_RUN_CAP || '2' }}" in wfy
print("PASS quota window: claims scheduled 08:05 UTC on the first unfinished test set; video Gemini calls paused 08-12 UTC")
