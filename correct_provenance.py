#!/usr/bin/env python3
"""Explicit, audited provenance downgrade for records wrongly admitted as live candidates.

Only ever makes provenance MORE conservative (live_candidate → backfill, forward_evidence_eligible →
False). Each change is declared in record.revision (fields, prior values, reason, timestamp) so the
append-only guards accept it as an explicit revision instead of a silent rewrite.
Rule: a record whose source was published more than LATE_DAYS before it was captured cannot be a
point-in-time live observation.
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone

import research_feed as rf

LATE_DAYS = 3


def _d(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")[:19])
    except Exception:
        try:
            return datetime.fromisoformat(str(v)[:10])
        except Exception:
            return None


def late_discovered(rec, late_days=LATE_DAYS):
    p, c = _d(rec.get("published_at")), _d(rec.get("captured_at"))
    return bool(p and c and (c.replace(tzinfo=None) - p.replace(tzinfo=None)).days > late_days)


def downgrade(records, author, reason, now=None):
    now = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    changed = []
    for r in records:
        if r.get("author") != author or r.get("intake_class_hint") != "live_candidate" or not late_discovered(r):
            continue
        prior = {k: r.get(k) for k in ("intake_class_hint", "capture_mode", "forward_evidence_eligible")}
        r["intake_class_hint"] = "backfill"
        r["capture_mode"] = "late_discovery_backfill"
        r["forward_evidence_eligible"] = False
        r["revision"] = {"fields": ["intake_class_hint", "capture_mode"], "prior": prior, "reason": reason, "at": now,
                         "direction": "downgrade_only"}
        changed.append(r.get("id"))
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", required=True)
    ap.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    feed = rf._read(rf.FEED_PATH, {"records": []})
    ids = downgrade(feed.get("records") or [], a.author, a.reason)
    if ids:
        feed["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        rf._write(rf.FEED_PATH, feed)
    print(json.dumps({"downgraded": len(ids), "ids": ids}, ensure_ascii=False))


if __name__ == "__main__":
    main()
