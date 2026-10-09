#!/usr/bin/env python3
"""Read-only diagnosis of research-feed records that carry only a title (quant-dashboard#133 item 5).

Samples up to N title-only records per author, re-fetches each public post page slowly (2–4.5 s
between requests via the existing fetch helper; stops on repeated failures; never retries around
403/429) and classifies why no body text was stored. Nothing about the feed is modified and no body
text is kept: the report holds only URL, HTTP outcome, selector presence, character/image counts and
a reason code.

Reason codes
  genuinely_empty   : page parsed, author matches, body has no text and no image (title-only post)
  image_only        : body has images but no text (needs image/OCR handling, not a scraper bug)
  body_now_present  : page now has body text although the feed stored none (capture-path defect)
  author_mismatch   : page author differs from the feed author (attribution must be reviewed)
  selector_miss     : page fetched but title/body selectors not found (layout change)
  http_error        : page unavailable (status recorded; no circumvention)
"""
from __future__ import annotations
import argparse, json, os, random, re, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
FEED = ROOT / "state" / "research_feed.json"
OUT = ROOT / "state" / "title_only_diagnosis.json"


def title_only(rec):
    return not str(rec.get("excerpt") or "").strip() and int(rec.get("content_chars") or 0) == 0


def classify(status, parsed, feed_author):
    """Pure classification (unit-tested)."""
    if status != 200:
        return "http_error"
    if not parsed:
        return "selector_miss"
    if str(parsed.get("author") or "").casefold() != str(feed_author or "").casefold():
        return "author_mismatch"
    if parsed.get("text_chars", 0) > 0:
        return "body_now_present"
    if parsed.get("images", 0) > 0:
        return "image_only"
    return "genuinely_empty"


def sample(records, per_author, seed=133):
    by = defaultdict(list)
    for r in records:
        if title_only(r) and r.get("url"):
            by[r.get("author") or "?"].append(r)
    rnd = random.Random(seed)
    out = {}
    for a, rows in by.items():
        rows = sorted(rows, key=lambda r: str(r.get("published_at")))
        out[a] = rnd.sample(rows, min(per_author, len(rows)))
    return out, {a: len(v) for a, v in by.items()}


def probe(url, author, session_get):
    import wxc_scraper as w
    status, parsed = None, None
    try:
        r = session_get(url)
        status = getattr(r, "status_code", None)
        if status == 200:
            r.encoding = "utf-8"
            p = w.parse_post(r.text, url)
            if p:
                parsed = {"author": p.get("author"), "text_chars": len((p.get("text") or "").strip()),
                          "images": len(p.get("images") or []), "title_chars": len(p.get("title") or "")}
    except Exception as e:  # network error → http_error with no status
        status = f"error:{type(e).__name__}"
    return status, parsed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-author", type=int, default=12)
    ap.add_argument("--max-requests", type=int, default=60)
    a = ap.parse_args(argv)
    import wxc_scraper as w
    records = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    picks, totals = sample(records, a.per_author)
    rows, fails, n = [], 0, 0
    for author, recs in picks.items():
        for rec in recs:
            if n >= a.max_requests or fails >= 5:
                break
            time.sleep(random.uniform(2.0, 4.5))
            status, parsed = probe(rec["url"], author, lambda u: w.sess.get(u, timeout=20))
            n += 1
            if status in (403, 429):
                fails = 5  # stop entirely; never circumvent
            elif status != 200:
                fails += 1
            else:
                fails = 0
            rows.append({"author": author, "url": rec["url"], "published_at": rec.get("published_at"),
                         "capture_mode": rec.get("capture_mode") or rec.get("intake_class_hint"),
                         "http": status, "selectors_found": parsed is not None,
                         "page_author_matches": bool(parsed) and str(parsed.get("author") or "").casefold() == author.casefold(),
                         "text_chars_now": (parsed or {}).get("text_chars"), "images_now": (parsed or {}).get("images"),
                         "reason": classify(status, parsed, author)})
    summary = {a: dict(Counter(r["reason"] for r in rows if r["author"] == a)) for a in picks}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "title_only_totals": totals,
              "sampled": len(rows), "stopped_early": fails >= 5, "by_author": summary,
              "overall": dict(Counter(r["reason"] for r in rows)), "rows": rows,
              "policy": "read-only; no body text stored; 2–4.5 s spacing; stops on 403/429 or 5 consecutive failures"}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("title_only_totals", "sampled", "stopped_early", "overall", "by_author")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
