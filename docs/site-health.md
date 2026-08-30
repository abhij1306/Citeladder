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
- A standard run advances through discovery, analysis, snapshot creation, and
  terminal completion. `input_mode=auto` is a request-mode token, not scheduled
  crawling. Only an explicit advanced request may pause between phases.
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

Two persisted summaries remain visible below. Internal linking reports the
total observed internal links, the count and percentage of observed pages with
at least one incoming link, and the orphan count when complete coverage permits
that absence claim. Structure depth reports page counts and percentages for
depth 0, depth 1, depth 2, and depth 3+, plus the number of pages whose depth was
not measured. Percentages use only pages with measured depth as their
denominator. Detailed internal-link and depth reports are deferred to PR3, so
PR1 presents no report links or report actions.

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
presentation projection over the selected crawl's current successful HTML
analyses and their persisted evaluations. It requires the crawl's exact page
analyzer and extractor versions and returns the exact source-analysis IDs.
Optional `crawl_id` selects one usable terminal crawl; omission selects the
latest. Reads never analyze, enqueue, repair, or call a provider.

The version-`1` PR2 measurement manifest maps only defensible score-applicable
checkpoints into seven ordered dimensions: **Answerability**, **Structure**,
**Evidence**, **Machine readability**, **Provenance & trust signals**,
**Freshness**, and **Crawlability**. The stable machine key for Provenance &
trust signals remains `authority`.

Each dimension is projected in page terms, not evaluation terms: applicability,
measurement state, score, coverage, expected and determinate points, explicit
uncertainty counts, catalog guidance, and a bounded set of failing pages. The
bound always travels with the true failing-page total. Reads use persisted
analyses, evaluations, and snapshot projections; they never calculate or repair
measurement.

## Shipped measurement contract

This section is the canonical logic for the active PR2 measurement contract.
The three-PR implementation sequence lives in
[`plans/site-health-measurement-cutover.md`](plans/site-health-measurement-cutover.md).
This file owns measurement meaning and formulas; the plan owns delivery order
and acceptance.

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
   `excluded`. A critical access, indexability, or snippet-control failure must
   not be diluted by unrelated passes.
2. **Technical integrity** is a 0–100 correctness score over deterministically
   evaluated objective defects, always paired with evidence coverage.
3. **AEO Readiness** is a separate 0–100 capability score over applicable,
   deterministic optimization signals. It may credit both satisfied defects
   and satisfied advisories without turning an advisory absence into an
   objective fault or eligibility failure.
4. **Web Fundamentals** is a separate accessibility, mobile, security, and
   page-experience result. Lab diagnostics never impersonate field Core Web
   Vitals. Field status uses the 75th percentile and the current good
   thresholds LCP <= 2.5 seconds, INP <= 200 milliseconds, and CLS <= 0.1
   ([Core Web Vitals thresholds](https://web.dev/articles/defining-core-web-vitals-thresholds)).
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
| `search.crawler_access` | Robots and declared search/citation-crawler policy evidence | A proven contradiction yields `blocked`; unsupported or conflated bot evidence remains `unknown` until a dedicated evaluator ships |
| `search.snippet_access` | Determinate snippet-control directives and declared visibility intent | A proven contradiction yields `blocked`; an evaluator not yet available remains `unknown` until a dedicated evaluator ships |

A checkpoint enters the critical set only when its evaluator can produce both
a determinate healthy state and a determinate blocker state. The delivery plan
may use a smaller temporary set before every target evaluator ships; an
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
makes the aggregate `blocked`. With no blocker, any expected critical checkpoint
that is unknown, unavailable, conflicting, or errored makes it `unknown`.
`eligible` requires every expected critical checkpoint to be determinate with no
blocker. `excluded` requires the declared audit intent to exclude the entire
selected cohort. Counts and reason groups remain visible beside the headline.

The design separates finding meaning, score ownership, and the two kinds of
applicability:

```text
finding_class = defect | advisory | diagnostic
score_roles   = {technical_integrity, aeo_readiness} | none
display_applicability = may this finding be shown as contextual guidance?
score_applicability   = is evidence strong enough to alter a score?
```

`finding_class` answers whether an absent or failed checkpoint is objectively
wrong, an optimization opportunity, or neutral diagnostic evidence.
`score_roles` answers which measurement the checkpoint informs. Only defects
may affect Technical integrity. An applicable defect or advisory may affect
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
| `other` | Universal eligibility, technical, and Web Fundamentals checks only | Universal AEO capabilities may be measured when evidence sufficiency is met, but no page-purpose profile or generic `WebPage` verdict is inferred. Unresolved purpose remains a visible limitation. |

FAQ, review, procedural, listing, local, contact, about, variant, and comparison
overlays follow observed traits rather than multiplying the exclusive taxonomy.
Before expanding those overlays, extraction must distinguish page-owned facts
from navigation, footer, recommendation, and script noise.

### Target score and coverage formula

Every checkpoint declares a stable ID and development version `1`, scope,
family, category,
severity, finding class, zero or more score roles, applicability contract,
required evidence, page-kind/trait profile, and—when AEO-scored—a readiness
dimension and positive readiness weight. One observable root condition receives
one scored checkpoint; diagnostic siblings do not stack points for the same
capability or remediation.

The initial config-owned checkpoint-family registry is explicit:

| Family ID | Meaning | Initial cutover checkpoints |
|---|---|---|
| `answer_content` | Direct answer or purpose-essential answer content | `aeo.answer_first` |
| `semantic_structure` | Recoverable semantic organization and question/answer structure | `aeo.question_headings` |
| `structured_representation` | Schema applicability, validity, completeness, and visible-content parity | `aeo.schema_expected_for_type`, `aeo.schema_required_valid`, `aeo.schema_recommended_present`, `aeo.schema_matches_content` |
| `provenance` | Named creator or responsible organization | `aeo.author_present`, `aeo.organization_identity` |
| `indexability` | Intended-public indexability | `technical.indexable` |

All four schema checkpoints intentionally count as one family. The registry may
add config-owned families only when genuinely distinct capabilities ship. A
checkpoint without a declared family cannot satisfy a breadth gate.

The analyzer constructs and freezes the expected checkpoint profile before any
evaluation outcome is assigned. The profile comes from audit intent,
page-owned page-kind/trait evidence, triggered present artifacts, and the
config-owned **score** applicability contracts. Display-only conditional
guidance remains outside the scored expected profile. An evaluator may not
remove an expected checkpoint by returning N/A:

- `not_applicable` requires a bounded deterministic reason code proving
  structural irrelevance, such as `format_has_no_html` or
  `trait_determinately_absent`;
- missing or insufficient evidence for an expected checkpoint becomes
  `unknown` or `unavailable` and lowers coverage; and
- weak classification may allow conditional display guidance, but it cannot
  make an expectation score-applicable. The page records a
  `profile_insufficient` limitation and cannot satisfy measured-state breadth
  through those conditional checks.

This ordering is an anti-gaming invariant: expected-set construction is owned
by the profile registry, not by individual evaluator outcomes.

Dimension applicability has the same evidentiary bar. The profile registry may
emit `not_applicable` only when a declared deterministic contract proves that
the page does not need the capability. A missing checkpoint, evaluator, or
score-applicability gate never proves irrelevance; when relevance cannot be
decided, the dimension is `unresolved` and remains in the coverage denominator.

The target assessment vocabulary is:

- `satisfied`: determinately present/correct;
- `partial`: determinately present but incomplete under a checkpoint-specific
  rubric;
- `missing`: determinately absent/incorrect;
- `unknown`, `unavailable`, `conflicting`: expected but not determinable from
  this evidence;
- `error`: analyzer failure, not a site failure;
- `not_applicable`: structurally irrelevant;
- `excluded`: deliberately outside the declared search/audit intent.

Every readiness dimension separately freezes:

```text
dimension_applicability   = applicable | not_applicable | unresolved
dimension_measurement_state = measured | limited_evidence | not_measured
```

`not_measured != not_applicable`. `not_applicable` requires a deterministic
page-purpose/trait reason proving the page does not need that capability and is
removed from both score and coverage denominators. When the capability is
applicable but CiteLadder lacks a trustworthy evaluator,
`dimension_readiness = null`, `dimension_coverage = 0`, and the state is
`not_measured`; the dimension remains in the overall coverage denominator but
not the readiness-score denominator. `unresolved` is used when available
evidence cannot yet decide relevance. It also contributes zero coverage and
prevents a measured headline, so uncertainty can never increase confidence by
silently removing a pillar.

An empty expected-checkpoint set does not decide applicability. The registry
must freeze one of three explicit outcomes:

- proven irrelevance -> `not_applicable`, reason
  `dimension_determinately_irrelevant`;
- proven relevance but no score-applicable checkpoint in the active manifest ->
  `applicable` + `not_measured`, zero coverage, reason
  `no_expected_checkpoint_evaluator`; or
- relevance not determinable -> `unresolved` + `not_measured`, zero coverage,
  reason `dimension_relevance_unresolved`.

These states are distinct from an expected checkpoint that ran but returned
unknown or unavailable evidence.

Objective defect checkpoints are binary: `satisfied` or `missing`; `partial`
is not allowed to soften a defect. AEO capability checkpoints use discrete,
config-owned credit only:

```text
satisfied = 1.0
partial   = 0.5
missing   = 0.0
```

Each partial rubric is deterministic and checkpoint-specific. For example, an
authored article may earn full provenance credit for a named author linked to
useful provenance, partial credit for a named author alone, and zero for no
attribution. No model invents continuous quality points.

Technical integrity consumes only checkpoints whose finding class is `defect`
and score roles include `technical_integrity`:

```text
technical_determinate_weight = satisfied_defect_weight + missing_defect_weight
technical_integrity =
    null if technical_determinate_weight == 0
    else 100 * satisfied_defect_weight / technical_determinate_weight
technical_coverage =
    null if expected_technical_defect_weight == 0
    else technical_determinate_weight / expected_technical_defect_weight
```

Analyzer error and unavailable evidence do not make the site technically
wrong. They remain expected but non-determinate and lower coverage.

Technical Integrity has its own presentation state:

- `measured`: every critical expected Technical checkpoint is determinate and
  Technical coverage meets `TECHNICAL_MEASURED_MIN_COVERAGE`;
- `limited_evidence`: some Technical evidence is determinate but the measured
  criteria are not met;
- `not_measured`: no defensible determinate Technical measurement exists; and
- `excluded`: the declared audit intent excludes the page.

The active development default is `TECHNICAL_MEASURED_MIN_COVERAGE=0.80`. The calculated
Technical ratio may remain persisted for diagnostics, but it is not presented
as a headline percentage unless the state is `measured`.

AEO Readiness consumes applicable defect and advisory checkpoints whose score
roles include `aeo_readiness`. For each dimension:

```text
earned_points = sum(readiness_weight * discrete_credit)
determinate_points = sum(readiness_weight for satisfied/partial/missing)
expected_points = sum(readiness_weight for every expected checkpoint)

dimension_readiness =
    null if determinate_points == 0
    else 100 * earned_points / determinate_points

dimension_coverage =
    null if dimension is not_applicable or excluded
    else 0 if expected_points == 0
    else determinate_points / expected_points
```

Unknown, unavailable, conflicting, and error are deliberately absent from the
readiness denominator; treating them as zero would collapse missing capability
and missing evidence. They remain in expected points and therefore lower
coverage. `not_applicable` and `excluded` leave the expected set entirely.

The overall formulas are fixed explicitly:

```text
scored_dimensions = applicable dimensions with dimension_readiness != null

overall_readiness =
    null if scored_dimensions is empty
    else sum(dimension_weight[d] * dimension_readiness[d]
             for d in scored_dimensions)
         / sum(dimension_weight[d] for d in scored_dimensions)

covered_dimensions = all applicable or unresolved dimensions

overall_coverage =
    null if covered_dimensions is empty
    else sum(dimension_weight[d] * dimension_coverage[d]
             for d in covered_dimensions)
         / sum(dimension_weight[d] for d in covered_dimensions)
```

An entirely non-determinate applicable dimension contributes no score credit or
penalty but remains in the coverage denominator. The measurement-state decision
is made only after both ratios and the breadth requirements are computed.

Finding class still controls user meaning and downstream action:

- missing defect -> defect issue and possible Opportunity;
- missing/partial advisory -> optimization gap and possible advisory action,
  never a defect, severity escalation, or eligibility failure;
- diagnostic -> evidence only, never a score or Opportunity.

Examples of readiness-scored advisories include relevant structured-data
implementation, creator/organization provenance, concrete supporting evidence,
meaningful semantic structure, direct answers where the page purpose warrants
them, and accurate freshness signals where freshness matters. Missing schema
receives modest machine-readability weight; it never dominates AEO Readiness.

Meta-description presence, Open Graph, `llms.txt`, generic FAQ presence,
self-canonical preference, fixed title/meta bands, and fixed content/chunk
lengths receive no core AEO points. They may remain no-score advisories or
diagnostics when useful. Research may justify a scoped advisory, never a
universal defect or causal visibility claim.

A critical eligibility failure produces `blocked` regardless of Technical or
AEO scores. The UI leads with that state but retains a sufficiently covered AEO
Readiness score; it never mathematically caps or zeros unrelated capability
evidence.

The development presentation policy is config-owned by:

```text
AEO_MEASURED_MIN_COVERAGE = 0.80
AEO_MEASURED_MIN_CHECKPOINTS = 4
AEO_MEASURED_MIN_FAMILIES = 3
AEO_MEASURED_MIN_DIMENSIONS = 3
```

The resulting states are:

- `measured`: every critical expected checkpoint is determinate, AEO coverage
  meets `AEO_MEASURED_MIN_COVERAGE`, and determinate evidence meets all three
  breadth minimums above;
- `limited_evidence`: some evidence is useful but those conditions are not met;
- `not_measured`: there is no defensible expected profile;
- `excluded`: declared page intent places the page outside public-search audit.

These are config-owned minimums under development policy `1`, not search-engine
thresholds. Shadow-corpus calibration may raise them when evidence shows that
the minimum still permits fake precision; lowering them requires an explicit
product decision. A limited result may retain its calculated ratio for
debugging but must not show it as a headline percentage. In particular, one to
three easy checks can never produce a measured 100.

Crawl aggregation pools earned and determinate readiness points within each
dimension across the latest compatible analysis per selected URL. Measurement
coverage is first normalized within each dimension so a pillar's global
influence does not grow merely because it applies to more pages. Only then are
the configured AEO dimension weights applied:

```text
site_technical_integrity =
    null if sum(page determinate defect weight) == 0
    else 100 * sum(page satisfied defect weight)
             / sum(page determinate defect weight)
site_aeo_dimension[d] =
    null if sum(page determinate readiness points in d) == 0
    else 100 * sum(page earned readiness points in d)
             / sum(page determinate readiness points in d)

site_dimension_coverage[d] =
    null if count(applicable or unresolved page-dimensions in d) == 0
    else sum(page_dimension_coverage[p, d]
             for applicable or unresolved page-dimensions in d)
         / count(applicable or unresolved page-dimensions in d)

site_aeo_measurement_coverage =
    null if count(site-applicable or unresolved dimensions) == 0
    else sum(dimension_weight[d] * site_dimension_coverage[d]
             for site-applicable or unresolved dimensions)
         / sum(dimension_weight[d]
               for site-applicable or unresolved dimensions)
```

An applicable `not_measured` or unresolved page-dimension contributes zero to
`site_dimension_coverage`; `not_applicable` and `excluded` page-dimensions are
absent. A site dimension is applicable or unresolved when at least one selected
page has that dimension state. Readiness never averages page score percentages.
Coverage averages already-normalized page-dimension coverage within a pillar
and applies each global pillar weight exactly once, so unresolved/not-measured
evidence cannot disappear and page-count differences cannot rewrite the
20/15/15/20/10/5/15 policy.
Aggregate responses also expose
selected/analyzed/evaluable counts, page-kind/trait splits, acquisition
coverage, measurement coverage, limitations, exact source IDs, and active
development identifiers (all `1`).
The crawl/site `technical_integrity_state` and `aeo_measurement_state` are
recomputed from pooled aggregate expected/determinate evidence. They are never
an average, majority, or best-page state. Aggregate breadth counts unique
checkpoint IDs, unique checkpoint families, and unique readiness dimensions;
repeating one checkpoint across 100 pages still counts as one checkpoint and
one family.
No Technical-only result is silently relabelled Combined. The active contract
retains Technical integrity and AEO Readiness as independent scalars and
retires the Technical/AEO 50:50 `overall_score` headline.

Technical integrity 100 means no observed objective defects within a
sufficiently covered measurement under the active build. AEO Readiness 100
means every determinately measured applicable readiness capability earned full
credit at sufficient coverage. Neither means perfect content, guaranteed
indexing, rank, authority, or answer-engine citation.

## Change Intelligence

After a newer crawl terminalizes with usable evidence, Site Health persists one
immutable comparison for its immediately preceding usable project crawl.
Comparable pairs require the same root origin, frozen crawl-scope hash,
extractor version, and page-analyzer version. A missing predecessor is
`unavailable`; scope or version drift is `non_comparable`, never a regression.
Completed pairs may report added/removed URLs. Partial or cancelled pairs
compare shared observed URLs only and suppress all added/removed claims.

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

Each scoped rule is `expectation`, `triggered`, or `universal`. An expectation
defect requires page-owned structural evidence. A path- or text-derived kind
cannot fail or score an expectation and returns `not_applicable` with
`low_confidence_kind`; conditional advisories may still display. Triggered
checks rely on their present artifact. Applicability keys on evidence tier, not
the confidence label.

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
`contact_intent`. Traits persist in
`SitePageAnalysis.page_traits` and appear in page detail.

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

Not-applicable is different from pass and is excluded from scoring.

- Technical delivery and indexability rules read the response and remain
  applicable to any successful fetch.
- Title, meta-description, and canonical rules require an HTML response. A
  supported office/PDF/Markdown document is successful inventory evidence and
  is not reported as missing markup its format does not have.
- Schema presence/type/property rules apply only to classified page kinds.
- Author and citation rules apply only to authored editorial types.
  `aeo.author_present` is `not_applicable` on `case_study_review`: a case study
  is usually published by the organization and owes no named writer.
- Date rules also include documentation.
- Question-heading rules apply to FAQ pages only, and are not applicable to a
  page with no h2/h3 subheadings at all: no sections is a different fact from
  badly phrased sections.
- Answer-first structure is a no-score advisory only when independent
  page-owned `has_faq` evidence proves an answer task. A route/title guess,
  service page, comparison, case study, narrative article, or generic guide/docs
  page carries no obligation to open with a direct answer.
- A canonical declaration that points away from the page is not a conflict —
  consolidating a sorted, filtered, or tracked URL onto its parent is what the
  element is for. Only positive evidence of a broken target fails: a canonical
  that is unresolvable, points to another origin, or points at a different
  hreflang alternate of the same page. Campaign and click parameters are
  removed before the comparison, and a relative canonical is resolved against
  the page URL first.
- Product offer and visible/schema parity rules apply only to product pages.
- Architecture depth, breadcrumb-conflict, and duplicate-page-kind-metadata rules
  report positive observations at any coverage. Orphan, parentless-detail,
  unhubbed-page-kind, and sitemap-orphan absence claims require complete coverage;
  the currently shipped evaluator stores `not_applicable` with
  `coverage_not_complete`. That encoding means expected-but-non-determinate for
  coverage and presentation; the replacement outcome is `unavailable`.

A JS shell receives one server-rendering finding. Rules that need unseen body
content remain not-applicable instead of producing a cascade of fabricated
missing-content issues.

## Provenance

`SitePageAnalysis` is UUID-identified and append-only. Repeated analyses may
reference the same immutable artifact; only one row per page in a crawl is
current. Rule rows carry exact source IDs and relevant version fields.

Grouped issue IDs are deterministic UUID5 values derived from the crawl and
rule. Filtering or adding another occurrence cannot change the group URL;
historical occurrence IDs remain accepted by the detail endpoint.

Every failed evaluation freezes its description, remediation, and
analyzer/catalog versions onto `SiteIssue`. Reads use that stored copy, never
the current catalog.

**Only defects score in the shipped formula.** Advisory and diagnostic evaluations
are excluded from scoring entirely — pass, fail, and error alike — so guidance
or neutral compatibility evidence can neither lower nor raise the shipped
health score. Diagnostics persist as evaluations but never create issues or
Opportunities. Exact-one-H1, very-low-word-count, outbound-citation, date,
answer-first, and expand-gating proxies are no-score advisories;
server-rendered-content and AI-crawler-access proxies are no-score diagnostics.
The approved replacement
allows only explicitly score-owned advisories to affect AEO Readiness, never
Technical Integrity. Defects and advisories retain separate filtered views;
only defects feed severity filters and Opportunities.

Indexability intent follows explicit user policy, canonical declaration,
sitemap membership, then robots evidence. Intended exclusion is not applicable;
an intended-indexing contradiction is a defect; unknown intent is a non-critical
advisory. Promo-like paths and missing inbound links are not intent evidence.

Version owners remain in `backend/app/core/config/site_health_*`; the active
values are `sh-extractor-1`, `sh-classifier-1`, `sh-traits-1`,
`sh-analyzer-1`, `sh-rules-1`, `sh-scoring-1`, `sh-coverage-1`,
`sh-link-metrics-1`, `sh-architecture-1`, and `sh-archetypes-1`. The disposable
development reset policy above applies. An unclassified `other` page retains
its Technical score but has no AEO score.
