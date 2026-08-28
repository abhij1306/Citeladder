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
- In the Compose stack, `web` is the API runtime. The frontend uses the internal
  `http://web:8000` rewrite destination, while port 8000 remains available for health checks.

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

These capabilities serve one product loop—Connect → Analyze → Act →
Improve / Verify → Track—while retaining the persistence owners below. AI
Visibility is the observed Track measurement; leading indicators never become
causal claims.

| Subsystem | Responsibility |
|---|---|
| Auth/workspaces/projects | Tenant and project boundary |
| Site Health | Discovery, secure acquisition, page kinds, rules, scores, issues, snapshots, exports |
| Content | Website-grounded generation queue, attempts, history, feedback |
| Integrations/Traffic/Analytics/Demand | GSC/Traffic evidence, snapshots, signals |
| Prompts/Audits/Visibility | Prompt portfolios and answer-engine measurement |
| Opportunities | One persisted cross-system action store |
| Commerce | Site Health-projected canonical catalog, append-only CSV/edit observations, approved competitor candidates, typed buyer prompts, frozen-audit recommendation observations, target-bound persisted AI Shelf metrics, and shared manual/scheduled audit execution |
| Growth Agent | Standalone explain/roadmap runs and append-only typed-tool attempts |

The command-center read projection is useful before the first visibility audit.
It composes Facts only from the workspace-authorized Project, BrandProfile, and
Competitor owners; exposes Connect, Analyze, Act, and Track with explicit
observed/partial/not-run/unavailable evidence states; and chooses exactly one
next action by persisted opportunity first, then connect, crawl, configure
prompts, audit, and monitor. Track returns unavailable measurement fields until
an audit exists, and the report endpoint returns not-found rather than creating
or repairing a report during a read.

BrandProfile field provenance is structured as `origin`, `review_state`,
`reviewed_by`, and `reviewed_at`. Onboarding discovery persists suggestions but
does not activate a portfolio before confirmation. Completion requires confirmed
or edited positioning, target audience, and products/services, records the
reviewer, and only then creates the bounded initial prompt portfolio exactly
once. Topics in that portfolio are reusable semantic demand clusters, not query
phrases; related prompts share a topic.

Completion is an accepted asynchronous job. The request validates and freezes
the confirmed review, claims its idempotency key, and adds a `brand_completion`
task to the existing brand-discovery PostgreSQL queue. The worker performs
provider I/O without holding the discovery row lock, then creates the project
and portfolio atomically. Retries replay the in-flight or completed discovery;
an exhausted task terminalizes it with a completion-specific failure instead
of leaving the client polling indefinitely. If project capacity changes while
generation is in flight, completion persists the occupancy code as a retryable
review state and reuses the same completion task after capacity is restored.

Onboarding discovery v8 keeps the existing bounded first-party acquisition and
adds bounded Keenable corroboration. One structured application-model call
classifies identity and emits an evidence-referenced competitive signature;
deterministic brand-neutral searches then gather the competitor research
evidence, and a second structured call reads the competitor names out of that
evidence. The bounded qualifier shares its text budget across every distinct
source so a few long fetched pages cannot hide the rest of the search pool.
Editorial, coupon, directory, and analytics results are evidence, never
candidates: their rivals are the companies named inside the text, not the
publishing domains. An official company page may establish that company itself
when its title, domain, and content match the buyer, category, and market.
Pydantic and deterministic reference
checks enforce the contracts and always run: no host is assumed to guarantee
native strict-schema output, so those checks stay in force even when the
gateway selects Mistral's verified native mode. The existing domain resolver remains the
final candidate check, so a name the model invents cannot reach the customer. Provider failures yield explicit
degraded warnings, and the immutable `BrandResearchSnapshot` records the
evidence manifest, verdicts, and per-phase model provenance without a new table
or queue. Discovery also adds one shared bounded repair seam for the two Keenable
research schemas: requests expose explicit allowed evidence IDs and validation
failures receive bounded contract feedback without response bodies or evidence
text. Retryable provider failures honor bounded backoff without weakening any
evidence-reference or hard-admission gate. The application gateway selects
Mistral's verified native strict JSON Schema mode automatically, falling back to
prompt-carried JSON-object mode for hosts without a verified guarantee.

Demand's `page_equivalence` module is the sole cross-source owned-page resolver.
It uses exact `SiteUrl` matches plus persisted redirect/canonical evidence and
returns `exact`, `resolved`, `ambiguous`, or `unresolved` with a versioned
candidate projection. Sitemap/preferred-origin signals rank but never prove a
mapping. All resolver queries are workspace- and project-scoped; large variant
sets are split into config-bounded SQL batches.

Traffic's existing `load_snapshot` resolver is exact-window when both dates are
present and explicit-latest only when they are omitted. Dashboard projections
expose `not_run`, `observed_zero`, or `available`; reads never substitute a
newer mismatched window or recompute missing state.

Demand owns the bounded query-evidence projection consumed by its detectors.
The existing post-GSC Demand queue builds it before `DemandSignal` computation
from immutable `gsc_query_page_daily` rows. `QueryEvidenceSnapshot` records the
workspace/project/exact-window identity, source hash, superseded snapshot,
coverage, limitations, source IDs, and analyzer/resolver versions;
`QueryEvidenceRow` records normalized query, observed and resolved page
identity, date, metrics, resolution evidence, and exact import provenance.
Retries reuse identical immutable snapshots, while source or version changes
append. Workspace-authorized list/summary APIs read only persisted rows, with
config-owned 100/500 pagination and 5,000-row/100-artifact build bounds. Cursors
are bound to the immutable snapshot ID. Latest-row and exact-window artifact
caps are applied in SQL before ORM materialization, and equal concurrent
snapshot inserts converge through the unique identity.

Demand query detection is split along complexity boundaries: `projection.py`
owns the baseline and branded/striking-distance separation,
`query_detectors.py` owns cannibalization, property-relative CTR gap, and
complete-daily-coverage adjacent-window trends, and `detector_source.py` performs bounded classified
input assembly. Detector states and limitations persist in the Demand snapshot
summary. `opportunities/demand_hits.py` is the sole mapping seam from the
approved actionable signal set into distinct existing Opportunity rules;
branded and ambiguous cohorts cannot cross that seam.

Demand's `query_classification` module owns deterministic branded-query
classification. Vocabulary comes from the canonical brand row, aliases, and
owned-domain spellings; results and append-only overrides carry the classifier
version. The newest override for the exact normalized query wins, with every
lookup scoped to workspace and project. Overrides are written through
`POST /api/v1/projects/{project_id}/demand/query-classification-overrides`.

Visibility-gap Opportunities carry an observed source pattern.
`opportunities/source_patterns.py` projects the citations already persisted for
a prompt into a `source_pattern` block on the existing
`brand_absent_high_value_prompt` and `owned_page_not_cited` evidence: distinct
cited domains per source class, the competitor-to-domain map, bounded
representative citations, and one deterministic next action. Classification is
identity-first — the analyzer's own `is_owned` / `matched_competitor` verdicts
win, and only the remainder is looked up in the `config/source_patterns.py`
domain tables, where an unknown domain abstains to `other_third_party`. The
block is descriptive evidence only: it never affects whether a rule fires, and
it asserts no causal link between a cited source and a recommendation. It is
versioned by `SOURCE_TAXONOMY_VERSION` beside the opportunity
`ANALYZER_VERSION`.

Opportunities owns the Act → Verify record. An
`OpportunityImplementationEvent` is an immutable, workspace-authorized user
declaration against the current opportunity snapshot, resolved owned-page
identities, optional content generation, and discriminated expected checks.
`OpportunityVerificationEvent` rows are separate append-only observations;
they never update the declaration or imply causality. The authenticated
create/list/detail routes live at
`/api/v1/projects/{project_id}/opportunities/implementation-events`, require an
idempotency key for writes, reject foreign or unresolved targets, and include
the persisted observation history in reads.

Crawl and audit terminalization enqueue `opportunity_verification` on the
existing PostgreSQL analytics queue. Its bounded, versioned executor reads
only post-boundary persisted evidence. A latest observation projects
`observed`, `verified`, or `contradicted`; without one the declaration remains
`declared`. Missing, not-applicable, or unsupported checks remain limitations.
`OpportunityStatusEvent` continues to track human workflow status only and is
never used as evidence that implementation occurred.

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

`connectors/web_evidence` is the only website acquisition boundary. Its sole
transport is SSRF-pinned `curl_cffi`, bounded by config-owned wire, decoded,
timeout, redirect, admission, and scope limits.

Site Health owns crawl, URL, task, attempt, artifact, evaluation, analysis,
issue, change snapshot, event, and export persistence. `SitePageAnalysis` is the one
page-understanding row. It stores scores, analyzer/scoring versions,
`page_kind`, classifier version/evidence, and source IDs. It is UUID-identified
and append-only; repeated analyses may reuse one immutable artifact, with one
current row per page in a crawl.

`SiteIssue` is the immutable failure-copy boundary. It freezes the catalog
description and remediation alongside rule/analyzer versions at creation;
group, detail, page, and history reads project those columns and never consult
current catalog copy for historical prose. Display labels remain the separate
current UI-label owner.

Rule evaluations and issues also freeze `finding_class` (`defect` or
`advisory`). Issue reads default to defects and expose explicit distinct-type,
occurrence, and affected-URL counts; advisory reads are opt-in. Opportunity
detection rejects advisory evidence at both its query and detector boundary.
Indexability classification uses only explicit policy, canonical, sitemap, or
robots evidence, in that order, and represents unknown intent as an uncertain
advisory.

A Site Health crawl is created only by the explicit user **Run new crawl**
action. Discovery and analysis remain durable internal phases: admitted pages
are progressively and automatically enqueued for analysis while discovery is
running, subject to the entitlement/runtime allowance frozen on that crawl.
The product control surface has no separate discovery or analysis start action.

The standard production crawl freezes a 50-page requested limit. Advanced
input and the 50,000 discovery/analysis ceilings are development-only config;
they are not a production UI contract or a throughput claim. Availability of
those development controls is separate from the frozen manual-phase lifecycle
marker. Standard user-triggered crawls never create manual phase runs and proceed to
snapshot and terminalization; starting an explicit development phase marks its
crawl as manually controlled. The internal `input_mode=auto` token describes
the standard user-triggered **Run new crawl** request; it is not a scheduled or
autonomous crawl feature. Each curl request continues to enforce the
connector's DNS, pinned-IP, redirect, robots, scope, and host-gate controls.
Sitemap observation inserts are bounded batched writes.
The default host-gate concurrency and start spacing permit at least six request
starts per second on a responsive host, while robots crawl-delay overrides
upward and observed throughput remains workload-dependent.

Worker persistence writes immutable and derived rows before completing the
canonical runtime → monitored membership → crawl → task lock sequence. The
crawl uses `FOR NO KEY UPDATE`: staged child rows already hold foreign-key key
share locks, so `FOR UPDATE` would deadlock sibling evidence transactions. The
final locks cover only ownership/liveness validation, monotonic counter updates,
and commit; a losing cancellation, entitlement, membership, or lease race rolls
the transaction back. Database serialization and deadlock retries use a
separately bounded short-jitter counter and never spend the page's acquisition
attempt budget.

Acquisition is shared, not page understanding. Discovery extracts and persists
the complete bounded normalized-facts payload once; a matching-version analysis
references that immutable discovery artifact and writes no duplicate artifact
or HTTP attempt. Analysis falls back to its own secure fetch only when no
complete current-extractor discovery artifact exists. A concurrent analysis is
deferred through the existing PostgreSQL queue until its active discovery
prerequisite commits, without recording a failure or consuming an acquisition
attempt. `SiteFetchAttempt` remains the append-only owner for bounded curl call
outcomes, and a host-level `429` cooldown prevents queued tasks from stampeding
the same host. This adds no fetch-artifact column or mutable crawl-config state.

A terminal crawl records WHY it is partial. `SiteCrawl.partial_reason` freezes
`discovery_incomplete`, `analysis_incomplete`, or both at terminalization and is
empty on every other status. A real fetch failure such as a dead link remains a
discovery shortfall. Admission exclusions and robots-denied URLs leave the
applicable analysis set, while supported documents complete as inventory-only
evidence. Reads project the reason and the client selects copy from it; it never
infers the cause from a counter.

Usable terminal Site Health evidence has one change-intelligence downstream DAG.
A conflict-safe `change_intel` task selects the immediate persisted A/B pair,
enforces root, scope, extractor, and analyzer comparability, and writes
immutable snapshot and observation rows.
`domain/site_health/terminal_refresh.py` admits verification and
Demand/Opportunity successors only after the change snapshot commits. Traffic
projects route `change -> Demand -> Opportunities`; site-only projects route
`change -> Opportunities`. Retries reuse projection and task
identities, so no successor can race or duplicate a predecessor.

The same terminal boundary independently enqueues a versioned, retryable
internal-link metric task. It constructs no durable edge graph: current page
analysis artifacts supply bounded anchor facts, and one workspace/project/crawl
scoped `SitePageLinkMetric` row per page stores counts, followable depth,
bounded neighbours, exact source artifact IDs, and extractor/formula versions.
The crawl snapshot separately freezes `complete | partial | unknown` coverage
with its formula version and reason evidence; `inventory_complete` is not used
as a completeness claim.

Link-metric completion admits a versioned `architecture` task. It reads only
persisted page analyses, immutable normalized facts, link metrics, the crawl
snapshot, and the workspace-authorized onboarding profile. One immutable
`SiteObservedArchitecture` stores page families, evidence-ordered parents,
coverage-gated archetype advisories, exact source IDs, and all relevant
versions. Its aggregated structural evaluations reuse the existing
`crawl_finalize` rule scope at weight zero; absence claims abstain unless crawl
coverage is complete. The task is retryable and cannot fail crawl
terminalization.

Those projections have one read surface each and no second writer. The
architecture route returns the newest persisted model for a crawl with its
architecture formula version, observed families, and hierarchy. It exposes no
archetype advisory block or correction mutation. The pages list
keyset-pages over `(link_metric_value, site_url_id)` when a link sort is
requested, with the sort inside the cursor fingerprint so a cursor cannot be
replayed under a different ordering. An unmeasured page reports `null`, never
`0`.

The AEO Readiness endpoint is a separate read-only projection over those same
persisted current page analyses and rule evaluations. It requires the crawl's
exact analyzer/extractor versions, maps only the 20 config-declared rule IDs
into seven presentation dimensions, and returns pass/fail/not-applicable/error
counts, expected/observed coverage, and source-analysis IDs. It persists no row,
computes no score, repairs no state, and performs no network/model work.

Its presentation contract is page-shaped rather than evaluation-shaped, because
the evaluation shape was unreadable. Each dimension carries a plain-language
description, per-rule rollups with the catalog title and remediation, the count
of distinct pages a check applied to, the count that failed at least one, and a
bounded list of failing pages that each name their own failed checks once. The
bound applies to pages and always travels beside the true failing-page total, so
a capped list is never presented as the complete one. A rule ID is provenance
here, never display copy.

Change summary, cursor-paged observation, and detail APIs are persisted reads
under `/api/v1/projects/{project_id}/site-health/changes`. Both crawl IDs are
required for an exact-pair request; omission selects the newest persisted pair.
Unavailable, non-comparable, and partial coverage remain distinct. Reads never
select source analyses, compare facts, enqueue work, or manufacture issues.

The analysis sequence is fixed:

```text
artifact -> normalized region/entity facts -> tiered page_kind assessment
  -> inject kind/evidence -> rule evaluation -> scoring -> persisted rows
```

The former industry-role, knowledge, correction, and comparison columns/tables
were removed. `page_kind` remains the generic structural classifier and drives
schema/property contracts and rule applicability. Primary-region facts exclude
chrome, non-rendered subtrees, and repeated-card contamination. Structured data
is retained as a suggestion/corroborator and never decides the kind alone. See
[`site-health.md`](site-health.md).

## Content

`ContentGeneration` and `ContentGenerationAttempt` are the queue/result owners.
The shipped runtime has no strategy, brief, context-package, validation,
revision, publication-claim, or verification rows.

`domain/content/grounding.py` is the sole grounding adapter. It builds a bounded,
versioned envelope from confirmed or edited BrandProfile fields and exact
crawl-observed fragments selected internally by `website_context.py`.
`ContentGeneration` freezes that envelope before provider I/O; message building
validates fact-to-source references, and the worker rejects provider source
markers outside the envelope. Conflicts prohibit the affected claim class.
Unavailable evidence remains a truthful ungrounded draft.

## Demand, Traffic, and visibility

Integration import artifacts are immutable. Normalized GSC/GA4 rows and Demand
snapshots preserve provider coverage, requested/available report families,
join coverage, source IDs, and formula versions. Missing permissions or data
remain unavailable rather than becoming zero.

Search Demand projects its latest snapshot as ranked GSC query/page signals with
their evidence window, honest detector states, and observed impressions,
clicks, CTR, and position. It does not
embed a duplicate AI Visibility projection. Traffic projections make chart
granularity explicit while retaining selected-window totals. AI Referrals derives
session volume and shares only from `ga4_source_medium_daily`; overlapping
referrer rows are provenance, not an additional summand. Derived referral
snapshots carry formula/analyzer versions and rebuild through an explicit worker
path, never in a read route.

Integration OAuth starts persist a one-time state row and set the signed
state's random nonce in one short-lived, HttpOnly, SameSite=Lax transaction
cookie. The callback authenticates that transaction independently of the main
login cookie: it validates the signed state, nonce cookie, provider, persisted
row, initiating active user, current workspace membership, and expiry before
any provider exchange. Consumption is atomic and committed before network I/O.
Every callback clears the transaction cookie, as do login and logout, so a
transaction cannot survive replay, a second connect attempt, or an account
switch. Invalid callbacks always redirect to Settings with
`oauth_state_invalid`; they do not expose an API authentication response.

Prompt generation, scheduled audits, provider attempts, and answer-engine
measurements use existing queue owners and immutable evidence. Visibility does
not write business truth.

Onboarding topic selection is the sole AI owner of the initial taxonomy. A
deterministic harvest reads the offering list the site already publishes -- its
departments, products, capabilities, specialties or courses -- from pages
already fetched, and the model selects and names topics from that list rather
than inventing them. Topic count follows the evidence up to a cap with no
minimum. If selection returns no topics, completion creates them from the
offerings the user explicitly confirms, preserving that wording and provenance
instead of blocking onboarding or padding with built-in categories.

Prompt generation receives those persisted UUIDs and cannot create, rename,
repair, or replace topics. One config-owned buyer-query planner freezes short
slots across buyer-stage archetypes for organic, brand-diagnostic, and
brand-versus-competitor queries. The model returns only slot ID and text; code
owns topic, cohort, buyer stage, intent, archetype, form, and count, then
deterministically validates archetype fit, topical binding, template lead-ins,
pasted positioning, and brand leakage. Onboarding and later library generation
use this same contract, and every persisted prompt records the generator and
buyer-query archetype versions. A topic that yields no usable prompt is reported
as a warning, not a failure. Later library generation remains restricted to
existing project topic IDs. See
[`visibility-prompt.md`](visibility-prompt.md) for the complete runtime
contract and model instructions.

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
- Opportunity implementation declarations and verification observations are
  append-only; deleting their owning workspace/project follows the baseline
  cascade. Nullable crawl/audit provenance survives source retention through
  `SET NULL`; a linked content generation is retained while a declaration
  references it.
- Derived data carries direct source IDs and relevant versions.
- Configuration and product policy live under `app/core/config/*`.
- PostgreSQL remains the durable queue; do not add Redis without measured need.

## Observability

Telemetry is optional and fails open. `app/core/telemetry.py` owns both the
structured-logging setup and the Pydantic Logfire wiring; nothing ships to
Logfire unless `LOGFIRE_ENABLED` is true AND `LOGFIRE_TOKEN` is set, and tests
stay local unless `LOGFIRE_ENABLED_IN_TESTS` is also set. A missing token,
missing SDK, or unavailable instrumentor degrades to the JSON stdout logs
alone — telemetry never fails an import, a test run, or a process start.

- Each runnable process configures Logfire once, under its own service name:
  `instrument_fastapi(app)` reports as `<LOGFIRE_SERVICE_NAME>-api`, and each
  worker's `instrument_worker("<role>")` reports as
  `<LOGFIRE_SERVICE_NAME>-<role>`. Compose hands every service the same
  environment block, so the role suffix has to come from the process entrypoint.
- Shared instrumentation per process: system metrics, HTTPX, SQLAlchemy (bound
  to the app engine), and a `LogfireLoggingHandler` added ALONGSIDE the
  structlog stdout handler. Database spans come from SQLAlchemy only; adding
  the asyncpg instrumentor on top would double every query span.
- HTTPX instrumentation records method, URL, status, and timing. Request and
  response bodies stay out of telemetry, so answer-engine prompts and
  completions are never shipped off-box (invariant 6).
- `LOGFIRE_BASE_URL` selects the region ingest endpoint; the write token lives
  in `.env` or the deployment secret store and is never committed.

## Verification

Use focused unit/component tests and Ruff for changed owners. Schema changes
are folded into `migrations/versions/0001_initial.py`, then verified from an
empty disposable database with `alembic upgrade head` and `alembic check`.
