#!/usr/bin/env python3
"""Historical YouTube learning archive (strictly non-gating).

Purpose:
- learn from already-published videos with Q1/Q2 text where available;
- preserve structured method/context memory without inserting old videos into
  research_feed / Source Store / Rule Registry / EventScore;
- never store full third-party transcripts in the repository.

The archive is descriptive research memory only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import research_feed as rf
import transcript_router as tr
import youtube_provider_health as health

DATA_DIR=Path(os.getenv("DATA_DIR","state"))
OUT=DATA_DIR/"youtube_learning_archive.json"
MAX_EXCERPT=240

MACRO_TOPICS={
    "利率/Fed":["federal reserve","fed ","interest rate","rate cut","rate hike","yield","treasury","fomc"],
    "通胀":["inflation","cpi","ppi"],
    "美元":["dollar","usd","dxy"],
    "黄金":["gold","precious metal"],
    "加密资产":["bitcoin","btc","crypto","ethereum"],
    "经济周期":["recession","soft landing","hard landing","economy","economic"],
    "流动性":["liquidity","money supply","financial conditions"],
}

def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def _hash(v):
    return hashlib.sha256(str(v or "").encode("utf-8")).hexdigest()

def macro_topics(text:str)->list[str]:
    low=(text or "").lower()
    return [name for name,keys in MACRO_TOPICS.items() if any(k in low for k in keys)]

NOISE_LINES={
    "scribe","like it? make scribe even better by","leaving a review","get chrome extension",
    "browse","popular videos","recent videos","all channels","free tools",
    "video subtitle downloader","video timestamp generator","video summarizer",
    "video word counter","video title analyzer","video transcript search","video analytics",
    "video chapters creator","video quiz generator","chat with video",
}
def clean_learning_text(text:str)->str:
    lines=[]
    for raw in (text or "").splitlines():
        line=re.sub(r"\s+"," ",raw).strip()
        if not line: continue
        if line.lower() in NOISE_LINES: continue
        lines.append(line)
    return "\n".join(lines)

def _sentences(text:str)->list[str]:
    chunks=re.split(r"(?<=[。！？.!?])\s+|\n+",text or "")
    return [re.sub(r"\s+"," ",x).strip() for x in chunks if len(re.sub(r"\s+"," ",x).strip())>=25]

def representative_points(text:str,role:str,limit:int=3)->list[str]:
    """Select bounded diagnostic snippets; no long transcript reproduction."""
    keys = (
        ["support","resistance","buy","sell","entry","break","hold","target","risk","止损","支撑","阻力","买","卖","突破","风险"]
        if role=="rule_supply"
        else ["fed","rate","yield","inflation","dollar","gold","bitcoin","recession","economy","liquidity"]
    )
    out=[]
    for s in _sentences(text):
        low=s.lower()
        if any(k in low for k in keys):
            # Keep short, non-contiguous snippets for internal research review.
            s=s[:120]
            if s not in out:
                out.append(s)
        if len(out)>=limit:
            break
    return out

def build_probe(p:dict)->dict:
    result=tr.acquire(p["video_id"],p["title"],p["author"])
    raw_text=str(result.get("text") or "")
    text=clean_learning_text(raw_text)
    quality=result.get("quality") or "Q5"
    eligible=quality in {"Q1","Q2"} and bool(text)

    learning={
        "symbols":[],
        "operations":[],
        "portfolio_rules":[],
        "lessons":[],
    }
    themes=[]
    macro=[]
    points=[]
    if eligible:
        learning=rf.extract_structured_learning(text)
        # Historical archive keeps only author-owned actions/plans. Third-party
        # examples mentioned inside a video are context, not the creator's own operation.
        learning["operations"]=[
            op for op in learning["operations"]
            if op.get("attribution") in {"author_action","author_plan"}
        ]
        themes=rf.detect_themes((p.get("title") or "")+"\n"+text)
        macro=macro_topics(text)
        points=representative_points(text,p.get("role") or "")

    return {
        "archive_id":"yt_hist_"+_hash(p["video_id"])[:16],
        "author":p["author"],
        "video_id":p["video_id"],
        "title":p["title"],
        "role":p["role"],
        "url":f"https://www.youtube.com/watch?v={p['video_id']}",
        "quality":quality,
        "provider":result.get("provider"),
        "provider_url":result.get("provider_url"),
        "content_origin":result.get("content_origin"),
        "timestamp_evidence":bool(result.get("timestamp_evidence")),
        "rule_candidate_capable_at_source":bool(result.get("rule_candidate_allowed")),
        "historical_learning_eligible":eligible,
        "text_chars_seen":len(text),
        "text_hash":_hash(text) if text else None,
        "excerpt":text[:MAX_EXCERPT] if text else "",
        "symbols":learning["symbols"] if eligible else [],
        "themes":themes,
        "macro_topics":macro,
        "operations":learning["operations"] if eligible else [],
        "portfolio_rules":learning["portfolio_rules"] if eligible else [],
        "lessons":learning["lessons"] if eligible else [],
        "representative_points":points,
        "forward_evidence_eligible":False,
        "promotion_eligible":False,
        "event_score_eligible":False,
        "note":"Historical observational learning only; never admitted to forward evidence or Promotion.",
    }

def main():
    rows=[build_probe(p) for p in health.PROBES]
    out={
        "version":1,
        "generated_at":_now(),
        "mode":"historical_observational_learning_only",
        "non_gating":True,
        "result_blind":True,
        "records":rows,
        "counts":{
            "records":len(rows),
            "q1_q2_learning_eligible":sum(1 for r in rows if r["historical_learning_eligible"]),
            "q5_metadata_only":sum(1 for r in rows if r["quality"]=="Q5"),
            "rule_supply_records":sum(1 for r in rows if r["role"]=="rule_supply"),
            "market_context_records":sum(1 for r in rows if r["role"]=="market_context"),
            "structured_operations":sum(len(r["operations"]) for r in rows),
        },
        "guardrails":[
            "This archive is never appended to research_feed.",
            "These historical videos never enter Source Store, Rule Registry, EventScore, Promotion, Readiness, or Planner gating.",
            "Only Q1/Q2 text is semantically extracted; Q3/Q4/Q5 remain descriptive/context-only.",
            "Full third-party transcripts are not stored; only hashes, bounded excerpts, and structured learning are persisted.",
        ],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out["counts"],ensure_ascii=False))

if __name__=="__main__":
    main()
