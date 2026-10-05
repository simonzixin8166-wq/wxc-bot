#!/usr/bin/env python3
"""YouTube research-source collector for MyAlpha.

Design:
- metadata/transcript only; never downloads video/audio;
- first run establishes a seen-video baseline and publishes diagnostics only;
- only videos first observed after baseline are appended to research_feed.json;
- transcript is best-effort. Metadata-only records are allowed but never
  fabricated into operations/rules;
- stores only a bounded excerpt, not full copyrighted transcripts.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any

import research_feed as rf

DATA_DIR=Path(os.getenv("DATA_DIR","state"))
SEEN_PATH=DATA_DIR/"seen_youtube.json"
STATUS_PATH=DATA_DIR/"youtube_source_status.json"
MAX_LIST_PER_CHANNEL=10
MAX_TRANSCRIPT_CHARS=12000
MAX_EXCERPT=360

CHANNELS=[
    {"handle":"@RhinoFinance","author":"RhinoFinance / 视野环球财经","role":"rule_supply"},
    {"handle":"@TianCompounding","author":"TianCompounding","role":"research_thesis"},
    {"handle":"@NaNaShuoMeiGu","author":"NaNa说美股","role":"rule_supply"},
    {"handle":"@老李玩钱","author":"老李玩钱","role":"rule_supply"},
    {"handle":"@AndreiJikh","author":"Andrei Jikh","role":"market_context"},
]

def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def _read(path:Path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default

def _write(path:Path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def _video_id(entry:dict)->str:
    return str(entry.get("id") or entry.get("url") or "").strip()

def _canonical_video_url(video_id:str)->str:
    return f"https://www.youtube.com/watch?v={video_id}"

def _date(upload_date)->str:
    if isinstance(upload_date,(int,float)):
        try:
            return datetime.fromtimestamp(upload_date,timezone.utc).date().isoformat()
        except Exception:
            return ""
    s=str(upload_date or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s)>=8 and s[:8].isdigit() else ""

def _entry_published(entry:dict)->str:
    return (
        _date(entry.get("upload_date"))
        or _date(entry.get("timestamp"))
        or _date(entry.get("release_timestamp"))
    )

def _entry_metadata(entry:dict)->dict:
    vid=_video_id(entry)
    return {
        "id":vid,
        "title":entry.get("title") or "",
        "webpage_url":entry.get("webpage_url") or _canonical_video_url(vid),
        "upload_date":entry.get("upload_date"),
        "timestamp":entry.get("timestamp"),
        "release_timestamp":entry.get("release_timestamp"),
    }

def default_list_channel(channel_url:str)->list[dict]:
    import yt_dlp
    opts={
        "quiet":True,"no_warnings":True,"skip_download":True,
        "extract_flat":"in_playlist","playlistend":MAX_LIST_PER_CHANNEL,
        "ignoreerrors":True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info=ydl.extract_info(channel_url,download=False) or {}
    return [x for x in (info.get("entries") or []) if isinstance(x,dict)]

def default_video_metadata(video_url:str)->dict:
    import yt_dlp
    opts={"quiet":True,"no_warnings":True,"skip_download":True,"ignoreerrors":False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(video_url,download=False) or {}

def default_transcript(video_id:str)->tuple[str,str]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api=YouTubeTranscriptApi()
        fetched=api.fetch(video_id,languages=["zh-Hans","zh-Hant","zh","en"])
        parts=[]
        for item in fetched:
            text=getattr(item,"text",None)
            if text:parts.append(str(text))
        joined=" ".join(parts).strip()
        return joined[:MAX_TRANSCRIPT_CHARS],"youtube_transcript_api"
    except Exception as exc:
        return "",f"unavailable:{type(exc).__name__}"

def _key(author:str,url:str,published:str,title:str)->str:
    raw="|".join([author,url,published,title])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

def make_feed_row(channel:dict, meta:dict, transcript:str, transcript_status:str)->dict:
    vid=str(meta.get("id") or "")
    title=str(meta.get("title") or "").strip()
    url=str(meta.get("webpage_url") or _canonical_video_url(vid))
    published=_date(meta.get("upload_date"))
    text=(transcript or "").strip()
    joined=(title+"\n"+text).strip()
    learning=rf.extract_structured_learning(joined) if text else {
        "symbols":rf.detect_symbols(title),"operations":[],"portfolio_rules":[],"lessons":[]
    }
    return {
        "id":_key(channel["author"],url,published,title),
        "source":"youtube",
        "source_kind":"video",
        "author":channel["author"],
        "published_at":published,
        "title":title,
        "url":url,
        "excerpt":text[:MAX_EXCERPT],
        "content_chars":len(text),
        "images_count":0,
        "themes_hint":rf.detect_themes(joined),
        "symbols":learning["symbols"],
        "operations":learning["operations"],
        "portfolio_rules":learning["portfolio_rules"],
        "lessons":learning["lessons"],
        "captured_at":_now(),
        "source_role":channel["role"],
        "transcript_status":transcript_status,
        "source_notice":"公开视频研究来源；仅保存短摘录与原视频链接。作者观点属于未验证假设，MyAlpha需独立验证后才可进入正式证据。",
    }

def collect(
    list_channel:Callable[[str],list[dict]]=default_list_channel,
    video_metadata:Callable[[str],dict]=default_video_metadata,
    transcript_fetcher:Callable[[str],tuple[str,str]]=default_transcript,
)->dict:
    seen_doc=_read(SEEN_PATH,None)
    first_run=not isinstance(seen_doc,dict) or "video_ids" not in seen_doc
    seen=set((seen_doc or {}).get("video_ids") or [])
    discovered=[]
    channel_status=[]

    for ch in CHANNELS:
        handle=ch["handle"]
        url=f"https://www.youtube.com/{handle}/videos"
        try:
            entries=list_channel(url)[:MAX_LIST_PER_CHANNEL]
            ids=[_video_id(x) for x in entries if _video_id(x)]
            newest=entries[0] if entries else {}
            sample={
                "video_id":_video_id(newest) or None,
                "title":newest.get("title"),
                "url":_canonical_video_url(_video_id(newest)) if _video_id(newest) else None,
                "published_at":_entry_published(newest),
                "flat_metadata_keys":sorted(
                    k for k in ("upload_date","timestamp","release_timestamp","duration","channel_id")
                    if newest.get(k) is not None
                ),
            }
            transcript_probe="not_probed"
            if sample["video_id"]:
                tr,ts=transcript_fetcher(sample["video_id"])
                transcript_probe=ts
                sample["transcript_available"]=bool(tr)
                sample["transcript_chars"]=len(tr)

            channel_status.append({
                "handle":handle,"author":ch["author"],"role":ch["role"],
                "status":"ok","listed_videos":len(ids),
                "latest":sample,"transcript_probe":transcript_probe,
            })

            if not first_run:
                for e in entries:
                    vid=_video_id(e)
                    if vid and vid not in seen:
                        discovered.append((ch,e))
            seen.update(ids)
        except Exception as exc:
            channel_status.append({
                "handle":handle,"author":ch["author"],"role":ch["role"],
                "status":"error","error":f"{type(exc).__name__}: {exc}",
            })

    added=0
    appended=[]
    if not first_run:
        rows=[]
        for ch,entry in discovered:
            vid=_video_id(entry)
            try:
                meta=_entry_metadata(entry)
                # Flat playlist metadata is the primary path. A full detail
                # lookup is only a best-effort enhancement because YouTube may
                # block datacenter IPs even when channel listing works.
                if not _entry_published(entry):
                    try:
                        full=video_metadata(_canonical_video_url(vid))
                        if full:
                            meta.update({k:v for k,v in full.items() if v is not None})
                    except Exception:
                        pass
                tr,ts=transcript_fetcher(vid)
                row=make_feed_row(ch,meta,tr,ts)
                rows.append(row)
                appended.append({
                    "author":row["author"],"video_id":vid,"title":row["title"],
                    "published_at":row["published_at"],"transcript_status":ts,
                    "content_chars":row["content_chars"],"symbols":row["symbols"],
                    "operations":len(row["operations"]),
                })
            except Exception as exc:
                appended.append({
                    "author":ch["author"],"video_id":vid,
                    "error":f"{type(exc).__name__}: {exc}",
                })
        added=rf.append_records(rows)

    status={
        "version":1,
        "generated_at":_now(),
        "status":"baseline_established" if first_run else "ok",
        "first_run":first_run,
        "channels":channel_status,
        "discovered_new_videos":0 if first_run else len(discovered),
        "feed_records_added":added,
        "new_video_diagnostics":appended,
        "guardrails":[
            "Initial run only establishes a seen-video baseline; existing videos are not inserted into forward research feed.",
            "Collector never downloads video/audio and stores only bounded transcript excerpts.",
            "Transcript absence is metadata_only, not a reason to invent operations or testable rules.",
            "Channel role controls interpretation: market_context sources may legitimately produce no testable rule.",
        ],
    }
    _write(SEEN_PATH,{"version":1,"updated_at":status["generated_at"],"video_ids":sorted(seen)})
    _write(STATUS_PATH,status)
    return status

def main():
    out=collect()
    print(json.dumps({
        "status":out["status"],
        "channels":len(out["channels"]),
        "new":out["discovered_new_videos"],
        "added":out["feed_records_added"],
        "errors":sum(1 for x in out["channels"] if x.get("status")!="ok"),
    },ensure_ascii=False))

if __name__=="__main__":
    main()
