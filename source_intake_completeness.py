#!/usr/bin/env python3
"""Unified intake completeness contract for forum/blog/YouTube collectors."""
from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
STATE=ROOT/"state"
OUT=STATE/"source_intake_completeness.json"

def load(name,default=None):
    try:return json.loads((STATE/name).read_text(encoding="utf-8"))
    except Exception:return {} if default is None else default

def build():
    forum=load("forum_source_status.json",{})
    blogs=load("blog_scan_state.json",{})
    yt=load("youtube_source_status.json",{})
    ytd=load("youtube_discovery_state.json",{})
    ytb=load("youtube_historical_backlog.json",{"records":[]})
    ytp=load("pending_youtube.json",{"records":[]})

    authors=blogs.get("authors") or {}
    blog_rows={}
    for name,row in authors.items():
        missing=int(row.get("missing_from_feed") or 0)
        complete=bool(row.get("scan_complete")) and missing==0
        blog_rows[name]={
            "complete":complete,
            "scan_complete":bool(row.get("scan_complete")),
            "missing_from_feed":missing,
            "unique_article_ids":row.get("unique_article_ids"),
            "feed_present_urls":row.get("feed_present_urls"),
            "archive_failures":row.get("archive_failures") or [],
        }
    blogs_complete=bool(blog_rows) and all(x["complete"] for x in blog_rows.values())

    forum_complete=bool(forum.get("complete")) and bool(forum.get("continuity_proven"))
    youtube_discovery_complete=bool(ytd.get("complete"))
    pending=len(ytp.get("records") or [])
    backlog=len(ytb.get("records") or [])
    youtube_learning_complete=youtube_discovery_complete and pending==0 and backlog==0

    complete=forum_complete and blogs_complete and youtube_learning_complete
    return {
      "version":1,
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "complete":complete,
      "forum":{
        "complete":forum_complete,
        "continuity_proven":forum.get("continuity_proven"),
        "anchor_id":forum.get("anchor_id"),
        "previous_anchor_id":forum.get("previous_anchor_id"),
        "status":forum.get("status"),
      },
      "blogs":{"complete":blogs_complete,"authors":blog_rows},
      "youtube":{
        "complete":youtube_learning_complete,
        "discovery_complete":youtube_discovery_complete,
        "pending":pending,
        "historical_backlog":backlog,
        "status":yt.get("status"),
      },
      "guardrail":"complete=true requires proven forum continuity, zero blog feed gaps, proven YouTube discovery continuity, and zero unresolved YouTube pending/backlog items."
    }

def main():
    out=build()
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False))

if __name__=="__main__":main()
