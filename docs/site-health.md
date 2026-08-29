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

1. **Site Health** — crawl lifecycle, scores by page kind, and URL inventory,
   with **Pages**, **Architecture**, **AEO Readiness**, and **Changes** tabs.
2. **Issues** — grouped findings with affected page-kind badges.
3. **Opportunities** — persisted prioritized actions.

The removed Site Intelligence workspace and industry-pack/knowledge subsystems
must not be reintroduced as parallel owners. Site Health owns one persisted
observed-architecture projection whose read surface exposes observed families
and hierarchy only.

## Pipeline

```text
explicit user Run new crawl -> seed + sitemap + internal links
  -> URL admission and corpus disposition
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
- As admissible pages arrive, analysis is automatically enqueued and progresses
  alongside discovery. The frozen entitlement/runtime allowance still bounds
  which pages may be analyzed; discovery never turns an unentitled inventory
  row into analysis work.
- A user-triggered **Run new crawl** request always advances through discovery,
  analysis, snapshot creation, and terminal completion. Its
  internal `input_mode=auto` value is a request-mode token, not an automatic or
  scheduled crawl feature. The development advanced-controls setting only
  makes manual APIs available; it does not opt standard runs into pausing.
  Only an explicit advanced request or a manual phase-start API call freezes
  the internal manual-phase marker that permits pausing between phases.
- Discovery completion never opens a page-selection or separate analysis step.
  The live results surface stays mounted until the crawl terminalizes.
- Sitemap frontier lookups and inserts use bounded batches; a full configured
  sitemap cannot exceed PostgreSQL driver parameter limits.
- Sitemap observations are also written in bounded batches. A worker reuses
  secure HTTP connection pools by original origin while retaining the same
  per-request DNS, pinned-IP, redirect, robots, and host-gate checks.
- The default host gate no longer imposes a sub-six-starts-per-second policy
  ceiling on a responsive owned site. Robots directives, response latency,
  retries, parsing, and persistence still determine actual crawl throughput.
- Fetch attempts and artifacts are append-only; secrets and unsafe response
  headers are never persisted.
- Discovery runs the complete bounded fact extractor on each acquired HTML
  response and freezes those facts on its immutable artifact. Analysis reuses
  that same artifact when the crawl's required extractor version matches, so
  discovery and analysis retain separate lifecycle results without a second
  HTTP acquisition. If no complete current-version discovery artifact can
  exist (including a Free sample analyze-only URL), analysis uses the normal
  secure acquisition fallback. An analyze task that races an active discovery
  task is durably deferred without consuming a network-attempt budget.
- Append-only fetch-attempt rows retain each curl call's bounded delivery and
  error provenance. A host-level `429` cooldown gates new starts while task
  retries retain their ordinary bounded queue policy.
- Anchor extraction may repair an encoded query delimiter only when the first
  encoded suffix key is a config-owned tracking parameter. That boundary-only
  rewrite interprets encoded `=` and `&` separators in the identified query,
  runs ordinary query normalization, and freezes its reason and rewrite version
  on the immutable URL observation. Legitimate `%3F`, `%26`, `%2F`, and `%25`
  path content remains byte-preserving crawler identity; `canonicalize()` and
  `canonical_identity()` retain their reserved-escape semantics.
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

Page families replace only the final path segment with `*` and report URL and
page-kind counts, median observed depth, indexable count, metadata-duplication
rate, and—only for complete coverage—orphan count. Parent evidence resolves in
strict order: visible breadcrumb links, explicit `BreadcrumbList`/`isPartOf`
relationships, a crawled immediate URL parent whose page kind can safely act as
a hub, then `unknown`. Cross-links never manufacture a parent.

The archetype can only be mapped from a sufficiently grounded onboarding
`business_model`; an absent/weak profile or materially contradictory crawl
abstains to `other`. Crawl evidence may veto but never assign an archetype.
Common structures not observed are suppressed unless coverage is complete.

### Architecture read surface

The Architecture tab renders page families only — each family expanding to the
URLs assigned to it. The observed hierarchy tree and the site-profile block are
not presented; the Markdown export below remains the place a structural tree
belongs.

`GET /api/v1/projects/{project_id}/site-health/architecture` projects the newest
persisted model for the selected (or latest usable) crawl. It never re-derives
the model, crawls, or scores. The response carries `coverage_state` alongside
every site-level number, the page-family rows, the hierarchy nodes with their
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

Taxonomy `aeo-readiness-v1` maps exactly 21 declared rule IDs into seven ordered
dimensions: **Answerability**, **Structure**, **Evidence**,
**Machine readability**, **Authority**, **Freshness**, and **Crawlability**.

Each dimension is projected in page terms, not evaluation terms: a plain
description, per-rule rollups carrying the catalog title and remediation, the
distinct pages a check applied to, the distinct pages that failed at least one,
and a bounded list of failing pages each naming its own failed checks once. The
bound is on pages and is always reported with the true failing-page total, so a
capped list never reads as the whole set. A rule ID stays provenance and is
never display copy.
Unmapped Site Health rules remain outside this view; there is no fallback
bucket. Each dimension exposes pass, fail, not-applicable, error, expected and
observed counts, coverage, and at most 25 failing pages in `evidence_pages`.
The true failing-page total is reported separately even when that page list is
bounded.
Not-applicable remains disclosed and never becomes a failure. This adds no AEO
Readiness score and does not reinterpret Site Health scoring.

## Change Intelligence

After a newer crawl terminalizes with usable evidence, Site Health persists one
immutable comparison for its immediately preceding usable project crawl.
Comparable pairs require the same root origin, frozen crawl-scope hash,
extractor version, and page-analyzer version. A missing predecessor is
`unavailable`; scope or version drift is `non_comparable`, never a regression.Completed pairs may report added/removed URLs. Partial or cancelled pairs
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

Classification is pure, deterministic, bounded, and versioned. The extractor
first selects the primary `<main>`, `<article>`, or body-minus-chrome region.
Non-rendered subtrees and page chrome cannot contribute visible text or entity
controls. Repeated, structurally similar linked cards are identified so a
recommendation carousel cannot speak for the page's primary entity.

The classifier resolves three evidence tiers:

1. structural page-owned evidence: a corroborated visible product buy box, a
   listing grid plus a listing affordance, or one address under a local route;
2. the semantic URL path segment nearest the root;
3. bounded FAQ/article/title semantics.

Structured data remains recorded as weak evidence and a schema suggestion, but
is never eligible to decide a page kind by itself. Same-tier disagreements
abstain to `other`; lower-tier disagreements persist as conflicts. Confidence
is the label `high`, `medium`, `low`, or `unknown`, not a probability. The
winning signal, tier, conflicts, alternatives, and schema suggestion persist on
`SitePageAnalysis.page_kind_evidence`.

A visible price plus purchase control and a corroborator may therefore override
an ancestor category-path signal for a deep PDP. Product schema may corroborate
that independently visible structure but cannot self-certify the product
contract.

Nested route families such as `/resources/guides/...`,
`/company/contact-us`, and `/legal/privacy-policy` are recognized. Exact path
segments are required, so a slug such as `/blog-post` does not accidentally
become the `blog` route family.

`other` is an abstention. It is not treated as a proven `WebPage`, and
page-kind-specific rules are not scored for it.

Confidence is consumed, not merely recorded. Every page-kind-scoped rule
declares how it relates to the classification:

- **expectation** — asserts something should be present *because of* the page
  kind. Only as sound as the classification behind it.
- **triggered** — validates an artifact that is actually present, and already
  resolves not-applicable when it is absent.
- **universal** — not page-kind-scoped.

An expectation **defect** requires structural evidence: page-owned structure
the classifier read from the page itself. A kind established only from a URL
path segment or from bounded title/content semantics yields
`not_applicable` with reason `low_confidence_kind` instead, so a page inferred
to be an FAQ because its path contains `/support/` is never accused of missing
FAQ structure. Advisories are offered at every tier, because an opportunity
costs nothing when the guess is wrong. Triggered validation runs at every tier,
because its trigger is the artifact rather than the classification.

The gate keys on the evidence tier rather than the confidence label:
`_confidence` demotes structural evidence to `medium` whenever any other signal
disagreed, so reading the label alone would suppress checks on pages whose own
structure proved what they were.

## Page traits

`page_kind` is exclusive and answers "what is this page for". A **trait** is
additive and answers "what else is on it":

```text
has_faq, has_reviews, has_variants, listing, local_intent,
contact_intent, about_intent, case_study_intent, review_intent,
comparison_content, procedural
```

A product page carrying an FAQ block is a `product` with `has_faq`, and answers
both checklists, rather than being filed as one or the other or requiring a
`product_with_faq` kind that would never cover the combinations.

Traits also separate the two kinds that bundle unlike pages. `about_contact`
mixes pages with different success criteria — demanding contact details of
`/about/our-story` invents a fault, while not checking them on `/contact-us`
misses an improvement — and `case_study_review` mixes "problem, intervention,
result" with "item, evaluator, verdict". `aeo.author_present` therefore no
longer applies to `case_study_review`, and `aeo.reviewer_identified` asks for
an evaluator on any page observed to carry `review_intent`, whatever its kind.

Derivation is pure, deterministic, bounded, and versioned (`TRAITS_VERSION`).
It reads the same page facts as the classifier but never reads `page_kind`, so
a trait is an observation rather than a consequence of the classification. That
is also why a trait-scoped rule (`page_trait:` / `page_trait_content:`) is not
gated by classification confidence: there is no classification behind it.

A trait is deliberately stricter than the classifier signal it resembles.
`has_faq` requires FAQPage markup or subheadings that literally end in a
question mark, where the classifier's FAQ signal accepts a heading opening with
what/why/how — right for a signal resolved by tier precedence against
competitors, wrong for a standalone assertion that whatever keys on it fires
with no second opinion.

Observed traits persist on `SitePageAnalysis.page_traits` as a queryable array
and appear on the per-URL detail beside the page kind.

## Content sufficiency

There is no magical minimum word count and no ideal page length, so length is
evidence, never the verdict. `technical.thin_content` reports an **empty** page,
not a short one: one low universal floor (`MIN_MEANINGFUL_WORDS`) replaces the
former per-kind ladder of 40 to 300 words, and the word count is recorded as
evidence rather than as the judgement.

Below the floor a page can still prove itself structurally — a category page
that actually lists items, a location page carrying findable details, a product
or pricing page showing a price, a contact page handing over a way to reply, an
about page identifying the entity. Those signals only ever ADD a way to pass;
none of them can fail a page the floor would have passed, so the check reports
fewer pages than the floor alone would, never more.

A page kind with no structural signal is judged on the floor alone. That is the
correct answer rather than a gap: a 150-word article is short, not defective,
and nothing in the crawl can tell those apart.

## Structured-data extraction and schema contracts

The bounded extractor reads JSON-LD graphs and shallow microdata. It normalizes
schema.org URL types, retains every recognized token from a multi-typed
`@type` array, extracts only config-owned property paths, and skips malformed
blocks without failing the page.

`PAGE_KIND_EXPECTED_SCHEMA` owns allowed schema alternatives and their required
and recommended property contracts. Properties are resolved for the actual
schema type used, not once for the whole page kind. For example:

- a guide may use `HowTo.name` or `Article.headline`;
- `WebSite` does not inherit `Organization.sameAs`/`logo` recommendations;
- `CollectionPage` is not incorrectly required to carry
  `BreadcrumbList.itemListElement`;
- Article and ItemList alternatives on comparison pages use their own fields.

Schema handling is validation-first, not presence-first. Absent markup is an
opportunity, never a page defect: structured data helps a search engine
understand a page and can unlock specific features, but it has never been
required, and no special markup is needed to be read by an answer engine.
Markup that is present and contradicts the visible page is a real defect, and
`aeo.schema_matches_content` owns that finding.

Required properties are therefore only those a present block genuinely needs.
`Article` requires `headline` alone, with `author` and `datePublished` as
recommendations. `FAQPage` and `HowTo` require nothing at all — both describe
retired rich-result features, so their absence cannot be scored and their shape
cannot be a contract, while a present-but-contradictory block stays reportable.

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
- Date rules also include documentation.
- Question-heading rules apply to FAQ pages only, and are not applicable to a
  page with no h2/h3 subheadings at all: no sections is a different fact from
  badly phrased sections.
- Answer-first structure applies to FAQ, guide, and docs pages, as an advisory.
  A service page, a comparison, a case study, or a narrative article carries no
  obligation to open with a direct answer.
- A canonical declaration that points away from the page is not a conflict —
  consolidating a sorted, filtered, or tracked URL onto its parent is what the
  element is for. Only positive evidence of a broken target fails: a canonical
  that is unresolvable, points to another origin, or points at a different
  hreflang alternate of the same page. Campaign and click parameters are
  removed before the comparison, and a relative canonical is resolved against
  the page URL first.
- Product offer and visible/schema parity rules apply only to product pages.
- Architecture depth, breadcrumb-conflict, and duplicate-family-metadata rules
  report positive observations at any coverage. Orphan, parentless-detail,
  unhubbed-family, and sitemap-orphan absence claims require complete coverage;
  otherwise they are `not_applicable` with `coverage_not_complete`.

A JS shell receives one server-rendering finding. Rules that need unseen body
content remain not-applicable instead of producing a cascade of fabricated
missing-content issues.

## Provenance

`SitePageAnalysis` is UUID-identified and append-only. Repeated analyses may
reference the same immutable artifact; only one row per page in a crawl is
current. Rule rows carry rule version and exact source IDs. Any change to extraction,
classification, analysis semantics, or the rule catalog must bump its config
version so an old artifact is never silently reinterpreted as the same result.

Grouped issue IDs are deterministic UUID5 values derived from the crawl and
rule. Filtering or adding another occurrence cannot change the group URL;
legacy occurrence IDs remain accepted by the detail endpoint.

Every failed evaluation freezes both rule `description` (what is wrong) and
`remediation` (how to fix it) onto `SiteIssue` with its analyzer/catalog
versions. Group, detail, per-page, and history projections read that stored
copy and never substitute the current catalog. The Issues row shows severity,
plain-language title, frozen description, an affected-page evidence chip, and
page-kind scope; remediation appears when the row expands.

Every rule also owns a versioned `finding_class`: `defect` for a reproducible
problem and `advisory` for deterministic but opinionated guidance.

**Only defects score.** Advisory evaluations are excluded from scoring
entirely — pass, fail, and error alike — so guidance can neither lower nor
raise a health score. Excluding advisory passes matters as much as excluding
advisory failures: a page must not be able to lift its score by satisfying an
opinion. `weight` is therefore only meaningful on a defect.

Advisories are: title and meta-description length bands, meta-description and
canonical presence, structured-data and Open Graph presence, expected-schema
and recommended-schema properties, answer-first structure, collapsed-content
gating, and an indexability finding whose intent could not be established.
Defects and advisories have separate server-filtered views. The headline is the number of distinct defect
issue types by default and distinct advisory issue types in the advisory view;
supporting metrics explicitly name the selected class's occurrences and
affected URLs. Only defects feed severity filters and Opportunities. The
per-evaluation rows remain append-only evidence regardless of class.

Indexability follows strong-evidence precedence: explicit user policy, then a
canonical declaration, sitemap membership, then robots evidence. Explicitly
intended exclusion is not applicable; intended indexing contradicted by
`noindex` is a defect; genuinely unknown intent is an uncertain advisory and
never critical. Promo-like paths and missing inbound links are not intent
evidence. Host-scoped and template-scoped evaluation remain out of scope: the
current per-page evidence is retained, and no dormant scope configuration or
placeholder identity owner is introduced.

Current versions are owned in the focused `backend/app/core/config/site_health_*`
modules. The false-positive hardening slice ships extractor `sh-extractor-13`,
classifier `sh-classifier-9`, analyzer `sh-analyzer-8`, rule catalog
`sh-rules-7`, and scoring `sh-scoring-5`. Scores are not comparable across the
scoring-version boundary, and Change Intelligence correctly reports pairs that
straddle it as `non_comparable` rather than as regressions. An unclassified `other` page retains
its Technical score but has no AEO score; its count remains visible in the
page-kind rollup. Coverage uses `sh-coverage-1`,
internal-link metrics use `sh-link-metrics-1`, architecture uses
`sh-architecture-1`, and the archetype policy uses `sh-archetypes-1`; tests pin
persistence and replay behavior.

## False-positive contract

`backend/tests/unit/test_site_health_fixture_contracts.py` holds a fixture per
page shape, each stating both the findings it must produce and the findings it
must never produce. Most fixtures are correctly built pages; one is
deliberately broken so no rule can be neutralised into silence and still pass.

`KNOWN_FALSE_POSITIVES` in that module lists the defects a valid page still
produces, and the suite asserts the list is exact in both directions — it
cannot grow to cover new breakage, and a stale entry fails once its fix lands.
Any new page-kind check belongs here before it ships.

## Known boundary

The simplification removed the former knowledge assertion source used to ground
content briefs. Content generation currently receives an empty fact/source
envelope. Replacing that source requires a separate product decision; Site
Health analysis must not invent durable facts merely to fill it.

## Focused verification

From `backend/`:

```bash
uv run pytest tests/unit/test_site_health_fixture_contracts.py \
  tests/unit/test_site_health_page_kinds.py \
  tests/unit/test_site_health_parser.py \
  tests/unit/test_site_health_rules.py \
  tests/unit/test_site_health_scoring.py \
  tests/component/test_site_health_analyze.py \
  tests/component/test_site_health_discover.py -q
uv run ruff check app/analysis/site_health app/core/config/site_health_*.py
```
