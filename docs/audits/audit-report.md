# CiteLadder — Dead Code, Technical Debt & Complexity Cleanup

**Date:** 2026-08-02 · **Branch:** `design/framer-design-system`
**Scope:** `backend/app/**`, `frontend/{app,components,lib}/**`
**Status:** ✅ Complete — all nine action items below were implemented and verified.

> Historical audit snapshot. The file excerpts, line numbers, and "Recommended
> order"/effort sections below are preserved verbatim from the audit date and
> are stale — code has since moved. Read them as the record of what was found,
> not as open work. No items remain outstanding.

---

## Action items

**Resolution (verified against current code):** 1 ✅ `normalize_url` deleted ·
2 ✅ `build_combined_projection` split into `_aggregate_a2_for_currency` /
`_build_delta_rows` / `_has_attribution_evidence` · 3 ✅ `_run_crawl_finalize_pass`
split into the five named passes · 4 ✅ marketing `card.tsx` + `IconButton`
removed · 5 ✅ consolidated into `components/traffic/metric-table.tsx`
(`MetricTable`) · 6 ✅ shared `components/auth/auth-form.tsx` · 7 ✅
`product-window.tsx` uses `FrameView`/`FrameCard` · 8 ✅ roster label hoisted to
module `ENGINE_ROSTER_LABEL` · 9 ✅ `get_dashboard` split into
`fetch_latest_sources` / `build_analyze_sections` / `build_improve_sections` /
`assemble_response`.

### 1. Remove a dead utility function — XS
**File:** `backend/app/analysis/normalization.py:68`
`normalize_url` has zero callers anywhere in backend app, workers, or tests (the file's other helpers like `normalize_alias` and `normalize_domain` are all used). **Delete the function.**

### 2. Simplify a 48-branch attribution builder — M
**File:** `backend/app/domain/attribution/snapshot.py:454` — `build_combined_projection`
This ~230-line function runs nested loops over currency → order → line item, with an early-exit that must emit a field-identical "no data" row, a try/except around revenue math, and a 3-way delta join. It also computes the same `evidence_orders` filter twice (lines 486–490 and 605–610) in two slightly different forms — a latent divergence bug.
**Refactor:** extract `_aggregate_a2_for_currency()` and `_build_delta_rows()` as pure helpers and hoist one shared `_has_attribution_evidence()` predicate. Target ~15–20 branches, ~80 lines.

### 3. Split a 48-branch crawl finalizer — M
**File:** `backend/app/workers/site_health/lifecycle.py:497` — `_run_crawl_finalize_pass`
This ~310-line worker step runs four back-to-back rule evaluation passes (broken internal links → hreflang walk → sitemap-orphan diff → persistence), each with its own per-row skip guards — all domain predicates, not boilerplate. Its docstring already names the seams.
**Refactor:** split into five private methods — `load_latest_analyses`, `evaluate_broken_internal_links`, `evaluate_hreflang_conflicts`, `evaluate_sitemap_orphans`, `persist_evaluations`. The shared lookup dicts can be passed as parameters. Target orchestrator complexity ~8.

### 4. Remove an orphaned marketing component file + one unused export — XS
**Files:**
- `frontend/components/marketing/primitives/card.tsx` — entire file is unreachable; every `Card*` import resolves to the design-system version at `components/ui/card.tsx`, and no file imports this path. **Delete the file.**
- `frontend/components/marketing/primitives/button.tsx:223` — the `IconButton` variant is never used; only the sibling `IconButtonLink` is imported. **Delete the `IconButton` function.**

### 5. Deduplicate the two traffic tables — M
**Files:** `frontend/components/traffic/pages-table.tsx` ↔ `queries-table.tsx` (~146 duplicated lines)
These are the same component with different bindings — identical `SortableColumnHead` (~30 L), `NumericCell`/`NullCell` (~15 L), column config, cursor-pager wiring, and the entire Card+Table+skeleton+empty JSX (~70 L). Only the row type, API call, query key, lead cell, and copy differ.
**Refactor:** extract a generic `<MetricTable rowType fetch rowKey renderLead>` and parameterize the two pages.

### 6. Deduplicate the two auth pages — S
**Files:** `frontend/app/(auth)/login/page.tsx` ↔ `register/page.tsx` (~42 copied lines)
Card shell, centered header, `mutation.isError` alert, Email field, and the Password-with-visibility-toggle block are all verbatim; register only adds a confirm-password field.
**Refactor:** extract a shared `<AuthFormShell fields cta footerLink>` or a single parameterized component.

### 7. Decompose a self-duplicating marketing scene — M
**File:** `frontend/components/marketing/scenes/product-window.tsx` (~100+ lines of internal duplication)
Four `m.div` motion wrappers repeat the same 8-line boilerplate; each step card repeats the same "card-with-header" scaffold, and two step templates repeat identical rows with only copy differing.
**Refactor:** introduce a `<FrameView>` wrapper + `<FrameCard title icon>` shell and drive the bars/tiles with a data array + `.map()`.

### 8. Hoist a per-render constant — XS
**File:** `frontend/components/marketing/landing/rotating-engine-logos.tsx:96`
`const allLabels = [...AVAILABLE_LABELS, ...COMING_SOON_LABELS]` is recalculated every render even though it's only used once for a static aria-label. **Move it above the component.**

### 9. Shorten a long dashboard assembler (readability, optional) — M
**File:** `backend/app/domain/dashboard/service.py:55` — `get_dashboard`
~230 lines of straight-line DTO assembly (12 dashboard sections). It's not branchy — it's just long. **Optional:** split into `fetch_latest_sources()`, `build_analyze_sections()`, `build_improve_sections()`, `assemble_response()` so each section builder can be tested in isolation.

---

## Recommended order

| # | Why first |
|---|---|
| 1, 4, 8 | Tiny, zero-risk deletions / single-line moves |
| 5, 6, 7 | Removes the biggest copy-paste mass; easiest to review as pure extraction |
| 2, 3 | Highest correctness payoff (real branching + a latent duplication bug), needs focused tests before/after |
| 9 | Cosmetic readability — last |

**Estimated total effort:** ~2–3 days of focused cleanup (items 1/4/8 are minutes; 2/3/5/7 are the bulk).

---

## Health context (for reference)

- Backend lint (ruff): clean. Maintainability A-average; the two refactors above are the only branching hotspots.
- Frontend lint (ESLint): clean.
- Copy-paste duplication is ~2.6 % on both sides — already healthy; items 5–7 remove the only concentrated duplication.
- Everything else scanned showed no genuinely dead code — the above is the full actionable set.
