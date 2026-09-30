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
MAX_EXCERPT = 2400

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
        "captured_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source_notice": "作者原始观点/操作记录，仅作研究来源；MyAlpha需独立验证后才形成本站判断。",
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
