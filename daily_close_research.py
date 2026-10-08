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
        for pid in re.findall(r"(?:/cfzh/)?(\d+)\.html", html or ""):
            if pid not in seen:
                seen.add(pid); out.append(pid)
    return out

def collect_forum():
    authors=agent.load_watch()
    state={}
    prior=_read(FORUM_SCAN_STATE,{})
    prior_anchor=str(prior.get("anchor_id") or "")
    prior_version=int(prior.get("version") or 0)

    # Migration from the legacy fixed-page scanner: use the highest already-seen
    # forum id as the prior anchor. A missing prior anchor must never mean
    # "complete"; we first have to prove continuity to a known old observation.
    legacy_seen=[]
    for author in authors:
        for value in agent.load_seen(author):
            try: legacy_seen.append(int(value))
            except Exception: pass
    legacy_anchor=str(max(legacy_seen)) if legacy_seen else ""
    if prior_version<2 and legacy_anchor:
        prior_anchor=legacy_anchor

    prior_complete=bool(prior.get("complete",False)) if prior_version>=2 else False
    prior_budget=int(prior.get("next_scan_pages") or FORUM_DAILY_PAGES)
    budget=FORUM_DAILY_PAGES if prior_complete else min(FORUM_MAX_SCAN_PAGES,max(FORUM_DAILY_PAGES,prior_budget))

    # First prove list continuity. This is necessary but not sufficient for an
    # overall complete cycle: every newly visible entry must also be durably
    # processed or the batch stays fail-closed.
    scan_attempts=[]
    while True:
        htmls=agent.list_pages(budget,state)
        all_ids=_all_forum_ids(htmls)
        anchor_found=bool(prior_anchor) and prior_anchor in set(all_ids)
        scan_attempts.append({"pages":budget,"html_pages":len(htmls),"anchor_found":anchor_found})
        if anchor_found or budget>=FORUM_MAX_SCAN_PAGES:
            break
        budget=min(FORUM_MAX_SCAN_PAGES,max(budget+1,budget*2))

    reached_end=False
    continuity_complete=bool(htmls) and bool(anchor_found)
    discovered_by_author={}
    processed_by_author={}
    unresolved_by_author={}
    pending_rows=[]
    seen_targets={}

    for author in authors:
        entries=agent.entries_for(author,htmls)
        seen_entries_path=FORUM_SCAN_STATE.parent/f"seen_forum_entries_{author}.json"
        entry_state_exists=seen_entries_path.exists()
        seen_entries=set(_read(seen_entries_path,[]))
        legacy_seen={str(x) for x in agent.load_seen(author)}

        # One-time migration: legacy main posts were tracked by parent post id.
        # Replies remain intentionally unseeded because old post-id tracking
        # collapsed multiple reply entries.
        if not entry_state_exists:
            for key,entry in entries.items():
                if entry.get("entry_kind")=="post" and str(entry.get("parent_post_id") or "") in legacy_seen:
                    seen_entries.add(key)
            _write(seen_entries_path,sorted(seen_entries))

        new_keys=[k for k in entries if k not in seen_entries]
        new_entries=sorted(
            (entries[k] for k in new_keys),
            key=lambda x:(str(x.get("published_at") or ""),str(x.get("entry_key") or "")),
            reverse=True,
        )
        discovered_by_author[author]=len(new_entries)

        posts=agent.fetch_entries(new_entries,state) if new_entries else []
        processed_keys={str(p.get("source_entry_key") or "") for p in posts if p.get("source_entry_key")}
        unresolved=[x for x in new_entries if str(x.get("entry_key") or "") not in processed_keys]
        processed_by_author[author]=len(processed_keys)
        unresolved_by_author[author]=len(unresolved)

        # Do not mark anything as seen yet. Entries become "seen" only after
        # their feed row is durably persisted (verified below); unresolved or
        # unpersisted entries stay retryable on the next scan.
        seen_targets[author]=(seen_entries_path,seen_entries)

        if posts:
            pending_rows.extend((author,p) for p in posts)

    processing_complete=all(int(v or 0)==0 for v in unresolved_by_author.values())
    complete=continuity_complete and processing_complete

    # Only after the whole batch is known complete may records be admitted as
    # live candidates. Any continuity or processing gap demotes the entire batch
    # to backfill/non-forward, preventing partial-batch forward contamination.
    added=0
    rows=[]
    row_entry=[]
    for author,p in pending_rows:
        row=rf.normalize("forum",author,p)
        row_entry.append((author,str(p.get("source_entry_key") or ""),row.get("id")))
        row["capture_mode"]="scheduled_forum_anchor_scan"
        row["intake_class_hint"]="live_candidate" if complete else "backfill"
        if not complete:
            row["forward_evidence_eligible"]=False
            row["source_notice"]="论坛本轮未形成完整采集闭环；记录保留用于历史学习，但不计入 Genuine Forward。"
        rows.append(row)
    if rows:
        # Raises on write failure: nothing is marked seen, the anchor does not
        # move, and the whole batch is retried on the next run.
        added=rf.append_records(rows)

    # Persist-then-acknowledge: mark an entry seen only when its row is
    # verifiably present in the canonical feed on disk.
    persisted=rf.persisted_ids([rid for _,_,rid in row_entry]) if row_entry else set()
    unpersisted_by_author={}
    for author,key,rid in row_entry:
        if not key:continue
        if rid in persisted:
            seen_targets[author][1].add(key)
        else:
            unpersisted_by_author[author]=unpersisted_by_author.get(author,0)+1
    for author,(path,entries) in seen_targets.items():
        _write(path,sorted(entries))
    for author,n in unpersisted_by_author.items():
        unresolved_by_author[author]=unresolved_by_author.get(author,0)+n
    if unpersisted_by_author:
        processing_complete=False
        complete=False

    newest=(str(max(int(x) for x in all_ids)) if all_ids else prior_anchor or None)
    # Never advance the anchor on an incomplete batch. Otherwise an unresolved
    # entry could fall behind the next anchor and become permanently invisible.
    next_pages=FORUM_DAILY_PAGES if complete else min(FORUM_MAX_SCAN_PAGES,max(budget+1,budget*2))
    scan_state={
        "version":3,
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "anchor_id":newest if complete and newest else prior_anchor or None,
        "previous_anchor_id":prior_anchor or None,
        "legacy_seen_anchor_id":legacy_anchor or None,
        "complete":complete,
        "continuity_complete":continuity_complete,
        "processing_complete":processing_complete,
        "pages_scanned":len(htmls),
        "scan_budget":budget,
        "scan_attempts":scan_attempts,
        "next_scan_pages":next_pages,
    }
    _write(FORUM_SCAN_STATE,scan_state)
    _write(FORUM_STATUS,{
        **scan_state,
        "status":"complete" if complete else "partial",
        "anchor_found":anchor_found,
        "reached_end":reached_end,
        "continuity_proven":continuity_complete,
        "scan_attempts":scan_attempts,
        "authors":authors,
        "new_entries_by_author":discovered_by_author,
        "processed_entries_by_author":processed_by_author,
        "unresolved_entries_by_author":unresolved_by_author,
        "unresolved_entries_total":sum(unresolved_by_author.values()),
        "feed_records_added":added,
        "guardrail":"complete requires both continuity to the prior anchor and durable processing of every newly visible entry. Unresolved entries keep the batch partial, block anchor advancement, and prevent Genuine Forward admission.",
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
        result=rf.capture_blog_profile(name,days=days,return_report=True)
        rows=result.get("fresh") or []
        report=result.get("report") or {}
        blog_batches[name]=rows
        previous_success=prior.get("last_success_at")
        missing=int(report.get("missing_from_feed") or 0)
        complete=bool(report.get("scan_complete")) and missing==0
        blog_state.setdefault("authors",{})[name]={
            "last_success_at":now.isoformat() if complete else previous_success,
            "last_attempt_at":now.isoformat(),
            "scan_complete":complete,
            "recovery_days_used":days,
            "new_records":len(rows),
            "article_links_found":report.get("article_links_found",0),
            "posts_parsed":report.get("posts_parsed",0),
            "unique_article_ids":report.get("unique_article_ids",0),
            "parsed_unique_urls":report.get("parsed_unique_urls",0),
            "feed_present_urls":report.get("feed_present_urls",0),
            "missing_from_feed":missing,
            "missing_from_feed_urls":report.get("missing_from_feed_urls") or [],
            "seen_total":report.get("seen_total",0),
            "archive_months":report.get("archive_months",0),
            "archive_months_ok":report.get("archive_months_ok") or [],
            "archive_failures":report.get("archive_failures") or [],
            "overview_ok":report.get("overview_ok"),
            "retention_policy":report.get("retention_policy"),
        }
    blog_state["version"]=1
    blog_state["updated_at"]=now.isoformat()
    blog_state["policy"]="recovery window expands from the last complete scheduled scan; failed archive months or parsed URLs missing from canonical feed do not advance last_success_at; article discovery has no count cap"
    _write(BLOG_SCAN_STATE,blog_state)

    blog_added=sum(len(rows) for rows in blog_batches.values())
    day=datetime.now().strftime("%Y-%m-%d")
    digest=rf.daily_digest_text(day)
    forum_note="complete" if forum_scan.get("complete") else f"partial,next={forum_scan.get('next_scan_pages')} pages"
    agent.say(digest+f"\n\n本轮新增：论坛 {forum_added} 条（{forum_note}）；作者博客 {blog_added} 条。YouTube 由独立 youtube-forward-intake 持续采集。")
    print(digest)

if __name__ == "__main__":
    main()
