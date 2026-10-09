#!/usr/bin/env python3
"""Rule-based extraction of checkable research claims from author text (forum / blog / transcript).

A claim is the smallest unit MyAlpha can later verify: {symbol, stance, horizon?, conditional, price?}.
Nothing here stores third-party wording: each claim keeps only structured fields, the length of the
supporting sentence and its sha256, so the public repository never republishes the source text while a
reviewer holding the original can still prove which sentence a claim came from.

Stances: buy, add, sell, trim, hold, avoid, bullish, bearish. A sentence with a symbol but no
stance cue is not a claim (mentions are not opinions). Questions ("可以买入了？") are recorded as
stance with question=True so they are never mistaken for an explicit call.
"""
from __future__ import annotations
import hashlib, re

STANCE_CUES = [
    ("hold", r"(?:没有|没|不|未|不会)(?:减仓|卖出?|卖掉|清仓|止盈)|not selling|won'?t sell"),
    ("trim", r"减仓|卖掉一半|卖出一部分|止盈|trim|tak(?:e|ing) (?:some )?profits?"),
    ("sell", r"清仓|卖出|卖掉|sell\b|exit"),
    ("add", r"加仓|补仓|继续买|add to|adding"),
    ("buy", r"买入|建仓|逢低买|抄底|上车|必买|值得买|buy\b|bought|accumulat"),
    ("hold", r"继续持有|拿住|一股也不卖|持有不动|hold\b|holding"),
    ("avoid", r"不碰|远离|回避|不建议买|avoid|stay away"),
    ("bearish", r"看空|看跌|见顶|泡沫|下跌空间|bearish|overvalued"),
    ("bullish", r"看好|看涨|上涨空间|低估|牛股|bullish|undervalued|upside"),
]
HORIZON = [
    ("long", r"长期|长线|几年|多年|long[- ]term|years"),
    ("short", r"短期|短线|这周|下周|本周|近期|short[- ]term|this week|next week"),
    ("medium", r"中期|几个月|今年|年底|medium[- ]term|months|this year"),
]
CONDITIONAL = r"如果|要是|跌到|涨到|一旦|除非|假如|if\b|once\b|unless"
PRICE = r"(?:\$|美元|价位|跌到|涨到|目标价?|target)\s*([0-9]{1,5}(?:\.[0-9]{1,2})?)"
TICKER = r"(?<![A-Za-z$])\$?([A-Z]{2,5})(?![A-Za-z])"
STOP = {"ETF", "CEO", "IPO", "AI", "GDP", "CPI", "FED", "USD", "THE", "AND", "FOR", "YOU", "EPS", "PE", "OK", "US", "IRA", "API"}
ALIASES = {"英伟达": "NVDA", "特斯拉": "TSLA", "苹果": "AAPL", "微软": "MSFT", "谷歌": "GOOGL", "亚马逊": "AMZN",
           "美光": "MU", "台积电": "TSM", "超微": "AMD", "纳指": "QQQ", "标普": "VOO", "博通": "AVGO", "甲骨文": "ORCL",
           "脸书": "META", "奈飞": "NFLX", "黄金": "GLD"}


def sentences(text: str) -> list[str]:
    """Split on Chinese/English sentence ends without needing whitespace; long unpunctuated
    transcript runs are chunked so a claim stays local to its words."""
    out = []
    for part in re.split(r"(?<=[。！？!?；;])|(?<=\.)\s+|\n+", text or ""):
        part = re.sub(r"\s+", " ", part).strip()
        while len(part) > 160:
            cut = max(part.rfind("，", 0, 160), part.rfind(",", 0, 160), part.rfind(" ", 0, 160))
            cut = cut if cut > 40 else 160
            out.append(part[:cut].strip()); part = part[cut:].strip(" ，,")
        if len(part) >= 6:
            out.append(part)
    return out


def symbols_in(s: str) -> list[str]:
    """Use the feed's own whitelist + alias detection (pilot showed free-form uppercase tokens such as
    'SP' from 'S&P' or strategy acronyms become false tickers); fall back to the local regex only
    when research_feed is unavailable."""
    try:
        import research_feed as _rf
        syms = list(_rf.detect_symbols(s))
    except Exception:
        syms = [m for m in re.findall(TICKER, s) if m not in STOP]
    syms += [v for k, v in ALIASES.items() if k in s]
    return list(dict.fromkeys(syms))


def extract_claims(text: str, limit: int = 30) -> list[dict]:
    claims, seen = [], set()
    for s in sentences(text):
        syms = symbols_in(s)
        if not syms:
            continue
        low = s.lower()
        stances = [name for name, pat in STANCE_CUES if re.search(pat, low, re.I)]
        if not stances:
            continue
        horizon = next((h for h, pat in HORIZON if re.search(pat, low, re.I)), None)
        price = re.search(PRICE, s, re.I)
        digest = hashlib.sha256(s.encode("utf-8")).hexdigest()
        for sym in syms:
            key = (sym, stances[0], digest)
            if key in seen:
                continue
            seen.add(key)
            claims.append({"symbol": sym, "stance": stances[0], "stance_cues": stances[:3], "horizon": horizon,
                           "conditional": bool(re.search(CONDITIONAL, low, re.I)),
                           "question": s.rstrip().endswith(("?", "？", "吗")),
                           "price": float(price.group(1)) if price else None,
                           "evidence_sha256": digest, "evidence_chars": len(s)})
            if len(claims) >= limit:
                return claims
    return claims


EXTRACTOR_VERSION = "ce-3"  # ce-2 whitelist/aliases + negated sells → hold, "taking profit" → trim


def review_material(text: str, excerpt_chars: int = 40, max_missed: int = 5) -> dict:
    """Reviewer aid (#133 decision C allows short excerpts + locators, not full text):
    claim sentences and symbol-mentioning sentences that produced no claim (possible false negatives),
    each as a ≤excerpt_chars excerpt + sentence index + sha256."""
    claimed, missed = [], []
    for i, s in enumerate(sentences(text)):
        syms = symbols_in(s)
        if not syms:
            continue
        has_stance = any(re.search(pat, s.lower(), re.I) for _, pat in STANCE_CUES)
        keys = [k for k, v in ALIASES.items() if v in syms and k in s] + syms
        pos = min((s.find(k) for k in keys if s.find(k) >= 0), default=0)
        start = max(0, min(pos - excerpt_chars // 2, len(s) - excerpt_chars))
        item = {"i": i, "symbols": syms, "excerpt": s[start:start + excerpt_chars], "sha256": hashlib.sha256(s.encode("utf-8")).hexdigest()}
        (claimed if has_stance else missed).append(item)
    return {"claim_sentences": claimed[:30], "mention_without_stance": missed[:max_missed],
            "mention_without_stance_total": len(missed)}


def checkable(claim: dict) -> bool:
    """A claim MyAlpha can later score: explicit (not a question) directional stance on a symbol."""
    return not claim.get("question") and claim.get("stance") in {"buy", "add", "sell", "trim", "avoid", "bullish", "bearish", "hold"}


BOILERPLATE_MARKERS = ("get chrome extension", "popular videos", "recent videos", "video subtitle downloader",
                       "video transcript search", "free tools", "all channels", "leaving a review")


def provider_boilerplate(text: str) -> bool:
    """Transcript-provider navigation page returned instead of a transcript: several site-navigation
    markers and too little other text to be a real transcript."""
    low = (text or "").lower()
    return sum(m in low for m in BOILERPLATE_MARKERS) >= 3 and len(low) < 2000
