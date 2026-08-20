# Backend debt report — 2026-08-20

## 0. Method

**Sonar source:** no SonarQube/SonarCloud MCP server, no `sonar-project.properties`, no `SONAR_TOKEN` / `SONAR_LOGIN`, and GitHub has **no SonarCloud project** (workflows are only `ci.yml` and `compose-smoke.yml`). Local SonarQube **26.3.0.120487** at `C:\Users\abhij\Downloads\sonarqube-26.3.0.120487` was started and reached `status: UP` on `http://127.0.0.1:9000` (`api/system/status` id `147B411E-AZzrElexzwKLSyBn8rcK`). Default `admin:admin` is **invalid**; anonymous `api/projects/search` returns **401**. No issue export was possible. GitHub code scanning (CodeQL) has **0 open** alerts (historical alerts are dismissed/fixed; tool is CodeQL, not Sonar).

**Substitute used (labeled as such, not Sonar issues):**

- `uv run ruff check --select ALL --statistics .` (from `backend/`)
- `.venv/Scripts/radon.exe cc app -s -n B` and `mi app -s -n B`
- `.venv/Scripts/vulture.exe app --min-confidence 60`
- `uv run mypy app --strict` (report-only; CI only runs `mypy app` non-strict)
- `npx jscpd --pattern "backend/**/*.py"` with repo `jscpd.json`

**aislop:** `npx aislop@latest scan backend` then `… scan backend -d`. Version **0.14.1**. Exit code 1 (findings present); the raw scan output is not committed.

**Other inputs:** `backend/scripts/complexity_policy.json` (defaults `max_function_cc=12`, `max_module_loc=800`; **`exceptions.functions` and `exceptions.modules` are empty** — there is no frozen per-symbol complexity debt). CI already gates ruff `E,F,I,UP,B,W`, `mypy app`, complexity policy, `vulture --min-confidence 80`, pytest, pip-audit, detect-secrets. Radon in CI is advisory (`cc -n C`, `mi -n B`).

**Failed / incomplete:** Sonar issue import; `sonar-scanner` is not on PATH. `mypy --strict` was used as a substitute signal, not as a gate.

**aislop sample verification (≥10 flags, read in source):** listed in §4. True positives that survived reading the code are promoted into §2; the rest are rejected there.

**Marketplace scorecard (2026-08-20, 60.0 / “10 points from offer territory”):** reviewed as an external heuristic, not as authority. Claims about missing lint/CI, missing Compose, missing `/health`, missing structured logging, and a null `.env.example` were checked against `backend/` and rejected in §4 when false. Two backend-scoped gaps survived: liveness-only `/health`, and no pytest coverage tool or threshold. Frontend e2e isolation, git authorship span, tags, and “add docker-compose.yml” are out of this report’s `backend/` scope.

## 1. Executive summary

- CI already holds ruff/mypy/complexity/vulture-80/pytest to zero on the gated set. Remaining debt is **structural**: modules sitting 4–107 lines under the 800 LOC ceiling, functions at CC 11–12, and fail-open HTML extraction that tools still see because CI does not enable `S110`/`BLE001`.
- There is **no standing complexity-exception list**. The policy was already tightened to empty exceptions; the live risk is the **next feature** in `integration_worker.py` (796), `prompts/service.py` (789), `prompts/generation.py` (784), `site_health/rules.py` (784), `models/audit.py` (783), `parser.py` (769), `planner.py` (774).
- Site Health analysis is the densest maintainability cluster: `parser.py` plus `fact_links.py` / `fact_signals.py` copy `_text()` and wrap DOM walks in `except Exception: pass`, while `test_malformed_html_never_crashes` **encodes** that fail-open. Body-text junk removal already logs (`parser.py` ~321); sibling extractors do not.
- Runtime layering is mostly healthy (generic `PostgresTaskQueue`, analysis vs domain split for change-intel/AEO). Remaining leaks: **audit SSE/list loads every event then slices in Python** (Site Health already uses a SQL keyset), and the site-health router reaches a **private** `_crawl_count_disclosure`.
- Queue **behavior** is one implementation; queue **ORM columns** are copy-pasted across seven models (jscpd). That is documented as the shared contract, but it is how claim-order fields can drift.
- Scoring/opportunities/prompts are split into the right packages but each side is still a near-cap module. Product scoring already reuses `analysis/normalization.py`; the remaining mess is arity (`_persist_product_snapshots` 9–10 params) and CC-12 aggregators.
- Tests are the second codebase: 231 files, several **2.1k–2.3k line** component modules that call `_queue` / `_apply_funded_ledger`. `mypy` does not run on `tests/`. `--strict` on `app` reports **1013** errors in 197 files (mostly `type-arg` / `no-untyped-def`), so CI mypy is a shallow gate.
- aislop’s “AI slop” score (19/100) is dominated by **file-too-large@400** and **too-many-params@6**, both stricter than CiteLadder’s 800/12 policy. Treat those counts as noise unless they coincide with a real cluster below.
- Security tools did not surface an open production secret. `scripts/seed_dev_data.py:139` is an env-gated demo password. CodeQL open set is empty.
- Duplication (jscpd, `minLines` 15) is **0.08%** of scanned Python — not a clone farm. The six clones are queue-lease columns and integration-test fixtures.
- Observability is not “absent”: structlog JSON + optional Logfire are wired. What *is* missing is a **readiness** probe (DB/queue) behind `/health`, and **pytest-cov** with a threshold — both of which a marketplace scanner treated as missing logging/health/tests entirely.

## 2. Findings

### BD-01 — Site Health extractors fail-open by swallowing every DOM exception

- **ID**: `BD-01`
- **Severity**: high
- **Category**: correctness
- **Evidence**: `backend/app/analysis/site_health/parser.py:262`, `:440`, `:661` (`except Exception: pass`); same file has **20** `except Exception` sites. `backend/app/analysis/site_health/fact_links.py:56`, `:85`, `:109`. `backend/app/analysis/site_health/fact_signals.py:64`, `:87`. Contrast the already-logged path at `parser.py:321`. Tools: aislop `ai-slop/swallowed-exception` / `python-broad-except`; ruff ALL `S110`/`BLE001` (not in CI select).
- **Problem**: Analyze is supposed to persist **partial facts**, not crash on hostile HTML. The implementation does that by emptying the current fact bucket whenever lxml raises anything — including bugs and unexpected node types — with no log and no `error` outcome on that field. `_text()` is copy-pasted in parser, fact_links, and fact_signals, so the same silent contract is re-derived three times. Downstream rules then score “absent title / no CTAs / no forms” as real gaps.
- **Blast radius**: `app/analysis/site_health/{parser,fact_links,fact_signals}.py`, analyzer version bump, `workers/site_health/phases/analyze.py` persist path, issue/score snapshots. Hot path: every analyze task.
- **Test safety net**: `backend/tests/unit/test_site_health_parser.py` (`test_malformed_html_never_crashes` at `:200` **requires** no crash; `test_links_and_assets_classification` at `:136`; CTA/form tests `:405`/`:417`). `backend/tests/component/test_site_health_analyze.py`. The suite does **not** assert that a thrown DOM error is distinguishable from a genuinely empty page.
- **Fix sketch**: Keep fail-open, but narrow to `etree.Error` / `AttributeError` as the body-text path already does, log once at debug with `exc_info`, and share a single `_text` / `_iter_safe` helper. Bump extractor version so old analyses stay replayable.
- **Effort**: M
- **Risk of fixing**: medium (empty vs error changes issue counts on messy pages)

### BD-02 — Production modules are parked against the 800 LOC ceiling

- **ID**: `BD-02`
- **Severity**: high
- **Category**: architecture
- **Evidence**: measured LOC (physical lines): `backend/app/workers/integration_worker.py` 796; `domain/prompts/service.py` 789; `domain/prompts/generation.py` 784; `analysis/site_health/rules.py` 784; `models/audit.py` 783; `domain/traffic/service.py` 777; `workers/site_health/phases/analyze.py` 776; `domain/site_health/planner.py` 774; `analysis/site_health/parser.py` 769; `domain/billing/service.py` 768; `domain/opportunities/recompute.py` 756; `domain/agent/service.py` 749; `workers/site_health_worker.py` 742. Policy: `backend/scripts/complexity_policy.json` `max_module_loc: 800` with **no** module exceptions. Tool: aislop `complexity/file-too-large` (threshold 400, so it flags 92 files; the **policy-relevant** set is the 700–796 band). Radon MI `-n B`: `analysis/scoring.py` B 15.50, `domain/agent/service.py` B 13.41, `workers/commerce_discovery_worker.py` B 12.50.
- **Problem**: CI will not let these files grow. The debt is not “files exist”; it is that **ownership was split just enough to pass the gate**, so the next entitlement, rule, or provider field forces an emergency extract under the same owner (or a forbidden new exception). That is pre-approved-by-emptiness: the exceptions list cannot absorb them.
- **Blast radius**: whichever module is touched next; typically matching unit/component tests and a version bump if analysis formulas move. Hot paths: workers, planner, billing, prompts.
- **Test safety net**: exists per subsystem (e.g. `tests/component/test_integration_worker.py`, `test_prompt_generation_api.py`, `test_site_health_rules.py`, `test_audit_worker.py`) but those tests are themselves oversized (see BD-04).
- **Fix sketch**: When a change would add tens of lines, extract a cohesive helper **under the same owner** before coding the feature (phases mixins for Site Health already show the pattern). Do not raise `max_module_loc`.
- **Effort**: L (ongoing, per module)
- **Risk of fixing**: medium (import cycles, mixin MRO)

### BD-03 — `SiteHealthWorker` is still a 742-line process + persistence façade

- **ID**: `BD-03`
- **Severity**: high
- **Category**: architecture
- **Evidence**: `backend/app/workers/site_health_worker.py:1` still says Task 3 / **discover-only**; class at `:108` mixes `DiscoverPhaseMixin`, `AnalyzePhaseMixin`, `ChangeIntelPhaseMixin`; docstring at `:114` still says “discover rows”; `_write_attempt` at `:611` and `_finalize_queue_row` at `:686` remain on the façade while `phases/support.py:97` / `:132` are `NotImplementedError` protocol stubs. `phases/__init__.py:8` already documents why one process is required.
- **Problem**: Phase logic moved out, but the worker file still owns HTTP/browser pools, robots cache, artifact/attempt writes, and claim-loop comments that contradict shipped analyze/change-intel. Readers (and agents) follow the module docstring into the wrong mental model. Dual `_write_attempt` declarations make “where does an attempt row come from?” a hunt.
- **Blast radius**: `workers/site_health_worker.py`, `workers/site_health/phases/*`, `attempt_rows.py`. Hot path: site-health worker.
- **Test safety net**: `tests/component/test_site_health_discover.py`, `test_site_health_analyze.py`, `test_site_health_e2e.py`, `test_site_health_loop.py`, `test_site_health_terminalization.py`.
- **Fix sketch**: Move attempt/observation writers fully into `attempt_rows.py` / mixins; shrink the worker to construction, claim loop, and resource lifecycle; rewrite the module docstring to match analyze + change_intel.
- **Effort**: L
- **Risk of fixing**: high (lease, heartbeat, and persist ordering)

### BD-04 — Component tests are a second 80k-LOC product that pins internals

- **ID**: `BD-04`
- **Severity**: high
- **Category**: test-debt
- **Evidence**: largest tests: `backend/tests/component/test_site_health_api.py` 2330 lines; `test_audit_worker.py` 2307; `test_analysis_api.py` 2158; `test_opportunities_service.py` 1487; `test_site_health_terminalization.py` 1461. Four of those exceed 1000 LOC (marketplace `god_files` callout; their counts were ~2136 / ~2002 when scored). ruff ALL `SLF001` on production-adjacent tests (e.g. `test_audit_worker.py` accessing `_apply_funded_ledger`; `test_funded_terminalization.py` `_queue` / `_sweep_expired_leases`). aislop does not flag tests; this is **manual**.
- **Problem**: The suite is doing real Postgres component work (good), but several files are **god tests**: they import worker internals and assert method names. A safe refactor of funded terminalization or the site-health API then rewrites thousands of lines of tests. Volume also hides slow session-scoped loop coupling (`pyproject.toml` asyncio session loop comments).
- **Blast radius**: the named test files plus helpers `tests/component/audit_helpers.py`, `site_health_helpers.py`. Not a runtime path, but it blocks every worker/API change.
- **Test safety net**: these *are* the net.
- **Fix sketch**: Split by scenario (happy path / cancel / lease / funded) without adding a parallel framework. Replace private-attribute assertions with observable rows/events. Keep one e2e file.
- **Effort**: L
- **Risk of fixing**: medium (coverage holes while splitting)

### BD-05 — Audit event list/SSE loads the full history, then filters in Python

- **ID**: `BD-05`
- **Severity**: high
- **Category**: performance
- **Evidence**: `backend/app/api/audits.py:432` `_load_events` — `select(AuditEvent).where(audit_id==…).order_by(created_at, id)` then a Python scan for `after` (`:440`–`:450`). `AuditEvent` indexes `audit_id` and `created_at` separately (`models/audit.py:641`, `:650`) with **no** `(audit_id, created_at, id)` keyset. Contrast Site Health: `domain/site_health/service/lifecycle.py:541` documents and implements SQL keyset resume. Site Health **JSON** list still dumps all events: `api/site_health/events_exports.py:117`. Tool: **manual** (not Sonar). Tests: `tests/component/test_audit_events_sse.py:153` even says it “mirrors `_load_events`”.
- **Problem**: Site Health already paid for the correct resume pattern. Audits still pull every lifecycle event per poll/list. A 30-prompt × 3-engine run with retries produces a large append-only stream; SSE polling (`_event_stream` at `audits.py:466`) repeats that load. This is request-path, not leaf code.
- **Blast radius**: `app/api/audits.py`, possibly `domain/audits` if the query moves; `models/audit.py` for a composite index (fold into `0001_initial.py` per repo policy). Tests in `test_audit_events_sse.py`.
- **Test safety net**: `backend/tests/component/test_audit_events_sse.py`. Site Health: `test_site_health_lifecycle.py:537` (`test_load_events_resumes_after_the_anchor`).
- **Fix sketch**: Copy the Site Health keyset (`created_at`, `id`) into `_load_events`; add the matching index. Optionally page the JSON list.
- **Effort**: M
- **Risk of fixing**: low (behavior is already specified: resume strictly after cursor)

### BD-06 — Queue lease columns are duplicated across seven ORM models

- **ID**: `BD-06`
- **Severity**: medium
- **Category**: architecture
- **Evidence**: jscpd clones: `models/analytics.py:118`–`:139` vs `models/discovery.py:104`–`:123` vs `models/site_health/queue.py:131`–`:152` vs `models/integrations.py` (same lease block); `models/audit.py:409`–`:428` vs `models/content.py:100`–`:119`. Comments even say “identical contract to SiteCrawlTask” (`analytics.py:121`). Runtime is already generic: `orchestration/postgres_task_queue.py:12`. `AuditTask.randomized_position` lives **above** the “Queue + lease state” comment (`audit.py:395` vs `:412`), unlike the others.
- **Problem**: Claim/lease **code** was genericized; the **schema** was not. A new status, heartbeat column, or claim-order field must be edited in every model + `0001_initial.py`. The comment-separated `randomized_position` on `AuditTask` is how that drift starts.
- **Blast radius**: `app/models/{audit,analytics,content,discovery,commerce,integrations,site_health/queue}.py`, Alembic `0001_initial.py`, `PostgresQueueSpec` consumers. Hot path: every worker.
- **Test safety net**: `tests/component/test_task_queue_content.py`, `test_integration_queue.py`, `test_audit_worker.py`, site-health loop tests.
- **Fix sketch**: A mapped mixin or `@declared_attr` mixin for the lease columns only — still one table per kind. Do not invent a second queue implementation.
- **Effort**: L
- **Risk of fixing**: high (migration/ORM identity)

### BD-07 — Site Health HTTP layer calls a private disclosure helper

- **ID**: `BD-07`
- **Severity**: medium
- **Category**: architecture
- **Evidence**: `backend/app/api/site_health/events_exports.py:81` and `:115` `service._crawl_count_disclosure(crawl)`. Definition: `domain/site_health/service/presentation.py:127`. Re-export with an explicit “router shouldn’t know the module” comment: `service/__init__.py:109`. ruff ALL `SLF001` (not in CI).
- **Problem**: Count redaction is a product invariant. The API bypasses a public function and binds to an underscore name that the package re-exports for historical reasons. That is leaky layering: presentation policy should be a named domain function the router is allowed to call.
- **Blast radius**: `api/site_health/events_exports.py`, `domain/site_health/service/{presentation,__init__}.py`. Request path (SSE + JSON events).
- **Test safety net**: `tests/unit/test_site_health_events_exports.py`, `tests/component/test_site_health_api.py`.
- **Fix sketch**: Rename to `crawl_count_disclosure` (public) and stop exporting the underscore. No behavior change.
- **Effort**: S
- **Risk of fixing**: low

### BD-08 — Visibility/product scoring is at the CC cap in multiple aggregators

- **ID**: `BD-08`
- **Severity**: medium
- **Category**: maintainability
- **Evidence**: radon `cc -n B`: `analysis/product_scoring_aggregation.py` `_mentioned_id_sets` **C (12)** at `:201`, `_execution_summary` C (11) at `:138`; `analysis/product_service.py` `_apply_snapshot_fields` C (11) at `:569`; `analysis/scoring.py` many B-rank helpers, file 710 LOC, MI B 15.50. aislop too-many-params: `product_service.py:123`, `:236`, `:431`, `:477`, `:569`. Complexity policy `max_function_cc: 12` — these cannot gain a branch.
- **Problem**: Brand scoring and product scoring are correctly **separate** (product_scoring.py:1–14 states they share `normalization.py`). The remaining debt is **aggregation and persistence**: snapshot upserts take 9–10 parameters and sit at the cyclomatic ceiling. The next product dimension will not fit.
- **Blast radius**: `analysis/scoring.py`, `product_scoring.py`, `product_scoring_aggregation.py`, `product_service.py`, `analysis/service.py`. Worker finalize path after audits.
- **Test safety net**: `tests/unit/test_analysis_scoring.py`, `test_product_scoring_v2.py`, `tests/component/test_analysis_api.py`.
- **Fix sketch**: Pack snapshot fields into a small dataclass owned by `product_service`; split `_mentioned_id_sets` by dimension. Bump scoring versions if formula output can change.
- **Effort**: L
- **Risk of fixing**: medium

### BD-09 — Opportunity recompute is a 756-line loader glued to 543-line detectors

- **ID**: `BD-09`
- **Severity**: medium
- **Category**: maintainability
- **Evidence**: `domain/opportunities/recompute.py` 756 LOC; `_load_visibility_evidence` at `:187` (aislop: 101 lines). `analysis/opportunities/detectors.py` 543 LOC; `_gap_hit` at `:213` (7 params). `recompute.py:9` imports the detector set. Radon: `recompute.py` `_snapshot_is_current` C (12) `:580`, `_write_recompute` C (11) `:602`; `snapshot_build.py` `build_snapshot` C (12).
- **Problem**: Analysis vs domain split is right (pure detect vs persist). The domain file still **loads every evidence kind, scores, and writes** in one module at the LOC/CC wall. Detectors accumulate gap helpers with growing arity instead of a `GapContext` object.
- **Blast radius**: `domain/opportunities/*`, `analysis/opportunities/*`, post-audit workers. Tests: `test_opportunities_service.py` (1487 lines).
- **Test safety net**: `tests/component/test_opportunities_service.py`, `tests/unit/test_opportunity_scoring.py`, `test_opportunity_guidance_schemas.py`.
- **Fix sketch**: Extract loaders (`_load_visibility_evidence`) to `recompute_load.py` under the same package; introduce one context object for `_gap_hit`.
- **Effort**: L
- **Risk of fixing**: medium

### BD-10 — Prompt generation and prompt CRUD are two near-cap services

- **ID**: `BD-10`
- **Severity**: medium
- **Category**: maintainability
- **Evidence**: `domain/prompts/generation.py` 784 LOC; `domain/prompts/service.py` 789 LOC. API `generate_prompts_endpoint` radon C (11) at `api/prompts.py:392` — the handler is a long exception/status map over domain calls, not a second generator. aislop function-too-long does not flag generation.py’s inner builders as much as `create_audit`.
- **Problem**: Generation vs library service **is** the right split, but each file is one rule away from the complexity gate. CSV import, occupancy, and AI generation receipts keep landing in `service.py` / `generation.py` instead of a third owner under `domain/prompts/`.
- **Blast radius**: `domain/prompts/*`, `api/prompts.py`. Request path for generate/import.
- **Test safety net**: `tests/component/test_prompt_generation_api.py` (1378 lines), `test_projects_prompts_api.py`, `tests/unit/test_prompt_receipts.py`.
- **Fix sketch**: Move CSV parse / occupancy checks to existing helpers; keep HTTP mapping in the router. Split generation receipts from model I/O if the next change needs room.
- **Effort**: M
- **Risk of fixing**: medium

### BD-11 — `models/audit.py` mixes audit aggregate, tasks, events, and capacity

- **ID**: `BD-11`
- **Severity**: medium
- **Category**: architecture
- **Evidence**: `backend/app/models/audit.py` 783 LOC. `AuditEvent` at `:633`; `ProviderCapacityBucket` at `:657` in the **same** module as `Audit` / `AuditTask`.
- **Problem**: Site Health already split crawl/queue/urls models. Audits still use one file for the measurement run **and** the shared provider-capacity table. That couples unrelated migrations and keeps the file on the 800 cap.
- **Blast radius**: `models/audit.py` split, all audit imports, `0001_initial.py` (table names can stay). Tests across audit/capacity.
- **Test safety net**: `tests/component/test_audit_worker.py`, `test_audit_planner.py`, capacity tests in the same files.
- **Fix sketch**: Move `ProviderCapacityBucket` beside `orchestration/provider_capacity.py`’s model home (new module under `models/`, not a second table). Keep `AuditEvent` with audit if desired.
- **Effort**: M
- **Risk of fixing**: medium (import graph)

### BD-12 — Integration worker cannot absorb another provider without a split

- **ID**: `BD-12`
- **Severity**: medium
- **Category**: architecture
- **Evidence**: `workers/integration_worker.py` 796 LOC; radon `IntegrationWorker._sync_dataset` C (11) at `:555`. Header `:1` still lists GSC/GA4/Bing; Shopify is already a connector. aislop file-too-large.
- **Problem**: This is the hottest remaining worker file vs the 800 cap (4 lines of slack). Dataset paging already lives in `workers/integration/paging.py`; the worker still owns capability mutation (`:545`) and dataset sync.
- **Blast radius**: `workers/integration_worker.py`, `workers/integration/*`. Hot path: integration worker.
- **Test safety net**: `tests/component/test_integration_worker.py`, `test_integration_worker_failures.py`, per-provider `test_integration_{ga4,bing,shopify}.py`.
- **Fix sketch**: Move `_sync_dataset` / GA4 capability writes into `workers/integration/` modules already used for tokens/artifacts/finalization.
- **Effort**: M
- **Risk of fixing**: medium

### BD-13 — CI mypy is a shallow gate; `--strict` still finds 1013 issues

- **ID**: `BD-13`
- **Severity**: medium
- **Category**: maintainability
- **Evidence**: `uv run mypy app --strict` → **1013 errors in 197 files**. Clusters: `domain/projects/onboarding/{research,service}.py` (`no-untyped-def`, `type-arg`); `domain/command_center/service.py`; `workers/site_health/phases/analyze.py`; `api/demand.py`; `api/audits.py:466` untyped `_event_stream`. CI: `mypy app` without `--strict` (and **not** `tests/`). App `type: ignore` is rare and justified (`main.py:131` Starlette handler types). `parser.py` uses `Any` for lxml nodes (ruff ALL `ANN401` 144 hits repo-wide, many in tests).
- **Problem**: The gated typechecker cannot see untyped defs or bare `dict`. Onboarding research and command-center PDF/report code are especially untyped. That is how `Any` spreads into workers without failing CI.
- **Blast radius**: gradual `disallow_untyped_defs` per package. Not a user-facing path by itself.
- **Test safety net**: none for typing of tests; app tests still run.
- **Fix sketch**: Turn on `disallow_untyped_defs` for one package at a time starting with `app/api` and `app/workers`. Leave lxml as `Any` with a tiny helper type if needed.
- **Effort**: L
- **Risk of fixing**: low per package, high if done globally in one PR

### BD-14 — Growth Agent domain service is submit + claim + execute in 749 lines

- **ID**: `BD-14`
- **Severity**: medium
- **Category**: architecture
- **Evidence**: `domain/agent/service.py` 749 LOC, radon MI B 13.41. `execute_claimed_task` at `:220` (aislop: 158 lines). Worker `workers/agent_worker.py` is thin (claim loop only).
- **Problem**: The worker is correctly small; the domain module still owns idempotent submit, lease claim, tool loop, and persistence. That is a god service on the agent hot path (user-triggered, not autonomous publish).
- **Blast radius**: `domain/agent/service.py` split under `domain/agent/`. Tests: `tests/component/test_growth_agent_api.py`.
- **Test safety net**: `test_growth_agent_api.py`, `tests/unit/test_default_agent_client.py`.
- **Fix sketch**: `submit.py` / `claim.py` / `execute.py` in the same package; keep `service.py` as re-exports if import churn is painful.
- **Effort**: M
- **Risk of fixing**: medium

### BD-15 — `create_audit` is still a 220-line admission shell

- **ID**: `BD-15`
- **Severity**: medium
- **Category**: maintainability
- **Evidence**: `domain/audits/creation.py:54` `create_audit` through ~`:273` (aislop function-too-long, 220 lines). `_create_audit_tasks` **11 params** at `task_creation.py:36`. Comment at `creation.py:75` calls it an orchestration shell that “adds no branching.”
- **Problem**: Policy was extracted (`frozen_plan`, `funded_admission`, `task_creation`) but the shell still sequences every collaborator in one function. Eleven-parameter task creation is the same “options object” smell aislop reports — here it is real because admission, funding, and snapshots must stay atomic.
- **Blast radius**: `domain/audits/creation.py`, `task_creation.py`, `funded_admission.py`. Request path `POST /audits`.
- **Test safety net**: `tests/component/test_audit_planner.py`, `test_funded_admission.py`, `test_audit_worker.py`.
- **Fix sketch**: A `_AdmissionParts` dataclass for `_create_audit_tasks`; optionally split “draft persist” vs “queue + events” helpers without extra commits.
- **Effort**: M
- **Risk of fixing**: high (funding/idempotency)

### BD-16 — Site Health JSON event list is still unbounded

- **ID**: `BD-16`
- **Severity**: medium
- **Category**: performance
- **Evidence**: `api/site_health/events_exports.py:117` `load_events(..., crawl_id=)` with no `after`. `load_events` keyset only applies when `after` is set (`lifecycle.py:562`). Manual.
- **Problem**: SSE resume was fixed; the JSON replay used by the UI still materializes the crawl’s entire event log. Long crawls with progress events will grow this payload without a page size.
- **Blast radius**: `events_exports.py`, `lifecycle.py` (optional limit). Request path.
- **Test safety net**: `tests/component/test_site_health_api.py`, `test_site_health_lifecycle.py`.
- **Fix sketch**: Cap the JSON list (config-owned limit) or require a cursor. Do not change SSE semantics.
- **Effort**: S
- **Risk of fixing**: medium (UI assumes full replay)

### BD-17 — Execution evidence uses four serial queries for one task

- **ID**: `BD-17`
- **Severity**: low
- **Category**: performance
- **Evidence**: `domain/analysis/evidence.py:289` analysis; `:297` citations; `:308` `AuditTask`; `:309` `Audit`. Manual. (List path nearby batches mentions/citations by analysis id — `:250`.)
- **Problem**: Not an N+1 loop, but four round-trips for a detail endpoint that already knows `task_id` + `workspace_id`. Fine at current scale; wasteful if this becomes a hot dashboard poll.
- **Blast radius**: `domain/analysis/evidence.py`. Request path `GET` execution evidence.
- **Test safety net**: `tests/component/test_analysis_api.py`.
- **Fix sketch**: One `select` with joins / `selectinload` for task+audit+citations.
- **Effort**: S
- **Risk of fixing**: low

### BD-18 — Fetch HTTP/cURL rungs are 100–191 line functions on the crawl hot path

- **ID**: `BD-18`
- **Severity**: low
- **Category**: maintainability
- **Evidence**: aislop function-too-long: `connectors/web_evidence/fetcher_http.py:107` `_fetch_http` 191 lines; `fetcher_ladder.py:166` `_fetch_curl` 109 lines. Radon: `CurlCffiTransport.fetch` C (11); `SecureFetcher.__init__` C (11). Timeouts **are** present (`fetcher.py:177`, curl/httpx timeout args) — not a missing-timeout finding.
- **Problem**: SSRF-safe fetch is inherently branchy. The debt is operational: retry/trace/body-limit policy lives inside the rung functions, so a timeout or header change edits a 191-line procedure. Complexity policy still passes (CC ≤ 12).
- **Blast radius**: `connectors/web_evidence/fetcher_http.py`, `fetcher_ladder.py`, `fetcher.py`. Hot path: every discover/analyze fetch.
- **Test safety net**: `tests/unit/test_web_fetcher.py` (1142 lines), `test_curl_transport.py`, `test_browser_transport.py`.
- **Fix sketch**: Extract “build request / read body / classify error” helpers in the same package without changing the ladder order.
- **Effort**: M
- **Risk of fixing**: high (SSRF and attempt traces)

### BD-19 — Planner create-crawl functions are 157–212 lines of control validation + enqueue

- **ID**: `BD-19`
- **Severity**: medium
- **Category**: maintainability
- **Evidence**: aislop: `domain/site_health/planner.py:391` `create_crawl` 212 lines; `:603` `create_page_rerun_crawl` 157 lines. File 774 LOC. Radon `create_crawl` / `create_page_rerun_crawl` C (11).
- **Problem**: Crawl admission (entitlement, seeds, monitored set, task enqueue) is one of the most important mutations in the product. It is still one procedure per entrypoint, sitting on the LOC and CC ceilings.
- **Blast radius**: `domain/site_health/planner.py`, `planner_controls.py`, `planner_preview.py`. Request path: create crawl / rerun.
- **Test safety net**: `tests/component/test_site_health_api.py`, `test_site_health_selection.py`, `test_site_health_discover.py`.
- **Fix sketch**: Reuse `planner_controls.py` more aggressively; move enqueue loops next to `frontier.py` / `frontier_support.py` which already exist.
- **Effort**: L
- **Risk of fixing**: high

### BD-20 — `scripts/seed_dev_data.py` is an 838-line / 570-line-function seeder

- **ID**: `BD-20`
- **Severity**: low
- **Category**: maintainability
- **Evidence**: `scripts/seed_dev_data.py` 837 LOC; aislop `seed` at `:266` 570 lines. Password at `:139` (see §4). Not in `app/` complexity roots.
- **Problem**: Dev seed is allowed to be ugly, but a 570-line `seed()` mixes users, projects, prompts, crawls, and drain. Onboarding eval (`scripts/run_onboarding_eval.py`) is a similar script god. This does not hit CI complexity policy (`roots: ["app"]`).
- **Blast radius**: `scripts/seed_dev_data.py`, `seed_dev_support.py`.
- **Test safety net**: `tests/unit/test_provision_dev_login.py` (partial); no full seed test.
- **Fix sketch**: Keep env guard; split seed chapters into `seed_dev_support.py` functions already started.
- **Effort**: M
- **Risk of fixing**: low

### BD-21 — `/health` is process-alive only; it never checks Postgres or the queue

- **ID**: `BD-21`
- **Severity**: medium
- **Category**: correctness
- **Evidence**: `backend/app/main.py:171`–`:173` returns `{"status": "ok"}` with no session, `SELECT 1`, or worker liveness. `backend/tests/component/test_health.py:14` asserts exactly that body. Compose smoke waits on the same JSON (`compose-smoke.yml` curl `| grep -qx '{"status":"ok"}'`). Scheduler has a **separate** file-mtime `healthcheck()` at `workers/audit_scheduler.py:272`. Tool: marketplace scorecard (`has_health_endpoint` false — detector miss); the real gap is **manual** after reading `health()`.
- **Problem**: Load balancers and `docker compose` treat HTTP 200 as “the stack can serve.” This handler stays 200 if the API process is up and the database is down, migrations have not run, or every worker is dead. Logfire/structlog do not compensate: they observe requests that already reached the process. A dedicated `/ready` (or a DB ping inside `/health`) is the missing contract, not the missing route.
- **Blast radius**: `app/main.py`, `tests/component/test_health.py`, `.github/workflows/compose-smoke.yml` (exact-body grep), any compose healthcheck that copies that JSON. Request path, every deploy.
- **Test safety net**: `backend/tests/component/test_health.py` — currently **locks in** the shallow contract. None assert database connectivity.
- **Fix sketch**: Keep `/health` as liveness if desired; add `/ready` (or a `?deep=1`) that `SELECT 1` through `SessionLocal` with a short timeout and returns 503 on failure. Update the smoke grep and the component test. Do not call providers or crawl from the probe.
- **Effort**: S
- **Risk of fixing**: low (smoke and k8s probes must be updated together)

### BD-22 — Backend pytest has no coverage tool or fail-under threshold

- **ID**: `BD-22`
- **Severity**: low
- **Category**: test-debt
- **Evidence**: `backend/pyproject.toml` `[tool.pytest.ini_options]` (`:70`–`:80`) has `testpaths` and asyncio loop scopes only — no `--cov`. Dev extra in the same file lists pytest/mypy/ruff/radon/vulture, not `pytest-cov`. CI backend job runs `.venv/bin/python -m pytest -vv` with no coverage flags (`.github/workflows/ci.yml`). Frontend has `pnpm test:coverage` / `@vitest/coverage-v8`; backend has the equivalent gap. Tool: marketplace `coverage_threshold` / `coverage_tooling` null — **verified** for `backend/`.
- **Problem**: The suite is large (81k LOC tests) but CI cannot tell if a PR deleted assertions that used to cover `planner.py` or `product_scoring_aggregation.py`. Volume without a measured floor is how god tests (BD-04) coexist with untested seams. This is not “no tests”; it is **no enforced coverage signal**.
- **Blast radius**: `backend/pyproject.toml` optional-dev extra, CI backend job, possibly a `fail_under` once a baseline exists. Not a runtime path.
- **Test safety net**: the existing pytest run; no coverage artifact today.
- **Fix sketch**: Add `pytest-cov` to the `dev` extra, emit XML/term in CI, and land a conservative `fail_under` only after measuring current `app/` coverage so the first PR is not a surprise red build. Exclude `migrations/` and `scripts/`.
- **Effort**: M
- **Risk of fixing**: low if the threshold is set from a measured baseline; high if a guessed 80% is gated immediately

## 3. Clusters

**C1 — Site Health facts/rules/worker (BD-01, BD-03, BD-07, BD-16, BD-18, BD-19)**
One pass: shared DOM helpers + logged fail-open; finish moving persistence off `site_health_worker.py`; public disclosure helper; JSON event cap; planner/fetch splits only when those files must change.

**C2 — Complexity ceiling (BD-02, BD-08, BD-09, BD-10, BD-11, BD-12, BD-14, BD-15)**
Do not raise caps. Extract under the existing owner when a feature needs room. Highest urgency: `integration_worker.py` (796) and prompt modules (784–789).

**C3 — Queue contract copies (BD-06)**
Mixin the lease columns after a dedicated migration-policy conversation (still single `0001_initial.py`).

**C4 — Event reads (BD-05, BD-16)**
Audit keyset first (parity with Site Health SSE). Then bound JSON lists.

**C5 — Test corpus (BD-04, BD-13, BD-22)**
Split god component files when touching those subsystems; optionally type `app/api` more strictly. Add coverage tooling after a measured baseline. Do not enable aislop’s 400-line file rule on this repo.

**C6 — Readiness vs liveness (BD-21)**
Separate process-up from database-up. Touch smoke and `test_health.py` in the same change.

## 4. Rejected / false positives

**Complexity policy exceptions:** none. Empty lists are not hidden debt.

**CI-gated tools:** ruff `E,F,I,UP,B,W` clean; `mypy app` (non-strict) clean; vulture **80** clean; function CC ≤ 12 and module LOC ≤ 800 with no exceptions. Do not “fix” those.

**aislop `complexity/file-too-large` (92) and `too-many-params` (105):** thresholds 400 LOC / 6 params. CiteLadder’s gate is 800 / (no param rule). Flagged files such as `core/config/site_health_rules.py` (763) are **catalog/config**, which AGENTS.md wants in config modules. `_check_indexable` (`analysis/site_health/rules.py:154`) is a catalog adapter, not a pointless wrapper. `advanced_controls_requested` (`planner_controls.py:16`) is the public name over `_advanced_requested`. `_clean_aliases` (`domain/products/schemas.py:34`) exists so pydantic can attach a distinct validator.

**aislop swallowed-exception / broad-except false positives (verified):**

- `connectors/integrations/ga4.py:258` — `except ValueError: pass` then `float()`; not bare `except`.
- `domain/integrations/derive.py:129` — ISO date then compact GA4 date.
- `domain/projects/logos.py:160` — `except TimeoutError` after `asyncio.timeout` (budgeted gather).
- `domain/site_health/service/lifecycle.py:366` / `:370` — `except InvalidSiteCrawlTransition` only; comments at `:361` explain why `Exception` was removed.
- `workers/agent_worker.py:58` — `except TimeoutError` on `wait_for` of the stop event (idle poll).
- `core/database.py:69` — rollback failure logs with `exc_info=True`; not a silent continue.

**aislop hardcoded-url / provider-id (verified false for “env-specific deployment”):**

- `analysis/scoring.py:172` — documented Google grounding host in a comment + parsed-host check (CodeQL history).
- `connectors/answer_engines/openai_parser.py:22` — fixture JSON in a docstring.
- `connectors/web_evidence/browser_transport.py:156` — comment example `https://host:8443/`.
- `core/config/billing_settings.py:77` — Razorpay **API default**, overridable.
- `core/config/content.py:113` — Mistral default endpoint, env alias `CONTENT_PROVIDER_ENDPOINT`.
- `core/config/integrations_transport.py:78` — Google/Bing OAuth **scope URIs**, not a tenant URL.
- `core/config/integrations_contracts.py:65` — error **code** `token_refresh_failed`, not a project id.

**aislop meta-comment:** `workers/audit_worker.py:1`, `domain/site_health/state_events.py:1`, `core/config/opportunities.py:491` (“v1/v2 rule id”) are **invariant/version comments**, the same class as the `python-multipart` / asyncio loop comments in `backend/pyproject.toml`. Not slop.

**aislop chained `.get`:** `billing_catalog.py:168` is `credit_prices_by_cadence.get(cadence, {}).get(region)` on a frozen dataclass — a typed catalog lookup, not schema-evasion. `prompt_generation.py:101` is fallback template load with an explicit `RuntimeError` if groups are missing (`:114`).

**aislop / ruff security `scripts/seed_dev_data.py:139` `DEMO_PASSWORD`:** development-only, fail-closed env set at `:145`. Not production secret debt.

**ruff ALL (not CI):** `S101` 9772 asserts in tests; `COM812`/`D1xx` docstring/style; `CPY001` copyright; `S608` at `tests/conftest.py:90` is identifier-quoted `DELETE FROM` cleanup, not user SQL; `S311` at `task_creation.py:217` is `random.Random(int(seed)).shuffle` with `# NOSONAR` — **deterministic**, not crypto; `ASYNC109`/`ASYNC110`/`ASYNC240` in tests/scripts; `S104` in `test_web_url_policy.py`.

**vulture `--min-confidence 60`:** FastAPI route functions look unused (no direct calls). CI’s 80% gate is the right one.

**jscpd test clones:** `test_integration_bing.py` vs `test_integration_ga4.py` fixture overlap; intra-file clone in `test_site_health_terminalization.py`. Test duplication, not app logic.

**Layering that looks like duplication but is ownership:** `analysis/site_health/change_intel.py` vs `domain/site_health/change_intel.py` (pure compare vs persist); `analysis/site_health/aeo_readiness.py` vs `domain/site_health/service/aeo_readiness.py`; `query_search_analytics` on each connector plus `workers/integration/paging.py` `Protocol`. `app/schemas` is empty; HTTP DTOs live in `domain/*/schemas.py` and `domain/site_health/api_schemas.py` by design.

**httpx timeouts:** sampled connectors (`fetcher.py`, GSC/GA4/Bing/Shopify, billing, agent, mistral) pass timeouts. No finding.

**`asyncio.gather`:** audit worker documents bounded concurrency (`audit_worker.py:201`); commerce gather is limited by `discovery_worker_batch_size` (`commerce_discovery_worker.py:494`). Not unbounded fan-out.

**CodeQL (GitHub, not Sonar):** open set empty. Dismissed items (robots cache key membership, secret **names** in logs, test URL `in` set) should not be re-opened as debt.

**Marketplace scorecard (60.0) — false or out of scope for this backend report:**

- “No lint config / CI does not run tests, lint, or typecheck” — `.github/workflows/ci.yml` runs ruff, mypy, pytest, complexity, vulture; `backend/pyproject.toml` has `[tool.ruff]` and `[tool.mypy]`. Detector `repo_stats` flags are wrong.
- “No `/health` / no structured logging / no error tracking” — `GET /health` exists (`main.py:171`); `core/telemetry.py` configures structlog JSON and optional Logfire (`instrument_fastapi`). The remaining gap is BD-21 (probe depth), not missing telemetry libraries.
- “Add docker-compose.yml / `.env.example` is missing” — `infra/docker/docker-compose.yml` and `infra/docker/.env.example` are committed; compose-smoke already curls `/health`. `has_docker_compose` / `env_example_file` null is a path-detection miss (`infra/docker/`, not repo root).
- “No runnable suite / commit lockfiles” — `backend/uv.lock` is committed; CI `uv sync --frozen`.
- Frontend stubbed-vs-integration e2e split, git 22-day span, second author, semver tags — not `backend/` debt. Oversized **backend** tests are already BD-04.

## 5. Raw data

### Substitute “Sonar-like” counts (not a SonarQube export)

**ruff `--select ALL` (backend, includes tests; 27411 total):** top rules — `S101` 9772, `COM812` 5745, `D103` 2196, `PLR2004` 1691, `ANN001` 908, `TRY003` 767, `CPY001` 739, `EM101` 541, `TC002` 382, `PLR0913` 315, `SLF001` 152, `ANN401` 144, `BLE001` 55, `S110` 14, `C901` 7. Security-relevant outside tests: `S112` `parser.py:539`; `S311` is the seeded shuffle (rejected).

**radon `cc app -s -n B`:** dozens of B (6–10) and a band of **C (11–12)** exactly at the policy cap (examples: `_mentioned_id_sets` 12, `_hreflang_alternates` 12, `_applicability` 12, `create_crawl` 11, `_fetch_discover` 11, `CurlCffiTransport.fetch` 11). **No D+** in this run.

**radon `mi app -s -n B`:** 7 files at grade B (listed in §0 evidence / BD-02).

**vulture min-confidence 60:** large unused-function list dominated by `@router` endpoints (false). Not counted as dead-code findings.

**mypy `--strict`:** 1013 errors / 197 files / 492 modules checked.

**jscpd:** 647 Python files, 202111 lines, **6 clones**, 153 duplicated lines (0.08%).

**aislop 0.14.1:** 727 files; 16 errors, 246 warnings; score 19/100. Rule histogram: too-many-params 105, file-too-large 92, function-too-long 17, swallowed-exception 15, hardcoded-url 10, broad-except 8, meta-comment 5, thin-wrapper 3, chained-dict-get 2, silent-recovery 2, hardcoded secret 1.

### Top 20 `app/` files by size (proxy for finding density)

| LOC | File |
|----:|------|
| 796 | `app/workers/integration_worker.py` |
| 789 | `app/domain/prompts/service.py` |
| 784 | `app/domain/prompts/generation.py` |
| 784 | `app/analysis/site_health/rules.py` |
| 783 | `app/models/audit.py` |
| 777 | `app/domain/traffic/service.py` |
| 776 | `app/workers/site_health/phases/analyze.py` |
| 774 | `app/domain/site_health/planner.py` |
| 769 | `app/analysis/site_health/parser.py` |
| 768 | `app/domain/billing/service.py` |
| 762 | `app/core/config/site_health_rules.py` |
| 756 | `app/domain/opportunities/recompute.py` |
| 749 | `app/domain/agent/service.py` |
| 742 | `app/workers/site_health_worker.py` |
| 740 | `app/domain/measurement/harness.py` |
| 734 | `app/workers/commerce_discovery_worker.py` |
| 715 | `app/domain/site_health/selection.py` |
| 715 | `app/domain/analytics/enqueue.py` |
| 710 | `app/domain/commerce/intelligence.py` |
| 710 | `app/analysis/scoring.py` |

### Artifacts

- aislop 0.14.1 (`npx aislop@latest scan backend`; raw output not committed)
- Sonar export: **none** (server up, API unauthorized)
- Marketplace scorecard: abhij1306/Citeladder **60.0** (2026-08-20); used only as a heuristic, see §0 / §4
