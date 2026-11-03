# Claims gold — labeling guideline v1.3 (FROZEN · Owner-confirmed 2026-11-03)

Status: FROZEN. Built from Owner decisions on 2026-11-01 (#133 6553068356, 6553167319); the Owner confirmed this text
on 2026-11-03 (draft sha256 prefix 29fcb87173203554, body unchanged apart from this status header). The sha256 of this
file is recorded in research/gold/GUIDELINES_v1.3.sha256 and on #133. Any change makes a new version (v1.4); v1.2 and
every earlier gold file stay unchanged.

Why v1.3: in round 1 of test set v4 (wxc-bot #76, `claims_gold_v4_agreement_round1.json`) Claude and GPT agreed on
16 of the Owner's 20 spot-check items, but each agreed with the Owner on only 9. The gap came from three
definitions, not from labeling errors. The Owner had read the full conversation while the labelers saw one
sentence; reduce and bearish were scored as different directions; and holdings lists were counted ticker by ticker.

## 1. What is labeled (decision A)
- **Target:** one item, which is either a post title or the stored public excerpt (≤ 360 chars) of a post.
- **Context the labeler sees:** the conversation recorded by the collector (`thread_context`, wxc-bot #77):
  - the root post's title;
  - the post this item replies to (its author and title, plus its stored excerpt if it is in the feed);
  - the visible reply tree around the item.

  A 0-byte reply's title is the whole reply.
- **Rule:** label only claims stated **by the author in the target**. Context may be used to decide:
  - which ticker the target refers to (`ticker_source: "context"`);
  - whether the target agrees with, disagrees with or answers the post it replies to (see §5).

  Context may never be used to add a claim that the target does not make.
- **Needs the full article:** if the meaning still depends on text that is neither in the target nor in the
  recorded context, use `needs_article_check` with `labels: []`. This is scored as a **correct abstention**, not
  as an error.

## 2. Fields (unchanged from v1.2)
`symbol, stance, status, instrument, holder, ticker_source` with the v1.2 value sets. Selling puts means bullish
(willing to own), never "sell". `holder: author_system` is for the author's own rule or indicator signals.

## 3. Direction is scored by polarity (decision B)
| Polarity | stances |
|---|---|
| positive | buy, add, bullish, hold |
| negative | sell, trim, bearish, avoid |

- Agreement and precision/recall on direction use **polarity only**.
- The exact stance and status are recorded and reported as diagnostics. For example, "TMF 卖出" (sell TMF) is
  labeled `sell/executed`, scores as negative, and agrees with "TMF 看空" (bearish on TMF).
- Exception: an `executed` sale of a position after a gain, with a stated positive view on the same ticker, is two
  labels: `trim/executed` and `bullish/opinion`. Polarity is then **mixed**, and the item is not used for direction
  agreement.

## 4. Holdings disclosure (decision C)
- A holding counts as a claim (`hold`) only when the author explicitly says that they hold it, for example with
  "我持有", "我的仓位", "第一大持仓" or "还拿着".
- **At most 5 tickers per post.**
- A longer holdings list is recorded once as `note: "holdings_list"` with `labels: []` and is not scored ticker by
  ticker.
- A daily P&L or price list without "I hold" wording is a price report, not a claim.

## 5. Conversation role (new in v1.3; diagnostic only, not scored in round 2)
For an item that is a reply, also record `reply_role` with one of these values:
- `agree`: agrees with the parent post;
- `disagree`: disagrees with the parent post;
- `answer`: answers a question in the parent post;
- `question`: asks a question;
- `social`: "+1", thanks, greetings;
- `none`: none of the above.

This feeds phase 3 (conversation-aware understanding). It is reported separately and does not change the claim
labels.

## 6. Inputs that cannot be used (decision D)
- `note: "unavailable"` with `labels: []` for:
  - a video "transcript" that is a scraped page menu (Scribe);
  - a machine summary marked "Gemini 视频理解 · 未验证";
  - an empty or truncated target;
  - a page that cannot be opened.
- Never infer a view from those.

## 7. No-claim versus unclear (decision E)
- No author claim → `labels: []`, `ambiguous: false`, `note: null`.
- `ambiguous: true` only when the target is genuinely unreadable as a claim or as a non-claim. An ambiguous item
  needs a reason of 60 chars or fewer.

## 8. Unchanged from v1.2
- Not claims:
  - quotes of other people;
  - third-party trades (13F, "他买入");
  - examples;
  - price or index reports;
  - market statistics;
  - news fragments;
  - questions without the author's own view;
  - "开始关注" (watch only);
  - advice addressed to others without the author's own view.
- A claim stated only in a neighbouring sentence → `ambiguous`, not inferred.
- Disagreements are kept with all original labels, and the Owner adjudicates. The frozen test split is never edited.

## 9. Round 2 sampling plan (test set v4.1)
- **Pool:**
  - research_feed forum records with `thread_context` present, captured from the first research-close run after
    wxc-bot #77 (2026-11-01 13:10Z) onward;
  - blog and video posts in the same window;
  - no URL that already appears in any gold file.
- **Timing:** sample once the pool has at least 600 forum posts, which is expected about 5 sessions after #77.
- **Sampler:** `build_gold_v4.py` logic unchanged. Only the window and seed change, recorded in a new spec v0.3 (the
  spec v0.2 hash stays frozen). Seed: the date of the sampling run.
- **Labels:**
  - Claude labels all items.
  - GPT blind-labels 120 items from the textpack, now with the same context fields.
  - The Owner blind-labels 20 of those 120, also from the textpack with context, so that all three read the same
    text.
- **Gate:** unchanged from spec v0.2 §3.4 (κ ≥ 0.60, polarity agreement ≥ 0.85, Owner disagreements ≤ 3 of 20).
  Report item-level and post-level separately, with channel splits and Wilson intervals.
- **Rule:** no re-labeling of round 1 under v1.3, and no tuning on round 2 after seeing its scores.
