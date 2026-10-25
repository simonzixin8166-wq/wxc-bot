"""YT-01 manual path: the Owner pastes a NotebookLM (or other) summary of a YouTube video into Telegram:

    /yt https://www.youtube.com/watch?v=VIDEO_ID <summary text>

The submission is stored append-only in state/owner_video_summaries.jsonl WITHOUT the full text: a <=360-char
excerpt, the sha256 of the full summary, and up to 20 short claim lines (<=120 chars) that carry a ticker or a
number. Every claim is `author_claim_unverified` / evidence_mode `owner_supplied_summary`: a second-hand summary,
never "the video was read", never a rule or forward evidence until the Owner's spot check. The forward intake
(youtube_research) admits it for a queued video instead of spending a Gemini call."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_EXCERPT = 360
MAX_CLAIMS = 20
CLAIM_CHARS = 120
MIN_CHARS = 50
VIDEO_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^ ]*&)?v=|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")
TICKER = re.compile(r"(?<![A-Za-z])[A-Z]{1,5}(?![A-Za-z])")
NOT_TICKERS = {"AI", "CEO", "CFO", "IPO", "GDP", "CPI", "PCE", "VIX", "ETF", "EPS", "GW", "CDS", "US", "USD", "Q", "A",
               "I", "OK", "RSI", "MACD", "SMI", "FOMC", "PPI", "YOY", "QOQ", "AH", "PM", "AM", "TV"}
NUMBER = re.compile(r"\d")


def path():
    return Path(os.getenv("DATA_DIR", "state")) / "owner_video_summaries.jsonl"


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse(text):
    """-> (video_id, url, summary) or raises ValueError with a Chinese reason for the reply."""
    body = (text or "").strip()
    if not body.lower().startswith("/yt"):
        raise ValueError("不是 /yt 指令")
    body = body[3:].strip()
    m = VIDEO_ID.search(body)
    if not m:
        raise ValueError("没有找到 YouTube 链接。格式：/yt 视频链接 摘要内容")
    vid = m.group(1)
    # drop the whole URL token (including any &t=.. tail), keep everything else as the summary
    start = body.rfind(" ", 0, m.start()) + 1
    end = len(body)
    for i in range(m.end(), len(body)):
        if body[i].isspace():
            end = i
            break
    summary = (body[:start] + " " + body[end:]).strip()
    if len(summary) < MIN_CHARS:
        raise ValueError(f"摘要太短（少于 {MIN_CHARS} 字），没有收录。")
    return vid, f"https://www.youtube.com/watch?v={vid}", summary


def claims(summary):
    """Short claim lines that carry a ticker or a number; ticker = first ticker-shaped token (unverified)."""
    out, context = [], None
    for raw in re.split(r"[\n。；;]+", summary):
        line = re.sub(r"^[\s\-•*#>0-9.、()（）一二三四五六七八九十]+", "", raw).strip()
        if len(line) < 6:
            continue
        tickers = [t for t in TICKER.findall(line) if t not in NOT_TICKERS and len(t) >= 2]
        if tickers:
            context = tickers[0]
        if not tickers and not NUMBER.search(line):
            continue
        out.append({"claim": line[:CLAIM_CHARS], "symbol": tickers[0] if tickers else None,
                    # nearest ticker heading above a line without its own ticker (a hint only, never the symbol)
                    "context_symbol": None if tickers else context,
                    "symbol_check": "owner_text_unverified" if tickers else None,
                    "claim_status": "author_claim_unverified", "evidence_mode": "owner_supplied_summary"})
        if len(out) >= MAX_CLAIMS:
            break
    return out


def record(vid, url, summary, submitted_at=None):
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    return {
        "submission_id": hashlib.sha1(f"{vid}|{digest}".encode()).hexdigest()[:16],
        "video_id": vid, "url": url, "submitted_at": submitted_at or _now(), "source": "owner_telegram",
        "summary_sha256": digest, "summary_chars": len(summary), "excerpt": summary[:MAX_EXCERPT],
        "claims": claims(summary), "evidence_mode": "owner_supplied_summary",
        "claim_status": "author_claim_unverified", "validation_status": "pending_owner_spot_check",
        "published_at": None,  # unknown here; the intake uses the queued video's own metadata if it has one
        "forward_evidence_eligible": False, "rule_candidate_allowed": False,
    }


def load(p=None):
    p = p or path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def by_video(rows=None):
    """video_id -> merged view (all submissions; claims concatenated, capped)."""
    merged = {}
    for r in rows if rows is not None else load():
        m = merged.setdefault(r["video_id"], {"video_id": r["video_id"], "submission_ids": [], "summary_sha256": [],
                                              "excerpt": r.get("excerpt") or "", "claims": [],
                                              "submitted_at": r.get("submitted_at")})
        m["submission_ids"].append(r["submission_id"])
        m["summary_sha256"].append(r["summary_sha256"])
        m["claims"] = (m["claims"] + list(r.get("claims") or []))[:MAX_CLAIMS * 2]
    return merged


def submit(text, p=None):
    """Telegram handler: append the submission (deduped by content hash). Returns the reply text."""
    try:
        vid, url, summary = parse(text)
    except ValueError as exc:
        return f"❌ {exc}"
    p = p or path()
    rec = record(vid, url, summary)
    if any(r.get("submission_id") == rec["submission_id"] for r in load(p)):
        return f"ℹ️ 这段摘要已经收到过（{vid}），没有重复记录。"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return (f"✅ 已收到 {vid} 的摘要：{rec['summary_chars']} 字，提取 {len(rec['claims'])} 条观点（只保存 ≤360 字摘录和哈希）。\n"
            + queue_note(vid, p.parent) + "\n标记为「作者主张·未核实」，抽查前不会作为规则或前向证据。")


def queue_note(vid, base):
    """Tell the Owner honestly whether the intake will pick this video up."""
    def ids(name, key):
        try:
            doc = json.loads((base / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        items = doc.get(key) or []
        return {x.get("video_id") if isinstance(x, dict) else x for x in items}
    if vid in ids("pending_youtube.json", "records"):
        return "该视频在待处理队列中，下一次 YouTube 采集时收录（不再调用 Gemini）。"
    if vid in ids("seen_youtube.json", "video_ids"):
        return "该视频已不在待处理队列（可能已被收录），这份摘要只保存，供抽查时对照。"
    return "该视频不在已跟踪频道的队列中，摘要只保存，暂不进入资料库。"
