# Invariant 1 Configuration Audit & Refactoring Implementation Plan

## Overview
This plan addresses the **Invariant 1 ("Config Zero-Tolerance: Configuration MUST NOT live in code")** audit findings. 

Operational parameters—scoring rules, feature catalogs, parsing bounds, polling intervals, page sizes, prompt limits, max repetitions, and environment variables—must live exclusively in centralized configuration modules (`backend/app/core/config/*` in the backend and `frontend/lib/config/*` in the frontend). Business logic, workers, API clients, analysis algorithms, and UI components must read from these modules and never hardcode literals or inline constants.

---

## Audit Findings & Invariant 1 Violations

### 1. Backend Codebase Audit Findings
While `backend/app/core/config/` holds 27 settings modules, several operational configs remain embedded in domain, analysis, and worker modules:
* **Analysis & Scoring (`backend/app/analysis/scoring.py`)**:
  * `FANOUT_FEATURE_RULES` dictionary (keyword matching rules for query fanout classification) is hardcoded inline in `scoring.py` instead of residing in `app/core/config/analysis.py`.
  * Model alias checking (`gemini-2.5-flash`, `gemini-flash-latest`) is hardcoded directly inside cost calculation loops rather than utilizing `app/core/config/provider_catalog.py` or `analysis.py`.
* **Site Health Parser & Limits (`backend/app/analysis/site_health/`)**:
  * Parser length/count limits (`_MAX_TITLE_CHARS`, `_MAX_META_CHARS`, `_MAX_HEADING_CHARS`, `_MAX_HEADINGS_KEPT`, `_MAX_URL_CHARS`, `_MAX_ANCHOR_TEXT_CHARS`, `_MAX_AUTHOR_CHARS`, `_MAX_DATE_CHARS`, `_MAX_OUTBOUND_DOMAINS`, `_MAX_DOMAIN_CHARS`, `_MAX_HREFLANG_ALTERNATES`) are defined inside `parser.py` instead of `app/core/config/site_health.py`.
  * Page type path/detail bounds (`_MAX_PATH_CHARS`, `_MAX_SIGNAL_DETAIL_CHARS`) are defined inside `page_types.py`.
  * Evidence URL cap (`_MAX_EVIDENCE_URLS = 10`) is defined inside `finalize.py`.
* **Worker Task Queue Defaults (`backend/app/workers/audit_worker.py` & `drain.py`)**:
  * Default function argument `max_batches: int = 1000` is hardcoded in `run_until_idle()` signatures rather than referencing task queue configuration settings.

### 2. Frontend Codebase Audit Findings
In the frontend, `frontend/lib/config/` is currently incomplete (only contains `site-health.ts`), leaving operational parameters scattered across various domain modules:
* **Analytics (`frontend/lib/analytics/series.ts`)**: Hardcodes `REFERRALS_PAGE_SIZE = 50` and `CORRELATION_MIN_SAMPLE = 8`.
* **Billing API (`frontend/lib/api/billing.ts`)**: Hardcodes `BILLING_CONFIRM_POLL_MS = 3_000` and `BILLING_CONFIRM_MAX_POLLS = 20`.
* **Content Generation API (`frontend/lib/api/content.ts`)**: Hardcodes `CONTENT_PROMPT_MAX_LEN = 4000`, `CONTENT_LIST_DEFAULT_LIMIT = 50`, `CONTENT_LIST_POLL_MS = 3000`, and `CONTENT_DETAIL_POLL_MS = 2000`.
* **API Base URL (`frontend/lib/api/client.ts`)**: Hardcodes `API_BASE_URL = '/api/v1'`.
* **Integrations Sync (`frontend/lib/integrations/sync-runs.ts`)**: Hardcodes `SYNC_RUN_POLL_MS = 3_000`.
* **Product Attribution (`frontend/lib/products/attribution.ts`)**: Hardcodes `ATTRIBUTION_RECOMPUTE_POLL_MS = 3_000`.
* **Runs & Audit Execution (`frontend/lib/runs/launch.ts` & `runs.ts`)**: Hardcodes `MAX_REPETITIONS = 10` and `ACTIVE_RUN_POLL_MS = 3_000`.
* **Environment Variable Access (`frontend/lib/brand/logo-dev.ts`)**: Direct unvalidated read of `process.env.NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE`.

---

## User Review Required

> [!IMPORTANT]
> The proposed refactoring preserves all existing function signatures and behavior, while re-routing constant definitions through `backend/app/core/config/*` and `frontend/lib/config/*`.

> [!NOTE]
> All existing test imports (e.g., in unit/integration tests) will remain fully compatible as existing modules will re-export constants from the centralized config files where required.

---

## Open Questions

> [!NOTE]
> 1. Should frontend environment variables (like `NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE`, `NEXT_PUBLIC_SITE_URL`) be validated via a Zod schema in `frontend/lib/config/env.ts` during app initialization?
> 2. Are there any additional domain knobs (e.g., custom UI animation durations or toast dismiss timeouts) that you would like centralized under `frontend/lib/config/ui.ts` as part of this pass?

---

## Proposed Changes

### Backend Configuration Centralization

#### [MODIFY] [analysis.py](file:///c:/Projects/Searchify/backend/app/core/config/analysis.py)
* Add `FANOUT_FEATURE_RULES` dictionary defining search query fanout feature keyword rules.
* Add Gemini model pricing alias match helper definitions.

#### [MODIFY] [scoring.py](file:///c:/Projects/Searchify/backend/app/analysis/scoring.py)
* Remove inline `FANOUT_FEATURE_RULES` definition and import it from `app.core.config.analysis`.
* Replace inline Gemini model string array check with imported model alias check.

#### [MODIFY] [site_health.py](file:///c:/Projects/Searchify/backend/app/core/config/site_health.py)
* Export parser length and count limits (`SITE_HEALTH_MAX_TITLE_CHARS`, `SITE_HEALTH_MAX_META_CHARS`, `SITE_HEALTH_MAX_HEADING_CHARS`, `SITE_HEALTH_MAX_HEADINGS_KEPT`, `SITE_HEALTH_MAX_URL_CHARS`, `SITE_HEALTH_MAX_ANCHOR_TEXT_CHARS`, `SITE_HEALTH_MAX_AUTHOR_CHARS`, `SITE_HEALTH_MAX_DATE_CHARS`, `SITE_HEALTH_MAX_OUTBOUND_DOMAINS`, `SITE_HEALTH_MAX_DOMAIN_CHARS`, `SITE_HEALTH_MAX_HREFLANG_ALTERNATES`).
* Export page_types limits (`SITE_HEALTH_MAX_PATH_CHARS`, `SITE_HEALTH_MAX_SIGNAL_DETAIL_CHARS`).
* Export evidence limit (`SITE_HEALTH_MAX_EVIDENCE_URLS`).

#### [MODIFY] [parser.py](file:///c:/Projects/Searchify/backend/app/analysis/site_health/parser.py)
* Import parser limits from `app.core.config.site_health`.

#### [MODIFY] [page_types.py](file:///c:/Projects/Searchify/backend/app/analysis/site_health/page_types.py)
* Import path and detail limits from `app.core.config.site_health`.

#### [MODIFY] [finalize.py](file:///c:/Projects/Searchify/backend/app/analysis/site_health/finalize.py)
* Import evidence url limit from `app.core.config.site_health`.

#### [MODIFY] [audit_worker.py](file:///c:/Projects/Searchify/backend/app/workers/audit_worker.py) & [drain.py](file:///c:/Projects/Searchify/backend/app/workers/drain.py)
* Import default max batch bounds from `app.core.config.task_queue`.

---

### Frontend Configuration Centralization Layer

#### [NEW] [analytics.ts](file:///c:/Projects/Searchify/frontend/lib/config/analytics.ts)
* Define and export `REFERRALS_PAGE_SIZE = 50` and `CORRELATION_MIN_SAMPLE = 8`.

#### [NEW] [billing.ts](file:///c:/Projects/Searchify/frontend/lib/config/billing.ts)
* Define and export `BILLING_CONFIRM_POLL_MS = 3_000` and `BILLING_CONFIRM_MAX_POLLS = 20`.

#### [NEW] [content.ts](file:///c:/Projects/Searchify/frontend/lib/config/content.ts)
* Define and export `CONTENT_PROMPT_MAX_LEN = 4000`, `CONTENT_LIST_DEFAULT_LIMIT = 50`, `CONTENT_LIST_POLL_MS = 3000`, and `CONTENT_DETAIL_POLL_MS = 2000`.

#### [NEW] [integrations.ts](file:///c:/Projects/Searchify/frontend/lib/config/integrations.ts)
* Define and export `SYNC_RUN_POLL_MS = 3_000`.

#### [NEW] [products.ts](file:///c:/Projects/Searchify/frontend/lib/config/products.ts)
* Define and export `ATTRIBUTION_RECOMPUTE_POLL_MS = 3_000`.

#### [NEW] [runs.ts](file:///c:/Projects/Searchify/frontend/lib/config/runs.ts)
* Define and export `MAX_REPETITIONS = 10`, `MIN_REPETITIONS = 1`, and `ACTIVE_RUN_POLL_MS = 3_000`.

#### [NEW] [api.ts](file:///c:/Projects/Searchify/frontend/lib/config/api.ts)
* Define and export `API_BASE_URL = '/api/v1'`.

#### [NEW] [env.ts](file:///c:/Projects/Searchify/frontend/lib/config/env.ts)
* Centralized accessor module for frontend environment variables (`NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE`, `NEXT_PUBLIC_SITE_URL`, etc.).

#### [NEW] [index.ts](file:///c:/Projects/Searchify/frontend/lib/config/index.ts)
* Re-export all modular frontend configs.

#### [MODIFY] [series.ts](file:///c:/Projects/Searchify/frontend/lib/analytics/series.ts)
* Import constants from `@/lib/config/analytics`.

#### [MODIFY] [billing.ts](file:///c:/Projects/Searchify/frontend/lib/api/billing.ts)
* Import constants from `@/lib/config/billing`.

#### [MODIFY] [content.ts](file:///c:/Projects/Searchify/frontend/lib/api/content.ts)
* Import constants from `@/lib/config/content`.

#### [MODIFY] [client.ts](file:///c:/Projects/Searchify/frontend/lib/api/client.ts)
* Import `API_BASE_URL` from `@/lib/config/api`.

#### [MODIFY] [sync-runs.ts](file:///c:/Projects/Searchify/frontend/lib/integrations/sync-runs.ts)
* Import `SYNC_RUN_POLL_MS` from `@/lib/config/integrations`.

#### [MODIFY] [attribution.ts](file:///c:/Projects/Searchify/frontend/lib/products/attribution.ts)
* Import `ATTRIBUTION_RECOMPUTE_POLL_MS` from `@/lib/config/products`.

#### [MODIFY] [launch.ts](file:///c:/Projects/Searchify/frontend/lib/runs/launch.ts) & [runs.ts](file:///c:/Projects/Searchify/frontend/lib/runs/runs.ts)
* Import `MAX_REPETITIONS` and `ACTIVE_RUN_POLL_MS` from `@/lib/config/runs`.

#### [MODIFY] [logo-dev.ts](file:///c:/Projects/Searchify/frontend/lib/brand/logo-dev.ts)
* Access `NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE` via `@/lib/config/env`.

---

## Verification Plan

### Automated Tests
1. **Backend Test Suite**:
   ```bash
   python -m pytest backend/tests/ -q
   ```
   * Verifies that scoring, site health analysis, workers, and config modules operate correctly without breaking changes.

2. **Frontend Test Suite**:
   ```bash
   pnpm --dir frontend test
   ```
   * Verifies all Vitest unit test suites pass with centralized config imports.

3. **Frontend Policy & Architecture Guard**:
   ```bash
   pnpm --dir frontend check:policy
   ```
   * Verifies that frontend architecture policies, token escapes, design tokens, and budgets remain intact.
