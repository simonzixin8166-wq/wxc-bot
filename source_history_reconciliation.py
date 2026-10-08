#!/usr/bin/env python3
"""P2-10 author x month source-history reconciliation (forum + blog + one-off research posts).

For every author and publication month: records in the feed, live vs backfill, text depth
(title-only / excerpt / full text), plus per-author coverage facts the collectors already
prove (blog archive months scanned, forum seen-vs-feed gaps). History that was never scanned is
reported as *unknown*, not as zero. Backfilled history is never Genuine Forward.
Read-only over state/; writes state/source_history_reconciliation.json.
"""
from __future__ import annotations
import json, os, re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.getenv("DATA_DIR", "state"))
OUT = STATE / "source_history_reconciliation.json"


def load(name, default):
    try:
        return json.loads((STATE / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def depth(r):
    body = len(str(r.get("text") or r.get("full_text") or r.get("transcript") or ""))
    return "full_text" if body >= 1000 else ("excerpt" if (body or r.get("excerpt")) else "title_only")


def month(v):
    m = re.match(r"(\d{4})-(\d{2})", str(v or ""))
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return f"{m.group(3)}-{m.group(1)}" if m else "unknown"


def post_id(url):
    m = re.search(r"/(\d+)\.html", str(url or ""))
    return m.group(1) if m else None


def build(now=None):
    feed = load("research_feed.json", {}).get("records") or []
    cells = defaultdict(lambda: defaultdict(Counter))
    authors = defaultdict(lambda: {"kinds": set(), "records": 0})
    for r in feed:
        if r.get("source_kind") not in ("forum", "blog"):
            continue
        a, mo = r.get("author") or "unknown", month(r.get("published_at"))
        c = cells[a][mo]
        c["records"] += 1
        c["backfill" if r.get("intake_class_hint") == "backfill" or r.get("forward_evidence_eligible") is False else "live_or_unclassified"] += 1
        c[depth(r)] += 1
        if r.get("operations") or r.get("portfolio_rules") or r.get("lessons"):
            c["structured_view"] += 1
        authors[a]["kinds"].add(r.get("source_kind"))
        authors[a]["records"] += 1

    blog_state = (load("blog_scan_state.json", {}).get("authors") or {})
    watch = set(load("watch.json", []) or [])
    coverage = {}
    for a, info in sorted(authors.items()):
        months = sorted(m for m in cells[a] if m != "unknown")
        cov = {"kinds": sorted(info["kinds"]), "records": info["records"], "first_month": months[0] if months else None,
               "last_month": months[-1] if months else None, "watched_forum_author": a in watch}
        b = blog_state.get(a)
        if b:
            cov["blog"] = {"archive_months_scanned": b.get("archive_months_ok"), "archive_failures": b.get("archive_failures"),
                           "unique_article_ids": b.get("unique_article_ids"), "missing_from_feed": b.get("missing_from_feed"),
                           "recovery_window_days": b.get("recovery_days_used"),
                           "history_before_window": "not_scanned (unknown, not zero)"}
        seen = load(f"seen_{a}.json", None)
        if isinstance(seen, list):
            fids = {post_id(r.get("url")) for r in feed if r.get("author") == a and r.get("source_kind") == "forum"}
            gap = sorted(set(map(str, seen)) - {x for x in fids if x})
            cov["forum"] = {"seen_ids": len(seen), "in_feed": len(fids - {None}), "seen_not_in_feed": len(gap),
                            "seen_not_in_feed_examples": gap[:5],
                            "reason": "legacy seen before the feed existed / not research posts; recoverable only via explicit backfill" if gap else None}
        if not b and not isinstance(seen, list):
            cov["scope"] = "one-off research backfill (not a watched author); no history scan"
        coverage[a] = cov

    return {
        "version": 1,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "principle": "author x month reconciliation; unscanned history is unknown, backfill is never Genuine Forward",
        "matrix": {a: {m: dict(c) for m, c in sorted(ms.items())} for a, ms in sorted(cells.items())},
        "coverage": coverage,
        "totals": {"authors": len(authors), "records": sum(v["records"] for v in authors.values()),
                   "text_depth": dict(Counter(depth(r) for r in feed if r.get("source_kind") in ("forum", "blog")))},
        "access_policy": "no bypassing 403/429 or login walls; history fills only via bounded, rate-limited backfill",
    }


def main():
    out = build()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"totals": out["totals"], "authors": {a: {k: v for k, v in c.items() if k in ("records", "first_month", "last_month")}
                                                           for a, c in out["coverage"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
