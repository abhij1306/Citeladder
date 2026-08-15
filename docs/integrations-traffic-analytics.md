# Integrations, Traffic, and Analytics

> **Current role:** persisted first-party evidence and projections
> **Target role:** source layer for Demand Intelligence
> **Canonical plan:** [`plans/demand-intelligence.md`](plans/demand-intelligence.md)

The existing subsystem owns OAuth connections, property mapping, queued syncs, immutable import
artifacts, normalized metric rows, and current Traffic/Analytics snapshots. Demand Intelligence
extends these owners; reports and agent tasks never call Google or Bing directly.

## Current guarantees

- encrypted OAuth credentials and provider allowlists;
- queued, idempotent sync runs with append-only import artifacts;
- versioned derivation into normalized metric rows;
- project/workspace authorization and property mapping;
- persisted Traffic, page/query, referral, and analytics projections;
- revision-aware snapshots and explicit null/zero semantics;
- read routes that do not perform provider I/O.

## Required correctness work

Before creating Demand Signals:

1. A project/window projection must include all contributing GSC and GA4 source revisions; source
   identity must be part of refresh idempotency.
2. GSC requires query × page × date evidence plus coverage/truncation metadata.
3. GA4 report families must respect compatible scopes and use capability discovery.
4. Relative landing paths must resolve through the same canonical page identity as Site/GSC.
5. Engaged sessions and stable key events must be projected rather than discarded.
6. Join coverage and unmatched reasons must be exposed.
7. Unavailable measures remain null; observed zero is zero.
8. Alternative-dimensional GA4 reports must not be summed as independent activity.

## Cross-source owned-page equivalence

Demand owns `resolve_owned_page` for mapping GSC/GA4 URL variants onto an
existing workspace-owned `SiteUrl`. It is separate from crawler identity.
Exact normalized URLs return `exact`; a non-exact variant returns `resolved`
only when a persisted redirect or canonical declaration proves one target.
Sitemap membership and the configured preferred origin rank candidates but do
not prove equivalence. Heuristic-only candidates return `ambiguous`, including
a single candidate, and no candidate returns `unresolved`.

Every result includes the bounded candidate list, evidence kinds, and resolver
version. Every query filters both `workspace_id` and `project_id`; ambiguity is
never silently coerced into a join.

## Traffic and AI Referrals projections

Traffic headline totals describe the selected date window. **Day**, **Week**,
and **Month** choose the returned chart interval only: they change chart buckets
and prior-interval comparisons, not the selected window or headline totals. The
projection returns its actual `granularity`; clients derive bucket labels,
interval badges, and comparison wording from that value. Top pages and top
queries are selected-window totals and are independent of chart interval.

Traffic reads resolve the exact `(window_start, window_end, granularity)` when
dates are supplied. They use the newest snapshot only when the caller
explicitly omits the window to request current/latest state. The wire-level
`evidence_state` distinguishes `not_run`, `observed_zero`, and `available`, so
an absent snapshot never masquerades as a measured zero.

AI Referrals uses `ga4_source_medium_daily` as the canonical session grain.
The deterministic referrer classification selects AI-source sessions for volume;
all sessions from the same source/medium report form the referral-share and
source-share denominator. Referrer-report rows are retained with their source
artifacts and classifications for provenance, but are excluded from session
sums so alternative GA4 dimensions cannot double count. Public rows contain AI
sources only; `other` classifications remain available to the formula and audit
trail. A referral analyzer or formula version bump is applied by an explicit
rebuild of derived snapshots, never on a read.

## Demand projections

Demand Intelligence creates versioned `DemandSignal` and `DemandSnapshot` projections over:

- search query and query-page performance;
- landing/acquisition/engagement observations;
- configured journey/key-event observations;
- AI referrals;
- Site and Content coverage;
- active prompt and Visibility evidence.

For GSC query analysis, the integration owner remains the sole raw-truth owner:
`gsc_query_page_daily` is immutable input. The Demand refresh selects the latest
row per property/date/dimension key, then persists a separate bounded
`QueryEvidenceSnapshot` before detector computation. Its rows retain exact
metric-row and artifact IDs, importer version, query, page, date, metrics, and
versioned owned-page resolution. Identical source/window/version input is
idempotent; changed input appends and supersedes. The read-only query-evidence
API requires an exact window and exposes 100 rows by default, at most 500, from
a projection capped at 5,000 rows and 100 artifacts. It never issues a provider
request or duplicates normalized GSC metric truth.

Each signal records window, source artifact/row IDs, identity joins, coverage, confidence,
limitations, formula/analyzer version, and related page/entity/journey/question.

## Journey configuration

Analytics cannot define a conversion by itself. A reviewed `JourneyDefinition` maps conceptual
stages, primary/secondary outcomes, relevant page roles, and compatible events. Industry profiles
propose defaults; users confirm project mappings. Missing event configuration is a measurement
gap—not evidence of zero conversion.

## Future connectors

Paid media, CRM/admissions, email, social, campaign, call-tracking, and other connectors join the
same evidence and journey contracts. Provider-specific rows remain in the integration owner;
Demand Intelligence consumes normalized observations and never makes one connector the universal
business model.

Detailed v1 sync and development notes are archived at
`archive/subsystems/integrations-traffic-analytics-v1.md`. Verify provider grains and current code
before reusing any historical implementation detail.
