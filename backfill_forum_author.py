#!/usr/bin/env python3
"""One-time forum history backfill into state/research_feed.json.

Uses the forum's own latest timestamp as the clock anchor, walks list pages until
the requested cutoff is reached, then fetches only the requested author's posts.
The source feed keeps provenance and does not turn author opinions into trades.
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timedelta

import research_feed as rf
import wxc_scraper as w
import wxc_tg_bot as bot
import wxc_tg_agent as agent


def backfill(author: str, days: int, max_pages: int):
    state = {}
    first = bot.fetch(f"{w.BASE}?page=1", state)
    if not first:
        raise SystemExit("forum list page unavailable")
    ref = w.list_latest(first.text) or datetime.now()
    cutoff = ref - timedelta(days=days)

    ids = {}
    reached_cutoff = False
    for pg in range(1, max_pages + 1):
        r = first if pg == 1 else bot.fetch(f"{w.BASE}?page={pg}", state)
        if not r:
            continue
        for pid, href, _, _ in w.parse_list(r.text, author):
            ids[pid] = href
        if pg == 1 or pg % 25 == 0:
            print(json.dumps({"stage":"scan_pages","page":pg,"matched_ids":len(ids)}, ensure_ascii=False), flush=True)
        ds = w.list_dates(r.text)
        if ds and max(ds) < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
            reached_cutoff = True
            break

    ordered = sorted(ids, key=int, reverse=True)
    print(json.dumps({"stage":"fetch_posts","matched_ids":len(ordered)}, ensure_ascii=False), flush=True)
    posts = agent.fetch_posts(ordered, ids, state, since=cutoff)
    # Historical recovery is never Genuine Forward evidence.
    added = rf.add_forum_posts(author, posts, provenance={
        "intake_class_hint": "backfill",
        "capture_mode": "forum_author_backfill",
        "forward_evidence_eligible": False,
    })

    # Mark captured IDs as seen so the normal daily collector continues from here
    # instead of replaying the history window.
    seen = agent.load_seen(author)
    seen.update(p.get("id") for p in posts if p.get("id"))
    agent.save_seen(author, seen)

    dates = sorted(p.get("date","") for p in posts if p.get("date"))
    result = {
        "author": author,
        "requested_days": days,
        "forum_reference_time": ref.isoformat(),
        "cutoff": cutoff.isoformat(),
        "pages_scanned": pg,
        "reached_cutoff": reached_cutoff,
        "matched_ids": len(ids),
        "posts_fetched": len(posts),
        "feed_records_added": added,
        "earliest": dates[0] if dates else None,
        "latest": dates[-1] if dates else None,
    }
    print(json.dumps(result, ensure_ascii=False))
    if not reached_cutoff:
        print("WARNING: max_pages reached before the full requested window was proven complete")
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--author", required=True)
    ap.add_argument("--days", type=int, default=92)
    ap.add_argument("--max-pages", type=int, default=400)
    a=ap.parse_args()
    backfill(a.author, a.days, a.max_pages)

if __name__=="__main__":
    main()
