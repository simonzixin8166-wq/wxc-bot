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
HEALTH_OUT=DATA_DIR/"youtube_provider_health.json"
MAX_EXCERPT=0

QUALITY_RANK={"Q1":5,"Q2":4,"Q3":3,"Q4":2,"Q5":1}

def merge_with_prior(current:dict, prior:dict|None)->dict:
    """Historical memory is monotonic in evidence quality.

    A temporary provider outage must not erase a previously acquired Q1/Q2
    learning snapshot. Metadata fields may refresh, but the highest-quality
    persisted semantic learning is retained until a strictly better snapshot
    is acquired.
    """
    if not prior:
        return current
    cq=str(current.get("quality") or "Q5").upper()
    pq=str(prior.get("quality") or "Q5").upper()
    if QUALITY_RANK.get(pq,0) <= QUALITY_RANK.get(cq,0):
        return current
    keep=dict(current)
    for key in [
        "quality","provider","provider_url","content_origin","timestamp_evidence",
        "rule_candidate_capable_at_source","historical_learning_eligible",
        "text_chars_seen","text_hash","symbols","themes","macro_topics","operations",
        "portfolio_rules","lessons","representative_points",
    ]:
        keep[key]=prior.get(key)
    keep["retained_prior_best_quality"]=True
    keep["last_probe_quality"]=cq
    keep["last_probe_provider"]=current.get("provider")
    keep["note"]="Historical observational learning only; retained prior best-quality snapshot after a weaker provider probe. Never admitted to forward evidence or Promotion."
    keep["forward_evidence_eligible"]=False
    keep["promotion_eligible"]=False
    keep["event_score_eligible"]=False
    return keep

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
        "excerpt":"",
        "symbols":[
            s for s in (learning["symbols"] if eligible else [])
            if not (p.get("role")=="market_context" and s=="NOW" and "servicenow" not in text.lower() and "$NOW" not in text)
        ],
        "themes":themes,
        "macro_topics":macro,
        "operations":learning["operations"] if eligible else [],
        "portfolio_rules":learning["portfolio_rules"] if eligible else [],
        "lessons":learning["lessons"] if eligible else [],
        "representative_points":[],
        "forward_evidence_eligible":False,
        "promotion_eligible":False,
        "event_score_eligible":False,
        "note":"Historical observational learning only; never admitted to forward evidence or Promotion.",
    }

def provider_health_from_rows(rows:list[dict])->dict:
    probes=[]
    for r in rows:
        probes.append({
            "author":r.get("author"),"video_id":r.get("video_id"),"title":r.get("title"),"role":r.get("role"),
            "status":"available" if str(r.get("quality") or "Q5")!="Q5" else "metadata_only",
            "quality":r.get("quality") or "Q5","provider":r.get("provider") or "metadata_only",
            "provider_url":r.get("provider_url") or "","content_origin":r.get("content_origin") or "metadata_only",
            "timestamp_evidence":bool(r.get("timestamp_evidence")),
            "rule_candidate_allowed":bool(r.get("rule_candidate_capable_at_source")),
            "chars":int(r.get("text_chars_seen") or 0),
            "note":"Derived from the same historical acquisition pass; no second provider request.",
        })
    return {
        "version":1,"generated_at":_now(),"non_gating":True,"historical_diagnostic_only":True,
        "probe_count":len(probes),
        "available_count":sum(1 for r in probes if r.get("quality")!="Q5"),
        "rule_candidate_capable_count":sum(1 for r in probes if r.get("rule_candidate_allowed")),
        "probes":probes,
        "guardrail":"Derived from historical archive acquisition; never enters research_feed, Source Store, Rule Registry, EventScore, Promotion, or Readiness.",
    }

def main():
    prior_doc={}
    try:
        prior_doc=json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        prior_doc={}
    prior_by_video={str(x.get("video_id")):x for x in (prior_doc.get("records") or []) if x.get("video_id")}
    rows=[merge_with_prior(build_probe(p),prior_by_video.get(str(p.get("video_id")))) for p in health.PROBES]
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
            "Third-party transcripts are processed in-memory only; persisted records keep hashes, text length and structured learning, not transcript excerpts.",
            "Historical learning quality is monotonic: a temporary weaker provider result cannot erase a prior stronger Q1/Q2 snapshot.",
        ],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    health_out=provider_health_from_rows(rows)
    HEALTH_OUT.write_text(json.dumps(health_out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({**out["counts"],"provider_available":health_out["available_count"]},ensure_ascii=False))

if __name__=="__main__":
    main()
