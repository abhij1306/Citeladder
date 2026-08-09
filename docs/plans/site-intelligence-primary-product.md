# Site Intelligence and Knowledge Foundation

> **Status:** S0–S4 delivered and merged (PRs #52, #53, #55). S5 is not started.
> This document stays canonical: sections 1–11 describe shipped behaviour,
> §12 records which slices closed, and [§15](#15-delivery-status-and-open-work) is the
> authoritative list of what is NOT built. Read §15 before planning work here — the
> product is usable end to end, which is not the same as the plan being finished.
>
> **User decision in this layer:** run and schedule crawls. Classification, knowledge extraction,
> gap detection, and prioritization all run automatically.
>
> **Parent architecture:** [`growth-intelligence-platform.md`](growth-intelligence-platform.md).
>
> **Outcome:** turn an owned domain and optional business context into a reproducible company
> knowledge model, an industry-aware Site Intelligence report, and a prioritized roadmap. Ship
> K-12 Education first for The Asian School, then prove reuse with a Commerce industry pack.

## 1. Scope

This plan owns:

- URL/document discovery, admission, acquisition, and lifecycle truth;
- immutable normalized page/document evidence;
- generic page understanding and knowledge projections;
- Education v1 and Commerce v1 industry packs;
- entity, schema, content, trust, journey, and internal-relationship analysis;
- Site Intelligence snapshots, scores, reports, exports, and action bundles;
- recrawl comparison and verified resolution.

It does not own prose generation, GSC/GA4 demand analysis, recurring prompt measurement, or the
Growth Agent orchestration layer. It produces typed artifacts those plans consume.

## 2. Existing foundation and required corrections

Reuse the shipped Site Health subsystem:

- URL admission, sitemap/link discovery, selection, page inventory, progressive analysis;
- SSRF-safe HTTP acquisition, curl-cffi transport, attempts, artifacts, task queue, and events;
- 15 page types, normalized page parsing, structured-data parsing, rules, issues, snapshots;
- page detail, history, SSE/polling, exports, and workspace-scoped APIs;
- automatic Opportunity recompute after terminal crawl.

Do not create another fetcher, parser, crawl queue, page-analysis owner, issue engine, or
opportunity service.

Correct these foundations before adding knowledge features:

1. task aggregates must terminalize crawl, discovery, and analysis phase state;
2. Stop/Continue controls must be idempotent and cannot report work with no non-terminal task;
3. one URL failure must not be counted twice because discover and analyze tasks both failed;
4. acquisition comments/docs must match the existing curl-capable implementation;
5. orphaned Product/Offer rules must be registered or removed;
6. irrelevant and utility pages need a first-class analysis disposition;
7. current generic `page_type` must stop carrying both structural kind and industry role.

The observed Flipkart and Cube27 crawls both reproduce stale `analysis_status=running` after
work has drained. This is a release-blocking truthfulness issue, not a UI workaround.

## 3. Target pipeline

```mermaid
flowchart LR
  Seed["Domain, sitemaps, uploads, catalog, user seeds"] --> Inventory["URL / document inventory"]
  Inventory --> Disposition["analyze | inventory_only | exclude"]
  Disposition --> Acquire["httpx -> curl-cffi -> Patchright"]
  Acquire --> Artifact["Immutable normalized evidence"]
  Artifact --> Understand["Page kind, industry role, entities, assertions, content units"]
  Understand --> Analyze["Rules, journeys, schema, trust, gaps, relationships"]
  Analyze --> Snapshot["Site Intelligence snapshot"]
  Snapshot --> Report["Complete report + action bundles"]
  Report --> Recrawl["Recrawl and compare"]
  Recrawl --> Verify["verified | partial | unresolved"]
```

Every transition records source ids and versions. Read endpoints never fetch, classify, or call
a model.

## 4. Corpus inventory and relevance

Every discovered URL receives an inventory record and a versioned disposition:

- `analyze`: relevant canonical HTML or supported document content;
- `inventory_only`: known material retained for coverage/history but not worth deep analysis;
- `exclude`: confidently irrelevant, unsafe, transactional, or duplicate material.

Disposition records `reason_code`, classifier version, signals, confidence, and override policy.
High-confidence deterministic exclusions include login/account/admin, search/facets, preview,
feeds, transactional checkout/payment paths, and non-content assets. Redirect targets,
canonicalization, duplicate clusters, and archive/history classification remain visible.

An uncertain URL is not silently discarded. It remains inventory-only or enters a bounded
review queue. The report separates inventory coverage from analyzed-content coverage.

### Document policy

HTML, PDF, and supported office documents share generic knowledge contracts but use different
extractors. Document evidence preserves:

- title, URL, media type, page count where available, content hash, and extraction coverage;
- bounded text sections/tables and source coordinates;
- publication/effective dates and historical/current status;
- linked page/entity relationships;
- extraction version and unavailable reasons.

Historical evidence never overwrites a current assertion merely because it contains a value.

## 5. Acquisition architecture

Keep `backend/app/connectors/web_evidence/` as the only acquisition boundary.

The frozen acquisition ladder is:

1. `secure_httpx` for ordinary server-rendered evidence;
2. `curl_cffi` when config-owned transport/challenge evidence justifies retry;
3. bundled headless `patchright` when server/curl evidence remains unusable or a JS shell needs
   rendering.

No real-Chrome escalation, SerpAPI, ScraperAPI, or paid acquisition vendor belongs in this plan.
The Asian School currently succeeds with ordinary HTTP; Flipkart and Myntra remain opt-in live
recovery tests, not assumptions baked into the product.

Port only the minimal generic Patchright observation capability from internal CrawlerAI behind
the existing `AcquisitionTransport` contract:

- launch/pool/context lifecycle;
- readiness and low-content-shell observation;
- bounded same-site JSON/XHR capture with redaction;
- challenge/block diagnostics;
- timeout, cleanup, and resource behavior.

Do not depend on CrawlerAI's extraction API, persistence, Celery/Redis, UI, semantic extraction,
or real-Chrome code. Record its source commit and a source-to-target manifest in the implementing
PR. Raw HTML and network payloads remain worker-memory inputs; APIs and PostgreSQL receive only
bounded normalized evidence and hashes.

## 6. Generic page and knowledge understanding

Split the current classification into two independent concepts:

- `page_kind`: stable structural role such as identity, informational, conversion, trust,
  support, listing, detail, editorial, utility, or other;
- `industry_role`: pack-defined role such as `admissions`, `curriculum`, `product_detail`, or
  `category`, nullable when no pack role applies.

Persist classifier evidence, confidence, pack id/version, and analyzer version. Deterministic
path/schema/structure signals run first. A bounded semantic analyzer may adjudicate ambiguous
roles from a frozen evidence package, but cannot invent an unsupported role.

`SitePageAnalysis` is the single page-understanding owner. Make it append-only, keyed by
`(artifact_id, analyzer_version, pack_id, pack_version)` with one `is_current` row per corpus item,
and project it as `PageUnderstanding`. Never add a competing per-page analysis table.
Required generic projections include:

- document identity, canonical/indexability, language, titles, headings, and dates;
- bounded section/content-unit tree with lists, tables, definitions, calls to action, forms,
  questions/answers, claims, citations, media, and internal links;
- normalized JSON-LD nodes, ids, types, properties, source paths, and parse errors;
- detected entities, assertions, relations, contradictions, and effective dates;
- audiences, offerings, topics, intent, journey stages, and conversion actions;
- source/rendered coverage and unavailable-source reasons;
- hashes sufficient for deterministic replay and change comparison.

`SiteFetchArtifact` remains immutable. Derived knowledge references it and records extractor,
pack, classifier, rule, analyzer, and formula versions.

## 7. Site Intelligence analysis model

### Universal dimensions

Expose stable dimension scores plus coverage:

- **Discoverability and delivery** — admission, indexability, canonical integrity, internal
  reachability, and usable acquisition;
- **Knowledge completeness** — identity, offerings, audiences, facts, relationships, and topic
  coverage;
- **Answerability** — direct questions/answers, definitions, useful structure, completeness,
  and internal supporting content;
- **Trust and evidence** — current proof, attribution, authorship, policies, citations, and
  contradiction handling;
- **Journey clarity** — stage coverage, relevant calls to action, supporting answers, and path
  continuity;
- **Machine clarity** — schema graph quality, visible/schema parity, and entity consistency.

Composites are reported over the **full** denominator with coverage shown beside them. Never
renormalize over only the observed dimensions: missing evidence correlates with weakness, so a site
with no schema graph, no policy pages, and no author attribution is missing exactly the dimensions
it would have failed, and renormalizing would score it above a site that published all three and
scored badly. Low coverage is itself the finding. An industry pack may define a versioned readiness
score, but no universal number may hide unavailable evidence.

### Findings and action bundles

Rules produce findings such as missing page, missing section, weak answer, unsupported claim,
stale/conflicting fact, duplicate/competing content, poor discoverability, schema gap, or journey
gap. Group related findings into one `OpportunityBundle` by target, role, journey, and action
family. Extend the existing Opportunity subsystem and supersede-not-mutate history.

Priority uses versioned inputs: business objective, journey stage, page/entity importance,
evidence severity, reachability, confidence, and—when Demand Intelligence lands—observed demand
and behavior. A model may explain a priority but never silently set the score.

## 8. Education v1 industry profile

### Page roles

- institution/home, about/history/vision, leadership/team;
- admissions overview, enquiry/application, procedure, selection, fees, prospectus;
- academics, curriculum, grade/class, stream/subject, calendar/syllabus;
- boarding/pastoral care, facilities, health, food, transport;
- sports, activities, school life, community service;
- results, awards, testimonials, press, events/news;
- regulatory disclosure, affiliation, policies, certificates;
- parent/student resources and historical publications;
- campus/franchise/partner content;
- editorial discovery, comparison, and guidance content.

### Entity and relationship expectations

- educational organization, campuses/locations, leadership/faculty, accreditation/affiliation;
- programs, grade ranges, curriculum/board, facilities, activities, services, fees, dates;
- audience groups including prospective parents/students and current families;
- admissions journey stages, actions, requirements, deadlines, contacts, and proof;
- current versus historical facts with explicit effective dates;
- page-to-entity, page-to-journey, question-to-answer, and evidence-to-assertion relationships.

### Analysis modules

1. **Identity consistency:** organization name, URLs, contacts, locations, leadership, logos,
   profiles, and structured-data graph.
2. **Admissions journey:** enquiry through registration, assessment, interaction, payment, and
   onboarding; supporting pages, answers, proof, and calls to action.
3. **Academic coverage:** programs, curriculum, classes/grades, streams, outcomes, calendars,
   and supporting documents.
4. **Trust and proof:** affiliation, disclosures, results, leadership, faculty, facilities,
   policies, dates, authorship, citations, and historical conflicts.
5. **Question coverage:** fees, eligibility, deadlines, boarding, safety, academics, transport,
   activities, results, location, comparisons, and parent/student concerns.
6. **Content portfolio:** overlap between institutional, conversion, support, editorial, and
   historical material; duplicate/stale/competing pages.
7. **Machine readability:** `Organization`/`EducationalOrganization`, `WebSite`, `WebPage`,
   `Article`/`BlogPosting`, `FAQPage`, `BreadcrumbList`, `Person`, `Event`, `VideoObject`, and
   visible/schema consistency where applicable.

### The Asian School evaluation and acceptance report

The Screaming Frog export supplies an external technical baseline only for fields it observed.
Reviewed fixture labels are the semantic truth for corpus disposition, generic page kind,
Education role, temporal state, entities/assertions/relations, question coverage, journey support,
and expected findings. The fixture-backed report must:

- account for the current site, separate blog, advertised and legacy sitemaps, and documents;
- classify relevant pages and confidently exclude irrelevant utility paths;
- identify malformed and contradictory structured assertions without treating historical proof
  as current truth;
- map the observed admissions funnel and supporting content;
- expose entity/topic/question coverage by education role;
- group actionable identity, admissions, schema, content, trust, and duplication work;
- propose inputs for Content and Demand Intelligence without generating or measuring them here;
- render an executive report, drill-down workspace, and reproducible export from one snapshot.

## 9. Commerce v1 industry profile — phase 2

Commerce proves that the core knowledge architecture extends beyond education. Reuse the shipped
owned/competitor catalog, discovery candidates, deterministic identity matching, frozen audit
catalog, and product-visibility projections.

### Roles and entities

- store/organization, category/collection, product detail, product family/variant;
- offer/availability, comparison, buying guide, FAQ/support, shipping/returns, review/proof;
- product, brand, identifier, attribute, variant, category, offer, policy, audience, use case,
  question, and commerce journey.

### Category/listing analysis

- stable category identity, hierarchy, breadcrumbs, pagination/facet policy;
- `CollectionPage`, `ItemList`, `BreadcrumbList`, card/item/order consistency;
- category definition, audience/use-case guidance, selection criteria, attribute coverage,
  comparisons, FAQs, and guides;
- product reachability, catalog products without discoverable PDPs, duplicate categories, and
  competing intent.

### PDP analysis

- `Product`, `Offer`/`AggregateOffer`, identifiers, brand, variants, images, price/currency,
  availability, ratings/reviews, shipping, and returns;
- visible/schema/catalog parity for populated claims;
- answer-first summary, description, specifications/ingredients/materials, intended use,
  instructions, safety/limitations, evidence, comparison context, FAQs, and supporting links;
- duplicate, boilerplate, stale, gated, or client-only evidence;
- category, guide, policy, comparison, and related-product relationships.

### Commerce acceptance

Use synthetic fixtures plus opt-in representative merchant sites. A toothpaste brand remains a
useful fixture, but not the product's primary story. The pack must classify category/PDP/support
roles, validate facts without invention, bind catalog identity deterministically, create grouped
actions, and emit artifacts consumable by the same Content and Demand plans.

## 10. Persistence and contracts

Prefer extensions to current rows and add only contracts without an existing owner:

- extend `SiteCrawl.configuration` with acquisition policy and frozen registry/core/module/industry-profile snapshots;
- extend `SiteUrl`/observation projections with disposition and document metadata;
- extend the append-only `SitePageAnalysis` with page kind, industry role, content/knowledge/schema/journey
  summaries, coverage, and component scores;
- extend `SiteHealthSnapshot` into the versioned Site Intelligence projection;
- add generic knowledge entity/assertion/relation projections only after proving they cannot be
  represented cleanly by current immutable artifacts and analyses;
- add a deterministic commerce page-to-catalog link where catalog identity is required;
- continue using `SiteRuleEvaluation`, `SiteIssue`, `Opportunity`, and `OpportunitySnapshot`.

All new ids are UUIDs; rows are project/workspace scoped; versions and source ids are mandatory.
Schema changes remain in `0001_initial` while the product is pre-launch.

## 11. API and frontend

Retain `/site-health` URLs for compatibility while the navigation label becomes **Site
Intelligence**.

Primary projection:

- `GET /projects/{id}/site-intelligence?crawl_id=` — snapshot, coverage, scores, changes,
  pack identity, top bundles, and report metadata.

Supporting projections:

- inventory/pages with disposition, kind, role, entity, journey, and scores;
- knowledge/entities/assertions/contradictions;
- schema graph and visible parity;
- journeys and supporting content;
- findings/action bundles and evidence;
- crawl/report comparison and export.

The workspace panels are Overview, Pages, Knowledge, Schema, Journeys, and Evidence. One shared
crawl selector controls every panel. Only one panel renders at a time, tab state mirrors to the
URL, counts come from server projections, and every finding drills into persisted evidence.

## 12. Implementation slices and gates

### S0 — Lifecycle, registry, and contract reconciliation ✅ shipped

- fix phase/task terminal truth, failed-count integrity, and idempotent controls;
- activate the one config-owned industry registry with structural, cross-reference, and maturity
  validation; preserve the current onboarding compatibility projection;
- update canonical docs and active rule catalogs;
- capture Education, Commerce, curl-recovered, JS-shell, malformed-schema, duplicate, and
  historical-document fixtures.

**Gate:** no drained task set renders live; fixtures define expected inventory and evidence.

### S1 — Acquisition and corpus inventory ✅ shipped

- harden curl-cffi; port bounded Patchright; remove ScraperAPI-specific code and configuration;
- implement disposition and document-aware inventory;
- freeze acquisition/engine versions and safe diagnostics.

**Gate:** representative fixtures replay deterministically; optional Flipkart/Myntra tests use no
paid vendor or real Chrome.

### S2 — Generic knowledge contracts ✅ shipped

- extend normalized artifacts and analyses;
- split page kind from industry role;
- add entities, assertions, relations, content units, contradictions, dates, and coverage;
- implement dimension scores and snapshot versioning.

**Gate:** identical artifacts reproduce identical working knowledge and scores.

### S3 — Education v1 and complete report ✅ shipped

- activate the validated Education profile from the shared registry, including classifiers, rules,
  questions/FAQs, journeys, report modules, and labelled fixtures;
- build The Asian School inventory, snapshot, action bundles, report, and export;
- add the Site Intelligence workspace.

**Gate:** the acceptance report answers the contract in §8 with traceable evidence and no live
provider calls from read endpoints.

### S4 — Commerce v1 ✅ shipped

- register existing Product/Offer rules;
- activate the validated Commerce profile and its category/PDP/FAQ/policy roles plus catalog binding;
- emit the same knowledge, finding, action, and snapshot contracts.

**Gate:** commerce introduces no second knowledge model, fetcher, queue, or content pipeline.

### S5 — Recrawl comparison and rollout ❌ not started

- compare compatible assertions, rules, journeys, and scores;
- resolve action bundles only from observed passing evidence;
- calibrate packs on representative fixtures and opt-in live sites.

**Gate:** before/after reports remain reproducible and earlier snapshots stay immutable.

## 13. Verification

- unit tests for disposition, page kind/role, entity/assertion extraction, schema graph,
  contradiction handling, journey analysis, rules, scores, and pack compatibility;
- component tests for lifecycle, queue leases, persistence/provenance, APIs, workspace isolation,
  reports, exports, and comparison;
- frontend tests for tabs, URL state, null/coverage display, evidence drilldowns, and active-state
  convergence;
- migration reset, `alembic upgrade head`, `alembic check`, targeted Ruff, Vitest, lint, and
  build;
- CI uses redacted fixtures; live site and protected-site acceptance remains opt-in.

## 14. Handoff rule

An implementation session starts at S0 and closes only one gated slice at a time. It must inspect
the current owner before adding a type or table, update the canonical subsystem docs with shipped
behavior, and leave later slices as plans rather than partial hidden implementations.

## 15. Delivery status and open work

### Delivered

| Slice | State | Landed in |
| --- | --- | --- |
| S0 — lifecycle, registry, contract reconciliation | ✅ complete | #53 |
| S1 — acquisition and corpus inventory | ✅ complete | #53, #55 |
| S2 — generic knowledge contracts | ✅ complete | #53, #55 |
| S3 — Education v1 and complete report | ✅ complete | #52, #53 |
| S4 — Commerce v1 | ✅ complete | #53 |
| S5 — recrawl comparison and rollout | ❌ **not started** | — |

The registry ships **16 industry packs**, not the two this plan scoped: `education` and
`commerce` are the calibrated pair the acceptance work used, and the other fourteen
(`automotive`, `financial_services`, `general_business`, `healthcare`, `hospitality`,
`local_services`, `manufacturing`, `media_publishing`, `nonprofit`, `professional_services`,
`real_estate`, `recruiting_staffing`, `restaurants`, `saas`) are structurally validated but
have **not** been calibrated against a live corpus. Treat their role classifiers and question
contracts as unproven until one is.

### Open work

**1. Contradiction review — clauses 3–6. Blocked on Demand Intelligence.**

Only clauses 1–2 of the [contradiction policy](knowledge-kernel-and-industry-pack-spec.md#contradiction-policy)
ship: disputes are detected, every side is preserved, and a shared group is assigned. Clauses
3–6 — blocking publication as current truth, preferring no answer over an invented resolution,
and the reviewer flow to approve one side, narrow its scope, mark it historical, or reject both
— are **not implemented**. Every assertion stays `observed`; there is no review state a person
can move it to.

This cannot be closed inside this plan. A reviewer flow needs the approved-memory tables and
the human-review surface that [`demand-intelligence.md`](demand-intelligence.md) introduces, so
it sequences **after** that plan, not before. Anyone reading §7 or the spec's contradiction
section should read this note first: an earlier draft of both described the policy as if it had
shipped whole.

**2. S5 — recrawl comparison and verified resolution.** No snapshot-to-snapshot comparison, no
`verified | partial | unresolved` resolution of action bundles. Snapshots are immutable and
individually reproducible, so the data needed for this exists; nothing consumes it yet.

**3. Uncalibrated packs.** See the table note above.

### Gotchas for the next implementer

These are live constraints that cost real debugging. Changing any of them silently changes what
the product publishes.

- **A role's FIRST entity type is its subject; the rest are types the page may only MENTION.**
  `entity_type_ids[0]` is load-bearing in three places (`_primary_type_id`, page-subject minting,
  money binding). Treating any declared type as the subject let a schema-declared place or offer
  — identity-keyed by its own name rather than the page — capture every amount on the page.
- **Text-sanitization order is a correctness property, not style.** `readable_text_length` must
  remove CLOSED non-text subtrees, then comments, then unterminated subtrees. Comments-first let
  a bare `<!--` inside a JavaScript string literal discard the rest of the document, reporting a
  content-rich page as a zero-text "JS shell" and escalating it to a browser render.
- **Ambiguous currency notation is never resolved.** `Rs`, `Rs.`, and `₨` are all deliberately
  absent from both the symbol map and the parser's pattern: each is shared by four rupees, and
  guessing one publishes a fabricated fact. Only country-specific marks (`₹`) resolve.
- **Money amounts must be finite.** Python's JSON decoder accepts `NaN`/`Infinity`, and `bool` is
  a subclass of `int`, so an unguarded numeric check published `true` as a fee of 1.00 and `NaN`
  as "INR nan".
- **Coverage, journeys, and dimension scores are a bounded JSONB projection on
  `SiteHealthSnapshot`, not tables.** Likewise there is deliberately no contradiction-group
  table: the group is a deterministic UUID derived from `(crawl, subject, predicate, scope)`.
- **`projection_version` is a digest of every input version**, not a hand-bumped constant, so a
  changed input cannot be served from a stale projection.
- **Read endpoints never fetch, classify, or call a model.** This is the §3 rule and it still
  holds; a reader that needs new data needs a new worker phase, not a live call.
