#!/usr/bin/env python3
"""Transcript Acquisition Router for MyAlpha YouTube research.

Goal: obtain learning text without pretending metadata is content.

Priority:
Q1 official/auto transcript -> Q2 third-party near-full transcript
-> Q3 timestamped structured summary -> Q4 public summary -> Q5 metadata only.

Only allowlisted public providers are queried. Pages are fetched only for newly
observed videos or explicit health probes. The router never downloads video/audio.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, asdict
from urllib.parse import quote, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

UA={"User-Agent":"Mozilla/5.0 (compatible; MyAlphaView/1.0; +research)"}
FAST_MODE=os.getenv("TRANSCRIPT_FAST_MODE","0")=="1"
TIMEOUT=8 if FAST_MODE else 15
MAX_TEXT=12000

ALLOWLIST={
    "pickscribe.com":"third_party_transcript",
    "sozai.app":"third_party_transcript",
    "reducer.xgoose.org":"structured_summary",
    "stockvoice.cmoney.tw":"structured_summary",
    "lilys.ai":"third_party_transcript",
    "fifan.app":"structured_summary",
    "askchannel.ai":"third_party_transcript",
}
SEARCH_DOMAINS=[
    "reducer.xgoose.org",
    "stockvoice.cmoney.tw",
    "lilys.ai",
    "fifan.app",
    "askchannel.ai",
]

@dataclass
class Acquisition:
    text:str=""
    status:str="metadata_only"
    quality:str="Q5"
    provider:str="metadata_only"
    provider_url:str=""
    content_origin:str="metadata_only"
    timestamp_evidence:bool=False
    rule_candidate_allowed:bool=False
    chars:int=0
    note:str=""

    def to_dict(self):
        d=asdict(self)
        d["chars"]=len(self.text or "")
        return d

def _clean_text(raw:str)->str:
    raw=html.unescape(raw or "")
    raw=re.sub(r"\r","\n",raw)
    raw=re.sub(r"[ \t]+"," ",raw)
    raw=re.sub(r"\n{3,}","\n\n",raw)
    return raw.strip()

def _visible_text(page:str)->str:
    soup=BeautifulSoup(page or "","html.parser")
    for tag in soup(["script","style","noscript","svg"]):
        tag.decompose()
    return _clean_text(soup.get_text("\n"))

def _fetch(url:str)->tuple[str,int]:
    r=requests.get(url,headers=UA,timeout=TIMEOUT,allow_redirects=True)
    return (r.text if r.ok else ""),r.status_code

def _quality_for(domain:str,text:str)->tuple[str,bool,bool]:
    low=(text or "").lower()
    ts=bool(re.search(r"(?m)(?:^|\s)(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s|$)",text or ""))
    transcript_mark=any(x in low for x in ["transcript","script","full transcript","字幕","逐字稿"])
    structured_mark=any(x in low for x in ["detailed brief","detailed walkthrough","show notes","原片","跳到","infographic"])
    n=len(text or "")
    if domain in {"pickscribe.com","sozai.app","lilys.ai","askchannel.ai"} and n>=1800 and (transcript_mark or ts):
        return "Q2",ts,True
    if domain in {"reducer.xgoose.org","stockvoice.cmoney.tw","fifan.app"} and n>=650 and (structured_mark or ts):
        # Structured summaries are valuable learning context, but remain thesis-only
        # until a full transcript or independent primary evidence confirms wording.
        return "Q3",ts,False
    if n>=500:
        return "Q4",ts,False
    return "Q5",ts,False

def _candidate_from_url(url:str,title:str,author:str)->Acquisition|None:
    try:
        host=(urlparse(url).hostname or "").lower().removeprefix("www.")
        if host not in ALLOWLIST:
            return None
        page,code=_fetch(url)
        if code!=200 or not page:
            return None
        text=_visible_text(page)
        low=text.lower()
        # Conservative identity check: require either a substantial title overlap
        # or author mention. This avoids learning from an unrelated provider page.
        toks=[x.lower() for x in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}",title or "")[:12]]
        overlap=sum(1 for x in toks if x in low)
        author_key=(author or "").split("/")[0].strip().lower()
        identity_ok=(overlap>=2) or (author_key and author_key in low)
        if not identity_ok:
            return None
        quality,ts,rule_ok=_quality_for(host,text)
        if quality=="Q5":
            return None
        origin=ALLOWLIST[host]
        return Acquisition(
            text=text[:MAX_TEXT],
            status="available",
            quality=quality,
            provider=host,
            provider_url=url,
            content_origin=origin,
            timestamp_evidence=ts,
            rule_candidate_allowed=rule_ok,
            note="Public third-party text; MyAlpha preserves provider provenance and does not treat it as primary-source fact.",
        )
    except Exception:
        return None

def _source_video_id(url:str)->str:
    try:
        p=urlparse(url or "")
        host=(p.hostname or "").lower()
        if host=="youtu.be":
            return p.path.strip("/").split("/")[0]
        if host.endswith("youtube.com"):
            if p.path=="/watch":
                return parse_qs(p.query).get("v",[""])[0]
            m=re.search(r"/(?:shorts|embed|live)/([^/?#]+)",p.path)
            if m:return m.group(1)
    except Exception:
        pass
    return ""

def _xgoose_native(video_id:str,title:str,author:str)->Acquisition|None:
    """Use stream-reducer's public catalog API, matching the original YouTube id.

    The catalog lookup is title-assisted only; the final identity check is the
    source_url video id, so a same/similar title cannot contaminate attribution.
    """
    if not video_id or not title:
        return None
    try:
        query=(title or "").strip()[:120]
        r=requests.get(
            "https://reducer.xgoose.org/api/items",
            params={"platform":"youtube","q":query,"limit":20,"offset":0},
            headers=UA,timeout=TIMEOUT,
        )
        if not r.ok:
            return None
        rows=r.json()
        if not isinstance(rows,list):
            return None
        match=None
        for row in rows:
            if _source_video_id(str(row.get("source_url") or ""))==video_id:
                match=row;break
        # Title search can be punctuation-sensitive. Fall back to a few
        # discriminative title tokens, but still require exact video id.
        if match is None:
            tokens=re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}",title or "")
            for token in tokens[:2 if FAST_MODE else 5]:
                rr=requests.get(
                    "https://reducer.xgoose.org/api/items",
                    params={"platform":"youtube","q":token,"limit":100,"offset":0},
                    headers=UA,timeout=TIMEOUT,
                )
                if not rr.ok:continue
                for row in rr.json() if isinstance(rr.json(),list) else []:
                    if _source_video_id(str(row.get("source_url") or ""))==video_id:
                        match=row;break
                if match is not None:break
        if match is None or not match.get("id"):
            return None
        detail=requests.get(
            f"https://reducer.xgoose.org/api/items/{int(match['id'])}",
            headers=UA,timeout=TIMEOUT,
        )
        if not detail.ok:
            return None
        data=detail.json()
        transcript=(data.get("transcript") or {}) if isinstance(data,dict) else {}
        text=_clean_text(str(transcript.get("text") or ""))
        source_url=str(data.get("source_url") or match.get("source_url") or "")
        if _source_video_id(source_url)!=video_id:
            return None
        if len(text)>=1800:
            return Acquisition(
                text=text[:MAX_TEXT],status="available",quality="Q2",
                provider="reducer.xgoose.org",
                provider_url=f"https://reducer.xgoose.org/items/{int(match['id'])}",
                content_origin="third_party_transcript",
                timestamp_evidence=bool(transcript.get("segments")),
                rule_candidate_allowed=True,
                note="Public stream-reducer transcript; exact YouTube video-id matched.",
            )
        # If no near-full transcript is public, use the structured summary only
        # as Q3 context. It is never rule-eligible.
        summary=(data.get("summary") or {}) if isinstance(data,dict) else {}
        summary_text=_clean_text(str(summary.get("markdown") or ""))
        if len(summary_text)>=650:
            return Acquisition(
                text=summary_text[:MAX_TEXT],status="available",quality="Q3",
                provider="reducer.xgoose.org",
                provider_url=f"https://reducer.xgoose.org/items/{int(match['id'])}",
                content_origin="structured_summary",
                timestamp_evidence=True,
                rule_candidate_allowed=False,
                note="Public stream-reducer structured summary; exact YouTube video-id matched.",
            )
    except Exception:
        return None
    return None

def _direct_pickscribe(video_id:str,title:str,author:str)->Acquisition|None:
    if not video_id:
        return None
    return _candidate_from_url(f"https://pickscribe.com/v/{video_id}/",title,author)

def _duckduckgo_links(query:str)->list[str]:
    """Low-volume discovery fallback for allowlisted public text providers."""
    try:
        r=requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q":query},
            headers=UA,
            timeout=TIMEOUT,
        )
        if not r.ok:
            return []
        soup=BeautifulSoup(r.text,"html.parser")
        out=[]
        for a in soup.select("a.result__a, a[href]"):
            href=a.get("href") or ""
            if "uddg=" in href:
                try:
                    href=unquote(parse_qs(urlparse(href).query).get("uddg",[""])[0])
                except Exception:
                    pass
            host=(urlparse(href).hostname or "").lower().removeprefix("www.")
            if host in ALLOWLIST and href not in out:
                out.append(href)
        return out[:8]
    except Exception:
        return []

def acquire_third_party(video_id:str,title:str,author:str)->Acquisition:
    # English channels with stable PickScribe video-id pages should go direct
    # first. This avoids expensive title-search fallbacks and reduces transient
    # provider failures. Chinese rule-supply sources still prefer xgoose's
    # exact original-video-id catalog match.
    if "andrei jikh" in (author or "").lower():
        direct=_direct_pickscribe(video_id,title,author)
        if direct:
            return direct
    native=_xgoose_native(video_id,title,author)
    if native:
        return native
    direct=_direct_pickscribe(video_id,title,author)
    if direct:
        return direct
    if FAST_MODE:
        # New-video collection is latency-sensitive. If exact providers have
        # not indexed the video yet, persist it in pending and retry later
        # rather than fan out to broad web discovery in the same daily run.
        return Acquisition(note="Fast mode: exact providers not ready; retry from pending on a later run.")

    queries=[
        f'"{video_id}" transcript',
        f'"{title}" "{author}" transcript',
        f'"{title}" "{author}"',
    ]
    checked=set()
    for q in queries:
        for url in _duckduckgo_links(q):
            if url in checked:
                continue
            checked.add(url)
            got=_candidate_from_url(url,title,author)
            if got:
                return got
    return Acquisition(note="No allowlisted public transcript/summary provider matched this video.")

def acquire(video_id:str,title:str,author:str,official_fetcher=None)->dict:
    """Acquire best available text. official_fetcher(video_id)->(text,status)."""
    if official_fetcher:
        try:
            text,status=official_fetcher(video_id)
            text=_clean_text(text)
            if len(text)>=500:
                return Acquisition(
                    text=text[:MAX_TEXT],
                    status="available",
                    quality="Q1",
                    provider="youtube_official",
                    provider_url=f"https://www.youtube.com/watch?v={video_id}",
                    content_origin="youtube_official_transcript",
                    timestamp_evidence=False,
                    rule_candidate_allowed=True,
                    note=status or "official transcript",
                ).to_dict()
        except Exception:
            pass

    return acquire_third_party(video_id,title,author).to_dict()

def public_view(result:dict)->dict:
    """Sanitized acquisition metadata; never expose/store full transcript here."""
    return {k:result.get(k) for k in [
        "status","quality","provider","provider_url","content_origin",
        "timestamp_evidence","rule_candidate_allowed","chars","note"
    ]}

if __name__=="__main__":
    import json,sys
    vid=sys.argv[1] if len(sys.argv)>1 else ""
    title=sys.argv[2] if len(sys.argv)>2 else ""
    author=sys.argv[3] if len(sys.argv)>3 else ""
    print(json.dumps(public_view(acquire(vid,title,author)),ensure_ascii=False,indent=2))
