#!/usr/bin/env python3
"""Daily author-claim export for MyAlpha's automatic research job (quant-dashboard#133 6109291884).

Runs ce-5 high-precision shadow extraction over the stored public text (title + ≤360-char excerpt) of
records first seen in the last LOOKBACK days, skipping records flagged in state/source_quality_flags.json.
Every claim keeps record id, author, url, published_at, first_seen, derived provenance, sentence sha256 and a
≤40-char locator. Claims are experimental_unvalidated: shadow research input only, never production.
Output: state/author_claims_hp.json
"""
from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import claim_extractor as ce

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "state" / "research_feed.json"
FLAGS = ROOT / "state" / "source_quality_flags.json"
OUT = ROOT / "state" / "author_claims_hp.json"
LOOKBACK = int(os.getenv("CLAIMS_LOOKBACK_DAYS", "21"))


def first_seen(r, flag):
    return (flag or {}).get("first_git_seen") or r.get("captured_at")


def build(now=None):
    now = now or datetime.now(timezone.utc)
    feed = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    flags = json.loads(FLAGS.read_text(encoding="utf-8"))["records_flags"] if FLAGS.exists() else {}
    cutoff = now - timedelta(days=LOOKBACK)
    claims, scanned, skipped = [], 0, 0
    for r in feed:
        fl = flags.get(r["id"]) or {}
        fs = first_seen(r, fl) or r.get("captured_at")
        try:
            fsd = datetime.fromisoformat(str(fs).replace("Z", "+00:00"))
        except Exception:
            continue
        try:
            pub = datetime.fromisoformat(str(r.get("published_at") or "").replace(" ", "T")).replace(tzinfo=timezone.utc)
        except Exception:
            pub = None
        if fsd < cutoff or pub is None or pub < cutoff:
            continue  # only recently published AND recently seen: no backfill enters the daily research input
        if fl.get("exclude"):
            skipped += 1
            continue
        scanned += 1
        seen = set()
        for c in ce.extract_claims_hp(f"{r.get('title') or ''}\n{r.get('excerpt') or ''}"):
            key = (c["symbol"], c["stance"], c["evidence_sha256"])
            if key in seen:
                continue
            seen.add(key)
            claims.append({"record_id": r["id"], "author": r.get("author"), "source_kind": r.get("source_kind"), "url": r.get("url"),
                           "published_at": r.get("published_at"), "first_seen": fs, "provenance": fl.get("provenance", "unaudited"),
                           "symbol": c["symbol"], "stance": c["stance"], "status": c["status"], "hp_gate": c["hp_gate"],
                           "instrument": "sell_put" if c["hp_gate"] == "sell_put_willing_to_own" else "stock",
                           "price": c.get("price"), "sentence_sha256": c["evidence_sha256"]})
    return {"generated_at": now.isoformat(timespec="seconds"), "extractor": ce.HP_VERSION, "lookback_days": LOOKBACK,
            "records_scanned": scanned, "records_excluded_by_flags": skipped, "claims": claims,
            "claims_status": "experimental_unvalidated",
            "policy": "shadow research input only; author statements are not verified trades; no source text stored"}


def main():
    rep = build()
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("extractor", "records_scanned", "records_excluded_by_flags")} | {"claims": len(rep["claims"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
