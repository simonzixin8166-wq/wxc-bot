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
assert gs.SHADOW_BATCH == 20      # Owner 11/19 option A
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


rows, daily = gs.run(records, set(), backfill=False, label_post=post, label_batch=batch, textpack=lambda i: "FULL TEXT", now=NOW)
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
rows2, d2 = gs.run(records, set(), backfill=False, label_post=post, label_batch=batch429, textpack=lambda i: None, now=NOW)
assert {r["understood_by"] for r in rows2} == {"ce4_fallback"} and d2["quota_stop"] == "http_429" and d2["coverage"] == 0.0
assert next(r for r in rows2 if r["record_id"] == "r1")["labels"] == [{"symbol": "NVDA", "stance": "add"}]

# a model answer marked unavailable falls back for that record only
def batch_unavail(items):
    return {i["id"]: {"labels": [], "note": "unavailable"} for i in items}, {"model": None}
rows3, d3 = gs.run(records, set(), backfill=False, label_post=post, label_batch=batch_unavail, textpack=lambda i: None, now=NOW)
assert [r["understood_by"] for r in rows3] == ["ce4_fallback", "ce4_fallback", "gemini"] and d3["text_basis"]["feed_excerpt"] == 1

# trial cap: unsent records are not written (they stay for the scheduled run), no fallback
calls.clear()
rows4, d4 = gs.run(records, set(), max_calls=1, backfill=False, label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW)
assert [r["record_id"] for r in rows4] == ["r1", "r2"] and d4["remaining"] == 1 and d4["trial"] is True

# append-only ledger: records already observed are never relabelled
with tempfile.TemporaryDirectory() as t:
    p = Path(t) / "rows.jsonl"
    gs.append_jsonl(p, rows4)
    done = {r["record_id"] for r in gs.read_jsonl(p)}
    rows5, _ = gs.run(records, done, backfill=False, label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW)
    assert [r["record_id"] for r in rows5] == ["r5"]

# labels and ids only: no text field leaks into the ledger
blob = json.dumps(rows + rows2 + rows3, ensure_ascii=False)
assert "加仓了" not in blob and "FULL TEXT" not in blob
src = (ROOT / "gemini_shadow.py").read_text(encoding="utf-8")
assert "research_feed" in src and "FEED.write" not in src and "production_use\": False" in src
print("PASS gemini shadow: Gemini first, ce-4 fallback marked, 429 -> fallback, trial cap, append-only, no text, production_use=false")

# a model error falls back now and is retried by the next run; the error status is recorded (11/17 run 2)
def batch_err(items):
    return {i["id"]: {"labels": [], "note": "unavailable"} for i in items}, {"model": None, "status": 503}
rows6, d6 = gs.run(records, set(), backfill=False, label_post=post, label_batch=batch_err, textpack=lambda i: "x", now=NOW)
assert d6["errors"] == {"503": 1} and {r["record_id"] for r in rows6 if r["understood_by"] == "ce4_fallback"} == {"r1", "r2"}
retry = {r["record_id"] for r in rows6 if r["understood_by"] == "ce4_fallback"}
done = {r["record_id"] for r in rows6 if r["understood_by"] == "gemini"}
rows7, d7 = gs.run(records, done, backfill=False, label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW, retry=retry)
assert [(r["record_id"], r["understood_by"]) for r in rows7] == [("r1", "gemini"), ("r2", "gemini")] and d7["retried"] == 2
print("PASS shadow retry: model error -> fallback with status recorded, retried next run and superseded")
wf = (ROOT / ".github/workflows/gemini-shadow.yml").read_text(encoding="utf-8")
assert 'GEMINI_CLAIMS_TIMEOUT: "240"' in wf and "timeout-minutes: 150" in wf
print("PASS shadow workflow: 240 s read timeout for 20-post batches")

# backlog (Owner 11/21): records before the window are labelled after it, newest first; only Gemini-labelled rows
# are written (basis=backfill) and they stay out of the window statistics; a per-run call cap bounds the backlog
calls.clear()
old = [rec(10 + k, day="2026-11-0%d" % (1 + k % 9)) for k in range(25)]
rows8, d8 = gs.run(records + old, set(), label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW)
win = [r for r in rows8 if r.get("basis") != "backfill"]
back = [r for r in rows8 if r.get("basis") == "backfill"]
assert [r["record_id"] for r in win] == ["r1", "r2", "r5"] and d8["records"] == 3 and d8["coverage"] == 1.0
assert len(back) == 26 and all(r["understood_by"] == "gemini" for r in back)          # 25 old + r3 (11/10)
assert d8["backfill"] == {"pending_before": 26, "labelled": 26, "calls": 2, "remaining": 0}
# window articles (r5) go before any backlog batch (11/23: 27 newsletter articles were starved by the backlog)
assert calls[0] == ("batch", ["r1", "r2"]) and calls[1][0] == "post" and calls[2][0] == "batch" and len(calls[2][1]) == 20
first_back = calls[2][1]
old_ids = [r["id"] for r in sorted(old + [records[2]], key=lambda r: (r["captured_at"], r["id"]), reverse=True)]
assert first_back == old_ids[:20]
# unavailable answers are not written for the backlog; the cap stops backlog calls but never the window
rows9, d9 = gs.run(records + old, set(), label_post=post, label_batch=batch_unavail, textpack=lambda i: None, now=NOW)
assert not [r for r in rows9 if r.get("basis") == "backfill"] and d9["backfill"]["remaining"] == 26
gs.BACKFILL_MAX_CALLS = 1
rows10, d10 = gs.run(records + old, set(), label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW)
assert d10["backfill"]["calls"] == 1 and d10["backfill"]["labelled"] == 20 and d10["records"] == 3
# already labelled backlog records are not sent again
done = {r["record_id"] for r in rows8}
rows11, d11 = gs.run(records + old, done, label_post=post, label_batch=batch, textpack=lambda i: "x", now=NOW)
assert rows11 == [] and d11["backfill"]["pending_before"] == 0
print("PASS shadow backlog: window first, backlog newest first, Gemini-only rows, per-run cap, out of window stats")


# token usage (Owner 2026-11-24): Gemini's reported counts are summed per run and kept in the daily row
def batch_u(items):
    return ({i["id"]: {"labels": [], "note": None} for i in items},
            {"model": "m1", "usage": {"input": 5000, "output": 900, "thinking": 1500, "total": 7400}})
def post_u(title, text):
    return ({"labels": [], "note": None}, {"model": "m1", "usage": {"input": 2500, "output": 400, "thinking": 600, "total": 3500}})
gs.BACKFILL_MAX_CALLS = 12
_, du = gs.run(records, set(), backfill=False, label_post=post_u, label_batch=batch_u, textpack=lambda i: "x", now=NOW)
assert du["tokens"] == {"input": 7500, "output": 1300, "thinking": 2100, "total": 10900, "calls_with_usage": 2,
                        "by_model": {"m1": {"total": 10900, "calls": 2}}}, du["tokens"]
assert gs.gc.usage({"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3, "totalTokenCount": 13}}) == \
    {"input": 10, "output": 3, "thinking": 0, "total": 13} and gs.gc.usage({}) == {"input": 0, "output": 0, "thinking": 0, "total": 0}
print("PASS shadow tokens: usageMetadata summed per run into the daily row")
