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

1. **Site Health** — crawl lifecycle, scores by page kind, and URL inventory.
2. **Issues** — grouped findings with affected page-kind badges.
3. **Opportunities** — persisted prioritized actions.

The removed Site Intelligence workspace and industry-pack/knowledge subsystems
must not be reintroduced as parallel owners.

## Pipeline

```text
explicit user Run new crawl -> seed + sitemap + internal links
  -> URL admission and corpus disposition
  -> secure_httpx -> curl_cffi -> patchright acquisition ladder
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
  analysis, link checking, snapshot creation, and terminal completion. Its
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
- `analyze`, `inventory_only`, and `exclude` dispositions stay distinct.
- Supported documents may remain inventory-only and never enter the HTML rule
  evaluator.
- The screen phase is resolved once by the backend. Worker bookkeeping states
  are not independently reinterpreted by the frontend.

## Crawl controls, limits, and progressive UI

The production path is one standard crawl: its frozen requested-page cap and
default are **500**. Advanced input, seed, page-kind, and oversized limits are
development-only; when enabled there, the separate discovery and analysis
ceilings are **50,000**. These are configuration-owned operational bounds, not
throughput promises.

Before any crawl, Site Health shows one empty placeholder with **Run new
crawl**. Once a crawl exists, the header exposes one contextual primary control:
**Stop crawl** while its persisted status is active, otherwise **Run new
crawl**. **Export** is secondary. There are no separate user controls for
discovery or analysis. A paused historical crawl remains eligible for **Run
new crawl**; read endpoints never repair or reinterpret its persisted state.

The inventory stays mounted as the crawl progresses. During discovery it shows
the first ten persisted rows as they arrive; once scoring is available, those
same persisted rows enrich in place rather than moving the user to a separate
analysis screen. Issue/remediation copy uses the persisted remediation text as
its subtitle, so the UI does not manufacture a second recommendation.

## Page-kind classification

Every analyzed HTML page receives one of:

```text
homepage, article, product, category, pricing, docs, faq,
about_contact, service, local, guide, comparison,
case_study_review, trust_policy, other
```

Classification is pure, deterministic, bounded, and versioned. Signals run in
this priority order:

1. root/homepage path equivalence;
2. the semantic URL path segment nearest the root;
3. bounded visible-content heuristics for FAQ, product, and article pages;
4. explicitly prioritized recognized schema types.

Path/content evidence outranks schema because schema is a page's claim about
itself. Letting that claim select the contract used to validate it would make
schema analysis circular. Conflicts, alternatives, confidence, winning signal,
and schema suggestion persist on `SitePageAnalysis.page_kind_evidence`.

Nested route families such as `/resources/guides/...`,
`/company/contact-us`, and `/legal/privacy-policy` are recognized. Exact path
segments are required, so a slug such as `/blog-post` does not accidentally
become the `blog` route family.

`other` is an abstention. It is not treated as a proven `WebPage`, and
page-kind-specific rules are not scored for it.

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

Schema rules require both a classified non-`other` page kind and an HTML
response. Content-parity rules additionally require visible server-rendered
body content.

## Rule applicability

Not-applicable is different from pass and is excluded from scoring.

- Technical delivery, indexability, metadata, and rendering rules remain
  broadly applicable where their source evidence exists.
- Schema presence/type/property rules apply only to classified page kinds.
- Author and citation rules apply only to authored editorial types.
- Date rules also include documentation.
- Question-heading rules apply to FAQ, guide, docs, and article pages.
- Answer-first structure applies to article, FAQ, guide, docs, service,
  comparison, and case-study/review pages.
- Product offer and visible/schema parity rules apply only to product pages.

A JS shell receives one server-rendering finding. Rules that need unseen body
content remain not-applicable instead of producing a cascade of fabricated
missing-content issues.

## Provenance

`SitePageAnalysis` is append-only per artifact and analyzer version. Rule rows
carry rule version and exact source IDs. Any change to extraction,
classification, analysis semantics, or the rule catalog must bump its config
version so an old artifact is never silently reinterpreted as the same result.

Grouped issue IDs are deterministic UUID5 values derived from the crawl and
rule. Filtering or adding another occurrence cannot change the group URL;
legacy occurrence IDs remain accepted by the detail endpoint.

Current versions are owned in `backend/app/core/config/site_health.py`; tests
pin persistence and replay behavior.

## Known boundary

The simplification removed the former knowledge assertion source used to ground
content briefs. Content generation currently receives an empty fact/source
envelope. Replacing that source requires a separate product decision; Site
Health analysis must not invent durable facts merely to fill it.

## Focused verification

From `backend/`:

```bash
uv run pytest tests/unit/test_site_health_page_kinds.py \
  tests/unit/test_site_health_parser.py \
  tests/unit/test_site_health_rules.py \
  tests/component/test_site_health_analyze.py \
  tests/component/test_site_health_discover.py -q
uv run ruff check app/analysis/site_health app/core/config/site_health.py
```
