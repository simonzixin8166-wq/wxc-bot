#!/usr/bin/env python3
"""Offline: how many title-only forum records carry an extractable, checkable view in the title itself
(#133 P1-4). Uses only the titles already stored in the public feed; no network, no new text stored.
Output keeps record ids + structured claims, never re-publishing the titles."""
from __future__ import annotations
import json, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import claim_extractor as ce  # noqa: E402
from diagnose_title_only import title_only  # noqa: E402

FEED = ROOT / "state" / "research_feed.json"
OUT = ROOT / "state" / "title_claims_scan.json"


def scan(records):
    per = defaultdict(Counter)
    claims = []
    for r in records:
        if not title_only(r):
            continue
        a = r.get("author") or "?"
        c = ce.extract_claims(r.get("title") or "", limit=5)
        syms = ce.symbols_in(r.get("title") or "")
        per[a]["title_only"] += 1
        per[a]["mentions_symbol"] += bool(syms)
        per[a]["with_claim"] += bool(c)
        per[a]["with_checkable_claim"] += any(ce.checkable(x) for x in c)
        per[a]["question_only"] += bool(c) and all(x["question"] for x in c)
        if c:
            claims.append({"id": r.get("id"), "author": a, "published_at": r.get("published_at"),
                           "claims": [{k: x[k] for k in ("symbol", "stance", "question", "conditional", "horizon")} for x in c]})
    tot = Counter()
    for v in per.values():
        tot.update(v)
    return {k: dict(v) for k, v in per.items()}, dict(tot), claims


def main():
    records = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    per, tot, claims = scan(records)
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(), "extractor_version": ce.EXTRACTOR_VERSION,
           "totals": tot, "by_author": per, "claims": claims,
           "policy": "offline over stored titles; ids + structured claims only"}
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"totals": tot, "by_author": per}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
