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
- Third-party content (Owner 2026-11-09): obtain public content through compliant channels only (official RSS/API,
  public pages per the site's rules at low frequency, transcripts, filings, Owner forwards/saves). Full text may be
  kept long-term ONLY in private repos for personal, non-commercial learning and backtesting, never published; public
  repos and Pages keep titles, ≤360-char excerpts, links and hashes. Never circumvent access controls or paywalls:
  no proxy/IP rotation, UA spoofing, captcha solving, login-cookie scraping, or caches/archives of blocked content.
- Wenxuecity (Owner 2026-11-11): the site refuses MyAlpha, so every request to *.wenxuecity.com is paused until
  2027-05-11 (`wxc_access_policy.py`); the Owner's own forwards and forum exports via the bot continue.
- Flag bad inputs instead of using them (e.g. `state/source_quality_flags.json`: invalid transcripts excluded).
- Author claims are `experimental_unvalidated` until frozen, unseen tests pass the agreed gate; author
  self-reported trades are never "verified".
- Zero new paid APIs; small PRs with CI; report on quant-dashboard Issue #133.
