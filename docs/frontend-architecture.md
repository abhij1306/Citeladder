# Frontend Architecture — CiteLadder

> Next.js App Router frontend for the visibility slice. Consumes the live workspace-scoped
> `/api/v1` backend contract (B2–B6) through a same-origin proxy. No mock-only fallback, no
> int-id / `user_id` contract.
> Companion docs: [`../Agents.md`](../Agents.md), [`invariants.md`](invariants.md),
> [`backend-architecture.md`](backend-architecture.md), [`design.md`](design.md).

## 1. Stack & role

- **Next.js App Router** + **TypeScript**, deployed on **Vercel** (root = `frontend/`).
- **TanStack Query v5** for server state; **react-hook-form** + **zod** for forms/validation.
- **Tailwind v4** semantic tokens (light/dark) — single `app/globals.css` token source authored
  from [`design.md`](design.md). **Radix** primitives + **lucide** icons; **CVA** for variants.
- Frontend conventions: typed API client with `ApiError` + request-id + abort, per-domain
  endpoint modules with zod `strictValidate`, a `queryKeys` module, a React Query retry policy,
  CVA primitives and a single light-only `globals.css` token owner — on
  **App Router**.
- **Role**: render the seven current application screens and orchestrate calls to the FastAPI backend. It owns
  no business logic and no source of truth — **the backend is the source of truth** (§7).

## 2. Full-product route map (every surface tagged)

| Route | Screen | Status |
|---|---|---|
| `/` | Public marketing landing page (shared chrome in `app/(marketing)/layout.tsx`; client island forwards authed visitors to `/visibility` or `/onboarding`) | **MVP** |
| `/pricing`, `/enterprise`, `/demo`, `/solutions` | Public Free/Paid/Enterprise pricing, enterprise explanation, stable demo funnel, and audience-solution pages | **MVP** |
| `/blog`, `/blog/[slug]` | Public marketing blog index and statically generated posts (`notFound()` for unknown slugs) | **MVP** |
| `/compare`, `/compare/[competitor]` | Public marketing comparison index and statically generated comparison pages (`notFound()` for unknown slugs) | **MVP** |
| `/faq` | Public marketing FAQ (native disclosure controls) | **MVP** |
| `/login`, `/register` | Auth — split-screen (brand panel ≥900px + form panel) with OAuth buttons (Google/GitHub/Apple) wired to the flagged backend scaffold (503 → inline "coming soon") | **MVP** |
| `(app)/layout.tsx` | App shell (sidebar + top bar + project switcher) | **MVP** |
| `/onboarding` | Project creation via AI auto-discovery (brand → discovery → review). Full-screen, no AppShell; replaces the retired `/setup`, `/setup/new` and `/setup/[projectId]` | **MVP** |
| `/projects` | Active-project Dashboard (Analyze/Improve persisted summaries, authenticated PDF report) plus workspace project management | **Implemented** |
| `/prompts` | Your Prompts — read-only active prompts grouped by topic with measured visibility; links to Prompt Research | **MVP** |
| `/prompt-research` | Prompt Research — manage prompts (manual + CSV import + AI generation; Topics rail, Active/Proposed/Archived review tabs) | **MVP** |
| `/providers` | BYOK Provider Settings | **MVP** |
| `/visibility` | Visibility workspace (four tabs: Overview, Trends, Mentions & Citations, Query Fanout) | **MVP** |
| `/products`, `/products/[productId]` | Commerce workspace: Discover, Catalog, AI Conversations, and Market Intelligence. The current UI retains catalog and persisted product-visibility projections; discovery and comparison requests stay feature-gated until their backend contract ships. Drill-down retains mention evidence. | **Implemented / staged** — `components/products/products-screen.tsx` + `lib/api/products.ts` |
| `/runs`, `/runs/[runId]` | Run/Executions explorer; execution evidence opens in a run-context drawer | **MVP** |
| `/analytics` | LLM Analytics | **Implemented** — `components/analytics/analytics-screen.tsx` + `lib/api/analytics.ts` |
| `/traffic` | Traffic | **Implemented** — `components/traffic/traffic-screen.tsx` + `lib/api/traffic.ts` |
| `/content` | Content writer (basic v1: prompt-box-first composer, Website-context toggle, sanitised Markdown result, cancel, history) | **Implemented** |
| `/opportunities` | Opportunities (snapshot strip + priority catalog + evidence drawer) | **Implemented (v1)** |
| `/site-health`, `/site-health/crawls/[crawlId]/pages/[siteUrlId]`, `/issues` | Site Health + Issues | **Implemented** — see [`site-health.md`](site-health.md) |
| `/brand` (Profile beyond setup, Competitors, E-E-A-T) | Brand suite | Roadmap |
| `/topics` | Dedicated Topics page (topic management already lives in the `/prompt-research` rail) | Roadmap |
| `/knowledge-base` | Curated Brand Knowledge — description, positioning, products/services, audience, and reviewed AI drafting | **MVP** |
| `/writing` (Tone/Style, Memory) | Writing suite | Roadmap |
| Settings → Integrations (`?tab=integrations`, 4th settings tab; GSC/GA4/Bing connect, sync, property mapping) | Integrations | **Implemented** — `components/settings/integration-settings.tsx` + `lib/api/integrations.ts` |
| Settings → Billing (`?tab=billing`; billing country, Free/Paid status, hosted Razorpay upgrade and end-of-period cancellation) | Billing | **Implemented, disabled by default pending merchant readiness** — `components/settings/billing-settings.tsx` + `lib/api/billing.ts` |
| Settings → Agent, MCP | Agent / MCP | Roadmap |

The sidebar renders only live items (no disabled/"soon" placeholders); Traffic and LLM Analytics are live in the Analyze group.

## 3. Current surface and roadmap table

| Capability | MVP | Roadmap |
|---|---|---|
| Auth + workspace + project switch | ✅ | |
| Brand/project setup (aliases, domains, competitors, benchmark_mode) | ✅ | full `/brand` suite, competitor profiles, E-E-A-T |
| Curated Brand Knowledge editor and review-first AI drafting on persisted projects | ✅ (`/knowledge-base`) | broader writing suite, memory |
| Prompts: manual entry + CSV import + AI-generated topics/prompts (proposed → accept/archive review) | ✅ | |
| BYOK providers + connection test (direct OpenAI/Anthropic/Google, exact Pulse + Benchmark routes) | ✅ | |
| Launch audit (multi-engine, repetitions) + cancel | ✅ | recurring schedules |
| Visibility workspace | four tabs — Overview (selected-run score + per-engine + rankings), Trends (cross-run), Mentions & Citations + Query Fanout (persisted evidence) | Sources / Topics / Sentiment tabs (**not built**) |
| Sentiment + avg-position columns | render `—` placeholder | computed |
| Run/Executions evidence + CSV/MD export | ✅ | HTML/JSON renderers |
| Run progress | polling (SSE optional) | full SSE streaming UI |

## 4. Frontend subsystems

| Subsystem | Files (target) | Owns |
|---|---|---|
| Shell + auth | `(auth)/*`, `(app)/layout.tsx`, `session-guard.tsx`, `app-shell`, `sidebar-nav`, `top-bar`, `project-switcher`, `components/auth/oauth-buttons.tsx`, `components/ui/logo-cube.tsx` | Session, guard, nav, project context, OAuth buttons (coming-soon), brand cube |
| API contract layer | `lib/api/{client,errors,query-client,query-keys,schemas,types,index}.ts` + per-domain modules | Transport, zod contracts, retry policy |
| Onboarding | `/onboarding` + `lib/api/brand-discoveries.ts` | Brand name + official website (required), optional industry/country/language hints, persisted crawl/search/synthesis, evidence review, and atomic project creation |
| Projects | `/projects` + `components/projects/dashboard-screen.tsx` + `lib/api/projects.ts` | Active-project Dashboard, persisted PDF download, list/switch projects, add another |
| Product tour | `components/tour/product-tour-provider.tsx` + `lib/api/workspaces.ts` | Versioned, workspace-member progress; route resume, Skip/Done, reduced-motion handling, and user-menu replay |
| Prompts | `/prompts` (Your Prompts) + `/prompt-research` + `lib/api/prompts.ts` + `lib/api/topics.ts` | Your Prompts: topic-grouped read-only view with evidence-derived visibility scores. Prompt Research: prompt CRUD, CSV import, topic rail (create/delete/filter), AI generation dialog (consent-gated), proposed/active/archived status tabs with accept/archive actions |
| Providers | `/providers` + `lib/api/providers.ts` | BYOK cards and connection test. Model identity is catalog-owned; the UI displays exact Pulse and Benchmark routes and never selects or aliases models. |
| Billing | Settings Billing + `lib/api/billing.ts` + `lib/billing/entitlement-context.tsx` | Strict catalog/account/entitlement contracts, persisted country selection, Razorpay hosted checkout, webhook-confirmation state, cancellation, and fail-closed workspace capability context. |
| Visibility | `/visibility` + `lib/api/visibility.ts` | Four-tab workspace with a shared filter bar (§7) |
| Runs / executions | `/runs/*` + `lib/api/runs.ts` | Launch, progress, cancel, evidence, export |
| Content | `/content` + `lib/api/content.ts` + `lib/content/{use-content-generations.ts,markdown.tsx}` + `components/content/content-screen.tsx` | **Live** — enqueue (client-generated `Idempotency-Key`), conditional polling while non-terminal, cancel/regenerate/try-again, history list, and a sanitised Markdown renderer (react-markdown + remark-gfm, **no rehype-raw**, http/https/mailto URL allowlist, images dropped, hardened links) |
| Opportunities | `/opportunities` + `lib/api/opportunities.ts` + `components/opportunities/{opportunities-screen,opportunities-catalog,evidence-drawer}.tsx` | Snapshot strip (API-owned counts + Recompute + exports), server-filtered priority catalog (keyset), status PATCH, evidence/provenance drawer (new 448px shell — not the HistoryDrawer) |
| UI + token policy | `components/ui/*`, `app/globals.css` | CVA primitives, bridged tokens only (no raw hex) |
| Marketing CSS | `app/(marketing)/marketing-theme.css` (≤400 lines), `app/(marketing)/marketing-motion.css` (≤260) | Tokens + scene rules in one owner, keyframes + scroll timelines in the other; both budgets machine-enforced |
| Command palette | `components/ui/command-palette.tsx` | ⌘K/Ctrl+K over `NAV_GROUPS` + workspace projects; owns its centered top-bar trigger |

## 5. Live backend API usage

- **Same-origin proxy**: `next.config.ts` `rewrites()` maps `/api/:path*` → the server-only
  `BACKEND_ORIGIN`. The browser **only ever** calls `/api/...` relative (invariant 12).
- **API client** (`lib/api/client.ts`): relative base (`/api/v1`), `ApiError` with
  `X-Request-ID`, `AbortSignal` support, `credentials:'include'`, `cache:'no-store'`, bounded
  network retry for GET/idempotent only, JSON enforcement.
- **Endpoints per screen**:
  - Auth → `/auth/register|login|logout|me` + `/auth/oauth/providers|{provider}/start|{provider}/callback` (scaffold behind `OAUTH_*` flags; 503 until configured)
  - Shell/switcher → `/workspaces`, `/projects`
  - Dashboard → `GET /projects/{id}/dashboard`, `GET /projects/{id}/dashboard/report.pdf`
  - Product tour → `GET/PATCH /workspaces/{id}/product-tour`
  - Billing → `/billing/catalog` (public), `/billing/entitlement`, `/billing/usage`,
    `POST /billing/subscriptions` + `DELETE /billing/subscription`,
    `POST /billing/addons` + `DELETE /billing/addons/{key}`, `POST /billing/topups`
    (all mutations carry a mandatory `Idempotency-Key`; `202` while pending),
    `POST /billing/webhooks/razorpay` (server-only). Legacy routes
    (`/billing/me|profile|checkout|manage|cancel`, `/workspaces/{id}/entitlements`)
    are deleted and return 404.
  - Onboarding → `/brand-discovery-catalog`, `/brand-discoveries` create/read/confirm/create-project; profile gaps remain editable `needs_input`.
  - Projects → `/projects` (+ `/projects/{id}`), `GET/PUT /projects/{id}/brand-profile`,
    `POST /projects/{id}/brand-profile/suggest`, and explicit suggestion acceptance
  - Prompts → `/prompt-sets`, `/prompts/{id}`, `/prompt-sets/{id}/import` (CSV),
    `/prompt-sets/{id}/generate` (AI generation), `/prompt-sets/{id}/prompts/bulk-status`
    (accept-all), `/projects/{id}/topics` + `/topics/{id}` (topic CRUD)
  - Providers → `/provider-connections`, `/provider-connections/{id}/test`, `/provider-catalog`
  - Visibility → `GET /projects/{id}/visibility?audit_id=` (Overview),
    `GET /projects/{id}/visibility/trends` (Trends),
    `GET /projects/{id}/visibility/evidence` (Mentions & Citations + Query Fanout, shared)
  - Runs → `POST /audits/estimate`, `POST /audits`, `GET /audits`, `GET /audits/{id}`, `GET /audits/{id}/performance`, `POST /audits/{id}/cancel`,
    `GET /audits/{id}/executions`, `GET /executions/{id}`, `GET /audits/{id}/export.{csv,md}`,
    `GET /audits/{id}/events` (SSE, optional)
  - Content → `GET/POST /content/generations`, `GET /content/generations/{id}`,
    `POST /content/generations/{id}/{regenerate|try-again|cancel}`
  - Opportunities → `GET /projects/{id}/opportunities` (+ `type|severity|status|rule_id|
    min_priority|limit|cursor`), `GET /projects/{id}/opportunities/summary`,
    `POST /projects/{id}/opportunities/recompute`, `GET /opportunities/{id}`,
    `PATCH /opportunities/{id}` (status only), `GET /projects/{id}/opportunities/export.{csv,md}`
- **Workspace scoping**: the active workspace + project are carried in context; the backend
  enforces workspace auth on every query (invariant 5). No `user_id` anywhere.
- **Cookie session**: JWT in a secure HttpOnly cookie; the client sends `credentials:'include'`.
  A 401 clears the session and redirects to `/login`.
- **Run progress = polling first**: `/runs/[runId]` **polls** `GET /audits/{id}` while active
  (requested/completed/failed + status). The backend SSE `/events` endpoint is MVP but the UI
  **consumes SSE optionally** — polling is the baseline so a dropped stream never blocks
  progress.

### 5.1 Visibility workspace (four-tab IA)

`/visibility` is ONE workspace shell (`components/visibility/visibility-dashboard.tsx`): a
**shared filter bar** (`visibility-toolbar.tsx`) above an accessible tablist
(`visibility-tabs.tsx`, WAI-ARIA `tablist`/`tab`/`tabpanel` with roving tabindex +
Arrow/Home/End) with **exactly four** panels, in order:

1. **Overview** (default) — selected-run score / share-of-voice / per-engine provider comparison
   / brand-vs-competitor rankings, from `GET /projects/{id}/visibility?audit_id=`.
2. **Trends** — cross-run metrics + charts, from `GET /projects/{id}/visibility/trends`.
3. **Mentions & Citations** — persisted mention/citation evidence.
4. **Query Fanout** — frozen prompts + generated queries with `queries_available | count_only |
   no_search` states.

Tabs 3 and 4 read the **same** shared persisted dataset,
`GET /projects/{id}/visibility/evidence`. **Only one panel renders at a time**; the active tab
is mirrored in `?tab=` (invalid values fall back to Overview) so refresh / back / forward
preserve it. There are **no Sources / Topics / Sentiment tabs** and **no disabled /
"coming soon" tabs**. Sentiment + avg-position stay null and render as an em-dash (`—`).

**Shared filter ownership** (state lives in the container and persists across tab switches;
hidden controls keep their state):

| Filter | Affects |
|---|---|
| Selected run (`audit_id`) | Overview + both evidence tabs |
| Logical engine | all four tabs |
| Cohort (`core|comparison`) | all four tabs; defaults to core |
| Prompt | both evidence tabs |
| Date range (`from`/`to`) | Trends + both evidence tabs |
| Granularity (`run\|week\|month`) | Trends only |

When an evidence request carries both `audit_id` and a date bound, the backend intersects them.

**Per-tab query enablement**: only the active tab's query runs — the selected-run projection for
Overview, the trend series for Trends, and a **single shared evidence query** (one identical
cache key) for either evidence tab, so switching between Mentions & Citations and Query Fanout
reuses the cached dataset rather than refetching.

## 6. Drift policy

- Every JSON response object is validated with **zod `strictValidate`** — it **fails loud**
  on any mismatch of a **declared field** (a missing required field, a wrong type, an unknown
  enum value) rather than silently coercing. A validation failure is a bug to fix, not to
  swallow. (Non-JSON response bodies — CSV/Markdown exports via `getText`, PDF/CSV blobs via
  `getBlob` — have no zod schema and are not parsed.)
- **Tolerant-on-unknown (ERR-5).** Response objects are built with the `responseObject`
  helper in `lib/api/schemas.ts` (zod `.strip()` semantics): **unknown keys are dropped**
  from the parsed output, so an additive backend field can never break a screen. (The old
  `z.strictObject` policy rejected any undeclared key — one additive `AuditResponse` field
  took down `/visibility`.) Stripping also keeps accidentally leaked keys (e.g. a secret)
  out of app state.
- **Contract-drift guard.** Tolerance must not become silent divergence, so a guard diffs
  the backend OpenAPI response-model field sets against the zod schemas' declared keys
  (`lib/api/contract-drift.ts`, run by the `lib/api/contract-drift.test.ts` vitest wrapper
  inside `pnpm test`, or standalone via `pnpm check:contract`). It **FAILS on missing
  declared fields** (the frontend declares a field the backend model no longer has — drift
  the UI needs) and **WARNS on additive-only diffs** (backend fields not yet declared —
  update `schemas.ts` promptly). The OpenAPI document is obtained deterministically: from
  `CITELADDER_OPENAPI_JSON` (path to a schema export) when set, else generated offline from
  the checked-in backend code (`backend/.venv` — no server, database, or network), else
  fetched from the live backend at `CITELADDER_BACKEND_ORIGIN` (default
  `http://localhost:8000`). When no source is available the plain vitest wrapper logs and
  skips, while `pnpm check:contract` **fails** — it sets `CITELADDER_CONTRACT_STRICT=1`,
  which `contractGuardIsStrict` turns into a hard error instead of a skip. **`pnpm test`
  alone is therefore not sufficient verification of the contract**: always run
  `pnpm check:contract` too (from `backend/`-adjacent checkouts, where the offline
  codegen can reach `backend/.venv`), since `pnpm test` silently skips the guard whenever
  the OpenAPI source is unavailable.
- **Requests stay typed.** Outgoing payloads are built from TypeScript DTOs, so call sites get
  compile-time type checks. These local DTOs are not generated from or validated against
  the backend OpenAPI schema, so backend request-contract drift still requires review or
  integration/contract tests; the automatic schema-drift guard described above applies to
  parsed response fields.
- **The backend is the source of truth.** The frontend never invents fields, never keeps a
  parallel schema, and never falls back to mock data in production paths. If the contract
  changes, update `schemas.ts` to match the backend, not the other way around.

## 7. zod data contracts (all ids `z.string().uuid()`, workspace-scoped)

- `sessionUserSchema {id,email,role,is_active,created_at,updated_at}`
- `competitorSchema {id,name,aliases[],domains[]}`
- `promptSchema {id,prompt_set_id,text,theme,intent,branded,enabled,origin}`
- `projectSchema {id,workspace_id,name,brand_name,website_url,country_code,language_code,
  benchmark_mode,default_repetitions,brand{aliases[]},owned_domains[],unintended_domains[],
  competitors[],prompt_sets[],created_at,updated_at}` (benchmark_mode enum)
- `providerConnectionSchema {id,workspace_id,transport_provider,base_url,active,...}` — **secret
  never present**
- `providerRouteSchema {id,logical_engine,transport_provider,transport_model,is_default}`
- `providerCatalogSchema`
- `auditSchema {id,workspace_id,project_id,status,random_seed,configuration,summary,
  requested_count,completed_count,failed_count,error_message,created_at,updated_at,completed_at}`
- `executionSchema {id,audit_id,prompt_index,repetition,randomized_position,status,prompt_text,answer_text,
  search_used,search_events[],citations[],score,provider_metadata,error_code,error_message,
  latency_ms}`
- `citationSchema {ordinal,url,title,domain,cited_text,classification}` (`owned|competitor|third_party`)
- `visibilitySchema` — Overview selected-run: score + per-engine comparison + rankings rows;
  `sentiment`/`avg_position` nullable (render `—`).
- `visibilityTrendPointSchema` / `visibilityTrendListSchema` — Trends: cross-run series.
- `visibilityEvidenceResponseSchema {items,truncated}` (`visibilityExecutionEvidenceSchema` →
  mentions/citations + `search_events[]` + fanout `state` of
  `queries_available|count_only|no_search`) — the shared dataset for the two evidence tabs.
- `transportProviderSchema = z.enum(['openai','anthropic','google'])` for the approved
  direct transports on both request and response DTOs.
- `opportunitySchema` / `opportunityDetailSchema` / `opportunitiesPageSchema` /
  `opportunitySummarySchema` / `recomputeResponseSchema` with the per-subsystem enums
  `opportunityTypeSchema` (`visibility|site|traffic|topic`), `opportunitySeveritySchema`
  (5 tokens), `opportunityStatusSchema` (`open|in_progress|dismissed|resolved`). The summary
  is `computed=false` (empty counts, null ids) before the first recompute — a 200, not a 404.

**Every `id` and `*_id` field is `z.string().uuid()`; no numeric ids; no `user_id`.** All
responses pass through `strictValidate`.

## 8. Testing surface

- **Vitest + Testing Library + jsdom + msw** for unit/component (client throws `ApiError`,
  `strictValidate` throws on mismatch, `shouldRetryQuery` matrix, form validation, table CRUD,
  command-center rendering from data and light-only appearance settings).
- **Playwright** smoke: login → shell → Visibility → open run → open execution.
- **Playwright real-stack content integration** (`e2e/content-integration.spec.ts`, own config
  `e2e/content-integration.config.ts`): disposable Postgres DB + real API + real
  `content_worker` + mock provider endpoint (swap is `CONTENT_PROVIDER_ENDPOINT` only). Run
  explicitly: `pnpm exec playwright test --config e2e/content-integration.config.ts`.
- **Architecture-guard scripts**: line budgets, required API owners exist, `index.ts` owns no
  transport, token-escape / **no-raw-hex** guard over `globals.css` + `components/`.
- Full-suite + build + guards run in task **V1** (final full-stack verification).

## 9. Architectural notes

- CiteLadder is light-only. Root layout loads Geist through `next/font/google`; there is
  no theme bootstrap, persisted theme preference, or alternate theme infrastructure.
- **Retry policy** (`shouldRetryQuery`): retry 408/429/5xx/network up to 2×; `staleTime` 15s;
  `refetchOnWindowFocus:false`.
- **`index.ts` is a compat facade** — it spreads the per-domain modules and owns no transport.
- **`trend-chart` primitive powers the Trends tab** — the cross-run Visibility metrics + charts
  render from `GET /projects/{id}/visibility/trends`.
- **No raw hex in components** — only bridged Tailwind semantic tokens (see [`design.md`](design.md)).

## 10. Companion docs

- Repo bootstrap + rules: [`../Agents.md`](../Agents.md)
- Hard rules + ops gotchas: [`invariants.md`](invariants.md)
- Backend contract this frontend consumes: [`backend-architecture.md`](backend-architecture.md)
- Design tokens + per-screen layout: [`design.md`](design.md)
