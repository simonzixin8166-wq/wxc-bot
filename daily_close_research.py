#!/usr/bin/env python3
"""One daily post-close research collection cycle.

Collects:
- configured author blog additions from the recent window
- new forum posts from the currently subscribed authors
Then sends one TG digest and leaves normalized records in state/research_feed.json.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import wxc_tg_agent as agent
import research_feed as rf

FORUM_DAILY_PAGES = int(os.getenv("FORUM_DAILY_PAGES", "8"))
FORUM_MAX_SCAN_PAGES = int(os.getenv("FORUM_MAX_SCAN_PAGES", "256"))
BLOG_RECOVERY_DAYS = int(os.getenv("BLOG_RECOVERY_DAYS", "14"))
FORUM_SCAN_STATE = Path(os.getenv("FORUM_SCAN_STATE", "state/forum_daily_scan_state.json"))
FORUM_STATUS = Path(os.getenv("FORUM_STATUS", "state/forum_source_status.json"))
BLOG_SCAN_STATE = Path(os.getenv("BLOG_SCAN_STATE", "state/blog_scan_state.json"))

def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default

def _write(path, value):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

def _all_forum_ids(htmls):
    import re
    out=[]
    seen=set()
    for html in htmls:
        for pid in re.findall(r"/cfzh/(\d+)\.html", html or ""):
            if pid not in seen:
                seen.add(pid); out.append(pid)
    return out

def collect_forum():
    authors=agent.load_watch()
    state={}
    prior=_read(FORUM_SCAN_STATE,{})
    prior_anchor=str(prior.get("anchor_id") or "")
    prior_complete=bool(prior.get("complete", True))
    prior_budget=int(prior.get("next_scan_pages") or FORUM_DAILY_PAGES)
    budget=FORUM_DAILY_PAGES if prior_complete else min(FORUM_MAX_SCAN_PAGES,max(FORUM_DAILY_PAGES,prior_budget))
    htmls=agent.list_pages(budget,state)
    all_ids=_all_forum_ids(htmls)
    anchor_found=(not prior_anchor) or (prior_anchor in set(all_ids))
    reached_end=len(htmls)<budget
    complete=bool(htmls) and (anchor_found or reached_end)
    added=0
    discovered_by_author={}
    for author in authors:
        ids=agent.ids_for(author,htmls)
        seen=agent.load_seen(author)
        new=sorted((i for i in ids if i not in seen),key=int,reverse=True)
        discovered_by_author[author]=len(new)
        if not new:
            continue
        posts=agent.fetch_posts(new,ids,state)
        if not posts:
            continue
        rows=[rf.normalize("forum",author,p) for p in posts]
        for row in rows:
            row["capture_mode"]="scheduled_forum_anchor_scan"
            row["intake_class_hint"]="live_candidate" if complete else "backfill"
            if not complete:
                row["forward_evidence_eligible"]=False
                row["source_notice"]="论坛扫描尚未到达上次锚点；记录保留用于历史学习，但本轮不计入 Genuine Forward。"
        added+=rf.append_records(rows)
        seen.update(p["id"] for p in posts)
        agent.save_seen(author,seen)

    newest=all_ids[0] if all_ids else prior_anchor or None
    next_pages=FORUM_DAILY_PAGES if complete else min(FORUM_MAX_SCAN_PAGES,max(budget+1,budget*2))
    scan_state={
        "version":1,
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "anchor_id":newest if complete and newest else prior_anchor or None,
        "previous_anchor_id":prior_anchor or None,
        "complete":complete,
        "pages_scanned":len(htmls),
        "scan_budget":budget,
        "next_scan_pages":next_pages,
    }
    _write(FORUM_SCAN_STATE,scan_state)
    _write(FORUM_STATUS,{
        **scan_state,
        "status":"complete" if complete else "partial",
        "anchor_found":anchor_found,
        "reached_end":reached_end,
        "authors":authors,
        "new_ids_by_author":discovered_by_author,
        "feed_records_added":added,
        "guardrail":"partial scans never advance the prior anchor and never create Genuine Forward evidence; next run expands scan depth until the prior anchor/end is reached.",
    })
    return added,scan_state

def main():
    forum_added,forum_scan=collect_forum()

    blog_state=_read(BLOG_SCAN_STATE,{"authors":{}})
    blog_batches={}
    now=datetime.now(timezone.utc)
    for name in rf.BLOG_PROFILES:
        prior=((blog_state.get("authors") or {}).get(name) or {})
        last=prior.get("last_success_at")
        days=BLOG_RECOVERY_DAYS
        if last:
            try:
                last_dt=datetime.fromisoformat(str(last).replace("Z","+00:00"))
                if last_dt.tzinfo is None:last_dt=last_dt.replace(tzinfo=timezone.utc)
                elapsed=max(0,(now-last_dt).days+2)
                days=max(days,elapsed)
            except Exception:
                pass
        rows=rf.capture_blog_profile(name,days=days)
        blog_batches[name]=rows
        blog_state.setdefault("authors",{})[name]={
            "last_success_at":now.isoformat(),
            "recovery_days_used":days,
            "new_records":len(rows),
        }
    blog_state["version"]=1
    blog_state["updated_at"]=now.isoformat()
    blog_state["policy"]="recovery window expands from the last successful scheduled scan; it is not capped at 14 days"
    _write(BLOG_SCAN_STATE,blog_state)

    blog_added=sum(len(rows) for rows in blog_batches.values())
    day=datetime.now().strftime("%Y-%m-%d")
    digest=rf.daily_digest_text(day)
    forum_note="complete" if forum_scan.get("complete") else f"partial,next={forum_scan.get('next_scan_pages')} pages"
    agent.say(digest+f"\n\n本轮新增：论坛 {forum_added} 条（{forum_note}）；作者博客 {blog_added} 条。YouTube 由独立 youtube-forward-intake 持续采集。")
    print(digest)

if __name__ == "__main__":
    main()
