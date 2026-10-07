#!/usr/bin/env python3
"""Recover every research_feed record that ever existed in Git history.\n\n# recovery-trigger: 2026-10-07

Safety:
- current records win;
- historical versions may only fill fields that are currently empty;
- records missing from current feed are restored as historical backfill;
- recovered rows are never reclassified as live/forward intake;
- no record-count retention cap is applied.
"""
from __future__ import annotations
import json, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FEED=ROOT/"state"/"research_feed.json"
REPORT=ROOT/"state"/"research_feed_recovery_report.json"
IMMUTABLE={"id","source","source_kind","author","published_at","url","captured_at","intake_class_hint","capture_mode"}

def read_json_text(text):
    try:return json.loads(text)
    except Exception:return {}

def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT,text=True,stderr=subprocess.DEVNULL)

def history_commits():
    raw=git("log","--format=%H","--",str(FEED.relative_to(ROOT)))
    return [x.strip() for x in raw.splitlines() if x.strip()]

def historical_feed(commit):
    try:return read_json_text(git("show",f"{commit}:{FEED.relative_to(ROOT)}"))
    except Exception:return {}

def key(row):
    return str(row.get("id") or row.get("url") or "").strip()

def empty(v):
    return v is None or v=="" or v==[] or v=={}

def merge_missing_fields(current,historical):
    out=dict(current)
    for k,v in historical.items():
        if k in IMMUTABLE: continue
        if k not in out or (empty(out.get(k)) and not empty(v)):
            out[k]=v
    return out

def build():
    current=read_json_text(FEED.read_text(encoding="utf-8"))
    current_rows=list(current.get("records") or [])
    merged={key(r):dict(r) for r in current_rows if key(r)}
    historical_seen=set()
    recovered_ids=[]
    enriched_existing=0
    commits=history_commits()

    # Newest -> oldest. Current record is authoritative; history only fills gaps.
    for commit in commits:
        feed=historical_feed(commit)
        for row in feed.get("records") or []:
            k=key(row)
            if not k: continue
            historical_seen.add(k)
            if k in merged:
                newer=merged[k]
                enriched=merge_missing_fields(newer,row)
                if enriched!=newer:
                    merged[k]=enriched
                    enriched_existing+=1
                continue
            restored=dict(row)
            restored["intake_class_hint"]="backfill"
            restored["capture_mode"]="recovered_git_history"
            restored["recovered_from_git_history"]=True
            restored["forward_evidence_eligible"]=False
            merged[k]=restored
            recovered_ids.append(k)

    rows=sorted(merged.values(),key=lambda r:(str(r.get("captured_at") or ""),str(r.get("published_at") or ""),key(r)))
    out=dict(current)
    out["records"]=rows
    out["retention_policy"]="append_only_no_record_count_cap"
    out["historical_recovery"]={
        "completed_at":datetime.now(timezone.utc).isoformat(),
        "git_commits_scanned":len(commits),
        "current_before":len(current_rows),
        "historical_unique_seen":len(historical_seen),
        "recovered_missing_records":len(recovered_ids),
        "current_after":len(rows),
        "policy":"restored rows are historical_backfill and never genuine forward evidence",
    }
    report={
        "version":1,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "git_commits_scanned":len(commits),
        "current_before":len(current_rows),
        "historical_unique_seen":len(historical_seen),
        "recovered_missing_records":len(recovered_ids),
        "enriched_existing_records":enriched_existing,
        "current_after":len(rows),
        "recovered_ids":recovered_ids,
        "forward_integrity":"recovered rows force backfill/recovered_git_history and forward_evidence_eligible=false",
    }
    return out,report

def main():
    out,report=build()
    FEED.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("git_commits_scanned","current_before","historical_unique_seen","recovered_missing_records","current_after")},ensure_ascii=False))

if __name__=="__main__":main()
