"""Gemini shadow observation: Gemini first, ce-4 fallback only when Gemini could not label; every row says who
understood it; a 429 sends the rest to the fallback; a trial cap leaves the rest for the next run; append-only
ledger never relabels a record; labels and ids only, never source text; production_use is always false."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gemini_shadow as gs

gs.gc.PAUSE = 0
NOW = datetime(2026, 11, 17, 8, 6, tzinfo=timezone.utc)


def rec(i, prov="owner_forum_export", day="2026-11-16", claims=None, text="NVDA 我加仓了"):
    r = {"id": f"r{i}", "intake_provenance": prov, "captured_at": f"{day}T02:00:00Z", "title": text, "excerpt": text,
         "author": "a", "source_entry_key": str(i), "claims": claims or []}
    if prov == "owner_forward":
        r["owner_forward_item_id"] = f"C-{i}"
    return r


records = [rec(1, claims=[{"symbol": "NVDA", "stance": "add"}]), rec(2), rec(3, day="2026-11-10"),
           rec(4, prov=None), rec(5, prov="owner_forward", claims=[{"symbol": "AMD", "stance": "sell"}])]
calls = []


def batch(items):
    calls.append(("batch", [i["id"] for i in items]))
    return {i["id"]: {"labels": [{"symbol": "NVDA", "stance": "add", "status": "executed"}], "note": None} for i in items}, {"model": "m"}


def post(title, text):
    calls.append(("post", text))
    return {"labels": [{"symbol": "AMD", "stance": "trim", "status": "executed"}, {"symbol": "TSM", "stance": "bullish", "status": "opinion"}], "note": None}, {"model": "m"}


rows, daily = gs.run(records, set(), label_post=post, label_batch=batch, textpack=lambda i: "FULL TEXT", now=NOW)
assert [r["record_id"] for r in rows] == ["r1", "r2", "r5"]          # window + provenance filter
assert all(r["understood_by"] == "gemini" and r["production_use"] is False for r in rows)
assert calls == [("batch", ["r1", "r2"]), ("post", "FULL TEXT")]
assert daily["coverage"] == 1.0 and daily["text_basis"] == {"feed_title_excerpt": 2, "full_text": 1}
assert daily["gemini_pairs"] == 4 and daily["both_pairs"] == 2 and daily["direction_agree"] == 2 and daily["gemini_only_pairs"] == 2
r5 = next(r for r in rows if r["record_id"] == "r5")
assert r5["ce4_labels"] == [{"symbol": "AMD", "stance": "sell"}] and {l["symbol"] for l in r5["labels"]} == {"AMD", "TSM"}

# 429 on the first call: everything falls back to the production ce-4 claims, marked as such
def batch429(items):
    raise RuntimeError("quota")
rows2, d2 = gs.run(records, set(), label_post=post, label_batch=batch429, textpack=lambda i: None, now=NOW)
assert {r["understood_by"] for r in rows2} == {"ce4_fallback"} and d2["quota_stop"] == "http_429" and d2["coverage"] == 0.0
assert next(r for r in rows2 if r["record_id"] == "r1")["labels"] == [{"symbol": "NVDA", "stance": "add"}]

# a model answer marked unavailable falls back for that record only
def batch_unavail(items):
    return {i["id"]: {"labels": [], "note": "unavailable"} for i in items}, {"model": None}
rows3, d3 = gs.run(records, set(), label_post=post, label_batch=batch_unavail, textpack=lambda i: None, now=NOW)
assert [r["understood_by"] for r in rows3] == ["ce4_fallback", "ce4_fallback", "gemini"] and d3["text_basis"]["feed_excerpt"] == 1

# trial cap: unsent records are not written (they stay for the scheduled run), no fallback
calls.clear()
rows4, d4 = gs.run(records, set(), max_calls=1, label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW)
assert [r["record_id"] for r in rows4] == ["r1", "r2"] and d4["remaining"] == 1 and d4["trial"] is True

# append-only ledger: records already observed are never relabelled
with tempfile.TemporaryDirectory() as t:
    p = Path(t) / "rows.jsonl"
    gs.append_jsonl(p, rows4)
    done = {r["record_id"] for r in gs.read_jsonl(p)}
    rows5, _ = gs.run(records, done, label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW)
    assert [r["record_id"] for r in rows5] == ["r5"]

# labels and ids only: no text field leaks into the ledger
blob = json.dumps(rows + rows2 + rows3, ensure_ascii=False)
assert "加仓了" not in blob and "FULL TEXT" not in blob
src = (ROOT / "gemini_shadow.py").read_text(encoding="utf-8")
assert "research_feed" in src and "FEED.write" not in src and "production_use\": False" in src
print("PASS gemini shadow: Gemini first, ce-4 fallback marked, 429 -> fallback, trial cap, append-only, no text, production_use=false")
