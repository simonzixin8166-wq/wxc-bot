#!/usr/bin/env python3
"""Pre-push guard for the shared research feed (run after `git pull --rebase`, before push).

Fails (non-zero) if the working-tree feed is not valid JSON, has duplicate/missing ids,
shrank relative to origin/main, or disagrees with its manifest while claiming the same
feed_updated_at. A failure aborts the push, so a torn write or a bad textual merge never
reaches main and downstream consumers keep the last good feed.
"""
from __future__ import annotations
import hashlib, json, os, subprocess, sys
from pathlib import Path

import research_feed as rf


def committed_records(ref="origin/main"):
    try:
        raw = subprocess.run(["git", "show", f"{ref}:state/research_feed.json"], capture_output=True, check=True).stdout
        return json.loads(raw.decode("utf-8")).get("records") or []
    except Exception:
        return None


def committed_count(ref="origin/main"):
    rows = committed_records(ref)
    return None if rows is None else len(rows)


def verify(feed_path: Path, manifest_path: Path, baseline, legacy_ok: bool = False):
    """baseline: previous records list (strict append-only) or an int count (legacy callers)."""
    payload = feed_path.read_bytes()
    feed = json.loads(payload.decode("utf-8"))
    records = feed.get("records")
    if not isinstance(records, list):
        raise SystemExit("FEED_INVALID: records is not a list")
    ids = [r.get("id") for r in records]
    if any(not i for i in ids):
        raise SystemExit("FEED_INVALID: record without id")
    if len(set(ids)) != len(ids):
        raise SystemExit(f"FEED_INVALID: duplicate ids ({len(ids) - len(set(ids))})")
    base_rows = baseline if isinstance(baseline, list) else None
    base_n = len(base_rows) if base_rows is not None else baseline
    if base_n is not None and len(records) < base_n:
        raise SystemExit(f"FEED_SHRINK: {base_n} -> {len(records)}")
    if base_rows is not None:
        lost, changed = rf.immutable_violations(base_rows, records)
        if lost:
            raise SystemExit(f"FEED_LOST_IDS: {len(lost)} e.g. {lost[:3]}")
        if changed:
            raise SystemExit(f"FEED_PROVENANCE_REWRITE: {len(changed)} e.g. {changed[:3]}")
    # Strict manifest: every writer goes through rf._write, which writes feed + manifest together,
    # so the manifest must describe exactly this feed. legacy_ok only for pre-manifest history.
    status = "absent"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        same_ts = m.get("feed_updated_at") == feed.get("updated_at")
        ok = same_ts and m.get("record_count") == len(records) and m.get("content_sha256") == hashlib.sha256(payload).hexdigest()
        if same_ts and not ok:
            raise SystemExit("FEED_MANIFEST_MISMATCH: same feed_updated_at but different content")
        status = "verified" if ok else "stale"
    if status != "verified" and not legacy_ok:
        raise SystemExit(f"FEED_MANIFEST_{status.upper()}: feed was not written through research_feed._write")
    return {"records": len(records), "bytes": len(payload), "baseline": base_n, "manifest": status}


if __name__ == "__main__":
    out = verify(rf.FEED_PATH, rf.FEED_PATH.parent / rf.MANIFEST_NAME, committed_records(),
                 legacy_ok=os.getenv("FEED_VERIFY_LEGACY") == "1")
    print("PASS research feed integrity", json.dumps(out))
