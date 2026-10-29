# wxc-bot — role in MyAlpha View

wxc-bot is the source-collection and understanding layer of MyAlpha View. The governing product charter
lives in `simonzixin8166-wq/quant-dashboard/CLAUDE.md` (owner-confirmed 2026-10-11) and applies here too.

In short: MyAlpha is a personal AI investment research assistant — it collects, understands, verifies and
learns every day on its own, and the owner places every order manually. For this repo that means:
- Purpose (owner, 2026-10-29): everything collected here is training material for MyAlpha itself — it exists
  to make MyAlpha's understanding, judgments and alerts measurably more intelligent and professional. Collection
  that never feeds understanding, verification and reusable experience has no value (see the charter's
  "Why we collect" and evidence ladder).
- Collect legally and incrementally; record source, published_at, first_seen and provenance; never fake real-time.
- Never persist third-party full text; keep titles, ≤360-char public excerpts, short locators and hashes.
- Flag bad inputs instead of using them (e.g. `state/source_quality_flags.json`: invalid transcripts excluded).
- Author claims are `experimental_unvalidated` until frozen, unseen tests pass the agreed gate; author
  self-reported trades are never "verified".
- Zero new paid APIs; small PRs with CI; report on quant-dashboard Issue #133.
