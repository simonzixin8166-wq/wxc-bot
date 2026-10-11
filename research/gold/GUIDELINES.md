# Claims gold — labeling guideline v1.1 (2026-10-11)

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
