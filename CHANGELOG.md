# Changelog

All notable changes to CiteLadder are documented in this file. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) when it begins publishing releases.

## [Unreleased]

### Added

- Weekly Dependabot coverage for backend `uv`, frontend `pnpm`, Docker, and GitHub Actions
  dependencies. Patch and minor updates are grouped; major updates remain separate for review.
- A clean-clone Compose workflow that starts the frontend, API, migrations, database, and workers.
- A pre-release checklist in [`docs/release-checklist.md`](docs/release-checklist.md).

### Changed

- Active documentation now identifies `docs/site-health.md` as the Site Health authority instead
  of linking to a removed archive directory.
- **Site Health extraction now reports its own failures.** DOM traversal catches are narrowed to a
  documented exception set and logged, so a parser bug is no longer scored as "this page has no
  title / no CTAs". Extraction still fails open on hostile HTML. `EXTRACTOR_VERSION` is
  `sh-extractor-8`; the first crawl after deploy re-fetches rather than reusing a v7 artifact.
- **Pulse audits carry their own retry budget** (`AUDIT_PULSE_MAX_ATTEMPTS`, default 2). Benchmark
  keeps the full `AUDIT_MAX_ATTEMPTS` (5). The budget is frozen onto each task at planning, so a
  live change never alters an in-flight run.
- **Sample crawls no longer fetch `llms.txt`.** It sat outside the `sample_mode` guard, so the free
  automatic crawl paid for a probe it never acted on.
- **Sitemap parse budget aligned with the admit budget** — `SITE_HEALTH_MAX_SITEMAP_URLS`
  50,000 → 5,000 and `SITE_HEALTH_MAX_SITEMAP_DECODED_BYTES` 50 MB → 8 MB. The walker now stops
  fetching documents once the collector saturates instead of parsing all 32 sitemap documents.
- **The Growth Agent records an unreadable source as `unavailable`**, not as a completed read, and
  withholds its empty body from the paid narration payload while still naming it to the model.
  Agent policy version is `bounded-agent-v4`.
- **Every API router raises `ApiException`** through `app/core/http_errors.py`; the raw
  `HTTPException` compatibility shim now covers only the framework's own routing errors. Response
  bodies are unchanged. See [`docs/api-error-contract.md`](docs/api-error-contract.md).
- Queue-row status tokens are imported from `app/core/config/task_queue.py` directly; the
  re-export block in `app/core/config/audits.py` is gone.
- The audit event list and SSE stream page at a configured ceiling
  (`AUDIT_MAX_EVENT_PAGE`, default 1,000) instead of materializing a whole history; the stream
  drains a full page before the terminal grace can close it.

### Removed

- `by_page_type` fallback in the Site Health score-summary projection. No writer has ever emitted
  that key — it was a compatibility branch for rows that do not exist.

### Fixed

- `SITE_HEALTH_MAX_EVENT_PAGE` is validated as positive; zero or a negative override was accepted
  and silently produced an empty or unbounded page.
- The measurement harness rejects a malformed (non-object) prompt entry through its configuration
  error path instead of raising `AttributeError`, and stamps the run manifest with the digest of
  the prompt artifact actually loaded rather than always the default one.

## Release policy

Do not create a tag, GitHub release, or package publication from this unreleased entry. A release
is created only after the checklist passes on a clean checkout and the intended version, release
notes, and commit are approved.
