# CiteLadder security and production-readiness audit

- **Audit date:** 2026-07-27
- **Repository revision:** `7effabf91f8012982a816d807ab9df93b9aece85`
  (`main`; parent of the audit-document commit)
- **Report status:** **pre-remediation baseline**. Findings, counts, and the
  verdict describe only the revision above. Later changes on
  `docs/security-production-aws-audit` are remediation candidates, not an
  audited final tree; this report must be rerun before any finding is marked
  closed or any launch decision is changed.
- **Assessment type:** source, configuration, dependency, container, CI/CD, and
  production-operations review
- **Related runbook:** [AWS hosting runbook](aws-hosting-runbook.md)
- **Billing launch gate:**
  [Razorpay and demo owner requirements](razorpay-and-demo-owner-requirements.md)

## Executive verdict

**At the reviewed baseline, CiteLadder was not ready for an unrestricted public
production launch.** A controlled staging deployment was reasonable only after
the immediate staging gates below were met. This historical verdict is not an
approval or rejection of the remediation branch: the final remediated revision
requires a new audit, retained evidence, and an updated launch decision.

No obvious direct SQL-injection path, arbitrary-code-execution path, committed
production credential, BYOK secret response, or workspace-authorization bypass
was found in the reviewed revision. Those are meaningful strengths, but they do
not offset the current gaps in abuse controls, browser session transitions,
credential-bearing outbound endpoints, cache isolation, request-size and secret
strength enforcement, immutable migrations, reproducible images, database
capacity, and production operations.

### Immediate launch decision

| Environment        | Decision       | Minimum condition                                                                                                                                                                                      |
| ------------------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Local development  | Go             | Continue using the documented local workflow.                                                                                                                                                          |
| Controlled staging | Conditional go | Use synthetic data and non-live provider/billing credentials; disable API caching; use unique secrets; impose edge rate limits; freeze the database bootstrap; and deploy through reproducible images. |
| Private pilot      | No-go today    | Close all high findings, complete restore and rollback drills, and add monitoring/on-call ownership.                                                                                                   |
| Public production  | No-go today    | Meet every production gate in this report and the AWS runbook.                                                                                                                                         |

## Severity model

| Severity | Meaning                                                                                                                       |
| -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Critical | A practical path to broad compromise, destructive loss, or cross-tenant disclosure requiring emergency action.                |
| High     | A credible security or availability failure that blocks public launch, especially at an internet boundary or tenant boundary. |
| Medium   | Important defense-in-depth or operational weakness that should be fixed before scale or shortly before launch.                |
| Low      | Hardening, quality, or documentation issue with limited direct impact.                                                        |

There were **no confirmed critical findings**. This is not a guarantee that no
critical vulnerability exists; the limitations section defines what was not
tested.

## Scope and method

The review covered:

- all 132 registered FastAPI route definitions and their authentication or
  deliberate public status;
- workspace membership dependencies, UUID scoping, ORM query patterns, response
  schemas, billing webhooks, OAuth flows, and secret-handling paths;
- authentication cookies, frontend API calls, React Query keys/caches,
  local-storage state, Markdown rendering, downloads, and same-origin rewrites;
- the PostgreSQL task queue, lease/heartbeat paths, six worker processes,
  immutable evidence, crawler URL policy, and provider HTTP clients;
- configuration defaults, the Alembic bootstrap, Docker assets, CI workflow,
  dependency locks, and repository secret scanning;
- production deployment, availability, monitoring, backup, restore, rollback,
  data lifecycle, and AWS suitability.

Techniques included manual data-flow review, endpoint/dependency inventory,
targeted source searches for dangerous sinks and missing controls, dependency
advisory checks, package-integrity verification, and focused automated tests.

### Verification performed

The baseline run did not retain raw console logs, JUnit, SARIF, audit JSON, or
an immutable CI run URL. The outcomes below are therefore historical
observations recorded in this report, not independently verifiable artifacts.
A rerun of the final remediation revision must publish the named report files
as protected CI artifacts and link them from the replacement audit.

Reproduction environment recorded during the 2026-07-27 audit/remediation
session: `uv 0.11.28`, `Python 3.12.13`, `pip-audit 2.10.0`,
`pnpm 11.9.0`, `Node v24.18.0`, and `Docker 29.6.1`. Inputs were repository
revision `7effabf91f8012982a816d807ab9df93b9aece85`,
[`backend/uv.lock`](../../backend/uv.lock) Git blob
`b3fffc26733898cb198f3e59c4bf45f10d7fbb67`,
[`frontend/pnpm-lock.yaml`](../../frontend/pnpm-lock.yaml) Git blob
`07da41f509e05d05494cd9aa87a13514273090e1`, and
[`frontend/pnpm-workspace.yaml`](../../frontend/pnpm-workspace.yaml) Git blob
`68c2ed83f7a0a1c5106b930e2d3f0b763fc4ea5f`. The reviewed
[CI workflow](../../.github/workflows/ci.yml) blob was
`3827a75c081d91974aa0bc88f3fc241383c64069`.

| Check | Exact baseline command / selector | Recorded outcome | Required retained report on rerun |
| --- | --- | --- | --- |
| Python locked dependency audit | `cd backend && uv export --frozen --no-emit-project --format requirements.txt -o requirements-audit.txt && uvx pip-audit==2.10.0 --strict -r requirements-audit.txt` | No known vulnerability reported. | `pip-audit.json` plus the exported requirements file |
| Frontend production dependency audit | `cd frontend && pnpm audit --prod --audit-level high` | No known vulnerability reported. | `pnpm-audit-production.json` |
| Full frontend dependency audit | `cd frontend && pnpm audit --audit-level high` | One High development-only advisory: `brace-expansion <=5.0.7`, [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg). | `pnpm-audit-full.json` |
| pnpm package trust/signatures | `cd frontend && pnpm install --frozen-lockfile` with the checked-in `trustPolicy` | 774 of 774 entries passed the configured supply-chain policy. | Complete install log and pnpm store/lock integrity summary |
| Frontend API/auth/session tests | `cd frontend && pnpm test -- "app/(auth)/login/page.test.tsx" "app/(auth)/register/page.test.tsx" components/auth/oauth-buttons.test.tsx lib/api/client.test.ts lib/api/query-client.test.ts lib/auth/session-guard.test.tsx lib/auth/use-auth-mutation.test.tsx components/marketing/landing-session-redirect.test.tsx` | 56 passed. | `frontend-security-junit.xml` |
| Backend security/health broader selection | `cd backend && uv run pytest tests/component/test_auth_api.py tests/component/test_oauth_api.py tests/component/test_integrations_oauth_api.py tests/component/test_health.py tests/unit/test_workspace_auth.py tests/unit/test_oauth_state.py tests/unit/test_oauth_config.py tests/unit/test_integrations_oauth.py tests/unit/test_web_fetcher.py tests/unit/test_web_fetcher_escalation.py tests/unit/test_referral_sanitize.py tests/unit/test_order_sanitize.py tests/unit/test_billing.py -q` | 185 passed; a separately selected security/health rerun recorded 148 passed. The exact narrower 148-test selector was not retained and must not be inferred. | `backend-security-junit.xml` for each explicitly named selector |
| PostgreSQL queue/claim/lease tests | `cd backend && uv run pytest tests/component/test_audit_queue.py tests/component/test_integration_queue.py tests/component/test_analytics_queue.py tests/component/test_task_queue_content.py tests/component/test_site_health_queue.py -q` against PostgreSQL 16 | 31 passed. | `backend-queue-junit.xml` and PostgreSQL server version output |

Passing tests demonstrate the exercised contracts; they do not replace a live
penetration test or production failure drill.

## Threat model and data classification

The review considered an anonymous internet attacker, a malicious or compromised
tenant member, cross-workspace object-ID probing, credential stuffing and cost
abuse, hostile prompt/provider/crawl content, OAuth or webhook forgery, dependency
and CI compromise, operator misconfiguration, leaked backups/logs, and ordinary
task/AZ/region failures. The principal trust boundaries are browser → CloudFront
→ Next.js, Next.js → private FastAPI, API/workers → PostgreSQL, and
API/workers → third-party providers or arbitrary public crawl targets.

| Class                        | CiteLadder examples                                                                                                      | Required handling                                                                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Restricted secrets           | Password hashes, JWT signing key, Fernet key, BYOK keys, OAuth refresh/access tokens, provider and Razorpay secrets     | Never return/log; least-privilege runtime access; application encryption where designed; KMS-encrypted secret/backup storage; versioned rotation and audited recovery |
| Confidential tenant data     | Brands, competitors, prompts, raw answer artifacts, citations, products, crawl evidence, integrations, metrics, exports | Workspace authorization on every query; no shared caching; encryption in transit/at rest; retention/erasure policy; access audit                                      |
| Personal/commercial data     | Account email, billing country/account state, sanitized referral/order facts and pseudonymous hashes                    | Data minimization; approved purpose/retention; subject/account deletion process; restricted logs and support access                                                   |
| Security-sensitive telemetry | IPs, request IDs, OAuth callback queries, WAF/ALB/CloudFront logs, provider error metadata                              | Redaction, access control, bounded retention, incident preservation procedure                                                                                         |
| Public                       | Marketing pages, deliberately public billing/provider catalog metadata, liveness response                               | Explicitly separated cache and response policy; no secret/config leakage                                                                                              |

## Existing controls that should be preserved

1. **Tenant authorization:** project-owned routes consistently resolve access
   through `require_active_workspace` or verified workspace membership. The
   dependency returns 404 for non-members to avoid resource enumeration
   (`backend/app/api/deps.py:84-138`).
2. **Secret storage:** BYOK provider keys and integration tokens are
   Fernet-encrypted; response models expose status/metadata rather than secret
   values (`backend/app/core/security.py:169-184`).
3. **Session confidentiality:** the JWT is placed in an HttpOnly cookie, with
   `Secure` enabled outside local environments and `SameSite=Lax`
   (`backend/app/api/auth.py:33-50`).
4. **Passwords:** passwords are length-bounded and hashed with Argon2
   (`backend/app/domain/auth/schemas.py:10-14`,
   `backend/app/core/security.py:21-47`).
5. **SSRF resistance:** the crawler rejects non-HTTP(S), user-info, private,
   loopback, link-local, IPv4-mapped, and cloud-metadata destinations, and binds
   requests to validated DNS results. Response bodies, redirects, sitemaps, and
   parsed text are bounded.
6. **Webhook integrity:** Razorpay processing verifies HMAC over the unchanged
   raw body, uses constant-time comparison, deduplicates event IDs, and bounds
   the body at 256 KiB (`backend/app/core/config/billing.py:184-201`).
7. **Queue correctness:** workers claim with PostgreSQL `FOR UPDATE SKIP LOCKED`,
   commit before network I/O, heartbeat leases, and reclaim expired work.
8. **Evidence integrity:** raw response artifacts and execution evidence follow
   single-writer/append-only patterns; derived rows carry analyzer provenance.
9. **Provider-data minimization:** connector errors avoid tokens and raw
   credentials; Shopify/referral sanitizers remove or hash PII-adjacent data
   before persistence.
10. **Container user:** the backend runtime uses an unprivileged UID
    (`infra/docker/Dockerfile:23-26`).

## Baseline findings summary (open at `7effabf`)

| ID       | Severity | Finding                                                                                    | Public-launch gate               |
| -------- | -------- | ------------------------------------------------------------------------------------------ | -------------------------------- |
| SEC-H01  | High     | Tenant-controlled provider endpoints permit SSRF and forwarding of stored BYOK credentials | Yes                              |
| SEC-H02  | High     | No application rate limiting, cost quotas, or tenant-fair queue scheduling                 | Yes                              |
| SEC-H03  | High     | Logout and account-switch cache handling can preserve or expose the wrong session state    | Yes                              |
| SEC-H04  | High     | Authenticated responses lack authoritative no-store cache policy                           | Yes                              |
| SEC-H05  | High     | Request bodies and CSV imports can be read/parsed without an early byte bound              | Yes                              |
| SEC-H06  | High     | Production accepts trivially weak JWT, encryption, and HMAC secrets                        | Yes                              |
| OPS-H01  | High     | The mutable `0001_initial` migration is unsafe after first production launch               | Yes                              |
| OPS-H02  | High     | Production images are incomplete and not reproducible from locks                           | Yes                              |
| OPS-H03  | High     | No AWS IaC, deploy/rollback pipeline, or tested recovery system exists                     | Yes                              |
| OPS-H04  | High     | Per-process database pools can exhaust RDS as services scale                               | Yes                              |
| SEC-M01  | Medium   | Cookie mutations rely on SameSite without explicit CSRF/origin enforcement                 | Before public launch             |
| SEC-M02  | Medium   | Security headers and trusted proxy/host validation are absent                              | Before public launch             |
| SEC-M03  | Medium   | Audit CSV export permits spreadsheet formula injection                                     | Before customer exports          |
| SEC-M04  | Medium   | JWT/session lifecycle lacks server-side revocation and account recovery controls           | Before material customer use     |
| SEC-M05  | Medium   | Application encryption and HMAC secrets have no versioned rotation path                    | Before first key rotation        |
| SEC-M06  | Medium   | OAuth callback origin and query logging are fragile behind proxies                         | Before integrations are enabled  |
| SEC-M07  | Medium   | Workspace roles are stored but not enforced for privileged operations                      | Before multi-member workspaces   |
| SEC-M08  | Medium   | Credential-bearing HTTP clients inherit ambient proxy configuration                        | Before production                |
| OPS-M01  | Medium   | Health, graceful draining, worker heartbeats, and SSE keepalives are incomplete            | Before production                |
| OPS-M02  | Medium   | Database TLS, runtime roles, and query timeouts are not enforced                           | Before production                |
| OPS-M03  | Medium   | Provider/crawler pacing is process-local, constraining safe horizontal scaling             | Before worker autoscaling        |
| DATA-M01 | Medium   | General retention, erasure, and large-artifact lifecycle are incomplete                    | Before customer data             |
| CI-M01   | Medium   | CI has security blind spots; the secret scan likely cannot fail on a new secret            | Before protected deployments     |
| DEP-M01  | Low      | Development dependency has one High DoS advisory                                           | Next dependency update           |
| BIZ-M01  | Medium   | Billing, legal, support, and launch content are unfinished                                 | Before charging/public marketing |
| SEC-L01  | Low      | Production debug/reference surfaces and trusted provider configuration need hardening      | Before production                |
| DOC-L01  | Low      | Container operations documentation omits four required processes                           | Before operator handoff          |

## Detailed findings

### SEC-H01 — Tenant-controlled provider endpoints can receive stored BYOK keys

**Observation.** A workspace member may create or update an answer-engine
connection with any HTTPS URL and may use plain HTTP for `localhost`,
`127.0.0.1`, or `::1` (`backend/app/domain/providers/schemas.py:18-42`,
`73-93`). Updating only `base_url` preserves the existing encrypted API key
(`backend/app/domain/providers/service.py:171-195`). Connection tests and audit
execution decrypt that stored key and pass it to the adapter; OpenAI sends an
`Authorization: Bearer` header, Anthropic sends `x-api-key`, and Google sends
`x-goog-api-key` to the configured URL
(`backend/app/domain/providers/service.py:262-267`,
`backend/app/connectors/answer_engines/openai.py:104-120`,
`backend/app/connectors/answer_engines/anthropic.py:127-145`,
`backend/app/connectors/answer_engines/gemini.py:101-118`). The provider routes
require workspace membership but no privileged role
(`backend/app/api/provider_connections.py:46-147`).

**Impact.** A malicious or compromised member can point a shared connection at
an attacker-controlled HTTPS server and receive another member's previously
stored provider key. Loopback and DNS-to-private destinations also create a
server-side request path into the ECS task/VPC. TLS and a web scheme do not make
an arbitrary destination trustworthy.

**Required action.** In hosted production, default to the exact cataloged
provider endpoints. If customer gateways remain a feature:

- require workspace owner/admin permission and fresh API-key entry whenever the
  endpoint changes;
- maintain an operator-approved per-provider gateway allowlist or verify domain
  ownership before use;
- reject loopback, private, link-local, multicast, reserved, and cloud-metadata
  IPs after every DNS resolution, pin the validated address, and revalidate any
  redirect before following it;
- require HTTPS with normal hostname/certificate validation and keep redirects
  disabled unless the redirect policy is explicitly safe;
- log only destination class/host and decision, never the credential or full
  sensitive URL.

WAF is an inbound control and does not solve this outbound credential leak.

**Verification.** Test public attacker endpoints, localhost, IPv4/IPv6 private
ranges, metadata addresses, DNS rebinding, redirects to private hosts, mixed DNS
answers, endpoint change without key re-entry, and member-versus-owner access.
Assert no request containing a stored credential leaves for an unapproved host.

### SEC-H02 — No application rate limiting, cost quotas, or queue fairness

**Observation.** Registration and login perform database work and Argon2 hashing
without a rate limiter (`backend/app/api/auth.py:53-94`). There is no limiter
middleware in the application factory (`backend/app/main.py:103-135`). Anonymous
registration can create users, workspaces, and billing rows. Application-funded
prompt suggestions/content generation, connection tests, imports, and other
expensive mutations do not share a durable per-account cost budget.
The generic queue orders globally by priority and creation time rather than
allocating fair capacity between workspaces
(`backend/app/orchestration/postgres_task_queue.py:86-137`).

**Impact.** An attacker can consume CPU, database storage/connections, outbound
provider quota, and money. IP-only edge limits do not address distributed abuse
or an authenticated tenant deliberately exhausting an application key.

**Required action.** Apply layered controls:

- AWS WAF rate rules for `/auth/login`, `/auth/register`, imports, provider tests,
  audit creation, generation, and billing mutations;
- application limits by normalized account/email, workspace, capability, and
  operation, stored durably in PostgreSQL or another approved shared mechanism;
- concurrency, daily/monthly usage, and estimated-cost ceilings for every
  application-funded provider;
- active-job limits and tenant-fair queue scheduling so one workspace cannot
  monopolize workers;
- uniform `429` responses with `Retry-After`, bounded registration, and alerts
  on authentication/provider abuse.

Do not introduce Redis solely for this; the product invariant is a PostgreSQL
queue and no Redis dependency.

**Verification.** Test burst, sustained, distributed-IP, concurrent, and
multi-task cases. Confirm limits remain correct across two API tasks and after a
restart, and that signed webhooks are not challenged or dropped.

### SEC-H03 — Unsafe logout and account transition handling

**Observation.** The menu calls `clearSession()` in `onSettled`, including when
the logout request fails (`frontend/components/layout/user-menu.tsx:31-34`).
That clears browser state, but the backend's 24-hour HttpOnly cookie is deleted
only when the request reaches `/auth/logout` successfully
(`backend/app/api/auth.py:41-50`, `97-101`). The login/register success handler
then writes the new `auth/me` value without first clearing the previous user's
QueryClient data (`frontend/lib/auth/use-auth-mutation.ts:25-39`). Query keys such
as `['projects', 'list']` are not user-qualified
(`frontend/lib/api/query-keys/core.ts:3-17`), and the active project ID persists
in local storage (`frontend/lib/project/project-context.tsx:26-50`).

**Impact.** A failed logout can leave the server session active after the UI says
the user is signed out. Subsequent account switching in the same browser can
briefly render or reuse account A's cached workspace data under account B's UI.

**Required action.** Only report logout success after the server confirms cookie
deletion. On failure, keep the authenticated state visible and offer retry. On
every successful login/register and confirmed logout, cancel in-flight queries,
clear the whole QueryClient, reset the active workspace header, remove
account-scoped local storage, then seed the new session and fetch fresh projects.
Add a server-side revocation mechanism as described in SEC-M04.

**Verification.** Add tests for failed/offline logout, an in-flight request during
logout, A → logout → B, A → failed logout, cookie expiry, and two tabs. Assert no
account-A response can render after account B authenticates.

### SEC-H04 — Missing authoritative cache isolation

**Observation.** The frontend sends `cache: 'no-store'` on API fetches
(`frontend/lib/api/client.ts:88-93`), which protects the browser fetch path.
FastAPI does not, however, set `Cache-Control: private, no-store` globally on
authenticated responses, JSON, exports, or errors. Several export responses set
only content type/disposition; the application middleware only adds a request ID
(`backend/app/main.py:116-128`).

**Impact.** A future CloudFront, reverse-proxy, or browser policy error could
cache cookie-authenticated workspace data and serve it to another user. Exports
are especially sensitive because their URLs are stable and contain customer
evidence.

**Required action.** Add backend defense-in-depth headers to all authenticated
responses and downloads: `Cache-Control: private, no-store, max-age=0` and
`Pragma: no-cache` where legacy clients matter. Keep truly public catalog/health
responses on an explicit separate policy. Configure CloudFront `/api/*` with the
managed `CachingDisabled` policy, all TTLs zero, and forwarding of all required
cookies, query strings, and workspace/idempotency/SSE headers. Never route
`/api/*` to a cache-enabled behavior.

**Verification.** Inspect responses through CloudFront, repeat identical URLs as
two users/workspaces, verify `Age` is absent/zero and `x-cache` never reports a
hit, and test exports and 4xx/5xx responses as well as JSON.

### SEC-H05 — Unbounded request and import parsing

**Observation.** Prompt and product imports call `UploadFile.read()` or
`Request.body()` without a byte limit before decoding and parsing
(`backend/app/api/prompts.py:265-285`,
`backend/app/api/products.py:194-221`). Product imports reject more than 500 rows
only after the complete file has been read and parsed
(`backend/app/domain/products/service.py:186-190`). Prompt imports have no row
cap, `PromptImport.prompts` has no list cap, and prompt text has no maximum length
(`backend/app/domain/prompts/schemas.py:27-40`, `60-68`).

**Impact.** An authenticated user can cause large memory allocations, long CSV
parsing/validation transactions, database growth, and task amplification. A
small number of concurrent requests can exhaust an API task.

**Required action.** Enforce a global request-body ceiling and smaller per-route
ceilings before buffering. Stream uploads in bounded chunks, reject oversized
`Content-Length` early, stop chunked reads at `limit + 1`, cap rows/columns/cell
lengths, cap JSON list lengths in schemas, and add prompt-text length limits.
Return `413` for bytes and `422` for shape/count violations. Set matching edge
rules without relying on WAF's partial body inspection as the only control.

**Verification.** Test declared and chunked oversized bodies, multipart/raw/JSON
paths, huge fields, many empty rows, many columns, concurrent requests, and a
valid request exactly at each limit.

### SEC-H06 — Weak production secret validation

**Observation.** JWT, encryption, referral/order HMAC, and database secret
settings have no minimum length or entropy constraint
(`backend/app/core/config/__init__.py:55-80`, `126-139`). Startup rejects only a
small set of exact placeholder values
(`backend/app/core/config/__init__.py:206-229`), so values such as `x` pass in
production. The JWT algorithm is also environment-selectable instead of fixed to
one reviewed algorithm (`backend/app/core/config/__init__.py:60-63`).

**Impact.** A weak JWT key permits offline guessing and session forgery; a weak
encryption key permits recovery of every stored BYOK/OAuth credential after a
database leak. Weak HMAC salts undermine pseudonymization. Startup currently
provides false assurance that non-default means strong.

**Required action.** Validate production secret length/entropy and independence
at startup, pin the approved JWT algorithm in code/config policy, generate
separate random values through Secrets Manager/KMS, and refuse to start on any
weak, duplicated, missing, or development-only value. Use at least 256 bits of
random material for signing/encryption secrets and an approved policy for HMAC
keys. Keep the versioning/rotation work in SEC-M05.

**Verification.** Add production-settings tests for empty, one-character,
dictionary-like, duplicated, placeholder, wrong-algorithm, valid-current, and
active+previous key configurations. Confirm secret values never appear in the
exception or logs.

### OPS-H01 — Mutable bootstrap migration

**Observation.** `0001_initial` imports the live ORM metadata and calls
`Base.metadata.create_all()` (`migrations/versions/0001_initial.py:24`, `33-34`).
The file explicitly assumes databases can be dropped/recreated while the product
is pre-production (`migrations/versions/0001_initial.py:7-14`).

**Impact.** After production records `0001_initial` as applied, changing models
changes what a fresh database receives but does nothing to an existing database.
Environments silently diverge and rollback/recovery becomes unpredictable.

**Required action.** Before the first production database, freeze a deterministic
`0001_initial` containing explicit operations. From that point onward, never
edit an applied revision; use additive, reviewed Alembic revisions and an
expand/migrate/contract rollout. CI must create both a fresh database and upgrade
a copy of the prior schema. Migrations run exactly once using a separate
DDL-capable role.

**Verification.** Prove fresh install, prior-version upgrade, application
compatibility before/after migration, backup restore plus upgrade, and forward
rollback to the previous image without automatically downgrading schema.

### OPS-H02 — Non-reproducible and incomplete runtime artifacts

**Observation.** CI installs from `uv.lock`, but the backend image copies only
`pyproject.toml` and runs mutable `pip install .`
(`infra/docker/Dockerfile:15-17`). Its base image uses a mutable tag, and build
tools remain in the runtime. All builds send the repository root as context
(`infra/docker/docker-compose.yml:41-43`), while no root `.dockerignore` exists;
the context can include ignored `.env` files, `.git`, `node_modules`, and local
artifacts. There is no production frontend image, `output: 'standalone'`, or
frontend health endpoint. `BACKEND_ORIGIN` silently falls back to localhost
(`frontend/next.config.ts:20`). `APP_ENV` also defaults to development
(`backend/app/core/config/__init__.py:39-42`); if omitted, the session cookie is
not marked Secure and insecure default secrets warn instead of stopping startup
(`backend/app/api/auth.py:33-38`,
`backend/app/core/config/__init__.py:206-230`).

**Impact.** Deployed dependencies can differ from tested dependencies. Build
contexts can leak local secrets to the builder/cache. Images are larger and
contain unnecessary attack surface. The frontend can build successfully yet
proxy production traffic to itself/localhost.

**Required action.** Add a root `.dockerignore`; build a multi-stage backend
image from `uv.lock` with `uv sync --frozen --no-dev`; pin base images by digest;
remove compilers from the final non-root image; create a multi-stage Next.js
standalone image; and make a production build fail if `BACKEND_ORIGIN` is absent
or loopback. Make production startup fail unless an explicit production
environment and canonical origins are present. Generate an SBOM, scan and sign
both images, and deploy immutable digests.

**Verification.** Rebuild twice from the same revision, compare dependency/SBOM
graphs, inspect image contents and user, assert no `.env`/Git/dev files exist,
scan images, and smoke-test the proxy and health endpoints in ECS.

### OPS-H03 — No production infrastructure or recovery implementation

**Observation.** The repository has local Docker Compose and code-test CI, but no
AWS IaC, ECR publication, deployment workflow, rollback automation, production
alarms, backup policy, restore drill, disaster-recovery target, or frontend
runtime artifact. Existing architecture prose primarily targets Vercel/Railway.

**Impact.** Manual configuration drift, over-privileged access, unrepeatable
deployments, missed worker processes, and untested recovery can turn an ordinary
release or AWS failure into prolonged outage or data loss.

**Required action.** Implement the linked [AWS hosting
runbook](aws-hosting-runbook.md) as environment-isolated IaC. Establish GitHub
OIDC deployment, one-off migrations, deployment circuit breakers, image-digest
promotion, monitoring, PITR, cross-account backup, tested restore, and named
RPO/RTO/on-call owners.

**Verification.** Recreate staging from IaC, deploy from a clean runner, roll back
an intentionally unhealthy release, fail an AZ, restore into a clean database,
and execute the regional recovery checklist while measuring actual RPO/RTO.

### OPS-H04 — Database pools multiply across every process

**Observation.** Every non-SQLite process receives `DB_POOL_SIZE=8` plus
`DB_MAX_OVERFLOW=12` (`backend/app/core/config/__init__.py:141-165`,
`backend/app/core/database.py:20-39`). The production topology has the API plus
six DB-using worker/dispatcher types; two API tasks and one of each worker can
therefore permit roughly 160 connections before a migration task, monitoring,
deploy overlap, or autoscaling.

**Impact.** A modest RDS instance can be saturated immediately or during a
rolling deployment. Pool storms turn provider latency or a database failover
into API timeouts, lease-heartbeat failures, and cascading restarts.

**Required action.** Set separate pool/overflow values for each ECS task family,
reserve maintenance/migration headroom, and keep the total below 70–80% of the
tested RDS ceiling. Add connection, checkout, statement, lock, and
idle-in-transaction timeouts; pause nonessential workers before the reserve is
consumed. Load-test asyncpg through RDS Proxy before using it and keep migrations
on a direct connection.

**Verification.** Exercise peak API and all workers during a rolling deployment,
provider slowdown, RDS failover, and connection leak. Prove connection alarms,
backpressure, recovery, and reserved admin/migrator access work at the selected
RDS size.

### SEC-M01 — Explicit CSRF/origin enforcement is absent

The session cookie uses `SameSite=Lax`, a valuable baseline, but unsafe methods
do not validate `Origin`, `Sec-Fetch-Site`, or a CSRF token. SameSite does not
protect against a compromised same-site sibling, future cookie-policy changes,
or every login/navigation edge case. Require an exact canonical origin and
Fetch Metadata policy for cookie-authenticated unsafe methods, or add a robust
CSRF token. Exempt only endpoints with independent verification, such as the
signed Razorpay webhook and validated OAuth callbacks. Test missing, `null`,
cross-origin, sibling-subdomain, and valid same-origin requests.

### SEC-M02 — Browser headers and proxy/host trust are not hardened

Neither Next.js nor FastAPI defines a production CSP, HSTS, frame policy,
`nosniff`, referrer policy, or permissions policy. FastAPI also lacks
`TrustedHostMiddleware` and an explicit trusted-proxy contract. CORS allows all
methods/headers for configured origins (`backend/app/main.py:108-114`), even
though production traffic should be same-origin and the API private. Add headers
at Next.js/CloudFront with a report-only CSP rollout, restrict frame ancestors,
validate public hosts, trust forwarded headers only from the ALB/frontend path,
and minimize or disable production CORS. Test redirects and absolute URLs behind
CloudFront → ALB → Next.js → FastAPI.

### SEC-M03 — Audit CSV formula injection

`audit_to_csv` writes prompt text, search queries, domains, provider-derived
values, and errors directly (`backend/app/analysis/exports.py:57-102`). A shared
`csv_cell()` helper already neutralizes leading `=`, `+`, `-`, `@`, tab, CR, and
LF for other exporters (`backend/app/analysis/csv_cells.py:30-54`). Apply the
shared helper to every audit cell, including JSON-joined values, and add tests
for whitespace/control-prefixed formulas. Until fixed, warn operators not to
open untrusted exports in a spreadsheet.

### SEC-M04 — Incomplete session and account lifecycle

JWTs contain a `ver` claim, but `get_current_user` does not compare it with a
stored user token version (`backend/app/core/security.py:50-71`,
`backend/app/api/deps.py:39-64`). Logout is cookie deletion only, so a copied JWT
remains valid for up to 24 hours. There is no email verification, password reset,
MFA, session/device list, or account-wide revocation. Add a persisted token
version or hashed session/JTI registry, revoke on password/security events,
rotate sessions, add `iat`/`iss`/`aud`/`jti` validation, consider a host-only
`__Host-` cookie name, shorten idle/absolute lifetimes, and implement verified
account recovery before storing material customer data. Keep login errors
generic; also decide whether registration should reveal an existing email.

### SEC-M05 — No versioned encryption/HMAC key rotation

All Fernet ciphertext derives from one `ENCRYPTION_KEY`; ciphertext carries no
application key ID (`backend/app/core/security.py:169-184`). Changing that secret
makes existing BYOK and OAuth tokens unreadable. Referral/order HMAC salts have
the same single-version lifecycle. Initially protect secrets with Secrets
Manager and KMS, but implement version-tagged ciphertext/keyrings or KMS envelope
encryption before rotation. SEC-H06 covers initial strength; this finding covers
safe change over time. Test active+previous read, online rewrap, rollback, backup
restore with historical key versions, and permanent old-key retirement.

### SEC-M06 — OAuth callback origin and query-secret handling

Integration redirect URIs are derived from `request.base_url`
(`backend/app/api/integrations.py:103-106`), so a proxy/host mistake can produce
the wrong registered URI or host-sensitive flow. Authorization `code` and
`state` arrive in the query string (`backend/app/api/integrations.py:172-203`)
and can appear in Uvicorn, ALB, CloudFront, WAF samples, browser history, or
support telemetry. Use a configured canonical public callback base, strict host
validation, short-lived single-use state, and log redaction/short retention for
query-bearing paths. The separate login OAuth callback deliberately returns 501
(`backend/app/api/oauth.py:90-103`); keep every `OAUTH_*_ENABLED` flag false until
that flow is implemented and security-tested.

### SEC-M07 — Workspace roles do not authorize privileged operations

`WorkspaceMember` stores a role (`backend/app/models/workspace.py:35-60`), but
the shared dependencies verify membership only (`backend/app/api/deps.py:84-138`).
Provider credential CRUD/test, integrations, destructive project actions, and
expensive enqueues generally receive the same authority from any member. This is
not a cross-workspace bypass, but it becomes a privilege-escalation boundary as
soon as collaborators are supported and it amplifies SEC-H01. Define and enforce
an owner/admin/member/viewer capability matrix. Require step-up or fresh secret
entry for credential/endpoint changes and tests for every role on sensitive,
destructive, billing-adjacent, export, and cost-bearing routes.

### SEC-M08 — Credential-bearing clients inherit ambient proxies

The pooled answer-engine and billing clients, OAuth client, and several
integration/discovery clients construct `httpx.AsyncClient` without
`trust_env=False` (for example,
`backend/app/connectors/answer_engines/http_client.py:54-63`,
`backend/app/connectors/billing/http_client.py:17-28`, and
`backend/app/connectors/integrations/oauth.py:201-205`). They therefore honor
ambient `HTTP_PROXY`/`HTTPS_PROXY`/CA environment settings and may send provider
keys, OAuth codes/tokens, or billing credentials through an unintended proxy.
The crawler already disables ambient proxy inheritance. Set `trust_env=False`
on every credential-bearing client and use a separately reviewed explicit proxy
configuration only when required. Add a test with hostile proxy environment
variables proving no connection or credential reaches the proxy.

### OPS-M01 — Weak health, draining, and long-lived connection signals

`/health` always returns static success without testing database or migration
compatibility (`backend/app/main.py:130-132`). Worker container health checks are
disabled (`infra/docker/docker-compose.yml:95-195`), and most workers enter
infinite loops without an explicit SIGTERM drain protocol. SSE loops emit no
periodic keepalive while idle. Add separate liveness/readiness endpoints, worker
heartbeat/queue-age metrics, graceful stop-claim/drain logic, bounded ECS stop
timeouts, and 10–15 second SSE comments. Verify DB outage behavior avoids restart
storms and that deploys do not duplicate or abandon provider calls.

### OPS-M02 — Database transport, roles, and query limits are not enforced

`DATABASE_URL` accepts a non-TLS default
(`backend/app/core/config/__init__.py:136-140`), and the engine config sets pool
behavior but no application statement, lock, or idle-transaction timeout
(`backend/app/core/database.py:20-39`). Require verified RDS TLS and
`rds.force_ssl`, separate least-privilege runtime and DDL-only migrator roles,
and production parameter/session limits for runaway or blocked queries. Test CA
failure, hostname mismatch, long query, lock wait, idle transaction, and runtime
attempted DDL.

### OPS-M03 — Process-local external pacing

The PostgreSQL queue prevents duplicate claims, but provider pacing and crawler
per-host delay/concurrency are maintained inside each worker process. Multiple
replicas multiply the effective rate and politeness limit. Launch each external
I/O worker at one replica, especially Site Health and audit, and prohibit worker
autoscaling until a distributed PostgreSQL-backed limiter/advisory-lock design is
tested. Keep the integration dispatcher at exactly one owner or replace it with
EventBridge Scheduler plus a database lock.

### DATA-M01 — Incomplete retention, erasure, and artifact lifecycle

Targeted referral and sanitized-order retention exists, but there is no general
account/workspace deletion workflow, verified cascading erasure job, or defined
retention schedule for raw answer artifacts, prompts, crawls, integrations,
exports, logs, and backups. Some provider artifacts remain inline in PostgreSQL,
increasing WAL and backup growth. Define a data inventory, lawful purpose,
retention/deletion periods, export/erasure workflow, backup-expiry behavior, and
audit evidence. Move large immutable payloads to versioned SSE-KMS S3 when volume
justifies it while preserving artifact provenance and workspace authorization.

### CI-M01 — Security pipeline gaps and ineffective secret gate

CI runs tests, lint, a Python dependency audit, and `detect-secrets`, but no
frontend advisory gate, image/IaC scan, SBOM/signature verification, migration
upgrade test, end-to-end security smoke test, or coverage threshold. Actions use
mutable major tags. More importantly, `detect-secrets scan --baseline
.secrets.baseline` updates the baseline and exits successfully; the command at
`.github/workflows/ci.yml:92-95` is therefore likely unable to fail a PR merely
because a new secret was found. Use `detect-secrets-hook --baseline` against
tracked changed files or compare a fresh scan with the reviewed baseline. Pin
actions by full commit SHA and add SAST, dependency-update automation, `pnpm
audit --prod`, container/IaC scanning, SBOM generation, signing, and protected
environment approvals.

### DEP-M01 — Development-only `brace-expansion` advisory

The production frontend dependency audit is clean. The full graph includes
`brace-expansion <=5.0.7` through ESLint/minimatch, vulnerable to unbounded
expansion and process OOM. It is not shipped in the production bundle, so direct
runtime exposure is low. Upgrade the lock graph to `>=5.0.8`, rerun lint/tests,
and keep production and full-graph audits as separate CI gates.

### BIZ-M01 — Commercial and public-launch prerequisites

Checkout is correctly disabled by default, but it must remain disabled until the
[Razorpay owner checklist](razorpay-and-demo-owner-requirements.md) is completed.
Privacy, terms, refund/support processes, and approved data-processing language
are not published. Public comparison/pricing/blog surfaces still contain
`[TODO(user)]`, and a visibility help link uses `citeladder.example`. Complete
legal/accounting review, merchant KYC and sandbox lifecycle tests, incident and
support ownership, real contact/legal links, and removal of launch placeholders
before public indexing or charging customers.

### SEC-L01 — Production reference and trusted-provider configuration

FastAPI enables `/docs`, `/redoc`, and `/openapi.json` by default. The proposed
private backend makes them unreachable from the public origin, but production
should still disable them or require an explicit internal access path. Razorpay's
API base URL is environment-configurable (`backend/app/core/config/billing.py:190`);
pin it to the exact approved HTTPS origin in production, as should every other
operator-controlled credential-bearing endpoint. These are lower-risk because
they require deployment access, but startup validation should make the trusted
destinations explicit.

### DOC-L01 — Operations documentation drift

`infra/docker/README.md` lists only the API, audit worker, and content worker,
while Compose also requires Site Health, analytics, integration worker, and the
integration dispatcher. Update operator-facing service inventory so a seemingly
healthy deployment cannot leave queues permanently unprocessed.

## Production gates

### Required before controlled staging

- [ ] Use unique, non-default JWT, encryption, HMAC, database, and provider
      secrets from a secret manager; keep live billing and login OAuth disabled.
- [ ] Disable custom provider base URLs or enforce the approved-host, IP, role,
      and fresh-key controls in SEC-H01.
- [ ] Disable CloudFront caching for `/api/*` and verify cookie/header forwarding.
- [ ] Freeze the migration bootstrap and exercise fresh install plus upgrade.
- [ ] Build frontend/backend from locked, non-root, secret-excluding contexts.
- [ ] Apply coarse WAF rate limits and request-size protections.
- [ ] Use synthetic/non-sensitive data and separate staging provider accounts.

### Required before private pilot

- [ ] Close SEC-H01 through SEC-H06 and OPS-H01 through OPS-H04.
- [ ] Add CSP/security headers, origin/CSRF validation, and trusted host/proxy rules.
- [ ] Fix CSV injection and account-switch/logout tests.
- [ ] Implement readiness, worker heartbeat, queue-age, error-rate, and cost alarms.
- [ ] Complete a deployment rollback and database+key restore drill.
- [ ] Document on-call, incident severity, customer notification, RPO, and RTO.

### Required before public production

- [ ] Close every High finding and accept/plan every Medium finding with a named
      owner and date.
- [ ] Complete an independent dynamic penetration test against staging,
      including cross-workspace/BOLA, auth abuse, CSRF, upload DoS, SSRF, OAuth,
      billing webhook, cache, and WAF testing.
- [ ] Run production-shaped concurrency, queue, provider-failure, and database
      failover tests.
- [ ] Complete legal/privacy/terms/support/refund and Razorpay launch gates.
- [ ] Verify backups, cross-account recovery material, encryption key history,
      and a measured restore.
- [ ] Obtain final engineering, security, product, finance/legal, and operations
      sign-off.

## Limitations

This was a repository audit, not a live penetration test. It did not include:

- testing a deployed AWS account, IAM policies, WAF rules, TLS, DNS, or network
  security groups because those resources do not yet exist;
- black-box fuzzing, credential stuffing, browser exploit testing, or sustained
  denial-of-service/load testing;
- direct review of third-party provider, Razorpay, GitHub, domain registrar, or
  organization account configurations;
- source review of every transitive dependency;
- legal, privacy, tax, or regulatory advice;
- proof that local/CI test databases and runners exactly match future production.

Re-run the audit after the high-severity remediations and AWS IaC land, then add
an independent staging penetration test and operational recovery exercise.
