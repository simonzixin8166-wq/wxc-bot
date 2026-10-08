#!/usr/bin/env python3
"""Pre-push guard for the shared research feed (run after `git pull --rebase`, before push).

Fails (non-zero) if the working-tree feed is not valid JSON, has duplicate/missing ids,
shrank relative to origin/main, or disagrees with its manifest while claiming the same
feed_updated_at. A failure aborts the push, so a torn write or a bad textual merge never
reaches main and downstream consumers keep the last good feed.
"""
from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path

import research_feed as rf


def committed_count(ref="origin/main"):
    try:
        raw = subprocess.run(["git", "show", f"{ref}:state/research_feed.json"], capture_output=True, check=True).stdout
        return len(json.loads(raw.decode("utf-8")).get("records") or [])
    except Exception:
        return None


def verify(feed_path: Path, manifest_path: Path, baseline: int | None):
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
    if baseline is not None and len(records) < baseline:
        raise SystemExit(f"FEED_SHRINK: {baseline} -> {len(records)}")
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        if m.get("feed_updated_at") == feed.get("updated_at"):
            if m.get("record_count") != len(records) or m.get("content_sha256") != hashlib.sha256(payload).hexdigest():
                raise SystemExit("FEED_MANIFEST_MISMATCH: same feed_updated_at but different content")
    return {"records": len(records), "bytes": len(payload), "baseline": baseline}


if __name__ == "__main__":
    out = verify(rf.FEED_PATH, rf.FEED_PATH.parent / rf.MANIFEST_NAME, committed_count())
    print("PASS research feed integrity", json.dumps(out))
