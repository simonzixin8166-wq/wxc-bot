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


def stratified_sample(records, total, min_per_author=12, exclude=(), seed=1133):
    """Round 2 (#133 P1-4): proportional allocation across authors (at least min_per_author each,
    capped by population), stratified within each author by publication year so old and new posts are
    both represented; URLs already probed in round 1 are excluded."""
    by = defaultdict(list)
    for r in records:
        if title_only(r) and r.get("url") and r["url"] not in exclude:
            by[r.get("author") or "?"].append(r)
    pop = {a: len(v) for a, v in by.items()}
    n_all = sum(pop.values()) or 1
    alloc = {a: min(pop[a], max(min_per_author, round(total * pop[a] / n_all))) for a in pop}
    rnd = random.Random(seed)
    out = {}
    for a, rows in by.items():
        years = defaultdict(list)
        for r in sorted(rows, key=lambda r: (str(r.get("published_at")), r["url"])):
            years[str(r.get("published_at") or "")[:4] or "?"].append(r)
        k, picks = alloc[a], []
        for y, yr in sorted(years.items()):
            share = max(1, round(k * len(yr) / len(rows)))
            picks += rnd.sample(yr, min(share, len(yr)))
        rnd.shuffle(picks)
        out[a] = picks[:k]
    return out, pop, alloc


def wilson(k, n, z=1.96):
    """95% Wilson interval for a proportion (small samples)."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def estimate(rows, pop):
    """Per-author share of each reason with Wilson CI, plus a population-weighted overall estimate."""
    per, weighted = {}, Counter()
    for a, n_pop in pop.items():
        rs = [r for r in rows if r["author"] == a and r["reason"] != "http_error"]
        cnt = Counter(r["reason"] for r in rs)
        per[a] = {"population": n_pop, "probed": len(rs),
                  "reasons": {k: {"n": v, "share": round(v / len(rs), 3), "ci95": wilson(v, len(rs))} for k, v in cnt.items()}}
        for k, v in cnt.items():
            weighted[k] += n_pop * v / len(rs) if rs else 0
    tot = sum(pop.values()) or 1
    return per, {k: round(v / tot, 3) for k, v in weighted.items()}


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
    ap.add_argument("--round2-total", type=int, default=0, help="stratified round 2 sample size (0 = round 1 mode)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    import wxc_scraper as w
    records = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    alloc = None
    if a.round2_total:
        prev = set()
        try:
            prev = {r["url"] for r in json.loads(OUT.read_text(encoding="utf-8")).get("rows", [])}
        except Exception:
            pass
        picks, totals, alloc = stratified_sample(records, a.round2_total, exclude=prev)
    else:
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
    if alloc is not None:
        per, weighted = estimate(rows, totals)
        report.update({"round": 2, "allocation": alloc, "excluded_round1_urls": True,
                       "per_author_estimate": per, "population_weighted_share": weighted})
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    keys = ("title_only_totals", "sampled", "stopped_early", "overall", "by_author") + (("population_weighted_share",) if alloc is not None else ())
    print(json.dumps({k: report[k] for k in keys}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
