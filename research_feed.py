#!/usr/bin/env python3
"""Normalize Wenxuecity captures into a source-preserving research feed.

Collector responsibility only:
- preserve author/source/time/link
- keep a bounded excerpt for research routing
- never convert an author's opinion into a trade instruction
"""
from __future__ import annotations
import hashlib, json, os, re
from datetime import datetime, timedelta
from pathlib import Path

import wxc_blog as blog

DATA_DIR = Path(os.getenv("DATA_DIR", "state"))
FEED_PATH = DATA_DIR / "research_feed.json"
BLOG_SEEN = DATA_DIR / "seen_blog_BrightLine.json"
MAX_FEED = 1200
MAX_EXCERPT = 360

THEMES = {
    "Sell Put": ["sell put", "sp ", "卖put", "卖 put", "put"],
    "LEAPS": ["leap", "leaps", "长期期权"],
    "风险管理": ["风险", "回撤", "现金", "保险", "对冲", "止损", "爆仓"],
    "失败复盘": ["认错", "失败", "亏", "割肉", "复盘", "看错"],
    "长期持有纪律": ["长期", "长持", "定投", "time in the market", "纪律"],
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
    "英特尔":"INTC","intel":"INTC","intc":"INTC",
    "iren":"IREN","特斯拉":"TSLA","tesla":"TSLA","tsla":"TSLA",
    "nebius":"NBIS","nbis":"NBIS","coreweave":"CRWV","crwv":"CRWV",
    "meta":"META","qcom":"QCOM","mrvl":"MRVL","marvell":"MRVL",
    "nvda":"NVDA","英伟达":"NVDA","mu":"MU","美光":"MU",
    "now":"NOW","servicenow":"NOW","pypl":"PYPL","paypal":"PYPL",
    "coin":"COIN","aapl":"AAPL","amzn":"AMZN","goog":"GOOG","googl":"GOOGL",
    "qqq":"QQQ","tqqq":"TQQQ","smh":"SMH","spy":"SPY","voo":"VOO","qld":"QLD","vgt":"VGT",
}

def detect_symbols(text: str) -> list[str]:
    raw = text or ""
    low = raw.lower()
    out = []
    for alias in sorted(SYMBOL_ALIASES, key=len, reverse=True):
        hit = alias in low if alias.isascii() else alias in raw
        if hit:
            sym = SYMBOL_ALIASES[alias]
            if sym not in out:
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

def extract_structured_learning(text: str) -> dict:
    operations = []
    portfolio_rules = []
    lessons = []
    for unit in _sentences(text):
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

def capture_brightline(days: int = 2) -> list[dict]:
    profile = blog.resolve_profile("BrightLine")
    end = datetime.now()
    start = end - timedelta(days=days)
    outdir = str(DATA_DIR / "_blog_daily_tmp")
    result = blog.collect(profile, start, end, outdir, delay=2.5, max_articles=30, max_images=0)
    seen = set(_read(BLOG_SEEN, []))
    fresh = []
    for post in result.get("posts", []):
        pid = post.get("id")
        if pid and pid not in seen:
            fresh.append(normalize("blog", "BrightLine", post))
            seen.add(pid)
    _write(BLOG_SEEN, sorted(seen))
    append_records(fresh)
    return fresh

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
