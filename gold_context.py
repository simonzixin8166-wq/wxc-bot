#!/usr/bin/env python3
"""Runtime context export for the claims gold corpus v1 (quant-dashboard#133 6106896435).

Picks public forum/blog articles stratified by author (excluding the round-2 pilot URLs), fetches each
page slowly, and writes ONLY sentence locators: index, ≤40-char window around the symbol / stance cue,
sentence sha256, detected symbols and whether a stance cue is present. No article text is stored
(decision C: runtime use, structured fields, short locators). The labeler reads the public page itself.
Stops on 403/429 or 5 consecutive failures; never retries around access limits.
"""
from __future__ import annotations
import argparse, hashlib, json, random, re, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import claim_extractor as ce  # noqa: E402
from pilot_fulltext_claims import fetch_text  # noqa: E402

FEED = ROOT / "state" / "research_feed.json"
OUT = ROOT / "state" / "gold_context_v1.json"
EXCLUDE = ROOT / "state" / "fulltext_claims_pilot_round2.json"
QUOTA = {"bogbog": 8, "麻你": 8, "yifan99": 6, "我是一只井底蛙": 5, "BrightLine": 5, "三心三意": 4}
STANCE_ANY = "|".join(p for _, p in ce.STANCE_CUES)


def pick(records, exclude, quota=QUOTA, seed=1011):
    rnd = random.Random(seed)
    by = defaultdict(list)
    for r in records:
        if (r.get("source_kind") in ("forum", "blog") and r.get("url") and r["url"] not in exclude
                and int(r.get("content_chars") or 0) > 120):
            by[r.get("author")].append(r)
    out = []
    for a, n in quota.items():
        pool = sorted(by.get(a, []), key=lambda r: r["url"])
        out += rnd.sample(pool, min(n, len(pool)))
    return out


def locators(text, cap=25, width=40):
    out = []
    for i, s in enumerate(ce.sentences(text)):
        syms = ce.symbols_in(s)
        stance = bool(re.search(STANCE_ANY, s.lower(), re.I))
        if not syms and not stance:
            continue
        keys = [k for k, v in ce.ALIASES.items() if v in syms and k in s] + syms
        pos = min((s.find(k) for k in keys if s.find(k) >= 0), default=0)
        start = max(0, min(pos - width // 2, len(s) - width))
        out.append({"i": i, "locator": s[start:start + width], "sha256": hashlib.sha256(s.encode("utf-8")).hexdigest(),
                    "symbols": syms, "stance_cue": stance, "chars": len(s)})
    sym_first = [x for x in out if x["symbols"]] + [x for x in out if not x["symbols"]]
    return sym_first[:cap], len(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=36)
    a = ap.parse_args(argv)
    records = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    exclude = set()
    try:
        exclude = {r["url"] for r in json.loads(EXCLUDE.read_text(encoding="utf-8"))["rows"]}
    except Exception:
        pass
    rows, fails = [], 0
    for rec in pick(records, exclude)[: a.limit]:
        if fails >= 5:
            break
        time.sleep(random.uniform(2.0, 4.5))
        status, page_author, text = fetch_text(rec)
        if status in (403, 429):
            rows.append({"url": rec["url"], "author": rec.get("author"), "outcome": "unavailable", "http": status})
            break
        if text is None:
            fails += 1
            rows.append({"url": rec["url"], "author": rec.get("author"), "outcome": "unavailable", "http": status})
            continue
        fails = 0
        locs, total = locators(text)
        rows.append({"url": rec["url"], "item_id": rec.get("id"), "author": rec.get("author"), "source_kind": rec.get("source_kind"),
                     "published_at": rec.get("published_at"), "outcome": "ok", "chars": len(text),
                     "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                     "sentences": locs, "candidate_sentences_total": total})
        text = None
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(), "articles": rows,
           "policy": "runtime-only text; stores ≤40-char locators + sentence sha256 only"}
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ok = [r for r in rows if r["outcome"] == "ok"]
    print(json.dumps({"articles_ok": len(ok), "unavailable": len(rows) - len(ok),
                      "sentences": sum(len(r["sentences"]) for r in ok)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
