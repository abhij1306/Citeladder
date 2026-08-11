# Site Health rebuild — handoff

Paste this into a new chat to continue. Full detail lives in
`docs/plans/site-health-debt-audit.md`.

---

## Context

Repo `c:\Projects\Citeladder`, branch `main`, last commit `67a7fa3f`.

**Nothing is committed.** ~187 files are modified/deleted in the working tree
(97 deletions, 87 modifications, 3 new). Verify state before changing anything:

```
git status --short
cd backend && python -m pytest tests -q
cd frontend && npx tsc --noEmit && npx eslint components lib app && npx vitest run
```

Last known good: **2,481 backend tests pass**, **1,242 frontend tests pass**,
tsc clean, ESLint clean.

## My decisions (do not relitigate)

1. **Three pages only:** Site Health, Issues, Opportunities. Everything else in
   that area is noise.
2. **Issue classification by page type is the product.** A product page, a
   homepage and an FAQ page must not get the same checklist.
3. **Site Intelligence is deleted entirely** — knowledge, schema, journeys,
   evidence panels, industry packs, corrections, comparisons.
4. **Data is disposable.** Reset the DB, rebuild images, rebuild the migration
   schema freely. `0001_initial` is the sole greenfield baseline and is edited
   in place.
5. **Aggressive debt reduction is wanted.** ~57k lines for a site crawler was
   the complaint. Do not add abstraction layers "for later".
6. **Passing tests are not evidence of health** when the tests pin the debt.
   Retire tests *with* the code they pin, never separately.

## Completed

### UI bugs
- `bg-subtle` rendered a dark slate panel — `--color-subtle` is a Gray-500
  **text** ink and Tailwind v4 generates `bg-*` from every token. Fixed, plus an
  ESLint rule banning background utilities built from text-role tokens (it found
  8 more instances codebase-wide, all migrated).
- Long URLs blew the pages table out of the viewport and pushed header buttons
  off screen. Truncation + `title` tooltips at 4 call sites; the app shell's
  content column is now `grid-cols-[minmax(0,1fr)]` with `min-w-0` on the
  nested site-health grids.
- Export is always available when a crawl exists (was gated on
  `phase === 'dashboard'`). Crawl actions consolidated into the phase-controls
  card.
- Score cards + page-kind breakdown moved **above** the URL inventory.
- Untitled pages show the URL's last path segment (`pageDisplayTitle`) instead
  of repeating the whole URL.

### Debt removed (~11k lines net; 83,927 deletions total incl. pack catalogs)
- **The 14-clause client phase resolver is gone.** `resolve_phase()` in
  `backend/app/domain/site_health/phase.py` resolves the screen phase once,
  server-side, from all inputs in one transaction and ships it on the dashboard
  projection. `status.ts` 641→418, `status.test.ts` 825→397; 19 Python tests
  replace the 367-line TS block.
- **`advanced_controls_enabled` defaults to `True`.** It defaulted off, which
  made `PhaseControls` render nothing — there was no way to continue discovery
  or start an analysis batch anywhere in the UI. `PhaseControls` is now gated
  only on "a crawl exists".
- Deleted the page-kind accordion (a third page-selection UI nested in a table
  cell) and the duplicate "Start analysis" button.
- **Site Intelligence deleted** — see the coupling notes below.
- `0001_initial` rebuilt. Verified by applying to an empty DB and running
  `alembic check` → *"No new upgrade operations detected."*

### Page-type issue classification
- The applicability gate takes a SET: `page_kind:a|b|c`, built by `_page_kinds()`.
- A second token, `page_kind_content:a|b|c`, composes page-kind scope with the
  JS-shell guard. **This was a real regression I introduced and the existing
  shell test caught:** moving a content-reading rule onto a bare page-kind token
  dropped the shell guard and reinstated the six-findings-for-one-problem
  cascade. Keep both tokens.
- Four editorial rules scoped: `aeo.author_present` /
  `aeo.outbound_citations` (article, guide, case_study_review, comparison),
  `aeo.date_present` (+ docs), `aeo.question_headings` (faq, guide, docs,
  article). Non-matching kinds resolve NOT_APPLICABLE — out of the issue list
  AND out of scoring.
- Unclassified pages fail closed.
- The Issues list carries `page_kinds` per grouped issue (one aggregate per
  page of groups) and renders them as badges.

Applicability now: 10 `has_html`, 8 `always`, 5 `observed_content`, 5 page-kind
scoped, 3 `crawl_finalize`, 2 `site_root` — 33 rules.

## Consequences outside Site Health (accepted, not accidents)

- **Content generation lost fact grounding.** `_brief_evidence` returns empty
  `allowed_facts` / `prohibited_claims` / `source_refs`; those came from
  knowledge assertions. **This needs a product decision** — see pending #1.
- **Content strategy's question program is empty** (it was computed from SI
  question coverage). The page inventory it persists still works and is now
  grouped by page kind. Error code `site_intelligence_unavailable` →
  `site_snapshot_unavailable`.
- **Growth Agent** lost `site.intelligence`, `comparison`, the `industry_pack`
  manifest block and the `corrections` context section;
  `contradictory_count` / `correction_count` are constant 0. The
  `propose_correction` task policy, its `knowledge.propose_correction` tool and
  `POST /tasks/{run_id}/correction` are removed.
- `snapshot_id` moved onto the Site Health dashboard projection because Content
  verification legitimately needs that handle.
- `infra/docker/.env` + `.env.example`: `SITE_HEALTH_ADVANCED_CONTROLS_ENABLED=true`.
  **Containers need a restart to pick this up.**

## Pending, in value order

1. **Decide content fact grounding.** Generation currently cites nothing.
   Either build a replacement evidence source from Site Health page analyses, or
   accept prompt-only generation and remove the empty-envelope plumbing.
   *This is the only item that is a product decision, not cleanup.*
2. **Split `backend/app/core/config/site_health.py` (2,529 lines).** Separate
   neutral policy (limits, caps, tiers) from constants (status tokens, event
   names, error codes) from env-bound `BaseSettings`.
3. **Split `backend/app/api/site_health.py` (1,118 lines, 24 handlers)** into
   crawls / pages / issues / exports / events. Mechanical, low risk.
4. **Merge `domain/site_health/selection.py` (1,134) and `phase_control.py`
   (859)** — they overlap on "what may run next". One guard module, one entry
   point.
5. **Audit the 17 tables in `models/site_health.py`.** `site_fetch_attempts`,
   `site_url_observations`, `site_link_references`, `site_rule_evaluations`,
   `site_crawl_events` are per-URL-per-crawl fan-out. Confirm each is read by a
   shipped feature; drop or roll up the rest. DB is disposable, so this is a
   schema edit + `alembic check`.
6. **Scope more rules by page kind.** I did the four clearest cases. The 10
   `has_html` and 5 `observed_content` rules should be reviewed the same way —
   e.g. `aeo.schema_recommended_present` likely differs by page type.
7. **Commit.** Everything above is one large uncommitted change. Split it into
   reviewable commits (UI fixes / server-owned phase / SI deletion / page-type
   rules) before opening a PR. Never open a draft PR — review bots skip them.

## Working agreements

- Report debt removed, not test counts.
- Verify claims before stating them (I twice asserted a rule count from an
  incomplete grep and had to correct it — grep for f-string forms too).
- Flag cross-feature consequences before executing, not after.
