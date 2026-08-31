# Development guide — CiteLadder

Everything needed to run, test, and troubleshoot CiteLadder locally, including two
environment gotchas that otherwise waste substantial time. Pair this with
[`../AGENTS.md`](../AGENTS.md), [`README.md`](README.md), and
[`invariants.md`](invariants.md).

## Toolchain

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.12+ | Backend |
| [`uv`](https://docs.astral.sh/uv/) | latest | Backend dependency + venv manager |
| Node.js | 22+ | Frontend |
| pnpm | 11.9+ | Frontend package manager; pinned in `frontend/package.json` |
| PostgreSQL | 15+ | Via Docker or local |
| Docker + Compose | latest | Local stack |

## Backend setup

```bash
cd backend
uv sync                     # creates backend/.venv and installs deps from uv.lock
export DATABASE_URL="postgresql+asyncpg://postgres:<password>@localhost:5432/citeladder"
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

Run only the separate workers required by the workflow under test. The web process enqueues
work and never performs provider calls or long-running crawl/sync/generation work inline.

```bash
cd backend
uv run python -m app.workers.audit_worker
uv run python -m app.workers.audit_scheduler
uv run python -m app.workers.site_health_worker
uv run python -m app.workers.brand_discovery_worker
uv run python -m app.workers.content_worker
uv run python -m app.workers.integration_worker
uv run python -m app.workers.integration_dispatcher
uv run python -m app.workers.analytics_worker
```

Each process uses the shared durable PostgreSQL queue/lease contract and receives only the
configuration/secrets required by its owner.

## Frontend setup

```bash
cd frontend
echo "BACKEND_ORIGIN=http://localhost:8000" > .env.local
pnpm install
pnpm dev                    # http://127.0.0.1:3000
```

`BACKEND_ORIGIN` is **server-only**. The browser calls relative `/api/*`; Next.js
`rewrites()` proxy those to `BACKEND_ORIGIN` (see gotcha 2 below).

## Running the full stack with Docker Compose

The Compose path is the clean-clone workflow. From the repository root, it builds and starts
PostgreSQL, applies the migration baseline once, then starts FastAPI, the browser-facing Next.js
frontend, and the workers. Do not run host-side migrations or `pnpm dev` alongside this stack.

```bash
cp .env.example .env

# Use the env -u workaround (gotcha 1) and select the copied env file — verbatim:
env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)" \
  docker compose --env-file .env -f docker-compose.yml \
  up -d --build --force-recreate

# The frontend proxies relative /api/* requests to the API inside Compose.
curl -fsS http://localhost:3000/
curl -fsS http://localhost:8000/health
```

The stack's frontend is at `http://localhost:3000`, and FastAPI is at
`http://localhost:8000`. Inspect readiness with the same `env -u` wrapper (gotcha 1) —
every Compose invocation resolves `${VAR}` from the shell first, not just `up`:

```bash
env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)" \
  docker compose --env-file .env -f docker-compose.yml ps
```

The one-shot `migrate` service must have completed successfully. See
`docker-compose.yml` for the executable process list and
[`release-checklist.md`](release-checklist.md) for clean-clone release verification.

## Testing

### Backend

Backend tests use a real Postgres (each test runs against an isolated schema). The
suite creates a throwaway `citeladder_tests_<runid>` database for the run and drops it
on teardown — nothing persists and the dev database is never touched.

**Tests never read `.env`.** A developer `.env` carries real provider keys, OAuth client
secrets, and the encryption key; loading them into a test run turns "is this provider
configured?" branches ON, which is how a component test once posted evidence to a live
provider endpoint. `backend/tests/conftest.py` therefore sets
`CITELADDER_DISABLE_DOTENV`, supplies its own deterministic secrets, and clears inherited
`*_API_KEY` / `*_CLIENT_SECRET` / `*_CLIENT_ID` variables before importing the app.
`backend/tests/unit/test_dotenv_isolation.py` enforces it, and
`backend/app/core/config/dotenv.py` is the single owner of the opt-out.

The one thing the suite cannot invent is a Postgres server, so tell it where one is.
Export this once per shell (or in your profile); CI already sets `DATABASE_URL`:

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://postgres:<password>@127.0.0.1:55432/citeladder"
```

```bash
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:<password>@127.0.0.1:55432/citeladder"
```

`TEST_DATABASE_URL` is preferred; a `DATABASE_URL` already exported in the shell is used
as a fallback, and without either the localhost default is tried. Only the server
(host/port/credentials) is reused — never that server's own database.

```bash
cd backend
uv run pytest -q
uv run ruff check .
```

### Frontend

```bash
cd frontend
pnpm test             # Vitest (network mocked with MSW)
pnpm lint             # Oxlint (React/Next/TypeScript/a11y rules)
pnpm check:policy     # architecture + design-token guards
pnpm check:dead-code  # Knip module-graph/dependency gate
pnpm exec tsc --noEmit # type check
pnpm build            # next build
pnpm test:e2e         # Playwright (needs a browser + a running stack)
```

### Repository validation harness

`scripts/quality.mjs` owns the static sequence used by both local development
and CI. `check.ps1` remains the PowerShell compatibility shim. Run the two
completion commands from the repository root, in this order, once the planned
implementation is finished — not after every step.

```powershell
.\scripts\check.ps1     # static + fix gate: ruff, mypy, complexity,
                        # import-linter, vulture, deptry, oxfmt, oxlint,
                        # tsc, Knip, frontend policies, contract, docs index
.\scripts\test.ps1      # affected backend, frontend, and mapped E2E tests
```

Useful variants:

```powershell
.\scripts\check.ps1 -CheckOnly              # never mutates files
.\scripts\check.ps1 -Scope Backend          # or Frontend
.\scripts\test.ps1 -ChangedFiles a.py,b.py  # retry delta after a failed run
```

The direct cross-platform entry points are available from `frontend/` as
`pnpm quality:fix` and the non-mutating `pnpm quality:check`.

`test.ps1` compares the working tree against `origin/main`, maps every changed
production file through `scripts/validation.json`, and fails if a changed file
under `backend/app` or `frontend/{app,components,lib}` has no mapping. Add the
missing mapping; never substitute a broad or full-suite fallback.

GitHub CI has one cheap classifier before the implementation jobs. On an
initial pull-request run it classifies the complete PR diff. On a subsequent
push it classifies only the range from the previous PR head to the new head and
also reruns any owner that failed on that previous head. Backend-only and
frontend-only pushes therefore do not repeat the other successful suite.
Changes to shared tooling or configuration select both sides; backend API/schema
and frontend API-client paths also select both sides and the strict contract
job. Documentation-only changes run the common classifier and documentation
gates. The clean-clone Compose smoke runs on initial application PR validation,
Compose-sensitive follow-up changes, a previously failed smoke owner, merge
queue validation, and every push to `main`. Merge queue and `main` events select
every CI owner as the final safety net.

Only `CI / Required` needs to be a required status for the main workflow. It
requires common gates and every selected owner while accepting jobs that the
classifier intentionally skipped. Do not add workflow-level `paths` filters to
required workflows; a skipped workflow can leave a required status pending.

Static-analysis commands, pinned by the frozen locks:

```powershell
# From backend/. Vulture, import-linter and deptry are CI gates; Radon is an
# advisory report. `app`, `evaluations` and `scripts` are all gated: an
# operational script that silently rots is a script nobody can run on the day
# they need it.
uv run vulture app evaluations scripts --min-confidence 80
uv run lint-imports          # layer contracts, backend/.importlinter
uv run deptry .              # declared-but-unused / used-but-undeclared deps
uv run radon cc app -s -n C
uv run radon mi app -s -n B

# From frontend/. These production checks are CI ratchets; the test scan is advisory.
pnpm check:complexity
pnpm check:duplicates
pnpm check:dead-code
pnpm report:duplicates:tests
```

The backend complexity policy enforces **CC 12 per function and 800 LOC per
module** across `app`, `evaluations` and `scripts`; the frontend policy has its
own ceilings. The exception lists are empty and should stay that way, and there
is no rebaseline command: CI compares the policy with the PR base and rejects
higher ceilings, higher exceptions, and newly added exceptions. Roots may be
*added* (widening the gate is a tightening) but never removed.

### Coverage

Coverage is measured and published whenever its owning CI suite is selected and
is **not a gate**, in either the repository-wide or the changed-lines form. A
coverage ratio is a target you can move without improving anything, so enforcing
one reliably produces tests written to move the number rather than to describe
behaviour.

What must be tested is decided by `scripts/validation.json`, which maps every
production file to the tests that have to run for it, and `test.ps1` fails when
a changed file under `backend/app` has no mapping. That mapping is reviewable in
a way a percentage is not. `scripts/` and `migrations/` have no suite; they are
held by ruff, mypy, vulture, import-linter and the complexity policy instead.

### Architecture policy

`backend/.importlinter` is the backend counterpart to the frontend's
`pnpm check:policy`. Seven contracts pin the directions that hold today: the API
and the workers are leaves nothing imports, `core` depends on no business logic,
and `models`, `connectors`, `orchestration` and `analysis` do not reach up.
Three known warts are recorded as named `ignore_imports` lines rather than
softened rules -- a wart with a name cannot quietly become two.

### Suppressions

`RUF100` is enabled, so a `# noqa` that suppresses nothing fails the build. A
suppression must name a rule this config actually enables and must currently
apply; every one carries its reason inline. This was added after an audit found
22 dead directives, including two file-level `# ruff: noqa: E501` blankets on
files with no long lines and thirteen `# noqa: BLE001` comments for a rule that
was enabled in one subpackage only.

## Project utility scripts

Run these from `backend/`. Use `--help` before any operator script whose
arguments are not shown here.

Seed local demo data (**development or disposable database only**):

```bash
APP_ENV=development uv run python -m scripts.seed_dev_data
```

Provision a local development login, or grant a Site Health allowance:

```bash
uv run python -m scripts.provision_dev_login --help
uv run python -m scripts.set_site_health_entitlement <workspace_uuid> <monitored_urls>
```

Measurement and billing/operator utilities:

```bash
uv run python -m scripts.measure_answer_engine_matrix --help
uv run python -m scripts.reprice_execution_costs --help
uv run python -m scripts.reconcile_billing --help
uv run python -m scripts.provision_platform_provider_connections --help
uv run python -m scripts.provision_razorpay_plans --help
```

From the repository root, reset and recreate the database named by
`DATABASE_URL` (**never against shared, staging, or production data**):

```bash
uv run --project backend python reset-db.py
```

The reset runs without an extra token only when `APP_ENV` is a development
value and `DATABASE_URL` targets `localhost`, `127.0.0.1`, or `::1`. A remote
host is refused even under `APP_ENV=development`; the exceptional case requires
the explicit `RESET_CONFIRM_DESTRUCTIVE=drop-and-recreate` token.

## Migrations (single greenfield baseline)

CiteLadder is greenfield and keeps one complete `0001_initial` revision. Fold
every schema change into that baseline, reset only disposable databases, and
verify the complete schema from scratch. Do not introduce additive revision
files while this policy is in effect.

Verify the bootstrap only against a disposable database:

```bash
cd backend
uv run alembic upgrade head
uv run alembic check            # explicit revisions match Base.metadata
uv run alembic downgrade base   # destructive; disposable database only
uv run alembic upgrade head
```

`alembic check` must converge with `Base.metadata` after every baseline edit.

---

## Site Health runtime (development)

Site Health behavior is a **runtime projection** of the account's resolved
`monitored_urls` entitlement allowance, stored one row per workspace in
`workspace_site_health_runtime`. The row is not a commercial source of truth: it
carries the neutral crawl policy (discovery mode, discovery/sample caps, monitored-URL
limit, count-disclosure flag) plus resolver provenance, and it doubles as the `FOR
UPDATE` quota-serialization lock.

A workspace with no grants resolves to the **zero-allowance sample policy** (fail-closed:
sample discovery, zero selectable monitored URLs, no count disclosure). To grant a
monitored-URL allowance locally, use the operator/dev command, run from `backend/` with
`DATABASE_URL` pointing at the target database:

```bash
cd backend
uv run python -m scripts.set_site_health_entitlement <workspace_uuid> <monitored_urls>
```

The command issues an audited operator `override` grant through the append-only write
service (`app.domain.entitlements.grants.issue_override_bundle`), re-projects the
workspace runtime row, and emits a single audit-safe log line (no secrets). Allowances
SUM across grants — a second grant adds to the first; revoking earlier grants is a
separate audited operation.

---

## Gotchas runbook

These two are environment-specific and will silently break the stack. The canonical
versions live in [`invariants.md`](invariants.md) §11–12.

### Gotcha 1 — shell secrets override Docker Compose `${VAR}`

**Symptom:** `docker compose up` connects Postgres/backend with the wrong
credentials/database even though `.env` looks correct.

**Cause:** this machine exports `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`, and
`DATABASE_URL` into **every shell**. Compose resolves `${VAR}` in `docker-compose.yml` from
the **shell environment before `.env`** (`env_file:` only injects vars *inside* the
container, not into `${VAR}` interpolation). The shell values win and silently override the
repo values.

**Workaround (verbatim):**

```bash
env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD=<repo-.env-value> \
  docker compose --env-file .env -f docker-compose.yml \
  up -d --build --force-recreate
```

Unset the four inherited vars for the Compose invocation and re-supply the repo `.env` value
explicitly. `docker-compose.yml` carries this note as a baked-in comment.

(This gotcha applies to the recommended Compose stack. Native development and tests use
their own configured PostgreSQL connection.)

### Gotcha 2 — tunnel double CORS header → same-origin rewrites

**Symptom:** frontend network calls fail in the browser with a CORS error about **duplicate**
`Access-Control-Allow-Origin` headers — but `curl` against the same backend succeeds.

**Cause:** the preview/tunnel proxy injects its own `Access-Control-Allow-Origin: *`. A
FastAPI backend that also sets a specific ACAO (required when `allow_credentials=True`)
produces **two** ACAO headers, which browsers reject. `curl` does not enforce CORS, so it
cannot reproduce the failure.

**Fix:** the browser never talks cross-origin to the backend. Next.js `rewrites()` proxy
`/api/:path*` → the server-only `BACKEND_ORIGIN`, so all browser calls are **same-origin**
(`/api/...` relative). The API client uses a relative base (`/api/v1`), `cache: 'no-store'`,
and `credentials: 'include'`.

```ts
// frontend/next.config.ts
async rewrites() {
  return [{ source: '/api/:path*', destination: `${process.env.BACKEND_ORIGIN}/api/:path*` }];
}
```

**Always test this in a real browser, not curl.**

## Web preview (running the stack behind a tunnel)

When previewing the app behind a tunnel/proxy:

1. Point the frontend's `BACKEND_ORIGIN` at the running backend.
2. Ensure the dev server accepts the proxied host (Next.js `allowedDevOrigins` / equivalent
   blocked-host config) so the preview host isn't rejected.
3. Confirm every browser network call hits relative `/api/*` (same-origin) — not a
   cross-origin backend URL. This is what avoids the gotcha-2 double-CORS failure.
