# CiteLadder invariants

> Review-blocking rules. A change that violates any rule fails review even when it appears to
> work. These are deliberately few. A rule that needs a paragraph of exceptions is a design
> problem, not an invariant.

## 1. One concept, one owner

Search before adding. Extend the owning model, service, config, queue, artifact, API, component,
or registry. Do not create a second crawler, page analysis, opportunity store, prompt resource,
content queue, knowledge store, or industry taxonomy.

`SitePageAnalysis` is the single page-understanding owner. `PageUnderstanding` is its public
DTO name, never a second table.

## 2. Configuration and industry knowledge are data, not service literals

Thresholds, models, transports, limits, schemas, page roles, classifier signals, entity and
predicate registries, journey templates, question expectations, claim policies, context budgets,
confidence thresholds, and prompt/content archetypes live in `backend/app/core/config/*` or the
versioned industry registry. Domain and worker code reads frozen configuration; it does not embed
it.

## 3. Workspace authorization on every project-owned operation

All project-owned reads and writes verify active workspace membership and filter by
`workspace_id`. IDs alone are never authorization. Project data is not scoped by `user_id`. All
IDs are UUIDs. Billing ownership may use an account owner only through the explicit workspace
billing boundary.

## 4. Evidence is immutable and is not truth

Raw crawl, document, integration, answer-engine, generation, and external-source artifacts are
written once. Attempts and source observations are append-only. Persistence means "observed", not
"true". Reruns produce new identities.

## 5. Every derived artifact records what produced it

Page understanding, assertions, relations, findings, scores, demand signals, opportunities,
briefs, prompts, validations, verifications, and agent results reference exact source IDs plus the
relevant extractor, analyzer, pack, rule, formula, template, provider, and model versions.

The requirement is that a result can be **re-inspected**: the manifest names exactly what went in.
Re-*deriving* a result bit-for-bit is required only for evaluation fixtures, where the retrieval
model and index version are pinned. Do not conflate the two — a semantic reranker in the path does
not invalidate an artifact whose manifest is complete.

## 6. Reads are persisted projections

Read endpoints and report renderers never crawl, sync, call a model or provider, or silently
repair state. They render persisted evidence and projections. Missing evidence stays missing.

## 7. Unknown states remain distinct

`unknown`, `unavailable`, `not_applicable`, `historical`, `future`, `conflicting`, `excluded`,
`failed`, and observed zero have different meanings. Do not collapse them into zero, false,
neutral, current, or pass.

Composite scores are reported over the **full** denominator with coverage shown beside them. Never
renormalize a composite over only the observed dimensions: missing evidence correlates with
weakness, so renormalizing rewards the sites with the least to show.

## 8. Generic page kind and industry role are separate

`page_kind` is a stable cross-industry structural classification. `industry_role` is defined by a
frozen industry pack. No industry extends the generic enum to encode its business roles, and no
industry gets a parallel page-analysis table.

## 9. Deterministic code owns facts; models own judgement, and say so

Code owns URL and media disposition, parsing, exact identifiers, dates, units, schema syntax,
deduplication, configured signal scoring, validation, and lifecycle state.

Models may make semantic judgements code cannot — matching a differently-worded page or question
to a pack archetype, reconciling bounded claims, drafting. Every such judgement persists its
confidence, model, and template version with the result.

A model judgement that **dismisses** a gap requires higher confidence than one that **detects**
it, because a false detection is visible and recoverable while a false dismissal is neither.
Thresholds are config-owned.

## 10. Customer knowledge never mutates shared industry knowledge

Project evidence, conversations, corrections, analytics, and model output stay tenant-scoped.
Generalized improvements enter a reviewed industry-registry release with version, migration notes,
fixtures, and tests. There is no automatic cross-customer training or pack mutation.

## 11. The system runs itself except at two decisions

Human **gates** exist at exactly two points:

- **generate and save content**, and
- **run and schedule audits.**

Acquisition within a schedule, classification, knowledge extraction, contradiction detection, gap
detection, opportunity creation, demand signals, prompt generation, prioritization, and roadmaps
are automatic. Do not add an approval gate to make a derivation safe — a derivation is made safe by
being a recomputable projection over immutable evidence, and by recording what produced it.

Approval gates are for spending money and for leaving the system. Nothing else.

Contradiction handling does not add a third approval gate. Every observed side stays immutable and
`observed`; a user may make an inline correction when the derived projection is wrong. Creating or
withdrawing that correction is an explicit, non-gating durable action with an append-only audit
trail—not approval of an observation and not a publication decision. It therefore sits outside the
exactly-two gate count. Withdrawal restores the latest derived value.

## 12. Derived facts are recomputable; corrections are durable

Project facts are projections and may be recomputed or superseded at any time. A user correction
is not: it persists across recomputation, outranks the derived value, records its author and
timestamp, and can be withdrawn to restore the derived value.

Generated content is never automatically promoted into project facts. A crawl or import may
supersede a derived fact; neither may overwrite a correction.

## 13. Context is selected, bounded, and inspectable

Generative and agent tasks receive a task-specific `TaskContextPackage` after authorization. The
package includes contradictions and limitations, enforces section and total budgets, redacts
secrets and prohibited data, records omissions, and freezes a manifest before provider I/O.
Embeddings are ranking projections, not truth or authorization.

## 14. Generated content cannot fabricate facts

Every draft is grounded in a frozen brief and context package. Unsupported, conflicting,
historical-as-current, regulated, numeric, price, fee, date, policy, safety, and identity claims
are validated automatically, and blocking failures prevent saving at the API as well as the UI.
A provider cannot cite an artifact absent from its context package; server validation resolves
every citation and rejects fabricated ones.

Where structured data mirrors visible content — `FAQPage` and its equivalents — the markup is
generated from reviewed visible content, never as a substitute for it.

## 15. The Growth Agent is bounded orchestration

The agent uses an explicit task catalog and typed tools. Every tool call is separately authorized,
idempotent where required, bounded, and versioned. The agent has no arbitrary SQL, unrestricted
URL access, provider impersonation, private data store, autonomous recursion, or external mutation
outside the two decisions in §11.

The agent presents and explains priority; it does not set it. A deterministic formula owns
ordering. An agent-proposed reordering is a separate, visible, reversible artifact.

## 16. Provider secrets and private evidence never leak

Credentials are encrypted at rest, resolved only by the owning connector, and excluded from DTOs,
logs, snapshots, context packages, and artifacts. Raw OAuth data and unrelated private evidence are
not sent to models. Measurement provider identity remains separate from analysis and generation
provider identity.

## 17. PostgreSQL queue leasing is authoritative

Workers claim with `FOR UPDATE SKIP LOCKED`, commit before network I/O, heartbeat leases, use
bounded retries, and reconcile expired work. Succeeded work is not re-executed under the same
identity. Cancellation is cooperative. Domain code depends on the queue protocol, not a concrete
future broker.

## 18. Historical evidence is immutable in context

A prompt audit freezes prompt text, provider route, mode, and versions. New demand evidence
proposes new candidates or priorities; it never rewrites an active historical audit. Scheduled runs
create new audit identities.

## 19. Frontend contract rules

The browser calls relative `/api/*` through Next.js rewrites. Response contracts are validated,
unknown additive response fields are tolerated per current API policy, and every ID is a UUID.
Frontend state never becomes a competing backend source of truth, and no production screen falls
back to mock data or computes a backend metric locally.

## 20. Archive is not authority

`docs/archive/` is excluded from implementation decisions and active-link validation. Historical
content must be restated in a current owner before it affects code.

## Operational gotchas

- Shell `POSTGRES_*` and `DATABASE_URL` values can override Docker Compose interpolation; use the
  documented `env -u ...` invocation in [`DEVELOPMENT.md`](DEVELOPMENT.md).
- Browser preview must use same-origin rewrites; `curl` does not reproduce duplicate-CORS browser
  failures.
- CiteLadder is pre-launch and keeps one `migrations/versions/0001_initial.py`. Fold schema changes
  into it and verify against a disposable database.
