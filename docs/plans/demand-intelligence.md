# Demand Intelligence

> **Status:** active owner and plan for first-party demand, journeys, prompts,
> and AI Visibility.

## Ownership

Demand Intelligence owns:

- immutable GSC and GA4 import artifacts plus normalized observations;
- configured business journeys and outcome definitions;
- query-to-page, event-to-journey, and landing-page coverage;
- immutable Demand snapshots and transparent signals;
- prompt portfolio lifecycle and generation evidence;
- scheduled/manual answer-engine measurements and AI Visibility projections.

It does not own website crawling, content generation, company truth, or a second
Opportunity store.

## Evidence flow

```text
GSC + GA4 + configured journeys + prompt measurements
  -> immutable source artifacts
  -> normalized observations with coverage
  -> DemandSnapshot
  -> DemandSignal
  -> existing Opportunity owner
```

Every derived row carries source IDs, requested/available report-family state,
time window, formula/analyzer version, and explicit unavailable reasons.

## First-party joins

- GSC queries and landing pages join through normalized URL identity.
- GA4 landing, engagement, event, key-event, and commerce observations remain
  separate until the configured join is supported by evidence.
- Missing permissions, unsupported report families, sampling, absent key
  events, and observed zero stay distinct.
- Journey coverage is based on configured steps and observed evidence; a model
  may explain but cannot change the metric.

## Prompts and AI Visibility

Prompts have explicit active/archive state, source provenance, audience/intent,
and generation version. The former industry-pack and Site knowledge inputs are
no longer available. Automatic prompt generation must use only currently
authorized persisted sources and report omissions; it must not fabricate a
business fact to fill the gap.

Answer-engine attempts and raw artifacts are immutable. Analyses preserve
provider/model identity, requested capabilities, citations, mentions,
rank/share metrics, and cost. Visibility measures how engines represent the
business; it does not determine whether a business claim is true.

## Scheduling

Schedules create ordinary persisted audit work and follow the same entitlement,
lease, retry, cancellation, and audit rules as manual runs. Timezone, cadence,
next/last run, prompt selection, and provider capability state are explicit.

## Opportunities

Demand signals route into the existing Opportunity subsystem. Priority uses a
versioned deterministic formula over available evidence. Unknown or unavailable
inputs never become zero. A model may explain the ordering but cannot silently
set it.

## Verification

Acceptance covers workspace isolation, immutable imports, requested-versus-
available capability state, URL/journey joins, observed-zero semantics,
schedule idempotency, prompt provenance, provider separation, and Opportunity
supersede-not-mutate behavior.
