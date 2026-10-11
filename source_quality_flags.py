#!/usr/bin/env python3
"""Machine-readable source quality flags (quant-dashboard#133 6109260776 P0-1). Overlay only: the
feed and raw files are never rewritten.

  invalid_transcript   : stored video "transcript" is a provider navigation page (claim_extractor.provider_boilerplate)
  no_text              : record has neither title text nor excerpt
  provenance           : derived from state/provenance_audit.json (first git appearance vs published_at);
                         near_publication_observed is NOT real-time locking — it only means first seen ≤36 h later
Consumers (claims, shadow knowledge, statistics, action hints) must skip records whose `exclude` is true.
Output: state/source_quality_flags.json
"""
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import claim_extractor as ce

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "state" / "research_feed.json"
AUDIT = ROOT / "state" / "provenance_audit.json"
OUT = ROOT / "state" / "source_quality_flags.json"


def flags_for(r, prov):
    f = []
    if r.get("source_kind") == "video" and ce.provider_boilerplate(r.get("excerpt") or ""):
        f.append("invalid_transcript")
    if not str(r.get("title") or "").strip() and not str(r.get("excerpt") or "").strip():
        f.append("no_text")
    return {"flags": f, "exclude": bool(f), "provenance": (prov or {}).get("derived_provenance", "unaudited"),
            "first_git_seen": (prov or {}).get("first_git_seen"), "published_at_timezone": "unknown"}


def build():
    feed = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    try:
        audit = {x["id"]: x for x in json.loads(AUDIT.read_text(encoding="utf-8"))["rows"]}
    except Exception:
        audit = {}
    out = {r["id"]: flags_for(r, audit.get(r["id"])) for r in feed}
    vids = [r for r in feed if r.get("source_kind") == "video"]
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "records": len(out), "excluded": sum(1 for v in out.values() if v["exclude"]),
            "flag_counts": dict(Counter(f for v in out.values() for f in v["flags"])),
            "video": {"records": len(vids), "invalid_transcript": sum(1 for r in vids if "invalid_transcript" in out[r["id"]]["flags"]),
                      "note": "video count follows the live feed (18 at the 10-11 inventory, 19 after a new video was captured 10-11 12:45Z)"},
            "provenance_counts": dict(Counter(v["provenance"] for v in out.values())),
            "policy": "overlay only; feed/raw files unchanged; near_publication_observed ≠ real-time lock",
            "records_flags": out}


def main():
    rep = build()
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("records", "excluded", "flag_counts", "video", "provenance_counts")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
