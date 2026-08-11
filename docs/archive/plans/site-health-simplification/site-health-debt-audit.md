# Site Health — debt audit and simplification plan

**Date:** 2026-08-11
**Scope:** `backend/app/{api,domain,workers,analysis,models,core/config}/site_health*`, `frontend/{components,lib}/site-health`, `frontend/components/site-intelligence`

---

## 1. Where it stands

| Surface | Files | LOC |
|---|---:|---:|
| Backend `site_health` app code | 44 | **28,354** |
| Backend `site_health` / `site_intelligence` tests | 30+ | **15,332** |
| Frontend `site-health` (components + lib) | 39 | **11,636** |
| Frontend `site-intelligence` | 7 | 1,702 |
| **Total** | | **~57,000** |

Concentration points:

- `core/config/site_health.py` — **2,461 lines** of *configuration*
- `api/site_health.py` — **1,393 lines**, **33 route handlers** in one module
- `models/site_health.py` — **1,329 lines**, **17 tables**
- `lib/site-health/status.ts` — **641 lines** of client-side phase logic, with an **825-line** test file

43 commits touched `domain/site_health` in the last 8 weeks. The feature has been
rewritten in place roughly five times (v1 → v2 page kinds → resumable phase
controls → Site Intelligence S0–S5 → the backend complexity refactor) without any
pass removing the previous shape.

---

## 2. Root cause: state is modelled six times over

One crawl's progress is represented by **six independent state sources**:

| Source | Values |
|---|---:|
| `crawl.status` | 9 (`draft`, `validating`, `queued`, `running`, `paused`, `completed`, `partially_completed`, `failed`, `cancelled`) |
| `crawl.discovery_status` | 7 |
| `crawl.analysis_status` | 7 |
| `phase_runs.{discovery,analysis}.status` | 4 |
| `entitlement.access_mode` | 3 (+ unsettled) |
| `hasMonitoredSelection` | 3-valued (true/false/unsettled) |

That is a nominal state space in the tens of thousands, collapsed on the client
by `resolveSiteHealthPhase()` — a **14-clause ordered precedence chain** — into 7
phases, then re-derived into `InventoryMode` (4) and `PrimaryAction` (4).

The comments in that function are a changelog of production bugs, not a design:

> *"…is what bounced the screen back to the URL list right after Start analysis"*
> *"…the bug the `crawlStarting` flag and a `createMutation.reset()` effect used to mask"*
> *"…that is the production shape that hid every failed crawl behind an empty dashboard"*

Every new bug adds a clause. Nothing has ever been removed. **This is the single
highest-leverage thing to fix** — most of the visible flakiness downstream is a
symptom of it.

---

## 3. Bugs found and fixed in this pass

| # | Defect | Cause | Fix |
|---|---|---|---|
| 1 | Expanded "Scores by Page Kind" row rendered as a **dark slate panel** with unreadable buttons (screenshot 2) | `bg-subtle` resolves to `--color-subtle: #667085` — the Gray-500 **text** ink. There is no `--color-bg-subtle` token, so Tailwind happily painted a background with a text colour. | `page-kind-scores.tsx` → `bg-background-alt` |
| 2 | One tracking-parameter URL pushed **every other column off screen** (screenshot 1) | A URL is a single unbreakable token, so an untruncated cell takes its full max-content width. `max-width` on a `<td>` is advisory under `table-layout: auto`, so the clamp has to sit on an inner box. | Truncation + `title` tooltips in `pages-table.tsx`, `inventory-table.tsx`, `inventory-section.tsx`, `issues-catalog.tsx`; `break-all` in `url-detail.tsx` |
| 3 | Page header **action buttons pushed outside the viewport** | The app shell's content column is a `grid` with an implicit (max-content-sized) track. Any descendant that cannot shrink widens the entire column. | `grid-cols-[minmax(0,1fr)]` on the shell content column + `min-w-0` on the four nested site-health grid wrappers |
| 4 | The **analysis section disappeared** | `PhaseControls` returns `null` unless `entitlement.advanced_controls_enabled`, which is `SITE_HEALTH_ADVANCED_CONTROLS_ENABLED` — defaulted to `false` and set to `false` in `infra/docker/.env`. With it off there is **no** "Analyze URLs" control anywhere in the product. | Flipped to `true` in `infra/docker/.env`. **The real fix is P0-4 below** — this must not be a hidden boolean. |

Verified: 250 frontend tests pass, `tsc --noEmit` clean.

Related, not fixed (out of the reported scope): `bg-subtle` is also used in
`components/marketing/landing/agent-console.tsx:531` and
`lib/analytics/series.ts:137`. Both sit on dark surfaces so the grey is plausible
there, but both are relying on a text token by accident.

---

## 3b. Landed in this pass

- **P0-1 — the phase is server-owned.** `resolve_phase()` in
  `backend/app/domain/site_health/phase.py` resolves it once from all inputs in
  one transaction and ships it on the dashboard projection. Deleted from the
  client: `resolveSiteHealthPhase` (14 clauses), `primaryActionForPhase`,
  `hasScoreData`, and the 367-line test block that pinned them. `status.ts`
  641 → 418; `status.test.ts` 825 → 397.
- **P0-4 — the trapdoor is gone.** `advanced_controls_enabled` defaults to
  `True`; `PhaseControls` is gated only on "a crawl exists".
- **P1-2 — scores render above the inventory**, not three screens below it.
- **P1-3 (partial)** — the page-kind accordion (the grey box: a third page-
  selection UI nested in a table cell) and the duplicate "Start analysis" in
  the selection panel are both deleted. One selection surface remains.
- **P3-1/P3-2 — the token bug cannot recur.** An ESLint `no-restricted-syntax`
  rule bans background utilities built from text-role tokens. It found **8 more
  instances** outside site health, all migrated to real surface/border tokens.
- **P4 (partial)** — retired the tests *with* the code they pinned.

Net: **−734 lines** across the site-health directories, with behaviour intact.

## 3c. Decided target architecture (2026-08-11)

**Three pages. Nothing else.**

1. **Site Health** — discover → analyze → scores, with issues classified **by
   page type**.
2. **Issues** — the catalog.
3. **Opportunities**.

Everything else is noise and comes out.

### Page-type issue classification — what exists vs. what's missing

Already built and working:
- `PAGE_KIND_EXPECTED_SCHEMA` — per-kind expected schema types and required /
  recommended properties (homepage → `Organization`/`WebSite`, product →
  `Product` + `offers`, article → `Article` + headline/author/datePublished,
  category → `ItemList`, pricing → `offers.price`, docs → `TechArticle`).
- Per-kind thin-content minimums (`min_sufficient_words`) and per-`(rule_id,
  page_kind)` weight overrides.
- A `page_kind:<type>` applicability gate in the rule evaluator
  (`PAGE_KIND_APPLICABILITY_PREFIX`, `rules.py:794`).

**The gap:** of the 18 catalog rules, **0 use the `page_kind:` gate** — all are
`always` (8) or `has_html` (10). The mechanism is built and unused, which is
exactly why irrelevant checks fire on every page kind. The work is classifying
the catalog, not building machinery.

### Site Intelligence — DELETE (~14.1k lines)

Knowledge, Schema, Journeys, Evidence panels; industry packs; corrections;
comparisons. Known couplings that must be unwound with it:
- `app/domain/agent/context.py` reads `site.intelligence`, `industry_pack`, and
  `Correction` into Growth Agent context.
- `planner.py` freezes an industry-pack manifest into every crawl config.
- `workers/site_health/phases/analyze.py` classifies an `industry_role` per page
  (surfaced as the second badge in the pages table).
- DB: the SI tables come out; the schema is collapsed and re-migrated from
  scratch (data is disposable — confirmed).

## 3d. Site Intelligence — DELETED (2026-08-11)

**−83,927 lines / +1,138 across 178 files.** (The bulk is
`app/core/config/industry_packs/`, a checked-in JSON pack catalog.)

| Surface | Before | After |
|---|---:|---:|
| Backend `site_health` app code | 28,354 | **21,972** |
| Backend `site_health` tests | 15,332 | **13,745** |
| Frontend `site-health` | 11,636 | **10,538** |
| Frontend `site-intelligence` | 1,702 | **0** |

Deleted: the 5 workspace panels, knowledge extraction/entities/assertions/
relations, corrections, snapshot comparisons, industry packs and the per-page
industry-role classifier, and every table behind them.

Couplings unwound, each of which is a **behaviour change outside Site Health**:

- **Growth Agent** — lost `site.intelligence`, `comparison`, the
  `industry_pack` manifest block, and the `corrections` context section.
  `contradictory_count` / `correction_count` are now constant 0. The
  `propose_correction` task policy, its `knowledge.propose_correction` tool,
  and the `POST /tasks/{id}/correction` endpoint are removed — they produced
  Corrections, which no longer exist.
- **Content Intelligence** — `_brief_evidence` returns EMPTY `allowed_facts` /
  `prohibited_claims` / `source_refs`. Those were grounded facts from knowledge
  assertions; content generation now has no fact grounding and needs a new
  evidence source. Strategy recompute no longer requires a pack
  (`content_pack_uncalibrated` is gone) and its question program is empty; the
  page inventory it persists still works and is grouped by **page kind**
  instead of industry role. Error code `site_intelligence_unavailable` →
  `site_snapshot_unavailable`.
- **Site Health snapshot** — `intelligence`, `intelligence_version`,
  `comparison`, `prior_snapshot_id` columns dropped. `snapshot_id` is now
  exposed on the Site Health dashboard projection, because Content verification
  legitimately needs that handle and read it off the SI overview before.
- **`site_page_analyses`** — the whole industry-role column group dropped; the
  append-only key is now `(artifact_id, analyzer_version)` rather than
  including the pack version.

Schema: `0001_initial` was edited in place (it is the sole greenfield baseline
and declares itself rebuildable). Verified by applying it to an empty database
and running `alembic check` → **"No new upgrade operations detected."**

## 3e. Page-type issue classification — DONE (2026-08-11)

**Correction to §3c:** the earlier claim that "0 of 18 rules use the page_kind
gate" was wrong — it came from grepping literal `applicability_key="…"` strings
and missed the f-string forms. Three rules were already scoped
(`aeo.organization_identity` → homepage, and the two product rules). The
catalog is 33 rules, not 18.

### What changed

1. **The gate accepts a SET of page kinds.** `page_kind:a|b|c` instead of one
   type per rule, built by `_page_kinds(...)` so a rule declares every type it
   is meant for.
2. **A second gate that composes with the JS-shell guard.**
   `page_kind_content:a|b|c` = those kinds AND server-rendered content. This
   was a real regression caught by the existing shell test: moving a
   content-reading rule off `observed_content` onto a bare page-kind token
   silently dropped the shell guard and reinstated the
   six-findings-for-one-problem cascade.
3. **Four editorial rules scoped** off "every page with content":

   | Rule | Now applies to |
   |---|---|
   | `aeo.author_present` | article, guide, case_study_review, comparison |
   | `aeo.date_present` | + docs |
   | `aeo.outbound_citations` | article, guide, case_study_review, comparison |
   | `aeo.question_headings` | faq, guide, docs, article |

   A product, category, pricing or policy page is no longer reported for a
   missing author byline; a homepage is no longer reported for missing
   question-form headings. Those resolve NOT_APPLICABLE, which keeps them out
   of the issue list AND out of scoring — a different statement from passing.
4. **Unclassified pages fail closed.** No page kind means no page-kind-scoped
   rule applies; we do not guess which checklist an unclassified page owes.
5. **The Issues screen shows which page types each issue reaches.** The
   per-group page kinds already existed but only fed the CSV export; they now
   ride the grouped-issue list DTO (one aggregate for the page of groups, not a
   query per row) and render as badges. A Product/offers finding scoped to
   product pages is different work from a title finding that touches
   everything, and the affected-page count alone cannot tell them apart.

Applicability distribution now: 10 `has_html`, 8 `always`, 5 `observed_content`,
**5 page-kind scoped**, 3 `crawl_finalize`, 2 `site_root`.

## 4. Todo list — debt elimination, in priority order

### P0 — collapse the state model (unblocks everything else)

- [ ] **P0-1. Make the server own the phase.** Add one `phase` field to the
      crawl projection, computed once in `domain/site_health/service/presentation.py`.
      Delete `resolveSiteHealthPhase` (14 clauses), `primaryActionForPhase`,
      `inventoryModeForPhase` and the 825-line `status.test.ts` that pins their
      interactions. The client renders what it is told.
- [ ] **P0-2. Retire `discovery_status` / `analysis_status` as *screen* inputs.**
      Keep them as worker bookkeeping if the workers need them, but stop
      exporting all 7×7 to the client. The UI needs "what is happening now" and
      "can I act", not a cross-product.
- [ ] **P0-3. Delete `phase_runs` from the client contract** or make it the
      *only* progress source — right now `PhaseControls` reads both
      `crawl.discovery_status` **and** `phase_runs.discovery.status` and ORs them,
      which is two sources of truth by construction.
- [ ] **P0-4. Kill `advanced_controls_enabled`.** A boolean env var that removes
      the product's primary workflow is not a feature flag, it is a trapdoor —
      it is what made the analysis section vanish. Either the phase controls are
      the product (ship them unconditionally) or they are an entitlement tier
      (drive them from `access_mode`, which already exists). Not a third axis.

### P1 — collapse the two competing screens

- [ ] **P1-1. Resolve Site Health vs. Site Intelligence.** Today
      `SiteIntelligenceWorkspace` wraps the *entire* legacy Site Health dashboard
      as its "Pages" tab, so the old screen is nested inside the new one and both
      layouts are live. Pick one information architecture and delete the other.
- [ ] **P1-2. Move the score cards, page-kind breakdown and site-facts panel out
      of the Pages tab.** They are crawl-level summaries rendered *below* a
      page-level table, which is why the scores read as "missing" — they are
      three screens down. They belong in Overview.
- [ ] **P1-3. Drop the accordion-with-checkboxes-and-a-pager inside a table row**
      (`PageKindScores` → `PageKindDetails`). It is a third page-selection UI
      alongside `InventorySelection` and `PagesTable`, and it is the widget that
      rendered as the grey box. Re-analyze belongs with the other bulk actions.

### P2 — backend surface reduction

- [ ] **P2-1. Split `api/site_health.py`** (1,393 lines, 33 handlers) into
      `crawls`, `pages`, `issues`, `exports`, `events`. Mechanical, low risk.
- [ ] **P2-2. Split `core/config/site_health.py`** (2,461 lines). A config module
      that large is holding policy, not configuration — separate the neutral
      *policy* (limits, caps, tiers) from *constants* (status tokens, event names,
      error codes) from *settings* (env-bound `BaseSettings`).
- [ ] **P2-3. Audit the 17 tables.** `site_fetch_attempts`, `site_fetch_artifacts`,
      `site_url_observations`, `site_link_references`, `site_rule_evaluations`
      and `site_crawl_events` are all per-URL-per-crawl fan-out. Confirm each is
      read by a shipped feature; drop or roll up the ones that are not.
- [ ] **P2-4. `domain/site_health/selection.py` (1,134 lines) and
      `phase_control.py` (859 lines)** overlap on "what may run next". Merge into
      one guard module with one entry point.

### P3 — design-system hardening (prevents recurrence of §3)

- [ ] **P3-1. Add a `--color-bg-subtle` token** (or rename `--color-subtle` →
      `--color-text-subtle`) so `bg-subtle` cannot silently mean "paint with an
      ink colour". This class of bug is invisible in review.
- [ ] **P3-2. Add a lint rule** banning background utilities built from text-role
      tokens.
- [ ] **P3-3. Give the table primitive a `truncate` column affordance** so every
      caller does not re-derive the `min-w-0` + inner-box clamp by hand. Four
      call sites had the same defect.
- [ ] **P3-4. Add a wide-content regression test** (a page row with a 500-char
      URL) asserting the content column does not exceed the viewport.

### P4 — test-suite right-sizing (do last)

- [ ] **P4-1.** 15,332 lines of backend tests for 28,354 lines of code, much of
      it pinning the state-machine interactions that P0 deletes. Retire those
      tests *with* the code they pin — not before, not separately.

---

## 5. Suggested sequencing

P0-1 through P0-4 are one change and should land together — splitting them leaves
two phase models live at once, which is the failure mode that produced the current
state. P1 depends on P0. P2 and P3 are independent and can go in parallel at any
time. P4 falls out of P0/P1 naturally.

Realistically P0+P1 removes on the order of 3–5k lines of frontend logic and its
tests, and makes the screen's behaviour explainable in a paragraph rather than a
14-clause comment.
