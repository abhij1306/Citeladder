# Codex Handoff — Wire the Canonical Industry Catalog into Site Intelligence

**Status:** next gated implementation slice  
**Created:** 2026-08-06  
**Canonical catalog:** [`../../backend/app/core/config/industry_packs/`](../../backend/app/core/config/industry_packs/)  
**Current runtime:** generic Site Health `page_type` only  
**Primary objective:** add immutable, pack-governed `industry_role` understanding beside the existing generic page-kind classifier without changing current scoring or user-visible behavior until shadow evaluation passes

## Read this first

Do not infer repository state from this handoff alone. Start by reading:

1. [`../../Agents.md`](../../Agents.md)
2. [`../documentation-index.md`](../documentation-index.md)
3. [`../architecture.md`](../architecture.md)
4. [`site-intelligence-primary-product.md`](site-intelligence-primary-product.md)
5. [`knowledge-kernel-and-industry-pack-spec.md`](knowledge-kernel-and-industry-pack-spec.md)
6. [`../../backend/app/core/config/industry_packs/README.md`](../../backend/app/core/config/industry_packs/README.md)
7. [`../../backend/app/core/config/industry_packs/PAGE_ANALYSIS_AUDIT.md`](../../backend/app/core/config/industry_packs/PAGE_ANALYSIS_AUDIT.md)
8. [`../../backend/app/core/config/industry_packs/PERFORMANCE_CONTRACT.md`](../../backend/app/core/config/industry_packs/PERFORMANCE_CONTRACT.md)
9. [`../../backend/app/core/config/industry_packs/EXTENSION_CONTRACT.md`](../../backend/app/core/config/industry_packs/EXTENSION_CONTRACT.md)
10. [`../../backend/app/core/config/industry_packs/EVALUATION_CONTRACT.md`](../../backend/app/core/config/industry_packs/EVALUATION_CONTRACT.md)

Then establish the actual dirty-worktree state. Preserve all legitimate existing changes. Do not
stage, commit, delete unrelated files, or regenerate the catalog unless the task explicitly
requires a new catalog release.

## What already exists

The canonical catalog slice is complete and self-validating:

- exact immutable loader and resolver in
  [`catalog.py`](../../backend/app/core/config/industry_packs/catalog.py);
- pure compiled reference classifier in
  [`reference.py`](../../backend/app/core/config/industry_packs/reference.py);
- complete validator in
  [`validate.py`](../../backend/app/core/config/industry_packs/validate.py);
- benchmark harness in
  [`benchmark.py`](../../backend/app/core/config/industry_packs/benchmark.py);
- 16 registered packs, exact versions and content hashes;
- Education and Commerce at `validated_candidate`; 14 additional packs at `foundation`;
- role, FAQ, temporal, ambiguity, conflict, schema-only, public-label, and Commerce scenario
  fixtures;
- focused acceptance tests in
  [`test_industry_pack_catalog.py`](../../backend/tests/unit/test_industry_pack_catalog.py).

The catalog is a definition/runtime library only. It is not yet resolved onto projects or crawls,
not persisted on page analyses, not used by Site Health rules, and not exposed by APIs or the
frontend. Do not claim pack-aware production behavior until this handoff is implemented and its
gates pass.

## Current shipped owners to extend

Inspect before editing:

| Concern | Current owner |
|---|---|
| Generic page classifier | [`page_kinds.py`](../../backend/app/analysis/site_health/page_kinds.py) |
| Site Health classifier vocabulary/config | [`site_health.py`](../../backend/app/core/config/site_health.py) |
| Analyze-phase invocation and persistence | [`analyze.py`](../../backend/app/workers/site_health/phases/analyze.py) |
| Crawl creation/config freeze | Site Health services/routes/workers that currently own `SiteCrawl.configuration` |
| Durable models | Existing Site Health and project models under `backend/app/models/`; search before adding |
| Canonical pre-launch migration | [`0001_initial.py`](../../migrations/versions/0001_initial.py) |
| API schemas/routes | Existing Site Health schemas and `/api/v1/site-crawls` routes |
| Frontend type vocabulary/evidence | [`page-kinds.ts`](../../frontend/lib/site-health/page-kinds.ts) |
| Frontend page display | Site Health badge, filter, score, and URL-detail components |

Extend these owners. Do not create a parallel crawler, queue, fetcher, parser, report store,
knowledge store, or frontend data client.

## Non-negotiable semantic separation

Persist and expose two independent concepts:

```text
page_kind      = generic structural purpose from the current Site Health classifier
industry_role  = active-pack business purpose from the canonical pack classifier
```

Examples:

- an Education program-detail page may have `page_kind = product` or `page_kind = article`
  depending on current generic evidence, while `industry_role = education.program_detail`;
- a Commerce returns page may have `page_kind = trust_policy` while
  `industry_role = commerce.return_policy`;
- an industry role may abstain while the generic page kind remains classified.

Do not replace the existing `page_type` enum with pack role IDs. During migration, preserve
`page_type` as the compatibility field and introduce an explicit `page_kind` projection or alias
only through a versioned API/data migration. Existing rule applicability and score summaries must
not silently reinterpret old data.

## Target result of this slice

For every newly analyzed eligible page, persist an immutable pack-governed understanding that
contains:

- source artifact and corpus/page identity;
- generic page kind and its existing evidence/version;
- exact pack manifest: catalog version, pack ID, pack version, pack content hash, classifier
  version;
- selected industry role or explicit abstention reason;
- score, winner margin, confidence band, and optional secondary roles;
- bounded matched evidence, alternatives, and conflicts;
- temporal state and corpus disposition;
- analyzer/extractor versions and created timestamp.

Historical rows remain interpretable through their frozen versions. A read API must never load the
current pack and silently reinterpret an older analysis.

## Phase 0 — repository and schema discovery

Before implementation:

1. Capture `git status --short`, current branch/HEAD, and staged diff.
2. Search all current uses of `SitePageAnalysis.page_type`, `page_type_evidence`,
   `classifier_version`, crawl configuration, score summary `by_page_type`, and page-type API
   filters.
3. Search existing generic artifact/snapshot/context/knowledge models before adding tables.
4. Inspect `0001_initial.py` and ORM constraints together.
5. Map workspace/project authorization for every read/write path.
6. Run the existing Site Health and catalog-focused tests to establish a baseline.

Record the actual migration map in the implementation notes. Do not add a model merely because a
concept name appears in a plan.

## Phase 1 — resolve and freeze one exact pack

### Project selection

Add a project-owned, workspace-authorized pack selection only if no equivalent project setting
already exists. Store an explicit canonical `pack_id`; aliases and taxonomy labels are input-time
helpers, not durable identities. Unknown/ambiguous identifiers fail closed. The registered
`general_business` fallback may be used only through an explicit product policy and must be visible
in provenance.

### Crawl/snapshot freeze

At crawl or immutable snapshot creation:

1. resolve the project selection once;
2. load the exact registered version with `load_pack`;
3. obtain `pack_manifest`;
4. freeze the manifest into the crawl configuration or an owned immutable snapshot row;
5. never resolve again inside per-page reads or from mutable project settings.

Required frozen keys:

```json
{
  "catalog_version": "1.0.0",
  "pack_id": "education",
  "pack_version": "1.0.0",
  "pack_content_hash": "sha256",
  "classifier_version": "industry-role-classifier-1.0.0"
}
```

Validate the frozen hash when a worker loads the pack. If the exact registered bytes are missing or
mismatched, stop pack-specific analysis with a coded operational failure; do not substitute a
newer pack or fallback silently.

## Phase 2 — persistence design

Prefer one immutable `PageUnderstanding`-equivalent owner rather than adding pack fields to many
unrelated projections. If the existing `SitePageAnalysis` is the correct owner, extend it
carefully; otherwise add one directly workspace-scoped immutable table linked one-to-one to source
artifact/analysis.

At minimum persist:

- UUID primary key and direct `workspace_id`, `project_id`, `crawl_id`, `site_url_id`, source
  artifact/analysis IDs;
- `page_kind`, generic classifier version/evidence reference;
- nullable `industry_role_id`;
- nullable numeric score and winner margin;
- confidence band;
- nullable abstention reason;
- bounded secondary role IDs, evidence, alternatives, and conflicts;
- temporal state and corpus disposition;
- catalog/pack/classifier manifest fields;
- analyzer version and immutable timestamp;
- uniqueness/idempotency key that makes retries return the same semantic row rather than append
  duplicates.

Every project-owned query must be directly workspace-authorized. JSON fields need explicit size
bounds and stable schemas. IDs in pack data are strings by design; durable project-owned row IDs
remain UUIDs.

CiteLadder is pre-launch. Fold schema changes into
[`0001_initial.py`](../../migrations/versions/0001_initial.py), reset a disposable database, run the
migration from scratch, and run `alembic check`. Do not add a `0002+` migration unless repository
policy changes explicitly.

## Phase 3 — worker integration in shadow mode

### Compile outside the page loop

Load and compile the frozen pack once per worker process, crawl, or bounded task scope. Use an
exact `(pack_id, version, content_hash)` cache key. Do not perform JSON I/O, hash calculation, regex
compilation, model calls, or database lookups inside `classify_page` for each page.

### Build bounded facts

Map existing extractor output to the reference classifier fields without copying full HTML:

- final URL and decoded path;
- filename;
- title and H1;
- bounded headings and visible body text;
- CTA text and form-field labels when already extracted;
- bounded internal-link context when available;
- schema types;
- media/content type;
- current generic page kind;
- corpus disposition and temporal state when known.

Do not invent empty strings as positive facts. Missing URL/path must produce `invalid_input`, not a
homepage. Do not add network work to obtain classifier facts.

### Shadow persistence

Initially:

- invoke the pack classifier after generic page-kind classification and extraction;
- persist the pack result and manifest;
- do not change existing Technical/AEO/overall scores, issue rules, page-type filters, monitoring,
  selection, or crawl terminalization;
- emit bounded metrics for selected, abstained, ambiguous, schema-only, conflict, and error states;
- keep failures isolated so a catalog operational error is visible and retryable where appropriate,
  while ordinary semantic abstention is a successful analysis outcome.

Do not call a model to resolve an abstention in the hot loop. Optional adjudication, if later
approved, must be a separate versioned attempt with evidence, cost, and review policy.

## Phase 4 — corpus and temporal states

The role result must not collapse broader knowledge states into `other`:

- `analyze`, `inventory_only`, and `exclude` remain distinct corpus dispositions;
- `current`, `historical`, `future`, and `unknown` remain distinct temporal states;
- unsupported media may remain inventoried even when the HTML analyzer is not applicable;
- excluded or ineligible items produce `not_applicable`/explicit disposition, not a guessed role;
- conflicting current evidence remains represented for later contradiction handling.

Use existing discovery/artifact owners where possible. A PDF or feed inventory row must not be
lost merely because the current page analyzer handles HTML.

## Phase 5 — API contract

Add fields through existing `/api/v1` Site Health read projections. Reads render persisted state
only and never resolve/load/reclassify a pack.

Recommended page-detail shape:

```json
{
  "page_type": "article",
  "page_kind": "article",
  "industry_role": {
    "role_id": "education.program_detail",
    "label": "Program detail",
    "score": 8.0,
    "winner_margin": 3.5,
    "confidence_band": "moderate",
    "secondary_role_ids": [],
    "abstention_reason": null,
    "temporal_state": "current",
    "evidence": [],
    "alternatives": [],
    "conflicts": [],
    "manifest": {}
  }
}
```

When no understanding exists, return `null`/unavailable. When classification abstains, return the
industry-role object with `role_id: null` plus the reason/evidence; do not serialize it as missing.
Keep evidence bounded. Add server-backed filters only after indexes/query plans are reviewed:
`industry_role_id`, abstention state, temporal state, and conflict presence should compose with
existing cursor filters without offset pagination.

Do not expose foundation-pack results as authoritative findings. Include maturity or an equivalent
review/readiness projection where users could otherwise misread the result.

## Phase 6 — frontend contract

Keep generic and industry views separate:

- retain existing `PageTypeBadge`, page-type filter, and score breakdown;
- add an industry-role badge/label owner generated from persisted role IDs/labels or a safe API
  projection;
- show `—` for unavailable/unrun state;
- show “Unclassified” with a specific abstention reason for an executed abstention;
- add a bounded “Why this role?” disclosure with score, margin, positive/negative signals,
  alternatives, conflicts, temporal state, and pack/version;
- visually distinguish a conflict from low confidence and from schema-only abstention;
- never title-case an unknown namespaced ID as though it were a reviewed label;
- preserve full mobile workflow and existing design-system tokens.

The current frontend parser drops backend alternatives/conflicts from generic evidence. Correct
that only in a backward-compatible typed change with tests; do not overload the generic evidence
view with the industry-role schema.

## Phase 7 — typed knowledge, questions, opportunities, and FAQ verification

Role classification is only the first layer. Extend existing evidence/knowledge/content owners; do
not create a second knowledge graph or action store.

### Typed extraction and question coverage

For eligible analyzed corpus items:

1. create bounded `ContentUnit` and `Evidence` records that point to immutable source artifacts and
   exact locators;
2. extract proposed entities, assertions, and relations through versioned deterministic/hybrid
   analyzers;
3. preserve scope, source refs, confidence, temporal state, and knowledge state on every assertion;
4. represent overlapping incompatible assertions as explicit contradiction groups rather than
   selecting a convenient value;
5. evaluate the active role's required questions into `answered_strong`, `answered_weak`,
   `missing`, `conflicting`, `unsupported`, `historical_only`, `unavailable_evidence`, or
   `not_applicable`;
6. keep model output `proposed` unless deterministic validation and an audited user approval move
   it into approved project memory.

A source artifact proves only what is visible at its observed scope and time. Schema, a model
summary, or a pack predicate never proves a project fact by itself. Customer facts remain directly
workspace/project scoped and never mutate the shared pack.

### Rules, findings, and opportunities

Run a pack rule only when:

- the crawl's frozen pack manifest contains the rule;
- the pack/rule maturity permits that result class;
- required evidence and question coverage exist;
- temporal, contradiction, and regulated-claim gates pass;
- the rule/analyzer version is frozen on the result.

Persist deterministic rule evaluations and findings through the existing Site Intelligence owners.
Group related findings through the existing `Opportunity` owner and prioritization pipeline; do not
introduce an industry-specific task/opportunity table. A foundation pack may support shadow
classification and contextual suggestions, but it must not silently emit authoritative findings.

### FAQ brief and context package

The first end-to-end Content Intelligence consumer is FAQ work:

```text
classified role
  -> required-question coverage
  -> evidence-backed finding/opportunity
  -> frozen FAQ brief and TaskContextPackage
  -> constrained generated attempt
  -> deterministic claim/citation/duplication/link/parity validation
  -> human review and approval
  -> observed publication
  -> recrawl verification
```

Reuse the existing brief/content-job/review/publication owners. The frozen context package must
contain the exact pack manifest, source/evidence/assertion/question IDs, approved-memory IDs,
contradictions, omissions, claim policy, template version, and context-budget decisions. It must
exclude unrelated workspace data and unapproved raw conversation history.

Support an FAQ section on an existing page, a standalone FAQ/support page, and optional `FAQPage`
JSON-LD only when it mirrors reviewed visible content. Unknown or conflicting fees, prices, dates,
availability, results, ratings, credentials, eligibility, clinical/financial claims, property or
travel availability, tolerances, allergens, or policies are requested, qualified, or omitted—not
invented.

### Recrawl verification

Verification compares immutable before and after source snapshots. Persist what changed, which
finding/attempt/change was evaluated, evidence IDs, result state, and limitations. No observed
technical or visibility change should be presented as causal business impact without compatible
Demand/admissions/commerce outcome evidence.

## Phase 8 — evaluation and controlled activation

### Shadow corpus

For Education and Commerce:

1. replay all canonical fixtures;
2. run on sanitized/opt-in field corpora;
3. preserve source artifact IDs and reviewer labels;
4. measure selected/abstained rates, score/margin distributions, conflicts, schema-only cases, and
   disagreements with reviewed labels;
5. review errors by role and site architecture, not only aggregate accuracy;
6. record catalog/pack hashes with every evaluation result.

The Asian School external crawler export is a technical baseline and source for sanitized semantic
review. Crawler labels are not automatically industry-role truth. Commerce field cases must keep
prices, availability, variants, offers, shipping, and returns scoped and temporal.

### Activation gate

Pack-aware rules or briefs remain disabled until:

- shadow persistence is stable and idempotent;
- workspace isolation and provenance tests pass;
- reviewed field error analysis is acceptable for the intended role/rule;
- abstention/conflict states are visible in APIs/UI;
- foundation packs remain non-authoritative;
- rollback can disable pack-aware consumers without deleting evidence.

Activate one rule/brief family at a time behind explicit versioned configuration. Never change old
scores in place.

## Phase 9 — performance and operational instrumentation

Follow
[`PERFORMANCE_CONTRACT.md`](../../backend/app/core/config/industry_packs/PERFORMANCE_CONTRACT.md).
At minimum instrument:

- catalog load/compile duration and cache hit/miss;
- per-page role-classification duration and input/evidence sizes;
- selected/abstained/conflict counters by pack/version;
- persistence SQL count/latency and retry/idempotency behavior;
- crawl queue/lease/terminalization impact;
- API payload/query latency for new filters.

Do not optimize by weakening per-host politeness, SSRF, robots, response bounds, evidence, or
workspace authorization. Connection reuse and evaluation-write batching are separate measured
performance slices, not hidden parts of role wiring.

## Required tests

Add focused tests for:

### Configuration and manifest

- project pack selection authorization;
- alias/taxonomy resolution at write time and canonical ID persistence;
- exact version/hash freeze;
- missing/mismatched pack operational failure;
- no silent general fallback;
- historical crawl keeps old manifest after project setting changes.

### Persistence and isolation

- two workspaces cannot read/write each other's selection or understanding;
- retries are idempotent;
- source IDs and all versions persist;
- JSON bounds are enforced;
- abstention is persisted as an executed result, distinct from unavailable;
- foundation maturity cannot enable authoritative findings.

### Classification wiring

- generic page type remains unchanged;
- industry role is classified from the same bounded facts;
- missing URL does not become homepage/role;
- schema-only abstains;
- ambiguity and conflicts persist;
- historical/excluded/not-applicable states remain distinct;
- no model/network/database/file I/O occurs in the pure hot loop.

### Knowledge, questions, FAQ, and verification

- entities/assertions/relations retain source, scope, temporal state, knowledge state, and analyzer version;
- contradiction groups preserve incompatible evidence instead of silently resolving it;
- every required question maps to the expected coverage state;
- foundation maturity blocks authoritative findings;
- findings group through the existing Opportunity owner;
- FAQ briefs and TaskContextPackages freeze exact evidence, approved memory, omissions, contradictions, templates, and pack manifest;
- unknown/conflicting/historical/unsupported claims are requested, qualified, omitted, or blocked as required;
- visible FAQ content and `FAQPage` JSON-LD remain in parity;
- generation/publishing requires explicit human approval;
- recrawl verification compares immutable before/after evidence without causal overclaiming.

### API/frontend

- persisted-only reads;
- null versus abstained semantics;
- manifest/evidence bounds;
- filters compose with cursor pagination;
- generic and industry labels/evidence remain distinct;
- alternatives/conflicts/negative evidence render;
- mobile and accessibility tests for disclosure/filter controls.

### Migration and operations

- `alembic upgrade head` from an empty disposable database;
- `alembic check` and ORM drift checks;
- worker retry/cancellation/lease behavior;
- 10,000-page Education and Commerce classifier benchmarks;
- representative crawl instrumentation at increasing scale before throughput claims.

## Validation commands

Run the catalog baseline before and after wiring:

```bash
cd backend
uv run python -m app.core.config.industry_packs.validate
uv run pytest tests/unit/test_industry_pack_catalog.py -q
uv run ruff check app/core/config/industry_packs tests/unit/test_industry_pack_catalog.py
uv run python -m app.core.config.industry_packs.benchmark --pack education --pages 10000
uv run python -m app.core.config.industry_packs.benchmark --pack commerce --pages 10000
```

Add and run the new focused unit/component/integration/frontend tests for the touched owners, then:

```bash
cd backend
uv run alembic upgrade head
uv run alembic check
uv run ruff check <all changed Python paths>
python -m py_compile <all changed Python paths>

cd ../frontend
pnpm test -- <focused test files>
pnpm lint
pnpm build

cd ..
python docs/validate_documentation.py
git diff --check
```

Do not claim completion from a partial test subset if a listed command fails. Report exact command
results and unrelated pre-existing failures separately; do not rewrite other workstreams to hide
them.

## Rollback contract

The first release must be disable-able without deleting data:

- one explicit feature/config gate stops new pack-aware persistence or consumers;
- existing generic page type, scoring, issues, APIs, and frontend continue unchanged;
- persisted shadow understandings remain immutable evidence for diagnosis;
- project pack selection and frozen crawl manifests are not rewritten;
- reactivation uses the same exact pack/version or an explicit new analysis/recompute job;
- rollback never interprets a failed/abstained result as a successful default role.

## Completion definition

This wiring slice is complete only when:

1. one exact pack manifest is frozen per eligible crawl/snapshot;
2. generic page kind and pack-specific industry role are separately persisted;
3. every new role result has bounded evidence, alternatives, conflicts, temporal/disposition state,
   and exact provenance—or an explicit abstention reason;
4. worker execution has no per-page catalog I/O/compilation/model call;
5. workspace isolation, idempotency, migration, API, frontend, and fixture tests pass;
6. Education and Commerce shadow evaluation and 10,000-page classifier benchmarks are recorded;
7. current generic scoring remains unchanged until an independently reviewed pack-aware rule is
   activated;
8. rollback is tested;
9. active documentation reflects the shipped boundary;
10. no duplicate catalog, transient generator output, staged changes, or unrelated rewrites remain.
