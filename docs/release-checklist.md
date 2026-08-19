# Release checklist

This checklist is for maintainers preparing a release after the change set has merged. It does
not authorize a release by itself: do **not** create a tag, GitHub release, or package publication
until every applicable gate is complete and the release owner approves the exact commit.

## 1. Select the candidate

- [ ] The candidate is a merged commit on the protected release branch.
- [ ] The version and scope are agreed, and [`../CHANGELOG.md`](../CHANGELOG.md) has accurate
      release notes under `Unreleased`.
- [ ] Open dependency PRs are reviewed independently; grouped Dependabot patch/minor updates do
      not bypass normal CI or review.
- [ ] Required security fixes, migrations, configuration changes, and rollback notes are known.

## 2. Verify from a clean clone

Use a new directory with no inherited application files, local databases, or dependency caches as
the release evidence. Do not substitute an already-running development stack.

```bash
git clone <repository-url> citeladder-release-check
cd citeladder-release-check
git checkout <candidate-commit>
cp infra/docker/.env.example infra/docker/.env
# Edit only local or deployment-specific values; do not commit this file.

env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD=citeladder_dev_password \
  docker compose --env-file infra/docker/.env -f infra/docker/docker-compose.yml \
  up -d --build --force-recreate

docker compose --env-file infra/docker/.env -f infra/docker/docker-compose.yml ps
curl -fsS http://localhost:3000/
curl -fsS http://localhost:8000/health
```

- [ ] Compose reports the migration job completed successfully and the API/frontend services are
      healthy or running as designed.
- [ ] The frontend loads at port 3000 and its browser requests use relative `/api/*` routes.
- [ ] The API health endpoint responds at port 8000.
- [ ] Smoke-test the appropriate authenticated and worker-backed flows with non-production data.
- [ ] Stop the evidence stack when finished: `docker compose --env-file infra/docker/.env -f
      infra/docker/docker-compose.yml down` (use `down -v` only when deleting disposable data).

## 3. Run repository gates

```bash
python docs/validate_documentation.py
(cd backend && uv sync --frozen --extra dev && uv run ruff check . && uv run mypy app)
(cd frontend && pnpm install --frozen-lockfile && pnpm lint && pnpm exec tsc --noEmit && BACKEND_ORIGIN=https://backend.ci.invalid pnpm build)
```

- [ ] Required backend, frontend, documentation, security, migration, and end-to-end checks pass.
- [ ] CI passes for the exact candidate commit.
- [ ] Deployment settings use real deployment secrets and origins; no `.env` file or local secret
      has entered the candidate.
- [ ] Rollback owner, target, and verification steps are recorded for production changes.

## 4. Create the release only after approval

- [ ] Obtain release-owner approval for the candidate commit, version, and final release notes.
- [ ] Create the annotated tag and release from that exact approved commit.
- [ ] Publish artifacts only after the tag/release exists and deployment verification is recorded.
