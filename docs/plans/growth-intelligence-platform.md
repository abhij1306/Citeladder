# Growth Intelligence delivery plan

> **Status:** active cross-system sequence. Runtime details remain in each
> subsystem authority.

The approved six-wave AEO rebuild supersedes this document for delivery order;
see [`citeladder-aeo-product-rebuild.md`](citeladder-aeo-product-rebuild.md).

## Goal

Give a business one governed loop for website health, content improvement,
demand evidence, and bounded growth orchestration:

```text
acquire evidence
  -> classify and analyze the owned site
  -> identify page-type-correct issues and demand gaps
  -> prioritize an opportunity
  -> create or improve content with explicit grounding
  -> measure later evidence
  -> choose the next action
```

## Current systems

- **Site Health** — crawler, structural page kinds, schema contracts, rules,
  scores, issues, snapshots, and opportunities.
- **Content Intelligence** — strategy, briefs, generation, validation,
  revision, save, publication claims, and verification.
- **Demand Intelligence** — GSC/GA4, journeys, prompts, schedules, and AI
  Visibility.
- **Growth Agent** — bounded typed-tool orchestration over those persisted
  owners.

The former Site Intelligence workspace, industry-pack runtime, knowledge
kernel, corrections, and snapshot-comparison system were removed in the
2026-08 simplification. Historical plans are archived under
[`../archive/plans/site-health-simplification/`](../archive/plans/site-health-simplification/).

## Delivery order

### G1 — Site Health truthfulness

- Keep one acquisition boundary and one PostgreSQL crawl/task lifecycle.
- Persist immutable attempts/artifacts and versioned analysis rows.
- Classify pages deterministically with visible evidence and explicit
  abstention.
- Apply schema and content rules only to their declared page kinds.
- Preserve HTML and JS-shell guards when narrowing applicability.
- Keep Site Health, Issues, and Opportunities as the only site surfaces.

### G2 — Content grounding envelope

The shipped Content owner freezes confirmed or edited BrandProfile facts and
exact crawl-observed fragments into one bounded envelope. Provider inputs and
source markers are validated against that frozen manifest; unavailable evidence
is labelled ungrounded. Generated text never becomes a durable fact.

### G3 — Demand evidence

- Continue immutable GSC/GA4 imports and coverage reporting.
- Join queries, pages, events, journeys, and opportunities with explicit
  unavailable states.
- Keep AI Visibility as measurement, not business truth.

### G4 — Agent orchestration

- Add tools only over typed persisted domain services.
- Bound context packages, attempts, retries, and child-task reconciliation.
- Require explicit user decisions for save/publish/external mutation.

## Gates

Each slice must:

1. extend the existing owner rather than create a parallel store or queue;
2. preserve workspace authorization and append-only evidence;
3. carry exact source IDs and relevant versions;
4. add deterministic fixtures and focused tests;
5. expose unknown, unavailable, not-applicable, and excluded distinctly;
6. update the active owner and archive superseded guidance;
7. pass focused verification before the next slice begins.

## Current priority

Site crawl and page-kind/schema correctness are release-critical because every
score and issue depends on them. Content grounding is the next product decision.
Mechanical module splitting and table reduction follow only when they preserve
those contracts and measurably reduce maintenance cost.
