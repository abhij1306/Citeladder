# Site Health

Site Health is CiteLadder's in-house **on-page + AEO crawler**. It discovers a
project's URLs with a first-party HTTP crawler (no headless browser, no
PageSpeed/CrUX, no raw-HTML storage), analyzes each admitted page against a
deterministic rule catalog, scores it on two dimensions (**Web Fundamentals** and
**AEO**), and surfaces the result as a dashboard, a grouped issues catalog, and a
per-URL detail view. Every persisted row is projected through a workspace-scoped
service layer — the API never re-fetches, re-scores, or fabricates a metric.

This document is the reconciled reference for the feature's **entitlements,
statuses, API surface, exports, and frontend routes**. It matches the code in
`backend/app/api/site_health.py`, `backend/app/core/config/site_health.py`,
`backend/app/analysis/site_health/`, and `frontend/app/(app)/site-health/`.

- Deep worker/analysis internals: `docs/roadmap/technical-audit.md` (original
  design spec) and `docs/backend-architecture.md`.
- Local entitlement granting: `docs/DEVELOPMENT.md` → "Site Health entitlements".
- Design tokens / per-screen layout: `docs/design.md`.

---

## Entitlements & runtime projection

Site Health reads a **projected runtime row** per workspace
(`workspace_site_health_runtime`). The entitlements subsystem resolves the
account's `monitored_urls` grant through the v8 resolver and projects the
result into that row with provenance (`registry_revision`,
`entitlement_lifecycle_version`); Site Health never resolves grants itself and
never stores a plan/capability key. `monitored_urls = 0` means **sample** mode;
any positive allowance means **full** mode. A workspace with no grant
**fail-closes to sample** (the most restrictive mode).

| Access mode | Discovery mode | Discovered total disclosed? | Monitored selection | Analysis scope |
|---|---|---|---|---|
| `sample` | `sample` (deterministic, seeded, read-only) | **No** — the full-site/discovered total is never revealed | Not allowed (a sample set is auto-selected) | The sample set only |
| `full` | `full` (progressive inventory) | Yes | User picks a monitored URL set (quota-limited) | The selected monitored set |

- **Sample behavior.** Sample mode crawls a deterministic, seeded sample and is
  **read-only**: the user cannot pick a monitored set, and no event, crawl
  projection, or export ever leaks a discovered/total/frontier count
  (`count_disclosure = false`). The crawl's admitted (visible) URL count
  is *not* a full-site total and is shown. This non-disclosure is enforced in
  three layers: the runtime projection, the event serializer
  (`redact_event_payload`), and the crawl projection (which nulls
  `discovered_count` / `total_url_count` / `has_more_site_urls`).
- **Full-mode monitored selection.** Full mode runs the full progressive
  inventory. The user selects a monitored URL set via a **full-set, versioned**
  replacement (`PUT /projects/{id}/monitored-urls`). The set is bounded by the
  runtime row's `monitored_url_limit` (workspace-wide, counted under a
  `FOR UPDATE` runtime-row lock). Selecting URLs converts the deterministic
  sample rows to user-managed rows (deactivated rows are never deleted, so
  evidence survives).
- **Granting `monitored_urls` locally:** see `docs/DEVELOPMENT.md`. Grants go
  through the v8 grant services (`app.domain.entitlements.grants`) — plan
  bundles, add-ons, trials, or operator overrides — never a Site
  Health-owned writer. Grant changes re-project the runtime row in the same
  transaction.

`GET /api/v1/entitlements` returns: `workspace_id`, `access_mode`,
`sample_url_limit`, `monitored_url_limit`, `count_disclosure`,
`resolver_status` (`resolved` | `entitlement_unresolved`), `registry_revision`,
`entitlement_lifecycle_version`, `valid_until`, and `contributing_grant_ids`.
There is no `plan_key` and no capability-revision field.

---

## Status vocabulary

All status/vocabulary constants are owned by
`backend/app/core/config/site_health.py` (read from it; do not hardcode).

- **Crawl status** (`CrawlResponse.status`): `draft`, `validating`, `queued`,
  `running`, `completed`, `partially_completed`, `failed`, `cancelled`. The last
  four are terminal.
- **Discovery status**: `pending`, `running`, `completed`, `sample_completed`,
  `failed`, `cancelled`.
- **Analysis status** (crawl-level): `pending`, `running`, `completed`,
  `partially_completed`, `failed`, `cancelled`.
- **Per-page presentation status** (`PageSummary.analysis_status`): the derived,
  mockup-facing status. A raw `failed` page-analysis row is **never** surfaced as
  page copy — it maps to `error` (or `blocked` for a policy denial such as
  robots/SSRF or an exhausted bot block, carrying the error code). Possible
  values: `completed`, `partially_completed`, `pending`, `running`, `error`,
  `blocked`, `cancelled`, `not_selected`.
- **Rule outcome**: `pass`, `fail`, `not_applicable`, `error`.
- **Severity**: `critical`, `high`, `medium`, `low`, `info`.
- **Dimension**: `technical`, `aeo`. `technical` is an internal/API token; all
  user-facing copy calls it **Web Fundamentals**.
- **Page type** (`PageSummary.page_type`, per-URL detail, exports): the
  deterministic classifier's page-type taxonomy is expanded in the canonical
  matrix below. API tokens remain config-owned and stable; legacy categories
  continue to map to the nearest expanded category.
  Assigned at analysis time (config-owned pattern tables +
  `PAGE_TYPE_PROFILES`); always present, `other` when no signal clears the
  confidence threshold. Classifier/classification rationale:
  [`roadmap/site-health-v2-page-aware.md`](roadmap/site-health-v2-page-aware.md).
- **Scores.** Web Fundamentals / AEO / overall scores are `0–100` floats. A missing or
  failed score is **`null`** in the API and renders as an em dash (`—`) in the
  UI — never a fabricated `0`.

---

## Fetching & bot-block classification

Page evidence begins with `SecureFetcher.fetch()` — `httpx`, identifying honestly as the crawler UA
(`CiteLadderSiteHealthBot/1.0`), with the full SSRF posture: manual redirects
revalidated per hop, pinned-IP dial, wire + decoded byte caps, response headers
redacted to the config allowlist, per-host politeness, robots compliance.

When frozen acquisition policy permits it, acquisition is an observable three-rung ladder:
secure `httpx`, then `curl-cffi` for configured block/challenge or low-content evidence,
then server-only ScraperAPI if the preceding rung remains unusable. This is not an evasion
path: robots, SSRF controls, manual redirect validation, TLS verification, host pacing and
byte/time limits apply to every rung. The impersonation profile is configuration and
provenance, never user input; no raw HTML is returned by the API.

Every real network call (every redirect hop) appends one immutable entry to the
fetcher's per-call trace, and the worker persists **one `SiteFetchAttempt` row
per network call** — a failed or blocked call never vanishes. `attempt_number`
stays the queue-attempt number; `request_ordinal` is the deterministic per-call
ordinal (order/uniqueness key `(task_id, attempt_number, request_ordinal)`).
**Only the successful terminal call links the artifact** (a blocked call is an
attempt only, never an artifact generation; the unique one-artifact-per-task
constraint stands).

When a response carries a challenge-platform marker from
`BOT_BLOCK_BODY_MARKERS` (Cloudflare `cf-chl`, DataDome, PerimeterX, …), the
task fails terminally with `ERROR_BOT_BLOCKED` (`bot_blocked`) — distinct from
the generic `http_4xx` so a blocked page presents as **`blocked`** (via
`POLICY_BLOCKING_ERROR_CODES`) instead of `error`. The blocked response is
retained in the per-call trace only and never becomes an analyzable artifact.

Status codes alone are **not** a bot-block signal: a bare `401`/`403`/`503`
keeps its ordinary `http_4xx`/`http_5xx` classification, so a members-only page
or a transient outage is never mislabelled as bot protection.

---

## API surface

All endpoints live under `/api/v1` (no `workspace_id` in the path). The active
workspace is resolved by `require_active_workspace` from the `X-Workspace-Id`
header (or the caller's default workspace) and **every** lookup is filtered by
it, so a foreign/missing id is always a `404` (invariant 5). Keyset (cursor)
pagination is used throughout; a malformed/tampered/scope-mismatched cursor is a
typed `400`, never a `500`.

| Method & path | Purpose |
|---|---|
| `GET /entitlements` | Workspace Site Health entitlement view (fail-closed sample when no `monitored_urls` grant resolves). |
| `POST /site-crawls` | Create + queue a crawl for a project. New project creation also makes this best-effort queue attempt automatically; a crawl failure never rolls back the project. `seed` must be an integer string. `201`; a second active crawl for the project is `409` (`crawl_already_active`); an unusable root is `422` (`invalid_root`); unknown project is `404`. |
| `GET /site-crawls?project_id=&limit=&cursor=` | List crawls (created-at keyset). |
| `GET /site-crawls/{crawl_id}` | Crawl summary/projection (redacted in sample mode). |
| `POST /site-crawls/{crawl_id}/cancel` | Cancel a crawl → `cancelled`. |
| `GET /site-crawls/{crawl_id}/inventory?limit=&cursor=&query=&status=&monitored=&page_type=` | Admitted-URL inventory (selection source of truth). `page_type` filters by the classifier's page type (unknown values are ignored, matching the other filters). |
| `GET /projects/{project_id}/monitored-urls` | Current monitored set + quota + `selection_version`. |
| `PUT /projects/{project_id}/monitored-urls` | Full-set, versioned monitored-set replacement. `403` `monitoring_not_allowed` (sample mode) / `site_health_quota_exceeded`; `409` `stale_selection_version` (carries `current_selection_version`); `422` for unknown URL ids. |
| `GET /site-crawls/{crawl_id}/pages?limit=&cursor=&query=&status=&monitored=&page_type=` | Dashboard page rows (derived `analysis_status` + `error_code`, monitored flag, `page_type`, scores). |
| `GET /site-crawls/{crawl_id}/pages/{site_url_id}` | Per-URL detail (facts, delivery, evaluations, issues, link refs). |
| `GET /site-crawls/{crawl_id}/pages/{site_url_id}/issue-history?limit=&cursor=` | Crawl-bounded issue history for a URL. |
| `GET /site-crawls/{crawl_id}/issues?limit=&cursor=&query=&severity=&category=&dimension=&rule=&site_url_id=&page_type=` | Grouped issues catalog + summary tiles. The grouped-issue wire filter is `rule` (not `rule_id`). `page_type` filters to issues affecting pages of that type. |
| `GET /site-crawls/{crawl_id}/issues/{canonical_id}` | Grouped-issue detail (a non-representative member id canonicalizes to the earliest `(created_at, id)`). |
| `GET /projects/{project_id}/site-health?crawl_id=` | Dashboard projection (defaults to the latest completed crawl). |
| `GET /site-crawls/{crawl_id}/events?stream=` | Event replay (`stream=false`, default → ordered JSON list) or SSE (`stream=true`). Sample-mode payloads are redacted. |
| `GET /site-crawls/{crawl_id}/export.csv?view=` | CSV export. |
| `GET /site-crawls/{crawl_id}/export.md?view=` | Markdown export. |

### Planned value-aware crawl contract

The following contract is staged with the crawler implementation. Until then the
production create route retains its automatic ten-page behavior. The UI must not
send these fields to a backend that does not advertise the versioned contract.

`POST /site-crawls` will accept `input_mode` (`auto`, `exact_urls`, or
`discovery_seeds`), `requested_page_limit`, `seed_urls`, `page_types`, existing
include/exclude globs, and a deterministic seed. `POST /site-crawls/preview`
will accept bounded CSV, text, or JSON URL input and return normalized accepted
rows, duplicates, hard exclusions, out-of-scope rows, safe reason codes, and
row-level validation errors. Exact mode fetches only accepted URLs; seed mode
may expand through admissible links and sitemaps. The creation projection freezes
admission-policy, value-classifier, page-type-classifier, and acquisition-policy
versions, together with the final budget and inputs.

Hard exclusions apply before a task exists and can never be overridden: login,
registration, account/profile, admin, cart, checkout, payment, order
confirmation, wishlist and localized equivalents; search and facet/sort/filter
URLs; tag/author archives, pagination duplicates, feeds, print/share and preview
pages; tracking URLs, attachments, and non-HTML assets. The same admission gate
applies to roots, redirects, links, sitemaps, uploads, recrawls, and manual
selections. Excluded URLs never invoke a transport. Safe aggregate skip counts
and reason codes may be shown, but no sensitive path detail is exposed.

Value order is deterministic: root and explicit selections, products,
comparison/service/local pages, category/pricing, article/guide/FAQ/docs, then
trust and ambiguous pages. This ranking is a scheduling priority, not a claim
that unselected content was fetched.

Advanced URL count, upload, crawl-mode, and page-type controls are development
configuration only. Production remains automatic ten pages. Future Tier 2 may
increase limits; Tier 3 may permit page-type selection; crawl-limit add-ons are
documented only and do not change billing behavior today.

### Page-type and rule-family matrix

Classification is deterministic and uses normalized URL, sitemap hints, visible
content, metadata, structured data, and commerce signals. Each page stores the
winning type, alternatives, confidence, conflicts, and classifier version. A
low-confidence page remains `other` with its bounded reasons. All types receive
crawlability/indexability, AI-crawler-access, metadata, delivery/security,
content-structure, citability/trust, links/media, structured-data presence,
required/recommended-property, and visible/schema-consistency checks when
applicable. Evidence is a bounded URL, header, metadata field, visible excerpt,
or JSON-LD path; remediation is an actionable change, not generated content.

| Page type | Expected schema | Required properties | Recommended properties | Typical severity / remediation |
|---|---|---|---|---|
| Homepage | `Organization`, `WebSite` | name, url | logo, sameAs, SearchAction | High when absent; add authoritative identity/schema and align visible brand data. |
| Product | `Product`, `Offer` | name, brand, offer price/currency/availability | sku, gtin, mpn, image, aggregateRating, shippingDetails, hasMerchantReturnPolicy | Critical for purchasable pages; publish complete offer facts and keep visible values identical. |
| Category/listing | `CollectionPage`, `ItemList` | name, itemListElement | numberOfItems, breadcrumbs | High when listings lack indexable item context; add stable canonical list markup. |
| Service | `Service`, `Organization` | name, provider | areaServed, serviceType, offers | High where a service cannot be identified; state provider, scope, and offer consistently. |
| Local location | `LocalBusiness` | name, address, telephone | geo, openingHours, priceRange, sameAs | Critical for local conversion; reconcile NAP and operating facts. |
| Article | `Article` or `NewsArticle` | headline, author/datePublished | dateModified, image, publisher | Medium; expose byline/date and cite primary sources. |
| Guide/how-to | `HowTo` or `Article` | name/headline, steps where HowTo applies | supplies, tools, totalTime | Medium; use ordered, visible steps and matching markup. |
| Comparison | `Article`, `ItemList` | headline, compared entities | author, dateModified, review evidence | High for unsupported comparisons; disclose criteria and source claims. |
| FAQ | `FAQPage` | mainEntity with question/acceptedAnswer | author/dateModified | Medium; only mark up visible, answerable FAQs. |
| Docs/support | `TechArticle`, `Article`, `WebPage` | headline, description | dateModified, about, breadcrumbs | Medium; make version and support scope explicit. |
| Pricing | `Offer`, `Product` or `Service` | name, price/currency when a price is shown | availability, validThrough, priceSpecification | High; publish unambiguous terms and visible/schema parity. |
| About/contact | `Organization`, `ContactPage` | name, url/contactPoint | logo, sameAs, address | Medium; complete first-party identity and reachable contacts. |
| Case study/review | `Review`, `Article` | itemReviewed or headline, author | reviewRating, datePublished, evidence source | High for unsupported ratings; identify the subject and evidence. |
| Trust/policy | `WebPage` | name/headline | dateModified, publisher | Low/medium; make policy owner, effective date, and linked terms clear. |
| Other | `WebPage` when appropriate | title/canonical/indexability | description, breadcrumbs | Info/medium; classify only after evidence supports a more specific type. |

Rule applicability is profile-owned. A missing `Offer` is not an issue for an
article, and an unavailable rating is not fabricated for a product. Required
property failures are critical/high where the page visibly makes the claim;
recommended-property omissions are medium/low; unavailable evidence is
`not_applicable` or `error`, never a failure. Product parity checks cover SKU/
GTIN/brand, price/currency/availability, variants, ratings, shipping and returns
only when present in visible content or schema. Every rule maps to an opportunity
with page type, evidence, expected schema, missing properties, why it matters,
and remediation.

### Acquisition provenance, guidance, and history

Every append-only attempt records its transport/rung, trigger, validated redirect
chain, configuration versions, and safe error classification. curl-cffi uses
`trust_env=False`, manual redirects, and validated pinned resolution; unsupported
pinned-IP verification disables that rung and continues to ScraperAPI. ScraperAPI
options (including render/premium/geo) come only from frozen server configuration;
the request id and redacted options are provenance. Successful artifacts also
carry the winning transport. Raw HTML remains worker-only Site Health input.

Development-enabled `POST /opportunities/{id}/guidance`, latest, and history
reads produce immutable `OpportunityGuidance` rows. Each stores source IDs,
bounded input snapshot/hash, findings, recommendations, prompt/model/provider
versions, timestamps, and an idempotency key. Regeneration creates a new row;
guidance is unavailable to trial/Tier 1 in production and never changes a rule,
priority, or score. The drawer presents what was found, affected page/type,
bounded evidence, impact, expected schema/missing properties, recommendation,
and collapsed provenance.

Issue history is a persisted-evidence projection grouped by rule: current state,
occurrence count, first/last seen, new/continuing/resolved transition, collapsed
crawl timeline, and a “since previous crawl” summary. It does not repeat one
visually identical row for every crawl and never recrawls to answer history.

### Key crawl-projection fields

`CrawlResponse` aliases model columns to the contract:
`random_seed → seed`, `admitted_url_count → visible_url_count`,
`analyzed_url_count → analyzed_count`, `failed_url_count → failed_count`,
`rule_catalog_version → rule_version`. For a **sample** (non-disclosing) crawl,
`discovered_count`, `total_url_count`, and `has_more_site_urls` are `null`.

`site_facts` (required, nullable — never sample-redacted) is the bounded
site-level blob `_crawl_setup` builds (robots.txt AI-crawler stance, llms.txt
result, sitemap files); the dashboard's **AI crawler access** panel
(`site-facts-panel.tsx`, between the status strip and the per-page-type
scores) renders it and hides itself while it is `null`. Its
`robots.status` classifies the robots.txt fetch (SH-1):
`fetched` / `not_found` (HTTP 404 — the site HAS no robots.txt; crawling
proceeds fail-open and the AI-crawler stance defaults to allow) /
`fetch_failed` (network error / 5xx — the stance is genuinely unknown). The
legacy `robots.fetched` bool stays for back-compat.

`failure_summary` (required, nullable — SH-2/SH-5) explains a **failed** crawl:
`{code, message, attempts, status_code, target_url}`, projected by
`domain/site_health/failure.py` from the root discover task's terminal
`SiteFetchAttempt` rows — a stable machine `code` plus a human `message`
naming the terminal status/attempt count ("The site returned HTTP 500 after 3
attempts"), never a bare `http_4xx` token. The worker writes the same message
onto `SiteCrawl.error_message` at terminalization and records a
**`crawl.failed`** event (payload `{status, failure}`) INSTEAD of the
misleading `crawl.completed`. Single-crawl reads (`GET /site-crawls/{id}`,
cancel, dashboard) carry it; the list projection leaves it `null` (N+1
avoidance). A fully-failed crawl also maps `analysis_status` to `failed`
(SH-3 — an empty plan is only `completed` when the plan was legitimately
empty, e.g. full mode with no monitored selection).

`root_errors` (required array — SH-4) rides the **pages** and **dashboard**
responses: one entry per REAL root-target network call the crawl lost
(`method, target, outcome, error_code, status_code, latency_ms`), empty for
any crawl whose root fetch succeeded (including retried-then-succeeded). The
Errors & Blocked tab renders them as a distinct **non-clickable** block above
the table (`root-errors-block.tsx`) — they are deliberately not page rows (a
root failure never created a `SiteUrl`, so no `site_url_id` and no
PageDetail), they never enter the keyset pagination, and the
`error_or_blocked` filter keeps its real-page semantics.

---

## Exports

CSV (`export.csv`) and Markdown (`export.md`) render the **same
workspace-scoped, already-projected rows** the JSON API returns, so an export can
never leak more than the API. The `view` query parameter selects the projection:

- `inventory` — admitted-URL inventory columns (including `page_type` when the
  row has a completed analysis).
- `pages` — dashboard page columns (status, error code, `page_type`, scores).
- `issues` — grouped issues columns (`page_type` is the comma-joined distinct
  set of affected page types).

Exports are **authenticated blob downloads** (`Content-Disposition: attachment`),
so a selected non-default workspace's `X-Workspace-Id` header is carried (a plain
`<a href>` navigation cannot). CSV/Markdown cells beginning with a
spreadsheet-formula trigger (`=`, `+`, `-`, `@`) are prefixed with `'` to
neutralize formula injection; Markdown cell content is additionally escaped so a
`|` or newline cannot break the table.

---

## Frontend routes

Site Health and Issues are live MVP nav items.

| Route | Screen |
|---|---|
| `/site-health` | The Site Health screen: discovery-in-progress, inventory selection, live analysis, and the completed dashboard (mockups 708 / 709 / 712 / 713). The phase is derived from the crawl + pages queries. |
| `/site-health/crawls/[crawlId]/pages/[siteUrlId]` | Per-URL detail: metadata, Web Fundamentals/AEO/overall score rings (`—` for null), delivery metrics, all issues by severity, and crawl-bounded issue history (mockup 711). |

**Unmeasured delivery timings render `—` (SH-6).** `0` and `null` are both
treated as UI **sentinels for "no usable measurement"**. The fetcher records
whole milliseconds, so a `0` TTFB (or a `0 ms` root-error latency) is almost
always an unmeasured hop — a redirect/no-body hop, a DNS failure that never
reached the wire, or a legacy row. It is *not* proof the hop was never measured:
a genuinely sub-millisecond duration also rounds down to `0`. The tradeoff is
deliberate — rendering `0ms` would advertise impossibly fast delivery far more
often than it would report a real sub-millisecond response — so both collapse to
the placeholder. **Byte counts do not share this rule**: `0 B` is a real,
measured empty body and still renders as a number.
| `/issues` | Grouped Issues catalog: severity/occurrence/affected-page summary tiles, grouped cards with remediation, server-backed search/filter/pagination, and affected-URL navigation (mockup 710). |

Data flow notes:

- **Polling-first.** The screen polls the crawl/pages/dashboard while active. SSE
  (`use-crawl-events.ts`, a credentialed abortable `fetch` reader — not
  `EventSource`, so `X-Workspace-Id` is sent) is only a polling-invalidation
  accelerator; a dropped stream never stops polling.
- **Exports** go through `lib/site-health/download.ts` →
  `apiClient.getBlob` so the workspace header + credentials are carried, and the
  object URL is revoked after download.
- **Selection** commits a full versioned monitored set; a `409`
  `stale_selection_version` surfaces a stale notice and rebases (no silent
  overwrite).
- **Discovered inventory continuity.** A full-mode recrawl freezes a bounded
  newest-first lineage of earlier full-crawl ids in its configuration. The
  inventory and `All Discovered` read models union those immutable observation
  sets while the new crawl re-discovers the site, so starting analysis never
  collapses hundreds of discovered URLs to only the monitored subset. Current
  results stay current-crawl-only; inherited rows link to the source crawl that
  owns their persisted detail. Sample crawls ignore this lineage entirely.

---

## Screen lifecycle & phase precedence

The Site Health route renders one canonical dashboard layout. Its score cards,
compact status row, and inventory stay mounted while their data/mode changes.
`resolveSiteHealthPhase(crawl, plan, hasMonitoredSelection)` in
`frontend/lib/site-health/status.ts` is the single source of truth for those
view modes. Its clauses are mutually exclusive and evaluated in this explicit,
deterministic precedence (top wins):

1. **no crawl** → `empty` (first-run "Start discovery" card).
2. **`completed` / `partially_completed`** → `dashboard`.
3. **`failed` with `analyzed_count === 0` and `score_summary.overall_score`
   null** → `terminal` (SH-2). A fully-failed crawl persists a
   *present-but-null-score* summary (`persist_empty=True`), so the score-data
   probe at clause 4 alone would misroute it to an empty dashboard. Placement
   after clause 2 protects a legitimately `completed` empty-plan crawl — which
   persists the same null-score summary shape — from regressing to `terminal`.
4. **any crawl with `score_summary`** (including `cancelled`/`failed` mid-run) →
   `dashboard`. Score data always outranks the discovering/analyzing sub-states,
   so a landed projection is never hidden behind an active-looking view.
5. **`failed` without data** → `terminal` (explicit stopped card + restart).
6. **`cancelled` without data**: full mode with discovered URLs → `selection`
   (the inventory persists through a cancel and re-seeds the next crawl);
   otherwise → `terminal`.
7. **active full-mode crawl + committed monitored set** → `analyzing`, including
   the interval where re-discovery is running and `analysis_status` still says
   `pending`.
8. **discovery still running** → `discovering`.
9. **analysis running** → `analyzing`.
10. **full mode + analysis pending** → `selection`; otherwise (sample auto-analysis)
   → `analyzing`.

A `failed` crawl's terminal view keeps the tabbed page browser mounted
(`inventoryModeForPhase(phase, crawl)`) so the **Errors & Blocked** tab stays
reachable: it renders the `root_errors` failure block (see below) even though
a root failure never created page rows.

### Cancellation with partial data

When a run is cancelled after it produced scores, the product keeps the **latest
dashboard, partial scores, and URL inventory visible**, explicitly labels the run
**Cancelled** (a text-labelled badge + notice, never color alone —
`dashboardRunNotice` in `status.ts`), and offers **Re-crawl**. The same
notice covers `partially_completed` (Partial) and `failed`-with-data. A cancel
that produced *no* data routes to `selection` (full mode, inventory survives) or
`terminal`.

### Retaining content during transitions

- **Cancelling** (cancel request in flight): the discovery/analysis views keep
  their inventory and counts on screen and swap the status line to an
  `aria-live` "Cancelling…" message — nothing is torn down mid-request.
- **Re-crawl starting** (`recrawlStarting` in `use-site-health-screen.ts`): the
  prior dashboard/selection stays in view behind an info notice until the new
  crawl's first projection takes over.
- **Recrawl** re-seeds from the committed monitored set — a fresh crawl
  re-discovers and enqueues the persisted selection (a cancelled crawl cannot
  enqueue analyze tasks itself). Its `All Discovered` tab retains the earlier
  full inventory until re-discovery refreshes those URL observations.

### Count integrity during loading

The live analysis counters come from server-side aggregates
(`analyzed_count` / `failed_count`) and the per-project monitored count, never
from the bounded page window. Until the selected total is known (no terminal
`score_summary` **and** the monitored count has not resolved), **Total pages**
and **Queued** render `—` rather than a misleading `0`. A failed monitored-count
fetch is surfaced as a warning (`projectSelectedError`) instead of silently
approximating or disabling actions. Missing scores always render `—`, never a
fabricated zero.

The same server-backed Monitored / All Discovered / Errors table renders during
analysis and after completion. Its first cursor page polls while active, so row
statuses and scores fill in without swapping to a separate results screen.

Sample-mode non-disclosure is preserved across every state: no phase leaks a
discovered/full-site total, and sample-mode discovery never implies continued
full-site scanning.

---

## Guardrails (for anyone extending Site Health)

- Keep workspace resolution on `require_active_workspace`; a foreign/missing id
  must be an indistinguishable `404`.
- Preserve sample-mode count/event/export **non-disclosure** (never leak a
  discovered/full-site total).
- Keep inherited inventory ids as read-scope references only. Never manufacture
  a `SiteUrlObservation` or copy old analysis into a new crawl.
- Read status/severity/dimension/limits/error tokens from
  `app/core/config/site_health.py`; never hardcode them.
- No raw-HTML storage, no PageSpeed/CrUX, no headless browser.
- The service layer only **projects persisted rows** — it never re-fetches or
  re-scores.
