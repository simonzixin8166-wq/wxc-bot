#!/usr/bin/env python3
"""S2 step 1 (design v0.2 §9.2/§9.3/§9.5): v4.1 candidate manifest, published sampling plan and deterministic draw.

Research-only; changes nothing in production. Reads state/research_feed.json and every earlier gold / evaluation /
pilot file, and writes research/gold/v4.1/:
  candidate_manifest.json  every October-2026 Wenxuecity post never used before (ids, dates, author, thread, observable
                           features, prior-use check, content and context hashes; titles/excerpts are NOT copied here)
  sampling_plan.json       sizes, strata quotas, minimums, author cap, seed - fixed BEFORE the draw
  selection.json           the drawn dev / test ids (thread-grouped: one thread never spans dev and test)

Eligibility: published 2026-10-01..31; source wenxuecity; the complete text is available today without fetching
(title-only posts, or posts whose whole body is <= 360 chars and therefore fully held in the stored excerpt). Posts
whose body was truncated (mostly long blog articles) cannot be labelled while the site returns 403 and are excluded
and counted, never silently dropped. A post counts as previously used if its id or URL appears in any earlier gold,
evaluation, pilot, diagnosis or context file; a reply also counts if its thread URL appears there (replies share the
thread's URL, so the thread was already seen as text or context).

  python s2_v41_manifest.py            # writes the three files
  python s2_v41_manifest.py --check    # recomputes and fails if the committed files differ (valid while no newer
                                       # gold file exists; afterwards tests/test_s2_v41_manifest.py checks the invariants)
"""
from __future__ import annotations

import glob
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "state" / "research_feed.json"
OUT = ROOT / "research" / "gold" / "v4.1"
PRIOR_FILES = sorted(f for f in glob.glob(str(ROOT / "research" / "gold" / "*")) if Path(f).is_file()) + [str(ROOT / "state" / f) for f in (
    "author_claims_hp.json", "claims_gold_eval.json", "eval_claims_gold_test_v2.json", "eval_claims_gold_test_v3_ce.json",
    "eval_claims_gold_test_v3_hp.json", "eval_claims_gold_v1_ce_dev.json", "eval_claims_gold_v1_hp_dev.json",
    "fulltext_claims_pilot.json", "fulltext_claims_pilot_round2.json", "fulltext_claims_review_round2.json",
    "gold_context_test_v2.json", "gold_context_v1.json", "title_only_diagnosis.json", "title_only_diagnosis_round2.json",
    "title_claims_scan.json")]

PLAN = {
    "version": "v4.1-plan-1",
    "frozen_before_draw": True,
    "seed": 20261105,
    "label_schema": "GUIDELINES_v1.3 (A-E, <= 5 holdings per post), sha256 prefix 7dd420392be709ff",
    "sizes": {"dev": 120, "test_stratified": 200, "test_natural_traffic": 50},
    "split": "whole threads are assigned to dev or test (seeded shuffle of thread ids); a thread never spans both",
    "author_cap_share_of_test": 0.40,
    "minimum_per_category_in_test": {"reply": 60, "root": 60, "has_symbol": 80, "no_symbol": 40, "action_word": 40,
                                     "conditional": 25, "short_full_text": 30, "irony_marker": 10, "holdings_list": 5},
    "categories": {
        "reply": "post is a reply in a thread (parent_post_id set)",
        "root": "thread starter",
        "has_symbol": "the collector found >= 1 ticker",
        "no_symbol": "no ticker found",
        "action_word": "text contains 买|卖|加仓|减仓|清仓|建仓|止盈|止损|抄底|出货|持有|空仓",
        "conditional": "text contains 如果|若|假如|一旦|跌破|站上|突破|除非",
        "short_full_text": "body <= 360 chars fully held in the excerpt (not title-only)",
        "irony_marker": "text contains 哈哈|呵呵|LOL|lol|笑死|😂|反指",
        "holdings_list": ">= 3 tickers in one post",
    },
    "natural_traffic_subset": "50 further test posts drawn uniformly (no quotas, no author cap) from the test-side posts left after the stratified draw; frozen with the test set and always reported separately, so the stratified set's author cap is not diluted",
    "insufficient_rule": "a category with fewer eligible posts than its minimum is reported INSUFFICIENT_N, never padded",
    "labelling": "three-way blind: Claude, GPT, Owner spot-check 20; every disagreement and every high-risk category "
                 "(conditional, irony, holdings list) adjudicated by the Owner; test frozen only at kappa >= 0.70",
}

ACTION = re.compile(r"买|卖|加仓|减仓|清仓|建仓|止盈|止损|抄底|出货|持有|空仓")
COND = re.compile(r"如果|若|假如|一旦|跌破|站上|突破|除非")
IRONY = re.compile(r"哈哈|呵呵|LOL|lol|笑死|😂|反指")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def thread_of(r: dict) -> str:
    if r.get("parent_post_id"):
        return f"cfzh:{r['parent_post_id']}" if "bbs.wenxuecity.com" in (r.get("url") or "") else f"p:{r['parent_post_id']}"
    m = re.search(r"/(\d+)\.html", r.get("url") or "")
    return (f"cfzh:{m.group(1)}" if "bbs.wenxuecity.com" in (r.get("url") or "") else f"blog:{m.group(1)}") if m else f"id:{r['id']}"


def build() -> tuple[dict, dict]:
    recs = json.loads(FEED.read_text(encoding="utf-8"))["records"]
    wx = [r for r in recs if r.get("source") == "wenxuecity"]
    byid, byurl = {r["id"]: r for r in wx}, {r["url"]: r["id"] for r in wx if r.get("url")}
    used, used_urls = defaultdict(set), set()
    for f in PRIOR_FILES:
        try:
            t = Path(f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        name = Path(f).name
        for u in set(re.findall(r"https?://[^\s\"'\\]*wenxuecity[^\s\"'\\]*", t)):
            used_urls.add(u.rstrip("\\,"))
            if u.rstrip("\\,") in byurl:
                used[byurl[u.rstrip("\\,")]].add(name)
        for i in set(re.findall(r"\b[0-9a-f]{20}\b", t)):
            if i in byid:
                used[i].add(name)
    titles_by_thread = defaultdict(list)
    for r in wx:
        titles_by_thread[thread_of(r)].append((r["published_at"], r["id"], r.get("title") or ""))
    excluded, cands = Counter(), []
    for r in sorted(wx, key=lambda x: (x["published_at"], x["id"])):
        if r["published_at"][:7] != "2026-10":
            continue
        if r["id"] in used:
            excluded["previously_used"] += 1
            continue
        if r.get("url") in used_urls:  # replies share their thread's URL: the thread was seen before (context leak)
            excluded["thread_previously_used"] += 1
            continue
        cc = r.get("content_chars") or 0
        if cc > 360:
            excluded["body_truncated_cannot_label_without_fetch"] += 1
            continue
        text = (r.get("title") or "") + "\n" + (r.get("excerpt") or "")
        th = thread_of(r)
        ctx = [t for (p, i, t) in sorted(titles_by_thread[th]) if p < r["published_at"]]  # context visible at posting
        cands.append({
            "id": r["id"], "published_at": r["published_at"], "author": r.get("author"), "source_kind": r.get("source_kind"),
            "thread_id": th, "is_reply": bool(r.get("parent_post_id")), "text_kind": "title_only" if cc == 0 else "short_full_text",
            "n_symbols": len(r.get("symbols") or []), "action_word": bool(ACTION.search(text)), "conditional": bool(COND.search(text)),
            "irony_marker": bool(IRONY.search(text)), "content_sha256": sha(text), "context_sha256": sha("\n".join(ctx)),
            "context_items": len(ctx), "prior_use": [],
        })
    manifest = {
        "version": "v4.1-manifest-1", "october_records_sha256": october_hash(wx),
        "window": "2026-10-01..2026-10-31",
        "prior_use_files_checked": [Path(f).name for f in PRIOR_FILES],
        "october_posts": sum(1 for r in wx if r["published_at"][:7] == "2026-10"),
        "excluded": dict(excluded), "eligible": len(cands),
        "note": "no third-party text is stored here; content and context are pinned by sha256 of title+excerpt as held in the feed",
        "candidates": cands,
    }
    return manifest, draw(cands)


def october_hash(wx: list) -> str:
    """Pins the October Wenxuecity records the manifest was built from (the feed itself keeps growing, append-only)."""
    keep = ("id", "published_at", "author", "url", "title", "excerpt", "content_chars", "parent_post_id", "source_kind")
    octo = sorted(({k: r.get(k) for k in keep} for r in wx if r["published_at"][:7] == "2026-10"), key=lambda r: r["id"])
    # only the fields the sample depends on: later enrichment (claims, method signals) must not break the pin
    return sha(json.dumps(octo, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def cats(c: dict) -> set:
    s = {"reply" if c["is_reply"] else "root", "has_symbol" if c["n_symbols"] else "no_symbol"}
    for k in ("action_word", "conditional", "irony_marker"):
        if c[k]:
            s.add(k)
    if c["text_kind"] == "short_full_text":
        s.add("short_full_text")
    if c["n_symbols"] >= 3:
        s.add("holdings_list")
    return s


def draw(cands: list) -> dict:
    rng = random.Random(PLAN["seed"])
    threads = sorted({c["thread_id"] for c in cands})
    rng.shuffle(threads)
    # assign threads to the test side until it holds ~ 62.5% of posts (test 200 of 320), rest to dev
    by_t = defaultdict(list)
    for c in cands:
        by_t[c["thread_id"]].append(c)
    test_pool, dev_pool, n = [], [], 0
    for t in threads:
        (test_pool if n < 0.625 * len(cands) else dev_pool).extend(by_t[t])
        n += len(by_t[t])

    def strat(pool, size, mins, cap):
        pool = sorted(pool, key=lambda c: c["id"])
        rng.shuffle(pool)
        chosen, per_author = [], Counter()
        for cat, need in sorted(mins.items(), key=lambda kv: sum(cat_ok(c, kv[0]) for c in pool)):  # rarest first
            have = sum(1 for c in chosen if cat in cats(c))
            for c in pool:
                if have >= need or len(chosen) >= size:
                    break
                if c in chosen or cat not in cats(c) or per_author[c["author"]] >= cap * size:
                    continue
                chosen.append(c); per_author[c["author"]] += 1; have += 1
        for c in pool:
            if len(chosen) >= size:
                break
            if c not in chosen and per_author[c["author"]] < cap * size:
                chosen.append(c); per_author[c["author"]] += 1
        return chosen

    def cat_ok(c, cat):
        return cat in cats(c)

    sz = PLAN["sizes"]
    test = strat(test_pool, sz["test_stratified"], PLAN["minimum_per_category_in_test"], PLAN["author_cap_share_of_test"])
    left = sorted((c for c in test_pool if c not in test), key=lambda c: c["id"])
    natural = sorted(rng.sample(left, min(sz["test_natural_traffic"], len(left))), key=lambda c: c["id"])
    dev = strat(dev_pool, sz["dev"], {k: max(1, v * sz["dev"] // sz["test_stratified"]) for k, v in PLAN["minimum_per_category_in_test"].items()},
                PLAN["author_cap_share_of_test"])
    cov = {k: sum(1 for c in test if k in cats(c)) for k in PLAN["minimum_per_category_in_test"]}
    status = {k: ("OK" if cov[k] >= v else "INSUFFICIENT_N") for k, v in PLAN["minimum_per_category_in_test"].items()}
    assert not ({c["thread_id"] for c in test + natural} & {c["thread_id"] for c in dev}), "a thread spans dev and test"
    return {
        "version": "v4.1-selection-1", "plan_version": PLAN["version"], "seed": PLAN["seed"],
        "test_ids": sorted(c["id"] for c in test), "test_natural_traffic_ids": sorted(c["id"] for c in natural),
        "dev_ids": sorted(c["id"] for c in dev),
        "test_category_counts": cov, "test_category_status": status,
        "test_authors": dict(Counter(c["author"] for c in test).most_common()),
        "dev_authors": dict(Counter(c["author"] for c in dev).most_common()),
        "test_threads": len({c["thread_id"] for c in test + natural}), "dev_threads": len({c["thread_id"] for c in dev}),
        "pools": {"test_side_posts": len(test_pool), "dev_side_posts": len(dev_pool)},
    }


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, indent=1) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    manifest, selection = build()
    files = {"candidate_manifest.json": dumps(manifest), "sampling_plan.json": dumps(PLAN), "selection.json": dumps(selection)}
    if "--check" in argv:
        bad = [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != t]
        print(json.dumps({"check": "FAIL" if bad else "PASS", "differs": bad}))
        return 1 if bad else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n, t in files.items():
        (OUT / n).write_text(t, encoding="utf-8")
    print(json.dumps({"eligible": manifest["eligible"], "excluded": manifest["excluded"], "test": len(selection["test_ids"]), "natural": len(selection["test_natural_traffic_ids"]),
                      "dev": len(selection["dev_ids"]), "status": selection["test_category_status"],
                      "counts": selection["test_category_counts"], "test_authors": selection["test_authors"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
