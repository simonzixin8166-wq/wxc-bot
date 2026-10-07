#!/usr/bin/env python3
"""One daily post-close research collection cycle.

Collects:
- configured author blog additions from the recent window
- new forum posts from the currently subscribed authors
Then sends one TG digest and leaves normalized records in state/research_feed.json.
"""
from __future__ import annotations
from datetime import datetime
import os
import wxc_tg_agent as agent
import research_feed as rf
import youtube_research as yt

FORUM_DAILY_PAGES = int(os.getenv("FORUM_DAILY_PAGES", "8"))
BLOG_RECOVERY_DAYS = int(os.getenv("BLOG_RECOVERY_DAYS", "14"))

def collect_forum():
    authors = agent.load_watch()
    state = {}
    # Shared scan: one set of list pages serves every subscribed author.
    htmls = agent.list_pages(FORUM_DAILY_PAGES, state)
    added = 0
    for author in authors:
        ids = agent.ids_for(author, htmls)
        seen = agent.load_seen(author)
        new = sorted((i for i in ids if i not in seen), key=int, reverse=True)[:60]
        if not new:
            continue
        posts = agent.fetch_posts(new, ids, state)
        if not posts:
            continue
        added += rf.add_forum_posts(author, posts)
        seen.update(p["id"] for p in posts)
        agent.save_seen(author, seen)
    return added

def main():
    forum_added = collect_forum()
    blog_batches = rf.capture_configured_blogs(days=BLOG_RECOVERY_DAYS)
    blog_added = sum(len(rows) for rows in blog_batches.values())
    youtube = yt.collect()
    day = datetime.now().strftime("%Y-%m-%d")
    digest = rf.daily_digest_text(day)
    agent.say(digest + f"\n\n本轮新增：论坛 {forum_added} 条；作者博客 {blog_added} 条；YouTube {youtube.get('feed_records_added',0)} 条。")
    print(digest)

if __name__ == "__main__":
    main()
