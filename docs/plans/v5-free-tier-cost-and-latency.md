# Free trial, Base/Scale plans, cost, and latency implementation plan

> **Status: APPROVED DIRECTION — planning only; not yet implemented unless the repository says otherwise.** Prepared 2026-07-30.
>
> Dependencies: [`v6-account-tiers-and-india-billing.md`](v6-account-tiers-and-india-billing.md), [`v6-razorpay-production-and-enterprise-demo.md`](v6-razorpay-production-and-enterprise-demo.md), and the backend/frontend architecture and invariants. This plan supersedes older two-tier, BYOK-only Free, and editable-`0001_initial` assumptions. Existing code follows current invariants until Task 0 updates them deliberately.

## 1. Outcome and commercial contract

| Plan | Price | Audit capability |
|---|---:|---|
| **Free** | `$0` | One card-verified, Searchify-funded Model Knowledge audit: 10 prompts × ChatGPT, Claude, Gemini; no live search; mentions only; capped answers hidden |
| **Base** | `$49/month` | 10 scheduled prompts total, one project, core-three BYOK, daily reports, full answers/mentions/citations, 50 monitored URLs |
| **Scale** | `$149/month` | 20 scheduled prompts total across up to three projects, core three plus gated optional sources, Query Fanout, 250 monitored URLs |
| **Enterprise** | Custom | Custom providers, volume, retention, security, deployment, and support |

Tier values become `free | paid | bundle | enterprise`. `paid` remains the stable internal Base key; `bundle` is Scale. Existing `$49 Paid` subscriptions become Base through catalog/display mapping only—no re-checkout, price change, entitlement gap, or Razorpay plan replacement.

Prompt allowances are sponsoring-`BillingAccount` totals distributed across eligible projects. Each `prompt × provider × repetition` is one reserved execution. Scheduled runs use one repetition; manual runs consume the same quota.

## 2. Measurement profiles and credentials

Add config-owned, versioned profiles frozen into `Audit.configuration`:

| Profile | Plan | Credentials | Retrieval | User evidence |
|---|---|---|---|---|
| `free_model_knowledge` | Free | Platform core three | Disabled | Mentions only; answer hidden |
| `base_web_visibility` | Base | BYOK core three | Approved provider search | Full answers, mentions, citations |
| `scale_web_visibility` | Scale | BYOK core + enabled optional | Approved per-source search | Full evidence and supported fanout |

Freeze profile/version, entitlement/catalog revisions, `credential_source`, retrieval/output policy, trigger/schedule metadata, logical source, transport, exact model, request-policy version, output cap, and reservation status/count. Never freeze keys, card data, or brand/competitor lists.

Free uses environment-backed server-only credentials, endpoints, and cheaper approved models from `app/core/config/*` and deployment secrets. Platform keys are never tenant connections, DTO fields, logs, snapshots, or artifacts. Free sends only the prompt plus a config-owned concise-answer instruction—never brand or competitor identity—and omits search/tools.

The capped answer is stored immutably for deterministic local mention/share-of-voice scoring, but server output policy excludes it from DTOs, Runs, evidence, downloads, exports, and user-visible support paths. Strict frontend schemas reject a Free answer field. Free has no citations/query extraction and persists `no_search`.

Paid answers remain visible/exportable. Benchmark caps 768/1024/1536 per route; choose the smallest retaining at least 95% deterministic mention/citation agreement and version the change. Trends partition by profile/version plus retrieval and route/model identity. Free never joins paid trends. Base exposes 90 days, Scale 12 months, Enterprise contract-defined history; evidence remains immutably stored pending a separate retention policy.

## 3. Entitlements, quotas, and schedules

Capability profiles add project/prompt/execution limits and reset/retry rules; allowed source classes and credential modes; answer/citation/export/fanout access; manual/schedule capability; history window; Site Health/monitored URLs; and platform-funded allowance.

| Key | Display | Projects | Scheduled prompts | Providers | Fanout | History | URLs |
|---|---|---:|---:|---|---|---|---:|
| `free` | Free | Trial | None | Platform core three | `no_search` | Trial audit | 0 |
| `paid` | Base | 1 | 10 | BYOK core three | Upgrade state | 90 days | 50 |
| `bundle` | Scale | 3 | 20 | Core + released optional | Supported queries | 12 months | 250 |
| `enterprise` | Enterprise | Contract | Contract | Contract | Contract | Contract | Contract |

Task 0 freezes paid execution periods, resets, and retry reserves required for daily reports. These values live in configuration. Downgrades pause excess new work deterministically and never delete or rewrite completed evidence.

Add immutable `AuditUsageReservation` rows with UUID, billing/workspace/project/audit identities, usage kind/period, units, entitlement/catalog revision, idempotency key, and timestamps. Audit creation authorizes membership, resolves `WorkspaceBillingLink`, locks entitlement/usage rows `FOR UPDATE`, validates limits, reserves all executions atomically with audit/config/tasks, deduplicates retries, and commits before provider I/O. Provider failures do not auto-refund; exceptional credits append audited adjustments.

Stable errors include `audit_capability_required`, `project_limit_reached`, `audit_idempotency_conflict`, `schedule_window_exists`, `audit_shape_invalid`, and `audit_quota_exhausted` with safe limit/reset data.

Free permits exactly one card-verified account reservation: `10 × 3 × 1 = 30 executions`. Store only safe verification state and opaque provider reference. Enforce with locking plus DB uniqueness across tabs, workspaces, and members. Consumption occurs when audit/tasks commit; downstream failures do not automatically refund it. If Razorpay lacks a compliant no-charge hosted flow, funded Free remains disabled until an approved alternative exists.

Add one timezone-aware `AuditSchedule` per eligible project with ownership identities, selected prompts/sources, benchmark mode, IANA timezone, local report-ready time, state/pause reasons, next local date, dispatch-policy version, and timestamps. “Report ready by” is not start time; config-owned lead time uses measured route latency, queue wait, retry reserve, and finalization.

The dispatcher claims due windows with `FOR UPDATE SKIP LOCKED`, deduplicates unique `(schedule_id, local_date)`, re-resolves entitlements/connections, pauses invalid providers independently, invokes the shared reservation planner, and advances atomically. Test timezones, DST gaps/folds, delayed ticks, concurrent dispatchers, missing credentials, and provider recovery. No Redis.

## 4. Provider catalog and BYOK expansion

Preserve ChatGPT, Claude, and Gemini as included core sources while replacing hardcoded three-only assumptions with catalog metadata: source/logical key, display name, `source_class = core | optional`, transport/exact model, availability/reason, BYOK/platform-funding support, search/citation/query/batch capabilities, and probe/request-policy versions.

The current invariant limiting active transports to OpenAI, Anthropic, and Google remains in force until an optional adapter passes its gate and the invariant/catalog change is reviewed. Every enabled source preserves logical source, transport, and exact-model provenance across attempts, artifacts, derived rows, filters, metrics, and exports.

Grok/xAI and Perplexity ship independently only after fresh official verification and contract tests prove exact model/endpoint, customer-key support, search/citation/query and empty-search semantics, usage reporting, truncation, authentication, timeout, 429/retry/partial-failure behavior, rate limits, safe key probes, and batch compatibility if claimed.

Copilot is research-gated. Ship and market it only if Microsoft provides an official customer-authenticated API reproducing the relevant public Copilot-style answer with citations under acceptable terms. Never relabel a generic Azure/OpenAI model as Copilot.

Scale may be purchased before optional keys exist. Provider Settings shows connected, missing, failed, or unavailable. Unavailable sources have no key form or schedule selection. The backend validates entitlement, availability, credential mode, and ownership. No optional source is marketed merely because a placeholder exists.

## 5. Cost and latency engineering

Extend the existing artifact-derived cost projection with config-owned, versioned prices for uncached/cached input, output/reasoning tokens, search/tool charges, eligible batch discounts, retries/attempts, currency/effective date, and unavailable usage/pricing. Missing usage yields `unknown`, never zero. Every projection references its `RawResponseArtifact`, attempts, pricing version, and formula version; repricing creates a new projection.

Safe telemetry includes queue wait, provider latency, audit wall time, report finalization, tokens, searches/tools, retries, 429s, schedule lateness, safe connection identity, route/profile, batch mode, and estimated cost. It excludes prompts, answers, brand/competitor data, keys, authorization headers, and raw provider bodies.

Run a non-sensitive 10–20 prompt matrix for every candidate route with search on/off, caps 768/1024/1536, repeated runs, token/tool/retry capture, citation quality, mention/citation agreement, and batch turnaround where relevant. Use the approximately `$0.10/execution` funded baseline only for comparison. Do not claim “three times cheaper” until selected Free routes demonstrate at least a 67% reduction—about `$0.033/execution` or less—under approved p95 treatment including retries/tools.

Release targets: 30 Free no-search executions under 60 seconds p95; at least 95% of paid scheduled reports ready by selected local time; zero provider calls from dashboard/report/evidence/export reads. Use connection-aware concurrency, per-transport pacing, fair slots, capacity-aware claims, continuously refilled slots, queue telemetry, and DB-pool guards. Models, caps, timeouts, concurrency, retry reserves, pricing, pacing, and availability remain configuration. Horizontal scaling stays blocked until capacity is coordinated across processes.

Batch is provider-specific. Use it only when the exact production search/citation payload preserves identity, citations, queries, usage, errors, partial failures, cancellation/expiry, immutable mapping, and the report-ready SLO. Otherwise use paced synchronous execution; never apply token discounts to search/tool charges without proof.

## 6. Billing and funded add-ons

Keep Base on internal key `paid` and existing `$49` Razorpay plans. Add Scale on `bundle` at `$149/month` with separate environment-owned INR/USD plan IDs. Preserve historical Paid external-plan aliases and webhook mappings; never mutate or replace an existing subscription merely to rename Paid to Base. The browser submits only `tier_key="bundle"` and cadence; the server chooses region, currency, amount, provider, and external plan ID.

Use additive Alembic revisions for tier constraints, verification state, usage reservations, schedules, and related persistence. `0001_initial` is frozen and must never be edited.

Phase one launches the funded one-time Free audit plus BYOK Base/Scale. Searchify-funded recurring paid execution remains disabled. Phase two may add fixed monthly per-provider packs and a `BYOK | Searchify-funded` toggle. When funded allowance expires, use valid BYOK if configured; otherwise pause only that provider until reset.

Do not publish pack sizes/prices until measured p95 provider cost plus retry/payment reserve supports at least 70% gross margin. Remove unconditional “provider usage is never marked up” language before funded packs launch.

## 7. Public interfaces and persistence

All routes use `/api/v1`, same-origin browser access, UUID IDs, workspace membership authorization for project data, and billing-owner authorization for checkout/card-verification mutations.

Entitlement DTOs add:

- tier/display plan and capability revision;
- execution limit/reserved/remaining/reset;
- project and scheduled-prompt limits/current use;
- allowed source classes and credential modes;
- answer, citation, fanout, history, schedule, Site Health, monitored-URL, and funded-allowance fields.

Audit DTOs add profile/version, credential source, retrieval/output policy, trigger, schedule/local-date/report-ready metadata, provider-catalog version, and quota reservation status/count. Provider catalog/connection DTOs add source class, availability/reason, BYOK/platform-funding support, search/citation/query/batch capabilities, policy versions, and safe connected/missing/failed/unavailable state.

Add a safe account usage-summary endpoint and one-project-schedule CRUD under `/api/v1`, following existing route conventions:

```text
GET    /projects/{project_id}/audit-schedule
PUT    /projects/{project_id}/audit-schedule
PATCH  /projects/{project_id}/audit-schedule
DELETE /projects/{project_id}/audit-schedule
```

`GET /api/v1/projects/{project_id}/visibility/evidence` remains a persisted projection with `VisibilityEvidenceResponse{items, truncated}`. It exposes answer/citation/query fields only when frozen output policy and current entitlement permit them. Free omits answers and returns `no_search`; Base exposes standard evidence and a structured Query Fanout upgrade state; Scale exposes persisted supported queries and honest `count_only | no_search` states.

History-window checks apply consistently to Visibility, Runs, audit detail, evidence, metrics, and exports. Initial enforcement is an API access window only; evidence remains immutable until a separate provenance-compatible archive/deletion plan is approved.

## 8. Frontend and marketing

Update centralized pricing/catalog content and all consumers together: pricing, FAQ, landing, comparison, enterprise, metadata, onboarding, Billing Settings, Provider Settings, launch confirmation, Visibility, Runs, evidence, and exports.

- Free is a one-time **Model Knowledge audit**, not web visibility: no live citations, Query Fanout, full-answer access, or recurring monitoring.
- Base is daily core-three BYOK monitoring with complete standard evidence, one project, 10 prompts, 90-day history, and 50 monitored URLs.
- Scale is 20 prompts across three projects, 12-month history, Query Fanout, 250 monitored URLs, and only optional sources whose adapters have shipped.
- Enterprise is custom providers, volume, retention, security, deployment, and support.

Keep all four Visibility tabs, one rendered panel, `?tab=` mirroring, and WAI-ARIA behavior. Free Query Fanout shows `no_search`; Base shows an entitlement upgrade state; Scale shows persisted supported queries/counts. Sentiment and average position remain `—`.

Grok, Perplexity, and Copilot stay out of public claims until their individual gates pass. Provider Settings may show a truthful unavailable/research state before marketing launch.

## 9. Implementation task graph

### Task 0 — contract and external-assumption gate

- Approve exact paid execution periods/reset/retry reserves, downgrade policy, funded budget, and card-verification provider.
- Recheck official provider models/endpoints/prices/terms and Razorpay no-charge verification.
- Update invariant 6 deliberately for server-only platform credentials while retaining no-return/no-log/no-brand-list protections.
- Update invariant 10 only when an optional source passes its gate.
- Correct superseded V6 two-tier and migration language; keep `0001_initial` frozen.
- Run the cost/latency/output-cap matrix and freeze profile/catalog/pricing versions.
- **Exit:** every external claim and config value is verified before implementation.

### Task 1 — billing catalog and entitlements

- Add `bundle`, display `paid` as Base, and configure Scale INR/USD plans.
- Add additive migrations and expand capability/catalog/entitlement DTOs.
- Preserve historical Paid webhook and external-plan aliases.
- **Tests:** Paid→Base continuity, historical events, Scale checkout routing, catalog validation, migration/check, injection rejection, and secret-free serialization.

### Task 2 — verification and funded Free

- Implement hosted verification/reconciliation and the one-time 30-unit grant.
- Add platform credential settings and health gates for the core three.
- **Tests:** verified/unverified/expired/failed states, concurrent requests, idempotency, exact reservation, no automatic refund, and no card/key leakage.

### Task 3 — profiles and connector policies

- Add all three profiles and freeze route/request/output identity.
- Implement concise no-search Free payloads for OpenAI, Anthropic, and Google.
- Enforce prompt-only provider input and hidden Free answers across all read/export paths.
- Adopt paid caps only after the 95% agreement gate.
- **Tests:** payload snapshots, absent search tools, no brand leakage, secret redaction, internal-only raw answer, strict DTO omission, empty citations, `no_search`, and historical immutability.

### Task 4 — usage reservations and planner

- Add immutable reservations/adjustments and locked period accounting.
- Enforce account-wide project/prompt/provider/execution limits.
- Route Free, manual, and scheduled creation through one atomic planner.
- **Tests:** concurrency, multi-workspace totals, reset boundary, selected-provider count, manual/scheduled shared use, rollback, idempotency, downgrade races, and workspace isolation.

### Task 5 — report-ready schedules

- Add one project schedule, local-date windows, lead-time policy, and dispatcher.
- Pause providers independently and surface last/next report plus safe pause/lateness data.
- **Tests:** timezones, DST, dedupe, concurrent dispatchers, missed ticks, missing keys, partial provider runs, recovery, downgrade, and no read-path provider calls.

### Task 6 — cost, capacity, and telemetry

- Extend cost projection for cached/input/output/tool/batch/retry data and `unknown`.
- Add connection-aware caps, pacing, fair slots, capacity-aware claims, and DB-pool guards.
- Run production-shaped Free and scheduled-paid matrices.
- **Tests:** pricing provenance, missing usage, retries/discount components, fairness, slot refill, lease/heartbeat/reclaim, pool guard, cancellation, and telemetry redaction.

### Task 7 — Base/Scale frontend and history

- Update strict schemas, pricing, onboarding, Settings, Runs, Visibility, exports, Site Health, quota/schedule UI, history windows, and upgrade states.
- **Tests:** backend/catalog agreement, Paid shown as Base, Scale checkout, optional-source states, hidden Free answers, fanout gates, 90-day/12-month access, WAI-ARIA, and same-origin APIs.

### Task 8 — optional providers

- Implement Grok/xAI and Perplexity as separate releases after their contract matrices pass.
- Extend provenance, filters, metrics, evidence, exports, schedules, and cost config per source.
- Keep Copilot unavailable until its official customer-authenticated API gate passes.

### Task 9 — funded paid packs

- Add per-provider pack catalog, funding-mode toggle, reservations, and BYOK fallback only after the 70% gross-margin gate.
- **Tests:** reset/exhaustion, concurrency, fallback/pause, downgrade, catalog/invoice agreement, and secret safety.

## 10. Verification and release

Focused coverage must include tier aliases/migration, hosted verification, one-time Free use, concurrent account quotas, manual/scheduled shared usage, downgrade behavior, every adapter contract, hidden-answer serialization/exports, scheduler DST/dedupe/recovery, cost provenance, strict frontend schemas, pricing/catalog agreement, provider states, fanout gates, history windows, and workspace authorization.

Representative commands after planned files exist:

```bash
# backend/
uv run pytest tests/unit/test_billing.py tests/unit/test_billing_config.py -q
uv run pytest tests/unit/test_provider_catalog.py tests/unit/test_answer_engine_connectors.py -q
uv run pytest tests/component/test_billing_api.py tests/component/test_audit_planner.py -q
uv run pytest tests/component/test_audit_schedules.py tests/component/test_audit_worker.py -q
uv run pytest tests/component/test_visibility_evidence_api.py tests/component/test_analysis_api.py -q
uv run ruff check .
uv run alembic upgrade head
uv run alembic check

# frontend/
pnpm test -- lib/api/billing.test.ts lib/api/audits.test.ts
pnpm test -- components/visibility/visibility-dashboard.test.tsx
pnpm test -- components/runs/launch-dialog.test.tsx
pnpm lint
pnpm build
```

Measured gates:

- Free p95 under 60 seconds for all 30 executions;
- at least 67% funded cost reduction before a “three times cheaper” claim;
- at least 95% mention/citation agreement for the selected output cap;
- at least 95% of scheduled reports ready by selected local time;
- unknown rather than zero for missing cost/usage;
- zero provider calls from read paths;
- account quota correctness under concurrency;
- no Free answer leakage;
- no optional-provider marketing before its gate; and
- no funded paid pack below 70% gross margin.

Roll out in order: observability/profiles; billing vocabulary with Paid→Base continuity; internal funded Free; BYOK Base scheduling; Scale core features; Grok/Perplexity independently; Copilot after its official API gate; funded packs last.

Rollback disables new reservations, dispatch, source selection, or checkout for the affected capability while preserving webhook processing, entitlement reads, billing history, reservations, artifacts, and evidence.

## 11. Definition of done

- Public plans are Free, Base, Scale, Enterprise; internal keys are `free | paid | bundle | enterprise`.
- Existing `$49 Paid` subscriptions operate as Base without external replacement.
- Exactly one verified 30-execution Free audit is reservable per billing account.
- Free uses server-only platform credentials, prompt-only no-search requests, immutable hidden answers, and deterministic local mention scoring.
- Base enforces one project, 10 prompts, core-three BYOK, daily reports, complete evidence, 90-day access, and 50 monitored URLs.
- Scale enforces three projects, 20 total prompts, 12-month access, Query Fanout, 250 monitored URLs, and only released optional sources.
- Manual and scheduled work share one locked account usage ledger.
- Every audit freezes profile, route/model, credential source, policies, versions, trigger, schedule, and reservation provenance.
- Incompatible profiles/routes are never silently mixed.
- Schedules are timezone-aware, local-date deduplicated, provider-failure isolated, and meet the measured report-ready target.
- Cost projections are artifact-derived, versioned, retry/tool/batch aware, and unknown when incomplete.
- Provider capacity is paced/fair and all reads use persisted evidence only.
- Optional providers and paid packs remain gated.
- Schema changes are additive and `0001_initial` remains untouched.

## 12. Assumptions and non-goals

Assumptions:

- Base remains `$49/month`; Scale launches at `$149/month`, before applicable tax.
- Phase-one recurring paid execution is BYOK.
- Card verification uses an approved hosted flow and stores verification state only.
- Provider/model/pricing/marketing claims receive fresh official verification before launch.
- Existing evidence is immutable and old measurements are not reclassified.

Phase-one non-goals:

- funded recurring Base/Scale execution or overages;
- anonymous or unverified funded audits;
- scraping consumer answer-engine interfaces;
- relabeling generic Azure/OpenAI access as Copilot;
- marketing optional sources before release;
- retroactive profile/evidence rewriting;
- provenance-incompatible archive/deletion;
- sentiment or average-position computation;
- provider calls from read paths;
- Redis or uncoordinated multi-replica workers; and
- unmeasured batch, cost, latency, pack-size, or margin claims.
