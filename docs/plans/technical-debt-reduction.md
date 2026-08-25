# Technical debt reduction plan

> Active plan. Subordinate to [`../architecture.md`](../architecture.md) and the
> repository invariants in [`../invariants.md`](../invariants.md). Every slice
> here is a structural change with no user-visible behavior change unless the
> slice says otherwise.

## Position

CiteLadder's static gates hold and are now enforced by one harness:
`.\scripts\check.ps1` and `.\scripts\test.ps1` (see
[`../../AGENTS.md`](../../AGENTS.md)). Both complexity policies carry **zero
exceptions**, duplication sits at 0.052% against a 1% budget, and mypy and
Vulture are clean.

The ceilings are set at **CC 15 per function and 900 LOC per module** on both
sides of the stack. That is deliberate headroom, not a target to grow into.
Against it the code has room:

| Signal | Ceiling | Measured | Headroom |
|---|---|---|---|
| Largest backend module | 900 LOC | 797 (`workers/integration_worker.py`) | 103 lines |
| Backend modules over 900 LOC | — | **0** | |
| Highest backend function CC | 15 | 12 | 3 |
| Backend functions over CC 15 | — | **0** | |
| Duplication (production) | 1% | 0.052% | |
| Complexity exceptions (both policies) | 0 | **0** | |

**Module size and cyclomatic complexity are not this plan's problem.** Nothing
is near a limit, and no slice below exists to shave lines or branches. Reshaping
working code to move a number that is already passing is waste.

The real debt is in three places the ceilings never measured: **branch coverage
on the code that executes work**, **frontend surfaces with no tests at all**,
and **gaps where local and CI authority disagree**.

## Non-goals

- Do not raise a ceiling further or add a complexity exception. At 15/900,
  a file that cannot fit has a design problem, not a budget problem.
- Do not split modules or extract helpers to lower a number. There is no number
  to lower.
- Do not add abstraction layers, registries, or indirection for one caller.
- Do not touch duplication. 0.052% is not a target.

## Slices

Ordered so each makes the next cheaper. Each is independently shippable and
gated by `.\scripts\check.ps1` + `.\scripts\test.ps1`.

---

### Slice 1 — Close the harness/CI gaps

Installing the harness surfaced three places where local and CI authority
disagree. Fix these first so later slices are measured against one truth.

| Gap | Action |
|---|---|
| `ruff format` was never gated, and seven files had drifted | **Done** — formatter applied, `Ruff format` step added to `.github/workflows/ci.yml` |
| CI runs no Playwright job at all, so mapped E2E only ever runs on a developer machine | **Done** — an `E2E (playwright)` job runs the whole mapped suite on chromium. The specs stub every `/api/v1/` route, so no backend is provisioned |
| `backend/.python-version` and CI pin 3.12; `Dockerfile` ships `python:3.14.7` | **Done** — `Dockerfile` pinned to `python:3.12.14-slim-bookworm` (digest-pinned). Image, `.python-version`, CI, and the `requires-python` floor are now one version |
| `docs/validate_documentation.py` allowlisted three documents that do not exist | **Done** — the three stale entries removed; the two `backend/pyproject.toml` comments citing `backend-test-corpus-rework.md` now point at this document |

**What gating E2E immediately found.** The suite had rotted in exactly the way
an ungated gate does: four specs failed on the first run, none of them flaky.
All four are fixed and the suite is **34/34 green**.

| Spec | Cause | Fix |
|---|---|---|
| `smoke.spec.ts`, `marketing-pages.spec.ts` | asserted a white canvas; `docs/design.md` §Colour makes the canvas the pearl-paper `background` token, and white is `panel` | Specs corrected against the design authority |
| `design-repair.spec.ts` (Growth Agent) | queried a button named `Agent`; the trigger carries `aria-label="Open Growth Agent"`, which overrides the visible text | Spec queries the real accessible name, matching the colocated `agent-sheet.test.tsx` |
| `design-repair.spec.ts` (onboarding) | three separate defects, described below | Layout bug fixed; two stale assertions corrected |

**The onboarding failure was a real CSS bug, not a design question.** The first
diagnosis — "needs a design decision about rail/stage alignment" — was wrong.
Measuring the computed style showed that `STEP_MAIN_ALIGNMENT`'s
`min-[900px]:pt-[3.25rem]` **never applied at any width**: Tailwind orders
arbitrary `min-[…]` variants ahead of the named breakpoints, so the `py-*`
shorthand on the same element always won. The declared intent had been dead CSS
since it was written. Three changes make it real:

1. The two columns now share one vertical padding ramp. They had diverged at
   `lg` (32px vs 24px), which is why the measured offset differed per viewport
   (-38px at 1280/1440, -30px at 1024, -42px at 960) and why no single constant
   could satisfy the assertion.
2. The stage's top padding is scoped below the 900px split
   (`max-[899px]:pt-3`), so above it the only `padding-top` in play is the step
   alignment.
3. The alignment value is derived rather than tuned: the rail title sits a
   constant 62px below the shared padding edge (wordmark line box + `gap-8`),
   minus the stage wrapper's 8px, giving `3.375rem`.

The headings now align **exactly (0.0px) at 960, 1024, 1280, and 1440**, so the
assertion tolerance was tightened from ±12px to ±2px rather than loosened.

Fixing it unmasked two further assertions in the same test that had never run,
because the alignment check failed before reaching them:

- it asserted all three stage boxes were the same WIDTH, contradicting the
  layout's explicit `flow.step === 2 ? 'max-w-6xl' : 'max-w-xl'`. Review is
  deliberately wider — it shows the full ICP confirmation, not a two-field
  form. The assertion now pins equal HEIGHT (the real no-jump guarantee) and
  records that review is wider on purpose.
- it required a `Confirm your ICP` heading that has not existed since
  onboarding was rebuilt around business context. The review stage's heading is
  `Does this look right?`, already asserted two lines above.

**Verify:** `.\scripts\check.ps1` passes for Backend, Frontend, and Docs.
`pnpm test:e2e`: **34 of 34 pass**.

---

### Slice 2 — Branch coverage on the workers that execute

This is the largest real gap. It was also worse than recorded: the suite was
**failing its own coverage floor** — `fail_under = 84` against a measured
**83.79%** — so the CI `Pytest` step was already red on `main`.

Whole-suite statement+branch coverage of `app`: **83.79% → 85.14%**, from 231
new backend tests (2329 → 2560 passing).

| Module | Was | Now | Status |
|---|---|---|---|
| `workers/agent_worker.py` | **0%** | **100%** | Done — unit tests for the poll loop, component tests for claim-lease-commit against live Postgres |
| `domain/projects/onboarding/context_profile.py` | **0%** | **100%** | Done |
| `domain/audits/schedule_service.py` | 31% | **99%** | Done — every mutation asserts workspace isolation |
| `workers/brand_discovery_worker.py` | 29% | **89%** | Done — backoff and failure accounting as unit tests; finalize's three outcomes and the lease reaper against a real schema |
| `domain/audits/performance.py` | 36% | **86%** | Done |
| `domain/audits/cost_estimate.py` | 25% | **73%** | Done — the pure estimator; the two persistence helpers remain |
| `domain/integrations/service.py` | 43% | **70%** | Done — the management surface, including all three `delete_connection` revocation outcomes |
| `domain/projects/onboarding/research.py` | 41% | 43% | **Partial** — the pure evidence filters are covered (40 tests); the model call and site fetch, which dominate the module, are not |
| `domain/commerce/intelligence.py` | 48% | — | **Not started** |
| `connectors/web_evidence/browser_transport.py` | 48% | — | **Not started** — needs a transport fake, so still scheduled last |

Each new test carries deterministic fixtures plus workspace-isolation and
provenance assertions wherever it touches persistence, per the default workflow.
The research filters are worth singling out: each one exists because of a
specific way a competitor set went wrong (a Wikipedia URL adopted as Myntra's
own domain; an implementation agency scored against the platforms it
implements), and the tests are now the record of both.

**The hazard this slice found is now closed.** A developer `.env` carrying a
real provider key made `default_agent_settings.configured` true, so the first
version of `tests/component/test_agent_worker.py` built a live gateway and
posted evidence to a real provider endpoint from a component test. That is
fixed suite-wide rather than per-file — see *Added since: test isolation from
`.env`* below.

**One pre-existing flake to know about.** On a loaded machine,
`test_worker_executes_claimed_batch_concurrently` can fail: it asserts
`max_in_flight > 1` after 50ms sleeps, so a contended scheduler serialises the
batch and the probe never sees overlap. It is untouched by this work and passes
in isolation and in its own group. Worth making load-independent, not worth
loosening.

**Verify:** `.\scripts\test.ps1`. `[tool.coverage.report] fail_under` **raised
84 → 85**, which is the measured 85.14 rounded down — the plan's rule, taken
after the tests landed rather than ahead of them. 86 is the next step, once
`commerce/intelligence`, `browser_transport`, and `content_worker` (62%) are
covered.

---

### Slice 3 — Frontend surfaces with no tests at all

Eleven frontend directories shipped production code with zero colocated tests.
**All eleven now have tests**, all mapped in `scripts/validation.json`, so
`.\scripts	est.ps1` selects them. **232 new frontend tests across 17 files**; the suite now stands at 161 files / 1372 tests, all passing.

| Directory | Source files | Covered | Tests | Note |
|---|---:|---:|---:|---|
| `components/visibility` | 14 | 6 | 48 | Data states, rankings table, engine comparison, empty/active-run states |
| `components/runs` | 11 | 4 | 67 | Progress panel, executions table, runs table, measurement context |
| `lib/marketing-content` | 10 | 10 | 25 | Structural, not a snapshot: unique slugs, resolvable routes, no empty blocks, no open-source claim |
| `lib/config` | 6 | 6 | 23 | Rules the values must satisfy, not the values themselves |
| `lib/providers` | 3 | 3 | 22 | Includes `isConfigured` vs `isVerified`, mirroring the backend admission filter |
| `components/billing` | 2 | 2 | 15 | `unknown` / `unlimited` / `finite` must not be drawn as each other |
| `components/auth` | 2 | 2 | 8 | The shared brand canvas that auth and onboarding both use |
| `lib/csv` | 1 | 1 | 4 | Including the FileReader fallback the module exists for |
| `lib/forms` | 1 | 1 | 6 | |
| `lib/setup` | 1 | 1 | 6 | |
| `lib/navigation` | 1 | 1 | 2 | |

**Remaining:** 8 files in `components/visibility` (the dashboard, toolbar,
trends, tabs, fanout/mentions evidence, prompt insights, skeleton) and 7 in
`components/runs` (launch dialog and its view, run detail, evidence card and
drawer, schedules). Both directories are covered indirectly by page-level tests
and by the mapped E2E suite, which now runs in CI.

Note for whoever continues: `lib/setup/markets.ts` documents its codes as
satisfying "the existing `setupFormSchema` regexes", but no `setupFormSchema`
exists anywhere in the tree. The new test asserts the documented shape
directly; the stale reference in that comment is still there.

**A suite-load sensitivity this slice exposed.** Growing the suite from 144
files / 1140 tests to 161 / 1372 made an existing fragility visible: on a
loaded machine one arbitrary test would time out at vitest's 5s default on a
full run — a *different* pre-existing file each time, never one of the new
files, and every one passing in isolation. Five pure-logic files were moved to
`// @vitest-environment node`, cutting their environment cost to ~0ms, and the
full suite now passes cleanly at 161/1372. **The timeout was deliberately NOT
raised** — that would weaken a gate (definition-of-done item 2).

The underlying number is still poor and worth attention: `pnpm test` reports
roughly 2.1s of setup and 5.9s of jsdom environment *per file*. Worker
concurrency and `test/setup.ts` are where to look, and whether CI's runner
shows the same sensitivity should be watched on the first few pull requests.

**Verify:** `.\scripts	est.ps1` selects the new files. Full `pnpm test`:
**161 files / 1372 tests, all passing**. `pnpm check:complexity`, duplication,
design-system, architecture, and contract policies all pass.

---

### Slice 4 — Deprecation and warning debt

**Done.**

- `StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated`.
  The plan recorded this as `app/main.py` plus five call sites in
  `app/api/prompts.py`; it was actually **41 call sites across 16 modules**, and
  `app/main.py` was not one of them. All 41 now use
  `HTTP_422_UNPROCESSABLE_CONTENT`.
- `frontend/vitest.config.ts` moved from `__dirname` to `import.meta.dirname`.

**Verify:** `.\scripts\test.ps1` runs clean of both warnings.

---

## Sequencing and definition of done

Run 1 → 4. Slices 3 and 4 are independent of 2 and can be picked up in parallel.

A slice is done when:

1. `.\scripts\check.ps1` and `.\scripts\test.ps1` both pass.
2. No ceiling, exception list, coverage floor, or lint configuration was
   weakened to get there.
3. The measured number this plan cites for that slice has moved, and this
   document carries the new measurement.
4. Behavior is unchanged, or the change was requested explicitly.

### Current state

| Slice | Status |
|---|---|
| 1 — harness/CI gaps | **Complete.** E2E now runs in CI and is 34/34 green; the Python pin, the formatter gate, and the stale doc references are all closed |
| 2 — backend branch coverage | In progress. Coverage 83.79% → **85.14%**, floor raised 84 → 85. Seven of the ten target modules are done, `onboarding/research` is partial, and `commerce/intelligence` + `browser_transport` remain |
| 3 — untested frontend surfaces | In progress. All eleven directories have tests; `components/visibility` and `components/runs` are 6-of-14 and 4-of-11 files |
| 4 — deprecation and warning debt | **Complete** |

Nothing was weakened to get here: no ceiling changed, no complexity exception
was added, the coverage floor **rose** (84 → 85) on a measurement rather than a
guess, and the one E2E tolerance that moved was **tightened** (±12px → ±2px)
after the underlying CSS bug was fixed.

### Added since: test isolation from `.env`

Not in the original plan, and a direct consequence of the hazard Slice 2 found.
The backend suite no longer reads `.env` at all: `app/core/config/dotenv.py` is
the single owner of the decision, `tests/conftest.py` disables it and declares
the suite's own configuration, and `tests/unit/test_dotenv_isolation.py`
enforces both — including a sweep that fails if any config module builds its
own `.env` path. Point the suite at a database with `TEST_DATABASE_URL`; see
[`../DEVELOPMENT.md`](../DEVELOPMENT.md).

When every slice is complete, move this document to `docs/archive/` and remove
its row from [`../documentation-index.md`](../documentation-index.md).

---

## Watch, do not act

Recorded so the next reader does not re-derive them. None is a defect today.

- Twenty backend modules sit between 710 and 797 LOC. Fine at a 900 ceiling.
  Revisit only if one crosses 900 — and then as a design question about that
  module's responsibilities, not as a line-count exercise.
- Thirty-nine functions sit at CC 12 against a 15 ceiling. Same rule: only
  interesting if one actually exceeds 15.
- Large config-shaped modules (`core/config/site_health_rules.py`,
  `models/audit.py`) are long because they declare data. Length is not a defect
  there and they should not be split.
