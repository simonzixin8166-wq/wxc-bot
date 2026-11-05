# Claims gold test set v4.1 · sampling spec v0.3 (Owner 2026-11-05, option 1)

Status: FROZEN at the commit that adds it. Guideline v1.3 (sha256 prefix 7dd420392be709ff) is unchanged; spec v0.2
stays frozen. Learning status UNPROVEN / FINAL=NO.

## What changes versus guideline v1.3 §9
- **Sampler:** `build_gold_v4.py`, logic unchanged (its sha256 is recorded in `claims_gold_v4.1_sample.json`).
  Only the two values §9 allows to change are set:
  - `SEED = "20261105"` (the sampling date);
  - `WINDOW = ("2026-10-01", "2026-10-31")` (captured_at).
- **Pool deviation (Owner-approved):** §9 asks for forum posts that carry the collector's `thread_context` (captured
  after wxc-bot #77). Wenxuecity has returned 403 since 2026-11-01, so that pool is empty. The pool is October-2026
  Wenxuecity posts instead.
- **Pre-filter (input only):** a post is dropped if its id, URL or thread URL appears in any earlier gold, evaluation,
  pilot, diagnosis or context file (list in `claims_gold_v4.1_sample.json`). Replies share the thread URL, so a
  thread seen before is dropped whole. Result: 1,733 October posts → 517 id-used, 81 thread-used → 1,135 kept.
- **Thread rule (output only, GPT #133 6594659763 §2):** a thread never spans test and dev. If the unchanged sampler
  put one thread on both sides, the dev posts of that thread would be dropped. On this run nothing had to be dropped.

## Result (`claims_gold_v4.1_sample.json`)
- Test: 276 items (221 title, 55 excerpt) from 221 posts and 221 threads. Authors: 三心三意 88, bogbog 87,
  我是一只井底蛙 62, 麻你 35, BrightLine 2, yifan99 2. Max author share 0.319.
- The sampler's target of 360 test items is not reached: its 25% author cap (90 items) binds and October has only a few
  tracked authors. The sampler's own rule is kept; nothing is topped up.
- Dev: 150 items (121 posts, 120 threads; bogbog 113, 三心三意 37). Dev is for prompt work only and is never scored.
- Test and dev share no post and no thread.

## Labelling (§9, unchanged)
- Claude labels every test and dev item, blind to extractor output.
- GPT blind-labels 120 test items from `blind_test_v4.1_textpack.json`; the Owner blind-labels 20 of those 120
  (`blind_test_v4.1_key.json`, `owner_subset`), from the same textpack.
- Gate (spec v0.2 §3.4): κ ≥ 0.60, polarity agreement ≥ 0.85, Owner disagreements ≤ 3 of 20. Item-level and post-level
  are reported separately, with channel splits and Wilson intervals. No tuning on the test set after seeing scores.

## Known limit: context
The textpack's `thread_context` is rebuilt from the feed: the thread root's title and up to 5 earlier titles in the
same thread. The feed only holds posts by tracked authors, so for this sample it is empty for all 71 replies among the
GPT 120 items. Labellers therefore see what round 1 saw for replies. Guideline v1.3 §1 covers this: a reply whose
meaning depends on text that is not there gets `needs_article_check`, which is scored as a correct abstention, not as
an error. The share of such abstentions is reported, and §9's thread_context pool is sampled as v4.2 once Wenxuecity
is reachable again.
