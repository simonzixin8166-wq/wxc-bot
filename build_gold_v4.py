#!/usr/bin/env python3
"""Sample the claims gold v4 dev/test items (spec: quant-dashboard#133 6512756252, Owner-approved 2026-10-30).

Pool   : research_feed records captured 2026-10-12 .. 2026-10-31 (UTC), never in an earlier gold file,
         canonical rows only when a duplicate map is given.
Unit   : the post. A post's title item and stored-excerpt item always go to the same split.
Strata : every blog and video post goes to test; forum posts by author, round-robin over ISO weeks in a
         seeded hash order; no author above 25% of the test items. Dev takes the next forum posts, same caps.
Output : item skeletons without labels (labels are added by the labeler, blind to extractor output).
         Only the public title text hash, a <=40-char locator and the excerpt hash are written - never full text.
Deterministic: same feed + same seed -> same sample.
"""
from __future__ import annotations
import argparse, glob, hashlib, json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED = "20261030"
WINDOW = ("2026-10-12", "2026-10-31")
TEST_ITEMS, DEV_ITEMS, AUTHOR_CAP = 360, 150, 0.25


def sha(t):
    return hashlib.sha256((t or "").encode("utf-8")).hexdigest()


def seeded(key):
    return hashlib.sha256(f"{SEED}|{key}".encode()).hexdigest()


def gold_urls(gold_dir):
    urls = set()
    for g in glob.glob(str(gold_dir / "*.jsonl")):
        for line in open(g, encoding="utf-8"):
            if line.strip():
                u = json.loads(line).get("url")
                if u:
                    urls.add(u)
    return urls


def items_of(r):
    out = []
    title, excerpt = (r.get("title") or "").strip(), (r.get("excerpt") or "").strip()
    base = {"author": r.get("author"), "source_kind": r.get("source_kind"), "url": r.get("url"),
            "record_id": r.get("id"), "published_at": r.get("published_at"), "captured_at": r.get("captured_at"),
            "labels": None, "ambiguous": None, "labeler": None, "guideline": "v1.2", "origin": "v4"}
    if title:
        out.append({**base, "item_id": "t4-" + sha("title|" + r["id"])[:16], "kind": "title",
                    "context": "full_title", "text_sha256": sha(title)})
    if excerpt and excerpt != title:
        out.append({**base, "item_id": "t4-" + sha("excerpt|" + r["id"])[:16], "kind": "excerpt",
                    "context": "stored_excerpt", "text_sha256": sha(excerpt), "locator": excerpt[:40]})
    return out


def pool(feed, used_urls, dup_of):
    posts = []
    for r in feed:
        cap = (r.get("captured_at") or "")[:10]
        if not (WINDOW[0] <= cap <= WINDOW[1]) or r.get("url") in used_urls or dup_of.get(r.get("id")):
            continue
        its = items_of(r)
        if its:
            posts.append({"id": r["id"], "author": r.get("author") or "?", "kind": r.get("source_kind"),
                          "week": date.fromisoformat(cap).isocalendar()[1], "items": its})
    return posts


def round_robin(posts):
    by_week = defaultdict(list)
    for p in sorted(posts, key=lambda p: seeded(p["id"])):
        by_week[p["week"]].append(p)
    weeks, out = sorted(by_week), []
    while any(by_week[w] for w in weeks):
        for w in weeks:
            if by_week[w]:
                out.append(by_week[w].pop(0))
    return out


def fill(queues, target, taken):
    """Take whole posts author by author (round-robin over authors) until target items, cap per author."""
    chosen, n, per = [], 0, Counter()
    cap = int(AUTHOR_CAP * target)
    authors = sorted(queues, key=seeded)
    progress = True
    while n < target and progress:
        progress = False
        for a in authors:
            q = queues[a]
            while q and q[0]["id"] in taken:
                q.pop(0)
            if not q or n >= target:
                continue
            p = q[0]
            if per[a] + len(p["items"]) > cap:
                continue
            q.pop(0); taken.add(p["id"]); chosen.append(p)
            per[a] += len(p["items"]); n += len(p["items"]); progress = True
    return chosen, per


def build(feed, used_urls, dup_of):
    posts = pool(feed, used_urls, dup_of)
    fixed = [p for p in posts if p["kind"] in ("blog", "video")]
    forum = [p for p in posts if p["kind"] not in ("blog", "video")]
    queues = defaultdict(list)
    for p in round_robin(forum):
        queues[p["author"]].append(p)
    taken = {p["id"] for p in fixed}
    fixed_items = sum(len(p["items"]) for p in fixed)
    test_forum, _ = fill(queues, TEST_ITEMS - fixed_items, taken)
    test = fixed + test_forum
    dev, _ = fill(queues, DEV_ITEMS, taken)
    # dev is for tuning, not for scoring: when the cap stalls it (small authors used up by test),
    # top up from the remaining forum posts in the same seeded order without the cap.
    n = sum(len(p["items"]) for p in dev)
    for p in (p for q in sorted(queues, key=seeded) for p in queues[q]):
        if n >= DEV_ITEMS:
            break
        if p["id"] not in taken:
            taken.add(p["id"]); dev.append(p); n += len(p["items"])
    split = lambda ps, s: [{**it, "split": s} for p in ps for it in p["items"]]
    return posts, split(test, "test"), split(dev, "dev")


def summary(posts, test, dev):
    def st(items):
        n = len(items)
        per = Counter(i["author"] for i in items)
        return {"items": n, "posts": len({i["record_id"] for i in items}),
                "by_kind": dict(Counter(i["source_kind"] for i in items)),
                "by_author": dict(per.most_common()), "max_author_share": round(max(per.values()) / n, 3) if n else None}
    overlap = {i["record_id"] for i in test} & {i["record_id"] for i in dev}
    return {"seed": SEED, "window": WINDOW, "pool_posts": len(posts),
            "pool_by_kind": dict(Counter(p["kind"] for p in posts)),
            "pool_by_author": dict(Counter(p["author"] for p in posts).most_common()),
            "test": st(test), "dev": st(dev), "post_overlap": len(overlap)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(ROOT / "state" / "research_feed.json"))
    ap.add_argument("--dup-map", default=None, help="quant-dashboard docs/research/source_duplicate_map.json")
    ap.add_argument("--out-dir", default=None, help="write claims_gold_{test,dev}_v4.unlabeled.jsonl here")
    a = ap.parse_args(argv)
    data = json.load(open(a.feed, encoding="utf-8"))
    feed = data["records"] if isinstance(data, dict) else data
    dup_of = {}
    if a.dup_map:
        m = json.load(open(a.dup_map, encoding="utf-8")).get("mapping", {})
        dup_of = {k: v.get("duplicate_of") for k, v in m.items() if v.get("duplicate_of")}
    posts, test, dev = build(feed, gold_urls(ROOT / "research" / "gold"), dup_of)
    print(json.dumps(summary(posts, test, dev), ensure_ascii=False, indent=1))
    if a.out_dir:
        out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
        for name, rows in (("test", test), ("dev", dev)):
            with open(out / f"claims_gold_{name}_v4.unlabeled.jsonl", "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
