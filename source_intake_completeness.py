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

def _youtube_id_from_url(url):
    s=str(url or "")
    if "v=" in s:return s.split("v=")[-1].split("&")[0]
    if "youtu.be/" in s:return s.split("youtu.be/")[-1].split("?")[0]
    return ""

def _ids(rows,key="video_id"):
    return {str(x.get(key) or "") for x in (rows or []) if str(x.get(key) or "")}

def build():
    forum=load("forum_source_status.json",{})
    blogs=load("blog_scan_state.json",{})
    yt=load("youtube_source_status.json",{})
    ytd=load("youtube_discovery_state.json",{})
    ytb=load("youtube_historical_backlog.json",{"records":[]})
    ytp=load("pending_youtube.json",{"records":[]})
    yts=load("seen_youtube.json",{"video_ids":[]})
    yta=load("youtube_learning_archive.json",{"records":[]})
    feed=load("research_feed.json",{"records":[]})

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
    pending_rows=ytp.get("records") or []
    backlog_rows=ytb.get("records") or []
    archive_rows=yta.get("records") or []
    pending=len(pending_rows)
    backlog=len(backlog_rows)

    seen={str(x) for x in (yts.get("video_ids") or []) if str(x)}
    pending_ids=_ids(pending_rows)
    backlog_ids=_ids(backlog_rows)
    archive_ids=_ids(archive_rows)
    learned_hist_ids={
        str(x.get("video_id"))
        for x in archive_rows
        if x.get("video_id") and x.get("historical_learning_eligible") is True
    }
    feed_ids=set()
    for row in (feed.get("records") or []):
        if row.get("source")!="youtube":continue
        vid=str((row.get("youtube") or {}).get("video_id") or row.get("video_id") or _youtube_id_from_url(row.get("url")) or "")
        if vid:feed_ids.add(vid)

    accounted_ids=feed_ids|archive_ids|pending_ids|backlog_ids
    unaccounted=sorted(seen-accounted_ids)
    youtube_accounting_balanced=(len(unaccounted)==0)
    youtube_coverage_complete=youtube_discovery_complete and youtube_accounting_balanced
    semantic_learned_ids=feed_ids|learned_hist_ids
    unresolved_semantic=sorted(seen-semantic_learned_ids)
    youtube_learning_complete=youtube_coverage_complete and len(unresolved_semantic)==0

    coverage_complete=forum_complete and blogs_complete and youtube_coverage_complete
    semantic_learning_complete=forum_complete and blogs_complete and youtube_learning_complete
    return {
      "version":2,
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "complete":coverage_complete,
      "coverage_complete":coverage_complete,
      "semantic_learning_complete":semantic_learning_complete,
      "forum":{
        "complete":forum_complete,
        "continuity_proven":forum.get("continuity_proven"),
        "anchor_id":forum.get("anchor_id"),
        "previous_anchor_id":forum.get("previous_anchor_id"),
        "status":forum.get("status"),
      },
      "blogs":{"complete":blogs_complete,"authors":blog_rows},
      "youtube":{
        "complete":youtube_coverage_complete,
        "coverage_complete":youtube_coverage_complete,
        "semantic_learning_complete":youtube_learning_complete,
        "discovery_complete":youtube_discovery_complete,
        "accounting_balanced":youtube_accounting_balanced,
        "seen":len(seen),
        "feed_records":len(feed_ids),
        "historical_archive_records":len(archive_ids),
        "historical_semantic_learned":len(learned_hist_ids),
        "pending":pending,
        "historical_backlog":backlog,
        "unaccounted":len(unaccounted),
        "unaccounted_video_ids":unaccounted[:50],
        "unresolved_semantic":len(unresolved_semantic),
        "status":yt.get("status"),
      },
      "guardrails":[
        "coverage_complete proves every discovered source is durably accounted; it does not claim every external item yielded learnable text.",
        "semantic_learning_complete additionally requires every discovered YouTube item to have formal-feed or Q1/Q2 historical semantic learning.",
        "Pending/backlog/provider-blocked items remain explicit and keep the external-source learning domain partial; they are never silently counted as learned."
      ]
    }

def main():
    out=build()
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False))

if __name__=="__main__":main()
