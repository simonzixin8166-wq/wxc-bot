#!/usr/bin/env python3
"""Recover legacy YouTube discovery-scan items into historical learning scope.

The 2026-10-08 scan-until-anchor migration intentionally expanded discovery
from latest-10 to a much deeper window. Those newly surfaced *older* videos
were added to the forward pending queue by the legacy code even though they
were not newly published. This repeatable recovery identifies the largest
historical one-step pending expansion from Git history and reclassifies only
those still-unresolved IDs into the non-gating historical backlog.

No item is deleted: it moves from forward-pending to explicit historical
learning backlog. Formal feed records and already semantically learned archive
records always win.
"""
from __future__ import annotations
import json,subprocess
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PENDING=ROOT/"state"/"pending_youtube.json"
BACKLOG=ROOT/"state"/"youtube_historical_backlog.json"
ARCHIVE=ROOT/"state"/"youtube_learning_archive.json"
FEED=ROOT/"state"/"research_feed.json"
REPORT=ROOT/"state"/"youtube_pending_scope_recovery.json"

def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT,text=True,stderr=subprocess.DEVNULL)

def parse(text,default=None):
    try:return json.loads(text)
    except Exception:return {} if default is None else default

def load(path,default=None):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:return {} if default is None else default

def ids(doc):
    return {str(x.get("video_id")) for x in (doc.get("records") or []) if x.get("video_id")}

def commits():
    raw=git("log","--format=%H","--",str(PENDING.relative_to(ROOT)))
    return [x for x in raw.splitlines() if x.strip()]

def version(sha):
    try:return parse(git("show",f"{sha}:{PENDING.relative_to(ROOT)}"),{"records":[]})
    except Exception:return {"records":[]}

def feed_ids():
    out=set()
    for row in load(FEED,{"records":[]}).get("records") or []:
        if row.get("source")!="youtube":continue
        vid=str((row.get("youtube") or {}).get("video_id") or row.get("video_id") or "")
        if not vid:
            url=str(row.get("url") or "")
            if "v=" in url:vid=url.split("v=")[-1].split("&")[0]
        if vid:out.add(vid)
    return out

def find_bulk_delta(history):
    snapshots=[]
    # commits() is newest->oldest; compare oldest->newest.
    for sha in reversed(history):
        doc=version(sha)
        snapshots.append((sha,ids(doc)))
    best={"added":set(),"from_sha":None,"to_sha":None,"before":0,"after":0}
    for (sha0,a),(sha1,b) in zip(snapshots,snapshots[1:]):
        added=b-a
        if len(added)>len(best["added"]):
            best={"added":added,"from_sha":sha0,"to_sha":sha1,"before":len(a),"after":len(b)}
    return best

def recover():
    now=datetime.now(timezone.utc).isoformat()
    history=commits()
    bulk=find_bulk_delta(history)
    current=load(PENDING,{"version":1,"records":[]})
    backlog=load(BACKLOG,{"version":1,"records":[]})
    archive=load(ARCHIVE,{"records":[]})
    feed=feed_ids()
    learned={
        str(x.get("video_id")) for x in (archive.get("records") or [])
        if x.get("video_id") and x.get("historical_learning_eligible") is True
    }
    current_rows={str(x.get("video_id")):dict(x) for x in (current.get("records") or []) if x.get("video_id")}
    backlog_rows={str(x.get("video_id")):dict(x) for x in (backlog.get("records") or []) if x.get("video_id")}

    moved=[]
    for vid in sorted(bulk["added"]):
        row=current_rows.get(vid)
        if not row or vid in feed or vid in learned:
            continue
        current_rows.pop(vid,None)
        hist=dict(backlog_rows.get(vid) or {})
        hist.update({k:v for k,v in row.items() if v not in (None,"")})
        hist["video_id"]=vid
        hist["status"]="historical_learning_backlog"
        hist["forward_evidence_eligible"]=False
        hist["recovery_reason"]="legacy_scan_until_anchor_bulk_discovery"
        hist["recovered_at"]=now
        backlog_rows[vid]=hist
        moved.append(vid)

    current_out=dict(current)
    current_out["records"]=sorted(current_rows.values(),key=lambda x:(str(x.get("first_discovered_at") or ""),str(x.get("video_id") or "")))
    current_out["scope_recovery"]={
        "completed_at":now,"bulk_from_sha":bulk["from_sha"],"bulk_to_sha":bulk["to_sha"],
        "largest_pending_jump":len(bulk["added"]),"moved_to_historical_backlog":len(moved),
        "guardrail":"Bulk legacy discovery items are historical/non-forward; unknown timestamps are never invented.",
    }
    PENDING.write_text(json.dumps(current_out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    backlog_out=dict(backlog)
    backlog_out["updated_at"]=now
    backlog_out["records"]=sorted(backlog_rows.values(),key=lambda x:str(x.get("video_id") or ""))
    prior_counts=backlog_out.get("counts") or {}
    backlog_out["counts"]={**prior_counts,"unresolved_backlog":len(backlog_rows)}
    backlog_out["scope_recovery"]={
        "bulk_from_sha":bulk["from_sha"],"bulk_to_sha":bulk["to_sha"],
        "largest_pending_jump":len(bulk["added"]),"moved":len(moved),
    }
    BACKLOG.write_text(json.dumps(backlog_out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    report={
        "version":1,"generated_at":now,"git_versions_scanned":len(history),
        "largest_pending_jump":{
            "from_sha":bulk["from_sha"],"to_sha":bulk["to_sha"],
            "before":bulk["before"],"after":bulk["after"],"added":len(bulk["added"]),
        },
        "current_pending_before":len(current.get("records") or []),
        "moved_to_historical_backlog":len(moved),
        "current_pending_after":len(current_rows),
        "historical_backlog_after":len(backlog_rows),
        "feed_or_learned_excluded":len([x for x in bulk["added"] if x in feed or x in learned]),
        "moved_video_ids":moved,
        "guardrail":"Recovered items remain learning candidates only; they never become Genuine Forward evidence.",
    }
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("git_versions_scanned","current_pending_before","moved_to_historical_backlog","current_pending_after","historical_backlog_after")},ensure_ascii=False))

if __name__=="__main__":recover()
