# Agents.md — CiteLadder

> Mandatory session bootstrap for coding agents. Read this file first, then
> follow the documentation map below. Archived plans are historical context
> only and are never implementation authority.

## What CiteLadder is

CiteLadder is an evidence-grounded growth intelligence platform organized
around one measurable loop: Connect → Analyze → Act → Improve / Verify →
Track. Four durable capabilities sit behind those stations:

1. **Site Health** securely crawls the owned website, classifies each page by
structural type, applies the correct deterministic checklist, and produces
persisted scores, issues, graph/change snapshots, and opportunities.
2. **Content Intelligence** turns site and demand evidence into strategies,
   briefs, drafts, reviews, and post-publication verification.
3. **Demand Intelligence** connects GSC, GA4, journeys, prompts, and AI
   Visibility to show what audiences need and what should improve next.
4. **Growth Agent** orchestrates typed tools from those systems. It owns no
   second knowledge store and cannot publish or mutate external systems without
   an explicit user action.

The measured outcome is increased observed mention/citation share across a
versioned prompt portfolio under comparable audit conditions. AI Visibility is
the Track capability; crawl health, demand coverage, and AEO readiness are
leading indicators, never causal proof.

## Canonical documentation

Read only the documents required by the task.

| Task | Required source |
|---|---|
| Product loop, hierarchy, and architecture | `docs/architecture.md` |
| AEO rebuild delivery sequence | `docs/plans/citeladder-aeo-product-rebuild.md` |
| Complete active-document map | `docs/documentation-index.md` |
| Program sequence | `docs/plans/citeladder-aeo-product-rebuild.md` |
| Site crawl, classification, rules, and runtime | `docs/site-health.md` |
| Content workflows | `docs/plans/CITELADDER_CONTENT_GENERATION_SIMPLIFIED_PLAN.md` |
| Demand, prompts, visibility, and Agent | `docs/plans/citeladder-aeo-product-rebuild.md` |
| Backend ownership and shipped runtime | `docs/backend-architecture.md` |
| Frontend ownership and shipped runtime | `docs/frontend-architecture.md` |
| Hard invariants | `docs/invariants.md` |
| API errors | `docs/api-error-contract.md` |
| UI tokens and interaction rules | `docs/design.md` |
| Historical context | `docs/archive/` — only when explicitly reconciling old behavior |

Code plus current-runtime tests describe what is shipped. Active plans describe
approved future work. Archived plans have no authority.

## Site Health architecture

The shipped Site Health product has three pages: **Site Health**, **Issues**,
and **Opportunities**. Do not recreate the removed Site Intelligence workspace,
industry-pack catalog, knowledge tables, corrections, or comparison system.
The single persisted observed-architecture projection is part of Site Health,
not a second workspace: it is the **Architecture** tab of the existing Website
tablist. The read surface exposes observed families and hierarchy only. It has
no archetype correction endpoint, mutable archetype field, or advisory response
block.

Page analysis separates acquisition truth from structural classification:

```text
safe acquisition -> immutable artifact -> normalized facts
  -> deterministic page_kind + evidence
  -> page-kind-scoped rules and schema contract
  -> persisted evaluations, scores, issues, snapshot, opportunities
```

`page_kind` is the stable, cross-industry structural purpose. Structured data
is one classifier signal and one gap surface; it must never self-certify the
type whose schema is being validated. Path, headings, visible content, forms,
links, and delivery signals must still work when schema is absent.

Unclassified pages use `other`. That is an abstention, not a `WebPage` verdict:
page-kind-specific rules fail closed and remain out of scoring. A JS shell is
also distinct from missing content; content-reading rules stay not-applicable
while `aeo.server_rendered_content` owns the observable problem.

Every classifier, extractor, analyzer, rule, and scoring change carries a
version bump so append-only analyses are replayable.

## Repository invariants

- All IDs are UUIDs. Every project-owned query is workspace-authorized; never
  scope product data by `user_id` or trust an object ID alone.
- API routes use `/api/v1`. Browser calls remain same-origin through the
  frontend proxy.
- Configuration, catalogs, thresholds, limits, templates, page profiles, and
  schedules live in `backend/app/core/config/*` or frontend config owners—not
  service code.
- Raw evidence and provider attempts are immutable/append-only. Derived rows
  carry exact source IDs and relevant extractor, analyzer, classifier, rule,
  formula, template, or model versions.
- Read APIs render persisted projections. They never crawl, sync, call a
  model, or repair state.
- PostgreSQL remains durable state and the task queue. Claim with
  `FOR UPDATE SKIP LOCKED`, commit before network I/O, and use leases and
  idempotency. Do not add Redis without measured need.
- Extend existing subsystem owners before adding a table, queue, fetcher,
  parser, recommendation store, content store, or memory system.
- A model may explain, classify bounded ambiguity, plan, or generate. It never
  becomes raw truth or changes a deterministic metric.
- Unknown, unavailable, zero, historical, conflicting, not-applicable, and
  excluded are distinct states.
- Tests never read `.env`. The backend suite disables it and declares its own
  configuration (`backend/app/core/config/dotenv.py`,
  `backend/tests/conftest.py`); a real provider key must never reach a test
  run. Point the suite at a database with `TEST_DATABASE_URL`.
- No autonomous publishing, prompt activation, external mutation, or
  unbounded agent loop.

## Default implementation workflow

1. Identify the active owner and search before adding.
2. Inspect current code, tests, models, configuration, and API contracts.
3. Implement one gated slice completely.
4. Add deterministic fixtures plus workspace-isolation/provenance tests where
   persistence is touched.
5. Update active documentation when shipped authority changes.
6. Move superseded material to `docs/archive/`; never leave contradictory
   guidance beside active plans.
7. Run the change-validation harness below and report exactly what was and was
   not verified.

## Package and migration rules

- Frontend uses **pnpm only**, pinned by `frontend/package.json`. Never use npm
  or yarn and never create `package-lock.json`.
- CiteLadder is pre-launch and keeps one explicit
  `migrations/versions/0001_initial.py`. Fold schema changes into it, reset a
  disposable database, migrate from scratch, and check ORM drift. Do not add a
  `0002+` migration unless this policy changes explicitly.

## Change validation

Apply this to every implementation or code change. Repository scripts decide
test scope; agents never hand-pick a test set at completion.

Do not run repository gates after each implementation step. Finish the planned
implementation first. Before declaring implementation complete or pushing, run
these once, in this order, from the repository root:

```powershell
.\scripts\check.ps1
.\scripts\test.ps1
```

`scripts/quality.mjs` is the cross-platform static-gate owner;
`check.ps1` is its release-compatible PowerShell shim. The fix mode applies
Ruff and Oxfmt fixes; check mode never writes. Both run mypy, backend
complexity/dead-code/dependency policies, Oxlint, `tsc --noEmit`, frontend
complexity/duplication/design/architecture/dead-code policies, the strict
API-contract guard, and the documentation-index check. `test.ps1` separately selects and runs the affected
backend, frontend, and mapped E2E tests from the working diff against
`origin/main`. Fix every failure. Review and include any formatter changes.

Narrow scopes exist for iteration only: `.\scripts\check.ps1 -Scope Backend`,
`-Scope Frontend`, `-Scope Docs`. The full run is what completion means.

If `test.ps1` fails, note every file edited while fixing that failure. Rerun the
selector with only that retry delta:

```powershell
.\scripts\test.ps1 -ChangedFiles backend/app/example.py,backend/tests/unit/test_example.py
```

Use `-ChangedFiles` only after an earlier `test.ps1` run in the same task, and
include every file edited since that run. The first run always uses the full
working diff. Agents choose changed files, never test files or test scope.
Missing production mappings must be added to `scripts/validation.json`. Never
replace a missing mapping with a broad or full-suite fallback.

When debugging one known failure, running that exact test directly is allowed.
Return to the repository script before considering the change complete.

`.\scripts\check.ps1 -CheckOnly` never mutates files; use it for a pre-push or
verification-only pass. GitHub CI remains authoritative and runs full static,
unit, component, frontend, build, and security validation. Do not run the full
backend suite locally.

A coding task is complete only when `.\scripts\check.ps1` and `.\scripts\test.ps1`
pass.

### Do not game gates

Never make validation pass by raising the CC/LOC ceilings in
`backend/scripts/complexity_policy.json` or
`frontend/scripts/frontend_complexity_policy.json`; removing a root from either
policy; adding complexity or duplication exceptions; weakening lint, type, or
format configuration; narrowing `[tool.mypy] files`; adding a
`[tool.coverage.report] fail_under` or any other coverage threshold (coverage is
measured, never gated -- a ratio is a target that invites tests written to move
it); dropping a rule family from `[tool.ruff.lint]
select`; adding a `per-file-ignores` entry that covers application code;
softening an `.importlinter` contract or adding an `ignore_imports` line;
editing `scripts/validation.json` to avoid relevant tests; deleting, skipping,
xfail-ing, disabling, trivializing, or over-mocking tests; mechanically
splitting or hiding complexity; swallowing failures; using `--no-verify`; or
substituting a smaller hand-picked test set at completion.

A `# noqa` must name a rule this repository actually enables, must currently
apply, and must carry its reason inline. `RUF100` fails the build on a
directive that suppresses nothing, so a decorative suppression is a build
error, not a style preference. `backend/tests/unit/test_static_analysis_tools.py`
asserts the gate configuration itself, so weakening one of the above breaks a
test rather than passing quietly.

If a gate exposes a design problem, refactor the implementation. If a repository
rule is obsolete, report it separately and change it only when the user asks or
the task requires that policy change.

### Test scope

- Focused change: affected tests.
- User-facing feature flow: affected tests plus mapped feature E2E.
- Core, shared, or config change: the broader mapped set the rules select.
- Pull request and main: GitHub CI full suite.

Frontend tooling is **pnpm only**. Never use npm or yarn wrappers.

## Focused verification

For debugging a single known failure, or for gates the scripts do not own:

```bash
# Backend, from backend/
uv run pytest tests/unit/test_<area>.py tests/component/test_<area>.py -q
uv run alembic upgrade head
uv run alembic check

# Frontend, from frontend/
pnpm exec vitest run <file>
pnpm build
```

Preserve unrelated user-owned work. Do not use failures from another dirty
workstream as justification to rewrite or delete it.
