# CiteLadder Docker stack

Services: `db` (Postgres 16), `migrate` (one-shot `alembic upgrade head`),
`web` (FastAPI/uvicorn), `frontend` (Next.js, port 3000), and the named background workers.
The frontend proxies its relative `/api/*` routes to `web` on the Compose network; browsers do
not need a direct backend origin.

## Content generation env

The content worker's provider is env-driven (see `.env.example`):
`CONTENT_PROVIDER` (default `mistral`), `CONTENT_MODEL` (default
`mistral-small-latest`), `MISTRAL_API_KEY` (**empty = content generation
disabled**; the API returns 409 `provider_not_configured` on enqueue),
`CONTENT_PROVIDER_ENDPOINT` (OpenAI-compatible chat-completions URL),
`CONTENT_REQUEST_TIMEOUT_SECONDS`, `CONTENT_MAX_OUTPUT_TOKENS`.

On **Railway**, run the content worker as a **separate service** with start
command `python -m app.workers.content_worker`, sharing the same env
(including `MISTRAL_API_KEY`) as the web + audit-worker services.

Run brand discovery as a separate service with start command
`python -m app.workers.brand_discovery_worker`. It performs one SSRF-safe
homepage request and uses the application model with a deterministic industry
fallback. Research gaps are warnings and always remain editable at review.

## Default application model

Assisted onboarding and prompt generation default to Mistral Small 4 through
`https://api.mistral.ai/v1` with model `mistral-small-2603`. The client selects
`MISTRAL_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY`, or
`AWS_BEARER_TOKEN_BEDROCK` only when `DEFAULT_AGENT_BASE_URL` matches that
provider; `DEFAULT_AGENT_API_KEY` remains the explicit fallback for other
OpenAI-compatible gateways.


## Bring the stack up (gotcha 1 workaround — use verbatim)

This machine exports `POSTGRES_PASSWORD` / `POSTGRES_USER` / `POSTGRES_DB` /
`DATABASE_URL` into **every shell**, and Docker Compose resolves `${VAR}` from
the shell environment **before** `.env`. Those inherited values silently
override the repo `.env`, so you must unset them for the Compose invocation and
re-supply the repo password explicitly (see `docs/invariants.md` invariant 11):

```bash
cd /path/to/CiteLadder
cp infra/docker/.env.example infra/docker/.env   # first time only

env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD=citeladder_dev_password \
  docker compose --env-file infra/docker/.env -f infra/docker/docker-compose.yml \
  up -d --build --force-recreate
```

`POSTGRES_PASSWORD` must match the value in `infra/docker/.env`.

Check the browser-facing frontend and API after `migrate` completes:

```bash
docker compose --env-file infra/docker/.env -f infra/docker/docker-compose.yml ps
curl -fsS http://localhost:3000/
curl -fsS http://localhost:8000/health   # {"status":"ok"}
```

Tear down:

```bash
docker compose --env-file infra/docker/.env -f infra/docker/docker-compose.yml down      # keep volume
docker compose --env-file infra/docker/.env -f infra/docker/docker-compose.yml down -v   # drop DB volume
```

## Local (no Docker)

```bash
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```
