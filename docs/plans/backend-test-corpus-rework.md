# Backend test corpus rework

> Deferred companion to the backend productionization refactor. Do not start
> this before that refactor's coverage gate has landed and been measured —
> this plan raises the floor it establishes.

## Why this is a separate plan

`backend/tests/` is 81,385 lines across 234 files. It does real Postgres
component work against a live service container, which is the right shape and
is not in question here. Two properties make it a liability rather than an
asset:

1. **No measured floor.** Until the productionization refactor adds
   `pytest-cov`, CI cannot tell whether a PR deleted the assertions that used
   to cover `planner.py` or `product_scoring_aggregation.py`. Volume without a
   measured floor is how oversized files coexist with untested seams — the
   `commerce_legacy_placeholder` branch reached production with zero coverage
   in a suite this large.
2. **Tests pin internals, not behavior.** Several files import worker
   internals and assert on method names, so a safe refactor of funded
   terminalization or the Site Health API rewrites thousands of test lines.
   This is what makes the near-800-LOC production modules expensive to touch:
   the cost is not the module, it is the test file behind it.

Splitting these files is a large, mostly mechanical change with a real risk of
silently dropping coverage while in flight. It needs the coverage gate in
place first so the drop is visible, which is exactly why it is deferred rather
than folded into the refactor.

## Scope

### 1. Split the oversized component files

| Lines | File |
|------:|------|
| 2330 | `backend/tests/component/test_site_health_api.py` |
| 1887 | `backend/tests/component/test_audit_worker.py` |
| 2087 | `backend/tests/component/test_analysis_api.py` |
| 1487 | `backend/tests/component/test_opportunities_service.py` |
| 1461 | `backend/tests/component/test_site_health_terminalization.py` |

`test_audit_worker.py` is already part-split: the productionization refactor's
Wave 7 pulled its attempt-budget scenarios into
`test_audit_attempt_budget.py` and its adapter stubs into
`audit_worker_helpers.py`. That is the shape the rest of this section should
follow — a scenario file plus one shared helper module, never a per-file copy
of the stubs.

Split by **scenario**, not by method: happy path / cancellation / lease
expiry / funded admission. Do not introduce a parallel test framework or a
second set of fixtures — the existing helpers (`tests/component/audit_helpers.py`,
`site_health_helpers.py`) stay the shared seam.

Keep exactly one end-to-end file per subsystem. `test_site_health_e2e.py`
documents at `:1-21` that it covers journeys the isolated API tests do not; it
is not a clone of `test_site_health_api.py` and must survive the split intact.

The productionization refactor will already have split the shopping-surface
and attempt-budget sections out of the first three files. Start from that
state, not from `main` as it stands today.

### 2. Replace private-attribute assertions with observable state

There are 152 `SLF001` (private member access) sites under `backend/tests/`.
The load-bearing ones reach into worker internals:

- `test_audit_worker.py` — `_apply_funded_ledger`
- `test_funded_terminalization.py` — `_queue`, `_sweep_expired_leases`
- `test_audit_events_sse.py:153` — a comment stating the test "mirrors
  `_load_events`", i.e. it asserts an implementation it duplicates

Each should assert on what the system actually persists or emits: queue rows,
ledger rows, lifecycle events, API responses. A test that mirrors the
implementation cannot catch the implementation being wrong.

Enable ruff `SLF001` for `backend/tests/` once the count reaches zero, so it
cannot regress. Leave `S101` (assert) off — asserts are the point.

### 3. Type the test tree and deepen the app gate

`mypy` does not run on `tests/` at all today
(`backend/pyproject.toml` `files = ["app"]`), and `mypy app --strict` reports
**1013 errors across 197 files**, so the gated typechecker cannot see untyped
defs or bare `dict`.

Turn on `disallow_untyped_defs` **one package at a time**, never globally in
one PR. Suggested order, densest-payoff first:

1. `app/api` — request-path DTO boundaries
2. `app/workers` — where `Any` currently spreads from untyped helpers
3. `app/domain/projects/onboarding/{research,service}.py` and
   `app/domain/command_center/service.py` — the two worst untyped clusters
4. `tests/` last, and only after the splits above

Leave lxml nodes as `Any` in `analysis/site_health/parser.py`; a tiny helper
type is enough. `type: ignore` in `app/` is already rare and justified
(`main.py:131` Starlette handler types) — keep it that way.

### 4. Ratchet the coverage floor

The productionization refactor landed `pytest-cov` with the floor at the
measured baseline: **`fail_under = 84`** (statement + branch, `source = ["app"]`,
omitting `migrations/`, `scripts/`, `evaluations/`, `tests/`). This plan raises
it in steps, each step justified by the splits above rather than by adding
assertions for their own sake. Never raise the floor and split files in the
same PR — one of the two will mask the other.

The thinnest seams in that baseline, and therefore the first places a raise
should come from:

| Coverage | Module |
|---------:|--------|
| 0% | `app/workers/agent_worker.py` |
| 29% | `app/workers/brand_discovery_worker.py` |
| 61% | `app/workers/analytics_worker.py` |
| 62% | `app/workers/content_worker.py` |
| 67% | `app/workers/commerce_discovery_worker.py` |

## Non-goals

- Deleting the catalog unit tests (`test_opportunities_config.py`,
  `test_content_config.py`, `test_integrations_config.py`). They pin
  vocabularies and are the only guard against catalog drift.
- Deleting `test_static_analysis_tools.py` — it pins the vulture
  configuration and is cheap.
- Deduplicating the `test_integration_bing.py` / `test_integration_ga4.py`
  fixture overlap. jscpd measures repository duplication at 0.08%; this is
  test setup, not app logic.
- Adopting aislop's 400-line file threshold. This repository's policy is 800
  LOC / CC 12, and the complexity policy roots are `["app"]` by design.

## Verification

From `backend/`, after every PR in this plan:

```
uv run pytest -vv --cov=app --cov-report=term
uv run ruff check .
uv run mypy app
uv run python -m scripts.check_complexity
```

Coverage must not fall between PRs. If a split drops a percentage point, the
missing assertions were real — restore them before merging rather than
lowering the floor.
