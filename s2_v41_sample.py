#!/usr/bin/env python3
"""Claims gold test set v4.1, spec v0.3 (Owner 2026-11-05, option 1; guideline v1.3 §9).

Runs the v4 sampler `build_gold_v4.py` with its logic UNCHANGED; only the window and the seed change, as §9 allows:
  SEED   = "20261105"                      (the sampling date)
  WINDOW = ("2026-10-01", "2026-10-31")    (captured_at; every October-2026 post)
Two input/output steps around the sampler are added and recorded in spec v0.3:
  1. pre-filter (input only): keep Wenxuecity posts published in October 2026 whose id, URL or thread URL never
     appeared in ANY earlier gold, evaluation, pilot, diagnosis or context file (the v4 sampler itself only checks
     URLs in gold *.jsonl files);
  2. thread rule (output only, GPT #133 6594659763 §2): a thread never spans test and dev. When the unchanged sampler
     puts posts of one thread on both sides, the DEV posts of that thread are dropped (test is never changed).
Deviation from §9, written into spec v0.3: §9 asks for posts carrying the collector's `thread_context` (captured after
wxc-bot #77). Wenxuecity has returned 403 since 2026-11-01, so that pool is empty. These October posts have no
`thread_context`; the labelling packs instead show the thread titles that were visible before each post, rebuilt from
the feed (no fetching).

Outputs research/gold/claims_gold_{test,dev}_v4.1.unlabeled.jsonl and research/gold/claims_gold_v4.1_sample.json.
No third-party text beyond what the v4 sampler already writes (text hash, <= 40-char locator).

  python s2_v41_sample.py           # writes
  python s2_v41_sample.py --check   # recomputes and compares byte for byte
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import build_gold_v4 as bg

ROOT = Path(__file__).resolve().parent
GOLD = ROOT / "research" / "gold"
FEED = ROOT / "state" / "research_feed.json"
SEED, WINDOW = "20261105", ("2026-10-01", "2026-10-31")
# Frozen inputs (2026-11-09): the sample commit f304de9 was made 2026-11-05T02:46:11Z.
FROZEN_PRIOR = ROOT / "research" / "gold" / "claims_gold_v4.1_prior_use.json"
CAPTURED_CUTOFF = "2026-11-05T02:46:11Z"
V4_SAMPLER_SHA256 = hashlib.sha256((ROOT / "build_gold_v4.py").read_bytes()).hexdigest()
# Files from later rounds (v5 and up) are not prior use of v4.1 and must not change its frozen summary.
_LATER = re.compile(r"_v(?:[5-9]|\d{2,})(?:[._]|$)")
PRIOR = [f for f in sorted(glob.glob(str(GOLD / "*"))) if Path(f).is_file() and "v4.1" not in Path(f).name
         and not _LATER.search(Path(f).name)] + [
    str(ROOT / "state" / f) for f in (
        "author_claims_hp.json", "claims_gold_eval.json", "eval_claims_gold_test_v2.json", "eval_claims_gold_test_v3_ce.json",
        "eval_claims_gold_test_v3_hp.json", "eval_claims_gold_v1_ce_dev.json", "eval_claims_gold_v1_hp_dev.json",
        "fulltext_claims_pilot.json", "fulltext_claims_pilot_round2.json", "fulltext_claims_review_round2.json",
        "gold_context_test_v2.json", "gold_context_v1.json", "title_only_diagnosis.json", "title_only_diagnosis_round2.json",
        "title_claims_scan.json")]


def thread_of(r: dict) -> str:
    m = re.search(r"/(\d+)\.html", r.get("url") or "")
    return f"{(r.get('source_kind') or '?')}:{r.get('parent_post_id') or (m.group(1) if m else r['id'])}"


def prefilter(feed: list) -> tuple[list, dict]:
    wx = [r for r in feed if r.get("source") == "wenxuecity"]
    byid = {r["id"] for r in wx}
    used_ids, used_urls = set(), set()
    if FROZEN_PRIOR.exists():
        # 2026-11-09: the prior-use set as it was at the sample commit (rolling state files are rewritten daily)
        fz = json.loads(FROZEN_PRIOR.read_text(encoding="utf-8"))
        used_ids, used_urls = set(fz["used_ids"]) & byid, set(fz["used_urls"])
    else:
        for f in PRIOR:
            try:
                t = Path(f).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            used_urls |= {u.rstrip(",") for u in re.findall(r"https?://[^\s\"'\\]*wenxuecity[^\s\"'\\]*", t)}
            used_ids |= {i for i in re.findall(r"\b[0-9a-f]{20}\b", t) if i in byid}
    keep, why = [], Counter()
    for r in wx:
        if r["published_at"][:7] != "2026-10":
            continue
        if str(r.get("captured_at") or "") > CAPTURED_CUTOFF:
            continue  # appended to the feed after the sample was drawn: never part of the v4.1 pool
        if r["id"] in used_ids:
            why["id_previously_used"] += 1
        elif r.get("url") in used_urls:  # replies share the thread URL: the thread was already seen
            why["url_or_thread_previously_used"] += 1
        else:
            keep.append(r)
    why["kept"] = len(keep)
    return keep, dict(why)


def run() -> dict:
    data = json.loads(FEED.read_text(encoding="utf-8"))
    feed = data["records"]
    keep, why = prefilter(feed)
    bg.SEED, bg.WINDOW = SEED, WINDOW  # the only two changes allowed by guideline v1.3 §9
    # the sampler's own gold-URL exclusion, minus this sample's output files (so re-running reproduces it)
    gold = set()
    fz = json.loads(FROZEN_PRIOR.read_text(encoding="utf-8")) if FROZEN_PRIOR.exists() else {}
    if "gold_urls" in fz:
        gold = set(fz["gold_urls"])  # frozen: gold files added later (v5, ...) must not change the v4.1 sample
    else:
        for g in sorted(glob.glob(str(GOLD / "*.jsonl"))):
            if "v4.1" not in Path(g).name:
                gold |= {json.loads(x).get("url") for x in open(g, encoding="utf-8") if x.strip()} - {None}
    posts, test, dev = bg.build(keep, gold, {})
    by_rec = {r["id"]: r for r in keep}
    t_threads = {thread_of(by_rec[i["record_id"]]) for i in test}
    dropped = [i for i in dev if thread_of(by_rec[i["record_id"]]) in t_threads]
    dev = [i for i in dev if thread_of(by_rec[i["record_id"]]) not in t_threads]
    for rows in (test, dev):
        for i in rows:
            i["origin"], i["guideline"] = "v4.1", "v1.3"
            i["thread_id"] = thread_of(by_rec[i["record_id"]])
    summ = bg.summary(posts, test, dev)
    summ.update({"spec": "v0.3", "v4_sampler_sha256": V4_SAMPLER_SHA256, "prefilter": why,
                 "dev_items_dropped_for_thread_rule": len(dropped),
                 "thread_overlap_after_rule": len({i["thread_id"] for i in test} & {i["thread_id"] for i in dev}),
                 "test_threads": len({i["thread_id"] for i in test}), "dev_threads": len({i["thread_id"] for i in dev}),
                 "prior_use_files_checked": [Path(f).name for f in PRIOR]})
    pack, key = textpack({"test": test}, by_rec, [r for r in feed if r.get("source") == "wenxuecity"])
    return {"summary": summ, "test": test, "dev": dev, "pack": pack, "key": key}


GPT_N, OWNER_N = 120, 20  # guideline v1.3 §9: GPT blind-labels 120 test items, the Owner 20 of those 120
INSTRUCTIONS = (
    "Label each item under research/gold/GUIDELINES_v1.3.md (frozen, sha256 prefix 7dd420392be709ff). TARGET = "
    "target_text: kind=title is the post title (a 0-byte reply's title is the whole reply); kind=excerpt is the stored "
    "public excerpt (<= 360 chars) and `title` is context only. CONTEXT = thread_context: the thread's root title and up "
    "to 5 earlier titles in the same thread, rebuilt from the collector's feed (these October posts predate the "
    "collector's own thread_context; spec v0.3). Label only claims the AUTHOR makes in the TARGET; context may only "
    "resolve the ticker (ticker_source=context) or the reply role. Fields: symbol, stance (buy/add/sell/trim/hold/avoid/"
    "bullish/bearish), status (executed/planned/conditional/opinion), instrument (stock/sell_put/covered_call/leaps/other), "
    "holder (author/author_system), ticker_source (text/context). Holdings: only with explicit 'I hold' wording, <= 5 "
    "tickers, longer lists -> note 'holdings_list' and labels []. No claim -> labels [], ambiguous false. Needs the full "
    "article -> note 'needs_article_check', labels []. Replies also get reply_role (agree/disagree/answer/question/social/"
    "none). Never guess, never open other pages. Answer per blind_id: {blind_id, labels:[...], ambiguous, note, reply_role}.")


def textpack(res: dict, keep_by_id: dict, feed_wx: list) -> tuple[dict, dict]:
    test = sorted(res["test"], key=lambda i: bg.seeded("gpt|" + i["item_id"]))
    gpt = sorted(test[:GPT_N], key=lambda i: bg.seeded("order|" + i["item_id"]))
    owner = {i["item_id"] for i in sorted(gpt, key=lambda i: bg.seeded("owner|" + i["item_id"]))[:OWNER_N]}
    by_thread = {}
    for r in feed_wx:
        by_thread.setdefault(thread_of(r), []).append(r)
    items, key = [], []
    for i in gpt:
        r = keep_by_id[i["record_id"]]
        th = sorted(by_thread.get(i["thread_id"], []), key=lambda x: (x["published_at"], x["id"]))
        root = next((x for x in th if not x.get("parent_post_id")), None)
        earlier = [x.get("title") or "" for x in th if (x["published_at"], x["id"]) < (r["published_at"], r["id"])][-5:]
        target = (r.get("title") or "").strip() if i["kind"] == "title" else (r.get("excerpt") or "").strip()
        assert bg.sha(target) == i["text_sha256"], "target text does not match the sampled hash"
        bid = "b41-" + bg.sha("blind|" + i["item_id"])[:12]
        items.append({"blind_id": bid, "kind": i["kind"], "source_kind": i["source_kind"], "author": i["author"],
                      "url": i["url"], "published_at": i["published_at"], "is_reply": bool(r.get("parent_post_id")),
                      "title": r.get("title") if i["kind"] == "excerpt" else None, "target_text": target,
                      "thread_context": {"root_title": (root or {}).get("title") if root and root["id"] != r["id"] else None,
                                         "earlier_titles": earlier}})
        key.append({"blind_id": bid, "item_id": i["item_id"], "owner_subset": i["item_id"] in owner})
    pack = {"version": "blind_test_v4.1_textpack", "spec": "v0.3", "guideline": "v1.3", "instructions": INSTRUCTIONS,
            "note": "titles and <= 360-char public excerpts only (the same text the extractor sees); no labels, no extractor output",
            "items": items}
    return pack, {"version": "blind_test_v4.1_key", "gpt_items": len(key), "owner_items": sum(k["owner_subset"] for k in key), "key": key}


def render(res: dict) -> dict:
    j = lambda rows: "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    return {"claims_gold_test_v4.1.unlabeled.jsonl": j(res["test"]), "claims_gold_dev_v4.1.unlabeled.jsonl": j(res["dev"]),
            "claims_gold_v4.1_sample.json": json.dumps(res["summary"], ensure_ascii=False, indent=1) + "\n",
            "blind_test_v4.1_textpack.json": json.dumps(res["pack"], ensure_ascii=False, indent=1) + "\n",
            "blind_test_v4.1_key.json": json.dumps(res["key"], ensure_ascii=False, indent=1) + "\n"}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    files = render(run())
    if "--check" in argv:
        bad = [n for n, t in files.items() if not (GOLD / n).exists() or (GOLD / n).read_text(encoding="utf-8") != t]
        print(json.dumps({"check": "FAIL" if bad else "PASS", "differs": bad}))
        return 1 if bad else 0
    for n, t in files.items():
        (GOLD / n).write_text(t, encoding="utf-8")
    s = json.loads(files["claims_gold_v4.1_sample.json"])
    print(json.dumps({k: s[k] for k in ("pool_posts", "prefilter", "test", "dev", "dev_items_dropped_for_thread_rule",
                                         "thread_overlap_after_rule", "test_threads", "dev_threads")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
