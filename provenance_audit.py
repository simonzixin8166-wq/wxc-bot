#!/usr/bin/env python3
"""M1 provenance audit (quant-dashboard#133 6107376896 / 6109126287). Read-only; never edits the feed.

For every feed record without a recorded capture mode, derive provenance only from provable evidence:
the first git commit (GitHub-side commit time) in which the record id appears in state/research_feed.json.
  near_publication_observed : first seen ≤ 36 h after the post's published_at (timezone of published_at is
                              not recorded, so the window is generous) — observed close to publication
  delayed_capture           : 36–72 h
  backfill_proven           : > 72 h after publication (e.g. posts from before the feed existed)
  unprovable                : no published_at or no git appearance — never guessed
Video records are additionally checked for transcript authenticity (provider navigation pages
masquerading as transcripts) using claim_extractor.provider_boilerplate on the stored excerpt.
Output: state/provenance_audit.json (ids, classes, evidence timestamps; no text).
"""
from __future__ import annotations
import json, subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "state" / "research_feed.json"
OUT = ROOT / "state" / "provenance_audit.json"


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout


def first_seen():
    seen = {}
    for line in git("log", "--reverse", "--format=%H %cI", "--", "state/research_feed.json").splitlines():
        sha, t = line.split()
        try:
            recs = json.loads(git("show", f"{sha}:state/research_feed.json") or "{}").get("records") or []
        except json.JSONDecodeError:
            continue
        for r in recs:
            seen.setdefault(r.get("id"), (t, sha))
    return seen


def parse(ts):
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace(" ", "T"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def classify(published, first):
    p, f = parse(published), parse(first)
    if not p or not f:
        return "unprovable", None
    gap = (f - p).total_seconds() / 3600
    if gap <= 36:
        return "near_publication_observed", round(gap, 1)
    if gap <= 72:
        return "delayed_capture", round(gap, 1)
    return "backfill_proven", round(gap, 1)


def main():
    import claim_extractor as ce
    feed = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    fs = first_seen()
    rows, cls = [], Counter()
    for r in feed:
        recorded = r.get("intake_class_hint") or r.get("capture_mode")
        t, sha = fs.get(r["id"], (None, None))
        c, gap = classify(r.get("published_at"), t)
        row = {"id": r["id"], "kind": r.get("source_kind"), "author": r.get("author"), "recorded_provenance": recorded,
               "published_at": r.get("published_at"), "first_git_seen": t, "first_git_commit": sha,
               "gap_hours": gap, "derived_provenance": c}
        if r.get("source_kind") == "video":
            row["transcript_check"] = ("provider_navigation_page" if ce.provider_boilerplate(r.get("excerpt") or "")
                                       else ("excerpt_present" if int(r.get("content_chars") or 0) > 0 else "no_text"))
            row["transcript_status"] = r.get("transcript_status")
            row["content_quality"] = r.get("content_quality")
        rows.append(row)
        if not recorded:
            cls[c] += 1
    unrec = [x for x in rows if not x["recorded_provenance"]]
    conflict = [x["id"] for x in rows if x["recorded_provenance"] in ("live_candidate", "scheduled_board_anchor_scan")
                and x["derived_provenance"] == "backfill_proven"]
    vids = [x for x in rows if x["kind"] == "video"]
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "records": len(rows), "without_recorded_provenance": len(unrec),
           "derived_for_unrecorded": dict(cls),
           "recorded_live_but_gap_over_72h": conflict,
           "video_transcripts": dict(Counter(x["transcript_check"] for x in vids)),
           "video_transcript_status": dict(Counter(str(x.get("transcript_status")) for x in vids)),
           "method": "first git appearance of the record id in state/research_feed.json vs published_at (timezone not recorded); unprovable is never guessed",
           "rows": rows}
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("records", "without_recorded_provenance", "derived_for_unrecorded",
                                         "video_transcripts", "video_transcript_status")}, ensure_ascii=False),
          "conflicts:", len(conflict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
