#!/usr/bin/env python3
"""Gemini understanding · shadow observation (Owner 2026-11-16: option "A + fallback", 2 weeks 11/17-11/30).

Every day, right after the free-tier quota resets, Gemini labels the author claims of the new feed records
(Owner forum exports in batched forum mode; Owner-forwarded articles one by one, full text read at runtime from the
private textpack). A record Gemini could not label (quota stop, model unavailable, no text) falls back to the
production ce-4 claims already stored on the feed record. Every row says who understood it: gemini | ce4_fallback.

Shadow only: reads state/research_feed.json, never writes it; every row is production_use=false and nothing here
feeds Daily, judgments, alerts or the brief. Labels and ids only, no source text is written.

Same model, prompts and schema validation as the frozen-test measurement; forum posts go 20 per call (11/19) (gemini_claims.py, measured
2026-11-16: v5 P 52/54 R 52/70; forum P 31/36 R 31/48).

A ce-4 fallback is not final: the next run (inside the window) tries Gemini again, and a later row supersedes
the earlier one (latest row per record wins). Daily stats record HTTP error statuses.

Outputs (append-only):
  research/shadow/gemini_shadow_rows.jsonl   one row per feed record (labels, ce-4 labels, understood_by)
  research/shadow/gemini_shadow_daily.jsonl  one stats row per run day
Decision gate for the Owner at the December review: coverage >= 90% and spot-checked precision >= 85%.
Backlog (Owner 2026-11-21): records captured before SHADOW_FROM are labelled with the quota left after the
window, newest first; their rows carry basis=backfill and stay out of the window statistics.

  python gemini_shadow.py                 # label every eligible record since SHADOW_FROM not yet in the ledger
  python gemini_shadow.py --max-calls 3   # small trial
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import gemini_claims as gc

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "state" / "research_feed.json"
OUT_DIR = ROOT / "research" / "shadow"
ROWS = OUT_DIR / "gemini_shadow_rows.jsonl"
DAILY = OUT_DIR / "gemini_shadow_daily.jsonl"
VERSION = "gemini-shadow-0.1"
SHADOW_FROM = os.getenv("GEMINI_SHADOW_FROM", "2026-11-16")      # records captured on/after this UTC date
SHADOW_UNTIL = os.getenv("GEMINI_SHADOW_UNTIL", "2026-11-30")    # last observation day (Owner: 2 weeks)
PROVENANCE = ("owner_forum_export", "owner_forward")
# Owner 2026-11-19 (option A): ~86 forum posts a day at 8 per call ran out of free-tier calls; 20 per call
# (spot-checked on the forum dev set before the December review; the frozen measurement used 8)
SHADOW_BATCH = int(os.getenv("GEMINI_SHADOW_BATCH", "20"))
# Owner 2026-11-21: all Gemini quota goes to forum/blog first, the new records and every earlier one. Records
# captured before SHADOW_FROM are labelled after the window's records with whatever quota is left (newest first,
# at most BACKFILL_MAX_CALLS calls per run); a backfill record gets a row only once Gemini labelled it (its stored
# ce-4 claims stay as they are until then). Backfill rows never enter the window's coverage/gate statistics.
BACKFILL_FROM = os.getenv("GEMINI_BACKFILL_FROM", "2026-01-01")
BACKFILL_MAX_CALLS = int(os.getenv("GEMINI_BACKFILL_MAX_CALLS", "12"))
POS = {"buy", "add", "bullish", "hold"}


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def append_jsonl(p: Path, rows: list[dict]) -> None:
    if not rows:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def _as_list(x):
    if isinstance(x, list):
        return x
    if isinstance(x, str) and x.strip().startswith("["):
        try:
            import ast
            v = ast.literal_eval(x)
            return v if isinstance(v, list) else []
        except (ValueError, SyntaxError):
            return []
    return []


def ce4_labels(rec: dict) -> list[dict]:
    """Production ce-4 claims already on the feed record (what production uses today)."""
    out = []
    for c in _as_list(rec.get("claims")):
        if isinstance(c, dict) and c.get("symbol") and c.get("stance"):
            out.append({"symbol": str(c["symbol"]).upper(), "stance": str(c["stance"])})
    return out


def backfill_eligible(records: list[dict], done: set) -> list[dict]:
    out = [r for r in records if r.get("intake_provenance") in PROVENANCE and r.get("id") not in done
           and BACKFILL_FROM <= str(r.get("captured_at") or "")[:10] < SHADOW_FROM]
    return sorted(out, key=lambda r: (str(r.get("captured_at") or ""), r["id"]), reverse=True)


def eligible(records: list[dict], done: set) -> list[dict]:
    out = []
    for r in records:
        if r.get("intake_provenance") not in PROVENANCE or r.get("id") in done:
            continue
        day = str(r.get("captured_at") or "")[:10]
        if SHADOW_FROM <= day <= SHADOW_UNTIL:
            out.append(r)
    return sorted(out, key=lambda r: (str(r.get("captured_at") or ""), r["id"]))


def _forum_item(r: dict) -> dict:
    title, ex = (r.get("title") or "").strip(), (r.get("excerpt") or "").strip()
    tc = r.get("thread_context")
    if isinstance(tc, str):
        try:
            import ast
            tc = ast.literal_eval(tc)
        except (ValueError, SyntaxError):
            tc = {}
    par = (tc or {}).get("in_reply_to") or {}
    return {"id": r["id"], "text": title if ex in ("", title) else f"{title}\n{ex}",
            "context": f"{par.get('author')}: {par.get('title')}" if par.get("title") else None}


def pairs(labels: list[dict]) -> dict:
    d = {}
    for l in labels:
        d.setdefault(l["symbol"], set()).add("pos" if l["stance"] in POS else "neg")
    return d


def run(records: list[dict], done: set, max_calls: int | None = None, label_post=None, label_batch=None,
        textpack=None, now=None, retry: set | None = None, backfill: bool = True) -> tuple[list[dict], dict]:
    """done = records Gemini already labelled; retry = records whose latest row is a ce-4 fallback (tried again)."""
    retry = retry or set()
    label_post = label_post or gc.label_post
    label_batch = label_batch or gc.label_batch
    textpack = textpack or gc._textpack_text
    now = now or datetime.now(timezone.utc)
    todo = eligible(records, done)
    back = backfill_eligible(records, done) if backfill else []
    back_ids = {r["id"] for r in back}
    answers, meta, stop = {}, {"calls": 0, "quota_stop": False, "text_basis": Counter(), "models": Counter(),
                                "errors": Counter(), "backfill_calls": 0}, False

    def budget_left(is_back=False):
        if is_back and meta["backfill_calls"] >= BACKFILL_MAX_CALLS:
            return False
        return max_calls is None or meta["calls"] < max_calls

    def chunks(rows):
        f = [r for r in rows if r["intake_provenance"] == "owner_forum_export"]
        return [f[k:k + SHADOW_BATCH] for k in range(0, len(f), SHADOW_BATCH)]

    forum_chunks = chunks(todo) + chunks(back)          # the window first, then the backlog
    longs = [r for r in todo + back if r["intake_provenance"] == "owner_forward"]
    longs.sort(key=lambda r: r["id"] in back_ids)        # window articles before backlog articles
    for chunk in forum_chunks:
        is_back = chunk[0]["id"] in back_ids
        if stop or not budget_left(is_back):
            if is_back:
                continue
            break
        try:
            got, m = label_batch([_forum_item(r) for r in chunk])
        except RuntimeError:
            meta["quota_stop"] = "http_429"; stop = True
            break
        meta["calls"] += 1; meta["models"][str(m.get("model"))] += 1; meta["backfill_calls"] += is_back
        if m.get("model") is None:
            meta["errors"][str(m.get("status"))] += 1
        for r in chunk:
            meta["text_basis"]["feed_title_excerpt"] += 1
            answers[r["id"]] = (got.get(r["id"]), m.get("model"))
        time.sleep(gc.PAUSE)
    for r in longs:
        is_back = r["id"] in back_ids
        if stop or not budget_left(is_back):
            if is_back:
                continue
            break
        body = textpack(r.get("owner_forward_item_id") or "") if r.get("owner_forward_item_id") else None
        basis = "full_text" if body else "feed_excerpt"
        body = body or (r.get("excerpt") or "")
        try:
            ans, m = label_post(r.get("title") or "", body)
        except RuntimeError:
            meta["quota_stop"] = "http_429"; stop = True
            break
        meta["calls"] += 1; meta["models"][str(m.get("model"))] += 1; meta["text_basis"][basis] += 1
        meta["backfill_calls"] += is_back
        if m.get("model") is None:
            meta["errors"][str(m.get("status"))] += 1
        answers[r["id"]] = (ans, m.get("model"))
        time.sleep(gc.PAUSE)

    rows, st = [], Counter()
    for r in back:   # backlog: a row only for what Gemini actually labelled; the rest waits for the next run
        ans, model = answers.get(r["id"], (None, None))
        if ans is None or ans.get("note") == "unavailable":
            continue
        labels = [{k: l.get(k) for k in ("symbol", "stance", "status") if l.get(k)} for l in ans["labels"]]
        rows.append({"version": VERSION, "record_id": r["id"], "provenance": r["intake_provenance"],
                     "source_entry_key": r.get("source_entry_key"), "author": r.get("author"),
                     "captured_at": r.get("captured_at"), "understood_by": "gemini", "model": model, "basis": "backfill",
                     "labels": labels, "ce4_labels": ce4_labels(r), "production_use": False,
                     "recorded_at": now.isoformat(timespec="seconds")})
        st["backfill_gemini"] += 1
    for r in todo:
        ce4 = ce4_labels(r)
        ans, model = answers.get(r["id"], (None, None))
        if r["id"] not in answers and not stop:
            continue  # never sent (trial cap): stays for the next run; only a quota stop forces the ce-4 fallback
        by = "gemini" if ans is not None and ans.get("note") != "unavailable" else "ce4_fallback"
        labels = [{k: l.get(k) for k in ("symbol", "stance", "status") if l.get(k)} for l in ans["labels"]] if by == "gemini" else ce4
        rows.append({"version": VERSION, "record_id": r["id"], "provenance": r["intake_provenance"],
                     "source_entry_key": r.get("source_entry_key"), "author": r.get("author"),
                     "captured_at": r.get("captured_at"), "understood_by": by, "model": model if by == "gemini" else None,
                     "labels": labels, "ce4_labels": ce4, "production_use": False, "recorded_at": now.isoformat(timespec="seconds")})
        st[by] += 1
        if by == "gemini":
            pg, pc = pairs(labels), pairs(ce4)
            st["gemini_pairs"] += len(pg); st["ce4_pairs"] += len(pc)
            both = set(pg) & set(pc)
            st["both_pairs"] += len(both); st["direction_agree"] += sum(1 for s in both if pg[s] & pc[s])
            st["gemini_only_pairs"] += len(set(pg) - set(pc)); st["ce4_only_pairs"] += len(set(pc) - set(pg))
    n = st["gemini"] + st["ce4_fallback"]
    daily = {"version": VERSION, "run_at": now.isoformat(timespec="seconds"), "day": now.date().isoformat(),
             "records": n, "gemini": st["gemini"], "ce4_fallback": st["ce4_fallback"],
             "coverage": round(st["gemini"] / n, 3) if n else None,
             "gemini_pairs": st["gemini_pairs"], "ce4_pairs": st["ce4_pairs"], "both_pairs": st["both_pairs"],
             "direction_agree": st["direction_agree"], "gemini_only_pairs": st["gemini_only_pairs"],
             "ce4_only_pairs": st["ce4_only_pairs"], "calls": meta["calls"], "quota_stop": meta["quota_stop"],
             "text_basis": dict(meta["text_basis"]), "models": dict(meta["models"]), "errors": dict(meta["errors"]),
             "retried": sum(1 for r in todo if r["id"] in retry), "batch": SHADOW_BATCH,
             "trial": max_calls is not None, "remaining": len(todo) - n,
             "backfill": {"pending_before": len(back), "labelled": st["backfill_gemini"], "calls": meta["backfill_calls"],
                          "remaining": len(back) - st["backfill_gemini"]},
             "production_use": False}
    return rows, daily


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=None)
    a = ap.parse_args(argv)
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set: shadow observation off")
        return 0
    records = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    # a record counts as done once Gemini labelled it; a ce-4 fallback (quota stop / model error) is retried by
    # the next runs inside the observation window, and the newer row supersedes it (append-only, latest wins)
    rows_all = read_jsonl(ROWS)
    gem = {r["record_id"] for r in rows_all if r.get("understood_by") == "gemini"}
    done = gem
    retry = {r["record_id"] for r in rows_all if r.get("understood_by") == "ce4_fallback"} - gem
    rows, daily = run(records, done, max_calls=a.max_calls, retry=retry)
    append_jsonl(ROWS, rows)
    append_jsonl(DAILY, [daily])
    print(json.dumps(daily, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
