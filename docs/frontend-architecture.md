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
| Analyze | Website | `/site?tab=pages` (navigation target and non-dashboard default); Overview becomes the default when the server phase is `dashboard`, with `architecture`, `aeo-readiness`, and `changes` also available |
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
The completion request returns the committed project shell rather than waiting
for prompt generation. The review stage enters the project whenever the
completion response or persisted discovery carries `project_id`; it does not
wait for the background portfolio to reach `project_created`. A shell-less
terminal completion failure remains visible instead of being presented as work
that is still running.

## Core rules

- Browser calls use relative `/api/*`; Next.js rewrites to server-only
  `BACKEND_ORIGIN`. In Compose, that destination is `http://web:8000`; the browser-facing
  frontend service listens on port 3000.
- Server data uses TanStack Query and shared Zod response schemas.
- Next.js Cache Components and Partial Prefetching produce one reusable App
  Shell per route. The authenticated layout is instant-navigation validated;
  its sidebar, top bar, query client, and project context remain mounted while
  route-owned content streams or enters the `(app)` loading shell. A focused
  Playwright `instant()` assertion protects primary navigation.
- Retained TanStack Query placeholder data is owner-scoped: filter, sort, and
  cursor changes may keep prior results mounted only while the project or
  crawl identity is unchanged. A project/crawl switch returns to an explicit
  loading state instead of temporarily relabelling prior persisted evidence.
- IDs and active workspace/project context are explicit.
- No production screen falls back to mock data or computes a backend metric.
- Only live destinations render; future work is not shown as disabled UI.
- Long-running state comes from persisted backend projections. Polling may be
  accelerated by events but is never replaced by ephemeral client state.

## Site surfaces

The site area has exactly three destinations:

| Route | Purpose |
|---|---|
| `/site` | Crawl lifecycle, readiness and three coverage projections, scores by page kind, URL inventory |
| `/issues` | Grouped issue catalog with severity, affected pages, and unboxed page-kind scope metadata |
| `/opportunities` | Persisted prioritized actions |

The former multi-panel Site Intelligence workspace is removed. Do not nest a
second site workspace, knowledge panel, journey panel, correction workflow, or
comparison surface inside these routes.

The persisted observed-architecture projection is presented as the
**Architecture** tab of the existing Website tablist in
`components/site-health/architecture-panel.tsx` — never a second site workspace
and never its own route. The tab leads with the persisted Internal linking and
Structure depth summaries, followed by Page kinds, Pages, Median depth,
Duplicate metadata, and Orphaned pages and an always-visible page-kind ledger
whose columns are page kind, pages, median depth, indexable, duplicate metadata,
and orphaned. Only the URLs assigned to a page kind are disclosed on demand.
A read-only Observed hierarchy follows the ledger and nests URLs only by the
API's persisted `parent_site_url_id`, naming each returned `parent_source`;
unresolved nodes remain roots and the browser never invents parentage. Expanded
URL sets and the observed tree use bounded scroll regions so a
large crawl cannot turn either card into an unbounded page. The tab
renders no site-profile/archetype block. The browser renders the persisted
coverage state and limitation once and leaves orphan absence unmeasured whenever
coverage is not `complete`.

The backend owns the current Site Health phase. The client renders the provided
phase and action availability instead of reconstructing a cross-product of
crawl, discovery, and analysis states. That includes why a crawl is
partial: the client selects copy from the persisted `partial_reason` and never
infers the cause from a counter. Links that could not be fetched are reported as
an observation, not as an analysis failure.

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

Website uses one tablist on `/site`: **Overview**, **Pages**, **Architecture**,
**AEO Readiness**, and **Changes**. Pages is the fallback outside the server's
`dashboard` phase; Overview is the fallback in `dashboard`.

Overview reads the backend's persisted measurement projection and presents four
distinct facts: AEO Readiness is quality for classified audited pages, AEO
Measurement Coverage is determinate expected evidence for that cohort,
Classification Coverage is classified / classification-expected supported
HTML, and Crawl Coverage is the selected discovery/acquisition/analysis
boundary. The client never derives one from another or uses classification
coverage to alter the score.

When classification is incomplete, the headline is intrinsically qualified as
**Readiness of classified audited pages**. Classification and measurement
coverage are adjacent, above the fold, and never hidden in a tooltip. Incomplete
crawl coverage adds its own visible audited-pages qualifier and crawl-coverage
line. Any present score renders with its persisted measurement state and
coverage; `limited_evidence` is never an unqualified number. A page whose
persisted kind is `other` renders **Not measured** with no AEO number; the
browser does not append the internal classification reason to that label.

Overview shares the screen's single dashboard poll while a crawl is active and
updates mounted metrics from the persisted `score_summary`. After
terminalization it reads the immutable snapshot. The frontend neither merges
those projections nor creates a second summary owner. The snapshot's seven
dimension rows render persisted labels, family-normalized scores, coverage, and
bounded evidence. Web Fundamentals opens its persisted Accessibility, Mobile,
Security, and Lab HTTP-evidence areas. Browser-rendering checks and field Core
Web Vitals are outside the product measurement surface and are not rendered as
missing or unavailable UI states.

The snapshot retains ten ranked issues while Overview projects five. Technical
defect and AEO-gap cards render separate persisted role-aware counts. The
Overview impact column maps the persisted impact band to **High**, **Medium**,
or **Low** for every row; it never presents a readiness dimension as an impact
label. Advisory bands remain derived from the persisted readiness dimension
and family budget rather than borrowed defect severity. Trend uses only
version- and projection-compatible snapshots. A scored-kind composition change
retains its numeric comparison with reason `cohort_composition_changed`; a
missing classification/scored-cohort projection is non-comparable.

**Pages** retains crawl lifecycle and persisted per-URL metrics. Page and detail
rows consume the server's score, measurement state, classification state, and
reasons without remapping checkpoint outcomes. `other` rows never display a
generic `WebPage` score.

**AEO Readiness** starts at the seven-dimension ledger. Aggregate readiness and
the three coverage projections remain in Overview rather than a duplicate
summary card. Evidence drawers name capability family, checkpoint, observed
evidence, expectation, reason, and remediation; an internal rule ID is
provenance, not primary copy. Content-addressable missing/partial checkpoints
link to Content with stable project/crawl/URL/analysis/family/checkpoint
references, which Content re-authorizes. The client never remaps families,
recomputes score or coverage, guesses outcome buckets, or displays a Combined
score.

The shared response schemas accept exactly `satisfied`, `partial`, `missing`,
`unknown`, `not_applicable`, and `error` as checkpoint outcomes. Unavailable,
ambiguous, and conflicting evidence is displayed from bounded `unknown` reasons,
never invented as an additional outcome bucket.

**Changes** reads only persisted Change Intelligence summary and cursor pages.
It shows the four classes, exact before/after values, analysis provenance, and
an Expected marker only for an exact implementation-event link. Unavailable,
non-comparable, partial, and observed-zero pairs have separate copy. Partial
pairs explicitly state that added/removed URL claims were suppressed; the
browser never computes a diff or turns a neutral/expected change into an action.

The inventory remains mounted and progressive: discovery renders the first ten
persisted rows as they arrive, and rows later receive their analysis status and
scores in place. The Issues workspace renders a compact group list beside one
sticky selected-detail rail. It owns one selected-group query and one
occurrence cursor; filters and catalog pagination remain server-backed.
Persisted remediation is distinct from the failure-specific description. The
shared occurrence presenter renders the same direct evaluation evidence here
and on URL detail, with no per-card query/expansion state and no browser-made
recommendation copy.

During an active recrawl, the first page tab is labelled **Audited so far** and
reads only completed persisted page projections. This prevents the frozen
monitored set from filling the first screen with pending rows before work has
finished; **All Discovered** remains available for the full inventory. Once the
crawl terminalizes, the first tab returns to the complete **Monitored** view.

The Issues surface has separate server-backed **Defects** and **Advisories**
views. Defects are the default and show severity as compact unboxed metadata. Its
headline explicitly counts distinct defect issue types, while supporting
labels name occurrences and affected URLs. Switching views changes the
headline to distinct advisory issue types and labels the supporting quantities
as advisory evidence. Advisory rows are labelled as advisories rather than
borrowing defect severity semantics.
Its rule, search, dimension/severity, finding-class, page-kind, and cursor state
is URL-backed so Overview deep links and browser back/forward restore the same
server query. Filter edits remove the filter-bound cursor, and unrelated query
parameters are preserved.

## Page-kind UX

The API-contract schema owns the page-kind vocabulary. Shared helpers in
`frontend/lib/site-health/page-kinds.ts` provide labels, stable ordering, and a
defensive parser for classifier evidence.

Pages and URL detail show the persisted structural kind. The detail disclosure
may explain the winning signal, schema suggestion, alternatives, conflicts,
confidence, and `other` reason. It never reclassifies in the browser.

Issue groups show affected page kinds as compact unboxed metadata so a
product-schema issue is visibly different from a universal title or delivery issue. Not-applicable evaluations
do not appear as passes or issues. Catalog selection uses `group_id`; affected
rows and URL detail use `occurrence_id` and the occurrence's persisted
`evaluation_id`. The frontend never associates evidence by `rule_id`.

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
| Site Health URL detail | `components/site-health/url-detail.tsx` owns query/rerun control and polling | `url-detail-view.tsx` owns the persisted-detail presentation; `internal-links-card.tsx` owns the link-metric section |
| Site Health architecture | `components/site-health/architecture-panel.tsx` owns the projection query, page-kind rows, and persisted link/depth summaries | — |
| Commerce, prompts, providers, and marketing previews | Existing public panels and dialogs remain their caller-facing owners | small view, cell, topic, preview, and message-bus modules own discrete presentation or local interaction regions |

### Site Health API schemas

`frontend/lib/api/schemas/site-health.ts` is the stable Site Health schema
facade. The public `lib/api/schemas` barrel re-exports that facade, so API
consumers retain their existing import boundary and inferred Zod schema names.
Focused modules under `lib/api/schemas/site-health/` own crawl lifecycle,
dashboard/change/readiness, observed architecture, inventory, issues, page
detail, pagination, and shared schema primitives. Do not import a focused file from a feature solely to
avoid the facade; move a genuinely shared primitive into the focused schema
folder and re-export it through the facade.

### CSV import mechanics

`components/ui/csv-import.tsx` owns the reusable import trigger and dialog
shell, accessible file input, same-file reset/reselection, pending state,
preview framing, and `useCsvImportFile` lifecycle. File text loading,
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
| `/products` | Commerce: Catalog (default), Competitors, Buyer Prompts, AI Shelf |
| `/settings` | Shared workspace/project configuration, including Integrations and Providers |

Commerce AI Shelf requires a product or category target before reading its
persisted projection. The four headline metrics, recommendation evidence, and
immutable measurement history remain bound to that target. Buyer Prompts reuses
the shared audit-launch dialog for target-filtered approved prompt IDs, provider
selection, repetitions, estimates, and launch; Commerce owns no parallel runner.
The Commerce catalog rail is a category tree: products appear beneath their
projected categories, uncategorized products retain an explicit fallback group,
and an opaque sticky search filters both levels without letting scrolled rows
bleed above it. Categories begin collapsed, retain their product counts, and
only categories with projected children render a disclosure control. Category
bulk selection includes every child product without changing the target
currently open in the detail pane.

## Authentication flow

Registration consumes only the generic `RegistrationResponse` acknowledgement
and redirects to `/login?registered=1`. It does not seed the authenticated-user
cache or assume that registration created a session. Login remains the sole
email/password flow that receives a session and performs the account-scoped
cache transition. After the destination is resolved, login crosses the identity
boundary with a full-document navigation so the protected layout reads the new
session cookie and cannot reuse a prefetched anonymous shell.

## Data and query ownership

Each domain has one API module, one query-key owner, and shared schemas/types.
Queries are enabled only when their surface is visible where practical. A
shared artifact uses the same server ID and cache identity everywhere.

Unknown, unavailable, zero, historical, conflicting, excluded, and
not-applicable states retain distinct labels and are never communicated by
color alone.

Authenticated interaction state has three owners. TanStack Query owns server
records and retains prior data during paginated or filtered background work.
`lib/navigation/url-state.ts` owns typed, shareable tabs, filters, cursors, and
selected record IDs with explicit push/replace history. Component-local state
owns only ephemeral drafts and interaction state. The shared UI and motion map
is [`ui-component-system.md`](ui-component-system.md).

Opportunities renders the backend's persisted three-way source mix and coverage,
plus server-filtered Owned and Earned paths. Detail renders a typed Content
handoff with bounded citations, coverage, limitations, suggested skill, and
linked generations; the browser never reclassifies a domain or invents the
handoff. Content seeds the editable task once and preserves user edits on
refetch. Source copy remains observational and never claims that a citation
caused a recommendation.

The Opportunity detail footer owns the explicit **I implemented this** action.
It posts an idempotent declaration with resolved target IDs and expected
checks projected by the server, optionally linking the latest successful
generation. It renders the persisted lifecycle and independent visibility,
AI-referral, and branded-demand verification legs, including unavailable and
non-comparable states. Reloading reads
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
