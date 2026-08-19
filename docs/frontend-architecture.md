# CiteLadder frontend architecture

> **Status:** current frontend authority
> **Framework:** Next.js App Router, TypeScript, TanStack Query, Zod

The frontend projects workspace-scoped backend contracts. It owns navigation,
interaction, accessibility, validation, and local ephemeral state; it does not
own scoring, page classification, lifecycle truth, or authorization.

## Locked rebuild route contract

Navigation is organized into five loop stations. This is the shipped contract;
a replacement is complete only after every caller is migrated and the
superseded path is deleted.

| Station | Destination | Canonical browser location |
|---|---|---|
| Overview | Overview | `/projects` |
| Analyze | Website | `/site?tab=pages` (default), `aeo-readiness`, `changes` |
| Analyze | Issues / Search Demand / Traffic | `/issues`, `/demand`, `/traffic` |
| Analyze | Commerce Suite | `/products` |
| Act | Opportunities / Content | `/opportunities`, `/content` |
| Track | AI Visibility | `/visibility?tab=trends` (default), `mentions-citations`, `query-fanout` |
| Track | Runs / AI Referrals | `/runs`, `/runs/[runId]`, `/ai-referrals` |
| Connect | Integrations / Providers | `/settings?tab=integrations`, `/settings?tab=providers` |
| Connect | Prompts / Settings | `/prompts`, `/settings` |

The mobile bar has exactly Overview, Analyze, Act, Track, and Connect. One
shared station-navigation owner exposes secondary destinations and resolves
active state from pathname plus recognized `tab`/`mode` values. The Growth
Agent moves to an accessible top-bar sheet with typed persisted route context;
it is not a sidebar destination. Retired internal routes receive no redirects.

Desktop and mobile now consume that shared station owner. Commerce Suite is an
Analyze destination for every project. Providers and Integrations are Settings
tabs, and prompt read/manage modes live only under `/prompts`.

Overview renders before any audit: canonical Facts with an editable drawer,
competitor suggestions, four evidence-labelled loop states, one server-selected
next action, and a Track summary whose missing audit values remain unavailable.
The standalone Facts route is deleted; the reusable BrandProfile editor remains
the only editor owner. Onboarding's confirmation step edits the discovered ICP
fields and requires positioning, target audience, and products/services before
completion can create prompts.

## Core rules

- Browser calls use relative `/api/*`; Next.js rewrites to server-only
  `BACKEND_ORIGIN`. In Compose, that destination is `http://web:8000`; the browser-facing
  frontend service listens on port 3000.
- Server data uses TanStack Query and shared Zod response schemas.
- IDs and active workspace/project context are explicit.
- No production screen falls back to mock data or computes a backend metric.
- Only live destinations render; future work is not shown as disabled UI.
- Long-running state comes from persisted backend projections. Polling may be
  accelerated by events but is never replaced by ephemeral client state.

## Site surfaces

The site area has exactly three destinations:

| Route | Purpose |
|---|---|
| `/site` | Crawl lifecycle, score summary, scores by page kind, URL inventory |
| `/issues` | Grouped issue catalog with severity, affected pages, and page-kind scope |
| `/opportunities` | Persisted prioritized actions |

The former multi-panel Site Intelligence workspace is removed. Do not nest a
second site workspace, knowledge panel, journey panel, correction workflow, or
comparison surface inside these routes.

The backend owns the current Site Health phase. The client renders the provided
phase and action availability instead of reconstructing a cross-product of
crawl, discovery, analysis, and phase-run states.

The same rule applies to live worker activity. The API supplies a persisted
blocked/failure breakdown and an evidence-derived `working | waiting | stalled
| terminal` activity projection. The browser renders host-gate and retry waits,
continues polling through recovery, and calls a crawl stalled only when the
backend reports an expired lease. It never infers failure from a quiet timer or
from a completed counter that has stopped moving.

Before the first crawl, `/site` renders one actionable empty placeholder
with **Run new crawl**, rather than empty metrics or an intake workflow. After a
crawl exists, its header has one contextual primary control: **Stop crawl** for
an active persisted crawl, otherwise **Run new crawl**. **Export** is the
secondary action. The client exposes no separate discovery or analysis buttons.

Website uses one tablist on `/site`. **Pages** retains the crawl lifecycle and
inventory surface. **AEO Readiness** is the adjacent Website tab. It renders the server's seven
ordered presentation dimensions as pass, fail, not-applicable, and explicit
expected/observed coverage columns. Bounded persisted evaluation links open the
existing crawl-bounded page detail. The client does not remap rules, recompute
coverage, guess a missing bucket, or display a composite readiness score.

**Changes** reads only persisted Change Intelligence summary and cursor pages.
It shows the four classes, exact before/after values, analysis provenance, and
an Expected marker only for an exact implementation-event link. Unavailable,
non-comparable, partial, and observed-zero pairs have separate copy. Partial
pairs explicitly state that added/removed URL claims were suppressed; the
browser never computes a diff or turns a neutral/expected change into an action.

The inventory remains mounted and progressive: discovery renders the first ten
persisted rows as they arrive, and rows later receive their analysis status and
scores in place. The Issues row uses persisted description copy for what is
wrong, an affected-page evidence chip, and persisted remediation only inside
the expanded fix guidance. It does not generate browser-side recommendation
copy.

The Issues surface has separate server-backed **Defects** and **Advisories**
views. Defects are the default and the only class with severity chips. Its
headline explicitly counts distinct defect issue types, while supporting
labels name occurrences and affected URLs. Switching views changes the
headline to distinct advisory issue types and labels the supporting quantities
as advisory evidence. Advisory rows are labelled as advisories rather than
borrowing defect severity semantics.

## Page-kind UX

The API-contract schema owns the page-kind vocabulary. Shared helpers in
`frontend/lib/site-health/page-kinds.ts` provide labels, stable ordering, and a
defensive parser for classifier evidence.

Pages and URL detail show the persisted structural kind. The detail disclosure
may explain the winning signal, schema suggestion, alternatives, conflicts,
confidence, and `other` reason. It never reclassifies in the browser.

Issue groups show affected page-kind badges so a product-schema issue is visibly
different from a universal title or delivery issue. Not-applicable evaluations
do not appear as passes or issues.

## Frontend owner boundaries and shared mechanics

A screen entry point coordinates route context, server-state hooks, mutations, and
transient UI state. It delegates cohesive visual regions, domain-specific
formatting, and interaction mechanics to focused sibling owners. A split must
preserve one public entry point for callers; consumers must not compose a
screen from its internal presentation files.

| Surface | Coordinator boundary | Focused owners |
|---|---|---|
| Growth Agent | `components/agent/growth-agent-workspace.tsx` owns workspace state and actions | `growth-agent-workspace-view.tsx` owns run detail, task form, and task history presentation |
| AI Referrals | `components/ai-referrals/ai-referrals-screen.tsx` owns project/range queries and toolbar selection | content, dashboard, and skeleton owners render the query states and measurements |
| Content | `components/content/content-screen.tsx` owns project transitions and generation orchestration | data hooks, generation history, and composer/result panels own their respective concerns |
| Onboarding | `components/onboarding/onboarding-screen.tsx` selects the active stage | flow, layout, and stage owners contain the transaction state, responsive chrome, and stage UI |
| Projects dashboard | `components/projects/dashboard-screen.tsx` owns query gates and project context | dashboard controls, primitives, sections, and command-center action hook own reusable UI and mutations |
| Traffic | `components/traffic/traffic-screen.tsx` owns query gates and selected analytical controls | toolbar, unified-performance card, and synchronization hook own their scoped behavior |
| Site Health URL detail | `components/site-health/url-detail.tsx` owns query/rerun control and polling | `url-detail-view.tsx` owns the persisted-detail presentation |
| Commerce, prompts, providers, and marketing previews | Existing public panels and dialogs remain their caller-facing owners | small view, cell, topic, preview, and message-bus modules own discrete presentation or local interaction regions |

### Site Health API schemas

`frontend/lib/api/schemas/site-health.ts` is the stable Site Health schema
facade. The public `lib/api/schemas` barrel re-exports that facade, so API
consumers retain their existing import boundary and inferred Zod schema names.
Focused modules under `lib/api/schemas/site-health/` own crawl lifecycle,
dashboard/change/readiness, inventory, issues, page detail, pagination, and
shared schema primitives. Do not import a focused file from a feature solely to
avoid the facade; move a genuinely shared primitive into the focused schema
folder and re-export it through the facade.

### CSV import mechanics

`components/ui/csv-import.tsx` owns the reusable import-dialog shell, file
input, preview framing, and `useCsvImportFile` lifecycle. File text loading,
including the browser and test-environment fallback, belongs to
`lib/csv/read-file-text.ts`. Prompt and product modules retain ownership of
their own CSV grammar, validation, preview columns, and import mutations. The
shared layer must not make domain validity decisions or post a domain payload.

### Event-stream mechanics

`lib/sse/frames.ts` owns raw Server-Sent Event frame splitting and parsing.
`lib/sse/use-event-stream.ts` owns the credentialed browser transport:
workspace and resumption headers, chunk decoding, cancellation, reconnect
backoff, and debounced invalidation delivery. Domain hooks retain event
classification and query invalidation ownership:

- `lib/runs/use-run-events.ts` validates audit frames and chooses run and
  visibility query families.
- `lib/site-health/use-crawl-events.ts` distinguishes lifecycle changes from
  per-page progress and refreshes the applicable crawl views.
- `lib/api/run-events.ts` retains the audit-event contract and compatibility
  exports for framing helpers; it does not own a second stream transport.

Streams accelerate polling-backed projections only. They never become a
client-side source of truth or construct rows from partial, replayed, or
unknown event payloads.

### Complexity boundary

The frontend complexity guard covers `app`, `components`, and `lib` with a
maximum cyclomatic complexity of 12 per function, 500 LOC per production
module, and 800 LOC per test module. The guard rejects relaxed defaults and
new or increased policy exceptions. New and refactored owners must meet those
defaults by decomposition; an exception is not an intended delivery outcome.

## Other route ownership

| Route family | Owner |
|---|---|
| `/content` | Content Intelligence; frozen grounding status and provenance summary |
| `/demand`, `/traffic`, `/ai-referrals` | Demand Intelligence |
| `/prompts`, `/visibility`, `/runs` | Demand/Visibility workflows |
| `/products` | Commerce specialization |
| `/settings` | Shared workspace/project configuration, including Integrations and Providers |

## Authentication flow

Registration consumes only the generic `RegistrationResponse` acknowledgement
and redirects to `/login?registered=1`. It does not seed the authenticated-user
cache or assume that registration created a session. Login remains the sole
email/password flow that receives a session and performs the account-scoped
cache transition.

## Data and query ownership

Each domain has one API module, one query-key owner, and shared schemas/types.
Queries are enabled only when their surface is visible where practical. A
shared artifact uses the same server ID and cache identity everywhere.

Unknown, unavailable, zero, historical, conflicting, excluded, and
not-applicable states retain distinct labels and are never communicated by
color alone.

The Opportunity evidence section renders the backend's `source_pattern` block
for visibility gaps: the distinct cited domains grouped by source class, the
competitor-to-domain map, representative citations, and the suggested next
action. `lib/opportunities/source-pattern.ts` parses the persisted payload
defensively and never re-derives a class from a domain; an absent block or a
gap with nothing cited renders nothing rather than a measured zero. Badge color
tracks ownership only, so independence is never presented as a quality ranking,
and the copy stays observational — these are sources seen alongside a measured
gap, never its stated cause.

The Opportunity detail footer owns the explicit **I implemented this** action.
It posts an idempotent declaration with resolved target IDs and expected
checks, then renders the persisted lifecycle as `declared`, `observed`,
`verified`, or `contradicted`, including verifier limitations. Reloading reads
the same state from the implementation-event projection; a workflow status
such as Resolved neither creates nor replaces this action record.

## Demand, traffic, referrals, and agent UX

`/demand` is the single **Search Demand** screen; it does not provide nested
Overview/Search Demand/AI Visibility tabs. `/visibility` remains the standalone
AI Visibility destination. Search Demand renders labelled GSC-backed signal
rows, branded demand as a non-actionable cohort, and the honest no-snapshot,
unavailable, observed-zero, partial, insufficient-history, and active states.
Detector absence never becomes a fabricated zero or an intended-page mismatch
placeholder.

AI Visibility has exactly Trends, Mentions & Citations, and Query Fanout, with
Trends as the default. Trends owns latest/start rankings, engine comparison, and
prompt movement. Competitor suggestions live in Overview's Facts drawer, and no
Visibility overview token, component, selected-run composition, or redirect is
retained.

Traffic treats Day/Week/Month as chart-interval controls. During an interval
refetch, existing analytical content stays mounted, the analytical region is
marked busy with compact loading feedback, and focus remains on the selected
control. Labels and comparisons render from API-returned `granularity` only.
Top pages and Top queries are accessible underline tabs; their selected-window
rankings state that chart interval does not affect them.

`/ai-referrals` renders only referral volume, referral share, and AI-source
totals, with their measurement context. It has no copied visibility, themes,
correlation, or event surfaces. The empty Reports navigation item, route, and
title mapping are absent; the persisted executive PDF remains an Overview
download.

## Verification

Use pnpm only:

```bash
pnpm test -- <file>
pnpm lint
pnpm build
```
