# Demand Intelligence

> **Status:** shipped authority for deterministic first-party demand signals,
> Prompts, and AI Visibility.

Delivery sequencing and the Analyze/Track station contract are owned by
[`citeladder-aeo-product-rebuild.md`](citeladder-aeo-product-rebuild.md).

Demand snapshots derive from immutable GSC and Traffic observations. The first
shipped detector identifies high-impression, low-CTR search demand and preserves
exact source IDs, freshness, time window, formula version, and unknown versus
zero/unavailable states. A previous compatible snapshot provides a descriptive
comparison. Signals route to the existing Opportunity owner.

Before signal detection, the Demand refresh freezes a bounded
`QueryEvidenceSnapshot` over `gsc_query_page_daily`. Each row preserves the
normalized query, observed page URL, date, metrics, exact import artifact and
metric-row IDs, importer version, and the versioned owned-page resolution
outcome (`exact`, `resolved`, `ambiguous`, or `unresolved`). Resolution stores
the frozen `SiteUrl` identity and candidate evidence; it does not rewrite GSC
truth or widen a read into a sync.

The projection identity is workspace + project + exact window + source hash +
analyzer version. An identical retry reuses the immutable snapshot; changed
source evidence or versions append a snapshot that points to the prior one.
The config-owned row cap is 5,000 and source-artifact cap is 100. Latest-row
selection and its one-row truncation sentinel are enforced in SQL before ORM
rows are materialized. Coverage is
`available`, `observed_zero`, or `unavailable`, with truncation and missing
property evidence recorded as limitations.

Workspace-authorized persisted reads require `window_start` and `window_end`:

- `GET /api/v1/projects/{project_id}/demand/query-evidence` supports a typed,
  snapshot-bound cursor, filters, a default page size of 100, and hard maximum
  of 500. A cursor from a superseded snapshot is rejected instead of crossing
  immutable evidence sets.
- `GET /api/v1/projects/{project_id}/demand/query-evidence/summary` returns the
  snapshot and resolution counts without pagination.

Neither endpoint crawls, syncs, recomputes, nor repairs state.

## Query detectors and honest states

Detector thresholds are config-owned and model-free. The pure baseline lives
in `domain/demand/projection.py`; the stricter query-evidence algorithms are
split into `query_detectors.py`, while `detector_source.py` performs the one
bounded workspace/project-scoped input assembly. Every emitted signal carries
the exact source metric-row and artifact IDs plus analyzer, rule, formula,
classifier, and owned-page resolver versions. Multi-row signals retain the
complete sorted classifier-version and override-ID sets.

- Branded classification runs before all query detectors. Branded rows emit
  only `branded_query_performance`, remain visible as their own cohort, and
  never create an Opportunity. Ambiguous classifications abstain.
- `striking_distance` requires a resolved non-branded query/page, at least 50
  impressions, and an impression-weighted average position from 4 through 15.
- `query_cannibalization` requires one non-branded query to resolve to at
  least two distinct pages after URL equivalence. Each qualifying page needs
  20 impressions and 10% of the query total. Any ambiguous/unresolved page in
  the query group makes that query abstain.
- `property_relative_ctr_gap` groups resolved non-branded query/page rows by
  property and whole-number position band. A cohort needs 20 rows and 500
  impressions. A candidate needs 100 impressions and CTR at least 25% and two
  percentage points below the cohort median. Without such a cohort the
  detector state is `unavailable`; no universal curve is substituted.
- `emerging_query` and `declining_query` compare adjacent, non-overlapping
  14-day windows. The evidence set must cover every calendar day across both
  windows; endpoint-only or otherwise sparse history abstains as
  `insufficient_history`. Each query needs 50 total impressions and 10 per
  window. Emerging is at least 1.5x with +20 impressions; declining is at most
  0.67x with -20. Short coverage is `insufficient_history`.

The Demand snapshot persists each detector's `available`, `partial`,
`unavailable`, or `insufficient_history` state and limitations. Search Demand
renders these states and labels branded rows as non-actionable. Approved
actionable signals map into the existing Opportunity owner under distinct
rules for striking distance, cannibalization, property-relative CTR gap,
emerging demand, and declining demand. Query-to-page mismatch has no schema
token, detector, flag, or UI placeholder because no intended-page evidence
owner exists.

```text
immutable GSC/Traffic artifacts -> DemandSnapshot -> DemandSignal -> Opportunity
```

The public **Search Demand** screen is the latest workspace-authorized snapshot
plus an explicit recompute action. It is one screen, not a nested Overview or a
copy of AI Visibility. It shows the evidence window, a signal count, detector
state notes, and ranked query/page evidence with type, target, GSC impressions,
clicks, CTR, and position.
Rows are ordered highest-priority gap first, but the internal priority score is
not presented as a user metric. The GSC privacy/filtering limitation is stated
once for the surface.

The projection distinguishes no snapshot, unavailable Search Console evidence,
an observed zero qualifying gaps, and active gaps. Demand does not persist
configured journeys, duplicate Site inventory, provider capability panels, or
copied Prompt and Visibility summaries. Site completion does not enqueue Demand
work when no Site signal is consumed.

Prompts and AI Visibility retain their independent owners, immutable attempts,
evidence views, schedules, and provenance. Demand summary removal does not
remove either product. Acceptance covers workspace isolation, deterministic
signals/comparison, source freshness, missing/zero distinctions, recompute
idempotency, and Opportunity supersede-not-mutate behavior.

AI Visibility remains the standalone `/visibility` destination. AI Referrals is
the separate GA4 referral-measurement projection: it reports AI referral volume
over time, referral share, and source totals only. It does not duplicate answer
engine visibility, themes, correlations, or event-level UI. Its canonical
session dataset is `ga4_source_medium_daily`: AI volume is the sessions whose
deterministic classification matches an AI source; referral share and each
source share use all sessions from that same report as their denominator.
Referrer artifacts remain provenance only and are never added to those session
sums. Non-AI classifications remain in the canonical denominator and audit
record but do not render in the public AI Referrals projection. Formula/analyzer
version changes require an explicit snapshot rebuild; reads never repair state.

Branded-query classification uses canonical `Brand.name`, normalized aliases,
and owned-domain spellings. It returns `branded`, `non_branded`, or `ambiguous`
with matched terms and a classifier version. A single-token canonical name
requires exact-token plus owned-domain support; otherwise automatic
classification abstains as `ambiguous`. User overrides are append-only evidence
for one exact normalized query, and the newest workspace-scoped override wins.
