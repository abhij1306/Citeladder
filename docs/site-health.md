# Site Health runtime

> **Status:** current authority for the crawler, page analysis, issues, and
> site-facing product surfaces.

Site Health is CiteLadder's only owner of URL discovery, secure acquisition,
immutable fetch evidence, normalized page facts, structural page-kind
classification, deterministic rule evaluation, scores, grouped issues,
snapshots, exports, and site-derived opportunities.

Within the product loop, Site Health powers Website and Issues in Analyze and
supplies persisted evidence to Act and Improve / Verify. This framing does not
change crawler ownership, URL identity, or the rule and scoring contracts.

Demand's cross-source page-equivalence resolver consumes Site Health evidence
without changing `canonicalize()`, `canonical_identity()`, `url_hash`, or
`SiteUrl`. Scheme, `www`, and trailing-slash variants therefore remain distinct
crawler identities even when external evidence later resolves them for a join.

The user-facing area has three pages:

1. **Site Health** — persisted measurement Overview, crawl lifecycle, scores by
   page kind, and URL inventory, with **Overview**, **Pages**, **Architecture**,
   **AEO Readiness**, and **Changes** tabs.
2. **Issues** — grouped findings with affected page-kind badges.
3. **Opportunities** — persisted prioritized actions.

The removed Site Intelligence workspace and industry-pack/knowledge subsystems
must not be reintroduced as parallel owners. Site Health owns one persisted
observed-architecture projection whose read surface exposes observed page kinds
and hierarchy only.

## Pipeline

```text
explicit user Run new crawl
  -> durable root acquisition ───────────────┐
  -> durable site setup -> sitemap admission ├─> discovery convergence
                                             ┘
  -> internal-link frontier and corpus disposition
  -> SSRF-pinned curl_cffi acquisition
  -> immutable fetch attempt and artifact
  -> bounded normalized HTML/delivery/structured-data facts
  -> deterministic page_kind assessment
  -> page-kind-scoped rule evaluations and scores
  -> grouped issues, snapshot, exports, opportunities
```

Read endpoints only render persisted projections. They never crawl, classify,
repair lifecycle state, or call a model.

## Crawl guarantees

- A crawl begins only when the user explicitly chooses **Run new crawl**.
  Discovery and analysis are durable internal phases of that one crawl, not
  separately user-startable operations.
- URL safety and redirect targets are validated at the acquisition boundary.
- Discovery and analysis use PostgreSQL tasks with leases, retries,
  heartbeats, idempotent terminalization, and cancellation.
- Root acquisition and site setup are independent durable tasks on that same
  queue. Site setup owns robots/AI-crawler facts, llms.txt, and the bounded
  sitemap walk; root acquisition can fetch and expand internal links beside it.
  Discovery completes only after both branches and their admitted frontier
  drain. Root analysis waits for committed site facts so site-root rules never
  race the setup branch.
- Acquisition and processing lanes share idle capacity under one global
  concurrency ceiling and the shared host gate; discovery retains reserved
  acquisition capacity during analysis bursts.
- As admissible pages arrive, analysis is automatically enqueued and progresses
  alongside discovery. The frozen entitlement/runtime allowance still bounds
  which pages may be analyzed; discovery never turns an unentitled inventory
  row into analysis work.
- Every run advances through discovery, analysis, snapshot creation, and
  terminal completion. Advanced seed, page-kind, and limit inputs alter the
  crawl plan without creating a second lifecycle. `input_mode=auto` is a
  request-mode token, not scheduled crawling.
- Discovery completion never opens a page-selection or separate analysis step.
  The live results surface stays mounted until the crawl terminalizes.
- Sitemap frontier and observation writes are bounded batches. Secure connection
  pools may be reused by original origin without bypassing per-request DNS,
  pinned-IP, redirect, robots, or host-gate checks.
- Fetch attempts and artifacts are append-only; secrets and unsafe response
  headers are never persisted.
- Discovery freezes complete versioned facts on the immutable artifact;
  analysis reuses a compatible artifact or performs the normal secure fallback.
  A race with active discovery is durably deferred without spending a network
  attempt. Fetch attempts retain bounded delivery/error provenance, and `429`
  cooldowns gate new host starts.
- Anchor extraction may repair an encoded query delimiter only at a boundary
  whose first suffix key is a config-owned tracking parameter. The observation
  freezes the rewrite reason/version; legitimate reserved path escapes remain
  byte-preserving crawler identity.
- `analyze`, `inventory_only`, and `exclude` dispositions stay distinct.
- Supported office/PDF/Markdown documents are successful inventory evidence
  and never enter the HTML rule evaluator. A response whose recognized media
  type reveals an extensionless document is reprojected the same way.
- Declared canonicals remain observed evidence and never replace crawler URL
  identity. An in-scope canonical may key the Commerce projection; an
  automatically selected alias is skipped only when that canonical URL was
  also admitted to the same crawl. Explicit user selections are not collapsed.
- The screen phase is resolved once by the backend. Worker bookkeeping states
  are not independently reinterpreted by the frontend.

## Crawl controls, limits, and progressive UI

The production path is one standard crawl: its default is **50** and paid-plan
allowances remain entitlement-owned. The technical/development requested-page
ceiling is **500**; using it requires the existing audited operator override on
the dev/demo workspace. Advanced input, seed, and page-kind controls are
development-only; their separate discovery and analysis safety ceilings remain
**50,000**. These are configuration-owned operational bounds, not throughput
promises.

Before any crawl, Site Health shows one empty placeholder with **Run new
crawl**. Once a crawl exists, the header exposes one contextual primary control:
**Stop crawl** while its persisted status is active, otherwise **Run new
crawl**. **Export** is secondary. There are no separate user controls for
discovery or analysis. A paused historical crawl remains eligible for **Run
new crawl**; read endpoints never repair or reinterpret its persisted state.

The inventory stays mounted as the crawl progresses. During discovery it shows
the first ten persisted rows as they arrive; once scoring is available, those
same persisted rows enrich in place rather than moving the user to a separate
analysis screen. Issue rows use the persisted rule description as the
plain-language problem subtitle; remediation remains separate fix guidance.

Live analysis progress is a persisted task projection. It reports successful,
queued, running, blocked, and failed counts plus the explicit
`robots_denied`, `http_4xx`, `http_5xx`, and `timeout` breakdown. Activity is
`working`, `waiting`, `stalled`, or `terminal`: a healthy leased task waiting
for its host slot is `waiting/host_gate`; a future `available_at` is
`waiting/retry_backoff`; only an expired lease is `stalled/expired_lease`.
Lease ownership/expiry and durable queue availability—not elapsed browser
time—own those states. Terminal failures therefore count as progress and a
robots-blocked URL is visible instead of leaving the counter apparently frozen.

The first active page-table view reads completed persisted projections as
**Audited so far**, so pre-seeded monitored URLs do not appear as one immediate
pending burst. The full discovered inventory remains an explicit adjacent view,
and terminal crawls restore the complete monitored page view.

Terminal evidence refresh follows one transactionally idempotent DAG for
completed, partially completed, and cancelled-after-analysis crawls. Usable
evidence first enqueues the immutable change snapshot. Only after Change
Intelligence commits does a current Traffic
snapshot route through Demand and then Opportunities; without Traffic input,
the change snapshot routes directly to Opportunities. Successors never race
their change predecessors, and retries cannot duplicate a logical
refresh. A completed or partially completed crawl with zero successful HTML
analyses skips both projections but carries its crawl identity through the same
bounded downstream path so stale Site Opportunities are superseded. A
cancellation before any usable analysis enqueues none.

Every terminal crawl snapshot freezes a conservative coverage state:
`complete`, `partial`, or `unknown`, with a formula version and bounded reason
evidence. Complete requires a successfully exhausted discovery frontier below
the frozen page/frontier limits. A reached budget, pending frontier, bounded
sample/manual/rerun, or cancellation is partial. A discovery failure without a
limit signal is unknown. The older `inventory_complete` presentation field is
not evidence of complete site coverage.

Successful terminal crawls also enqueue a retryable internal-link projection
outside crawl finalization. It builds a transient graph from persisted current
analysis artifacts and stores one versioned `SitePageLinkMetric` per crawled
page: inbound/outbound and main-content counts, nofollow inbound count,
ordinary followable-link depth from home, bounded top neighbours, exact source
artifact IDs, and formula/extractor versions. Raw edges, PageRank, and authority
scores are not persisted.

After link metrics commit, a second idempotent post-terminal task derives one
immutable `SiteObservedArchitecture` per crawl and processing-version tuple. It
performs no acquisition and no model call. The projection freezes exact analysis, artifact,
indexability-evaluation, and link-metric IDs plus extractor, analyzer, rule,
architecture-formula, and archetype-policy versions.
Each structural rule evaluation references that exact architecture projection,
so a later formula or policy version persists independent replayable results.

### Page-kind classification

`page_kind` is the only user-facing term for a page's structural purpose.
"Page family" is not a second concept or a URL-pattern group. Every analyzed
URL has exactly one persisted `page_kind`; when the evidence cannot support a
specific kind, the classifier deliberately assigns `other` rather than forcing
a guess. Architecture groups pages by that persisted value, so one unusual URL
cannot appear as a one-page family merely because its path is unique.

The bounded taxonomy is `homepage`, `product`, `category`, `service`, `local`,
`article`, `guide`, `docs`, `pricing`, `faq`, `about_contact`, `comparison`,
`case_study_review`, `trust_policy`, and `other`. `category` is the listing or
hub kind for repeated collections of products or other navigable results. The
taxonomy stays intentionally broad enough for stable audits across industries;
new kinds require a distinct checklist or recommendation contract, not only a
new URL vocabulary.

Classification is deterministic and uses this precedence:

1. Normalize the canonical URL before classification. Host casing, fragments,
   trailing slashes, default index documents, duplicate query parameters, and
   tracking parameters cannot create different classifications. Meaningful
   routing parameters remain available as evidence.
2. Prefer page-owned structural evidence. A primary product entity requires
   facts such as a buy box, offer, SKU, price, availability, or variants outside
   repeated cards. A `category` requires a substantial repeated-card collection
   supported by result counts, sorting, filtering, facets, or pagination. A
   single location entity requires its own address/location evidence. Repeated
   recommendation cards in an article or product page do not make it a listing.
3. Apply high-confidence route evidence: `/` is `homepage`; product, collection,
   service, location, guide, comparison, pricing, documentation, FAQ,
   about/contact, case-study/review, and legal/policy route vocabularies map to
   their corresponding fixed kinds. Archive roots such as `/blog` or `/news`
   require listing structure, while their detail descendants remain `article`.
4. Use visible semantic evidence only when stronger evidence is absent. The
   title, H1, final slug, question-heading structure, author/date evidence, and
   bounded main-content heuristics may resolve an otherwise ambiguous page.
5. Treat structured data as corroboration, never self-certification. Schema is
   the page's claim about itself and cannot alone select the kind whose expected
   schema will subsequently be audited. Globally injected `Organization`,
   `WebSite`, or breadcrumb markup never classifies every page.
6. If the strongest tier contains conflicting kinds, or schema is the only
   signal, abstain to `other`. Persist the deciding signal, alternatives,
   conflicts, confidence label, and reason so the result remains explainable.

The classifier uses evidence tiers rather than adding unrelated signal weights.
Several weak hints therefore cannot outvote one page-owned structural fact, and
confidence is the explainable label `high`, `medium`, `low`, or `unknown`, not
an uncalibrated probability. An LLM does not classify page kinds in the shipped
runtime. A future bounded ambiguity resolver may choose only from the fixed
taxonomy and may not override deterministic evidence or invent a kind.

URL templates such as `/products/{slug}` may be retained later as internal
template evidence for template-wide defect analysis, but a template is not a
page kind and is not the primary Architecture grouping. Template clustering is
deferred until its DOM/schema/heading fingerprint, provenance, and confidence
contract are specified; a last-segment wildcard alone is insufficient.

Parent evidence resolves in strict order: visible breadcrumb links, explicit
`BreadcrumbList`/`isPartOf` relationships, a crawled immediate URL parent whose
page kind can safely act as a hub, then `unknown`. Cross-links never manufacture
a parent.

The archetype can only be mapped from a sufficiently grounded onboarding
`business_model`; an absent/weak profile or materially contradictory crawl
abstains to `other`. Crawl evidence may veto but never assign an archetype.
Common structures not observed are suppressed unless coverage is complete.

### Architecture read surface

The Architecture tab groups the observed URLs by `page_kind`. Each row exposes
the kind, page count, median observed depth, indexable count, duplicate metadata
count, and—only for complete coverage—orphan count; its assigned URL list is
disclosed on demand. There is no URL-pattern "family" column and no "type mix."

The same tab renders the persisted observed hierarchy beneath that ledger.
Nodes are nested only by their returned `parent_site_url_id`, and each
relationship names its persisted `parent_source`: visible breadcrumb, explicit
structure, safe immediate URL parent, or unresolved. The browser does not infer
parents from links or paths; a missing or unresolved parent stays at the root.

Two persisted summaries lead the tab. Internal linking reports the
total observed internal links, the count and percentage of observed pages with
at least one incoming link, and the orphan count when complete coverage permits
that absence claim. Structure depth reports page counts and percentages for
depth 0, depth 1, depth 2, and depth 3+, plus the number of pages whose depth was
not measured. Percentages use only pages with measured depth as their
denominator. The summaries link into the existing server-sorted Pages inventory
by inbound-link count or measured depth. No second report store or workspace is
created.

Architecture health is a state, not a synthesized score. An observed
indexability blocker is `Blocked`; an observed duplicate-metadata, orphan, or
excessive-depth defect is `Needs work`; no observed defect with incomplete
crawl/architecture evidence is `Limited evidence`; only sufficient evidence
without one of those findings is `Good`.

`GET /api/v1/projects/{project_id}/site-health/architecture` projects the newest
persisted model for the selected (or latest usable) crawl. It never re-derives
the model, crawls, or scores. The response carries `coverage_state` alongside
every site-level number, the page-kind rows, the hierarchy nodes with their
`parent_source`, the architecture formula version of the row it actually read,
and a plain-language `limitations` line whenever coverage is not `complete`. A
crawl with no persisted model returns `state:
"unavailable"` with a reason rather than an empty tree.

There is no archetype correction endpoint, mutable archetype override, or
archetype advisory block in the response.

`GET /api/v1/site-crawls/{crawl_id}/export.md?view=architecture` renders the
observed tree as Markdown with an ASCII tree; large sibling sets collapse to one
`[N kind]` count line. The CSV export rejects the view — a tree is not a table.

### Pages sorting and internal links

The pages list accepts `sort=url|inbound|main_content_inbound|depth`. Non-default
sorts keyset-page over `(metric_value, site_url_id)` against this crawl's
`SitePageLinkMetric` rows; the sort is part of the cursor fingerprint, so a
cursor cannot be replayed under a different ordering (400). Page rows and page
detail both carry the crawl's persisted link metrics, and detail adds bounded
top inbound/outbound neighbours. A URL with no metric row reports `null`, never
`0`: unmeasured and unlinked are different facts, and the UI renders the
not-measured placeholder for the former. Persisted analysis status and page-kind
filters are applied before keyset pagination, so a page of completed results is
never thinned by unfinished URLs that happen to sort earlier.

## AEO Readiness

`GET /api/v1/projects/{project_id}/site-health/aeo-readiness` is a read-only
presentation projection frozen in the immutable selected-crawl snapshot. The
snapshot stores its score, coverage, state, ordered dimensions, family and
checkpoint counts, bounded page evidence, limitations, versions, classification
projection, scored-kind composition, and exact source provenance together.
Optional `crawl_id` selects one usable terminal crawl; omission selects the
latest. The main read never reopens current analyses or evaluations, so later
current-row changes cannot rewrite historical diagnostics. Raw rows remain
available only to re-authorize the bounded per-page Content handoff. Reads never
analyze, enqueue, repair, or call a provider.

The version-`1` PR4 measurement manifest maps only defensible score-applicable
checkpoints into seven ordered dimensions: **Answerability**, **Structure**,
**Evidence**, **Machine readability**, **Provenance & trust signals**,
**Freshness**, and **Crawlability**. The stable machine key for Provenance &
trust signals remains `authority`.

Each dimension is frozen in capability-family terms: applicability, measurement
state, family-normalized score and coverage, expected and determinate weight,
six-outcome checkpoint counts, catalog guidance, and a bounded set of failing
pages. The bound always travels with the true failing-page total. Request-time
reads use the snapshot projection only; they never calculate or repair
measurement.

## Overview presentation

Overview has one live-data subscription: the screen's polling dashboard. Its
mounted metrics read the persisted `SiteCrawl.score_summary` while a crawl is
active and switch to the immutable terminal snapshot after terminalization.
Both projections are written by the same aggregation owner; reads never derive,
repair, or reconcile either projection.

Overview presents four distinct facts: AEO Readiness is quality for classified
audited pages, AEO Measurement Coverage is determinate expected evidence for
that classified cohort, Classification Coverage is the classified share of
classification-expected supported HTML, and Crawl Coverage describes the
selected discovery/acquisition/analysis boundary. Classification, AEO
measurement, and crawl coverage are separate persisted projections and never
substitute for or multiply one another.

When classification is incomplete, the score title is **Readiness of classified
audited pages** and the classification and measurement coverage lines remain
adjacent and visible above the fold. Incomplete crawl coverage adds its own
audited-pages qualifier and crawl-coverage line. A present score always renders
with its measurement state and coverage. A page whose kind is `other` renders
**Not measured** with a null AEO score and coverage, never a generic `WebPage`
result or an appended internal classification reason.

Web Fundamentals and AEO Readiness render a non-null score in `measured` and
`limited_evidence` states. When no measurable expected evidence exists, the
score/`overall_readiness` is null and the UI renders the explicit state rather
than manufacturing zero or 100. The seven AEO rows render the persisted label,
description, family-normalized score, coverage, and bounded evidence. A
site-scoped family is labelled as site evidence rather than inherited into a
page score.

The snapshot retains ten ranked issues; Overview returns the first five. Its
metric counts are frozen separately: Web Fundamentals counts include defect
findings with the `web_fundamentals` score role, while AEO gap counts include
readiness-role findings. Site-scoped evidence never fabricates an affected
page. Overview maps every persisted impact band to **High**, **Medium**, or
**Low**. Advisory bands are derived from the persisted readiness dimension and
family budget, never borrowed severity, but the dimension itself is not shown
as the impact label. Rows link to the URL-backed Issues filter as
`/issues?rule=<rule_id>`.

Web Fundamentals renders its four persisted areas—Accessibility, Mobile,
Security, and Lab—with independent states and retains the evidence drawer.
Trend is a bounded series of at most 12 version-compatible terminal snapshots;
without a comparable predecessor it remains unavailable. Change summary
renders persisted directional deltas and their comparability reason.

## Shipped measurement contract

This section is the canonical logic for the active PR4 measurement contract.
The reliability implementation contract and remaining completion gates live in
[`plans/site-health-measurement-reliability-pr4.md`](plans/site-health-measurement-reliability-pr4.md);
the PR1–PR3 cutover plan is a historical delivery record. This file owns shipped
measurement meaning and formulas.

**Development reset policy.** CiteLadder is pre-launch and does not preserve
development database history. Schema changes are folded into
`migrations/versions/0001_initial.py`, reset the disposable development
database, and rebuild observations with the current code. Migration, extractor,
classifier, trait, analyzer, rule, profile, schema, scoring, coverage,
link-metric, architecture, archetype, and presentation version fields remain
present for provenance but
their active development value is always `1`. Do not add a `0002+`, increment a
semantic version, backfill old analyses, or build compatibility/recalibration
paths while this policy holds. Historical preservation and version increments
begin only after a separate production-history decision.

CiteLadder owns this measurement policy. Search-engine documentation, research,
commercial audit products, the current database, and public-page crawls are
evidence inputs—not authorities for the product formula. Engine documentation
is used only for engine-specific facts, such as crawler names, directives, and
feature requirements. The policy measures observable eligibility and
page-purpose completeness; it never claims that a crawler can prove authority,
truth, ranking, grounding, or citation likelihood.

### Measurement layers

Site Health separates five facts that a Combined percentage cannot represent:

1. **Search eligibility** is a gate/state: `eligible`, `blocked`, `unknown`, or
   `excluded`. A critical acquisition or indexability failure must not be
   diluted by unrelated passes.
2. **Web Fundamentals** is a 0–100 correctness score over deterministically
   evaluated objective defects, always paired with evidence coverage.
3. **AEO Readiness** is a separate 0–100 capability score over applicable,
   deterministic optimization signals. It may credit both satisfied defects
   and satisfied advisories without turning an advisory absence into an
   objective fault or eligibility failure.
4. **Web Fundamentals** is a separate accessibility, mobile, security, and
   page-experience projection persisted from bounded HTML, asset, delivery, and
   response-header evidence. Its objective HTML defects also participate in
   Web Fundamentals, so a displayed Web Fundamentals issue lowers that
   score. The projection has no second fabricated composite score. Browser
   layout, runtime DOM, touch targets, and field LCP/INP/CLS remain explicitly
   unavailable until a persisted browser or field-data provider exists; HTTP
   lab diagnostics never impersonate field Core Web Vitals.
5. **Observed AI Visibility** remains the outcome metric: comparable observed
   mentions and citations. It is not inferred from Site Health readiness.

### Search eligibility contract

Search eligibility is a persisted gate, not a score and not a field owned only
by successful HTML analysis. The complete target config-owned
`SEARCH_ELIGIBILITY_CRITICAL_CHECKPOINTS_1` set contains:

| Checkpoint | Evidence owner | Target decision |
|---|---|---|
| `acquisition.public_representation` | Intended-public URL disposition, terminal acquisition task, fetch attempt, and supported representation | A determinate fetch/representation blocker yields `blocked`; missing terminal evidence yields `unknown` |
| `search.indexability` | `technical.indexable` and its declared-intent evidence | A proven intended-public contradiction yields `blocked`; deliberate exclusion yields `excluded`; unresolved intent yields `unknown` |
Crawler and snippet access remain supplemental evidence and readiness
checkpoints; they do not hold completed search-eligibility rows in `unknown`.
A checkpoint enters the critical set only when its evaluator can produce both
a determinate healthy state and a determinate blocker state. An
unevaluable critical checkpoint must never make `eligible` unreachable by
construction.

The snapshot finalizer freezes the gate once from persisted acquisition,
artifact, evaluation, and declared-intent evidence. It stores the overall state,
per-state page totals, per-checkpoint reason totals, and exact source task,
attempt, artifact, analysis, and evaluation IDs. A blocked URL may have no
`SitePageAnalysis`, so eligibility cannot be inferred solely from that model.
Overview reads the persisted snapshot projection and never derives eligibility
at request time.

For the selected intended-public cohort, any determinate critical contradiction
makes the aggregate `blocked`. With no blocker, an expected critical checkpoint
whose outcome is `unknown` or `error` makes the gate `unknown`; unavailable,
ambiguous, and conflicting evidence remain bounded reasons under `unknown`.
`eligible` requires every expected critical checkpoint to be determinate with no
blocker. `excluded` requires the declared audit intent to exclude the entire
selected cohort. Counts and reason groups remain visible beside the headline.

The design separates finding meaning, score ownership, and the two kinds of
applicability:

```text
finding_class = defect | advisory | diagnostic
score_roles   = {web_fundamentals, aeo_readiness} | none
display_applicability = may this finding be shown as contextual guidance?
score_applicability   = is evidence strong enough to alter a score?
```

`finding_class` answers whether an absent or failed checkpoint is objectively
wrong, an optimization opportunity, or neutral diagnostic evidence.
`score_roles` answers which measurement the checkpoint informs. Only defects
may affect Web Fundamentals. An applicable defect or advisory may affect
AEO Readiness when it represents a declared readiness capability. Diagnostics
never score. Weak page-kind or trait evidence may permit a conditional advisory
to be displayed, but it cannot satisfy `score_applicability`. Expectation-based
defects and advisories alter scores only when page-owned structure, an
independently proven trait, or a triggered present artifact establishes the
applicability contract. This prevents weak classification from altering a score
without suppressing useful guidance.

Vendor-specific recommendations such as `llms.txt` or special AI markup receive
no core readiness credit unless CiteLadder adopts a deterministic capability in
configuration.

The target AEO Readiness score retains seven visible dimensions with
config-owned v1 weights. Their stable machine keys are `answerability`,
`structure`, `evidence`, `machine-readability`, `authority`, `freshness`, and
`crawlability`. The `authority` key remains stable across persistence, API, and
frontend contracts; its target display label is **Provenance & trust signals**
so the UI does not imply that a crawler proved authority.

| Dimension | Weight | Capability measured |
|---|---:|---|
| Answerability | 20% | Purpose-essential facts and direct, extractable answers or definitions where the page purpose warrants them |
| Structure | 15% | Semantic organization, descriptive headings, meaningful lists/tables, and recoverable content hierarchy |
| Evidence | 15% | Attributed sources, concrete support, and methodology/evidence patterns where applicable |
| Machine readability | 20% | Rendered text, valid structured representations, entity clarity, and schema/content parity |
| Provenance & trust signals | 10% | Named creator/organization and transparent provenance or credentials where relevant; never a claim that the crawler proved authority |
| Freshness | 5% | Accurate publication/update/version signals where freshness matters |
| Crawlability | 15% | Search/citation crawler access, discoverability, crawlable links, and relevant directives |

The weights are CiteLadder measurement policy, not a search-engine formula.
They are config-owned under the active development policy identifier `1` and
calibrated against fixtures and real pages without tuning toward a preferred
score distribution.

### Universal checkpoint baseline

`Defect` below means an objective failure only when the stated intent and
evidence make the checkpoint applicable. `Advisory` means a deterministic
optimization opportunity, not that it is necessarily absent from AEO
Readiness. The registry assigns score roles independently. `Unknown` is
expected-but-unmeasured and lowers coverage, never passes or fails.

| Area | Target checkpoint | Classification and applicability |
|---|---|---|
| Access | Final response succeeds and contains a supported public representation | Defect for intended-public pages. Private, authenticated, or deliberately excluded pages are `excluded`, not unhealthy. Google requires crawl access, HTTP 200, and indexable content ([technical requirements](https://developers.google.com/search/docs/essentials/technical)). |
| Crawler policy | Search/citation crawlers are not accidentally blocked | Defect only against declared visibility intent. Googlebot/Bingbot and OAI-SearchBot are distinct from training crawlers such as GPTBot; policy choices must not be collapsed ([OpenAI crawlers](https://developers.openai.com/api/docs/bots)). |
| Index and preview controls | `noindex`, `nosnippet`, `max-snippet`, `data-nosnippet`, `nocache`, and `noarchive` agree with intent | Defect on a proven contradiction, unknown when intent is absent. Snippet controls also affect Google AI features; Bing cache/archive controls can limit Copilot grounding depth. |
| Primary content | Main content exists in the rendered/indexable result and is not available only after click, scroll, CAPTCHA, or consent redirection | Defect when observed absent or interaction-only. Initial server HTML is a compatibility advisory, not a universal Google requirement; Google can render JavaScript but does not interact to reveal content ([JavaScript SEO](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics), [lazy loading](https://developers.google.com/search/docs/crawling-indexing/javascript/lazy-loading)). |
| Page identity | A descriptive title and unambiguous visible main title identify the primary topic | Defect for missing or non-descriptive identity. No title character band and no exact-one-H1 rule is scored ([title links](https://developers.google.com/search/docs/appearance/title-link)). |
| Semantic structure | Main content, headings, labels, relationships, and meaningful sequence are programmatically determinable | Web Fundamentals defect where deterministic. A logical heading hierarchy matters; mechanically requiring one H1 does not. |
| Internal discovery | Important destinations use crawlable `<a href>` links and fetched internal targets resolve | Page defect for a broken present link; crawl/cluster defect for undiscoverable intended pages. Orphan absence claims require complete coverage ([crawlable links](https://developers.google.com/search/docs/crawling-indexing/links-crawlable)). |
| Canonical integrity | A present canonical is parseable, resolvable, and consistent with redirects, sitemaps, hreflang, and its duplicate cluster | Contradiction is a defect; absence is advisory because Google can select a canonical without a declaration ([canonical guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)). |
| Structured-data integrity | Present markup parses, describes visible main content, uses the opted-in feature contract, and does not contradict visible facts | Invalid, misleading, hidden, or contradictory markup is a defect. Absence is advisory. Required fields are keyed by publisher + feature + schema type, not generic Schema.org vocabulary ([structured-data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)). |
| Site/cluster controls | Pagination, facets, sitemaps, hreflang, canonical targets, duplicates, and hierarchy are internally consistent | Defect only when the relevant structure exists and crawl coverage can establish it. N/A requires proven structural irrelevance; incomplete coverage or evidence is unknown or unavailable. |
| Page experience | HTTPS, mobile usability, unobscured content, accessible names/labels/alternatives, and field CWV are healthy | Separate Web Fundamentals result. Missing field data is unknown, not a pass ([page experience](https://developers.google.com/search/docs/appearance/page-experience), [WCAG 2.2](https://www.w3.org/TR/WCAG22/)). |

Meta-description presence/uniqueness, self-referential canonical, sitemap
submission, breadcrumbs, representative media, and concise summaries remain
useful advisories. Google may generate snippets from page content and specifies
no meta-description character limit ([snippet guidance](https://developers.google.com/search/docs/appearance/snippet)).

### Page-kind checkpoint matrix

These are CiteLadder page-purpose contracts, not claims that Google publishes
one checklist or ranking formula per page kind. A page-purpose defect activates
only from page-owned structural evidence or an independently observed trait.

| Page kind | Objective readiness checkpoints | Advisory capabilities or unknowns |
|---|---|---|
| `homepage` | Visible site/entity identity; clear primary purpose; crawlable routes to important page kinds; consistent title/main identity | `WebSite`/`Organization`, logo, `sameAs`, contact data. Entity legitimacy and reputation are unknown. |
| `article` | Article headline and substantial article-owned body; visible creator where the page presents authored editorial content; visible date where the content is explicitly dated or time-sensitive; present markup matches visible facts | `Article`/`BlogPosting`, representative image, author profile, sources, methodology. Word count, originality, expertise, and factual accuracy are not crawler verdicts. |
| `product` | Product identity/description; for a purchasable PDP, visible price and currency or range, availability/purchase state, usable purchase action, and selected-variant consistency; present merchant facts match visible facts | `Product`/`Offer`, identifiers, shipping/returns, Merchant Center. Product snippet eligibility is `name` plus one of offer/review/aggregate rating, not always an offer ([Product snippets](https://developers.google.com/search/docs/appearance/structured-data/product-snippet)). |
| `category` | A real collection/listing; crawlable detail-page links; persistent linked pagination when needed; explicit empty state where empty | Category description, breadcrumbs, `CollectionPage`/`ItemList`. Filter/facet crawl policy is cluster-scoped. |
| `pricing` | Named plans/offers; each commercial option exposes price, currency, and billing basis or an explicit free/custom/contact-sales state; features/limits associate with the correct plan; usable next action | `Service`/`Product`/`Offer` only when semantically true. There is no universal Google PricingPage feature contract. |
| `docs` | Explicit reference/task topic; accessible technical content and docs hierarchy; procedural trait adds prerequisites/context and executable ordered steps; version scope when the document is version-specific | `TechArticle`, `APIReference`, author/date/version navigation. HowTo rich-result absence is not a defect. |
| `faq` | At least one visible question with its associated visible answer; relationships are programmatically recoverable; answers do not require client fetching | `FAQPage` may describe real content, but its absence is not an opportunity. |
| `about_contact` | Trait-split: `about_intent` requires entity identity and what it does; `contact_intent` requires a usable contact path and programmatically labelled form controls; apply both when both are independently observed | `AboutPage`, `ContactPage`, `Organization`, `ProfilePage`. Footer mail/phone links are contact affordances, not page intent. |
| `service` | Service identity, provider, what is delivered and for whom, and a usable enquiry/booking/purchase next step where acquisition is offered; location/area only when geographically bounded | `Service`/`Offer`, price, audience, area served, evidence. Price is not universally required. |
| `local` | Location/business identity; address or explicit service area; usable contact/direction method; hours only when the business model makes them applicable; visible and marked-up facts agree | Most-specific `LocalBusiness`, geo, Business Profile. Legal existence and off-page consistency require external evidence. |
| `guide` | Goal/topic; `procedural` trait requires ordered actionable steps, required inputs/prerequisites, and identifiable outcome; non-procedural guides require organized explanatory sections instead | `HowTo`/`Article`, author/date, tools/media, summary. Do not manufacture a step requirement for a non-procedural guide. |
| `comparison` | At least two named alternatives; common criteria correctly associated with them; evidence/basis for factual comparisons; conclusion or decision guidance | Table, methodology, measurements, alternatives, Article/ItemList vocabulary. Comparative truth remains unknown without verification. |
| `case_study_review` | Trait-split: case study requires subject/context, problem, intervention/action, and observed result; review requires reviewed item, evaluator, evaluation basis, benefits/drawbacks, and verdict | Article/Review markup, quantitative evidence, firsthand media. Result truth and review authenticity are unknown. |
| `trust_policy` | Document/policy identity, responsible organization, scope/audience, operative content, and effective/revised date when state matters; relevant request/appeal/contact path | `WebPage`/`DigitalDocument`, publishing principles. Legal adequacy and jurisdictional compliance are not crawl checks. |
| `other` | Universal eligibility, technical, and diagnostic checks only | Page-purpose AEO is `not_measured` with null score/coverage and reason `page_purpose_unresolved`; no family profile or generic `WebPage` verdict is inferred. |

FAQ, review, procedural, listing, local, contact, about, variant, and comparison
overlays follow observed traits rather than multiplying the exclusive taxonomy.
Before expanding those overlays, extraction must distinguish page-owned facts
from navigation, footer, recommendation, and script noise.

### PR4 family, outcome, score, and coverage contract

The version-`1` measurement configuration owns one executable profile over
classified `page_kind`, independent trait condition, and capability family.
Every classified kind enumerates every family as exactly one of:

- `measured`, with implemented checkpoint expressions and frozen internal
  weights;
- `measurement_gap`, with no checkpoint and a bounded evaluator-gap reason; or
- `not_applicable`, with no checkpoint and a reason proving semantic
  irrelevance.

Omission never implies N/A. Family ownership is the only dimension mapping;
the profile does not repeat one. The analyzer freezes the resolved profile
before outcomes, and context decides expectation while evidence decides
outcome. `other` is classifier abstention outside this matrix: it has no AEO
family rows and returns `not_measured`, null score and coverage, and
`page_purpose_unresolved`.

Checkpoint outcomes have exactly six persisted states:

- `satisfied`: complete inspection proves the expectation;
- `partial`: complete inspection proves the configured partial contract;
- `missing`: inspectable required evidence is absent or deterministically
  defective;
- `unknown`: evidence is insufficient, unavailable, ambiguous, or conflicting;
- `not_applicable`: independent context proves semantic irrelevance; and
- `error`: evaluation failed before a semantic result.

Bounded `reason_code` preserves diagnostic detail without creating more outcome
states. A validated defect is `missing` or `partial`; unavailable extraction,
ambiguous attachment, and conflicting evidence are `unknown` with distinct
reasons. A profile `measurement_gap` is not a checkpoint outcome.

Each scored checkpoint belongs to exactly one of the 11 config-owned capability
families. Every family has one dimension, one scope, and a fixed budget; family
budgets within a dimension sum to `1`:

| Dimension ID | Capability family | Budget | Scope |
|---|---|---:|---|
| `answerability` | `answer_content` | `1` | page |
| `structure` | `semantic_structure` | `1` | page |
| `evidence` | `source_support` | `1/2` | page |
| `evidence` | `commerce_facts` | `1/2` | page |
| `machine-readability` | `structured_representation` | `1` | page |
| `authority` | `visible_attribution` | `1/2` | page |
| `authority` | `site_identity` | `1/2` | site |
| `freshness` | `currency` | `1` | page |
| `crawlability` | `indexability` | `1/3` | page |
| `crawlability` | `snippet_access` | `1/3` | page |
| `crawlability` | `crawler_access` | `1/3` | site |

The complete checkpoint membership is configuration-owned. In particular,
`source_support` requires a primary-content external reference bound to a
Sources, References, or Methodology section, a local citation marker, or nearby
visible attribution; generic outbound links never earn support credit.
`visible_attribution` separates a visible named creator/responsible publisher
from schema or metadata attribution, which may receive only explicit partial
credit. Freshness applicability is established independently by offer,
assortment, pricing, version, release, current-event, time-bound report, or
explicit year/version context before date evidence is inspected. Structured-data
validation binds to primary schema entities and their declared relationships;
a page-wide type union or generic schema node cannot activate or satisfy a
purpose-specific contract. Server-present collapsed content is extractable, and
server-rendering diagnostics do not score.

The structured-representation family is guarded. Absent expected schema resolves
the family through its absence checkpoint. Present schema activates its
required-validity, visible-content-parity, and recommended-property checks at
fixed internal weights without adding a second family budget.

Scoring is family-normalized rather than rule-count normalized:

```text
credit(satisfied) = 1
credit(partial)   = 0.5
credit(missing)   = 0

checkpoint outcomes
  -> family score and coverage per page
  -> coverage-weighted mean within page kind
  -> equal macro vote across expected page kinds
  -> fixed family budgets within each dimension
  -> fixed dimension weights
  -> overall AEO Readiness
```

For every weighted set, quality uses only determinate `satisfied`, `partial`,
and `missing` outcomes; coverage is determinate expected weight divided by total
expected weight. `unknown` and `error` lower coverage without quality credit or
penalty. `not_applicable` leaves the expected set. A `measurement_gap` family
has null quality and zero coverage. A quality result is null when determinate
weight is zero, and coverage is null when expected weight is zero; rollup never
coerces null to `0`, `100`, or N/A.

Expected weight includes every applicable `measured` family budget and every
applicable `measurement_gap` family budget. A gap therefore lowers coverage
without inventing a checkpoint outcome or quality penalty. A `not_applicable`
family is removed before expected weight is calculated. If a profile has no
expected families, expected weight is zero: score and coverage are both null
and state is `not_measured`.

Page-scoped family means are first computed within each expected page kind.
Every expected kind then receives one equal macro vote, regardless of its page
count. Adding more pages of a kind can refine that kind's mean but cannot
increase its cross-kind influence. Site-scoped families are evaluated once and
enter their dimension directly. Web Fundamentals remains objective-defect
scoring and does not consume this AEO family formula.

Aggregate AEO measurement state is:

```text
not_measured      expected weight > 0 and determinate weight == 0
not_measured      expected weight == 0 (no expected families)
limited_evidence  0 < determinate weight < expected weight
measured          determinate weight == expected weight > 0
```

No arbitrary classification, sample-size, or determinacy threshold suppresses a
numeric score. Quality, AEO measurement coverage, classification coverage, and
crawl coverage remain independent persisted facts.

### Classification coverage and persistence

Successful acquisition records a durable `classification_expected` assignment
for a selected, non-excluded supported HTML page before parsing, fact
extraction, classification, or analysis persistence begins. A JS shell remains
expected and normally terminalizes as `other`. A post-assignment parser, fact,
classifier, or persistence failure remains separately counted as a
classification error; it never disappears from the denominator or becomes
`other`.

```text
classification_expected_page_count =
    classified_page_count
    + other_page_count
    + classification_error_page_count

classification_coverage =
    null when classification_expected_page_count == 0
    else classified_page_count / classification_expected_page_count
```

`classified_page_count` includes only terminal non-`other` classifications.
`other_page_count` and `classification_error_page_count` are distinct. Failed
acquisition and supported non-HTML inventory remain outside this denominator
and are represented by Search eligibility and crawl coverage.

The immutable terminal `SiteHealthSnapshot` freezes the four counts, ratio,
state, bounded classifier/error reason groups, formula version, exact source
artifact/execution/analysis IDs, `scored_page_kind_set`, and
`scored_page_count_by_kind`. The active `SiteCrawl.score_summary` mirrors the
same result through the same aggregation owner. These are the only terminal and
active score-summary projections; read APIs never derive, reconcile, or repair
them.

Page, page-kind, crawl summary, snapshot, AEO Readiness, export, trend, and
change projections consume these persisted values. A comparison lacking the
classification or scored-cohort projection is `non_comparable`. When the scored
kind set or count by kind changes, numeric comparison remains available with
reason `cohort_composition_changed`, added/removed kinds, and prior/current
counts; the runtime does not invent a quality-versus-composition decomposition.

### Result interpretation

Finding class remains independent of score ownership: missing defects may create
defect issues and Opportunities; missing or partial advisories may create
readiness gaps but never borrow defect severity or eligibility semantics;
diagnostics are evidence only. Only checkpoints explicitly assigned to a
capability family and AEO score role can affect AEO Readiness.

A critical eligibility failure remains `blocked` regardless of Web Fundamentals
or AEO scores. It does not mathematically cap or zero unrelated capability
evidence. Web Fundamentals 100 means no observed objective defect within its
persisted evidence boundary. AEO Readiness 100 means every determinately
measured expected capability for the classified scored cohort earned full
credit. Neither means perfect content, guaranteed indexing, rank, authority, or
answer-engine citation.

## Issue identity and evidence

The issue catalog groups occurrences by deterministic
`(crawl_id, rule_id, finding_class)` identity and exposes that value as
`group_id`. A stored `SiteIssue.id` is always `occurrence_id`; its persisted
`evaluation_id` is the only relationship used to obtain reason and evaluation
evidence. Page detail does not match evaluations by `rule_id`, because a page
may contain more than one occurrence or evaluation for a rule.

One occurrence DTO is shared by grouped issue detail and per-URL detail. It
contains the affected URL and page kind, frozen description/remediation and
versions, `reason_code`, and bounded evidence. Group detail owns no canonical
evidence copy. The two heading rules remain separate structural signals:
**Web — Full-document heading hierarchy** reads the document-wide sequence;
**AEO — Primary-content heading hierarchy** reads the parser's existing
`primary_heading_outline` from its single `<main>`/content-region boundary.
Evidence names exact transitions and scope without treating every skip as an
automatic accessibility conformance violation.

Crawl-finalized broken-link evaluations are projected onto each source page,
not onto the crawl root. Their occurrence evidence names the bounded failed
target and observed HTTP status, so page detail can explain the actual link
defect without presenting a site-global statement as a homepage defect.

## Change Intelligence

After a newer crawl terminalizes with usable evidence, Site Health persists one
immutable comparison for its immediately preceding usable project crawl.
Comparable measurement pairs require the same root origin, frozen crawl-scope
hash, relevant version set, and persisted classification/scored-cohort
projection. A missing predecessor is `unavailable`; missing provenance or scope
or version drift is `non_comparable`, never a regression. A changed scored kind
set or count by kind remains mathematically comparable with bounded reason
`cohort_composition_changed` and the prior/current composition. Completed pairs
may report added/removed URLs. Partial or cancelled pairs compare shared
observed URLs only and suppress all added/removed claims.

The deterministic analyzer compares title, meta description, H1, canonical,
robots noindex, JSON-LD presence, internal-link count, and HTTP status. Changes
are `improvement`, `neutral-change`, `potential-regression`, or
`critical-regression`. Rule fail→pass improves; pass→fail regresses and becomes
critical only for a critical rule. HTTP 2xx→4xx/5xx and an explicitly
intended-indexable page becoming non-indexable are critical. The crawler never
infers intent. `expected` is an overlay only when an exact implementation event
targets the page/field or rule, falls between A and B, and its expected value or
outcome matches B.

`SiteChangeSnapshot` and `SiteChangeObservation` freeze both crawl IDs, source
analysis/artifact/evaluation IDs, versions, scope/source hashes, coverage, and
the optional implementation-event ID. They never manufacture `SiteIssue` rows.
Only unexpected potential/critical regressions map into the existing
Opportunity owner; later snapshots use its normal supersession lifecycle.
Summary, cursor-paged observations, and detail reads live under the existing
project Site Health `/changes` routes and never compute or repair a diff.

## Page-kind classification

Every analyzed HTML page receives one of:

```text
homepage, article, product, category, pricing, docs, faq,
about_contact, service, local, guide, comparison,
case_study_review, trust_policy, other
```

Classification is pure, deterministic, bounded, and versioned. It reads a
primary `<main>`, `<article>`, or body-minus-chrome region; non-rendered content,
page chrome, and repeated recommendation cards cannot speak for the primary
entity.

Evidence resolves in order: page-owned structure, the nearest exact semantic
path segment, then bounded FAQ/article/title semantics. An exact blog/news or
blog/category archive route plus a page-owned repeated linked-card collection
is structural category evidence; an individual post with a related-card strip
remains an article. Structured data may
corroborate and suggest schema but never decides page kind by itself. Same-tier
conflicts abstain to `other`; lower-tier conflicts persist. The winning signal,
tier, conflicts, alternatives, schema suggestion, and `high|medium|low|unknown`
confidence label persist in `SitePageAnalysis.page_kind_evidence`. `other` is
abstention and receives no page-kind-specific score.

Each scoped rule is `expectation`, `triggered`, or `universal`. The resolved
page-kind/trait family profile decides whether an expectation applies; the
winning classifier tier and confidence label do not change the profile or
score. Triggered quality checks rely on a present artifact and must declare a
same-family absence or root sibling.

## Page traits

`page_kind` is exclusive; traits are additive observations:

```text
has_faq, has_reviews, has_variants, listing, local_intent,
contact_intent, about_intent, case_study_intent, comparison_content, procedural
```

Derivation is pure, deterministic, bounded, and versioned (`TRAITS_VERSION`).
It reads page facts independently of `page_kind`; trait gates therefore cannot
become consequences of classification. Trait evidence is stricter than a
similar classifier signal: for example, `has_faq` requires FAQ markup or
question-mark subheadings. Traits split bundled contracts such as about versus
contact and case study versus review. Contact links and fields in header,
navigation, footer, and aside chrome never activate page-owned
`contact_intent`. Traits persist in `SitePageAnalysis.page_traits` and appear in
page detail. An independent trait may select a config-owned family-profile row,
but the scored evidence cannot manufacture the trait that makes itself
expected. For example, an FAQ checkpoint cannot use its own evidence to turn a
generic article into an FAQ-scored profile.

## Content sufficiency

Length is evidence, not a quality verdict. `technical.thin_content` detects an
empty page using the low universal `MIN_MEANINGFUL_WORDS` floor. Page-owned
structure such as a listing, price, address, contact path, or entity identity
may only add a way to pass; it can never make a page fail. Short content is not
automatically defective.

## Structured-data extraction and schema contracts

The bounded extractor reads JSON-LD graphs and shallow microdata, normalizes
schema.org URL types, preserves recognized multi-types, reads only config-owned
property paths, and skips malformed blocks without failing the page.

`PAGE_KIND_EXPECTED_SCHEMA` owns allowed alternatives and type-specific required
and recommended properties; contracts are resolved for the schema type actually
used, never once for an entire page kind.

Schema handling is validation-first. Absence is an advisory, never a defect;
present invalid or contradictory markup is a defect owned by its validation or
`aeo.schema_matches_content` check.

Required properties are only those a present block genuinely needs. `Article`
requires `headline`; `author` and `datePublished` are recommendations.
`FAQPage` and `HowTo` have no required-property scoring contract, while
present contradictory markup remains reportable.

Schema rules require both a classified non-`other` page kind and an HTML
response. Content-parity rules additionally require visible server-rendered
body content.

## Rule applicability

Not-applicable is different from satisfied and is excluded from the expected
set. It requires independent context proving semantic irrelevance; missing
evidence, failed extraction, uncertainty, conflict, or an absent evaluator
cannot produce it.

- Delivery and indexability rules read the response and remain applicable to
  any successful fetch.
- Title, meta-description, and canonical rules require an HTML response. A
  supported office/PDF/Markdown document is successful inventory evidence and
  is not reported as missing markup its format does not have.
- Page-purpose schema families require a classified non-`other` HTML page.
  Validation binds to the primary schema entity and visible page-owned content.
- Visible attribution applies only where independently established authored or
  responsible-publisher context requires it. Metadata-only authorship cannot
  earn full visible-attribution credit.
- Source support applies only under independent research-sensitive context and
  requires a deterministically attached primary-content source. A generic
  external link is neither support nor attribution.
- Freshness applies only under independent current-state, version, release,
  news, report, or explicit year/version context. Date presence or absence does
  not decide applicability.
- Question-heading requirements apply to the `faq` page kind under its resolved
  family profile. An expected FAQ with no eligible subheadings is `missing`,
  never N/A.
- A canonical declaration pointing away from a page is not itself a conflict;
  only deterministically broken or contradictory target evidence fails.
- Architecture absence claims that require complete coverage become `unknown`
  with a bounded coverage reason when that coverage is incomplete.

A JS shell receives the server-rendering diagnostic. Rules that need unseen body
content remain semantically not applicable only when independent context proves
irrelevance; otherwise expected checkpoints resolve `unknown` with the bounded
primary-content reason rather than producing fabricated missing-content issues.

## Provenance

`SitePageAnalysis` is UUID-identified and append-only. Repeated analyses may
reference the same immutable artifact; only one row per page in a crawl is
current. Rule rows carry exact source IDs and relevant version fields.

Grouped issue IDs are deterministic UUID5 values derived from the crawl, rule,
and finding class. Filtering or adding another occurrence cannot change the group URL.
Catalog detail routes accept only `group_id`; `occurrence_id` identifies the
persisted page evidence inside that group and is not a compatibility route key.

Every failing scored evaluation freezes its description, remediation, and
analyzer/catalog versions onto `SiteIssue`. Reads use that stored copy, never
the current catalog. A failing evaluation without a score role remains bounded
guidance in evidence detail; it cannot create an issue. This is enforced by one
issue-creation predicate shared by page, finalize, and architecture writers.

Only rules with an explicit score role enter a score or create an issue.
Web Fundamentals accepts objective defects only. AEO Readiness consumes a
deterministic defect or advisory only through its config-owned capability
family, dimension, scope, and fixed family budget; internal checkpoint weights
divide that budget rather than create new influence. Diagnostics and
non-scoring guidance never create issues or Opportunities. Therefore a
displayed issue always reduces at least one displayed score; a 100 cannot
coexist with one of its own failing issues.

Indexability intent follows explicit user policy, canonical declaration,
sitemap membership, then robots evidence. Intended exclusion is not applicable;
an intended-indexing contradiction is a defect; unknown intent is a non-critical
advisory. Promo-like paths and missing inbound links are not intent evidence.

Version owners remain in `backend/app/core/config/site_health_*`; the active
values are `sh-extractor-1`, `sh-classifier-1`, `sh-traits-1`,
`sh-analyzer-1`, `sh-rules-1`, `sh-scoring-1`, `sh-coverage-1`,
`sh-link-metrics-1`, `sh-architecture-1`, and `sh-archetypes-1`. The disposable
development reset policy above applies. An unclassified `other` page retains
its Web Fundamentals score but has no AEO score.

The analyzer, rule, scoring, profile, schema, and presentation version owners
deliberately remain separate. Snapshots do not yet persist a complete frozen
descriptor of the rule set, weights, thresholds, and profile, so collapsing
those six identifiers into one contract version would reduce historical
reproducibility. That cleanup is deferred until the full descriptor is frozen
on each snapshot.
