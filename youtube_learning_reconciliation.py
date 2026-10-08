#!/usr/bin/env python3
"""P2-9 YouTube learning reconciliation: every seen video is in exactly one stage.

Seen ≠ learned. Stages (highest reached wins, each video counted once):
  formal_feed_text      in research_feed (forward or timestamp-unknown backfill) with text
  transcript_readable   historical archive Q1/Q2 (full transcript text available)
  partial_text          historical archive Q3/Q4 (short/partial text)
  metadata_only         probed; only title/description metadata (Q5)
  pending_unprobed      discovered, no content probe yet
  historical_backlog    older video accounted for but not yet scheduled for learning
Learning layers reported on top (never inferred from 'seen'):
  semantically_understood  text that produced lessons/representative points
  falsifiable_claims       structured operations or rule candidates from the text
  matured_outcomes         claims with matured forward outcomes (no YouTube outcome tracker yet → 0)
Inconsistencies (a video listed in more than one state file) are reported, not hidden.
Read-only over state/; writes state/youtube_learning_reconciliation.json.
"""
from __future__ import annotations
import json, os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.getenv("DATA_DIR", "state"))
OUT = STATE / "youtube_learning_reconciliation.json"


def load(name, default):
    try:
        return json.loads((STATE / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def video_id_from_url(url):
    url = str(url or "")
    return url.split("v=")[-1].split("&")[0] if "v=" in url else None


def build(now=None):
    seen = list(dict.fromkeys(load("seen_youtube.json", {}).get("video_ids") or []))
    pending = {r["video_id"]: r for r in load("pending_youtube.json", {}).get("records") or [] if r.get("video_id")}
    backlog = {r["video_id"]: r for r in load("youtube_historical_backlog.json", {}).get("records") or [] if r.get("video_id")}
    archive = {r["video_id"]: r for r in load("youtube_learning_archive.json", {}).get("records") or [] if r.get("video_id")}
    feed = {}
    for r in load("research_feed.json", {}).get("records") or []:
        vid = (r.get("youtube") or {}).get("video_id") or r.get("video_id") or video_id_from_url(r.get("url"))
        if vid and (r.get("source") == "youtube" or r.get("source_kind") == "video"):
            feed[vid] = r

    stage, learned, claims, author_of = {}, set(), set(), {}
    overlaps = Counter()
    for vid in seen:
        homes = [n for n, d in (("feed", feed), ("archive", archive), ("pending", pending), ("backlog", backlog)) if vid in d]
        if len(homes) > 1:
            overlaps["+".join(homes)] += 1
        a = archive.get(vid) or {}
        f = feed.get(vid) or {}
        p = pending.get(vid) or {}
        author_of[vid] = f.get("author") or a.get("author") or p.get("author") or (backlog.get(vid) or {}).get("author") or "unknown"
        if vid in feed and (f.get("excerpt") or f.get("content_chars")):
            stage[vid] = "formal_feed_text"
        elif a.get("quality") in ("Q1", "Q2"):
            stage[vid] = "transcript_readable"
        elif a.get("quality") in ("Q3", "Q4"):
            stage[vid] = "partial_text"
        elif a.get("quality") == "Q5" or p.get("last_status") == "metadata_only":
            stage[vid] = "metadata_only"
        elif vid in pending:
            stage[vid] = "pending_unprobed"
        elif vid in backlog:
            stage[vid] = "historical_backlog"
        else:
            stage[vid] = "unaccounted"
        if a.get("lessons") or a.get("representative_points") or f.get("lessons"):
            learned.add(vid)
        if a.get("operations") or f.get("operations") or a.get("rule_candidate_capable_at_source"):
            claims.add(vid)

    by_stage = Counter(stage.values())
    by_author = defaultdict(Counter)
    for vid, st in stage.items():
        by_author[author_of[vid]][st] += 1
    provider = load("youtube_provider_health.json", {})
    status = load("youtube_source_status.json", {})
    budget = int(status.get("content_work_budget") or 0)
    pend_n = by_stage.get("pending_unprobed", 0)
    return {
        "version": 1,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "principle": "seen is discovery, not learning; each video is counted once in its highest stage",
        "seen": len(seen),
        "stages": dict(sorted(by_stage.items())),
        "stages_sum_equals_seen": sum(by_stage.values()) == len(seen),
        "learning_layers": {
            "text_available": by_stage.get("formal_feed_text", 0) + by_stage.get("transcript_readable", 0) + by_stage.get("partial_text", 0),
            "semantically_understood": len(learned),
            "falsifiable_claims_or_rule_capable": len(claims),
            "matured_outcomes": 0,
            "matured_outcomes_note": "no YouTube claim outcome tracker yet; never inferred",
        },
        "by_author": {k: dict(v) for k, v in sorted(by_author.items())},
        "inconsistencies": {"videos_in_multiple_state_files": dict(overlaps)},
        "provider": {"probes": provider.get("probe_count"), "available": provider.get("available_count"),
                     "rule_candidate_capable": provider.get("rule_candidate_capable_count")},
        "backlog_eta": {"content_work_budget_per_run": budget,
                        "pending_unprobed": pend_n,
                        "runs_to_probe_all_pending": (-(-pend_n // budget)) if budget else None,
                        "note": "free-first: bounded per-run budget, provider limits respected"},
        "guardrails": ["historical/backlog videos are never Genuine Forward",
                       "metadata-only titles are not learning", "no paid providers added"],
    }


def main():
    out = build()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("seen", "stages", "stages_sum_equals_seen", "learning_layers", "inconsistencies")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
