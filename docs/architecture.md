# CiteLadder architecture

> **Status:** canonical product architecture
> **Runtime:** FastAPI modular monolith and separate workers, Next.js frontend,
> PostgreSQL durable state and queues; one Compose stack for local production-like execution

CiteLadder is an evidence-grounded growth platform organized around one loop:

```text
Connect -> Analyze -> Act -> Improve / Verify -> Track -> recompute Analyze
```

Its primary measured outcome is increased **observed** mention/citation share
across a versioned prompt portfolio under comparable audit conditions. Crawl
health, GSC demand coverage, and AEO readiness are leading indicators. They do
not prove CiteLadder caused a later change.

## Capabilities behind the loop

### Site Health

Site Health acquires and analyzes the owned website. It owns secure discovery
and crawling, immutable artifacts, normalized facts, deterministic structural
page types, page-type schema contracts, rule evaluations, scores, issues,
snapshots, deterministic comparable-crawl changes, exports, and site-derived
opportunities.

Its product surface is deliberately limited to Site Health, Issues, and
Opportunities. Detailed contracts live in [`site-health.md`](site-health.md).

### Content Intelligence

Content Intelligence owns website-grounded generation requests and attempts,
history, retry and regeneration, cancellation, and feedback. The shipped
runtime does not own validation state machines, user revisions, save decisions,
publication claims, or later verification. Generated prose is never promoted
to business truth automatically.

Each generation freezes one bounded grounding envelope. Confirmed or edited
BrandProfile fields are the only allowed business facts; exact crawl fragments
remain untrusted observations for terminology, structure, tone, or explicit
attribution. Conflicts prohibit the affected claim class, and missing evidence
is exposed as an ungrounded draft rather than fabricated grounding.

### Demand Intelligence and Track

Demand Intelligence owns GSC and Traffic observations, demand signals, prompt
portfolios, schedules, answer-engine measurements, and AI Visibility. AI
Visibility is the Track station: it measures observed mentions, citations,
rankings, and share of voice under comparable conditions.

Every manual, scheduled, repaired, brand, and Commerce audit uses one
citation-capable execution policy. Users select logical engines and
repetitions, never a measurement mode. Each engine resolves to one approved
retrieval-enabled route, and the exact provider, transport model, retrieval
state, reasoning policy, and request configuration are frozen as provenance.
Trend comparability is separated by that frozen model/retrieval identity.

`benchmark_mode` remains a project-owned prompt-framing choice only; it does
not select a transport model or retrieval policy.

### Growth Agent

The Growth Agent is a top-bar orchestrator over persisted Site Health, Content,
and Demand projections, not a navigation station or a second copy of system
data. It cannot publish content, activate prompts, or mutate an external system
without an explicit user decision.

## Product stations

| Station | User job | Primary capability owners |
|---|---|---|
| Overview | See loop state, company facts, and one next action | Cross-system persisted projections |
| Connect | Establish authorized evidence and provider inputs | Projects and integrations |
| Analyze | Inspect website, search demand, traffic, and gaps | Site Health and Demand |
| Act | Prioritize and generate against one Opportunity | Opportunities and Content |
| Track | Compare observed citation share and later evidence | AI Visibility and analytics |

Improve / Verify is the transition after an explicit implementation declaration:
recrawl, resync, or audit evidence is observed without making a causal claim.

## Evidence flow

```text
external or owned source
  -> immutable evidence / provider attempt
  -> deterministic or bounded derived projection
  -> persisted issue, signal, generation, measurement, or opportunity
  -> user-visible evidence and explicit decisions
```

Raw evidence is append-only. Derived rows carry exact source IDs and every
relevant extractor, classifier, analyzer, rule, formula, template, or model
version. Read APIs project persisted state and never perform acquisition or
repair.

## Ownership boundaries

| Capability | Owner |
|---|---|
| Website discovery, acquisition, parsing, page kinds, rules, site snapshots | Site Health |
| Grounded content generation, attempts, history, feedback | Content Intelligence |
| GSC/Traffic demand signals, prompts, AI Visibility | Demand Intelligence |
| Cross-system persisted action ranking | Opportunities |
| Standalone explain/roadmap typed-tool tasks | Growth Agent |
| Provider/OAuth configuration and secret storage | Integrations/providers |

An existing owner must be extended before adding a parallel crawler, parser,
queue, snapshot, opportunity store, generation store, or memory system.

## State and execution

PostgreSQL is both durable state and the task queue. Workers claim with
`FOR UPDATE SKIP LOCKED`, commit before network I/O, use leases and heartbeats,
and terminalize idempotently. Redis is not part of the architecture without a
measured requirement.

Project data is always workspace-authorized. Object IDs alone are never an
authorization boundary. All product IDs are UUIDs and browser APIs stay under
same-origin `/api/v1` routing.

## Automation boundary

Acquisition, deterministic classification, scoring, issue grouping, scheduled
measurement, and persisted projections may run automatically within configured
bounds. User decisions remain required for content save/publish claims,
external mutations, prompt activation, billing changes, and any future durable
memory promotion.

Models may classify bounded ambiguity, explain evidence, plan, or generate.
They may not overwrite raw truth, silently change deterministic metrics, or
turn unsupported output into a verified fact.

## Active implementation sequence

1. Keep Site Health crawl lifecycle and page-kind/schema analysis truthful.
2. Re-establish content fact grounding only from an approved evidence source.
3. Continue Demand joins and measurement coverage.
4. Extend Growth Agent tools only over typed persisted owners.
5. Verify changes through recrawl or aligned later observations where the
   owning subsystem supports it.

See [`plans/growth-intelligence-platform.md`](plans/growth-intelligence-platform.md)
for the active cross-system delivery view.
