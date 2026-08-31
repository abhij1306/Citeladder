# CiteLadder invariants

> Review-blocking rules. A change that violates one fails review even if it
> appears to work.

## 1. One concept, one owner

Search before adding. Extend the owning model, service, config, queue, artifact,
API, or component. Do not create a second crawler, page analysis, opportunity
store, prompt resource, content queue, or memory store.

`SitePageAnalysis` is the only page-understanding owner.

## 2. Product policy is configuration

Thresholds, transports, limits, schemas, page kinds, classifier signals,
capability families, family budgets, trait-conditioned profiles, rule
applicability, context budgets, models, and templates live under
`backend/app/core/config/*` or the owning frontend config. Services and workers
do not embed alternate policy. AEO has exactly 11 config-owned families; rule
count and page-kind cohort size cannot manufacture score influence.

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
template, provider, and model version. During disposable pre-launch
development, active semantic versions remain `1`; a semantic change resets the
development database instead of preserving cross-version history.

## 6. Reads are persisted projections

Read endpoints never crawl, sync, classify, score, call a model/provider, or
silently repair state. Missing evidence stays missing.

Site Health has one active score-summary projection and one immutable terminal
snapshot projection, both written by the same aggregation owner. Classification
coverage, AEO measurement coverage, and crawl coverage are distinct persisted
facts with exact provenance; clients never derive or substitute one for another.

Measurement comparison requires compatible persisted classification and scored
page-kind composition provenance. A changed kind set or count by kind remains
comparable only with the bounded composition-change reason and both
compositions; missing projection or incompatible scope/version is
non-comparable.

## 7. Unknown states remain distinct

`unknown`, `unavailable`, `not_applicable`, `historical`, `future`,
`conflicting`, `excluded`, `failed`, and observed zero are different states.
Never collapse them into zero, false, current, neutral, or pass.

## 8. Page kind drives page-specific analysis

`page_kind` is a stable structural classification. Structured data is only one
signal and cannot self-certify the type whose primary-entity schema contract is
being checked.

Successful acquisition durably records `classification_expected` for selected,
non-excluded supported HTML before page-understanding work begins. Terminal
`other` and post-assignment page-understanding failure remain separate counts
under the same denominator.

`other` is classification abstention, not an inferred `WebPage`. It retains
universal technical evidence but has null page-purpose AEO score and coverage,
state `not_measured`, and reason `page_purpose_unresolved`. Classified page
profiles enumerate every capability family as `measured`, `measurement_gap`, or
`not_applicable`; omission never implies N/A.

AEO checkpoint outcomes are exactly `satisfied`, `partial`, `missing`,
`unknown`, `not_applicable`, or `error`. Unavailable, ambiguous, and conflicting
evidence remain bounded reasons under `unknown`, not additional AEO outcomes.
Content-reading expectations on a JS shell preserve this distinction while the
rendering diagnostic owns the observable delivery limitation.

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
durable-memory promotion. Declaring an Opportunity implemented is also an
explicit user action. Later verification is a bounded observation over
persisted evidence and never a causal claim or an inferred workflow status.

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

Content generation freezes one versioned grounding envelope from confirmed or
edited BrandProfile fields plus exact crawl-observed fragments. Crawl text stays
untrusted observation, conflicts prohibit the affected claim class, and absent
source references fail validation. An unavailable envelope produces an
explicitly labelled ungrounded draft; it never fabricates grounding.

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
explicit policy change. All active development semantic versions remain `1`
under the same reset policy.
