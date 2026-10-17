# Claims gold — labeling guideline v1.2 (2026-10-17; v1.1 2026-10-11)

Label only the **author's own** position/view per ticker in the target text (title, or the sentence that
contains the locator; the article is context only).

- stance: buy / add / sell / trim / hold / avoid / bullish / bearish. Scored on the coarse direction
  (long = buy+add, reduce = sell+trim, hold, bullish, bearish, avoid).
- status: executed / planned / conditional / opinion. **Not scored for `hold`** (blind-v1 showed hold is
  labeled opinion/planned/executed interchangeably).
- instrument: stock / sell_put / covered_call / leaps / other. Selling puts = willing to own (bullish),
  never a plain "sell".
- Position disclosure ("俺的VGT涨了33%", "苹果是我的最大仓") = hold.
- Not claims: quotes of other people, third-party trades (13F, "他买入"), examples, price/technical
  reports, "开始关注" (watch only), advice addressed to someone else without the author's own view.
- A claim stated in a neighbouring sentence → the target sentence is **ambiguous** (excluded), not inferred.
- Cannot open / cannot find → unavailable. Genuinely unclear → ambiguous. Never guess.
- Disagreements are resolved in `*_adjudication.jsonl` (append-only, with reason); dev only; the frozen
  test split is never edited.

## v1.2 changes (owner decision 2026-10-17, #133; evidence: research/gold/blind_owner_2026-10-17.json)

The first independent human blind test (owner, 69 frozen-test items) agreed with the v1.1 gold on stance
direction but not on what counts as a claim (κ 0.126; 45/46 disagreements claim-vs-none). Owner decided:

- **Context-resolved ticker counts.** When the target sentence states the author's own action/view but the
  ticker is named elsewhere in the same post (e.g. "这次也加仓了，17号那天64ish买入" in a post about RKLB),
  label it with `ticker_source: "context"`. Only when the ticker is unambiguous in the same post; if it
  cannot be verified from the post, the item is `needs_article_check`, never guessed.
- **Author system signals count, separately.** A signal produced by the author's own rule/indicator system
  ("TCDS 提示趋势转强", "确认周线买入信号", "假突破，回到偏弱区间") is labeled with `holder: "author_system"`
  and reported apart from the author's discretionary view.
- **Still not claims:** price or index-level reports ("特斯拉，上涨 3.27%"), market statistics (breadth),
  quotes/questions of other people, examples ("AAPL是我实际交易中的一个例子"), news fragments, and
  introductory sentences whose content is in the next sentence (→ ambiguous).
- The frozen v1.1 test files stay unedited. v1.2 decisions for the 69 blind items are an append-only
  adjudication (`claims_gold_test_v2v3_owner_v1.2_adjudication.jsonl`) made after seeing the owner's labels,
  so they are never used to compute inter-annotator agreement; agreement under v1.2 needs a fresh blind sample.
