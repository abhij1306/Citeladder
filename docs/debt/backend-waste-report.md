# Backend waste & refactor-residue report — 2026-08-20

Companion to [`backend-debt-report.md`](backend-debt-report.md). That report owns **BD-01 … BD-22** (ceilings, fail-open extractors, keyset pagination, health shallowness, coverage tooling). **None of those IDs are repeated here.** This report is only residue you can **delete**, or spend you can **stop**.

## 0. Method

**Git (required Track A):** `git log --oneline -30 -- backend/app` plus churn (`git log --name-only -- backend/app | group-by count`). Highest churn still names **deleted paths**: `core/config/site_health.py` (38), `domain/audits/planner.py` (28), `api/site_health.py` (22), `models/site_health.py` (21), `domain/opportunities/service.py` (23), `domain/analysis/service.py` (18), `domain/site_health/service.py` (16). Those files are gone from the tree — the cutover happened. Residue is what **remained after** those splits.

**Call-graph checks:** ripgrep for imports/usages of shims, version strings, catalogs, and ORM fields. vulture@80 is CI-clean; nothing here is syntactically unused.

**Not completed (called out as UNVERIFIED):** exhaustive unused-export scan of all 51 `core/config` modules; exhaustive unread-column scan of every `app/models` column vs readers. Samples below are verified; do not treat the rest of those catalogs as cleared.

**Track B prompt** in the user message was truncated after “Answer concretely, with file:line:”. Crawl answers below cover fetch reuse, browser ladder, robots/llms/sitemap probes, and budget knobs from the listed files.

## 1. Executive summary

- The big refactors (`#81` split domain owners, `#80` split config/persistence, `#70` remove demand legacy, Site Health package splits) **did delete the old modules**. Remaining waste is **compatibility tissue**: HTTPException shim, empty shopping-surface gate, `by_page_type` JSON fallback, stale version comments, and a commerce “legacy placeholder” failure code.
- Largest **deletable runtime LOC** is not a shim with zero callers — those façades still have callers. It is **future-feature scaffolding shipped in `app/`**: empty `SHOPPING_SURFACES`, the onboarding golden corpus + measurement harness (scripts/tests only), and dual agent HTTP adapters selected by config.
- Crawler spend: analyze **already reuses** discover artifacts (`reusable_discover_artifact`). Extra network is **llms.txt every crawl**, **`/sitemap.xml` when robots lists no sitemaps** (non-sample), and optional browser rungs (`browser_enabled` defaults **false**). Sitemap XML may be parsed up to 50 MB / 50k URLs then truncated to 5000 admitted URLs.
- Provider spend: `POST /audits` defaults **`measurement_mode="pulse"`** (1 repetition) but still **`max_attempts=5`** per task and the client must still pick engines. Pulse’s answer instruction is **explicitly unmeasured**. Growth Agent always runs **every allowlisted tool** then one LLM call. Content generation retries up to 3.
- Tests: `by_page_type_*` names wrap `aggregate_by_page_kind` and **never exercise** the `by_page_type` JSON key. `b6-analysis-1` appears only in test fixtures and a **wrong comment**. Catalog unit tests (`test_opportunities_config.py`, `test_content_config.py`) are guards, not dead coverage.
- Do not delete `domain/site_health/service/__init__.py`: API routers still import the façade (see Track A).

## 2. Findings

### BW-01 — Empty shopping-surface gate still fans out through audits, analysis, and products

- **ID**: `BW-01`
- **Severity**: high
- **Category**: residue (delete / stop branching)
- **Evidence**: `backend/app/core/config/commerce.py:374` `SHOPPING_SURFACE_MEASUREMENT = ""`; `:380` `SHOPPING_SURFACES: dict = {}`. `models/audit.py:301` comments the gate is empty (M2a). Task writer always stamps measurement: `domain/audits/task_creation.py:96`. Downstream still filters/branches: `analysis/service.py:242`, `workers/audit/terminalization.py:139`, `domain/analysis/evidence.py:195`, `domain/products/visibility.py:185`–`:279`, API `surface` query `api/audits.py:284`, `api/products.py:426`. Table `audit_shopping_surface_snapshots` (`models/audit.py:304`).
- **Problem**: Shopping surfaces were designed as extra audit slots. The catalog is an **empty dict**, so no live row can have a non-empty surface except by hand-editing. The product still carries snapshot tables, query params, `per_surface` maps, and “measurement vs other surface” branches. That is a design that changed; the columns stay because migrations are squashed, not because readers need other values.
- **Blast radius**: `config/commerce.py`, `models/audit.py` + `analysis.py` + `product.py` surface columns, analysis finalize, product visibility APIs, trend validation `domain/analysis/trends.py:48`. Tests across audits/products/analysis.
- **Test safety net**: product visibility and analysis tests that pass `surface=""`. None can create a second surface without monkeypatching `SHOPPING_SURFACES`.
- **Fix sketch**: Until a surface ships, collapse reads to the empty-string slot only; stop exposing `surface` on APIs; leave DB columns unused (pre-launch you may drop them in `0001_initial.py`). Do not keep `per_surface` loops “for later.”
- **Effort**: L
- **Spend saved**: none until surfaces would have multiplied audit tasks; **LOC saved** is the win.

### BW-02 — `by_page_type` JSON fallback has no live writer and no test that feeds the old key

- **ID**: `BW-02`
- **Severity**: medium
- **Category**: residue
- **Evidence**: Writers: `domain/site_health/snapshot.py:238` `"by_page_kind"`. Readers: `domain/site_health/service/presentation.py:146`–`:148` fall back to `"by_page_type"`. `score_aggregation.py` only exports `aggregate_by_page_kind`. Tests: `test_site_health_service_pure.py:242` is named `…by_page_type` but the fixture uses **`by_page_kind`** (`:252`). `test_site_health_scoring.py:200`–`:242` names `test_by_page_type_*` but calls `aggregate_by_page_kind`. **Grep finds zero tests that put `by_page_type` in a summary dict.**
- **Problem**: The fallback exists so pre-rename crawl JSON still shows a breakdown. Current writers never emit `by_page_type`. Pre-launch, that branch is kept alive by a comment, not by data. The tests that look like they cover it **do not**.
- **Blast radius**: `domain/site_health/service/presentation.py:138`–`:149`; rename tests. No analyzer version bump if you only drop a read fallback.
- **Test safety net**: none for the old key. `test_score_summary_without_breakdown_projects_empty_map` (`:282`) covers missing breakdown.
- **Fix sketch**: Delete the `by_page_type` get; rename tests to `by_page_kind`. If a disposable DB might still hold old JSON, one release of dual-read is enough — not forever.
- **Effort**: S
- **Spend saved**: none.

### BW-03 — Dual HTTP error paths: `ApiException` plus a compatibility shim for raw `HTTPException`

- **ID**: `BW-03`
- **Severity**: medium
- **Category**: residue
- **Evidence**: Shim `core/errors.py:190`–`:275` (`_legacy_detail_parts`, `_parse_legacy_detail`, `http_exception_shim_handler`). Registered in `main.py:132`–`:134`. Still-raising routers include `api/provider_connections.py`, `api/billing.py`, `api/auth.py`, `api/deps.py`, `api/prompts.py`, `api/audits.py`, `api/integrations.py`, and others (17 files under `app/api` still `raise HTTPException`). Starlette 404/405 also flow through the shim (docstring `:261`).
- **Problem**: The envelope contract already exists (`ApiException` / `raise_not_found`). The shim exists because the migration is **half-done**. You cannot delete `_legacy_*` until those routers stop raising FastAPI `HTTPException` for product errors. Routing 404/405 still need *a* handler — that part is not residue.
- **Blast radius**: listed API modules + `core/errors.py` + `main.py`. Frontend depends on envelope shape.
- **Test safety net**: `tests/unit/test_error_envelope.py`, `tests/component/test_error_envelope_api.py`.
- **Fix sketch**: Convert remaining product `HTTPException` to `ApiException`/`http_errors.py` helpers. Keep one handler for Starlette routing errors. Then delete `_legacy_detail_parts` / `_legacy_code_message` / `_legacy_extras`.
- **Effort**: M
- **Spend saved**: none.

### BW-04 — Onboarding golden corpus and measurement harness ship inside `app/` but only scripts/tests import them

- **ID**: `BW-04`
- **Severity**: medium
- **Category**: residue (delete from the runtime package)
- **Evidence**: `app/evaluations/` (6 modules; `onboarding_golden.py` ~701 LOC). Importers: `scripts/run_onboarding_eval.py`, `tests/unit/test_onboarding_golden_eval.py` — **not** `app/api` or workers. `app/domain/measurement/harness.py` (~741 LOC) docstring `:10`–`:14` (fixture-only, never a live measurement). Importers: `scripts/measure_answer_engine_matrix.py`, `tests/unit/test_measurement_harness.py`.
- **Problem**: Eval fixtures are product-quality tools, but they inflate the **API/worker image** and the complexity-policy `app/` tree. They are reachable (scripts import them) so vulture keeps them. They are pointless in the FastAPI process.
- **Blast radius**: move packages under `backend/scripts/` or `backend/evaluations/`; update those two scripts and two unit tests. `pyproject` package include `app*`.
- **Test safety net**: the two unit files above.
- **Fix sketch**: Relocate out of `app/`. Do not delete the golden cases.
- **Effort**: M
- **Spend saved**: none (offline fixtures).

### BW-05 — Commerce worker fails non-upload reruns with a literal `commerce_legacy_placeholder`

- **ID**: `BW-05`
- **Severity**: medium
- **Category**: residue / correctness-adjacent waste
- **Evidence**: Constant `core/config/commerce.py:98`. Only consumer: `workers/commerce_discovery_worker.py:545`–`:568` — if `input_kind` is not upload and an artifact already exists for the task, `_finalize_failure` with that code/detail, then return. No other app/test references to the token.
- **Problem**: A second claim of a crawl-style discovery task that already wrote an artifact is treated as **legacy failure**, not idempotent success (the upload branch uses `result_artifact_id` and succeeds). Either old rows needed a tombstone, or this is a half-migrated idempotency path that **spends a finalize/failure** instead of `queue.succeed`. The placeholder string is not a real error taxonomy.
- **Blast radius**: `commerce_discovery_worker.py` `_ack_upload_or_existing`, commerce tests.
- **Test safety net**: **none**. Grep of `backend/tests` finds zero mentions of `commerce_legacy_placeholder`. The branch is reachable from the worker and unasserted.
- **Fix sketch**: Align non-upload with upload: succeed with the existing artifact id. Delete `COMMERCE_DISCOVERY_ERROR_LEGACY_PLACEHOLDER`.
- **Effort**: S
- **Spend saved**: avoids extra failure/reconcile work on retries (not provider $).

### BW-06 — Stale analyzer version comment vs live constant; tests mint `b6-analysis-1`

- **ID**: `BW-06`
- **Severity**: low
- **Category**: residue
- **Evidence**: Live stamp `core/config/analysis.py:18` `ANALYZER_VERSION = "grounded-analysis-v3"`. Stale comment `domain/analytics/tasks.py:36` still says `"b6-analysis-1"`. Tests hard-code `b6-analysis-1` in `tests/component/test_analysis_api.py`, `test_analysis_http.py`, `opportunity_helpers.py`, `test_opportunities_service.py`. **No `app/` formula branch** switches on `b6-analysis-1`.
- **Problem**: There is no live v1 analysis formula to delete. The tests persist **fictional old version strings** so trend grouping still works. The comment will send the next agent looking for a ghost branch.
- **Blast radius**: one comment; optional test fixture cleanup (keep *some* foreign version if you still want mixed-version trend tests — just don’t pretend it is `config/analysis.py`).
- **Test safety net**: those component tests.
- **Fix sketch**: Fix the comment. Rename fixture versions to `fixture-analysis-old`.
- **Effort**: S
- **Spend saved**: none.

### BW-07 — `site_health.service` façade is not deletable (callers remain)

- **ID**: `BW-07`
- **Severity**: low
- **Category**: residue (negative finding — do not delete)
- **Evidence**: Façade `domain/site_health/service/__init__.py:25`–`:37`. Consumers: `api/site_health/{mutations,events_exports,projections,pages,common}.py`, `tests/unit/test_site_health_service_pure.py`, `test_site_health_events_exports.py`, `test_site_health_discover.py`, `test_site_health_terminalization.py`. Direct submodule imports exist too, but the façade is the API’s import.
- **Problem**: Report #1 suggested collapsing private re-exports (`_crawl_count_disclosure`). The **package `__init__` is still the public import path**. Zero-consumer shim: **false**.
- **Blast radius**: n/a
- **Test safety net**: n/a
- **Fix sketch**: Leave the façade. Optionally have routers import submodules **without** deleting `__init__.py` until no `from app.domain.site_health.service import` remains.
- **Effort**: —
- **Spend saved**: none.

### BW-08 — Every full crawl probes `llms.txt` and, if robots lists no sitemaps, `/sitemap.xml`

- **ID**: `BW-08`
- **Severity**: medium
- **Category**: resource waste
- **Evidence**: Site setup `workers/site_health/phases/discover_stages.py:156`–`:171` always `_llms_facts`; sitemaps skipped when `sample_mode` (`:162`). If no robots sitemaps, seeds `SITEMAP_DEFAULT_PATHS` = `("/sitemap.xml",)` (`site_health_acquisition.py:104`). `_llms_facts` `:197`–`:213` fetches unless robots disallows. Robots itself is fetched in discover (`phases/discover.py` robots purpose) and cached on the worker (`site_health_worker.py` robots cache comments ~146).
- **Problem**: Sample crawls skip the sitemap tree (good). Full crawls still pay **one llms.txt GET** and often **one 404 sitemap GET** on sites that never declared a sitemap. That is not required to classify the homepage; it is extra evidence for AEO rules (`llms_txt_present`, sitemap inventory).
- **Blast radius**: `discover_stages.py` `_site_setup` / `_ingest_sitemaps`; rules that read `site_facts.llms_txt` / sitemap files.
- **Test safety net**: `tests/component/test_site_health_discover.py`, unit parser/rules for llms.
- **Fix sketch**: Fetch llms.txt only when the `aeo.llms_txt_present` rule is in the active catalog (it is). Optionally skip default `/sitemap.xml` unless robots advertised sitemaps or the operator enabled sitemap seed. Keep robots.txt (needed for politeness and AI-crawler stance).
- **Effort**: M
- **Spend saved**: 1–N HTTP requests per **host** per full crawl (sitemap tree can be many more if indexes exist).

### BW-09 — Sitemap ingestion can decode huge documents then throw most URLs away

- **ID**: `BW-09`
- **Severity**: medium
- **Category**: resource waste
- **Evidence**: `site_health_runtime.py:191`–`:198` — `max_sitemap_index_depth=3`, `max_sitemap_urls=50000`, `max_sitemap_decoded_bytes=50_000_000`, `max_sitemap_documents=32`, `max_sitemap_admitted_urls=5000`. Walker `discover_stages.py:215`–`:247` bounds **attempts** at 32 documents but still parses each body.
- **Problem**: A 50k-URL index is downloaded/parsed so 5k URLs can be admitted. CPU, RAM, and bandwidth on the worker for URLs that never enter analyze.
- **Blast radius**: sitemap collector + `_ingest_sitemaps` + runtime knobs.
- **Test safety net**: site-health discover tests with sitemap fixtures.
- **Fix sketch**: Lower `max_sitemap_urls` to the admit cap (5000) or parse incrementally and stop at `max_sitemap_admitted_urls`. Shrink `max_sitemap_decoded_bytes` unless a measured corpus needs 50 MB.
- **Effort**: S
- **Spend saved**: worker CPU/RAM/network on large sites (not LLM $).

### BW-10 — Analyze already skips a second HTML fetch when discover facts exist

- **ID**: `BW-10`
- **Severity**: low
- **Category**: resource waste (negative — do not “fix” by adding another fetch)
- **Evidence**: `workers/site_health/phases/analyze.py:117`–`:133` + `workers/site_health/acquisition.py:90`–`:116` reuse discover artifact when `extractor_version` matches and `normalized_facts` is present. Re-fetch only if no row (`analyze.py:135` `_fetch_analyze`). Browser continue: `connectors/web_evidence/fetcher_ladder.py:71`–`:96`, default `browser_enabled=False` (`site_health_runtime.py:171`).
- **Problem**: Double-fetch is **not** the default. Waste remains when extractor versions diverge (rerun after bump) or facts are null. Do not treat “discover + analyze both exist” as two network calls.
- **Blast radius**: n/a
- **Test safety net**: analyze component tests for reused artifacts.
- **Fix sketch**: None for the happy path. When bumping `EXTRACTOR_VERSION`, expect a full re-fetch by design.
- **Effort**: —
- **Spend saved**: already saved vs naïve two-fetch.

### BW-11 — Pulse is the API default, but each task still has a 5-attempt provider budget

- **ID**: `BW-11`
- **Severity**: medium
- **Category**: cost waste
- **Evidence**: `domain/audits/schemas.py:197` `measurement_mode` default `"pulse"`; comment `:189`–`:191` originally described benchmark as the manual default — **comment disagrees with the literal default**. Reps: `audits.py` settings `pulse_repetitions=1`, `benchmark_repetitions=3` (`:421`–`:422`). `max_attempts: int = 5` (`:401`). Pulse instruction is an **unmeasured candidate** (`:134`–`:151`) but **is sent** on pulse runs. Engines: client-supplied, min_length 1 (`AuditCreate.engines`).
- **Problem**: Pulse already cuts retrieval/output vs benchmark. Remaining spend: retries (5) × engines × prompts, plus an answer prefix that the file itself says has **no validated −56%/−49%**. A 3-engine pulse on 30 prompts is 90 calls before retries; 5-attempt budget is 450 possible provider calls if everything fails.
- **Blast radius**: `AuditSettings.max_attempts`, pulse route policy, frontend engine picker (out of scope). Worker `call_provider_once`.
- **Test safety net**: `tests/component/test_audit_worker.py`, cost projection tests.
- **Fix sketch**: Lower pulse `max_attempts` (e.g. 2) independently of benchmark. Measure `PULSE_ANSWER_INSTRUCTION` or stop claiming it saves money. Fix the schema comment.
- **Effort**: S (knob) / L (measurement)
- **Spend saved**: failed-call retries on pulse; instruction TBD until measured.

### BW-12 — Growth Agent `explain` always executes four DB tools, then one LLM narration

- **ID**: `BW-12`
- **Severity**: low
- **Category**: cost waste
- **Evidence**: Policy `core/config/agent.py:49`–`:56` — `explain` allowlist has four tools. Loop `domain/agent/service.py:228`–`:256` runs **every** `run.allowed_tools` with `payload={}`. Then `gateway.complete_structured` (`:298`) if configured; else `_deterministic_narrative` (`:281`) — **still after all tool reads**.
- **Problem**: Tools are cheap (Postgres). The LLM call is the money. Waste: you cannot skip unused tools; `explain` always loads audits even if the user only needed site health. Unconfigured gateway still does four queries then a template — fine. Configured gateway always pays one completion per run.
- **Blast radius**: `agent.py` policies, `execute_claimed_task`.
- **Test safety net**: `tests/component/test_growth_agent_api.py`, `tests/unit/test_growth_agent.py`.
- **Fix sketch**: Narrow `explain` allowlist, or skip tools whose snapshots are `unavailable` without calling the model with empty evidence. Do not add a second LLM hop.
- **Effort**: S
- **Spend saved**: one completion per agent run (cannot skip if narration is the product); maybe fewer tokens if tools are trimmed.

### BW-13 — Two default-agent HTTP stacks; prompts import the factory under the old class name

- **ID**: `BW-13`
- **Severity**: low
- **Category**: residue
- **Evidence**: `connectors/agent/factory.py:13`–`:21` picks `NativeOpenAIClient` vs `DefaultAgentClient`. `api/prompts.py:34` `create_model_gateway as DefaultAgentClient`. Tests monkeypatch `prompts_api.DefaultAgentClient` (`test_prompt_generation_api.py`).
- **Problem**: Two ~250-line adapters is justified **if** both `adapter=` values are deployed. The import alias is leftover naming from before the factory. Not deletable without dropping an adapter.
- **Blast radius**: `connectors/agent/*`, `api/prompts.py`, prompt-generation tests.
- **Test safety net**: `test_default_agent_client.py`, `test_native_openai_agent.py`.
- **Fix sketch**: Rename the prompts import to `create_model_gateway` and update monkeypatches. Delete an adapter only if config never selects it in production.
- **Effort**: S (alias) / M (drop adapter)
- **Spend saved**: none unless an unused adapter’s tests/CI time.

### BW-14 — `config/audits.py` re-exports the entire queue vocabulary

- **ID**: `BW-14`
- **Severity**: low
- **Category**: residue (negative — high caller count)
- **Evidence**: `core/config/audits.py:42`–`:59` tuple of `TASK_STATUS_*` re-exports from `task_queue.py` “so existing audit imports keep working.” Grep shows widespread `from app.core.config.audits import TASK_STATUS_*`.
- **Problem**: Same pattern as the site-health façade: **not zero consumers**. Deleting the re-export is a mechanical import churn, not spend.
- **Fix sketch**: Optional later; do not prioritize over BW-01/BW-04.
- **Effort**: M
- **Spend saved**: none.

## 3. Clusters

**W1 — Unshipped commerce/audit surfaces (BW-01, BW-05)**
Empty `SHOPPING_SURFACES` plus a commerce legacy failure token. Delete branching; keep DB columns only if you refuse a squash-reset.

**W2 — Rename leftovers (BW-02, BW-06)**
`by_page_type` / `b6-analysis-1` / Task 3 comments. Delete fallbacks and fix comments; rename tests.

**W3 — Half-migrated HTTP errors (BW-03, BW-13 alias)**
Finish `ApiException` cutover; then delete legacy parsers.

**W4 — Eval code in the runtime package (BW-04)**
Move `app/evaluations` and `domain/measurement/harness.py` out of `app/`.

**W5 — Extra owned-site GETs (BW-08, BW-09; BW-10 is the reuse you should keep)**
Default sitemap + llms probe + oversized sitemap parse caps.

**W6 — Provider retry/instruction (BW-11, BW-12)**
Pulse `max_attempts` and agent allowlists.

## 4. Rejected / not deletable

- **vulture@80 clean** — no easy unused functions. FastAPI routes looking unused at confidence 60 are false.
- **`domain/site_health/service/__init__.py`** — BW-07; still the API import.
- **`domain/projects/shim.py` / `domain/products/shim.py`** — live serialization into frozen audit config, not leftover files.
- **`http_exception_shim_handler` for Starlette 404/405** — keep a handler; only the product-`HTTPException` path is residue (BW-03).
- **Grok / Perplexity / Copilot catalog rows** — `provider_catalog.py:359`–`:367` are **display coming-soon**, not dead executors. `ACTIVE_TRANSPORTS` is still openai/anthropic/google. Do not delete without a product decision.
- **Content skill ids (`linkedin`, `youtube`, …)** — `CONTENT_OUTPUT_TYPES` is only `website_page`, but `CONTENT_SKILLS` is the live request enum (`domain/content/schemas.py`); component tests post `skill_id: linkedin`. Not unread config.
- **`product_tour` config** — used by `domain/workspaces/service.py` and API.
- **Analyze vs discover two task kinds** — not duplicate implementations; reuse is BW-10.
- **`DataClient` Protocol** — four connector implementers + paging; not a single-implementer Protocol.
- **`PhaseSupport` `NotImplementedError` methods** — mixin typing seam (related to BD-03, not deletable waste).
- **`aeo.sufficient_text`** — comments only; not in `site_health_rules.py`. No live branch to delete.
- **Catalog unit tests** (`test_opportunities_config.py`, `test_content_config.py`, `test_integrations_config.py`) — they pin vocabularies. Deleting them loses the “catalog must not drift” net. Not duplicate of detector tests.
- **`test_static_analysis_tools.py`** — tiny vulture-pin; keep.
- **`test_site_health_e2e.py` vs `test_site_health_api.py`** — e2e file `:1`–`:21` states it covers journeys/mutations the isolated API tests do not. Not a copy-paste clone (jscpd did not flag it against the API file).
- **Config module count vs worker count** — invariant 1 wants knobs in `core/config`. Asymmetry is not residue by itself (51 config files, all sampled owners have readers).
- **BD-01…BD-22 items** — fail-open parsers, LOC ceilings, audit event Python slicing, health liveness, pytest-cov, test godfiles.

### UNVERIFIED

> UNVERIFIED: unread ORM columns across all models. Squash migration `0001_initial.py` cannot prove a column is unused without a full reader grep per column. Shopping-surface columns **are** written (always `""`) so they are used, even if other surfaces are not.
>
> UNVERIFIED: every exported name in all 51 config modules. Spots checks (http, oauth, api, workspaces, product_tour, suggestions via project schemas) had readers. Do not mass-delete config on this report.

## 5. Raw data

**Git churn (top leftover names, including deleted paths):** `models/__init__.py` 41, `workers/audit_worker.py` 39, `core/config/site_health.py` 38 (file gone; split into `site_health_*.py`), `workers/site_health_worker.py` 35, `api/projects.py` 29, `domain/audits/planner.py` 28 (gone), `connectors/web_evidence/fetcher.py` 25, `domain/site_health/discovery.py` 25, `domain/opportunities/service.py` 23 (gone).

**Recent backend subjects:** production-readiness, Site Health AEO orchestration, split domain/config owners, remove demand legacy, W2–W5 delivery waves.

**Version stamps (live, not dual-formula):** `grounded-analysis-v3` / `prompt-composite-v1`; `opp-analyzer-5`; `product-analysis-2`; site extractor/analyzer via contracts. Old `b6-analysis-1` is tests+comment only.

**Crawl knobs (runtime):** `browser_enabled` default false; `sample_url_limit` / `sample_discovery_url_cap`; frontier 50k; sitemap 32 docs / 50k URLs parsed / 5k admitted; `llms.txt` + optional `/sitemap.xml`.

**Cost knobs:** pulse default on `AuditCreate`; pulse reps 1; benchmark reps 3; audit `max_attempts` 5; content `CONTENT_MAX_ATTEMPTS` 3; agent `explain` 4 tools + 1 completion.
