# CiteLadder — Growth Intelligence Architecture

**Status:** canonical product architecture
**Runtime shape:** modular monolith; FastAPI API and workers; Next.js frontend; PostgreSQL state and queue
**Product hierarchy:** four layers — Site Intelligence, Content Intelligence, Demand Intelligence, and the Growth Agent
**First industry packs:** Education, then Commerce

## 1. Product vision

CiteLadder is the growth operating system for businesses that cannot afford to manage website
health, brand knowledge, content production, search demand, analytics, AI visibility, and growth
planning in disconnected tools.

It answers four connected questions:

1. What does this business currently say and prove?
2. What is missing, weak, contradictory, stale, or hard to discover?
3. What are customers demonstrably asking and doing?
4. What should the business improve, create, and measure next?

The durable differentiator is a project-specific, evidence-backed knowledge system that compounds
through every crawl, import, analysis, generation, audit, and verified outcome.

**The system runs itself.** Acquisition, understanding, gap detection, prioritization, demand
analysis, and recommendation all happen automatically. The product's job is to arrive at a
conclusion and show its work — not to ask the user to authorize each step toward it.

## 2. The four layers

Three layers own data. The fourth is how the user talks to them.

### 2.1 Site Intelligence

Owns the business's owned digital corpus:

- URL and document inventory;
- safe crawling, rendering escalation, and immutable artifacts;
- generic page kind and industry-specific role classification;
- content units, questions, entities, assertions, relationships, schema, and temporal state;
- discoverability, answerability, trust, machine clarity, and journey coverage;
- findings and grouped opportunities;
- snapshots, reports, exports, and recrawl verification.

It creates the knowledge foundation every other layer consumes.

**Shipped as of PR #55:** everything above except the last item's *recrawl verification*, and
except contradiction *review*. Snapshots, reports, and exports are live; snapshot-to-snapshot
comparison and `verified | partial | unresolved` resolution (slice S5) are not built, and
contradictions are detected and grouped but never block publication or reach a reviewer. See
[`plans/site-intelligence-primary-product.md` §15](plans/site-intelligence-primary-product.md#15-delivery-status-and-open-work)
for the authoritative list.

### 2.2 Content Intelligence

Turns evidence into reviewable improvements:

- content inventory and portfolio strategy;
- missing-page, missing-section, unanswered-question, contradiction, trust, and demand gaps;
- deterministic briefs carrying verified facts, prohibited claims, sources, and success criteria;
- task-scoped context packages;
- provider-neutral generation and append-only attempts;
- automatic validation, then user edit and save;
- recrawl, demand, and visibility verification.

### 2.3 Demand Intelligence

Connects external and behavioural evidence to the owned knowledge system:

- Google Search Console query and page observations;
- Google Analytics landing, engagement, event, key-event, and commerce observations;
- configured business journeys and outcome definitions;
- query-to-page and event-to-journey coverage;
- demand signals and transparent priorities;
- prompt portfolios and multi-engine AI Visibility measurement;
- aligned-window comparisons after site or content changes.

Visibility is measurement truth for answer-engine mentions, citations, rankings, and share of
voice. It does not own company truth and does not define the product hierarchy.

### 2.4 Growth Agent

The conversation and orchestration layer. It is a real layer of the product — the one the user
spends the most time in — but it owns no data of its own:

- explains persisted evidence, findings, signals, and changes;
- builds prioritized roadmaps from the three layers' own outputs;
- calls typed Site, Content, and Demand tools;
- assembles bounded, inspectable context rather than dumping the knowledge base;
- creates strategies, briefs, drafts, and prompts;
- stops at the two decision points in §3 and nowhere else;
- preserves model, context, tool, cost, and result provenance.

It is not a fourth data owner, an unrestricted chat interface, or an autonomous publisher. Every
fact it states belongs to one of the three intelligence layers and resolves to that layer's
evidence.

## 3. What the user decides

The system is automatic except at two points. This is a hard product boundary, not a default.

| Decision | Why the human is here |
|---|---|
| **Generate and save content** | Content is the product's only durable outward-facing output. The user chooses what to generate, edits it, and decides what to keep. |
| **Run and schedule audits** | Crawls, syncs, and answer-engine audits cost money and hit external systems. The user chooses when they run and on what cadence. |

Everything else runs on its own: crawling within an approved schedule, classification, knowledge
extraction, assertion and contradiction detection, gap detection, opportunity creation, demand
signals, prompt generation, prioritization, and roadmap construction.

Nothing in that automatic set is irreversible. Every derived artifact is a recomputable
projection over immutable evidence, so an error is corrected by fixing the input or the rule and
recomputing — not by having asked a human first. Approval gates are reserved for actions that
spend money or leave the system; they are not used as a substitute for correctness.

**Corrections, not approvals.** Where the user disagrees with a derived fact, they correct it. A
correction is durable, wins over any later derivation, and records who made it and when. This is
opt-out where the old model was opt-in: the user touches the knowledge layer only when something
is wrong, not to bless each thing that is right.

## 4. Canonical improvement loop

```text
owned domain, documents, and integrations
  -> immutable evidence
  -> page and document understanding
  -> project facts, gaps, and demand signals
  -> prioritized opportunities
  -> brief
  -> generated content the user edits and saves
  -> recrawl, resync, or visibility audit
  -> compatible before/after observation
  -> next recommended action
```

Every stage is inspectable and versioned. A later observation never rewrites earlier evidence.

## 5. Knowledge system

Two layers, not three.

### Immutable evidence

Observed artifacts, persisted automatically for reproducibility:

- crawl attempts and page/document artifacts;
- integration imports and normalized metric rows;
- answer-engine responses, citations, and analyses;
- generation requests and attempts;
- user actions.

Persistence means "observed", not "true".

### Project facts

The current best understanding of the business, derived automatically from evidence and kept
current. Includes entities, assertions, relations, questions, topics, audiences, offerings,
journeys, contradictions, gaps, demand signals, opportunities, briefs, and prompts — each carrying
confidence, coverage, effective dates, limitations, and analyzer versions.

Project facts are recomputable. A user correction is the one thing that is not: it persists across
recomputation, outranks derived values, and is preserved with its author and timestamp. A
correction can be edited or withdrawn, which restores the derived value.

Embeddings are optional retrieval projections. They are never authorization filters and never the
canonical truth store.

## 6. Core ontology and industry knowledge

The stable core models reusable concepts: corpus items and evidence; generic page kinds; entities,
assertions, relations, questions, topics, audiences, offerings, and content units; journeys,
stages, outcomes, demand signals, prompts, actions, briefs, context packages, and verification;
temporal, confidence, coverage, and contradiction state.

A versioned `IndustryPack` supplies industry-specific behaviour: page roles and classifier signals,
expected entity/relation/assertion types, journeys and outcomes, customer questions and content
expectations, schema parity expectations, trust and regulated-claim policies, rules, report
modules, brief and prompt archetypes, and evaluation fixtures.

The active analysis contract is:

```text
stable core + one primary industry pack + reviewed capabilities + versioned project overlay
```

This matches the normative contract in
[`../backend/app/core/config/industry_packs/EXTENSION_CONTRACT.md`](../backend/app/core/config/industry_packs/EXTENSION_CONTRACT.md),
which the pack validator enforces. Capabilities (`lead_generation`, `local_presence`, and the rest
of `capabilities.json`) are cross-cutting modules that a pack opts into; they add requirements and
never weaken shared controls.

**Known limitation.** A business with two genuine industry identities — a school with a
merchandise store, a retailer with a learning centre — has no composition path today, because
capabilities are cross-cutting concerns rather than industries. The forward-compatible mechanism
is ordered secondary packs scoped by URL subtree, with the primary pack winning ties. Every
understanding row already records its winning `pack_id` and `pack_version`, so adding this later
does not require a migration of existing rows. It is not built now.

Customer facts never mutate a shared pack. Generalized improvements enter a reviewed pack release
with fixtures and compatibility notes.

## 7. Page understanding

Page analysis separates two concepts:

```text
page_kind      = generic structural job
industry_role  = active-pack business job
```

```text
page_kind=conversion  industry_role=education.admissions_overview
page_kind=detail      industry_role=commerce.product_detail
page_kind=trust       industry_role=healthcare.clinician_profile
```

**One owner.** `SitePageAnalysis` is the single page-understanding row. It becomes append-only,
keyed by `(artifact_id, analyzer_version, pack_id, pack_version)`, with one `is_current` row per
corpus item. `PageUnderstanding` is the public API/DTO name for that row. There is no second
page-analysis table, and recomputing under a new pack version writes a new row rather than
mutating the old one — which is exactly what recrawl comparison needs.

Classification is deterministic-first: code owns URL and media disposition, parsing, exact
identifiers, dates, units, schema syntax, deduplication, and configured signal scoring. Structured
data is one signal and one expectation; its absence cannot prevent classification from visible
evidence.

**Where a model decides, say so.** Matching a differently-worded page or question to a pack
archetype is a semantic judgement that deterministic normalization cannot make. Those matches are
model-assisted, and each one persists its confidence, model, and template version alongside the
result. The asymmetry matters: a match that *creates* work is recoverable, while a match that
*dismisses* a gap hides it. Dismissals therefore require higher confidence than detections, and
the threshold is config-owned.

## 8. Demand, marketing, and measurement

The product progressively brings marketing strategy into the same knowledge system: organic demand
and query-page fit; landing-page and configured outcome evidence; paid campaign evidence when a
connector exists; AI prompt portfolios and visibility audits; content and site action verification;
business-priority and effort-aware roadmaps.

CiteLadder does not claim causality from aggregate correlations. It displays aligned windows,
sample size, source coverage, missing joins, and limitations. "Unavailable", "not configured", and
"observed zero" remain distinct.

## 9. Scores and coverage

Composite scores are reported over the **full** denominator with an explicit coverage figure
beside them. A composite is never renormalized over only the dimensions that happened to be
observable.

Renormalizing upward assumes missing dimensions would have scored like the observed ones, and in
this domain that assumption fails in a predictable direction: absent evidence correlates with
weakness. A site with no schema graph, no policy pages, and no author attribution is missing
exactly the dimensions it would have failed, and renormalization would hand it a better score than
a site that published all three and scored badly. Low coverage is itself the finding, and it is
shown as one.

## 10. Scheduled growth programs

Scheduling is a governed orchestration feature, not an unbounded agent loop. A `GrowthProgram`
defines a versioned, user-scheduled cadence for recurring recrawls, GSC/GA4 syncs, visibility
audits, stale-content reviews, executive snapshots, and post-publication verification windows.

Each schedule freezes task policy, resource scope, and cost/concurrency limits. Scheduled runs call
the same typed domain tools and create the same immutable artifacts as manual runs. Setting the
schedule is one of the two user decisions in §3; each run inside it is not.

## 11. Runtime architecture

CiteLadder is a modular monolith:

- Next.js frontend;
- FastAPI API;
- separate worker processes;
- PostgreSQL as canonical product state and task queue;
- object storage only when bounded database artifacts are insufficient;
- provider-neutral model gateway;
- direct measurement adapters for answer engines;
- typed domain modules rather than autonomous microservices.

Core runtime rules:

- workspace authorization on every project-owned query;
- UUID identities;
- config-owned policy;
- immutable artifacts and append-only attempts;
- short transactions and commit before external I/O;
- idempotent queued mutations and leased single-writer workers;
- persisted projections on reads;
- coded errors and same-origin browser APIs.

**Pre-launch database policy.** CiteLadder keeps one `migrations/versions/0001_initial.py`.
Schema changes fold into it and a disposable database is reset and re-verified. This is
deliberate: multiple pre-launch migrations create more confusion than they prevent. Development
data is disposable, and longitudinal behaviour — recrawl comparison, before/after verification —
is proven against re-ingestable fixtures rather than against accumulated local state.

## 12. Transition from the original product

CiteLadder was first built around AI Visibility. That capability is retained; the product is
reorganized rather than rebuilt.

| Existing capability | Target owner |
|---|---|
| Site Health crawler, pages, issues, snapshots | Site Intelligence |
| Brand Profile / Knowledge Base | Project facts and corrections |
| Content v1 generation | Content Intelligence generation and attempt foundation |
| GSC/GA4, Traffic, Analytics | Demand Intelligence evidence and projections |
| Topics, prompts, audits, visibility | Demand Intelligence prompt and outcome loop |
| Opportunities | Shared evidence-backed action bundles across all layers |
| Agent/discovery clients | Provider gateway and bounded Growth Agent |
| Commerce catalog and product visibility | Commerce pack identity and demand evidence |

Implementation extends these owners and corrects lifecycle and provenance gaps. It does not create
a second crawler, queue, prompt system, content store, opportunity store, or knowledge silo.

## 13. Delivery sequence

Sequence is owned by
[`plans/growth-intelligence-platform.md`](plans/growth-intelligence-platform.md) §10 and is not
restated here. The dependency that matters most: **project facts precede content generation.** A
brief cannot be built from assertions that do not exist yet.

## 14. Success measures

CiteLadder reports separate coverage and outcome layers rather than one opaque score:

- **Evidence:** relevant-corpus, extraction, integration, join, and audit coverage.
- **Knowledge:** assertion provenance, current-state confidence, contradiction resolution, and
  correction rate — a falling correction rate is the honest signal that derivation is improving.
- **Site:** role, question, journey, schema, and trust coverage, plus verified action resolution.
- **Content:** brief acceptance, unsupported-claim rate, edit distance before save, publication
  observation, and later demand or visibility association.
- **Demand:** query-page fit, event coverage, prompt acceptance, and priority stability.
- **Outcome:** configured qualified actions, organic and paid efficiency where evidence exists,
  owned citations, mentions, and share of voice.
- **Agent:** context precision, evidence citation rate, tool success, bounded cost, and zero
  unauthorized external mutation.

**Acceptance, not precision.** Precision requires labelled ground truth, and the only labels
available are authored by the same people who wrote the rules, on the same corpus the rules were
tuned against — a circular measure that reads high regardless of usefulness. Production reports
**acceptance rate**: accept / dismiss / not-applicable on real findings. The word "precision" is
reserved for a corpus slice held out during rule authoring, which
[`../backend/app/core/config/industry_packs/EVALUATION_CONTRACT.md`](../backend/app/core/config/industry_packs/EVALUATION_CONTRACT.md)
owns.

## 15. Documentation authority

The active documentation map is [`documentation-index.md`](documentation-index.md). Canonical
program plans live under `docs/plans/`. Current-runtime references describe shipped behaviour.
Everything under `docs/archive/` is historical and must not guide implementation.
