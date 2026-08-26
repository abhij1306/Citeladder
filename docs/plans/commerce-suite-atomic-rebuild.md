# Commerce Suite atomic rebuild

> **Status:** implemented
> **Authority:** historical delivery sequence. [`../commerce-intelligence.md`](../commerce-intelligence.md)
> is the shipped-runtime reference.

## Outcome

CiteLadder turns an ecommerce catalog into buyer-intent tracking and shows
which individual products are winning or losing inside AI recommendations.

The rebuild keeps one four-stage workspace at the existing `/products` route:

```text
Catalog -> Competitors -> Buyer Prompts -> AI Shelf
```

Commerce specializes existing owners. It reuses Site Health acquisition and
page understanding, Topics and Prompts, provider configuration, audit
execution, raw responses, citations, scheduling, PostgreSQL queues, workspace
authorization, and repository validation. It does not add a second crawler,
page analyzer, prompt store, audit runner, citation store, or external-memory
system.

The immediate Friday audience is Feedonomics. Best&Less is a difficult,
real-world reference corpus and the following Wednesday's presentation site;
it is not the architecture target. Production behavior must remain generic
across apparel, electronics, furniture, CPG, beauty, automotive,
marketplaces, and other ecommerce catalogs.

## Locked product decisions

### Product identity

- One canonical PDP URL is one Commerce product and one metric entity.
- Separate PDP URLs remain separate products even when they share a style,
  ProductGroup, SKU family, title, or catalog identifier.
- The canonical URL uses the existing Site Health URL identity. Commerce does
  not introduce alternate URL normalization.
- ProductGroup, variant, and related-PDP evidence is retained, but Phase 1
  does not create a family aggregate, family dashboard, or per-variant metric.
  A first-class product-family table is deferred until a user-facing family
  behavior needs it.
- Generic product fields are canonical URL, name, description, brand,
  price/currency, SKU, GTIN, MPN, category memberships, variants, normalized
  attributes, lifecycle state, and provenance. Domain-specific facts such as
  colour, material, flavour, dimensions, or storage belong in versioned
  attributes rather than permanent vertical-specific columns.
- A URL tail or retailer style code may be retained as an observed external
  identifier. It must never be promoted to SKU, GTIN, MPN, or barcode without
  explicit page or CSV evidence.

### Site Health reuse and progressive catalog projection

The ownership boundary is:

```text
explicit Site Health crawl
  -> immutable fetch artifact + normalized facts
  -> SitePageAnalysis page kind and evidence
       -> Site Health rules/scores
       -> idempotent Commerce catalog projection
```

- Site Health remains the only acquisition and page-understanding owner.
  Commerce never reparses raw HTML independently or reclassifies a page.
- Phase 1 uses only the response artifacts acquired by the existing Site
  Health HTTP crawler. It does not add Playwright, a browser service, sampled
  rendering, or any other JavaScript-rendering path. A detected JavaScript
  shell remains an explicit `not_applicable`/unavailable evidence state; it is
  not treated as empty product content or repaired by Commerce.
- Extend Site Health normalized facts and `SitePageAnalysis` evidence where
  necessary to preserve generic product-card relationships, breadcrumb and
  taxonomy evidence, and category role.
- Category pages expose a deterministic role of `hub`, `leaf`, or `unknown`.
  A hub contains navigation/subcategory evidence; a leaf contains supported
  PDP-card evidence. A subcategory or filter link is never emitted as a
  product.
- Category evidence precedence is breadcrumb/structured taxonomy, schema
  category, navigation relationship, URL/title, then bounded structured-model
  adjudication only for unresolved cases. Low confidence abstains to
  `Uncategorized`; categories remain editable.
- Add an idempotent Commerce projection task to the existing PostgreSQL queue
  for each eligible persisted analysis. Its key includes source analysis ID
  and projector version. Reads never start or repair projection work.
- Commerce may show products/categories progressively as projection tasks
  complete. Starting catalog discovery from Commerce calls the existing
  explicit Site Health crawl mutation and reuses an active or usable crawl
  rather than creating another traversal.
- Phase 1 may keep the current combined discovery/analysis admission path.
  Commerce rows reference acquisition and analysis provenance separately so a
  future split between large-catalog discovery and sampled Site Health rule
  evaluation does not require a Commerce schema rewrite.
- Raise only the technical/development requested crawl ceiling to 500 URLs.
  Do not change paid-plan allowances or pricing. The dev/demo workspace uses
  the existing audited operator override for a 500-URL allowance.

### Catalog persistence and CSV precedence

The replacement schema has one Commerce catalog owner:

- Current category, product, and product-category membership projections.
- Append-only product observations referencing exactly one crawl artifact and
  analysis or one immutable CSV import and row number, with extractor,
  classifier, importer, and projector versions.
- An immutable bounded CSV import artifact containing the content hash,
  source metadata, supported raw payload, row outcomes, and aggregate counts.
- Field-level source references on the current product projection so later
  evidence cannot silently erase provenance.

CSV identity precedence is canonical URL, then GTIN, then SKU. If identifiers
on one row resolve to different existing products, that row is rejected as a
conflict and neither product is changed.

CSV imports use these merge rules:

```text
non-empty supplied value -> CSV overrides the current field
empty supplied value     -> no override
missing column            -> no override
omitted product row       -> existing product remains active
```

- Parse and structurally validate the file first. An invalid delimiter,
  unreadable header, unsupported encoding, or over-limit payload rejects the
  file without catalog mutations.
- Within a structurally valid file, validate each row. Commit all valid rows
  and immutable row outcomes in one transaction; rejected rows do not block
  valid rows. An unexpected database failure rolls back the whole import.
- Return `created`, `updated`, `unchanged`, and `rejected` counts plus bounded
  row-numbered errors.
- A later crawl may fill a field never claimed by CSV, but it cannot overwrite
  a non-empty CSV-authoritative field. A later non-empty CSV value or explicit
  Catalog edit can correct a bad imported value. Clearing a CSV-owned field is
  allowed only through the explicit Catalog edit mutation; a blank CSV cell
  remains a no-op. The edit records its own immutable provenance instead of
  silently rewriting the original import artifact.

### Analysis targets and competitor intelligence

Every downstream request uses one typed target:

```text
CommerceTarget = { kind: "category" | "product", id: UUID }
```

- Category analysis aggregates all owned products with persisted membership
  in the selected category. Product analysis measures one canonical PDP.
- Commerce adds no arbitrary selection count. Existing prompt occupancy,
  audit-task, abuse, and provider-capacity guards remain authoritative; the UI
  shows estimated work and rejects an oversized request without truncating it.
- Tavily is optional pre-audit context. One locale-aware search per selected
  target may yield at most five surviving substitute-product candidates.
- Product targets produce competing products. Category targets produce
  competing brands plus representative products. A competitor category page
  is never a durable competitor entity.
- Persist every Tavily request/result attempt immutably with query, locale,
  provider version, and validation outcome. Commit the queue task before
  network I/O and make retries idempotent.
- Reuse the secure URL policy/fetch boundary to verify candidate URLs.
  Deterministically reject owned-domain, unsafe, duplicate, dead, obvious
  editorial/category, incompatible second-hand, and clearly wrong product
  results when the evidence supports that decision. Ambiguous results remain
  excluded rather than guessed.
- Show at most five verified candidates per target. Every survivor requires
  explicit approve/reject. Tavily failure, missing credentials, or zero
  candidates never blocks prompt generation or AI-observed discovery.
- Tavily is not a catalog-crawl fallback in Phase 1.

The implementation may use the configured Tavily key for a small real
contract/evaluation run. Automated tests remain mocked. A maximum of 100 live
calls is a coding-session safety reference, not a product entitlement,
connector counter, persisted quota, or runtime behavior. The implementer keeps
and reports the exact count. The key must never be printed, logged, persisted,
snapshotted, or committed.

### Buyer prompts and audit execution

- Reuse Topic, PromptSet, Prompt, prompt editing, provider selection,
  repetitions, estimation, audit execution/repair, and scheduling.
- Link each generated Commerce prompt to exactly one CommerceTarget through a
  typed persisted relation. Freeze that target and its current catalog,
  locale, approved-competitor, prompt-template, parser, and formula versions
  into the audit plan.
- Prompt count is request-configurable: minimum 2, default 5, maximum 10 per
  selected target. These values live in Commerce configuration, not services.
- Generated prompts are locale-aware, unbranded with respect to the owned
  brand/product, buyer/use-case aware, attribute/constraint aware, and suitable
  for discovery or comparison intent. The selected product informs the
  question but must not reveal the intended answer.
- Generated Commerce prompts persist disabled. Users edit/select and
  explicitly approve them before the existing launcher can execute them.
- The model gateway is bounded and structured. If unavailable, return a clear
  unavailable state and permit manual prompt entry; do not substitute a weak
  deterministic template or a hidden live provider call.
- Codex implementation and automated verification must use mocked structured
  model and answer-provider responses. No live OpenAI, Anthropic, Gemini,
  OpenRouter, or other LLM/provider credential may be used. The user performs
  credentialed validation after the PR is ready.

### Recommendation observations and matching

The Commerce response parser uses:

```text
deterministic recommendation-span and identity matching
  -> bounded structured-model resolution for unresolved spans only
  -> append-only observations
```

Deterministic matching considers canonical/product URL, GTIN, SKU/MPN,
normalized exact name, brand plus attributes, and approved competitor
mappings. Model output may resolve bounded ambiguity but never overwrite
authoritative catalog facts, invent identifiers, or alter deterministic
metrics.

Persist one observation for each recognized recommendation with:

- raw response/execution and target IDs;
- observed product and brand;
- classification as owned, approved competitor, AI-observed competitor, or
  unresolved;
- observed title and price without changing expected catalog values;
- merchant URL/domain;
- surface kind (`recommendation` or `shopping_result`);
- nullable rank and `order_observable`;
- match confidence and exact deterministic/model/parser versions.

Rank is assigned only for explicit numbered/ordered recommendations or a
provider product-card order. Sequential prose does not establish rank:

```text
explicit order/card order -> order_observable=true, rank=1..n
unordered prose           -> order_observable=false, rank=null
```

Unknown recommendations are retained. An unknown product may appear
immediately as AI-observed evidence, but explicit promotion is required before
it becomes a tracked competitor for later analyses.

Competitor, merchant, and citation remain separate concepts. Recommendation
observations may reference existing Citation rows through typed associations;
they do not copy or reinterpret citation ownership. A retailer recommendation
that cites Reddit records a competitor product, a possible merchant, and a
Reddit citation—not three competitors.

### AI Shelf metrics

Persist immutable formula-versioned snapshots for each audit and target. Do
not add a composite Commerce score.

1. **Product Visibility**

   Product target: successful eligible executions containing that owned
   product divided by all successful eligible target executions. Category
   target: executions containing any owned member of the category divided by
   all successful eligible target executions.

2. **Share of Shelf**

   Recognized owned recommendation slots divided by all recognized product
   recommendation slots. Arbitrary brand mentions are excluded.

3. **Average Shelf Position**

   Mean one-based rank of owned appearances using only observations with
   `order_observable=true` and non-null rank. It is unavailable when no ranked
   owned appearance exists.

4. **First-Position Win Rate**

   Successful executions whose first recognized ranked recommendation is
   owned divided by successful executions containing at least one ranked
   recommendation. An answer with no ranked products is not a position loss.

Competitor co-occurrence, prompt gaps, citation sources, merchant evidence,
and expected-versus-observed title/price are supporting evidence, not headline
scores. Unknown, unavailable, failed, unranked, excluded, and observed zero
remain distinct.

AI Shelf copy must explain that Share of Shelf includes every recognized
recommendation slot, while position metrics use only explicitly ordered
recommendations. The metrics can therefore move differently without either
being inconsistent.

## Public interfaces and workspace

Keep `/products` as the unconditional Analyze destination and replace its
current tabs atomically with:

1. **Catalog** — CSV or existing Site Health discovery, crawl/projection
   progress, categories/hub roles, canonical-PDP products, provenance, and
   row-level import results.
2. **Competitors** — category/product target selection, optional Tavily job
   status, evidence, and approve/reject decisions.
3. **Buyer Prompts** — target selection, configurable 2-10 generation count,
   edit/select/approval, and the existing audit launcher.
4. **AI Shelf** — persisted target/product/category metrics, provider/prompt
   filters, observations, raw-response drill-down, citations, and history.

The cutover deliberately removes the old Overview and AI Visibility tabs, the
Commerce-local Opportunities surface, and `/products/[productId]`. Catalog
rows and AI Shelf observations use inline detail/drill-down within the four-tab
workspace; they do not navigate to a replacement product-detail route. The
shared `/opportunities` product remains owned by the Opportunity subsystem and
is not removed with the Commerce-local surface.

The API remains same-origin under `/api/v1` and introduces one
`/projects/{project_id}/commerce/*` family for catalog reads/mutations,
competitor discoveries/decisions, prompt generation, and AI Shelf reads.
Existing prompt and audit APIs remain their owners. Backend and frontend
schemas change together. Every object-ID endpoint re-resolves the project and
active workspace; no query trusts an ID alone.

The old Commerce product, feed/order, Commerce-attribution, visibility, prompt
shim, API, frontend contract, tests, configuration, sample CSV, and
documentation are deleted in PR 1. The shared Opportunity owner stays, but its
legacy Commerce detectors and imports are removed or retargeted to the new
typed Commerce evidence in the same cutover. The existing Attribution domain
is Commerce-owned today and is retired; no dangling `Product` relationship,
worker import, API schema, contract-drift entry, or project relationship may
remain. Revenue attribution is explicitly deferred rather than recreated in
the replacement catalog.

No compatibility bridge is retained because CiteLadder is pre-launch and no
current external caller has been identified. PR 1 begins by writing a concrete
retirement manifest of exact routes, model names, task kinds, config constants,
frontend exports/routes, tests, fixtures, and documentation. That manifest—not
a broad grep for `product`—drives the final absence search. If a real external
contract is found, stop and record its focused compatibility/deletion
condition rather than guessing.

### Version lineage to inventory

PR 1 records a before/after version manifest next to its retirement manifest.
The current relevant namespaces are Site Health acquisition
`sh-acquisition-2`, extractor `sh-extractor-8`, analyzer `sh-analyzer-4`, page
classifier `sh-classifier-3`, rule catalog `sh-rules-4`, scoring
`sh-scoring-2`, legacy Commerce importer `commerce-importer-1`, legacy product
analyzer `product-analysis-3`, and legacy product scoring
`product-scoring-v2`.

Only behavior that changes is bumped. Because Phase 1 does not change the HTTP
acquisition mechanism or add rendering, the acquisition-policy version is not
bumped solely for this rebuild. New config-owned namespaces are defined once
for the Commerce catalog projector, catalog importer/edit policy, competitor
validator/provider contract, prompt template, recommendation parser/matcher,
and AI Shelf formulas. Persisted derived rows record the exact relevant
versions; the manual gate compares the before/after manifest rather than
relying on a generic instruction to “bump versions.”

## Four gated pull requests

Each PR must leave the repository runnable, pass the repository gates, receive
manual approval, and merge before the next begins.

PR 1 is intentionally a large atomic cutover. It may be internally implemented
in dependency order, but it is not split into coexistence PRs: the repository
must never have two Commerce catalog authorities or a half-retired schema.

### PR 1 — Generic catalog foundation

- Produce the exact retirement and dependency manifest, then atomically remove
  the superseded Commerce implementation. Resolve the current Product imports
  in Attribution, Opportunities, audit terminalization, project relationships,
  API contracts, and frontend drill-downs as part of the same cutover.
- Fold the replacement schema into `migrations/versions/0001_initial.py`; reset
  only an explicitly resolved disposable dev/test database.
- Extend Site Health extraction/page evidence generically for product cards,
  category hub/leaf distinction, taxonomy, visible price/title, PDP identity,
  and abstention. Do not add JavaScript rendering. Update every affected entry
  in the version manifest.
- Add progressive Site Health-to-Commerce projection, canonical-PDP identity,
  categories/memberships, product observations, CSV merge/import outcomes,
  and the Catalog tab.
- Raise the technical/dev requested crawl ceiling to 500 and document the
  existing 500-URL dev override. Do not edit paid-plan grants.
- Remove Commerce-only demo/sample data. Preserve unrelated marketing/dev
  seeds and deterministic test fixtures.
- Add the non-blocking Reference Commerce Eval reporter and run it against the
  supplied Best&Less snapshot.

Manual gate: migrate a disposable database from scratch, run a selected seeded
crawl, observe progressive catalog rows, verify hub/leaf behavior, import a CSV
with valid and invalid rows, verify correction and explicit clearing, and
inspect the reference-eval mismatch report. Reference mismatches inform
debugging but cannot fail this gate by count or percentage.

### PR 2 — Optional competitor discovery

- Add the Tavily connector, existing-queue task kind, immutable attempts,
  locale-aware product/category queries, deterministic candidate validation,
  five-result maximum, and approve/reject decisions.
- Build the Competitors tab without making it a prerequisite for Buyer
  Prompts.
- Add mocked contract/negative tests and, if credentials are available, one
  bounded live contract/eval run with the exact call count reported.

Manual gate: supply the Tavily key, discover product and category competitors,
verify product-versus-category/editorial filtering, approve/reject candidates,
and confirm missing/failed Tavily does not block the next tab.

### PR 3 — Buyer prompts and existing audit runner

- Add typed prompt-target mappings and configurable 2-10 generation with
  default 5.
- Generate disabled, unbranded, locale/attribute/constraint-grounded prompts;
  support edit/select/explicit approval.
- Reuse the existing provider launcher, repetition controls, execution
  estimate, audit-capacity checks, repair, and schedules.
- Freeze the complete Commerce measurement context into each audit without
  duplicating prompt or audit persistence.
- Use mocked model/provider responses only during implementation.

Manual gate: the user supplies model/provider credentials, generates and edits
prompts for a category and product, verifies no owned-name leakage, reviews the
execution estimate, approves prompts, and launches a Commerce audit.

### PR 4 — Recommendation parser and AI Shelf

- Add deterministic matching plus mocked structured-model resolution,
  append-only recommendation observations, typed Citation associations,
  merchant fields, AI-observed competitors, nullable rank, and explicit order
  observability.
- Persist the four metric snapshots with exact formulas and versions.
- Build AI Shelf filters, product/category results, supporting evidence,
  raw-response drill-down, immutable history, and existing schedule
  compatibility.
- Complete the Commerce authority/docs cutover and prove superseded names are
  absent.

Manual gate: inspect a credentialed audit against raw answers, verify ranked
and unranked observations, promote an AI-observed competitor, confirm merchant
and citation separation, and repeat the measurement through the existing
schedule path.

## Reference Commerce Eval

The canonical supplied reference files are:

- `docs/evaluations/bestandless_commerce_catalog_eval_100.json`
- `docs/evaluations/bestandless_commerce_catalog_eval_README.md`

The JSON currently contains 10 categories, 10 products per category, 100
products, and 100 unique PDP URLs. CSV or NDJSON versions are optional
convenience representations if supplied later; their absence cannot block PR
1, and they must remain semantically identical to the canonical JSON.

The reference evaluator is separate from unit/component fixtures. It accepts
an exported Commerce catalog plus the dated expected JSON and produces a
machine-readable and human-readable comparison report. It does not fetch
pages, modify expected data, import reference values into production behavior,
or decide whether PR 1 passes. The dataset is a diagnostic reference snapshot,
not ground truth or a hard acceptance gate: products, category membership,
titles, prices, availability, canonical URLs, and even live URLs can change.

For the live reference run:

1. Create a disposable authorized dev workspace with AU/en locale and a
   500-URL override.
2. Before the full run, inspect one category seed through the ordinary HTTP
   acquisition path and record whether product-card/PDP evidence is present in
   the persisted response artifact. This is a diagnostic preflight only; an
   absent client-rendered grid does not trigger browser-rendering work.
3. Use the dataset's ten category URLs as explicit evaluation seed inputs
   through existing development crawl controls. They are test inputs, never
   production rules.
4. Run the ordinary crawler and Commerce projector, then export the persisted
   catalog. When useful, run a separate extraction diagnostic with the known
   PDP URLs as explicit disposable-workspace seeds; do not count those URLs as
   category-discovery successes.
5. Compare the export with the reference JSON and retain the report outside
   application seed data.

The report always shows these structural and observational measures, without
pass/fail thresholds:

```text
reference PDP URLs observed / missing / redirected / unavailable
expected category memberships observed / missing / changed / unavailable
category or subcategory URLs emitted as products
identifier provenance violations
duplicate canonical product rows
normalized title matches / differences / unavailable
displayed-price matches / differences / unavailable
JavaScript-shell or otherwise acquisition-unavailable pages
```

Every title, price, membership, or URL difference is triaged as
`reference_drift`, `extraction_error`, `acquisition_unavailable`, or
`unresolved`. The report preserves both expected and observed values plus the
reference crawl date. It never labels a changed live product or sale price as
an extraction failure without evidence.

The reference `product_identifier`, `style_code`, and `catalog_numeric_id`
fields are evaluation metadata derived from observed URLs. They are not proof
of SKU/GTIN/MPN and are not required production fields. Null description, SKU,
and barcode values are intentionally unasserted, not expected-null outputs.

If the comparison exposes a generic defect, report the exact
URL/category/field evidence and fix the generic behavior. A reference mismatch
alone is not proof of a defect. Never special-case Best&Less, hard-code its
paths or values, change expected outputs to hide a mismatch, guess identifiers,
or omit unavailable cases from the report.

Small deterministic fixtures are the hard automated gates. They separately
cover category hub versus leaf, conventional PDP, JavaScript-shell
unavailability without rendering, variant relationships, missing schema,
missing price, CSV precedence and correction/clearing, conflicting identifiers,
unknown values, workspace isolation, provenance, retries, and idempotency.

## Verification and delivery gates

For each PR, finish the slice and then run once from the repository root:

```powershell
.\scripts\check.ps1
.\scripts\test.ps1
```

PR 1 additionally runs `alembic upgrade head`, `alembic check`, downgrade to
base, and upgrade again against the explicitly disposable database. Tests never
read `.env`; every Tavily/model/provider contract is mocked unless the bounded
manual Tavily check is deliberately invoked.

Required coverage across the four PRs includes:

- workspace isolation for every new read/write and foreign-ID negative case;
- append-only source/attempt/observation provenance and all affected versions;
- progressive projection, retries, concurrency, and idempotency;
- canonical-PDP identity, multiple category memberships, variants, hub/leaf
  abstention, and no category-as-product false positives;
- CSV structural rejection, partial row success, counts, conflicts, non-empty
  precedence, blank no-op, omission retention, correction, and explicit edit
  clearing;
- Tavily safety, locale, deduplication, optional failure, deterministic
  exclusions, and five-result maximum;
- configurable prompt bounds, owned-name leakage rejection, explicit approval,
  frozen measurement context, and oversized-audit rejection;
- owned/approved/observed/unresolved matching, malformed model output,
  provider failure, nullable rank, unordered prose, merchant/citation
  separation, and raw evidence links;
- exact metric denominators, zero versus unavailable, category aggregation,
  and immutable historical snapshots;
- component/E2E coverage for the four progressive tabs and the complete
  catalog-to-AI-Shelf workflow.

After each PR, inspect `git diff --check`, `git diff --stat`, and
`git diff --name-status`. The final cutover also searches routes, imports,
workers, models, config, tests, fixtures, navigation, and active docs for every
retired Commerce name. Formatter changes are reviewed and included; gate
failures are fixed without weakening policies, tests, coverage, mappings, or
complexity ceilings.

## Friday priority and deferrals

When scope must be traded, protect work in this order:

1. Generic catalog architecture and ownership.
2. Real category/PDP extraction and canonical identity.
3. Useful Best&Less comparison reporting without site-specific behavior.
4. Optional competitor discovery.
5. Buyer prompt review and existing audit reuse.
6. Correct recommendation observations and defensible metrics.
7. UI polish and secondary evidence views.

Explicitly deferred are family/per-variant aggregation UI, Tavily catalog
fallback, JavaScript/browser rendering, merchant dashboards, feed
remediation/publishing, schema injection, revenue attribution, sentiment,
shopping-mode rate, a product-accuracy or composite score, huge-catalog
scaling, autonomous optimization, and pricing-plan redesign.

The implementation introduces no fake Commerce demo data. The user prepares a
real credentialed workspace and historical audit before presentation; that is
operational demo preparation, not an application seed or a completion claim
for automated tests.
