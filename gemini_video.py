#!/usr/bin/env python3
"""YT-01: Gemini video understanding as the last transcript-router fallback (Owner 10/22, free tier only).

When no official/third-party transcript exists (108 of 109 forward-pending videos sat at Q5 metadata_only
for 7-8 retries), Gemini reads the PUBLIC video itself (speech + on-screen text) and returns structured JSON.

Guardrails
- Off unless GEMINI_API_KEY is set. Free tier only (Owner confirmed no billing on the key's project).
- Budget: GEMINI_VIDEO_DAILY_CAP calls per UTC day (default 10) and GEMINI_VIDEO_RUN_CAP per run (default 2),
  recorded in state/gemini_video_budget.json. Google's free tier allows 8 hours of YouTube video per day.
  HTTP 429 marks the day exhausted.
- Identity check: Gemini must report the video's title/channel; a weak match is rejected, so a model that
  cannot see the video cannot hallucinate content into the feed.
- Output is a Q3 structured summary: never rule-eligible, claims stay experimental_unvalidated, and every
  admitted video is listed for the Owner's spot check (validation_status=pending_owner_spot_check).
- Nothing beyond the runtime text is stored except the feed's usual 360-char excerpt and short claim lines.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODEL = os.getenv("GEMINI_VIDEO_MODEL", "gemini-3.8-flash")
DAILY_CAP = int(os.getenv("GEMINI_VIDEO_DAILY_CAP", "10"))
RUN_CAP = int(os.getenv("GEMINI_VIDEO_RUN_CAP", "2"))
TIMEOUT = int(os.getenv("GEMINI_VIDEO_TIMEOUT", "240"))
MAX_CLAIMS = 12
CLAIM_CHARS = 120
KEEP_DAYS = 45
ORIGIN = "gemini_video_understanding"

_run_calls = 0

PROMPT = r"""
You are a source-reading subsystem for a personal investment research assistant.
Watch the PUBLIC YouTube video at the given URL (spoken content and visible charts/text).
Return ONLY valid JSON, no markdown, with this schema:
{
  "observed_title": "the video's title exactly as shown",
  "observed_channel": "the channel name",
  "summary_zh": "concise Chinese summary, at most 300 characters",
  "symbols": ["tickers explicitly discussed"],
  "claims": [{"claim": "what the author explicitly says, in Chinese, at most 100 characters",
              "symbol": "ticker or null", "stance": "buy|sell|hold|watch|bullish|bearish|neutral|other",
              "price": "explicit price level or null", "timestamp": "MM:SS or HH:MM:SS or null",
              "evidence_mode": "spoken_explicit|onscreen_explicit|spoken_plus_onscreen|visual_inference",
              "confidence": "high|medium|low"}],
  "methods": [{"name": "method/indicator", "explicit_parameters": {}, "missing_parameters": [], "timestamp": null}],
  "invalidations": [{"symbol": "ticker or null", "condition": "explicit exit/failure condition", "timestamp": null}],
  "uncertainties": ["anything not clear enough to treat as the author's explicit statement"],
  "safety": {"historical_only": true, "forward_evidence_eligible": false, "promotion_eligible": false, "production_action": null}
}
Rules: do NOT invent periods, thresholds, prices, dates, tickers or formulas; put unstated parameters in
missing_parameters; separate explicit statements from your visual inference; at most 12 claims; if you cannot
access the video, return {"observed_title": null} and nothing else. Never output a recommendation.
"""


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _budget_path():
    return Path(os.getenv("DATA_DIR", "state")) / "gemini_video_budget.json"


def _load_budget():
    try:
        doc = json.loads(_budget_path().read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_budget(doc):
    days = doc.get("days") or {}
    doc["days"] = {d: days[d] for d in sorted(days)[-KEEP_DAYS:]}
    doc["version"] = 1
    doc["policy"] = f"free tier only; <= {DAILY_CAP} calls/day, <= {RUN_CAP} per run; 429 stops the day"
    p = _budget_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _bump(field, video_id=None, outcome=None, detail=None):
    doc = _load_budget()
    day = doc.setdefault("days", {}).setdefault(_today(), {"calls": 0, "admitted": 0, "rejected": 0, "errors": 0})
    day[field] = int(day.get(field) or 0) + 1
    if field == "exhausted":
        day["exhausted"] = True
    if outcome:
        # Diagnostics only: outcome code + a short provider message, never the key or video content.
        row = {"video_id": video_id, "outcome": outcome, "at": datetime.now(timezone.utc).strftime("%H:%M:%SZ")}
        if detail:
            row["detail"] = re.sub(r"AIza[0-9A-Za-z_-]{10,}", "[key]", str(detail))[:200]
        day["recent"] = (day.get("recent") or [])[-9:] + [row]
        print(f"::notice title=YT-01 Gemini::video={video_id} outcome={outcome} {row.get('detail', '')}"[:300])
    _save_budget(doc)


def _body(r):
    try:
        return (r.text or "")[:200]
    except Exception:
        return ""


def enabled():
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def budget_ok():
    day = (_load_budget().get("days") or {}).get(_today()) or {}
    return _run_calls < RUN_CAP and int(day.get("calls") or 0) < DAILY_CAP and not day.get("exhausted")


def _norm(s):
    return re.sub(r"[\W_]+", "", str(s or "").lower())


def identity_ok(parsed, title, author):
    seen_title, seen_channel = _norm(parsed.get("observed_title")), _norm(parsed.get("observed_channel"))
    want_title = _norm(title)
    if not seen_title or not want_title:
        return False
    ratio = difflib.SequenceMatcher(None, seen_title, want_title).ratio()
    names = [_norm(x) for x in re.split(r"[/|]", author or "") if _norm(x)]
    channel_hit = any(n and (n in seen_channel or seen_channel in n) for n in names) if seen_channel else False
    return ratio >= 0.6 or (ratio >= 0.35 and channel_hit)


def _extract_json(raw):
    texts = []

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("text"), str):
                texts.append(x["text"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(raw)
    joined = "\n".join(dict.fromkeys(t for t in texts if t.strip()))
    m = re.search(r"\{.*\}", joined, re.S)
    return json.loads(m.group(0)) if m else None


def _safe(parsed):
    s = parsed.get("safety") or {}
    return (s.get("historical_only") is True and s.get("forward_evidence_eligible") is False
            and s.get("promotion_eligible") is False and s.get("production_action") is None)


def render(parsed):
    """Runtime learning text (fed to the existing symbol/theme/claim extractors); not stored as a whole."""
    lines = ["[Gemini 视频理解 · 未验证] " + str(parsed.get("summary_zh") or "").strip()]
    for c in claims(parsed):
        tag = " ".join(x for x in (c.get("timestamp"), c.get("symbol"), c.get("stance"), c.get("price")) if x)
        lines.append(f"- [{tag}] {c['claim']}")
    for m in (parsed.get("methods") or [])[:6]:
        if isinstance(m, dict) and m.get("name"):
            lines.append(f"方法：{m['name']} 参数 {json.dumps(m.get('explicit_parameters') or {}, ensure_ascii=False)}")
    for v in (parsed.get("invalidations") or [])[:6]:
        if isinstance(v, dict) and v.get("condition"):
            lines.append(f"失效条件：{v.get('symbol') or ''} {v['condition']}")
    return "\n".join(lines).strip()


def claims(parsed):
    out = []
    for c in (parsed.get("claims") or [])[:MAX_CLAIMS]:
        if not isinstance(c, dict) or not str(c.get("claim") or "").strip():
            continue
        out.append({k: (str(c.get(k)).strip()[:CLAIM_CHARS] if c.get(k) not in (None, "") else None)
                    for k in ("claim", "symbol", "stance", "price", "timestamp", "evidence_mode", "confidence")})
    return out


def acquire(video_id, title, author, post=None):
    """Return an Acquisition-compatible dict, or None (disabled, over budget, failed or unverified)."""
    global _run_calls
    if not enabled() or not budget_ok():
        return None
    post = post or requests.post
    _run_calls += 1
    _bump("calls")
    url = f"https://www.youtube.com/watch?v={video_id}"
    body = {"model": MODEL, "input": [{"type": "video", "uri": url}, {"type": "text", "text": PROMPT}]}
    try:
        r = post(ENDPOINT, json=body, timeout=TIMEOUT,
                 headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip(), "Content-Type": "application/json",
                          "User-Agent": "MyAlphaView-YT01/1.0"})
        if r.status_code == 429:
            _bump("exhausted", video_id, "http_429", _body(r))
            return None
        if r.status_code != 200:
            _bump("errors", video_id, f"http_{r.status_code}", _body(r))
            return None
        parsed = _extract_json(r.json())
    except Exception as exc:
        _bump("errors", video_id, "exception", type(exc).__name__)
        return None
    if not isinstance(parsed, dict):
        _bump("rejected", video_id, "no_json")
        return None
    if not _safe(parsed):
        _bump("rejected", video_id, "safety_contract")
        return None
    if not identity_ok(parsed, title, author):
        _bump("rejected", video_id, "identity_mismatch",
              f"seen={str(parsed.get('observed_title'))[:60]!r} channel={str(parsed.get('observed_channel'))[:30]!r}")
        return None
    text = render(parsed)
    if len(str(parsed.get("summary_zh") or "").strip()) < 20 or not claims(parsed):
        _bump("rejected", video_id, "thin_content")
        return None
    _bump("admitted", video_id, "admitted")
    return {
        "text": text, "status": "available", "quality": "Q3", "provider": "gemini_video",
        "provider_url": url, "content_origin": ORIGIN,
        "timestamp_evidence": any(c.get("timestamp") for c in claims(parsed)),
        "rule_candidate_allowed": False, "chars": len(text),
        "note": f"Gemini {MODEL} read the public video; experimental, pending Owner spot check.",
        "structured": {"model": MODEL, "observed_title": parsed.get("observed_title"),
                       "claims": claims(parsed), "symbols": [str(s)[:12] for s in (parsed.get("symbols") or [])][:12],
                       "uncertainties": [str(u)[:CLAIM_CHARS] for u in (parsed.get("uncertainties") or [])][:5]},
    }
