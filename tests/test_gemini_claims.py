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

assert gc._budget()["calls"] >= 4
s = gc.score({"a": {"labels": [{"symbol": "NBIS", "stance": "buy"}, {"symbol": "X", "stance": "sell"}]}},
             {"a": {"labels": [{"symbol": "NBIS", "stance": "add"}]}})
assert s == {"gold_pairs": 1, "pred_pairs": 2, "matched": 1, "precision": 0.5, "recall": 1.0, "direction_agree": 1}
# only the dev set can be run before the three-way test labels exist
try:
    gc.main(["--set", "test"])
    raise AssertionError
except SystemExit:
    pass
print("PASS budget, scoring, test set locked")
