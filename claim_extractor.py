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
    # option strategies first: selling puts = willing to own (bullish), never a plain "sell"
    ("bullish", r"sell\s*puts?|卖\s*put|卖出看跌|short\s*puts?"),
    ("hold", r"covered\s*calls?|卖\s*call|备兑"),
    ("hold", r"(?:没有|没|不|未|不会)(?:减仓|卖出?|卖掉|清仓|止盈)|not selling|won'?t sell|继续保持|保持\s*\d+%|长期持有|满仓长期|我没动|拿了.{0,10}没动|半股也不会卖"),
    ("trim", r"减仓|减了仓|卖掉一半|卖出一部分|卖了一点|止盈|取利|获利卖|trim|tak(?:e|ing) (?:some )?profits?|took the profit"),
    ("sell", r"清仓|卖出|卖掉|卖了|sell\b|exit"),
    ("add", r"加仓|补仓|继续买|加了|加大|add to|adding|buy more"),
    ("buy", r"买入|建仓|建的仓|逢低买|抄底|上车|必买|值得买|买进|买了|少买了|\d\s*(?:左右)?接(?!受|近|着|下来)|(?<![直承对迎])接(?:的|了)?(?=\s*\d)|(?<![不别])买\s*\$?[A-Z]{2,5}(?![A-Za-z])|buy\b|bought|accumulat|is a buy"),
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
# third-party holders (other investors, quoted examples): their trades are not the author's claims
THIRD_PARTY = r"(?:^|[，,。；;：:\s“\"])(?:他|她|他们|有人|别人|巴菲特|段永平|Asness|作者拿)|举例|据报道|13F"
# extra tickers for claims only; uppercase-only because several are English words
EXTRA_TICKERS = ("ARM", "IBIT", "AEHR", "CRDO", "RKLB", "VSH", "SOXL", "AVL", "COHR", "TSEM", "UPRO", "SNDK", "DIA")
ALIASES = {"亚麻": "AMZN", "古狗": "GOOGL", "Marvell": "MRVL", "CoreWeave": "CRWV", "英伟达": "NVDA", "特斯拉": "TSLA", "苹果": "AAPL", "微软": "MSFT", "谷歌": "GOOGL", "亚马逊": "AMZN",
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
    syms = [x for x in syms if not (x == "BE" and not re.search(r"(?<![A-Za-z])BE(?![A-Za-z])", s))]
    syms += [v for k, v in ALIASES.items() if k in s]
    syms += [t for t in EXTRA_TICKERS if re.search(rf"(?<![A-Za-z0-9]){t}(?![A-Za-z0-9])", s)]
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
        if re.search(THIRD_PARTY, s) and not re.search(r"我|俺|\bI\b|\bmy\b", s):
            continue  # abstain: someone else's position, not the author's
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


EXTRACTOR_VERSION = "ce-4"  # ce-3 + option semantics (sell put → bullish), third-party abstain, executed-trade cues, extra tickers/aliases


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


# ---------------------------------------------------------------------------------------------
# ce-5 high-precision shadow mode (quant-dashboard#133 6107236790 item 2). Developed on gold v1 dev only.
# Keeps a claim only when the sentence is a first-person, explicit statement of a trade or position;
# everything else (forecasts, technical descriptions, questions, irony, third parties, mixed actions
# across several tickers) abstains. Output carries the gate that admitted it, for audit.
HP_VERSION = "ce-5-hp"
FIRST_PERSON = r"我|俺|本人|(?<![A-Za-z])I(?![A-Za-z])|(?<![A-Za-z])my(?![A-Za-z])"
EXECUTED = r"\btaking\b|\bselling\b|\bbuying\b|\badding\b|了|已经?|今天|昨天|昨晚|刚刚|刚才|盘前|盘后|上周|这周|本周|周[一二三四五]|月底|\d+月\d+[号日]|took|sold|bought|exited|added"
FORECAST = r"下一站|估计|猜|应该会|可能会|也许|大概率|看图|目标价|会到|会回到|会有|hard bounce|pt\b|target"
HOLD_POSITION = r"(?:保持|维持)\s*\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*%\s*(?:的)?仓位|重仓|最大仓|满仓|全仓|拿了.{0,10}没动|我没动|半股也不会卖|一股也不卖|不卖"
CONDITIONAL_PLAN = r"(?:如果|若|一旦|跌到|跌下|涨到|到了?)[^。；;]{0,24}(?:就|再|会|才)?\s*(?:买|加仓|加|卖|减仓|止盈|取利)"


def extract_claims_hp(text: str, limit: int = 30) -> list[dict]:
    out = []
    for s in sentences(text):
        low = s.lower()
        cs = [c for c in extract_claims(s, limit=10) if checkable(c)]
        if not cs or s.rstrip().endswith(("?", "？", "吗")):
            continue
        explicit_fp = bool(re.search(FIRST_PERSON, s))
        if re.search(THIRD_PARTY, s) and not explicit_fp:
            continue
        # Chinese posts often drop the subject: no other person named → the author speaks
        fp = explicit_fp or not re.search(r"你|您|他|她|有人|别人|大家|网友|网红|楼主", s)
        stances = {c["stance"] for c in cs}
        if len({c["symbol"] for c in cs}) > 1 and len(stances) > 1:
            continue  # mixed actions across tickers: abstain
        for c in cs:
            st = c["stance"]
            gate = None
            if st in ("buy", "add", "sell", "trim") and fp and re.search(EXECUTED, low) and not c["conditional"]:
                gate, status = "first_person_executed_trade", "executed"
            elif st in ("buy", "add", "sell", "trim") and fp and re.search(CONDITIONAL_PLAN, s):
                gate, status = "first_person_conditional_plan", "conditional"
            elif st == "hold" and re.search(HOLD_POSITION, s) and (fp or re.search(r"(?:保持|维持)\s*\d", s)):
                gate, status = "explicit_position_hold", "opinion"
            elif st == "bullish" and re.search(r"sell\s*puts?|卖\s*put|卖出看跌", low):
                gate, status = "sell_put_willing_to_own", "opinion"
            if not gate or (gate != "first_person_executed_trade" and re.search(FORECAST, low)):
                continue
            out.append({**c, "status": status, "hp_gate": gate})
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------------------------------------------------------
# ce-6 (2026-11-10, S2 v5 dev set only; production still calls extract_claims = ce-4 until the frozen v5 test
# set has measured ce-6 and the Owner approves). Fixes found on the v5 dev set (claude/s2_v5/dev_baseline_notes):
#   - colloquial forum views: target prices, "跌到 X 是好事", "可以的价格", "near the top / 向下概率更高", "look for X to reach"
#   - short posts state the ticker once (title) and the view in another sentence: carry the single ticker
#   - historical or hypothetical sentences (a past year, "如果是…买进") without the author are not claims
CE6_VERSION = "ce-6"
CE6_EXTRA_CUES = [
    ("bullish", r"目标价?\s*(?:依然|仍然|还是)?\s*(?:是|在)?\s*\$?\d|目标是\s*\$?\d|是好事|还可以的价格|可以的价格|价格不错|"
                r"look for .{0,20}to reach|don'?t see anything wrong|最靓仔|会有个?\s*hard bounce"),
    ("bearish", r"local top|near the top|接近.{0,4}顶|向下的?概率比向上的?高|跌的机率更大|跌的概率更大|涨幅有限|不是\s*buy"),
]
CE6_CONDITIONAL = CONDITIONAL + r"|到时候|到时"
CE6_EXTRA_TICKERS = ("SPX",)
HISTORICAL = r"(?<!\d)(?:19\d{2}|20(?:0\d|1\d|2[0-4]))\s*年|如果是.{0,12}(?:买进|买入|买的)|假设|打个比方|举个例子|比如说"
CE6_FIRST_PERSON = r"我|俺|本人|(?<![A-Za-z])I(?![A-Za-z])|(?<![A-Za-z])my(?![A-Za-z])"


def _ce6_symbols(s: str) -> list[str]:
    syms = symbols_in(s)
    syms += [t for t in CE6_EXTRA_TICKERS if re.search(rf"(?<![A-Za-z0-9]){t}(?![A-Za-z0-9])", s) and t not in syms]
    return syms


def _ce6_stances(s: str) -> list[str]:
    low = s.lower()
    # extra colloquial cues are checked first: "目标价 1400" or "不是 buy 的时候" must not fall to the generic buy cue
    extra = [name for name, pat in CE6_EXTRA_CUES if re.search(pat, low, re.I)]
    base = [name for name, pat in STANCE_CUES if re.search(pat, low, re.I)]
    if extra and "bearish" in extra:
        base = [b for b in base if b not in ("buy", "add")]
    return list(dict.fromkeys(extra + base))


def extract_claims_v6(text: str, limit: int = 30, carry_max_chars: int = 600) -> list[dict]:
    sents = sentences(text)
    post_syms = list(dict.fromkeys(x for s in sents for x in _ce6_symbols(s)))
    carry = post_syms[0] if len(post_syms) == 1 and len(text or "") <= carry_max_chars else None
    claims, seen = [], set()
    for s in sents:
        stances = _ce6_stances(s)
        if not stances:
            continue
        syms = _ce6_symbols(s)
        source = "text"
        if not syms and carry:
            syms, source = [carry], "context"
        if not syms:
            continue
        if re.search(THIRD_PARTY, s) and not re.search(CE6_FIRST_PERSON, s):
            continue
        if re.search(HISTORICAL, s) and not re.search(CE6_FIRST_PERSON, s):
            continue  # a past-year story or a hypothetical calculation, not the author's view
        low = s.lower()
        horizon = next((h for h, pat in HORIZON if re.search(pat, low, re.I)), None)
        price = re.search(PRICE, s, re.I)
        digest = hashlib.sha256(s.encode("utf-8")).hexdigest()
        for sym in syms:
            key = (sym, stances[0], digest)
            if key in seen:
                continue
            seen.add(key)
            claims.append({"symbol": sym, "stance": stances[0], "stance_cues": stances[:3], "horizon": horizon,
                           "conditional": bool(re.search(CE6_CONDITIONAL, low, re.I)),
                           "question": s.rstrip().endswith(("?", "？", "吗")),
                           "price": float(price.group(1)) if price else None, "ticker_source": source,
                           "evidence_sha256": digest, "evidence_chars": len(s), "extractor": CE6_VERSION})
            if len(claims) >= limit:
                return claims
    return claims


# ---------------------------------------------------------------- ce-7 (shadow, forum-aware), 2026-11-11
# Built ONLY on the forum DEV set (474 Owner-exported utterances, Claude labels; claude/forum diagnosis 11/11).
# Production stays on ce-4; ce-7 is measured once on a future forum test set (later exports) before any decision.
#   - forum replies are short: a one-line reply ("加仓qqq") is a sentence even under 6 chars
#   - the ticker often lives only in the post being answered: if the reply names no ticker and the parent title
#     names exactly one, carry it (ticker_source=context). Context never adds a claim the reply does not make.
#   - colloquial / English trade wording: 进 / 买回 / 被止损 / 退出来 / sold … put / 卖…葡萄 / long hold / not selling /
#     我的 X / good entry / it's a buy / short target …
#   - advice to "you" in a hypothetical ("如果你在300卖掉…") is not the author's claim
CE7_VERSION = "ce-7"
CE7_CUES = [
    ("bullish", r"sold\s.{0,30}?puts?\b|sell\s.{0,30}?puts?\b|卖(?:出)?的?.{0,10}(?:葡萄|put)|接(?:正)?股"),
    ("hold", r"long hold|not selling|no way i am going to (?:close|sell)|长仓|长持|不会动|不动(?:它|他)|握着不卖|拿着|不打算卖|还不打算卖|"
             r"找不到卖的理由|卖(?:出)?的?\s*cc\b|covered calls?|我的\s*\$?[A-Za-z]{2,5}(?:股票)?|最大仓|i still have"),
    ("sell", r"被止损|止损了|退出来|sold\b|sell (?:another|all|my|half)|全卖了|卖掉|应该去掉|去掉的"),
    ("buy", r"(?:又|再|我|先)进(?!行|步|一步|展|度|化|口|来)|进的|\d\s*(?:又)?进(?!行|步|展|度)|买回|买着|买进|新买|buying|buy buy|"
            r"it'?s a buy|good entry|准备进去|进去搞|可以加|盘前会加|买入小股"),
    ("add", r"又加|也加|再加|加了|今天也加仓|加\s*\$?[A-Z]{2,5}"),
    ("bearish", r"short target|最后需要考虑|回到.{0,8}以下都不是不可能|调整到.{0,8}才合理|破\s*\d+.{0,10}机率大"),
    ("bullish", r"合理估值|合理的?价位|非常合理|bottom is in|肯定涨|只是需要时间|没那么悲观|priced in|long term\b|更安全|安全一点|"
                r"假摔|park money|值那么多|could be a meaningful"),
]
YOU_HYPOTHETICAL = r"如果你|你如果|要是你|假如你|if you\b"
# real US tickers seen in forum talk that the feed whitelist lacks (uppercase-only: identifiers, not stance cues)
CE7_EXTRA_TICKERS = ("TMF", "TLT", "SKHY", "LRCX", "GEV", "VRT", "STX", "WDC", "SITM")


def _ce7_symbols(s: str) -> list[str]:
    syms = _ce6_symbols(s)
    syms += [t for t in CE7_EXTRA_TICKERS if re.search(rf"(?<![A-Za-z0-9]){t}(?![A-Za-z0-9])", s) and t not in syms]
    return syms


def _ce7_sentences(text: str) -> list[str]:
    s = sentences(text)
    t = re.sub(r"\s+", " ", text or "").strip()
    return s or ([t] if t else [])


def _ce7_stances(s: str) -> list[str]:
    low = s.lower()
    seven = [name for name, pat in CE7_CUES if re.search(pat, s, re.I)]
    six = _ce6_stances(s)
    if "bullish" in seven and re.search(r"put|葡萄", low):  # selling puts: never a plain sell
        six = [x for x in six if x not in ("sell", "trim")]
    return list(dict.fromkeys(seven + six))


def extract_claims_v7(text: str, context: str | None = None, limit: int = 30, carry_max_chars: int = 600) -> list[dict]:
    sents = _ce7_sentences(text)
    post_syms = list(dict.fromkeys(x for s in sents for x in _ce7_symbols(s)))
    carry, source0 = None, "context"
    if len(post_syms) == 1 and len(text or "") <= carry_max_chars:
        carry, source0 = post_syms[0], "context"
    elif not post_syms and context:
        ctx = list(dict.fromkeys(_ce7_symbols(context)))
        carry = ctx[0] if len(ctx) == 1 else None
    claims, seen = [], set()
    for s in sents:
        stances = _ce7_stances(s)
        if not stances:
            continue
        syms = _ce7_symbols(s)
        source = "text"
        if not syms and carry:
            syms, source = [carry], source0
        if not syms:
            continue
        fp = re.search(CE6_FIRST_PERSON, s)
        if re.search(THIRD_PARTY, s) and not fp:
            continue
        if re.search(HISTORICAL, s) and not fp:
            continue
        if re.search(YOU_HYPOTHETICAL, s, re.I) and not fp:
            continue
        low = s.lower()
        price = re.search(PRICE, s, re.I)
        digest = hashlib.sha256(s.encode("utf-8")).hexdigest()
        for sym in syms:
            key = (sym, stances[0], digest)
            if key in seen:
                continue
            seen.add(key)
            claims.append({"symbol": sym, "stance": stances[0], "stance_cues": stances[:3],
                           "horizon": next((h for h, pat in HORIZON if re.search(pat, low, re.I)), None),
                           "conditional": bool(re.search(CE6_CONDITIONAL, low, re.I)),
                           "question": s.rstrip().endswith(("?", "？", "吗")),
                           "price": float(price.group(1)) if price else None, "ticker_source": source,
                           "evidence_sha256": digest, "evidence_chars": len(s), "extractor": CE7_VERSION})
            if len(claims) >= limit:
                return claims
    return claims
