# CiteLadder Python Backend — Static Analysis Audit Report

**Date:** July 29, 2026  
**Target Codebase:** CiteLadder Python Backend (`backend/app` & `backend/tests`, ~121k total LOC)
**Scope:** Diagnostic audit across dead code, duplication, complexity, maintainability, marker inventory, and dispatch mechanics.  
**Constraint:** Diagnostic only — contains zero fix implementations or proposed code refactoring steps.

---

## 1. Executive Summary

This report presents a static-analysis audit of the CiteLadder Python backend (~121,577 lines of code across 371 source files). CiteLadder is an AI Search Optimization (AEO) and Search Engine Optimization (SEO) audit platform.

### Summary of Key Findings

1. **Clean Code & Hygiene Metrics:**
   - **Pyflakes (Unused Imports / Redefinitions):** **0** unused imports or redefinitions across the entire `app` and `tests` directories.
   - **TODO / FIXME / XXX / HACK / Deprecated Markers:** **0** instances inside `backend/` source files. (Markers exist only as user copy placeholders in `docs/` and frontend test assertions).
   - **Vulture Dead Code (at 80% Confidence):** **0** findings across `backend/app`.
   - **Vulture Dead Code (at 60% Confidence):** 455 raw findings. Analysis shows **432 are false positives** (FastAPI route handlers registered via decorators, Pydantic field/model validators, and SQLAlchemy ORM attributes). **2 functions are safe-to-remove**, and **21 require verification**.

2. **Code Duplication (jscpd):**
   - Total clones found: **450 duplication blocks** (5,322 duplicated lines, 33,513 duplicated tokens).
   - Overall codebase duplication rate: **4.38%** (lines) / **5.09%** (tokens).
   - Duplication is concentrated in domain services (e.g. `app/domain/site_health/service.py`), ORM models (`app/models/analysis.py`, `app/models/analytics.py`), and component test setup fixtures.

3. **Complexity & Maintainability (Radon CC & MI):**
   - **Cyclomatic Complexity Hotspots:** 348 functions exhibit CC $\ge$ 10. The highest complexity in application logic is found in snapshot/projection builders (`build_combined_projection` CC=48, `build_analytics_projection` CC=38) and domain query aggregators (`get_inventory` CC=35).
   - **Maintainability Index (MI = 0.0):** Three monolith files hit a Maintainability Index of **0.0 (Rank C)**:
     - [service.py](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/service.py) (1,632 LOC)
     - [site_health_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py) (2,899 LOC)
     - [test_site_health_worker.py](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py) (3,327 LOC)

4. **Dispatch Architecture:**
   - Background tasks do not use Celery; they execute through a Postgres-backed transactional queue ([postgres_task_queue.py](file:///c:/Projects/CiteLadder/backend/app/orchestration/postgres_task_queue.py)) leveraging `FOR UPDATE SKIP LOCKED` for task claiming, explicit lease renewals via heartbeats, and worker process ownership.
   - Individual SEO/AEO checks reach execution handlers via deterministic dictionary dispatch tables rather than direct function calls, preventing static analysis tools from seeing direct call-graph edges.

---

## 2. Dispatch / Registry Map

Background tasks and audit checks in CiteLadder are dispatched via string/enum lookup tables and transactional Postgres task queues.

```mermaid
flowchart TD
    subgraph Postgres Task Queue ("app/orchestration/postgres_task_queue.py")
        QueueRow[Postgres Task Queue Row<br/>FOR UPDATE SKIP LOCKED]
    end

    subgraph Workers ("app/workers/")
        AuditW[AuditWorker]
        SiteHealthW[SiteHealthWorker]
        AnalyticsW[AnalyticsWorker]
        ContentW[ContentWorker]
        IntegrationW[IntegrationWorker]
    end

    subgraph Registries & Dispatchers
        SHRules["_CHECKS Dict<br/>app/analysis/site_health/rules.py"]
        SHFinalize["Finalize Pass Functions<br/>app/analysis/site_health/finalize.py"]
        AnalyticsExec["_executors Dict<br/>app/workers/analytics_worker.py"]
        ContentExec["_executors Dict<br/>app/workers/content_worker.py"]
        IntegDispatcher["IntegrationDispatcher<br/>app/workers/integration_dispatcher.py"]
    end

    QueueRow -->|Claim Task| AuditW
    QueueRow -->|Claim Task| SiteHealthW
    QueueRow -->|Claim Task| AnalyticsW
    QueueRow -->|Claim Task| ContentW
    QueueRow -->|Claim Task| IntegrationW

    SiteHealthW -->|Rule ID Lookup| SHRules
    SiteHealthW -->|Crawl Finalize Reconcile| SHFinalize
    AnalyticsW -->|task_kind Lookup| AnalyticsExec
    ContentW -->|task_kind Lookup| ContentExec
    IntegrationW -->|provider/kind Lookup| IntegDispatcher
```

### Background Task Worker Loop Mechanics

All workers operate as independent long-running Docker container processes:

1. **Queue Claiming:** Workers invoke `PostgresTaskQueue.claim(owner=self.owner, limit=N)` in [postgres_task_queue.py](file:///c:/Projects/CiteLadder/backend/app/orchestration/postgres_task_queue.py#L125-L160) using SQL `FOR UPDATE SKIP LOCKED`.
2. **Lease Maintenance:** Workers launch an asynchronous background heartbeat task (`_heartbeat_loop`) that updates `leased_until` timestamps at half-lease intervals.
3. **Dispatch Resolution:**
   - **`AnalyticsWorker`** ([analytics_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/analytics_worker.py#L20-L45)): Maintains an `_executors` dict mapping `claimed.task_kind` strings to executor coroutines.
   - **`ContentWorker`** ([content_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/content_worker.py#L30-L50)): Maintains an `_executors` dict mapping task kinds to generator coroutines.
   - **`IntegrationWorker`** ([integration_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/integration_worker.py#L120-L150)): Dispatches tasks via [integration_dispatcher.py](file:///c:/Projects/CiteLadder/backend/app/workers/integration_dispatcher.py#L50-L100) based on provider kind and sync mode.
   - **`SiteHealthWorker`** ([site_health_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L607-L640)): Branches on `task.task_kind` to `_run_discover`, `_run_analyze`, or `_run_link_check`.

### Audit Rule Check Dispatch Mechanics

SEO and AEO rules are cataloged in `SITE_HEALTH_RULES` ([app/core/config/site_health.py](file:///c:/Projects/CiteLadder/backend/app/core/config/site_health.py)). Individual rule evaluations are dispatched as follows:

1. **Per-Page Analysis Rules:**
   - Evaluated by `evaluate_all(facts)` in [rules.py](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/rules.py#L709-L712).
   - Functions named `_check_*` (e.g., `_check_title_present`, `_check_structured_data_present`) are NOT called directly by name elsewhere in the code.
   - They are mapped inside `_CHECKS: dict[str, Callable[[dict], tuple[str, dict]]]` at [rules.py:591-622](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/rules.py#L591-L622).
   - `evaluate_rule(rule, facts)` looks up `_CHECKS.get(rule.rule_id)` at runtime ([rules.py:691](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/rules.py#L691)).

2. **Crawl Finalize Rules:**
   - Rules with applicability `crawl_finalize` (`technical.broken_internal_link`, `technical.sitemap_orphan`, `technical.hreflang_conflict`) are intentionally omitted from `_CHECKS` in `rules.py`.
   - They are dispatched during the worker's second pass inside `_reconcile_crawl_status` ([site_health_worker.py:2772](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L2772)) to functions defined in [finalize.py](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/finalize.py#L62-L150):
     - `evaluate_broken_internal_link`
     - `evaluate_sitemap_orphan`
     - `evaluate_hreflang_conflict`

---

## 3. Deep-Dive: site_health_worker.py & test_site_health_worker.py

The site health crawler core consists of two monolith files:
- [site_health_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py): **2,899 LOC**
- [test_site_health_worker.py](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py): **3,327 LOC**

### Architecture & Lifecycle Pipeline

`SiteHealthWorker` in [site_health_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L396) executes four discrete phases per crawl:

```mermaid
sequenceDiagram
    participant Queue as PostgresTaskQueue
    text over Worker: SiteHealthWorker Process
    Worker->>Queue: claim(SiteCrawlTask)
    
    rect rgb(235, 245, 255)
        note over Worker: Phase 1: DISCOVER
        Worker->>Worker: _run_discover()
        Worker->>Worker: Fetch robots.txt, well-known, sitemaps
        Worker->>Worker: Ingest sitemap URLs & seed frontier candidates
    end

    rect rgb(240, 255, 240)
        note over Worker: Phase 2: ANALYZE
        Worker->>Worker: _run_analyze()
        Worker->>Worker: SecureFetcher HTTP download & HTML extract
        Worker->>Worker: evaluate_all(facts) via rules.py _CHECKS
        Worker->>Worker: Enqueue link checks & persist page_analysis
    end

    rect rgb(255, 245, 235)
        note over Worker: Phase 3: LINK CHECK
        Worker->>Worker: _run_link_check()
        Worker->>Worker: Probe internal/external link targets
        Worker->>Worker: Persist link_reference rows
    end

    rect rgb(250, 235, 255)
        note over Worker: Phase 4: RECONCILE & FINALIZE
        Worker->>Worker: _reconcile_crawl_status()
        Worker->>Worker: _run_crawl_finalize_pass() (finalize.py)
        Worker->>Worker: _persist_snapshot()
    end
```

### Handler Dispatch Map within site_health_worker.py

Task handling enters via `_execute_claimed` ([site_health_worker.py:497](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L497)) and `_execute_task` ([site_health_worker.py:607](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L607)):

| Task Kind Token | Entry Handler | Internal Helper Functions Invoked |
| :--- | :--- | :--- |
| `TASK_KIND_DISCOVER` | [SiteHealthWorker._run_discover](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L672) | `_fetch_discover`, `_ensure_robots_policy`, `_fetch_well_known`, `_site_setup`, `_ingest_sitemaps`, `_persist_discover` |
| `TASK_KIND_ANALYZE` | [SiteHealthWorker._run_analyze](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L1776) | `_evaluate_analyze_guard`, `_fetch_analyze`, `_persist_analyze`, `_write_page_analysis` |
| `TASK_KIND_LINK_CHECK` | [SiteHealthWorker._run_link_check](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L2350) | `_load_link_check_source`, `_link_check_targets`, `_probe_link`, `_write_link_reference` |
| Crawl Terminalization | [SiteHealthWorker._reconcile_crawl_status](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L2603) | `_task_counts`, `_run_crawl_finalize_pass`, `_persist_snapshot` |

### Structural & Metric Breakdown

1. **Complexity Hotspots in `site_health_worker.py`:**
   - `_reconcile_crawl_status` ([line 2603](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L2603)): **CC = 26 (Rank D)**. Handles multi-task completion accounting, partial failure thresholds, cancellation state, and trigger logic for the finalize pass.
   - `_write_page_analysis` ([line 2175](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L2175)): **CC = 24 (Rank D)**. Assembles page facts, evaluates rules, constructs issue models, computes per-page scores, and generates link check tasks.
   - `_site_setup` ([line 1001](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L1001)): **CC = 18 (Rank C)**.
   - `_ingest_sitemaps` ([line 1099](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L1099)): **CC = 18 (Rank C)**.
   - `_write_attempt` ([line 1606](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L1606)): **CC = 16 (Rank C)**.
   - **Overall Maintainability Index:** **0.0 (Rank C)** due to class length and heavy inline AsyncSession database interactions.

2. **Complexity Hotspots in `test_site_health_worker.py`:**
   - `test_discover_site_setup_llms_stance_sitemap_and_finalize_orphan` ([line 3046](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py#L3046)): **CC = 40 (Rank E)**. Monolithic end-to-end component test setting up mock servers, discovery tasks, sitemap parsing, and orphan finalization assertions.
   - `test_finalize_pass_broken_link_and_hreflang_conflict_end_to_end` ([line 3217](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py#L3217)): **CC = 28 (Rank D)**.
   - `test_cancel_crawl_persists_partial_snapshot_from_completed_analyses` ([line 1724](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py#L1724)): **CC = 25 (Rank D)**.

---

## 4. Dead Code Findings Elsewhere

Dead code was audited using Vulture (min-confidence 60% and 80%) and Pyflakes.

### Tool Summary
- **Pyflakes:** 0 unused imports or variable redefinitions found across `app` and `tests`.
- **Vulture --min-confidence 80:** 0 findings across `app`.
- **Vulture --min-confidence 60:** 455 raw findings.

### Categorization of Vulture 60% Findings

```
┌────────────────────────────────────────────────────────────────────────┐
│ Total Vulture 60% Findings: 455                                        │
├────────────────────────────────────────────────────────────────────────┤
│ ├── False Positives (FastAPI Router Decorators): 139                   │
│ ├── False Positives (Pydantic / ORM Schema Attributes): 287            │
│ ├── False Positives (Worker Test Harness Methods): 5                   │
│ ├── False Positives (Analysis Rule Checks / Registry Mapped): 1        │
│ ├── Safe to Remove: 2                                                  │
│ └── Needs Verification: 21                                             │
└────────────────────────────────────────────────────────────────────────┘
```

#### A. Safe-to-Remove

1. [app/domain/analytics/enqueue.py:397](file:///c:/Projects/CiteLadder/backend/app/domain/analytics/enqueue.py#L397) — `enqueue_order_retention_sweep`
   - **Reasoning:** Defined as an async queue enqueuer for commerce order retention sweeps. A search across the entire codebase (`git grep "enqueue_order_retention_sweep"`) returns exactly **1 match** (its own definition). It is not invoked in any API endpoint, background worker, or test module.
2. [app/core/config/provider_catalog.py:53](file:///c:/Projects/CiteLadder/backend/app/core/config/provider_catalog.py#L53) — `transports_for_engine`
   - **Reasoning:** Helper function returning `frozenset` of approved transports for a logical engine. A repository-wide search returns **1 match** (its own definition). Other functions in the same module (`is_route_approved`, `is_active_transport`) handle routing verification.

#### B. Needs Verification

1. [app/domain/projects/normalization.py:40](file:///c:/Projects/CiteLadder/backend/app/domain/projects/normalization.py#L40) — `normalize_prompt_rows`
   - **Reasoning:** Used in `tests/unit/test_project_normalization.py`, but not referenced in any production endpoint in `app/api/` or `app/domain/`. Verify if CSV prompt import should use this or if it was superseded by `app/domain/prompts/csv_import.py`.
2. [app/orchestration/audit_state.py:76](file:///c:/Projects/CiteLadder/backend/app/orchestration/audit_state.py#L76) — `can_transition`
   - **Reasoning:** Unit tested in `tests/unit/test_audit_state.py`, but production code in `app/` calls `validate_transition` (which raises on invalid transitions) rather than `can_transition`.
3. [app/connectors/billing/base.py:43](file:///c:/Projects/CiteLadder/backend/app/connectors/billing/base.py#L43) & [app/connectors/billing/razorpay.py:162](file:///c:/Projects/CiteLadder/backend/app/connectors/billing/razorpay.py#L162) — `fetch_subscription`
   - **Reasoning:** Abstract interface method and concrete implementation on `RazorpayClient`. Billing service currently syncs subscription state via webhooks ([app/domain/billing/webhooks.py](file:///c:/Projects/CiteLadder/backend/app/domain/billing/webhooks.py)) rather than active polling via `fetch_subscription`.
4. [app/connectors/web_evidence/sitemaps.py:141](file:///c:/Projects/CiteLadder/backend/app/connectors/web_evidence/sitemaps.py#L141) — `url_count` property
   - **Reasoning:** Property on sitemap parser result class. Verify if callers use `len(result.urls)` instead.
5. [app/core/config/analytics.py:335](file:///c:/Projects/CiteLadder/backend/app/core/config/analytics.py#L335), [app/core/config/content.py:124](file:///c:/Projects/CiteLadder/backend/app/core/config/content.py#L124), [app/core/config/integrations.py:738](file:///c:/Projects/CiteLadder/backend/app/core/config/integrations.py#L738) — `_check_operational_bounds`
   - **Reasoning:** Config model validation methods. Verify if Pydantic v2 `@model_validator(mode="after")` decorator is correctly attached or if they are unannotated dead methods.
6. [app/core/config/site_health.py:1796](file:///c:/Projects/CiteLadder/backend/app/core/config/site_health.py#L1796) — `_validate_capability_limits` & [line 1815](file:///c:/Projects/CiteLadder/backend/app/core/config/site_health.py#L1815) — `_validate_lease_and_heartbeat`
   - **Reasoning:** Verify whether these validator methods are triggered during `SiteHealthSettings` instantiation or missing decorators.
7. [app/core/config/suggestions.py:82](file:///c:/Projects/CiteLadder/backend/app/core/config/suggestions.py#L82) & [line 126](file:///c:/Projects/CiteLadder/backend/app/core/config/suggestions.py#L126) — `_default_within_max`
   - **Reasoning:** Model validators for brand/prompt suggestion settings.
8. [app/domain/billing/schemas.py:41](file:///c:/Projects/CiteLadder/backend/app/domain/billing/schemas.py#L41) — `normalize_country`, [app/domain/content/schemas.py:31](file:///c:/Projects/CiteLadder/backend/app/domain/content/schemas.py#L31) — `_prompt_trimmed_bounded`, [app/domain/content/schemas.py:41](file:///c:/Projects/CiteLadder/backend/app/domain/content/schemas.py#L41) — `_output_type_known`, [app/domain/opportunities/schemas.py:31](file:///c:/Projects/CiteLadder/backend/app/domain/opportunities/schemas.py#L31) — `_known_status`, [app/domain/workspaces/schemas.py:41](file:///c:/Projects/CiteLadder/backend/app/domain/workspaces/schemas.py#L41) — `validate_step`
   - **Reasoning:** Field/model validator methods in Pydantic schema DTOs.
9. [app/connectors/answer_engines/normalization.py:54](file:///c:/Projects/CiteLadder/backend/app/connectors/answer_engines/normalization.py#L54) — `normalize_citation_url`
   - **Reasoning:** Duplicated between `app/analysis/normalization.py` and `app/connectors/answer_engines/normalization.py`. Check which module is the authoritative home.

#### C. False Positives (Rule Catalog, Router Decorators, ORM, Middleware, Event Listeners)

1. **FastAPI Endpoints (139 items):**
   - E.g., [app/api/audits.py:71](file:///c:/Projects/CiteLadder/backend/app/api/audits.py#L71) (`create_audit_endpoint`), [app/api/auth.py:86](file:///c:/Projects/CiteLadder/backend/app/api/auth.py#L86) (`register`).
   - **Reasoning:** Registered on FastAPI `APIRouter` via `@router.post(...)` or `@router.get(...)`.
2. **Analysis Rule Check Functions (30 items):**
   - E.g., [app/analysis/site_health/rules.py:102](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/rules.py#L102) (`_check_title_present`), [line 210](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/rules.py#L210) (`_check_structured_data_present`).
   - **Reasoning:** Invoked via `_CHECKS` dict lookup in `evaluate_rule`.
3. **ORM & Pydantic Schema Fields (287 items):**
   - E.g., `heartbeat_at`, `source_evaluation_ids`, `selecting_membership_id` across [app/models/site_health.py](file:///c:/Projects/CiteLadder/backend/app/models/site_health.py) and [app/models/analytics.py](file:///c:/Projects/CiteLadder/backend/app/models/analytics.py).
   - **Reasoning:** ORM columns and API response DTO attributes populated dynamically during database serialization.
4. **Middleware & SQLAlchemy Event Listeners:**
   - [app/main.py:119](file:///c:/Projects/CiteLadder/backend/app/main.py#L119) (`correlation_middleware`): Registered via `@app.middleware("http")`.
   - [app/models/prompt.py:182](file:///c:/Projects/CiteLadder/backend/app/models/prompt.py#L182) (`_sync_normalized_hash`): Registered via `@listens_for(Prompt, "before_insert")`.
5. **Worker Test Harness Methods:**
   - E.g., `run_until_idle` on `SiteHealthWorker` ([site_health_worker.py:582](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L582)), `AnalyticsWorker` ([analytics_worker.py:132](file:///c:/Projects/CiteLadder/backend/app/workers/analytics_worker.py#L132)), `AuditWorker` ([audit_worker.py:464](file:///c:/Projects/CiteLadder/backend/app/workers/audit_worker.py#L464)).
   - **Reasoning:** Explicit test harness method for draining queues synchronously in component tests.

---

## 5. Duplication Findings

Reported via `jscpd` across the codebase (450 total duplication blocks, 4.38% line duplication rate).

### Top Duplication Blocks in Application Code (`backend/app/`)

1. [app/domain/site_health/service.py:759-795](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/service.py#L759-L795) **vs** [app/domain/site_health/service.py:1031-1067](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/service.py#L1031-L1067)
   - **Lines:** 37 lines | **Tokens:** 201 tokens | **Similarity:** 100%
   - **Context:** Duplicate SQL query construction and keyset pagination filters between `get_issues` and `get_pages` list endpoints.
2. [app/models/analytics.py:271-297](file:///c:/Projects/CiteLadder/backend/app/models/analytics.py#L271-L297) **vs** [app/models/site_health.py:973-999](file:///c:/Projects/CiteLadder/backend/app/models/site_health.py#L973-L999)
   - **Lines:** 27 lines | **Tokens:** 160 tokens | **Similarity:** 100%
   - **Context:** Identical SQLAlchemy column definitions and index mixins for snapshot provenance tracking.
3. [app/models/analysis.py:66-91](file:///c:/Projects/CiteLadder/backend/app/models/analysis.py#L66-L91) **vs** [app/models/analysis.py:198-221](file:///c:/Projects/CiteLadder/backend/app/models/analysis.py#L198-L221) **and** [lines 242-265](file:///c:/Projects/CiteLadder/backend/app/models/analysis.py#L242-L265)
   - **Lines:** 26 lines | **Tokens:** 172 tokens | **Similarity:** 100%
   - **Context:** Identical score aggregation fields across audit run, prompt run, and project run ORM models.
4. [app/analysis/normalization.py:53-65](file:///c:/Projects/CiteLadder/backend/app/analysis/normalization.py#L53-L65) **vs** [app/connectors/answer_engines/normalization.py:54-66](file:///c:/Projects/CiteLadder/backend/app/connectors/answer_engines/normalization.py#L54-L66)
   - **Lines:** 13 lines | **Tokens:** 100 tokens | **Similarity:** 100%
   - **Context:** Identical URL citation normalization logic duplicated between analysis and connector layers.
5. [app/connectors/integrations/ga4.py:41-62](file:///c:/Projects/CiteLadder/backend/app/connectors/integrations/ga4.py#L41-L62) **vs** [app/connectors/integrations/gsc.py:23-44](file:///c:/Projects/CiteLadder/backend/app/connectors/integrations/gsc.py#L23-L44)
   - **Lines:** 22 lines | **Tokens:** 70 tokens | **Similarity:** 95%
   - **Context:** Identical OAuth token refresh retry loop and error handling logic.
6. [app/workers/content_worker.py:100-121](file:///c:/Projects/CiteLadder/backend/app/workers/content_worker.py#L100-L121) **vs** [app/workers/integration_worker.py:293-314](file:///c:/Projects/CiteLadder/backend/app/workers/integration_worker.py#L293-L314)
   - **Lines:** 22 lines | **Tokens:** 126 tokens | **Similarity:** 100%
   - **Context:** Identical worker `run_until_idle` queue draining loop implementation.

### Top Duplication Blocks in Test Code (`backend/tests/`)

1. [tests/component/test_analytics_snapshot.py:132-178](file:///c:/Projects/CiteLadder/backend/tests/component/test_analytics_snapshot.py#L132-L178) **vs** [tests/component/test_llm_analytics_api.py:183-229](file:///c:/Projects/CiteLadder/backend/tests/component/test_llm_analytics_api.py#L183-L229)
   - **Lines:** 47 lines | **Tokens:** 205 tokens | **Similarity:** 100%
2. [tests/component/test_integration_bing.py:186-217](file:///c:/Projects/CiteLadder/backend/tests/component/test_integration_bing.py#L186-L217) **vs** [tests/component/test_integration_ga4.py:279-310](file:///c:/Projects/CiteLadder/backend/tests/component/test_integration_ga4.py#L279-L310)
   - **Lines:** 32 lines | **Tokens:** 192 tokens | **Similarity:** 100%
3. [tests/component/test_site_health_worker.py:1746-1771](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py#L1746-L1771) **vs** [tests/component/test_site_health_worker.py:1916-1941](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py#L1916-L1941)
   - **Lines:** 26 lines | **Tokens:** 124 tokens | **Similarity:** 100%

---

## 6. Complexity Hotspots

Analysis performed using Radon Cyclomatic Complexity (CC) and Maintainability Index (MI).

### Top Complexity Hotspots in Application Code (`backend/app/`)

| File Path & Line | Function / Method Name | Radon Rank | Cyclomatic Complexity (CC) |
| :--- | :--- | :---: | :---: |
| [app/domain/attribution/snapshot.py:454](file:///c:/Projects/CiteLadder/backend/app/domain/attribution/snapshot.py#L454) | `build_combined_projection` | **F** | **48** |
| [app/domain/analytics/snapshot.py:297](file:///c:/Projects/CiteLadder/backend/app/domain/analytics/snapshot.py#L297) | `build_analytics_projection` | **E** | **38** |
| [app/domain/site_health/service.py:650](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/service.py#L650) | `get_inventory` | **E** | **35** |
| [app/analysis/product_scoring.py:937](file:///c:/Projects/CiteLadder/backend/app/analysis/product_scoring.py#L937) | `aggregate_product_run` | **E** | **34** |
| [app/domain/site_health/service.py:906](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/service.py#L906) | `get_pages` | **E** | **34** |
| [app/domain/attribution/snapshot.py:250](file:///c:/Projects/CiteLadder/backend/app/domain/attribution/snapshot.py#L250) | `build_a1_projection` | **E** | **31** |
| [app/domain/projects/service.py:201](file:///c:/Projects/CiteLadder/backend/app/domain/projects/service.py#L201) | `update_project` | **D** | **29** |
| [app/domain/content/website_context.py:124](file:///c:/Projects/CiteLadder/backend/app/domain/content/website_context.py#L124) | `build_website_context` | **D** | **28** |
| [app/domain/site_health/selection.py:374](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/selection.py#L374) | `replace_monitored_set` | **D** | **28** |
| [app/domain/traffic/projection.py:371](file:///c:/Projects/CiteLadder/backend/app/domain/traffic/projection.py#L371) | `build_traffic_projection` | **D** | **27** |
| [app/domain/attribution/service.py:276](file:///c:/Projects/CiteLadder/backend/app/domain/attribution/service.py#L276) | `get_attribution_orders` | **D** | **26** |
| [app/domain/commerce/service.py:49](file:///c:/Projects/CiteLadder/backend/app/domain/commerce/service.py#L49) | `get_catalog_health` | **D** | **26** |
| [app/workers/site_health_worker.py:2603](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L2603) | `SiteHealthWorker._reconcile_crawl_status` | **D** | **26** |
| [app/analysis/site_health/parser.py:241](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/parser.py#L241) | `_links_and_assets` | **D** | **25** |
| [app/analysis/product_service.py:359](file:///c:/Projects/CiteLadder/backend/app/analysis/product_service.py#L359) | `finalize_audit_product_analysis` | **D** | **24** |
| [app/workers/site_health_worker.py:2175](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py#L2175) | `SiteHealthWorker._write_page_analysis` | **D** | **24** |

### Top Complexity Hotspots in Test Code (`backend/tests/`)

| File Path & Line | Function / Method Name | Radon Rank | Cyclomatic Complexity (CC) |
| :--- | :--- | :---: | :---: |
| [tests/component/test_product_analysis_worker.py:179](file:///c:/Projects/CiteLadder/backend/tests/component/test_product_analysis_worker.py#L179) | `test_persisted_artifacts_rescore_to_v2_rows_and_snapshots` | **F** | **79** |
| [tests/component/test_integration_ga4.py:336](file:///c:/Projects/CiteLadder/backend/tests/component/test_integration_ga4.py#L336) | `test_fixture_import_refresh_artifacts_derivation` | **F** | **72** |
| [tests/component/test_attribution_api.py:385](file:///c:/Projects/CiteLadder/backend/tests/component/test_attribution_api.py#L385) | `test_serves_persisted_a1_projection` | **F** | **52** |
| [tests/component/test_opportunities_service.py:59](file:///c:/Projects/CiteLadder/backend/tests/component/test_opportunities_service.py#L59) | `test_recompute_persists_rows_and_snapshot_with_provenance` | **F** | **52** |
| [tests/component/test_integration_shopify.py:466](file:///c:/Projects/CiteLadder/backend/tests/component/test_integration_shopify.py#L466) | `test_shopify_sync_end_to_end` | **F** | **49** |

### Lowest Maintainability Index Modules (MI Rank C & B)

```
Maintainability Index Scale: 100-20 = Rank A (Very Good), 19-10 = Rank B (Medium), 9-0 = Rank C (Low)
```

| Module Path | Maintainability Index Score | Rank |
| :--- | :---: | :---: |
| [app/domain/site_health/service.py](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/service.py) | **0.00** | **C** |
| [app/workers/site_health_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py) | **0.00** | **C** |
| [tests/component/test_site_health_worker.py](file:///c:/Projects/CiteLadder/backend/tests/component/test_site_health_worker.py) | **0.00** | **C** |
| [tests/component/test_analysis_api.py](file:///c:/Projects/CiteLadder/backend/tests/component/test_analysis_api.py) | **2.30** | **C** |
| [tests/unit/test_site_health_rules.py](file:///c:/Projects/CiteLadder/backend/tests/unit/test_site_health_rules.py) | **6.18** | **C** |
| [tests/component/test_prompt_generation_api.py](file:///c:/Projects/CiteLadder/backend/tests/component/test_prompt_generation_api.py) | **6.76** | **C** |
| [tests/component/test_integrations_oauth_api.py](file:///c:/Projects/CiteLadder/backend/tests/component/test_integrations_oauth_api.py) | **8.85** | **C** |
| [app/analysis/product_scoring.py](file:///c:/Projects/CiteLadder/backend/app/analysis/product_scoring.py) | **11.49** | **B** |
| [app/domain/analysis/service.py](file:///c:/Projects/CiteLadder/backend/app/domain/analysis/service.py) | **13.91** | **B** |
| [app/analysis/site_health/parser.py](file:///c:/Projects/CiteLadder/backend/app/analysis/site_health/parser.py) | **14.86** | **B** |

---

## 7. TODO / FIXME / Deprecated Markers

A full regular expression search (`\b(TODO|FIXME|XXX|HACK|deprecated|DEPRECATED)\b`) was executed across all Python source files in `backend/`.

### Findings

- **`backend/app/` Hits:** **0**
- **`backend/tests/` Hits:** **0**
- **Repository-wide Context:**
  - 10 hits exist in documentation ([docs/marketing-content-audit.md](file:///c:/Projects/CiteLadder/docs/marketing-content-audit.md#L86), [docs/operations/security-production-audit-2026-07-27.md](file:///c:/Projects/CiteLadder/docs/operations/security-production-audit-2026-07-27.md#L651)) and frontend unit test assertions ([frontend/app/(marketing)/blog/page.test.tsx:140](file:///c:/Projects/CiteLadder/frontend/app/(marketing)/blog/page.test.tsx#L140)) where tests explicitly assert that user copy placeholders like `[TODO(user)]` are NOT rendered in marketing pages.

---

## 8. Open Questions

Before a refactoring plan is formulated based on this audit, the following architectural and verification questions must be resolved:

1. **Commerce Suite Retention Sweeps:** Is [enqueue_order_retention_sweep](file:///c:/Projects/CiteLadder/backend/app/domain/analytics/enqueue.py#L397) intended to be triggered via a cron/scheduled job (e.g., in a future release), or was it rendered obsolete by `enqueue_post_sync_projections`?
2. **Provider Catalog Routing Utility:** Should [transports_for_engine](file:///c:/Projects/CiteLadder/backend/app/core/config/provider_catalog.py#L53) be preserved as a public helper for external CLI scripts, or removed as dead code?
3. **Pydantic Validator Decorators:** Are the 5 config/schema validator methods identified in Section 4.B (e.g., [app/core/config/analytics.py:335](file:///c:/Projects/CiteLadder/backend/app/core/config/analytics.py#L335)) missing Pydantic `@model_validator(mode="after")` or `@field_validator` decorators, or are they uninvoked helper methods?
4. **Site Health Monolith Modularization:** Given that [site_health_worker.py](file:///c:/Projects/CiteLadder/backend/app/workers/site_health_worker.py) (2,899 LOC) and [service.py](file:///c:/Projects/CiteLadder/backend/app/domain/site_health/service.py) (1,632 LOC) both have a Maintainability Index of 0.0, should the refactoring plan prioritize splitting `SiteHealthWorker` into separate phase-specific worker classes (`DiscoverWorker`, `AnalyzeWorker`, `LinkCheckWorker`, `FinalizeWorker`)?
5. **Shared Citation Normalization:** Should the identical 13-line citation normalization logic in [app/analysis/normalization.py](file:///c:/Projects/CiteLadder/backend/app/analysis/normalization.py#L53-L65) and [app/connectors/answer_engines/normalization.py](file:///c:/Projects/CiteLadder/backend/app/connectors/answer_engines/normalization.py#L54-L66) be consolidated into a single common utility module?
