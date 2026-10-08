#!/usr/bin/env python3
"""Ingest ONE named historical forum post as research backfill (author's original post only).

Used for research requests such as #133 (jenning, 长持倍数基金的方法探讨). The post is
stored through the normal research feed (append-only, de-duplicated, manifest) with
backfill provenance, so it can never count as Genuine Forward evidence. Replies/comments
are not ingested and are never treated as the author's signal.
"""
from __future__ import annotations
import argparse, json, re, sys

import research_feed as rf
import wxc_scraper as w
import wxc_tg_bot as bot

ALLOWED = re.compile(r"^https://bbs\.wenxuecity\.com/[a-z0-9]+/\d+\.html$")


def ingest(url: str, expected_author: str, request_ref: str, fetch=None, parse=None) -> dict:
    if not ALLOWED.match(url):
        raise SystemExit(f"refusing non-forum-post URL: {url}")
    fetch = fetch or (lambda u: bot.fetch(u, {}))
    parse = parse or (lambda html, u: w.parse_post(html, u, with_comments=False))
    r = fetch(url)
    if not r:
        raise SystemExit("post page unavailable")
    post = parse(r.text, url)
    if not post:
        raise SystemExit("post could not be parsed")
    if expected_author and post.get("author") != expected_author:
        raise SystemExit(f"author mismatch: page says {post.get('author')!r}, expected {expected_author!r}")
    post.pop("comments", None)
    added = rf.add_forum_posts(post["author"], [post], provenance={
        "intake_class_hint": "backfill",
        "capture_mode": "single_post_research_backfill",
        "forward_evidence_eligible": False,
        "research_request": request_ref,
        "content_scope": "author_original_post_only",
    })
    return {"url": url, "author": post["author"], "published": post.get("date"), "title": post.get("title"),
            "text_chars": len(post.get("text") or ""), "feed_records_added": added,
            "deduplicated": added == 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--author", required=True)
    ap.add_argument("--request", default="")
    a = ap.parse_args()
    print(json.dumps(ingest(a.url, a.author, a.request), ensure_ascii=False))


if __name__ == "__main__":
    main()
