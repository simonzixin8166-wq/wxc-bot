#!/usr/bin/env python3
"""YT-01: Gemini video understanding as the last transcript-router fallback (Owner 10/22, free tier only).

When no official/third-party transcript exists (108 of 109 forward-pending videos sat at Q5 metadata_only
for 7-8 retries), Gemini reads the PUBLIC video itself (speech + on-screen text) and returns structured JSON.

Guardrails
- Off unless GEMINI_API_KEY is set. Free tier only (Owner confirmed no billing on the key's project).
- Budget: GEMINI_VIDEO_DAILY_CAP calls per Pacific-time quota day (default 10) and GEMINI_VIDEO_RUN_CAP per run (default 2),
  recorded in state/gemini_video_budget.json. Google's free tier allows 8 hours of YouTube video per day.
  HTTP 429 marks the day exhausted.
- Identity check: Gemini must report the video's title/channel; a weak match is rejected, so a model that
  cannot see the video cannot hallucinate content into the feed.
- Output is a Q3 structured summary: never rule-eligible, claims stay experimental_unvalidated, and every
  admitted video is listed for the Owner's spot check (validation_status=pending_owner_spot_check).
- Nothing beyond the runtime text is stored except the feed's usual 360-char excerpt and short claim lines.
"""
from __future__ import annotations

import contextlib
from collections import Counter
import difflib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODELS = [m.strip() for m in os.getenv("GEMINI_VIDEO_MODELS", "gemini-3.8-flash,gemini-3.5-flash").split(",") if m.strip()]
MODEL = MODELS[0]
DAILY_CAP = int(os.getenv("GEMINI_VIDEO_DAILY_CAP", "10"))
RUN_CAP = int(os.getenv("GEMINI_VIDEO_RUN_CAP", "2"))
# Long videos took >240s on 10/24 (SbZltIBvi7M, 1QM5vfCkId0: ReadTimeout, call spent, nothing admitted).
# 2 calls/run x 420s still fits the intake job's 25-minute limit.
TIMEOUT = int(os.getenv("GEMINI_VIDEO_TIMEOUT", "420"))
RETRY_WAIT = int(os.getenv("GEMINI_VIDEO_RETRY_WAIT", "20"))
MAX_CLAIMS = 20
MAX_MACRO = 8
CLAIM_CHARS = 120
KEEP_DAYS = 45
# One detail row per finished call (refunded 503s included); generous so a day's rows are never truncated.
RECENT_KEEP = max(40, DAILY_CAP * 4)
OUTCOME_FIELD = {"admitted": "admitted", "http_429": "exhausted"}
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
  "macro": [{"indicator": "macro/economic data point named in the video (e.g. Michigan sentiment, CPI, PCE, 10Y yield)",
             "value": "explicit value or null", "expectation": "explicit consensus/prior or null",
             "period": "reference period or null", "timestamp": "MM:SS or null"}],
  "methods": [{"name": "method/indicator", "explicit_parameters": {}, "missing_parameters": [], "timestamp": null}],
  "invalidations": [{"symbol": "ticker or null", "condition": "explicit exit/failure condition", "timestamp": null}],
  "uncertainties": ["anything not clear enough to treat as the author's explicit statement"],
  "safety": {"historical_only": true, "forward_evidence_eligible": false, "promotion_eligible": false, "production_action": null}
}
Rules: do NOT invent periods, thresholds, prices, dates, tickers or formulas; put unstated parameters in
missing_parameters; separate explicit statements from your visual inference; at most 20 claims and 8 macro
items; every claim about a specific company or fund MUST carry its exact US ticker in "symbol" as spoken or shown
(null only for market-wide or macro claims; never guess a ticker from a name you did not hear or see); if you cannot
access the video, return {"observed_title": null} and nothing else. Never output a recommendation.
"""


# Google: "Requests per day (RPD) quotas reset at midnight Pacific time" (ai.google.dev/gemini-api/docs/rate-limits).
# Budget days therefore follow the Pacific calendar day (DST-aware). On 10/28 a 429 at 01:18Z (still the previous
# Pacific day) marked the whole UTC day exhausted and three later runs skipped a freshly reset quota (0 videos read).
QUOTA_TZ = ZoneInfo("America/Los_Angeles")
DAY_BASIS = "America/Los_Angeles (Gemini RPD reset); keys before 2026-10-29 are UTC days"


def _today(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(QUOTA_TZ).strftime("%Y-%m-%d")


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
    for day in doc["days"].values():
        if isinstance(day, dict):
            day["reconciliation"] = reconcile(day)
    doc["version"] = 1
    doc["day_basis"] = DAY_BASIS
    doc["policy"] = f"free tier only; <= {DAILY_CAP} calls per Pacific-time quota day, <= {RUN_CAP} per run; 429 stops that quota day"
    p = _budget_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _field_of(outcome):
    if outcome in OUTCOME_FIELD:
        return OUTCOME_FIELD[outcome]
    return "errors" if outcome.startswith("http_") or outcome == "exception" else "rejected"


def reconcile(day):
    """Counters vs per-call rows. Every billed or refunded call must have exactly one detail row whose
    outcome class matches the counters; anything else is INCOMPLETE (never back-filled or guessed)."""
    rows = [r for r in (day.get("recent") or []) if isinstance(r, dict) and r.get("outcome")]
    expected = int(day.get("calls") or 0) + int(day.get("refunded_503") or 0)
    by = {"admitted": 0, "rejected": 0, "errors": 0, "exhausted": 0}
    for r in rows:
        by[_field_of(r["outcome"])] += 1
    mismatched = [f for f in ("admitted", "rejected", "errors") if by[f] != int(day.get(f) or 0)]
    complete = len(rows) == expected and not mismatched
    return {"status": "COMPLETE" if complete else "INCOMPLETE", "calls_billed": int(day.get("calls") or 0),
            "calls_refunded_503": int(day.get("refunded_503") or 0), "detail_rows": len(rows),
            "missing_detail_rows": max(0, expected - len(rows)), "counter_mismatch": mismatched}


def _bump(field, video_id=None, outcome=None, detail=None, **extra):
    doc = _load_budget()
    day = doc.setdefault("days", {}).setdefault(_today(), {"calls": 0, "admitted": 0, "rejected": 0, "errors": 0})
    day[field] = int(day.get(field) or 0) + 1
    if field == "exhausted":
        day["exhausted"] = True
        day["exhausted_quota_day"] = _today()
    if outcome:
        # Diagnostics only: outcome code + a short provider message, never the key or video content.
        row = {"video_id": video_id, "outcome": outcome, "at": datetime.now(timezone.utc).strftime("%H:%M:%SZ")}
        row.update({k: str(v)[:60] for k, v in extra.items() if v})
        if detail:
            row["detail"] = re.sub(r"AIza[0-9A-Za-z_-]{10,}", "[key]", str(detail))[:200]
        day["recent"] = (day.get("recent") or [])[-(RECENT_KEEP - 1):] + [row]
        print(f"::notice title=YT-01 Gemini::video={video_id} outcome={outcome} {row.get('detail', '')}"[:300])
    _save_budget(doc)


def _body(r):
    try:
        return (r.text or "")[:200]
    except Exception:
        return ""


def _refund():
    doc = _load_budget()
    day = (doc.get("days") or {}).get(_today())
    if day and int(day.get("calls") or 0) > 0:
        day["calls"] = int(day["calls"]) - 1
        day["refunded_503"] = int(day.get("refunded_503") or 0) + 1
        _save_budget(doc)


def _fallback_exhausted(model):
    day = (_load_budget().get("days") or {}).get(_today()) or {}
    return model in (day.get("fallback_exhausted") or [])


def _mark_fallback_exhausted(model):
    doc = _load_budget()
    day = doc.setdefault("days", {}).setdefault(_today(), {"calls": 0, "admitted": 0, "rejected": 0, "errors": 0})
    day["fallback_exhausted"] = sorted(set(day.get("fallback_exhausted") or []) | {model})
    _save_budget(doc)


def enabled():
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


# Calls kept back each day for recently published videos; backlog (old or undated) only uses what is left.
RESERVE_NEW = int(os.getenv("GEMINI_VIDEO_RESERVE_NEW", "4"))
UNSUPPORTED_DAYS = 3        # 403 on this many distinct days ...
UNSUPPORTED_WINDOW = 14     # ... within this many recent days -> treat the channel as gemini_unsupported
_priority = "new"


@contextlib.contextmanager
def priority(kind):
    """'new' (published within the recent window) or 'backlog' (older or undated) for the calls inside."""
    global _priority
    prev, _priority = _priority, ("backlog" if kind == "backlog" else "new")
    try:
        yield
    finally:
        _priority = prev


def budget_ok():
    day = (_load_budget().get("days") or {}).get(_today()) or {}
    cap = DAILY_CAP if _priority == "new" else max(0, DAILY_CAP - RESERVE_NEW)
    # Only a 429 recorded under the Pacific quota day stops calls; a legacy UTC-day flag is history, not a block.
    exhausted = bool(day.get("exhausted")) and day.get("exhausted_quota_day") == _today()
    return _run_calls < RUN_CAP and int(day.get("calls") or 0) < cap and not exhausted


def unsupported_authors(doc=None):
    """Authors with 403 permission_denied on >= UNSUPPORTED_DAYS distinct days in the last UNSUPPORTED_WINDOW
    days. Derived from the budget history (no extra state); lifts by itself once those days age out."""
    days = (doc or _load_budget()).get("days") or {}
    recent = sorted(days)[-UNSUPPORTED_WINDOW:]
    hits = Counter(a for d in recent for a in set((days[d] or {}).get("skip_authors_403") or []))
    return sorted(a for a, n in hits.items() if n >= UNSUPPORTED_DAYS)


def _norm(s):
    return re.sub(r"[\W_]+", "", str(s or "").lower())


TICKER = re.compile(r"(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])")


def identity_ok(parsed, title, author):
    """Did Gemini actually see this video? The prompt only carries the URL, never the title, so matching the
    known title's distinctive tickers is evidence the model read the real video even when it misremembers the
    exact title wording (first live run: right channel and tickers, wrong title/date -> was wrongly rejected)."""
    seen_title, seen_channel = _norm(parsed.get("observed_title")), _norm(parsed.get("observed_channel"))
    want_title = _norm(title)
    if not seen_title or not want_title:
        return False
    ratio = difflib.SequenceMatcher(None, seen_title, want_title).ratio()
    names = [_norm(x) for x in re.split(r"[/|]", author or "") if _norm(x)]
    channel_hit = any(n and (n in seen_channel or seen_channel in n) for n in names) if seen_channel else False
    if ratio >= 0.6 or (ratio >= 0.35 and channel_hit):
        return True
    want_tickers = set(TICKER.findall(title or ""))
    seen_tickers = set(TICKER.findall(str(parsed.get("observed_title") or ""))) | {
        str(x).upper() for x in (parsed.get("symbols") or []) if isinstance(x, str)}
    return channel_hit and len(want_tickers) >= 2 and len(want_tickers & seen_tickers) >= 2


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


TRADE_WORDS = {"buy", "sell", "short", "cover", "order", "trade", "place_order", "open", "close"}


def _safe(parsed):
    """The model's own 'safety' echo is not a guarantee - MyAlpha enforces the guardrails itself (Q3, never
    rule-eligible, forward_evidence_eligible=false). Reject only when the model proposes a concrete trade
    action for the platform; other wording ('none', 'n/a', flags flipped) is ignored and overwritten."""
    s = parsed.get("safety")
    if not isinstance(s, dict):
        return True
    action = str(s.get("production_action") or "").strip().lower()
    return action not in TRADE_WORDS


def render(parsed):
    """Runtime learning text (fed to the existing symbol/theme/claim extractors); not stored as a whole."""
    lines = ["[Gemini 视频理解 · 未验证] " + str(parsed.get("summary_zh") or "").strip()]
    for c in claims(parsed):
        tag = " ".join(x for x in (c.get("timestamp"), c.get("symbol"), c.get("stance"), c.get("price")) if x)
        lines.append(f"- [{tag}] {c['claim']}")
    for m in macro(parsed):
        lines.append(f"宏观：{m['indicator']} {m.get('value') or ''}（预期 {m.get('expectation') or '—'}）{m.get('period') or ''}")
    for m in (parsed.get("methods") or [])[:6]:
        if isinstance(m, dict) and m.get("name"):
            lines.append(f"方法：{m['name']} 参数 {json.dumps(m.get('explicit_parameters') or {}, ensure_ascii=False)}")
    for v in (parsed.get("invalidations") or [])[:6]:
        if isinstance(v, dict) and v.get("condition"):
            lines.append(f"失效条件：{v.get('symbol') or ''} {v['condition']}")
    return "\n".join(lines).strip()


SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _symbol(v):
    """Ticker as given by the model, upper-cased; anything that is not ticker-shaped becomes None (never guessed)."""
    s = str(v or "").strip().lstrip("$").upper()
    return s if SYMBOL_RE.match(s) else None


def claims(parsed):
    out = []
    listed = {_symbol(x) for x in (parsed.get("symbols") or [])} - {None}
    for c in (parsed.get("claims") or [])[:MAX_CLAIMS]:
        if not isinstance(c, dict) or not str(c.get("claim") or "").strip():
            continue
        row = {k: (str(c.get(k)).strip()[:CLAIM_CHARS] if c.get(k) not in (None, "") else None)
               for k in ("claim", "stance", "price", "timestamp", "evidence_mode", "confidence")}
        sym = _symbol(c.get("symbol"))
        row["symbol"] = sym
        # a ticker the model did not also list among the discussed symbols is kept but flagged for spot-check
        row["symbol_check"] = None if sym is None else ("listed" if sym in listed else "not_in_symbols")
        out.append(row)
    return out


def macro(parsed):
    out = []
    for m in (parsed.get("macro") or [])[:MAX_MACRO]:
        if isinstance(m, dict) and str(m.get("indicator") or "").strip():
            out.append({k: (str(m.get(k)).strip()[:CLAIM_CHARS] if m.get(k) not in (None, "") else None)
                        for k in ("indicator", "value", "expectation", "period", "timestamp")})
    return out


def _author_blocked_today(author):
    doc = _load_budget()
    day = (doc.get("days") or {}).get(_today()) or {}
    return bool(author) and (author in (day.get("skip_authors_403") or []) or author in unsupported_authors(doc))


MEMBERS_ONLY = re.compile(r"会员|members?[ -]?only|member exclusive", re.I)
AUTHOR_403_VIDEOS = 2       # distinct videos with 403 in one day before the whole author is skipped that day
GIVE_UP_IDENTITY = 2        # identity mismatches on one video (any days) before Gemini stops trying it
GIVE_UP_TIMEOUT = 3         # ReadTimeouts on one video (any days) before Gemini stops trying it (long video)
# 10/29-10/30: QHrNWTgD7DA timed out 5 times (TIMEOUT 420 s each) and 9 of 14 calls were exceptions; a timed-out
# call is billed, so one long video kept eating the free daily quota. After one timeout in a quota day the video
# waits for the next quota day; after GIVE_UP_TIMEOUT it is left to the Owner's /yt path (like identity_mismatch).


def _members_only(title):
    """Members-only uploads (e.g. '（会员第301期）') always 403 for Gemini: never spend a call on them."""
    return bool(MEMBERS_ONLY.search(str(title or "")))


def _video_given_up(video_id, doc=None):
    """Gemini repeatedly 'saw' a different video (identity_mismatch) -> leave it to the Owner's /yt path."""
    days = (doc or _load_budget()).get("days") or {}
    n = sum(1 for d in days.values() for r in (d or {}).get("recent") or []
            if isinstance(r, dict) and r.get("video_id") == video_id and r.get("outcome") == "identity_mismatch")
    return n >= GIVE_UP_IDENTITY


def _timeouts(video_id, doc=None, today_only=False):
    days = (doc or _load_budget()).get("days") or {}
    pick = {_today(): days.get(_today())} if today_only else days
    return sum(1 for d in pick.values() for r in (d or {}).get("recent") or []
               if isinstance(r, dict) and r.get("video_id") == video_id and r.get("outcome") == "exception"
               and str(r.get("detail") or "").startswith(("ReadTimeout", "Timeout", "ConnectTimeout")))


def _video_timed_out(video_id, doc=None):
    """Skip a video that already timed out this quota day; give it up after GIVE_UP_TIMEOUT timeouts in total."""
    doc = doc or _load_budget()
    return _timeouts(video_id, doc, today_only=True) >= 1 or _timeouts(video_id, doc) >= GIVE_UP_TIMEOUT


def _block_author_today(author, video_id=None):
    """403 permission_denied: one video may simply be restricted (members-only, premiere); only when
    AUTHOR_403_VIDEOS distinct videos of the same author 403 on the same UTC day is the author skipped for the
    rest of that day (and those days feed the 3-in-14 'unsupported' rule). Resets the next day."""
    if not author:
        return
    doc = _load_budget()
    day = doc.setdefault("days", {}).setdefault(_today(), {"calls": 0, "admitted": 0, "rejected": 0, "errors": 0})
    vids = {r.get("video_id") for r in day.get("recent") or []
            if isinstance(r, dict) and r.get("outcome") == "http_403" and r.get("author") == str(author)[:60]}
    if video_id:
        vids.add(video_id)
    if len(vids - {None}) >= AUTHOR_403_VIDEOS:
        day["skip_authors_403"] = sorted(set(day.get("skip_authors_403") or []) | {str(author)[:80]})
        _save_budget(doc)


def acquire(video_id, title, author, post=None):
    """Return an Acquisition-compatible dict, or None (disabled, over budget, failed or unverified)."""
    global _run_calls
    if not enabled() or _members_only(title) or _video_given_up(video_id) or _video_timed_out(video_id):
        return None
    if not budget_ok() or _author_blocked_today(author):
        return None
    post = post or requests.post
    _run_calls += 1
    _bump("calls")
    who = {"author": author, "title": title}
    url = f"https://www.youtube.com/watch?v={video_id}"
    used = MODEL
    try:
        headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip(), "Content-Type": "application/json",
                   "User-Agent": "MyAlphaView-YT01/1.0"}
        r = None
        # "high demand" (503) on one model: wait briefly and try the next free model inside the same call.
        # A fallback model whose own free quota is spent (429) is skipped for the rest of the quota day.
        models = [m for i, m in enumerate(MODELS) if i == 0 or not _fallback_exhausted(m)]
        for i, model in enumerate(models):
            if i:
                time.sleep(RETRY_WAIT)
            used = model
            body = {"model": model, "input": [{"type": "video", "uri": url}, {"type": "text", "text": PROMPT}]}
            r = post(ENDPOINT, json=body, timeout=TIMEOUT, headers=headers)
            if r.status_code != 503:
                break
        if r.status_code == 429 and used != MODELS[0]:
            # Quotas are per model. The primary only said "busy" (503) and its own quota is untouched, so a 429 from
            # the fallback must not stop the whole quota day (10/26-10/28: 3 of 4 day-stopping 429s came from the
            # fallback). Nothing was processed -> refund; the fallback is skipped for the rest of this quota day.
            _bump("errors", video_id, "http_429_fallback", _body(r), model=used, **who)
            _mark_fallback_exhausted(used)
            _refund()
            return None
        if r.status_code == 429:
            _bump("exhausted", video_id, "http_429", _body(r), model=used, **who)
            return None
        if r.status_code == 503:
            # Google-side overload: nothing was processed, so the call is refunded to today's budget.
            _bump("errors", video_id, "http_503_all_models", _body(r), model=",".join(MODELS), **who)
            _refund()
            return None
        if r.status_code != 200:
            _bump("errors", video_id, f"http_{r.status_code}", _body(r), model=used, **who)
            if r.status_code == 403:
                _block_author_today(author, video_id)
            return None
        parsed = _extract_json(r.json())
    except Exception as exc:
        _bump("errors", video_id, "exception", type(exc).__name__, model=used, **who)
        return None
    if not isinstance(parsed, dict):
        _bump("rejected", video_id, "no_json", model=used, **who)
        return None
    if not _safe(parsed):
        _bump("rejected", video_id, "safety_contract", json.dumps(parsed.get("safety"), ensure_ascii=False), model=used, **who)
        return None
    if not identity_ok(parsed, title, author):
        _bump("rejected", video_id, "identity_mismatch",
              f"seen={str(parsed.get('observed_title'))[:60]!r} channel={str(parsed.get('observed_channel'))[:30]!r}", model=used, **who)
        return None
    text = render(parsed)
    if len(str(parsed.get("summary_zh") or "").strip()) < 20 or not claims(parsed):
        _bump("rejected", video_id, "thin_content", model=used, **who)
        return None
    _bump("admitted", video_id, "admitted", model=used, **who)
    return {
        "text": text, "status": "available", "quality": "Q3", "provider": "gemini_video",
        "provider_url": url, "content_origin": ORIGIN,
        "timestamp_evidence": any(c.get("timestamp") for c in claims(parsed)),
        "rule_candidate_allowed": False, "chars": len(text),
        "note": f"Gemini {used} read the public video; experimental, pending Owner spot check.",
        "structured": {"model": used, "observed_title": parsed.get("observed_title"),
                       "claims": claims(parsed), "macro": macro(parsed), "symbols": [str(s)[:12] for s in (parsed.get("symbols") or [])][:12],
                       "uncertainties": [str(u)[:CLAIM_CHARS] for u in (parsed.get("uncertainties") or [])][:5]},
    }
