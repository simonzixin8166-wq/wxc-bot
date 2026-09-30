#!/usr/bin/env python3
"""One daily post-close research collection cycle.

Collects:
- BrightLine blog additions from the recent window
- new forum posts from the three currently subscribed authors
Then sends one TG digest and leaves normalized records in state/research_feed.json.
"""
from __future__ import annotations
from datetime import datetime
import wxc_tg_agent as agent
import research_feed as rf

def collect_forum():
    authors = agent.load_watch()
    state = {}
    htmls = agent.list_pages(4, state)
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
    blog_rows = rf.capture_brightline(days=2)
    day = datetime.now().strftime("%Y-%m-%d")
    digest = rf.daily_digest_text(day)
    agent.say(digest + f"\n\n本轮新增：论坛 {forum_added} 条；BrightLine 博客 {len(blog_rows)} 条。")
    print(digest)

if __name__ == "__main__":
    main()
