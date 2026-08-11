# CiteLadder invariants

> Review-blocking rules. A change that violates one fails review even if it
> appears to work.

## 1. One concept, one owner

Search before adding. Extend the owning model, service, config, queue, artifact,
API, or component. Do not create a second crawler, page analysis, opportunity
store, prompt resource, content queue, or memory store.

`SitePageAnalysis` is the only page-understanding owner.

## 2. Product policy is configuration

Thresholds, transports, limits, schemas, page kinds, classifier signals, rule
applicability, context budgets, models, and templates live under
`backend/app/core/config/*` or the owning frontend config. Services and workers
do not embed alternate policy.

## 3. Workspace authorization is mandatory

Every project-owned read and write verifies active workspace membership and
filters by `workspace_id`. IDs alone are never authorization. Product data is
not scoped by `user_id`. IDs are UUIDs.

## 4. Evidence is immutable and is not truth

Raw crawl, integration, answer-engine, generation, and external-source
artifacts are written once. Attempts and observations are append-only.
Persistence means observed, not automatically true.

## 5. Derived artifacts record provenance

Analyses, rule evaluations, scores, demand signals, opportunities, briefs,
prompts, validations, verifications, and agent results reference exact source
IDs and every relevant extractor, classifier, analyzer, rule, scoring, formula,
template, provider, and model version.

## 6. Reads are persisted projections

Read endpoints never crawl, sync, classify, call a model/provider, or silently
repair state. Missing evidence stays missing.

## 7. Unknown states remain distinct

`unknown`, `unavailable`, `not_applicable`, `historical`, `future`,
`conflicting`, `excluded`, `failed`, and observed zero are different states.
Never collapse them into zero, false, current, neutral, or pass.

## 8. Page kind drives page-specific analysis

`page_kind` is a stable structural classification. Structured data is only one
signal and cannot self-certify the type whose schema contract is being checked.

`other` is classification abstention, not an inferred `WebPage`. Page-kind
rules fail closed for it. Content-reading rules also remain not-applicable when
the server response is a JS shell; the rendering rule owns that observable
failure.

## 9. Deterministic code owns measurable facts

Code owns URL/media disposition, parsing, exact identifiers, dates, units,
schema syntax, configured signal scoring, validation, and lifecycle state.
Models may explain, generate, plan, or adjudicate explicitly bounded ambiguity.
Every model judgement records confidence, model, and template version.

## 10. Automation stays bounded

Site Health acquisition begins only from an explicit user **Run new crawl**
decision. Its durable discovery and deterministic analysis phases may then
progress automatically, but analysis admission remains bounded by the frozen
entitlement/runtime allowance. Other configured classification, opportunity
creation, demand imports, prompt generation, and scheduled measurement may run
automatically. Explicit user decisions are required for content save/publish
claims, external mutations, prompt activation, billing changes, and any future
durable-memory promotion.

## 11. Context is selected and inspectable

Generative and agent tasks receive an authorized, task-specific bounded context
package. It records included sources, omissions, limitations, budgets, and a
frozen manifest before provider I/O. Embeddings rank evidence; they are not
truth or authorization.

## 12. Generated content cannot fabricate facts

Unsupported, conflicting, historical-as-current, regulated, numeric, price,
date, policy, safety, and identity claims must be validated against the context
actually supplied. A provider cannot cite an absent artifact. Generated content
never becomes a fact automatically.

The current content fact envelope is explicitly empty after removal of the
former knowledge-assertion source. Do not pretend that this is grounded; a
replacement source requires a separate product decision.

Where structured data mirrors visible content, such as `FAQPage`, markup is
generated from reviewed visible content rather than substituted for it.

## 13. The Growth Agent is bounded orchestration

The agent uses a config-owned task catalog and typed domain tools. Every call is
authorized, bounded, versioned, and idempotent where required. The agent has no
arbitrary SQL, unrestricted URL access, provider impersonation, private data
store, autonomous recursion, or unapproved external mutation.

## 14. Secrets and private evidence do not leak

Credentials are encrypted at rest, resolved only by the owning connector, and
excluded from DTOs, logs, snapshots, context packages, and artifacts. Provider
identity for measurement stays separate from analysis and generation provider
identity.

## 15. PostgreSQL is the durable queue

Workers claim with `FOR UPDATE SKIP LOCKED`, commit before network I/O,
heartbeat leases, and terminalize atomically and idempotently. Do not add Redis
without measured need.

## 16. The migration baseline remains singular

Before launch, schema changes are folded into
`migrations/versions/0001_initial.py`. Verify from an empty disposable database
with `alembic upgrade head` and `alembic check`; do not add `0002+` without an
explicit policy change.
