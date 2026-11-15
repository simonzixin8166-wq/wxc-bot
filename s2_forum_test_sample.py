#!/usr/bin/env python3
"""Forum test set v1 sample (spec research/forum/spec_forum_test_v1.md, Owner 2026-11-15). Unit: one utterance
(a root post or a reply), read with the text it replies to, as in the forum dev gold v1.

Pool: Owner forum exports (state/owner_forum_index.jsonl) published on or after 2026-11-10 and indexed before the
cutoff. Everything the forum dev gold v1 or the 11/11 diagnosis sample has seen is excluded; ce-7 and the Gemini
forum prompt were tuned only on posts published 11/4-11/9, so the whole pool is unseen.
Draw (seed 20261115, deterministic): TEST items, proportional to the (kind, body_status) strata, at most
AUTHOR_CAP of the test from one author. Owner subset: OWNER items from the test set, in seeded order.
Everything else in the pool stays sealed (reserved for a later set; not for tuning).
Output: ids, links, hashes and counts only. No text is written to this public repo.

  python s2_forum_test_sample.py            # writes research/forum/claims_gold_forum_test_v1_sample.json
  python s2_forum_test_sample.py --check    # recomputes and compares byte for byte
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORUM = ROOT / "research" / "forum"
INDEX = ROOT / "state" / "owner_forum_index.jsonl"
DEV = FORUM / "claims_gold_forum_dev_v1.claude_first.jsonl"
SEEN = FORUM / "forum_diag_seen_2026-11-11.json"
OUT = FORUM / "claims_gold_forum_test_v1_sample.json"
SEED = "20261115"
PUBLISHED_FROM = "2026-11-10"
CUTOFF = "2026-11-15T02:00:00Z"          # indexed_at before this; later exports are not in the draw
TEST, OWNER, AUTHOR_CAP = 150, 30, 0.50


def h(s: str) -> str:
    return hashlib.sha256(f"{SEED}|{s}".encode("utf-8")).hexdigest()


def load_pool(index_lines, dev_ids, seen_ids):
    pool = []
    for line in index_lines:
        if not line.strip():
            continue
        r = json.loads(line)
        if r["post_id"] in dev_ids or r["post_id"] in seen_ids:
            continue
        if str(r.get("published_at", ""))[:10] < PUBLISHED_FROM or str(r.get("indexed_at", "")) >= CUTOFF:
            continue
        if r.get("textpack") != "stored":
            continue
        pool.append(r)
    return pool


def draw(pool, n=TEST, cap=AUTHOR_CAP):
    """Largest-remainder quotas per (kind, body_status); seeded order inside each stratum; author cap."""
    strata = Counter((r["kind"], r["body_status"]) for r in pool)
    raw = {k: n * v / len(pool) for k, v in strata.items()}
    quota = {k: int(x) for k, x in raw.items()}
    for k in sorted(raw, key=lambda k: (-(raw[k] - quota[k]), k))[: n - sum(quota.values())]:
        quota[k] += 1
    per_author, picked = Counter(), []
    limit = int(cap * n)
    for k in sorted(quota):
        rows = sorted((r for r in pool if (r["kind"], r["body_status"]) == k), key=lambda r: h(r["post_id"]))
        took = 0
        for r in rows:
            if took == quota[k]:
                break
            if per_author[r["author"]] >= limit:
                continue
            picked.append(r)
            per_author[r["author"]] += 1
            took += 1
    return sorted(picked, key=lambda r: h(r["post_id"])), quota


def build():
    dev_ids = {json.loads(l)["post_id"] for l in DEV.read_text(encoding="utf-8").splitlines() if l.strip()}
    seen_ids = set(json.loads(SEEN.read_text(encoding="utf-8"))["post_ids"])
    pool = load_pool(INDEX.read_text(encoding="utf-8").splitlines(), dev_ids, seen_ids)
    test, quota = draw(pool)
    owner = test[:OWNER]
    item = lambda r: {"post_id": r["post_id"], "kind": r["kind"], "body_status": r["body_status"], "author": r["author"],
                      "published_at": r["published_at"], "url": r["url"], "parent_post_id": r.get("parent_post_id"),
                      "root_post_id": r.get("root_post_id"), "sha256": r.get("sha256"), "textpack_path": r.get("textpack_path")}
    return {
        "version": "forum-test-v1-sample-0.1",
        "spec": "research/forum/spec_forum_test_v1.md",
        "seed": SEED, "published_from": PUBLISHED_FROM, "cutoff": CUTOFF,
        "excluded": {"forum_dev_v1": len(dev_ids), "diag_seen_2026_11_11": len(seen_ids)},
        "pool": len(pool), "pool_strata": {f"{k[0]}/{k[1]}": v for k, v in sorted(Counter((r["kind"], r["body_status"]) for r in pool).items())},
        "test": len(test), "test_quota": {f"{k[0]}/{k[1]}": v for k, v in sorted(quota.items())},
        "test_authors": dict(Counter(r["author"] for r in test).most_common()),
        "owner_subset": [r["post_id"] for r in owner],
        "sealed_rest": len(pool) - len(test),
        "items": [item(r) for r in test],
    }


def main():
    out = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == out
        print("forum test v1 sample:", "PASS" if ok else "FAIL (recomputed sample differs from the committed one)")
        return 0 if ok else 1
    OUT.write_text(out, encoding="utf-8")
    d = json.loads(out)
    print(json.dumps({k: d[k] for k in ("pool", "pool_strata", "test", "test_quota", "test_authors", "sealed_rest")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
