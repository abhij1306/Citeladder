# W6 Change + Final evaluation — 2026-08-15

This artifact is sanitized. It contains counts and deterministic fixture
outcomes only; no customer URL, credential, response body, or provider payload.

## C01 live read-only validation spike

A read-only transaction inspected the configured development PostgreSQL
database before reset. It contained zero usable terminal crawls across zero
projects, therefore zero adjacent pairs and no richer live pair to classify.
The analyzer correctly abstained rather than manufacturing a baseline. This is
the coded `unavailable` boundary; positive behavior is proven by deterministic
fixtures as required when the live sample does not naturally contain a pair.

## C01 deterministic fixture pair

- A persisted two-page comparable recrawl pair produced zero observations and
  zero false regressions when all eight locked fields were unchanged.
- The same build was idempotent and froze four exact analysis IDs plus four
  artifact IDs across A and B.
- Positive fixtures classify a critical rule pass→fail and HTTP 200→503 as
  `critical-regression`, link an exact expected title value to its immutable
  implementation event, and suppress URL added/removed observations for a
  partial pair.
- Exact-pair API fixtures prove summary, cursor traversal, detail evidence,
  one-sided pair rejection, and workspace isolation.

## C02 persisted/UI proof

- Opportunity fixtures admit only unexpected `potential-regression` and
  `critical-regression` observations from the exact current change snapshot.
  Expected regressions and neutral changes produce no hit; snapshot and
  observation IDs remain in source provenance.
- Website Changes component fixtures prove available, partial, and
  non-comparable states, exact before/after disclosure, and crawl-bounded page
  links. The named Playwright proof covers the summary and detail disclosure.

## Z01 clean-stack evidence

- `migrations/versions/0001_initial.py` is the only migration revision. A
  newly created PostgreSQL volume upgraded from empty and the Compose-target
  `alembic check` returned `No new upgrade operations detected` (with only the
  repository's documented cyclic-FK ordering warning).
- Every application image was rebuilt with `docker compose build --no-cache`;
  the complete Compose service set was then recreated with
  `--force-recreate`. No image or volume blanket-prune command was used. The
  disposable PostgreSQL volume alone was explicitly removed between clean
  seed attempts.
- The first clean seed attempt after adding confirmed BrandProfile evidence
  correctly failed the existing prompt topical-binding guard. The fixture was
  corrected by adding its missing `Waterproof backpack` product phrase; no
  admission rule was weakened. A fresh empty volume then migrated and seeded
  successfully exactly once.
- Clean persisted readback: 2 projects, 2 successful on-demand integration
  syncs (GSC and GA4), 11 immutable integration metric rows, 1 Demand
  snapshot, 3 completed Site Health crawls, 2 available comparable-change
  snapshots, 0 change observations, 3 completed audits, and 14 Opportunity
  rows.
- Authenticated real-API reads returned HTTP 200 for Command Center, Link
  Graph, AEO Readiness, Changes summary/list, Opportunities, and Integrations.
  The current Changes response was `available`, selected a complete pair, and
  reported zero observations and zero limitations: the clean comparable no-op
  pair therefore produced no false regression.
- The production frontend build emitted `/site` and the crawl-bounded page
  route, with none of the retired browser routes. The named Playwright
  `Website Changes browser proof: summary and exact before-after evidence`
  passed.
- Final replacement searches found no retired WS7 App Router route family,
  caller, `BrandKnowledgeScreen`, `VisibilityOverview`, or `OverviewSummary`.
  The surviving `site-health`, provider, prompt, knowledge, and agent symbols
  are the explicitly retained backend/API/module owners, not browser
  compatibility routes.
