#!/usr/bin/env python3
"""Normalize Wenxuecity captures into a source-preserving research feed.

Collector responsibility only:
- preserve author/source/time/link
- keep a bounded excerpt for research routing
- never convert an author's opinion into a trade instruction
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, tempfile
from datetime import datetime, timedelta
from pathlib import Path

import wxc_blog as blog

DATA_DIR = Path(os.getenv("DATA_DIR", "state"))
FEED_PATH = DATA_DIR / "research_feed.json"
BLOG_SEEN = DATA_DIR / "seen_blog_BrightLine.json"  # legacy alias
BLOG_PROFILES = ("BrightLine", "yifan99")

def blog_seen_path(author: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", author or "unknown")
    return DATA_DIR / f"seen_blog_{safe}.json"
MAX_FEED = 1200
MAX_EXCERPT = 360

THEMES = {
    "Sell Put": ["sell put", "sp ", "卖put", "卖 put", "put"],
    "LEAPS": ["leap", "leaps", "长期期权"],
    "风险管理": ["风险", "回撤", "现金", "保险", "对冲", "止损", "爆仓", "stop loss", "mental stop", "risk management"],
    "失败复盘": ["认错", "失败", "亏", "割肉", "复盘", "看错", "wrong", "mistake"],
    "长期持有纪律": ["长期", "长持", "定投", "time in the market", "纪律"],
    "趋势确认": ["突破", "breakout", "strong close", "hold above", "technical analysis", " ta "],
    "逆向交易": ["恐慌时买", "恐慌买入", "buy when they are panic", "buy when they panic", "panic"],
    "止损纪律": ["止损", "stop loss", "mental stop"],
    "INTC": ["intc", "intel", "英特尔"],
    "IREN": ["iren"],
    "TSLA": ["tsla", "tesla", "特斯拉"],
}

def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def _canonical(url: str) -> str:
    return re.sub(r"#.*$", "", url or "")

def _key(author: str, url: str, published: str, title: str) -> str:
    raw = "|".join([author or "", _canonical(url), published or "", title or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


SYMBOL_ALIASES = {
    "英特尔":"INTC","intel":"INTC",
    "iren":"IREN","特斯拉":"TSLA","tesla":"TSLA",
    "nebius":"NBIS","coreweave":"CRWV",
    "marvell":"MRVL","英伟达":"NVDA","美光":"MU",
    "servicenow":"NOW","paypal":"PYPL",
}

TICKER_WHITELIST = {
    "INTC","IREN","TSLA","NBIS","CRWV","META","QCOM","MRVL","NVDA","MU","NOW",
    "PYPL","COIN","AAPL","AMZN","GOOG","GOOGL","QQQ","TQQQ","SMH","SPY","VOO","QLD","VGT"
}
AMBIGUOUS_TICKERS = {"NOW","MU","META","COIN"}

def _has_ascii_word(text: str, token: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.I))

def detect_symbols(text: str) -> list[str]:
    raw = text or ""
    low = raw.lower()
    out = []

    # Company names / Chinese aliases are safe to match case-insensitively.
    for alias in sorted(SYMBOL_ALIASES, key=len, reverse=True):
        hit = _has_ascii_word(raw, alias) if alias.isascii() else alias in raw
        if hit:
            sym = SYMBOL_ALIASES[alias]
            if sym not in out:
                out.append(sym)

    # Tickers must be standalone tokens. Ambiguous English words require uppercase/cashtag form.
    for sym in sorted(TICKER_WHITELIST, key=len, reverse=True):
        pattern = rf"(?<![A-Za-z0-9])\$?{re.escape(sym)}(?![A-Za-z0-9])"
        if sym in AMBIGUOUS_TICKERS:
            hit = bool(re.search(pattern, raw))
        else:
            hit = bool(re.search(pattern, raw, re.I))
        if hit and sym not in out:
            out.append(sym)
    return out[:12]

def _sentences(text: str) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= 260:
            out.append(line)
        else:
            out.extend(x.strip() for x in re.split(r"(?<=[。！？；])", line) if x.strip())
    return out

def classify_attribution(title: str, unit: str, context: str) -> tuple[str, str]:
    third_names = ("段永平","巴菲特","德鲁肯米勒","斯坦利","芒格","Burry","伯里")
    third = any(name.lower() in (title + " " + unit).lower() for name in third_names)
    first = bool(re.search(r"(^|[，。；：\\s])(我|我的|我在|我已经|我现在|我会|我不|我只|我买|我卖|我加|我减|我持有|我清仓|我重仓|我准备)", context))
    plan = bool(re.search(r"预设点位|现在的做法|第一档|第二档|目标区|卖出线|才考虑|接到货再说", context))
    if first and plan:
        return "author_plan", "high"
    if first:
        return "author_action", "high"
    if third:
        return "third_party_example", "high"
    if plan:
        return "author_plan", "medium"
    return "unconfirmed_author_context", "needs_review"


def extract_structured_learning(text: str) -> dict:
    operations = []
    portfolio_rules = []
    lessons = []
    units = _sentences(text)
    title = units[0] if units else ""
    for i, unit in enumerate(units):
        context = " ".join(units[max(0, i-3):i+1])
        attribution, attribution_confidence = classify_attribution(title, unit, context)
        syms = detect_symbols(unit)
        op = {"symbols": syms} if syms else None
        if op:
            m = re.search(r"第一档\s*([0-9]+(?:\.[0-9]+)?)", unit, re.I)
            if m: op["entry_1"] = float(m.group(1))
            m = re.search(r"第二档\s*([0-9]+(?:\.[0-9]+)?)", unit, re.I)
            if m: op["entry_2"] = float(m.group(1))
            m = re.search(r"卖出线\s*(?:暂时不定|([0-9]+(?:\.[0-9]+)?))", unit, re.I)
            if m: op["exit_line"] = None if m.group(1) is None else float(m.group(1))
            m = re.search(r"目标区\s*([0-9]+(?:\.[0-9]+)?)\s*(?:到|[-–~至])\s*([0-9]+(?:\.[0-9]+)?)", unit, re.I)
            if m: op["target_range"] = [float(m.group(1)), float(m.group(2))]
            m = re.search(r"(?:卖|sell)\s*([0-9]+(?:\.[0-9]+)?)\s*行权价.*?(?:put)", unit, re.I)
            if m: op["sell_put_strike"] = float(m.group(1))
            m = re.search(r"跌到\s*([0-9]+(?:\.[0-9]+)?)\s*以下.*?第一档", unit, re.I)
            if m: op["entry_below"] = float(m.group(1))
            acts = []
            for label, pat in [
                ("clear", r"清仓"), ("trim_half", r"卖掉一半"),
                ("trim", r"减仓|卖掉不小的一部分|开始卖"),
                ("add", r"加仓|补仓|继续买"), ("buy", r"买入|建仓|逢低买"),
                ("sell", r"卖出"), ("sell_put", r"卖\s*\d*(?:\.\d+)?\s*行权价.*?put|sell put"),
                ("hold", r"持有|一股也不卖"), ("no_add", r"不主动加"),
                ("no_direct_stock_buy", r"不直接买股票"),
            ]:
                if re.search(pat, unit, re.I):
                    acts.append(label)
            if acts: op["actions"] = acts
            cond = []
            if "不主动加" in unit: cond.append("no_active_add")
            if "只有跌到" in unit and "才考虑" in unit: cond.append("only_below_threshold")
            if "接到货再说" in unit: cond.append("accept_assignment_then_reassess")
            if cond: op["conditions"] = cond
            if len(op) > 1 and (acts or any(k in op for k in ("entry_1","entry_2","exit_line","target_range","sell_put_strike","entry_below"))):
                op["attribution"] = attribution
                op["attribution_confidence"] = attribution_confidence
                operations.append(op)

        for typ, pat in [
            ("cash_floor", r"现金底线不破|现金比例不跌破底线"),
            ("no_core_leverage", r"核心仓位不上杠杆"),
            ("predefined_levels", r"预设点位|把点位写下来|跌到就买，不跌就不买"),
            ("one_tranche_at_a_time", r"每次只用一档|不允许一次打完"),
            ("do_not_chase", r"不追高|不追涨"),
            ("speculation_stop_10", r"投机股一旦回撤\s*10%.*?止损"),
            ("sell_put_only_willing_to_own", r"只卖\s*put\s*给自己愿意长期持有"),
            ("dca_core", r"核心长期股采用\s*DCA|逢低逐步买入"),
            ("keep_cash_30", r"保留约\s*30%\s*现金"),
            ("avoid_extreme_emotion", r"避免在极端情绪日做重大决策"),
        ]:
            if re.search(pat, unit, re.I):
                portfolio_rules.append(typ)
        for typ, pat in [
            ("cash_too_early", r"加得太快.*太猛|子弹在半山腰就打光"),
            ("process_wrong", r"过程是错的"),
            ("luck_not_skill", r"不是我预判精准.*运气|把运气当能力"),
            ("thesis_vs_timing", r"方向正确.*不代表|判断没错.*过程"),
            ("admit_wrong", r"认错|看错了|割肉"),
        ]:
            if re.search(pat, unit, re.I):
                lessons.append(typ)

    def uniq_dicts(rows):
        seen, out = set(), []
        for row in rows:
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key); out.append(row)
        return out
    return {
        "symbols": detect_symbols(text),
        "operations": uniq_dicts(operations)[:20],
        "portfolio_rules": list(dict.fromkeys(portfolio_rules))[:12],
        "lessons": list(dict.fromkeys(lessons))[:12],
    }

def detect_themes(text: str) -> list[str]:
    low = (text or "").lower()
    found = [name for name, keys in THEMES.items() if any(k in low for k in keys)]
    return found[:8] or ["其他研究"]

def normalize(source_kind: str, author: str, post: dict) -> dict:
    title = str(post.get("title") or "").strip()
    text = str(post.get("text") or "").strip()
    url = _canonical(str(post.get("url") or ""))
    published = str(post.get("date") or post.get("published_at") or "")
    joined = f"{title}\n{text}"
    learning = extract_structured_learning(joined)
    return {
        "id": _key(author, url, published, title),
        "source": "wenxuecity",
        "source_kind": source_kind,
        "author": author,
        "published_at": published,
        "title": title,
        "url": url,
        "excerpt": text[:MAX_EXCERPT],
        "content_chars": len(text),
        "images_count": len(post.get("images") or []),
        "themes_hint": detect_themes(joined),
        "symbols": learning["symbols"],
        "operations": learning["operations"],
        "portfolio_rules": learning["portfolio_rules"],
        "lessons": learning["lessons"],
        "captured_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source_notice": "作者原始观点/操作记录，仅作研究来源；公开归档仅保留短摘录与原文链接，MyAlpha需独立验证后才形成本站判断。",
    }

def append_records(records: list[dict]) -> int:
    if not records:
        return 0
    feed = _read(FEED_PATH, {"version": 1, "records": []})
    existing = {x.get("id") for x in feed.get("records", [])}
    added = 0
    for row in records:
        if row.get("id") and row["id"] not in existing:
            feed.setdefault("records", []).append(row)
            existing.add(row["id"]); added += 1
    feed["records"] = sorted(feed["records"], key=lambda x: x.get("captured_at", ""))[-MAX_FEED:]
    feed["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    _write(FEED_PATH, feed)
    return added

def add_forum_posts(author: str, posts: list[dict]) -> int:
    return append_records([normalize("forum", author, p) for p in posts])

def capture_blog_profile(name: str, days: int = 2) -> list[dict]:
    profile = blog.resolve_profile(name)
    if not profile:
        return []
    author = profile["author"]
    end = datetime.now()
    start = end - timedelta(days=days)
    outdir = tempfile.mkdtemp(prefix=f"wxc_blog_daily_{author}_")
    try:
        result = blog.collect(profile, start, end, outdir, delay=2.5, max_articles=40, max_images=0)
        seen_path = blog_seen_path(author)
        # Preserve BrightLine's original state filename for backward compatibility.
        if author == "BrightLine" and BLOG_SEEN.exists() and not seen_path.exists():
            seen_path = BLOG_SEEN
        # If this author has never had a blog seen-state before, the first
        # successful scan is a recovery/bootstrap of pre-existing material.
        # Mark it explicitly so downstream Forward Evidence cannot mistake a
        # collector rollout/backfill for a genuine point-in-time observation.
        bootstrap_backfill = not seen_path.exists()
        seen = set(_read(seen_path, []))
        fresh = []
        for post in result.get("posts", []):
            pid = post.get("id")
            if pid and pid not in seen:
                row = normalize("blog", author, post)
                row["intake_class_hint"] = "backfill" if bootstrap_backfill else "live_candidate"
                row["capture_mode"] = "initial_blog_profile_backfill" if bootstrap_backfill else "scheduled_blog_scan"
                fresh.append(row)
                seen.add(pid)
        _write(seen_path, sorted(seen))
        append_records(fresh)
        return fresh
    finally:
        shutil.rmtree(outdir, ignore_errors=True)

def capture_brightline(days: int = 2) -> list[dict]:
    return capture_blog_profile("BrightLine", days=days)

def capture_configured_blogs(days: int = 2) -> dict[str, list[dict]]:
    return {name: capture_blog_profile(name, days=days) for name in BLOG_PROFILES}

def records_for_day(day: str) -> list[dict]:
    feed = _read(FEED_PATH, {"records": []})
    out = []
    for r in feed.get("records", []):
        p = str(r.get("published_at") or "")
        c = str(r.get("captured_at") or "")
        if p.startswith(day) or c.startswith(day):
            out.append(r)
    return out

def daily_digest_text(day: str) -> str:
    rows = records_for_day(day)
    if not rows:
        return f"📚 收盘研究归档 {day}\n今日暂无新增可整理来源。"
    lines = [f"📚 收盘研究归档 {day} · {len(rows)} 条", "来源仅作研究，不直接形成买卖建议。"]
    by_author = {}
    for r in rows:
        by_author.setdefault(r.get("author") or "未知作者", []).append(r)
    for author, items in sorted(by_author.items()):
        lines.append(f"\n【{author}】{len(items)} 条")
        for r in items[:8]:
            themes = " / ".join(r.get("themes_hint") or [])
            lines.append(f"• {r.get('title') or '(短评)'} [{themes}]\n  {r.get('url')}")
        if len(items) > 8:
            lines.append(f"  …另 {len(items)-8} 条已归档")
    return "\n".join(lines)
