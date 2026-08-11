# CiteLadder architecture

> **Status:** canonical product architecture
> **Runtime:** FastAPI modular monolith, separate workers, Next.js frontend,
> PostgreSQL durable state and queues

CiteLadder is an evidence-grounded growth platform with three product systems
and one bounded orchestrator.

## Product systems

### Site Health

Site Health acquires and analyzes the owned website. It owns secure discovery
and crawling, immutable artifacts, normalized facts, deterministic structural
page types, page-type schema contracts, rule evaluations, scores, issues,
snapshots, exports, and site-derived opportunities.

Its product surface is deliberately limited to Site Health, Issues, and
Opportunities. Detailed contracts live in [`site-health.md`](site-health.md).

### Content Intelligence

Content Intelligence owns inventory strategy, briefs, generation attempts,
validation, user revisions, save decisions, publication claims, and later
verification. Generated prose is never promoted to business truth
automatically.

The former knowledge-assertion source for content fact grounding was removed
with the Site Intelligence simplification. Until a replacement evidence source
is approved, the runtime exposes an explicit empty fact/source envelope rather
than fabricating grounding.

### Demand Intelligence

Demand Intelligence owns GSC and GA4 imports, journeys, demand signals, prompt
portfolios, schedules, answer-engine measurements, and AI Visibility. AI
Visibility measures mentions, citations, rankings, and share of voice; it does
not define company truth or the product hierarchy.

### Growth Agent

The Growth Agent orchestrates typed tools over persisted Site Health, Content,
and Demand projections. It owns conversations and task execution, not a second
copy of system data. It cannot publish content, activate prompts, or mutate an
external system without an explicit user decision.

## Evidence flow

```text
external or owned source
  -> immutable evidence / provider attempt
  -> deterministic or bounded derived projection
  -> persisted issue, signal, brief, measurement, or opportunity
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
| Content strategies, briefs, drafts, revisions, verification | Content Intelligence |
| GSC/GA4, journeys, demand signals, prompts, AI Visibility | Demand Intelligence |
| Cross-system persisted action ranking | Opportunities |
| Conversation and bounded typed-tool orchestration | Growth Agent |
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
