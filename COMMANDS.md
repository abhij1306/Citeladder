# CiteLadder command reference

Project-specific commands for local development and verification. Unless a command
specifies otherwise, run it from the repository root. Commands that say `backend/` or
`frontend/` should be run after changing into that directory.

## Tool versions

CiteLadder currently expects:

- Python 3.12+
- `uv` for backend dependencies and virtual-environment execution
- Node.js 20.19+ (22+ recommended)
- pnpm 11.9.0
- PostgreSQL 15+ (the Compose image is PostgreSQL 16)
- Docker Desktop with Docker Compose

Check the installed tools:

```
python --version
uv --version
node --version
pnpm --version
docker --version
docker compose version
psql --version
```

## Environment and dependency setup

### Backend (`uv` + Python)

From `backend/`:

```
uv sync --extra dev
uv run python --version
```

`uv run ...` uses the project environment and the locked dependencies from
`backend/uv.lock`; do not activate or create a separate virtual environment for normal
project work.

### Frontend (`pnpm`)

From `frontend/`:

```
pnpm install
```

For a clean CI-style install using the checked-in lockfile:

```
pnpm install --frozen-lockfile
```

Create `frontend/.env.local` with the server-only backend origin:

```
BACKEND_ORIGIN=http://localhost:8000
```

The browser uses relative `/api/*` URLs. Do not configure the frontend to call the
backend cross-origin directly.

## PostgreSQL

### Check the Docker database

These commands use the Compose database exposed on host port `55432`:

```
docker compose -f infra/docker/docker-compose.yml ps db
docker compose -f infra/docker/docker-compose.yml exec db pg_isready -U postgres -d citeladder
```

Open a PostgreSQL shell inside the database container:

```
docker compose -f infra/docker/docker-compose.yml exec db psql -U postgres -d citeladder
```

Useful commands inside `psql`:

```
\dt
\d "table_name"
SELECT * FROM "table_name" LIMIT 20;
\q
```

For a native PostgreSQL installation, use the host, port, user, and database from
`DATABASE_URL`. For the repository's current local Docker mapping, the equivalent
connection is:

```
psql -h 127.0.0.1 -p 55432 -U postgres -d citeladder
```

The SQLAlchemy URL used by the backend includes `+asyncpg`; remove that driver suffix
when using the `psql` CLI:

```
postgresql+asyncpg://postgres:<password>@127.0.0.1:55432/citeladder
postgresql://postgres:<password>@127.0.0.1:55432/citeladder
```

## Docker Compose

### First-time setup

```
Copy-Item infra/docker/.env.example infra/docker/.env
```

On Bash, use `cp infra/docker/.env.example infra/docker/.env` instead. Edit the copied
file before using non-local credentials or provider integrations.

### Start the full local stack

The repository documents a Compose environment-variable precedence issue: inherited
`POSTGRES_*` or `DATABASE_URL` variables can override `infra/docker/.env`. Clear those
variables for the Compose invocation.

PowerShell:

```powershell
Remove-Item Env:POSTGRES_USER -ErrorAction SilentlyContinue
Remove-Item Env:POSTGRES_DB -ErrorAction SilentlyContinue
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
$env:POSTGRES_PASSWORD = "citeladder_dev_password"
docker compose -f infra/docker/docker-compose.yml up -d --build --force-recreate
```

Bash:

```bash
env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD=citeladder_dev_password \
  docker compose -f infra/docker/docker-compose.yml up -d --build --force-recreate
```

The password supplied to Compose must match `POSTGRES_PASSWORD` in
`infra/docker/.env`. The stack includes PostgreSQL, the migration job, the FastAPI web
service, and the project workers.

### Inspect and operate services

```
docker compose -f infra/docker/docker-compose.yml ps
docker compose -f infra/docker/docker-compose.yml logs -f web
docker compose -f infra/docker/docker-compose.yml logs -f worker
docker compose -f infra/docker/docker-compose.yml logs --tail 100 migrate
docker compose -f infra/docker/docker-compose.yml restart web
docker compose -f infra/docker/docker-compose.yml config
```

Rebuild only the web image after backend changes:

```
docker compose -f infra/docker/docker-compose.yml up -d --build web
```

Stop the stack while keeping the PostgreSQL volume:

```
docker compose -f infra/docker/docker-compose.yml down
```

Stop the stack and delete its PostgreSQL volume (**destructive; deletes local DB data**):

```
docker compose -f infra/docker/docker-compose.yml down -v
```

## Backend: FastAPI, workers, and migrations

Run these from `backend/` with `DATABASE_URL` pointing at the intended database.

### Start the API

```
uv run uvicorn app.main:app --reload --port 8000
```

Health check:

```
curl http://localhost:8000/health
```

### Run workers locally

Each worker needs its own terminal. The worker is intentionally separate from the web
process because provider calls and queued work do not run in the API process.

```
uv run python -m app.workers.audit_worker
uv run python -m app.workers.site_health_worker
uv run python -m app.workers.brand_discovery_worker
uv run python -m app.workers.content_worker
uv run python -m app.workers.analytics_worker
uv run python -m app.workers.integration_worker
uv run python -m app.workers.integration_dispatcher
```

Start only the workers needed for the feature being exercised. The Docker Compose
service names map to these same Python modules.

### Apply and verify migrations

```
uv run alembic upgrade head
uv run alembic check
```

The migration policy uses the complete `0001_initial` baseline. Do not edit an applied
migration casually or create an additive revision without following the project
migration policy.

Reset the schema on a disposable database only:

```
uv run alembic downgrade base
uv run alembic upgrade head
```

From the repository root, reset and recreate the database configured by `DATABASE_URL`:

```
uv run --project backend python reset-db.py
```

`reset-db.py` resolves the Docker development env as a fallback, drops and recreates the
target database, then runs migrations. For a development `APP_ENV`, it also provisions the
env-driven `DEV_LOGIN_EMAIL` / `DEV_LOGIN_PASSWORD` account with the configured
`DEV_LOGIN_COUNTER_ALLOWANCE`. Never run it against shared, staging, or production data.

## Backend tests and checks

From `backend/`:

```
uv run pytest -q
uv run pytest tests/unit/test_<area>.py -q
uv run pytest tests/unit/test_<area>.py tests/component/test_<area>.py -q
uv run ruff check .
uv run mypy
uv run python -m scripts.check_complexity
```

The complexity check enforces fixed defaults of CC 12 per function and 800 LOC per
module, with narrow checked-in exceptions for existing debt. It has no update or
rebaseline command. CI compares the policy with the PR base and rejects higher or
newly added exceptions; new code must fit the defaults.

Pinned static-analysis commands, installed by the frozen backend/frontend locks:

```powershell
# From backend/. Vulture is a CI gate; Radon is an advisory report.
uv run vulture app --min-confidence 80
uv run radon cc app -s -n C
uv run radon mi app -s -n B

# From frontend/. Both production checks are CI ratchets; the test scan is advisory.
pnpm check:complexity
pnpm check:duplicates
pnpm report:duplicates:tests
```

FastAPI decorators, Pydantic validators/fields, SQLAlchemy mappings, and registry
dispatch are common Vulture false positives. Declarative config and ORM modules are
poor Radon-MI refactor targets without an independent ownership or behavior problem.
The duplication gate scans only production owners under `backend/app` and
`frontend/{app,components,lib}` using the checked-in `jscpd.json`; test duplication is
reported separately and does not block CI.

The test suite needs a running PostgreSQL server. It creates and removes a throwaway
test database and does not use the development database for test data.

## Project utility scripts

Run these from `backend/` unless noted otherwise. Use `--help` before operator scripts
whose arguments are not shown here.

Seed local demo data (**development or disposable database only**):

PowerShell:

```powershell
$env:APP_ENV = "development"
uv run python -m scripts.seed_dev_data
```

Bash:

```bash
APP_ENV=development uv run python -m scripts.seed_dev_data
```

Provision a local development login:

```
uv run python -m scripts.provision_dev_login --help
```

Grant a local Site Health monitored-URL allowance:

```
uv run python -m scripts.set_site_health_entitlement <workspace_uuid> <monitored_urls>
```

Inspect available arguments for measurement and billing/operator utilities:

```
uv run python -m scripts.measure_answer_engine_matrix --help
uv run python -m scripts.reprice_execution_costs --help
uv run python -m scripts.reconcile_billing --help
uv run python -m scripts.provision_platform_provider_connections --help
uv run python -m scripts.provision_razorpay_plans --help
```

## Frontend: Next.js and pnpm

Run these from `frontend/`.

Start the development server at `http://localhost:3000`:

```
pnpm dev
```

Build and start the production bundle:

```
pnpm build
pnpm start
```

Lint, format, and check formatting:

```
pnpm lint
pnpm format
pnpm format:check
```

Run frontend tests:

```
pnpm test
pnpm test:watch
pnpm test:coverage
pnpm test -- path/to/file.test.tsx
```

Run architecture, design-token, and API-contract checks:

```
pnpm check:policy
pnpm check:contract
pnpm exec tsc --noEmit
```

Run browser tests. A running stack and installed Playwright browsers are required:

```
pnpm exec playwright install
pnpm test:e2e
pnpm test:e2e -- e2e/path/to/file.spec.ts
pnpm test:visual
pnpm test:visual:update
```

## Typical local workflows

### Docker-backed development

Use separate terminals:

```
# Terminal 1: from repository root
# Use the PowerShell or Bash start command from the Docker Compose section above.
# It clears inherited POSTGRES_* / DATABASE_URL variables first.

# Terminal 2: from frontend/
pnpm dev
```

The Compose stack already runs the backend web process and workers. Check
`docker compose ... ps` and `docker compose ... logs -f web` if the frontend cannot reach
the API.

### Native backend + PostgreSQL development

```
# Terminal 1: from backend/
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2: from frontend/
pnpm dev
```

Start the required worker modules in additional backend terminals when exercising
queued audits, Site Health, content, analytics, or integrations.

## Common command rules

- Use `pnpm`, never npm or yarn, for the frontend.
- Use `uv run` for Python commands and `uv sync` for backend dependencies.
- Keep `DATABASE_URL` aligned with the PostgreSQL instance being used. Docker Compose
  uses the internal hostname `db`; host-run backend processes use `127.0.0.1`.
- Use relative `/api/*` requests from the browser; `BACKEND_ORIGIN` is server-only.
- Run database reset, `alembic downgrade`, and demo seeding only against disposable local
  data.

