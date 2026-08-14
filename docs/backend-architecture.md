# CiteLadder backend architecture

> **Status:** current runtime authority
> **Shape:** FastAPI modular monolith plus separate workers
> **Durable state and queue:** PostgreSQL

## Runtime stack

- Python 3.12, FastAPI, async SQLAlchemy, asyncpg, and Pydantic settings.
- PostgreSQL for product state, immutable evidence, projections, and durable
  work queues.
- Separate workers for audits, Site Health, content, integrations, analytics,
  and bounded standalone Growth Agent tasks.
- Fernet-encrypted provider/OAuth secrets and least-privilege worker
  environments.
- Thin `/api/v1` routers; domain services own business rules.

## Layers

```text
api/          HTTP translation, dependencies, coded errors
core/         configuration, database, security, telemetry
models/       SQLAlchemy persistence
domain/       canonical business owners
connectors/   external acquisition/provider boundaries
analysis/     deterministic bounded derivation
workers/      lease -> I/O/analysis -> atomic terminal write
```

Business logic does not move into routers, connectors, workers, or generic
utilities for convenience.

## Current subsystem map

| Subsystem | Responsibility |
|---|---|
| Auth/workspaces/projects | Tenant and project boundary |
| Site Health | Discovery, secure acquisition, page kinds, rules, scores, issues, snapshots, exports |
| Content | Website-grounded generation queue, attempts, history, feedback |
| Integrations/Traffic/Analytics/Demand | GSC/Traffic evidence, snapshots, signals |
| Prompts/Audits/Visibility | Prompt portfolios and answer-engine measurement |
| Opportunities | One persisted cross-system action store |
| Commerce | Catalog/product specialization |
| Growth Agent | Standalone explain/roadmap runs and append-only typed-tool attempts |

## Authentication and tenant creation

Registration always returns the same `202 RegistrationResponse` for new and
existing addresses and never creates a browser session; the caller signs in
explicitly. Login JWTs carry the user's persisted `session_version`. Logout
increments that version before deleting the cookie, invalidating every token
issued under the previous version.

Authentication abuse limits identify clients from `X-Forwarded-For` only when
the direct ASGI peer belongs to `TRUSTED_PROXY_CIDRS`; the chain is walked from
the trusted edge toward the first untrusted address. Production startup fails
closed when the trusted-proxy networks are missing or invalid. The AWS deployer
places frontend proxy tasks in dedicated subnets and injects only those subnet
CIDRs. Catch-all IPv4 and IPv6 networks are rejected.

User-created workspaces are transaction-serialized per account and capped by
the config-owned `MAX_WORKSPACES_PER_USER`. The personal workspace counts
toward the cap; excess creates return `workspace_limit_exceeded`.

## Site Health

`connectors/web_evidence` is the only website acquisition boundary. The ladder
is `secure_httpx -> curl_cffi -> patchright`, gated by config-owned evidence and
resource limits.

Patchright enforces both limits independently: Chromium CDP network events
account for cumulative response bytes during acquisition, while rendered DOM
serialization enforces the decoded-document cap before HTML crosses the driver
boundary.

Site Health owns crawl, URL, task, attempt, artifact, evaluation, analysis,
issue, snapshot, event, and export persistence. `SitePageAnalysis` is the one
page-understanding row. It stores scores, analyzer/scoring versions,
`page_kind`, classifier version/evidence, and source IDs. It is append-only per
artifact/analyzer version with one current row.

A Site Health crawl is created only by the explicit user **Run new crawl**
action. Discovery and analysis remain durable internal phases: admitted pages
are progressively and automatically enqueued for analysis while discovery is
running, subject to the entitlement/runtime allowance frozen on that crawl.
The product control surface has no separate discovery or analysis start action.

The standard production crawl freezes a 500-page requested limit. Advanced
input and the 50,000 discovery/analysis ceilings are development-only config;
they are not a production UI contract or a throughput claim. The Site Health
worker owns reusable secure HTTP clients partitioned by original origin, while
each request continues to enforce the connector's DNS, pinned-IP, redirect,
robots, scope, and host-gate controls. Sitemap observation inserts are bounded
batched writes.
The default host-gate concurrency and start spacing permit at least six request
starts per second on a responsive host, while robots crawl-delay overrides
upward and observed throughput remains workload-dependent.

The analysis sequence is fixed:

```text
artifact -> normalized facts -> page_kind assessment
  -> inject kind/evidence -> rule evaluation -> scoring -> persisted rows
```

The former industry-role, knowledge, correction, and comparison columns/tables
were removed. `page_kind` remains the generic structural classifier and drives
schema/property contracts and rule applicability. See
[`site-health.md`](site-health.md).

## Content

`ContentGeneration` and `ContentGenerationAttempt` are the queue/result owners.
The shipped runtime has no strategy, brief, context-package, validation,
revision, publication-claim, or verification rows.

The current brief evidence adapter returns explicit empty `allowed_facts`,
`prohibited_claims`, and `source_refs` because its former knowledge-assertion
source was removed. A replacement requires a separate approved design.

## Demand, Traffic, and visibility

Integration import artifacts are immutable. Normalized GSC/GA4 rows and Demand
snapshots preserve provider coverage, requested/available report families,
join coverage, source IDs, and formula versions. Missing permissions or data
remain unavailable rather than becoming zero.

Search Demand projects its latest snapshot as ranked GSC query/page gaps with
their evidence window and observed impressions, clicks, and CTR. It does not
embed a duplicate AI Visibility projection. Traffic projections make chart
granularity explicit while retaining selected-window totals. AI Referrals derives
session volume and shares only from `ga4_source_medium_daily`; overlapping
referrer rows are provenance, not an additional summand. Derived referral
snapshots carry formula/analyzer versions and rebuild through an explicit worker
path, never in a read route.

Prompt generation, scheduled audits, provider attempts, and answer-engine
measurements use existing queue owners and immutable evidence. Visibility does
not write business truth.

## Growth Agent

Agent runs resolve a config-owned task policy, freeze a bounded context package,
execute registered typed tools, and persist progress/results. Result contracts
contain plain-language summary/observations, source availability, limitations,
artifact references, and deterministic Opportunity-ordered roadmap items.
Compact history and full run-detail routes have separate response shapes so
history reads do not return provenance payloads. Conversation reads do not
recompute domain state. The agent has no correction or knowledge-memory tool
after the Site Intelligence removal.

## Task queue contract

1. Claim bounded work with `FOR UPDATE SKIP LOCKED`.
2. Persist the lease and commit before network I/O.
3. Heartbeat long work and recover expired leases.
4. Write terminal state and derived rows atomically.
5. Make cancellation, retries, and reconciliation idempotent.
6. Never hold database transactions open across provider calls.

## API and persistence rules

- Every project-owned query is workspace-scoped.
- All public IDs are UUIDs.
- Reads render persisted projections; they never crawl, sync, classify, call a
  model, or repair lifecycle state.
- Raw evidence and provider attempts are append-only.
- Derived data carries direct source IDs and relevant versions.
- Configuration and product policy live under `app/core/config/*`.
- PostgreSQL remains the durable queue; do not add Redis without measured need.

## Verification

Use focused unit/component tests and Ruff for changed owners. Schema changes
are folded into `migrations/versions/0001_initial.py`, then verified from an
empty disposable database with `alembic upgrade head` and `alembic check`.
