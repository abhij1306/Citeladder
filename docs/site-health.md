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
- Discovery runs the complete bounded fact extractor on each acquired HTML
  response and freezes those facts on its immutable artifact. Analysis reuses
  that same artifact when the crawl's required extractor version matches, so
  discovery and analysis retain separate lifecycle results without a second
  HTTP acquisition. If no complete current-version discovery artifact can
  exist (including a Free sample analyze-only URL), analysis uses the normal
  secure acquisition fallback. An analyze task that races an active discovery
  task is durably deferred without consuming a network-attempt budget.
- Append-only fetch-attempt rows are also the bounded per-crawl host transport
  observations; the frozen crawl configuration is never mutated. Two
  consecutive rung-1 `403`/`429` outcomes prefer rung 2 for the next 20 host
  acquisitions, followed by one rung-1 recovery probe. A successful probe
  immediately restores rung 1; another `403`/`429` starts a fresh interval.
  Timeouts and `5xx` evidence use ordinary retry policy and never pin a rung.
- Anchor extraction may repair an encoded query delimiter only when the first
  encoded suffix key is a config-owned tracking parameter. That boundary-only
  rewrite interprets encoded `=` and `&` separators in the identified query,
  runs ordinary query normalization, and freezes its reason and rewrite version
  on the immutable URL observation. Legitimate `%3F`, `%26`, `%2F`, and `%25`
  path content remains byte-preserving crawler identity; `canonicalize()` and
  `canonical_identity()` retain their reserved-escape semantics.
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

Terminal evidence refresh follows one transactionally idempotent DAG for
completed, partially completed, and cancelled-after-analysis crawls. Usable
evidence first enqueues the crawl-scoped link graph. Only after that immutable
snapshot commits does a current Traffic snapshot route through Demand and then
Opportunities; without Traffic input, the graph routes directly to
Opportunities. The successors never race their graph predecessor, and repeated
terminalization, cancellation, or graph-task recovery cannot duplicate a
logical refresh. A cancellation before any usable analysis enqueues none.

## Internal-link graph

Site Health builds one immutable graph snapshot from the exact current,
successful HTML analyses of one crawl and records their analysis/artifact IDs,
page-analyzer/extractor versions, a source hash, coverage, and limitations.
`SiteLinkReference` remains the only link-evidence store. Anchor targets resolve
through an in-scope target artifact/final URL when present and otherwise by the
crawl's canonical `SiteUrl`; URL fragments never create nodes. External and
unresolved targets remain counted evidence, not authority nodes.

Repeated anchors for one ordered source/target pair collapse to one unit-weight
topology edge while retaining occurrence counts, bounded anchor texts, and
followed/nofollow observations. Anchor-level `rel=nofollow` and page-level
robots nofollow exclude the observation from PageRank and BFS without deleting
it. Deterministic PageRank uses damping `0.85`, tolerance `1e-8`, at most 100
iterations, and standard dangling-mass redistribution. Click depth is BFS from
the configured root; unreachable remains unknown.

Near-orphan, weak-authority, over-linked, hub, authority-concentration, and
anchor-distribution metrics use the config-owned WS4 thresholds. Suggested
sources use only PageRank plus normalized path/title token Jaccard and return at
most three stable candidates; no embeddings exist. Partial or bounded crawls
remain `incomplete`, disclose observed coverage, and provide descriptive
topology only. The existing `technical.sitemap_orphan` finalize evaluation
remains the sole sitemap-orphan owner.

Persisted reads are exposed at the project Site Health `link-graph`, `nodes`,
and `edges` endpoints. Optional `crawl_id` selects an exact persisted snapshot;
omission selects the latest. Node and edge pages use snapshot-bound cursors and
never compute, repair, crawl, or enqueue work.

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

Every failed evaluation freezes both rule `description` (what is wrong) and
`remediation` (how to fix it) onto `SiteIssue` with its analyzer/catalog
versions. Group, detail, per-page, and history projections read that stored
copy and never substitute the current catalog. The Issues row shows severity,
plain-language title, frozen description, an affected-page evidence chip, and
page-kind scope; remediation appears when the row expands.

Every rule also owns a versioned `finding_class`: `defect` for a reproducible
problem and `advisory` for deterministic but opinionated guidance. Title- and
meta-description length bands are advisories. Defects and advisories have
separate server-filtered views. The headline is the number of distinct defect
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
