#!/usr/bin/env python3
"""20-article full-text → checkable-claim pilot (quant-dashboard#133 item 5).

Runtime-only: each public page is fetched slowly, parsed, the claims are extracted from the full text
and from the stored 360-char excerpt, and the text is discarded. The report keeps only URL, author,
character counts and structured claims (symbol / stance / horizon / conditional / price / sentence
hash) — no source wording — so it can be committed to the public repo. No third-party full text is
persisted (that requires the owner's approval, decision A). Stops on 403/429 or repeated failures.
"""
from __future__ import annotations
import argparse, json, random, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import claim_extractor as ce  # noqa: E402

FEED = ROOT / "state" / "research_feed.json"
OUT = ROOT / "state" / "fulltext_claims_pilot.json"
QUOTA = {"BrightLine": 5, "yifan99": 8, "bogbog": 3, "三心三意": 2, "我是一只井底蛙": 1, "jenning": 1}


def pick(records, quota=QUOTA, seed=133):
    rnd = random.Random(seed)
    out = []
    for author, n in quota.items():
        pool = sorted((r for r in records if r.get("author") == author and int(r.get("content_chars") or 0) > 360
                       and r.get("source_kind") in ("forum", "blog") and r.get("url")), key=lambda r: r["url"])
        out += rnd.sample(pool, min(n, len(pool)))
    return out


def summarize(full_claims, excerpt_claims):
    return {"claims_full": len(full_claims), "checkable_full": sum(ce.checkable(c) for c in full_claims),
            "claims_excerpt": len(excerpt_claims), "checkable_excerpt": sum(ce.checkable(c) for c in excerpt_claims),
            "symbols_full": sorted({c["symbol"] for c in full_claims})}


def fetch_text(rec):
    import wxc_scraper as w, wxc_blog as wb
    url = rec["url"]
    if "blog.wenxuecity.com" in url:
        r = wb.get(url, retries=1, delay=0)
        p = wb.parse_article(r.text, url, rec.get("author") or "") if r is not None else None
    else:
        r = w.get(url, retries=1, delay=0)
        p = w.parse_post(r.text, url) if r is not None else None
    status = getattr(r, "status_code", None) if r is not None else None
    if not p:
        return status, None, None
    return status, p.get("author"), f"{p.get('title') or ''}\n{p.get('text') or ''}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args(argv)
    records = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    rows, fails = [], 0
    for rec in pick(records)[: a.limit]:
        if fails >= 5:
            break
        time.sleep(random.uniform(2.0, 4.5))
        status, page_author, text = fetch_text(rec)
        if text is None:
            fails += 1
            rows.append({"url": rec["url"], "author": rec.get("author"), "outcome": "unavailable", "http": status})
            continue
        fails = 0
        excerpt = f"{rec.get('title') or ''}\n{rec.get('excerpt') or ''}"
        full_c, ex_c = ce.extract_claims(text, limit=30), ce.extract_claims(excerpt, limit=30)
        rows.append({"url": rec["url"], "author": rec.get("author"), "outcome": "ok",
                     "author_matches": str(page_author or "").casefold() == str(rec.get("author") or "").casefold() or "blog.wenxuecity.com" in rec["url"],
                     "chars_full": len(text), "chars_stored": len(excerpt), **summarize(full_c, ex_c),
                     "claims": full_c})
        text = None  # runtime only
    ok = [r for r in rows if r["outcome"] == "ok"]
    agg = {"articles_ok": len(ok), "articles_unavailable": len(rows) - len(ok),
           "claims_full": sum(r["claims_full"] for r in ok), "checkable_full": sum(r["checkable_full"] for r in ok),
           "claims_excerpt": sum(r["claims_excerpt"] for r in ok), "checkable_excerpt": sum(r["checkable_excerpt"] for r in ok),
           "articles_with_checkable_full": sum(1 for r in ok if r["checkable_full"]),
           "articles_with_checkable_excerpt": sum(1 for r in ok if r["checkable_excerpt"]),
           "stance_mix": dict(Counter(c["stance"] for r in ok for c in r["claims"]))}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "aggregate": agg, "rows": rows,
              "policy": "runtime-only full text; report stores structured claims + sentence sha256, never source wording"}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
