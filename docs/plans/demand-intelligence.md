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

```text
immutable GSC/Traffic artifacts -> DemandSnapshot -> DemandSignal -> Opportunity
```

The public **Search Demand** screen is the latest workspace-authorized snapshot
plus an explicit recompute action. It is one screen, not a nested Overview or a
copy of AI Visibility. It shows the evidence window, a signal count, and ranked
query/page gaps with target type, target, GSC impressions, clicks, and CTR.
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
